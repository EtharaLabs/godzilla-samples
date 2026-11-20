"""Bun data APIs: Bun.hash (wyhash, CityHash, xxHash, Murmur, rapidhash, crc32/adler32),
Bun.CryptoHasher and the SHA classes, Bun.password (bcrypt + Argon2 PHC strings), bun:sqlite over the
system libsqlite3, and bun:ffi (dlopen of libc/libm, pointers, CString, read.*, JSCallback, cc).

Hash values are checked against the oracle Bun itself produced (Bun 1.2.21, inputs
`(i*31+7) & 0xff`) and against the system libxxhash for lengths the oracle does not cover; bcrypt
hashes come from the system crypt(3); Argon2 tags are the RFC 9106 vectors. SQLite and FFI tests are
skipped when the system library they need cannot be loaded; no pointer value is ever printed.
"""

import shutil

import pytest

from conftest import build_addon, err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]


def skip_without_sqlite(r):
    """bun:sqlite dlopens the system libsqlite3 lazily; skip when this machine has none."""
    if "bun:sqlite unavailable" in err(r):
        pytest.skip("system libsqlite3 is not available")


def skip_without_library(r, soname):
    """bun:ffi tests dlopen glibc sonames; skip on systems where they do not exist."""
    if f"cannot open library '{soname}'" in err(r):
        pytest.skip(f"{soname} is not available")


ORACLE_JS = r"""
const NUM = new Set(["cityHash32", "xxHash32", "murmur32v3", "murmur32v2", "crc32", "adler32"]);
function pat(n) { const b = new Uint8Array(n); for (let i = 0; i < n; i++) b[i] = (i * 31 + 7) & 0xff; return b; }
const lens = [0, 1, 2, 3, 4, 5, 7, 8, 9, 12, 13, 15, 16, 17, 24, 25, 31, 32, 33, 48, 49, 63, 64, 65, 96, 97, 100, 112, 127, 128, 129, 130, 1024];
const seeds = [0n, 1n, 0xdeadbeefn, 0x8000000000000000n, 0xffffffffffffffffn];
const u64hex = (v) => BigInt.asUintN(64, BigInt(v)).toString(16).padStart(16, "0");
const u32hex = (v) => (BigInt(v) & 0xffffffffn).toString(16).padStart(8, "0");
const inputs = lens.map(pat);
for (const fam of FAMILIES) for (const s of seeds) {
  const arg = s <= 0xdeadbeefn ? Number(s) : s;
  const fn = fam === "default" ? Bun.hash : Bun.hash[fam];
  const row = inputs.map((b) => { const v = fn(b, arg); return NUM.has(fam) ? u32hex(v) : u64hex(v); });
  console.log(fam + "|" + u64hex(s) + "|" + row.join(","));
}
"""


# -------------------------------------------------------------------------------------- Bun.hash
def test_bun_hash_64bit_families_match_bun_oracle(js, golden):
    """CATCHES: any deviation from Bun's 64-bit hashes (wyhash = Bun.hash, CityHash64, XXH64, XXH3,
    Murmur64A, rapidhash) at the length-branch boundaries from 0 to 130 bytes and at 1024, or
    wrong u64 seed handling for seeds 0, 1, 0xdeadbeef and the BigInt seeds 2^63 and 2^64-1."""
    families = '["default", "wyhash", "cityHash64", "xxHash64", "xxHash3", "murmur64v2", "rapidhash"]'
    r = js(f"const FAMILIES = {families};\n" + ORACLE_JS)
    assert out(r) == golden("bun_hash_64bit_families_match_bun_oracle")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_bun_hash_32bit_families_match_bun_oracle(js, golden, tier):
    """CATCHES: wrong 32-bit hash results (CityHash32, XXH32, MurmurHash3_x86_32, MurmurHash2,
    crc32, adler32) at tail/block boundaries, a seed not truncated to 32 bits, or cityHash32/crc32/
    adler32 not ignoring the seed, compared with Bun's oracle under all tiers."""
    families = '["cityHash32", "xxHash32", "murmur32v3", "murmur32v2", "crc32", "adler32"]'
    r = js(f"const FAMILIES = {families};\n" + ORACLE_JS, *tier)
    assert out(r) == golden("bun_hash_32bit_families_match_bun_oracle")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bun_hash_long_inputs(js, golden):
    """CATCHES: XXH3 bugs in the 129-240 byte mid-size path and in the long-input stripe/scramble
    loop (checked against libxxhash), and long-input bugs in every other family on a 64 KiB input
    (checked against Bun's oracle)."""
    code = r"""
function pat(n) { const b = new Uint8Array(n); for (let i = 0; i < n; i++) b[i] = (i * 31 + 7) & 0xff; return b; }
const hex = (v) => BigInt.asUintN(64, BigInt(v)).toString(16);
for (const n of [144, 160, 200, 240, 241, 1025, 2048, 5000]) {
  const b = pat(n);
  console.log("xxHash3", n, hex(Bun.hash.xxHash3(b)), hex(Bun.hash.xxHash3(b, 1)), hex(Bun.hash.xxHash64(b)), Bun.hash.xxHash32(b).toString(16));
}
const k64 = new Uint8Array(65536);
for (let off = 0; off < 65536; off += 256) k64.set(pat(256), off); // the pattern has period 256
for (const fam of ["wyhash", "cityHash64", "xxHash64", "xxHash3", "murmur64v2", "rapidhash", "cityHash32", "xxHash32", "murmur32v3", "murmur32v2", "crc32", "adler32"]) {
  console.log(fam, hex(Bun.hash[fam](k64)), hex(Bun.hash[fam](k64, 0xdeadbeef)));
}
"""
    r = js(code)
    assert out(r) == golden("bun_hash_long_inputs")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bun_hash_input_and_seed_coercion(js, golden):
    """CATCHES: Bun.hash input coercion bugs (no argument vs "", ArrayBuffer, DataView and
    TypedArray sub-views hashed by their bytes, numbers/null/objects hashed via String()) and seed
    coercion bugs (int32 sign extension, the 2^51 cutoff, non-integers and strings as 0, BigInt mod 2^64)."""
    code = r"""
const H = Bun.hash;
const show = (v) => typeof v === "bigint" ? v.toString(16) + "n" : v.toString(16);
console.log(show(H()), H() === H(""), H("") === H(new Uint8Array(0)));
console.log(show(H("hello")), H(Buffer.from("hello")) === H("hello"), H(new TextEncoder().encode("hello").buffer) === H("hello"),
  H(new DataView(Buffer.from("xhellox").buffer, 1, 5)) === H("hello"), H(new Uint8Array(new Uint16Array([0x6568, 0x6c6c, 0x006f]).buffer, 0, 5)) === H("hello"));
console.log(H(12345) === H("12345"), H(null) === H("null"), H(undefined) === H("undefined"), H({}) === H("[object Object]"), H("é") === H(Buffer.from([0xc3, 0xa9])));
for (const seed of [0, 1, -1, -5, 2 ** 31, 2 ** 32, 2 ** 51 - 1, 2 ** 51, 1.5, NaN, Infinity, "7", 7n, -1n, 2n ** 64n + 3n, 2n ** 70n]) {
  const label = typeof seed === "bigint" ? seed + "n" : typeof seed === "string" ? JSON.stringify(seed) : String(seed);
  console.log(label, show(H.wyhash("seeded", seed)), show(H.xxHash32("seeded", seed)), show(H.xxHash3("seeded", seed)), show(H.murmur32v3("seeded", seed)));
}
console.log(H.cityHash32("abc", 1) === H.cityHash32("abc"), H.crc32("abc", 5) === H.crc32("abc"), H.adler32("abc", 5) === H.adler32("abc"), H("abc", 3) === H.wyhash("abc", 3));
console.log(typeof H.wyhash("a"), typeof H.cityHash32("a"), typeof H.xxHash32("a"), typeof H.rapidhash("a"), typeof H.murmur64v2("a"), typeof H.adler32("a"));
"""
    r = js(code)
    assert out(r) == golden("bun_hash_input_and_seed_coercion")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bun_cryptohasher_and_sha_classes(js, golden):
    """CATCHES: Bun.CryptoHasher/Bun.SHA*/Bun.MD5/Bun.sha returning wrong digests or types (hex/base64
    strings vs Uint8Array), not chaining update(), ignoring the HMAC key argument, a wrong algorithms
    list, or silently accepting algorithms lumen cannot compute."""
    code = r"""
const h = new Bun.CryptoHasher("sha256");
h.update("hello ").update(Buffer.from("world"));
console.log(h.algorithm, h.digest("hex"));
const h2 = new Bun.CryptoHasher("sha512-256", "secret-key");
h2.update(new Uint8Array([1, 2, 3]));
const d2 = h2.digest();
console.log(d2.constructor.name, d2.length, Buffer.from(d2).toString("hex"));
const hm = new Bun.CryptoHasher("sha256", "key");
console.log(hm.update("The quick brown fox jumps over the lazy dog").digest("base64"));
console.log(Bun.CryptoHasher.hash("md5", "abc", "hex"), Buffer.from(Bun.CryptoHasher.hash("sha1", new TextEncoder().encode("abc"))).toString("base64"));
console.log(Bun.CryptoHasher.algorithms.join(","));
console.log(Bun.sha("abc", "hex"), Bun.sha("abc").constructor.name);
console.log(Bun.MD5.hash("abc", "hex"), new Bun.SHA1().update("abc").digest("hex"), Bun.SHA256.hash("abc", "base64"));
console.log(Bun.SHA384.hash("", "hex"), Buffer.from(Bun.SHA512.hash("abc")).subarray(0, 8).toString("hex"), new Bun.SHA512_256().update("a").update("bc").digest("hex"));
for (const f of [() => new Bun.CryptoHasher("sha3-256"), () => Bun.SHA224.hash("abc"), () => new Bun.MD4()]) {
  try { f(); console.log("accepted"); } catch (e) { console.log(e.name, e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("bun_cryptohasher_and_sha_classes")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------------- Bun.password
def test_bun_password_verify_bcrypt_reference_hashes(js, golden):
    """CATCHES: bcrypt verification bugs against OpenBSD/crypt(3) hashes: the $2a$/$2b$/$2y$ prefixes,
    costs 4 and 5, empty and non-ASCII passwords, the 72-byte key limit, Bun's SHA-512 pre-hash of
    longer passwords (so a 73-byte password must NOT match a plain bcrypt hash), and wrong passwords."""
    code = r"""
const cases = [
  ["U*U", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"],
  ["U*U*", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.VGOzA784oUp/Z0DY336zx7pLYAy0lwK"],
  ["U*U*U", "$2a$05$XXXXXXXXXXXXXXXXXXXXXOAcXxm9kjPGEMsLznoKqmqw7tc8WCx4a"],
  ["", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.7uG0VCzI2bS7j6ymqJi9CdcdxiRTWNy"],
  ["U*U", "$2b$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"],
  ["U*V", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"],
  ["hunter2", "$2b$04$abcdefghijklmnopqrstuuV3duMsC0HpUex6N9qapiuOHHWkwRXVm"],
  ["Hunter2", "$2b$04$abcdefghijklmnopqrstuuV3duMsC0HpUex6N9qapiuOHHWkwRXVm"],
  ["pässwörd", "$2b$05$/././././././././././.zLJvdmu/5jC9goZthN.SdPoqBP9uJpK"],
  ["", "$2y$04$ZZZZZZZZZZZZZZZZZZZZZu0ZYQLgwmUVIal.15laxyN/aOWwPvFSG"],
  ["x".repeat(72), "$2b$04$0123456789ABCDEFGHIJKuLYxWbTZrA9pRJwWQhpUTe0V4dxPp6gW"],
  ["x".repeat(73), "$2b$04$0123456789ABCDEFGHIJKuLYxWbTZrA9pRJwWQhpUTe0V4dxPp6gW"],
];
for (const [pw, hash] of cases) console.log(JSON.stringify(pw.length > 20 ? pw.length + " bytes" : pw), hash.slice(0, 7), Bun.password.verifySync(pw, hash));
const long = "y".repeat(100);
const h = Bun.password.hashSync(long, { algorithm: "bcrypt", cost: 4 });
const digest = require("crypto").createHash("sha512").update(long).digest();
console.log(Bun.password.verifySync(long, h), Bun.password.verifySync(digest, h), Bun.password.verifySync("y".repeat(99), h));
"""
    r = js(code)
    assert out(r) == golden("bun_password_verify_bcrypt_reference_hashes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bun_password_verify_argon2_phc_strings(js, golden):
    """CATCHES: Argon2 PHC verification bugs: decoding unpadded base64 salt/tag, honouring m/t/p,
    the variant and an explicit or omitted v=19, tags of any length, and rejecting each kind of
    malformed PHC string with Bun's exact InvalidEncoding/UnsupportedAlgorithm errors."""
    code = r"""
const crypto = require("crypto");
const b64 = (b) => Buffer.from(b).toString("base64").replace(/=+$/, "");
const salt = Buffer.from("0123456789abcdef");
const phc = (alg, m, t, p, tag, ver = "v=19$") => `$${alg}$${ver}m=${m},t=${t},p=${p}$${b64(salt)}$${b64(tag)}`;
for (const [alg, m, t, p, len] of [["argon2id", 64, 1, 1, 32], ["argon2i", 32, 2, 1, 16], ["argon2d", 64, 1, 2, 24], ["argon2id", 16, 3, 1, 4]]) {
  const tag = crypto.argon2Sync(alg, { message: "correct horse", nonce: salt, parallelism: p, tagLength: len, memory: Math.max(m, 8 * p), passes: t });
  const s = phc(alg, m, t, p, tag);
  console.log(s.split("$").slice(1, 4).join("$"), tag.length, Bun.password.verifySync("correct horse", s), Bun.password.verifySync("correct horsf", s),
    Bun.password.verifySync("correct horse", phc(alg, m, t, p, tag, "")));
}
const tag = crypto.argon2Sync("argon2id", { message: "pw", nonce: salt, parallelism: 1, tagLength: 32, memory: 64, passes: 1 });
const good = phc("argon2id", 64, 1, 1, tag);
const bad = {
  "no leading $": good.slice(1), "unknown variant": good.replace("argon2id", "argon2x"), "version 18": good.replace("v=19", "v=18"),
  "bad key": good.replace("t=1", "q=1"), "zero memory": good.replace("m=64", "m=0"), "missing p": good.replace(",p=1", ""),
  "bad base64": good.slice(0, -4) + "!!!!", "short tag": phc("argon2id", 64, 1, 1, Buffer.from("abc")), "extra field": good + "$x",
  "not a number": good.replace("m=64", "m=abc"), "bcrypt too short": "$2b$04$short", "bcrypt bad cost": "$2b$99$abcdefghijklmnopqrstuuV3duMsC0HpUex6N9qapiuOHHWkwRXVm",
  "unknown scheme": "$5$rounds=5000$salt$hash", "plain text": "hunter2", "salt length 5": good.replace(b64(salt), "AAAAA"),
};
console.log(Bun.password.verifySync("pw", good), Bun.password.verifySync(Buffer.from("pw"), good));
for (const [label, s] of Object.entries(bad)) {
  try { console.log(label, Bun.password.verifySync("pw", s)); } catch (e) { console.log(label, e.name, e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("bun_password_verify_argon2_phc_strings")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bun_password_hash_formats_and_option_errors(js, golden):
    """CATCHES: Bun.password.hashSync emitting the wrong PHC/$2b$ layout (variant, v=19, recorded m/t/p,
    salt/tag lengths, cost digits), hashes that do not verify, inputs as bytes, and missing exact
    TypeError/RangeError messages for unknown algorithms and out-of-range costs."""
    code = r"""
const shape = (h) => h.replace(/\$[A-Za-z0-9+/]{43}\$[A-Za-z0-9+/]{43}$/, "$<salt43>$<tag43>").replace(/^(\$2b\$\d\d\$)[./A-Za-z0-9]{53}$/, "$1<53>");
const opts = [{ algorithm: "bcrypt", cost: 4 }, { algorithm: "argon2id", memoryCost: 64, timeCost: 1 }, { algorithm: "ARGON2I", memoryCost: 32, timeCost: 2 },
  { algorithm: "argon2d", memoryCost: 1, timeCost: 1 }, "bcrypt"];
for (const o of opts) {
  const pw = typeof o === "string" ? new Uint8Array([0, 1, 2, 255]) : "s3cret pässword";
  const opt = typeof o === "string" ? { algorithm: o, cost: 5 } : o;
  const h = Bun.password.hashSync(pw, opt);
  console.log(shape(h), Bun.password.verifySync(pw, h), Bun.password.verifySync("other", h));
}
const a = Bun.password.hashSync("x", { algorithm: "argon2id", memoryCost: 8, timeCost: 1 });
const b = Bun.password.hashSync("x", { algorithm: "argon2id", memoryCost: 8, timeCost: 1 });
console.log("salted", a !== b, Bun.password.verifySync("x", a), Bun.password.verifySync("x", b));
const bad = [[{ algorithm: "scrypt" }], ["md5"], [5], [null], [{ algorithm: "bcrypt", cost: 3 }], [{ algorithm: "bcrypt", cost: 32 }],
  [{ algorithm: "bcrypt", cost: 4.5 }], [{ algorithm: "argon2id", memoryCost: 0 }], [{ algorithm: "argon2i", timeCost: -1 }], [{ algorithm: "argon2d", timeCost: "2" }]];
for (const [o] of bad) {
  try { Bun.password.hashSync("x", o); console.log("accepted", JSON.stringify(o)); } catch (e) { console.log(JSON.stringify(o), e.name, e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("bun_password_hash_formats_and_option_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bun_password_async_promises(js, golden):
    """CATCHES: async Bun.password.hash/verify that resolve synchronously or with the wrong value, run
    on the wrong options, or resolve instead of rejecting for invalid options, bad hash strings and
    unknown schemes (exact rejection messages, in a sequential chain)."""
    code = r"""
(async () => {
  const p = Bun.password.hash("async pw", { algorithm: "argon2i", memoryCost: 16, timeCost: 1 });
  console.log(p instanceof Promise);
  const h = await p;
  console.log(h.split("$").slice(0, 4).join("$"), await Bun.password.verify("async pw", h), await Bun.password.verify("async pW", h));
  const bc = await Bun.password.hash(new TextEncoder().encode("bytes pw"), { algorithm: "bcrypt", cost: 4 });
  console.log(bc.slice(0, 7), bc.length, await Bun.password.verify("bytes pw", bc));
  console.log(await Bun.password.verify("hunter2", "$2b$04$abcdefghijklmnopqrstuuV3duMsC0HpUex6N9qapiuOHHWkwRXVm"));
  for (const f of [() => Bun.password.hash("pw", "md5"), () => Bun.password.hash("pw", { algorithm: "bcrypt", cost: 40 }),
    () => Bun.password.verify("pw", "garbage"), () => Bun.password.verify("pw", "$argon2id$v=19$m=8,t=1,p=1$$")]) {
    try { console.log("resolved", await f()); } catch (e) { console.log("rejected", e.name, e.message); }
  }
})();
"""
    r = js(code)
    assert out(r) == golden("bun_password_async_promises")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------- bun:sqlite
def test_sqlite_crud_and_column_types(js, golden):
    """CATCHES: wrong bun:sqlite type mapping (INTEGER/REAL/TEXT/BLOB/NULL to number/string/
    Uint8Array/null), broken prepared-statement reuse, wrong run() results (changes and
    lastInsertRowid), and get()/all()/values() returning the wrong shapes or row order."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database(":memory:");
db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL, score REAL, data BLOB, flag INTEGER)");
const ins = db.prepare("INSERT INTO t (name, score, data, flag) VALUES (?, ?, ?, ?)");
console.log(JSON.stringify(ins.run("alice", 1.5, new Uint8Array([1, 2, 3]), true)));
console.log(JSON.stringify(ins.run("bob", 2, null, false)));
console.log(JSON.stringify(ins.run("carol", -0.25, Buffer.from("xyz"), 7n)));
const rows = db.query("SELECT id, name, score, typeof(score) AS ts, flag, typeof(flag) AS tf, data FROM t ORDER BY id").all();
for (const r of rows) console.log(r.id, r.name, r.score, r.ts, r.flag, r.tf, r.data === null ? "null" : r.data.constructor.name + "[" + Array.from(r.data) + "]");
console.log(JSON.stringify(db.query("SELECT name FROM t WHERE id > ? ORDER BY id").values(1)));
console.log(JSON.stringify(db.query("SELECT name FROM t WHERE id = ?").get(2)), db.query("SELECT name FROM t WHERE id = ?").get(99));
console.log(JSON.stringify(db.query("SELECT count(*) AS n, sum(score) AS s, max(name) AS m FROM t").get()));
console.log(JSON.stringify(db.prepare("UPDATE t SET score = score * 2 WHERE score > ?").run(0)));
console.log(JSON.stringify(db.query("SELECT group_concat(score, '|') AS g FROM t").get()));
console.log(JSON.stringify(db.query("SELECT 1 AS a, 'two' AS b, 3.5 AS c, NULL AS d, x'00ff' AS e").values()[0].map((v) => v instanceof Uint8Array ? Array.from(v) : v)));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_crud_and_column_types")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_parameter_binding_forms(js, golden):
    """CATCHES: parameter binding bugs: positional varargs vs a single array, ?NNN reuse, the
    $/:/@ prefixes in non-strict mode (bare keys must not bind), strict mode binding bare names and
    throwing for missing ones, count mismatches, and parameterless statements ignoring arguments."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database();
const show = (label, f) => { try { console.log(label, JSON.stringify(f())); } catch (e) { console.log(label, e.name, e.message); } };
show("varargs", () => db.query("SELECT ? AS a, ? AS b").get("p", "q"));
show("array", () => db.query("SELECT ? AS a, ? AS b").get(["p", "q"]));
show("numbered", () => db.query("SELECT ?2 || ?1 AS a, ?2 AS b").get("x", "y"));
show("prefixed", () => db.query("SELECT :x AS a, @y AS b, $z AS c").get({ ":x": 1, "@y": 2, $z: 3 }));
show("bare non-strict", () => db.query("SELECT $a AS a, @b AS b").get({ a: 1, "@b": 2 }));
show("mixed", () => db.query("SELECT $a AS a, ? AS b").get({ $a: 5 }));
show("too few", () => db.query("SELECT ?, ?").get(1));
show("too many", () => db.query("SELECT ?").all(1, 2));
show("no params", () => db.query("SELECT 42 AS answer").get("ignored", 1));
const strict = new Database(":memory:", { strict: true });
show("strict bare", () => strict.query("SELECT $a + :b + @c AS s").get({ a: 1, b: 2, c: 3 }));
show("strict prefixed key", () => strict.query("SELECT $a AS s").get({ $a: 1 }));
show("strict missing", () => strict.query("SELECT $a AS s, $b AS t").get({ a: 1 }));
const reuse = db.query("SELECT ? AS v");
show("bound", () => reuse.get("first"));
show("reused", () => reuse.get());
show("toString", () => reuse.toString());
show("rebound", () => reuse.all(["second"]));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_parameter_binding_forms")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_integer_real_boundaries_and_safe_integers(js, golden):
    """CATCHES: wrong number binding (integers only inside [-2^51, 2^51), -0/fractions/±Infinity as
    REAL, NaN as NULL), booleans/BigInts bound wrongly, and safeIntegers on the database or a single
    statement not returning BigInt (including lastInsertRowid) while plain mode loses precision."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database();
const q = db.query("SELECT ?1 AS v, typeof(?1) AS t");
const cases = [["0", 0], ["1", 1], ["-1", -1], ["2^50", 2 ** 50], ["2^51", 2 ** 51], ["-2^51", -(2 ** 51)], ["-2^51-2", -(2 ** 51) - 2],
  ["-0", -0], ["1.5", 1.5], ["NaN", NaN], ["Infinity", Infinity], ["-Infinity", -Infinity], ["true", true], ["false", false],
  ["null", null], ["undefined", undefined], ["2^53+1n", 9007199254740993n], ["i64min", -9223372036854775808n], ["i64max", 9223372036854775807n],
  ["str", "str"], ["empty", ""], ["u8[]", new Uint8Array(0)], ["u8[1,2]", new Uint8Array([1, 2])]];
for (const [label, v] of cases) {
  const r = q.get(v);
  const shown = r.v instanceof Uint8Array ? "u8[" + Array.from(r.v) + "]" : Object.is(r.v, -0) ? "-0" : typeof r.v === "number" ? String(r.v) : JSON.stringify(r.v);
  console.log(label, "->", shown, r.t);
}
const s = db.query("SELECT 9223372036854775807 AS big, 5 AS small, 1.5 AS r");
console.log(JSON.stringify(s.get()));
const g = s.safeIntegers().get();
console.log(typeof g.big, g.big, typeof g.small, g.small, typeof g.r, typeof s.safeIntegers(false).get().small);
const sdb = new Database(":memory:", { safeIntegers: true });
sdb.run("CREATE TABLE t (x)");
const r = sdb.query("INSERT INTO t VALUES (?)").run(9007199254740993n);
console.log(typeof r.lastInsertRowid, r.lastInsertRowid, typeof sdb.run("INSERT INTO t VALUES (2)").lastInsertRowid, sdb.query("SELECT x FROM t ORDER BY rowid").values().map(([x]) => typeof x + ":" + x).join());
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_integer_real_boundaries_and_safe_integers")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_transactions_and_savepoints(js, golden):
    """CATCHES: db.transaction() wrappers that do not commit, do not roll back on throw (CHECK failure
    mid-transfer), roll back the outer transaction when an inner nested one fails (must be a
    savepoint), lose return values/arguments, or lack the deferred/immediate/exclusive variants."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database();
db.exec("CREATE TABLE acct (name TEXT PRIMARY KEY, bal INTEGER NOT NULL CHECK (bal >= 0))");
const ins = db.prepare("INSERT INTO acct VALUES (?, ?)");
const insertMany = db.transaction((rows) => { for (const r of rows) ins.run(...r); return rows.length; });
console.log("inserted", insertMany([["a", 10], ["b", 20], ["c", 30]]));
const move = db.transaction(function (from, to, amt) {
  db.prepare("UPDATE acct SET bal = bal + ? WHERE name = ?").run(amt, to);
  db.prepare("UPDATE acct SET bal = bal - ? WHERE name = ?").run(amt, from);
  return this && this.tag;
});
console.log("moved", move.call({ tag: "ctx" }, "a", "b", 5));
try { move("a", "c", 50); } catch (e) { console.log("rolled back:", e.message); }
console.log(JSON.stringify(db.query("SELECT * FROM acct ORDER BY name").all()));
const outer = db.transaction(() => {
  ins.run("d", 1);
  try { db.transaction(() => { ins.run("e", 2); throw new Error("inner fail"); })(); } catch (e) { console.log("inner:", e.message); }
  db.transaction(() => ins.run("f", 3))();
  return "outer done";
});
console.log(outer(), JSON.stringify(db.query("SELECT name FROM acct ORDER BY name").values().flat()));
try { db.transaction(() => { ins.run("g", 1); throw new TypeError("outer fail"); })(); } catch (e) { console.log(e.name, e.message, db.query("SELECT count(*) AS n FROM acct").get().n); }
const v = db.transaction((x) => x * 2);
console.log(typeof v.deferred, v.deferred(1), v.immediate(2), v.exclusive(3), v(4));
try { db.transaction(5); } catch (e) { console.log(e.name, e.message); }
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_transactions_and_savepoints")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_constraint_and_syntax_errors(js, golden):
    """CATCHES: engine failures not surfaced as SQLiteError (an Error subclass named "SQLiteError")
    with SQLite's message, extended errno and code name: syntax errors and missing tables (errno 1,
    no code), UNIQUE/NOT NULL/CHECK/PRIMARY KEY/FOREIGN KEY constraint codes."""
    code = r"""
const { Database, SQLiteError } = require("bun:sqlite");
const db = new Database();
db.exec("PRAGMA foreign_keys = ON; CREATE TABLE p (id INTEGER PRIMARY KEY); CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, n INTEGER CHECK (n >= 0), pid INTEGER REFERENCES p(id))");
db.run("INSERT INTO p VALUES (1)");
const ins = db.prepare("INSERT INTO t (id, name, n, pid) VALUES (?, ?, ?, ?)");
ins.run(1, "a", 1, 1);
const t = (label, f) => {
  try { console.log(label, "OK", JSON.stringify(f())); }
  catch (e) { console.log(label, e instanceof SQLiteError, e instanceof Error, e.name, JSON.stringify(e.code), e.errno, e.message); }
};
t("syntax", () => db.run("SELEC 1"));
t("prepare syntax", () => db.prepare("SELECT FROM WHERE"));
t("no table", () => db.query("SELECT * FROM nope").all());
t("no column", () => db.query("SELECT missing FROM t").all());
t("unique", () => ins.run(2, "a", 1, 1));
t("not null", () => ins.run(3, null, 1, 1));
t("check", () => ins.run(4, "d", -1, 1));
t("primary key", () => ins.run(1, "e", 1, 1));
t("foreign key", () => ins.run(5, "f", 1, 9));
t("exec multi", () => db.exec("INSERT INTO t (id, name) VALUES (10, 'z'); INSERT INTO t (id, name) VALUES (11, 'z')"));
t("after", () => db.query("SELECT count(*) AS n FROM t").get());
t("construct", () => new SQLiteError("x"));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_constraint_and_syntax_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_api_misuse_errors(js, golden):
    """CATCHES: missing exact errors for API misuse: unbindable values (objects, symbols), an empty
    statement, use after close (RangeError for query/prepare, Error for run), a finalized statement,
    double close, constructing Statement directly, and a non-function transaction."""
    code = r"""
const { Database, Statement } = require("bun:sqlite");
const db = new Database();
const t = (label, f) => { try { console.log(label, "OK", JSON.stringify(f())); } catch (e) { console.log(label, e.name, e.message); } };
t("object param", () => db.query("SELECT ? AS v").get([{}]));
t("symbol param", () => db.query("SELECT ? AS v").get(Symbol("s")));
t("function param", () => db.query("SELECT ? AS v").get(() => 1));
t("empty sql", () => db.prepare("   -- only a comment"));
const st = db.prepare("SELECT 1 AS one");
st.finalize(); st.finalize();
t("finalized all", () => st.all());
t("finalized toString", () => st.toString());
t("statement ctor", () => new Statement());
const q = db.query("SELECT 2 AS two");
db.close(); db.close();
t("closed query", () => db.query("SELECT 1"));
t("closed prepare", () => db.prepare("SELECT 1"));
t("closed run", () => db.run("SELECT 1"));
t("closed serialize", () => db.serialize());
t("cached statement", () => q.get());
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_api_misuse_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_statement_metadata_iteration_and_cache(js, golden):
    """CATCHES: Statement metadata/iteration bugs: query() cache identity vs prepare(), columnNames
    and paramsCount, toString() with expanded bindings, iterate()/for-of (including early break and
    reuse of the last bindings), and .as(Class) mapping rows onto a prototype."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database();
db.exec("CREATE TABLE n (v INTEGER, label TEXT); INSERT INTO n VALUES (1, 'one'), (2, 'two'), (3, 'three'), (4, 'four')");
const sql = "SELECT v, label FROM n WHERE v > $min ORDER BY v";
const q = db.query(sql);
console.log(q === db.query(sql), db.prepare(sql) === db.prepare(sql), q.columnNames.join(), q.paramsCount, db.query("SELECT 1").paramsCount);
console.log(JSON.stringify(q.all({ $min: 2 })), q.toString());
for (const row of q.iterate({ $min: 1 })) { console.log("iter", JSON.stringify(row)); if (row.v === 3) break; }
for (const row of q) console.log("reuse", row.v);
const it = q.iterate({ $min: 3 });
console.log(JSON.stringify(it.next()), JSON.stringify(it.next()), JSON.stringify(it.return(7)));
class Num { get text() { return `${this.v}:${this.label}`; } }
const mapped = db.query("SELECT v, label FROM n ORDER BY v DESC LIMIT 2").as(Num).all();
console.log(mapped.map((m) => m instanceof Num && m.text).join(), Object.keys(mapped[0]).join());
console.log(JSON.stringify(db.query("SELECT v AS a, v * 10 AS b FROM n WHERE v = ?").values(2)), JSON.stringify(db.query("SELECT label AS x FROM n WHERE v < 0").all()));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_statement_metadata_iteration_and_cache")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_exec_multi_statement_and_changes(js, golden):
    """CATCHES: db.run/db.exec not executing every statement of a batch, wrong changes counts
    (batch totals, 0 for read-only statements, RETURNING drained), a wrong lastInsertRowid after
    batches and deletes, and run() with parameters not binding."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database();
console.log(JSON.stringify(db.run("CREATE TABLE k (id INTEGER PRIMARY KEY, v TEXT)")));
console.log(JSON.stringify(db.run("INSERT INTO k (v) VALUES ('a'); INSERT INTO k (v) VALUES ('b'); INSERT INTO k (v) VALUES ('c')")));
console.log(JSON.stringify(db.exec("INSERT INTO k (v) VALUES (?)", "d")), JSON.stringify(db.run("UPDATE k SET v = upper(v) WHERE id <= ?", 2)));
console.log(JSON.stringify(db.query("SELECT 1").run()), JSON.stringify(db.prepare("INSERT INTO k (v) VALUES ('e') RETURNING id").run()));
console.log(JSON.stringify(db.prepare("DELETE FROM k WHERE id % 2 = 0").run()), JSON.stringify(db.query("SELECT group_concat(v) AS g FROM k").get()));
console.log(JSON.stringify(db.run("")), JSON.stringify(db.run("SELECT 1; SELECT 2")));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_exec_multi_statement_and_changes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_serialize_and_deserialize(js, golden):
    """CATCHES: serialize() not producing a real SQLite file image (Buffer starting with the
    "SQLite format 3" header, whole pages), and deserialization via new Database(bytes) or
    Database.deserialize() not yielding an independent, writable copy with the same rows."""
    code = r"""
const { Database } = require("bun:sqlite");
const db = new Database();
db.exec("CREATE TABLE t (k TEXT, v BLOB); INSERT INTO t VALUES ('a', x'0102'), ('b', NULL)");
const bytes = db.serialize();
console.log(Buffer.isBuffer(bytes), JSON.stringify(bytes.subarray(0, 16).toString("latin1")), bytes.length % 512, bytes.length === bytes.readUInt16BE(16) * bytes.readUInt32BE(28));
const copy = new Database(bytes);
console.log(copy.filename, JSON.stringify(copy.query("SELECT k, hex(v) AS h FROM t ORDER BY k").all()));
const copy2 = Database.deserialize(new Uint8Array(bytes));
copy2.run("INSERT INTO t VALUES ('z', x'ff')");
console.log(copy2.query("SELECT count(*) AS n FROM t").get().n, copy.query("SELECT count(*) AS n FROM t").get().n, db.query("SELECT count(*) AS n FROM t").get().n);
const again = new Database(copy2.serialize());
console.log(JSON.stringify(again.query("SELECT k FROM t ORDER BY k").values().flat()));
try { new Database(new Uint8Array([1, 2, 3])).query("SELECT * FROM t").all(); } catch (e) { console.log(e.name, e.message); }
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_serialize_and_deserialize")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_file_database_and_open_flags(js, golden):
    """CATCHES: wrong open-flag mapping for file databases: readonly opens must reject writes with
    SQLITE_READONLY, missing files must fail with SQLITE_CANTOPEN instead of being created, `{}`/
    `{create:false}` must reach SQLite with no access mode (SQLITE_MISUSE), numeric flags must work."""
    code = r"""
const { Database, constants } = require("bun:sqlite");
const fs = require("fs");
const t = (label, f) => { try { console.log(label, "OK", JSON.stringify(f())); } catch (e) { console.log(label, e.name, JSON.stringify(e.code), e.errno, e.message); } };
const db = new Database("data.db");
db.run("CREATE TABLE kv (k TEXT PRIMARY KEY, v BLOB)");
db.query("INSERT INTO kv VALUES (?, ?)").run("blob", new Uint8Array([0, 255, 7]));
db.query("INSERT INTO kv VALUES (?, ?)").run("text", "plain");
console.log(db.filename, fs.existsSync("data.db"), fs.readFileSync("data.db").subarray(0, 15).toString());
db.close();
const ro = new Database("data.db", { readonly: true });
console.log(JSON.stringify(ro.query("SELECT k, hex(v) AS h, typeof(v) AS t FROM kv ORDER BY k").all()));
t("readonly write", () => ro.run("INSERT INTO kv VALUES ('x', 1)"));
ro.close();
const ro2 = Database.open("data.db", constants.SQLITE_OPEN_READONLY);
t("numeric readonly", () => ro2.query("DELETE FROM kv").run());
t("missing readonly", () => new Database("missing.db", { readonly: true }));
t("create false", () => new Database("missing2.db", { create: false }));
t("empty options", () => new Database("missing3.db", {}));
t("readwrite only", () => new Database("missing4.db", { readwrite: true }));
t("no directory", () => new Database("nodir/sub/x.db"));
console.log(["missing.db", "missing2.db", "missing3.db", "missing4.db"].map((f) => fs.existsSync(f)).join());
const rw = new Database("data.db", { readonly: true, create: true });
t("readonly+create", () => rw.run("INSERT INTO kv VALUES ('y', NULL)"));
const strict = new Database("strict.db", { strict: true });
t("strict opens rw", () => strict.run("CREATE TABLE s (x)"));
console.log(fs.readdirSync(".").filter((f) => f.endsWith(".db")).sort().join());
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_file_database_and_open_flags")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_extensions_file_control_and_custom_library(js, golden):
    """CATCHES: loadExtension/fileControl/setCustomSQLite not wired to SQLite: a missing extension
    must surface the loader's message, fileControl must accept numbers/TypedArrays and reject other
    values, and setCustomSQLite must reject a missing file and any call after a database is open."""
    code = r"""
const { Database, constants } = require("bun:sqlite");
const t = (label, f) => { try { console.log(label, "OK", JSON.stringify(f())); } catch (e) { console.log(label, e.name, JSON.stringify(e.code), e.message); } };
t("custom missing", () => Database.setCustomSQLite("./no-such-libsqlite.so"));
const db = new Database("fc.db");
db.run("CREATE TABLE x (y)");
t("custom after open", () => Database.setCustomSQLite("fc.db"));
t("load extension", () => db.loadExtension("./no_such_extension"));
t("fcntl number", () => db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, -1));
const flag = new Int32Array([-1]);
t("fcntl typed array", () => { db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, flag); return flag[0]; });
t("fcntl string", () => db.fileControl(constants.SQLITE_FCNTL_PERSIST_WAL, "x"));
console.log(constants.SQLITE_OPEN_READWRITE, constants.SQLITE_OPEN_CREATE, constants.SQLITE_PREPARE_PERSISTENT, constants.SQLITE_FCNTL_RESET_CACHE, Database.MAX_QUERY_CACHE_SIZE);
db.close();
t("closed extension", () => db.loadExtension("x"));
t("closed fcntl", () => db.fileControl(1, 0));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_extensions_file_control_and_custom_library")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_busy_locked_and_other_result_codes(js, golden):
    """CATCHES: wrong SQLiteError code/errno mapping for engine results beyond constraints: a second
    connection hitting a write lock (SQLITE_BUSY), dropping a table under an active cursor
    (SQLITE_LOCKED), oversized blobs, datatype mismatch, RAISE() in a trigger, a non-database file,
    max_page_count exhaustion (SQLITE_FULL) and a corrupted page header (SQLITE_CORRUPT)."""
    code = r"""
const { Database } = require("bun:sqlite");
const fs = require("fs");
const t = (label, f) => { try { console.log(label, "OK", JSON.stringify(f())); } catch (e) { console.log(label, e.name, JSON.stringify(e.code), e.errno, e.message); } };
const a = new Database("lock.db");
a.run("CREATE TABLE t (x INTEGER PRIMARY KEY, y)");
a.run("INSERT INTO t VALUES (1, 1)");
const b = new Database("lock.db");
a.run("BEGIN IMMEDIATE");
t("busy", () => b.run("INSERT INTO t VALUES (2, 2)"));
t("reader during lock", () => b.query("SELECT count(*) AS n FROM t").get());
a.run("COMMIT");
t("after commit", () => b.run("INSERT INTO t VALUES (2, 2)"));
const it = a.query("SELECT * FROM t").iterate();
it.next();
t("locked", () => a.run("DROP TABLE t"));
it.return();
t("toobig", () => a.query("SELECT zeroblob(2000000000) AS z").get());
t("mismatch", () => a.run("INSERT INTO t (x) VALUES ('abc')"));
t("trigger", () => { a.run("CREATE TRIGGER trg BEFORE INSERT ON t BEGIN SELECT RAISE(ABORT, 'no inserts allowed'); END"); return a.run("INSERT INTO t VALUES (5, 5)"); });
fs.writeFileSync("garbage.db", Buffer.alloc(4096, 0x42));
t("not a database", () => new Database("garbage.db").query("SELECT * FROM sqlite_master").all());
t("empty image", () => new Database(new Uint8Array(0)).query("SELECT 1 AS one").get());
const small = new Database();
small.run("CREATE TABLE big (b BLOB)");
t("full", () => { small.run("PRAGMA max_page_count = 3"); return small.query("INSERT INTO big VALUES (zeroblob(100000))").run(); });
const img = new Database();
img.run("CREATE TABLE c (v)");
img.run("INSERT INTO c VALUES (1)");
const bytes = img.serialize();
bytes[100] = 0xff; // page-1 b-tree page type
t("corrupt", () => new Database(bytes).query("SELECT * FROM c").all());
const st = a.prepare("SELECT 1 AS one");
a.close(); b.close();
t("statement after close", () => st.all());
t("run after close", () => st.run());
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_busy_locked_and_other_result_codes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_custom_library_load_failures(js, golden, workdir):
    """CATCHES: Database.setCustomSQLite not actually redirecting the dlopen: after pointing it at a
    file that is not a shared library, or at a library without the SQLite API, opening a database
    must fail with the loader's exact reason rather than silently using the system libsqlite3."""
    (workdir / "fake.so").write_text("not a library", encoding="utf-8")
    code = r"""
const { Database } = require("bun:sqlite");
const t = (label, f) => { try { console.log(label, "OK", JSON.stringify(f())); } catch (e) { console.log(label, e.name, e.message); } };
t("set", () => Database.setCustomSQLite("./fake.so"));
t("open", () => new Database());
t("open again", () => new Database(":memory:"));
t("set to a non-sqlite library", () => Database.setCustomSQLite("./noapi.so"));
t("open with missing symbols", () => new Database());
"""
    build_addon("int not_sqlite(void) { return 7; }\n", workdir / "noapi.so")
    r = js(code)
    assert out(r) == golden("sqlite_custom_library_load_failures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sqlite_load_compiled_extension(js, golden, workdir):
    """CATCHES: loadExtension not enabling and invoking SQLite's extension loader: an extension whose
    sqlite3_extension_init returns SQLITE_OK must load, one whose sqlite3_<name>_init fails must
    raise SQLite's initialization error, and a non-library file must report the loader error."""
    build_addon("int sqlite3_extension_init(void *db, char **err, const void *api) { return 0; }\n", workdir / "ext_ok.so")
    build_addon("int sqlite3_failing_init(void *db, char **err, const void *api) { return 1; }\n", workdir / "failing.so")
    (workdir / "fake.so").write_text("not a library", encoding="utf-8")
    code = r"""
const { Database } = require("bun:sqlite");
const t = (label, f) => { try { console.log(label, "OK", JSON.stringify(f())); } catch (e) { console.log(label, e.name, JSON.stringify(e.code), e.errno, e.message); } };
const db = new Database();
t("load ok", () => db.loadExtension("./ext_ok.so"));
t("still usable", () => db.query("SELECT 6 * 7 AS v").get());
t("init fails", () => db.loadExtension("./failing.so"));
t("not a library", () => db.loadExtension("./fake.so"));
"""
    r = js(code)
    skip_without_sqlite(r)
    assert out(r) == golden("sqlite_load_compiled_extension")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------------------- bun:ffi
def test_ffi_libc_integer_and_pointer_calls(js, golden):
    """CATCHES: broken integer-class FFI calls into libc: i32/i64/u64 marshalling (abs, labs with
    BigInt), Buffer and cstring pointer arguments (strlen, atoi), char-code round trips (toupper) and
    memset writing into a TypedArray through its pointer."""
    code = r"""
const { dlopen, FFIType } = require("bun:ffi");
const libc = dlopen("libc.so.6", {
  abs: { args: ["i32"], returns: "i32" },
  labs: { args: ["i64"], returns: "i64" },
  llabs: { args: [FFIType.int64_t], returns: FFIType.int64_t },
  strlen: { args: ["ptr"], returns: "u64" },
  toupper: { args: [FFIType.int], returns: FFIType.int },
  atoi: { args: ["cstring"], returns: "i32" },
  memset: { args: ["ptr", "i32", "usize"], returns: "ptr" },
  strtoul: { args: ["buffer", "ptr", "int"], returns: "u64" },
});
const s = libc.symbols;
const cstr = (x) => Buffer.from(x + "\0");
console.log(s.abs(-42), s.abs(7), s.abs(-2147483647), s.labs(-5000000000n), typeof s.labs(1), s.llabs(-9007199254740993n));
console.log(s.strlen(cstr("hello ffi")), s.strlen(cstr("")), String.fromCharCode(s.toupper("q".charCodeAt(0))), s.atoi(cstr("  -1234xyz")), s.atoi(cstr("42")));
console.log(s.strtoul(cstr("ff"), null, 16), s.strtoul(cstr("777"), null, 8));
const buf = new Uint8Array(12);
const ret = s.memset(buf.subarray(4), 0xab, 4);
console.log(Array.from(buf).join(), typeof ret);
libc.close();
"""
    r = js(code)
    skip_without_library(r, "libc.so.6")
    assert out(r) == golden("ffi_libc_integer_and_pointer_calls")
    assert (r.returncode, r.stderr) == (0, b"")


def test_ffi_libm_float_calls(js, golden):
    """CATCHES: wrong floating-point register handling in FFI calls: f64 and f32 args/returns (pow,
    sqrt, floorf, fmaf, fma, hypot), mixed int+float argument orders (ldexp, scalbnf), an i64
    return (lround), an out-pointer argument (frexp) and ToNumber coercion of string arguments."""
    code = r"""
const { dlopen, FFIType } = require("bun:ffi");
const m = dlopen("libm.so.6", {
  pow: { args: ["f64", "f64"], returns: "f64" },
  sqrt: { args: [FFIType.double], returns: FFIType.double },
  ldexp: { args: ["f64", "i32"], returns: "f64" },
  floorf: { args: ["f32"], returns: "f32" },
  fmaf: { args: ["f32", "f32", "f32"], returns: "f32" },
  fma: { args: ["f64", "f64", "f64"], returns: "f64" },
  hypot: { args: ["double", "double"], returns: "double" },
  scalbnf: { args: ["float", "int"], returns: "float" },
  lround: { args: ["f64"], returns: "i64" },
  ilogb: { args: ["f64"], returns: "i32" },
  frexp: { args: ["f64", "ptr"], returns: "f64" },
});
const s = m.symbols;
console.log(s.pow(2, 10), s.pow(2, 0.5), s.sqrt(2), s.ldexp(0.75, 4), s.floorf(-2.5), s.fmaf(1.5, 2, 0.25), s.fma(0.1, 10, -1), s.hypot(3, 4));
console.log(s.scalbnf(1.5, 3), s.lround(-2.5), s.ilogb(1024), s.sqrt(-1), s.floorf(0.1), s.pow(1e300, 2), s.sqrt("16"));
const e = new Int32Array(1);
console.log(s.frexp(48, e), e[0]);
"""
    r = js(code)
    skip_without_library(r, "libm.so.6")
    assert out(r) == golden("ffi_libm_float_calls")
    assert (r.returncode, r.stderr) == (0, b"")


def test_ffi_cstring_pointers_and_reads(js, golden):
    """CATCHES: pointer helpers that misbehave: cstring returns not wrapped as CString, null pointer
    returns not null, ptr() offsets/differences, CString with byteOffset/byteLength, read.* at
    offsets for every width and sign (little-endian), and toArrayBuffer/toBuffer copying wrong bytes."""
    code = r"""
const { dlopen, ptr, CString, read, toArrayBuffer, toBuffer } = require("bun:ffi");
const libc = dlopen("libc.so.6", {
  strstr: { args: ["ptr", "ptr"], returns: "cstring" },
  strchr: { args: ["ptr", "i32"], returns: "ptr" },
});
const s = libc.symbols;
const hay = Buffer.from("the quick brown fox\0");
const found = s.strstr(hay, Buffer.from("brown\0"));
console.log(found instanceof CString, found instanceof String, String(found), found.length, found.byteOffset, found.byteLength);
console.log(s.strstr(hay, Buffer.from("cat\0")) + "|", s.strchr(hay, "z".charCodeAt(0)), s.strchr(hay, "q".charCodeAt(0)) - ptr(hay), ptr(hay, 4) - ptr(hay));
const sub = new CString(ptr(hay), 4, 5);
console.log(String(sub), sub.byteLength, Array.from(new Uint8Array(sub.arrayBuffer)).join(), JSON.stringify(String(new CString(0))));
try { new CString(ptr(hay)).arrayBuffer; } catch (e) { console.log(e.name, e.message); }
const buf = new Uint8Array(24);
const dv = new DataView(buf.buffer);
dv.setUint32(0, 0xabcdef12, true); dv.setInt16(4, -2, true); dv.setFloat32(8, -2.0625, true); dv.setFloat64(16, Math.PI, true); buf[6] = 0x80; buf[7] = 0x7f;
const p = ptr(buf);
console.log(read.u8(p), read.i8(p, 6), read.u16(p, 4), read.i16(p, 4), read.u32(p), read.i32(p), read.f32(p, 8), read.f64(p, 16));
console.log(read.u64(p), read.i64(p), read.u64(p, 16), read.i64(p, 4));
const ab = toArrayBuffer(p, 4, 4), tb = toBuffer(p, 0, 3);
console.log(ab.constructor.name, Array.from(new Uint8Array(ab)).join(), Buffer.isBuffer(tb), tb.toString("hex"), toArrayBuffer(p, 0, 0).byteLength);
new Uint8Array(ab)[0] = 0; console.log(buf[4], "copy is independent");
"""
    r = js(code)
    skip_without_library(r, "libc.so.6")
    assert out(r) == golden("ffi_cstring_pointers_and_reads")
    assert (r.returncode, r.stderr) == (0, b"")


def test_ffi_jscallback_qsort_and_cfunction(js, golden):
    """CATCHES: JSCallback trampolines that do not re-enter JS with the right arguments (qsort
    comparator reading elements through read.i32), a callback whose return value is lost, CFunction
    over a callback pointer, close() not releasing the pointer, and unsupported float signatures."""
    code = r"""
const { dlopen, JSCallback, CFunction, read, FFIType } = require("bun:ffi");
const libc = dlopen("libc.so.6", { qsort: { args: ["ptr", "usize", "usize", "function"], returns: "void" } });
const arr = new Int32Array([5, -3, 99, 0, 42, -100, 7, 7, 1]);
let calls = 0;
const cmp = new JSCallback((a, b) => { calls++; return read.i32(a) - read.i32(b); }, { args: ["ptr", "ptr"], returns: "i32" });
libc.symbols.qsort(arr, arr.length, 4, cmp.ptr);
console.log(Array.from(arr).join(), calls > 0, typeof cmp.ptr);
const desc = new JSCallback((a, b) => read.i32(b) - read.i32(a), { args: [FFIType.ptr, FFIType.ptr], returns: FFIType.i32 });
libc.symbols.qsort(arr, arr.length, 4, desc.ptr);
console.log(Array.from(arr).join());
const add = new JSCallback((x, y) => x + y, { args: ["i32", "i32"], returns: "i32" });
const viaPtr = CFunction({ ptr: add.ptr, args: ["i32", "i32"], returns: "i32" });
const big = new JSCallback((x) => x * 3n, { args: ["i64"], returns: "i64" });
const bigFn = CFunction({ ptr: big.ptr, args: ["i64"], returns: "i64" });
const flag = new JSCallback((b) => !b, { args: ["bool"], returns: "bool" });
console.log(viaPtr(40, 2), viaPtr(-5, -6), bigFn(-7n), CFunction({ ptr: flag.ptr, args: ["bool"], returns: "bool" })(false));
cmp.close(); desc.close(); add.close();
console.log(cmp.ptr, add.ptr);
for (const def of [{ args: ["f64"], returns: "i32" }, { args: [], returns: "f32" }]) {
  try { new JSCallback(() => 0, def); } catch (e) { console.log(e.name, e.message); }
}
try { new JSCallback(5, { args: [] }); } catch (e) { console.log(e.name, e.message); }
"""
    r = js(code)
    skip_without_library(r, "libc.so.6")
    assert out(r) == golden("ffi_jscallback_qsort_and_cfunction")
    assert (r.returncode, r.stderr) == (0, b"")


def test_ffi_errors_and_type_table(js, golden):
    """CATCHES: bun:ffi accepting bad input instead of throwing Bun's exact errors (missing library or
    symbol, unknown FFIType, strings/BigInts/objects as pointers, fractional i64, more than 8 arguments)
    and a wrong FFIType table, suffix or linkSymbols binding."""
    code = r"""
const ffi = require("bun:ffi");
const { dlopen, FFIType, ptr, suffix, linkSymbols, JSCallback } = ffi;
const t = (label, f) => { try { console.log(label, "OK", String(f())); } catch (e) { console.log(label, e.name, e.message); } };
const libc = dlopen("libc.so.6", { strlen: { args: ["ptr"], returns: "u64" }, labs: { args: ["i64"], returns: "i64" } });
t("missing library", () => dlopen("./libnope-lumen.so", {}));
t("missing symbol", () => dlopen("libc.so.6", { lumen_no_such_fn: { args: [], returns: "void" } }));
t("unknown type", () => dlopen("libc.so.6", { abs: { args: ["i33"], returns: "i32" } }));
t("string pointer", () => libc.symbols.strlen("abc"));
t("bigint pointer", () => libc.symbols.strlen(5n));
t("object pointer", () => libc.symbols.strlen({}));
t("fractional i64", () => libc.symbols.labs(1.5));
t("nine args", () => dlopen("libc.so.6", { abs: { args: Array(9).fill("i32"), returns: "i32" } }).symbols.abs(1, 2, 3, 4, 5, 6, 7, 8, 9));
t("ptr of string", () => ptr("x"));
console.log(suffix, FFIType.char, FFIType.i8, FFIType.u8, FFIType.i16, FFIType.u16, FFIType.i32, FFIType.u32, FFIType.i64, FFIType.u64, FFIType.f64, FFIType.f32,
  FFIType.bool, FFIType.ptr, FFIType.void, FFIType.cstring, FFIType.i64_fast, FFIType.u64_fast, FFIType.function, FFIType.buffer, FFIType[12], FFIType["char*"]);
const neg = new JSCallback((x) => -x, { args: ["i32"], returns: "i32" });
const linked = linkSymbols({ negate: { ptr: neg.ptr, args: ["i32"], returns: "i32" }, negFast: { ptr: neg.ptr, args: ["i32"], returns: "i64_fast" } });
console.log(linked.symbols.negate(12), linked.symbols.negate(-2147483648), typeof linked.symbols.negFast(3), Object.keys(linked).sort().join());
console.log(Object.keys(ffi).sort().join());
"""
    r = js(code)
    skip_without_library(r, "libc.so.6")
    assert out(r) == golden("ffi_errors_and_type_table")
    assert (r.returncode, r.stderr) == (0, b"")


FFI_C_SOURCE = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
double mix(int a, double b, int c, float d) { return a * b + c - d; }
double mix2(double a, int b, float c, int64_t d, double e) { return a + b * c + (double)d - e; }
float halve(float x) { return x / 2.0f; }
int64_t sum8(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e, int64_t f, int64_t g, int64_t h) { return a + b + c + d + e + f + g + h; }
double fsum8(double a, double b, double c, double d, double e, double f, double g, double h) { return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f + 7 * g + 8 * h; }
double mixed8(int a, double b, int c, double d, int e, double f, int g, double h) { return a - b + c - d + e - f + g - h; }
uint8_t wrap_u8(int x) { return (uint8_t)x; }
int8_t wrap_i8(int x) { return (int8_t)x; }
int16_t wrap_i16(int x) { return (int16_t)x; }
uint16_t wrap_u16(int x) { return (uint16_t)x; }
uint32_t wrap_u32(int64_t x) { return (uint32_t)x; }
int take_i8(int8_t x) { return x; }
unsigned take_u16(uint16_t x) { return x; }
bool is_even(int x) { return x % 2 == 0; }
void *null_ptr(void) { return NULL; }
uint64_t big_u64(void) { return 0xFFFFFFFFFFFFFFFFull; }
int64_t neg_i64(void) { return -9007199254740993ll; }
int apply(int (*f)(int, int), int a, int b) { return f(a, b) * 10; }
int64_t apply64(int64_t (*f)(int64_t), int64_t x) { return f(x) + 1; }
int fold3(int (*f)(int, int, int), int n) { int acc = 0; for (int i = 0; i < n; i++) acc = f(acc, i, n); return acc; }
static char msg[] = "from C";
const char *message(void) { return msg; }
static int counter = 0;
void bump(void) { counter++; }
int get_count(void) { return counter; }
int answer(void) { return ANSWER; }
"""


def test_ffi_cc_compiled_signatures(js, golden, workdir):
    """CATCHES: trampoline bugs for signatures libc cannot exercise: mixed int/float orders, f32
    returns, all-8-register int and float calls, narrow integer wrap-around on arguments and
    returns, bool, null pointers, u64/i64/i64_fast returns, cstring returns, C calling back into JS
    (including i64 callbacks), cc() `define`s, and state kept between calls."""
    if shutil.which("cc") is None:
        pytest.skip("no C compiler for bun:ffi cc")
    (workdir / "lib.c").write_text(FFI_C_SOURCE, encoding="utf-8")
    code = r"""
const { cc, JSCallback } = require("bun:ffi");
const lib = cc({ source: "./lib.c", define: { ANSWER: "42" }, flags: ["-O1"], symbols: {
  mix: { args: ["i32", "f64", "i32", "f32"], returns: "f64" },
  mix2: { args: ["f64", "i32", "f32", "i64", "f64"], returns: "f64" },
  halve: { args: ["f32"], returns: "f32" },
  sum8: { args: Array(8).fill("i64"), returns: "i64" },
  fsum8: { args: Array(8).fill("f64"), returns: "f64" },
  mixed8: { args: ["i32", "f64", "i32", "f64", "i32", "f64", "i32", "f64"], returns: "f64" },
  wrap_u8: { args: ["i32"], returns: "u8" }, wrap_i8: { args: ["i32"], returns: "i8" },
  wrap_i16: { args: ["i32"], returns: "i16" }, wrap_u16: { args: ["i32"], returns: "u16" },
  wrap_u32: { args: ["i64"], returns: "u32" }, take_i8: { args: ["i8"], returns: "i32" }, take_u16: { args: ["u16"], returns: "u32" },
  is_even: { args: ["i32"], returns: "bool" },
  null_ptr: { returns: "ptr" }, big_u64: { returns: "u64" }, neg_i64: { returns: "i64" },
  big_fast: { name: "big_u64", returns: "u64_fast" }, neg_fast: { name: "neg_i64", returns: "i64_fast" },
  apply: { args: ["function", "i32", "i32"], returns: "i32" },
  apply64: { args: ["function", "i64"], returns: "i64" },
  fold3: { args: ["callback", "i32"], returns: "i32" },
  message: { returns: "cstring" }, bump: {}, get_count: { returns: "int" }, answer: { returns: "i32" },
}});
const s = lib.symbols;
console.log(s.mix(3, 1.5, 4, 0.25), s.mix2(0.5, 3, 1.5, 10n, 0.25), s.halve(5), s.halve(1e-45), s.sum8(1, 2, 3, 4, 5, 6, 7, 8n), s.fsum8(1, 1, 1, 1, 1, 1, 1, 0.5), s.mixed8(10, 0.5, 20, 0.25, 30, 0.125, 40, 1));
console.log(s.wrap_u8(300), s.wrap_i8(200), s.wrap_i16(40000), s.wrap_u16(-1), s.wrap_u32(-1), s.take_i8(255), s.take_u16(65537), s.is_even(4), s.is_even(5));
console.log(s.null_ptr(), typeof s.big_u64(), s.big_u64(), s.neg_i64(), typeof s.big_fast(), s.neg_fast(), String(s.message()), s.answer());
const add = new JSCallback((a, b) => a + b, { args: ["i32", "i32"], returns: "i32" });
const dbl = new JSCallback((x) => x * 2n, { args: ["i64"], returns: "i64" });
const seen = [];
const f3 = new JSCallback((acc, i, n) => { seen.push(i); return acc + i * n; }, { args: ["i32", "i32", "i32"], returns: "i32" });
console.log(s.apply(add.ptr, 4, 5), s.apply(add.ptr, 10, -3), s.apply64(dbl.ptr, 21n), s.fold3(f3.ptr, 4), seen.join());
s.bump(); s.bump(); s.bump();
console.log(s.get_count());
lib.close();
"""
    r = js(code)
    assert out(r) == golden("ffi_cc_compiled_signatures")
    assert (r.returncode, r.stderr) == (0, b"")


def test_ffi_cc_errors(js, golden, workdir):
    """CATCHES: cc() accepting invalid options instead of throwing: a non-object, a missing or
    non-string source, a source path that does not exist, and C code that fails to compile must all
    raise their exact errors (the compiler diagnostics are not compared, only the prefix)."""
    if shutil.which("cc") is None:
        pytest.skip("no C compiler for bun:ffi cc")
    (workdir / "broken.c").write_text("int broken( { return 1; }\n", encoding="utf-8")
    code = r"""
const { cc, viewSource } = require("bun:ffi");
const t = (label, f) => { try { f(); console.log(label, "no error"); } catch (e) { console.log(label, e.name, e.message.split("\n")[0].slice(0, 30)); } };
t("no options", () => cc());
t("bad source", () => cc({ source: 42 }));
t("missing file", () => cc({ source: "./does-not-exist.c", symbols: {} }));
t("compile error", () => cc({ source: "./broken.c", symbols: {} }));
t("viewSource", () => viewSource(42));
console.log(viewSource(function named() { return 1; }));
"""
    r = js(code)
    assert out(r) == golden("ffi_cc_errors")
    assert (r.returncode, r.stderr) == (0, b"")


FFI_CALLBACK_C = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
typedef int64_t (*cb_all)(uint8_t, int8_t, int16_t, uint16_t, uint32_t, int32_t, bool, void *);
int64_t call_all(cb_all f) { return f(200, -100, -30000, 60000, 4000000000u, -5, true, NULL); }
typedef uint64_t (*cb_u64)(uint64_t, int64_t);
uint64_t call_u64(cb_u64 f) { return f(0xFFFFFFFFFFFFFFF0ull, -2); }
typedef void (*cb_void)(int);
int call_void(cb_void f) { f(7); f(8); return 3; }
typedef char *(*cb_ptr)(char *);
int call_ptr(cb_ptr f, char *s) { char *r = f(s); return r == s ? 1 : (r == NULL ? 2 : 0); }
typedef int (*cb_int)(int);
int call_twice(cb_int f) { return f(1) * 100 + f(2); }
typedef char (*cb_char)(char);
int call_char(cb_char f) { return f('a'); }
typedef uint8_t (*cb_u8)(void);
int call_u8(cb_u8 f) { return f(); }
"""


def test_ffi_callback_argument_types_and_failures(js, golden, workdir):
    """CATCHES: JSCallback marshalling bugs: narrow ints (u8/i8/i16/u16/u32/char) must be truncated and
    sign/zero-extended, 64-bit values arrive as BigInt, bool as boolean, NULL as null, void/pointer/
    narrow returns convert back, a throwing callback reports on stderr and returns 0, a closed
    callback's stale pointer returns 0; plus the 16-slot pool limit and the 8-argument limit."""
    if shutil.which("cc") is None:
        pytest.skip("no C compiler for bun:ffi cc")
    (workdir / "cb.c").write_text(FFI_CALLBACK_C, encoding="utf-8")
    code = r"""
const { cc, JSCallback, ptr, read, toBuffer } = require("bun:ffi");
const lib = cc({ source: "./cb.c", symbols: {
  call_all: { args: ["function"], returns: "i64" }, call_u64: { args: ["function"], returns: "u64" },
  call_void: { args: ["function"], returns: "i32" }, call_ptr: { args: ["function", "ptr"], returns: "i32" },
  call_twice: { args: ["function"], returns: "i32" }, call_char: { args: ["function"], returns: "i32" }, call_u8: { args: ["function"], returns: "i32" },
}});
const s = lib.symbols;
const all = new JSCallback((...a) => { console.log("all args", a.map((v) => typeof v === "bigint" ? v + "n" : String(v)).join(" ")); return -123456789012n; },
  { args: ["u8", "i8", "i16", "u16", "u32", "i32", "bool", "ptr"], returns: "i64" });
console.log(s.call_all(all.ptr));
const u = new JSCallback((a, b) => { console.log("u64 args", typeof a, a, typeof b, b); return a + BigInt(b) * 3n; }, { args: ["u64", "i64"], returns: "u64" });
console.log(s.call_u64(u.ptr));
const seen = [];
const v = new JSCallback((x) => { seen.push(x); return 99; }, { args: ["i32"] });
console.log(s.call_void(v.ptr), seen.join());
const buf = Buffer.from("pointer!\0");
const same = new JSCallback((p) => p, { args: ["ptr"], returns: "ptr" });
const nul = new JSCallback(() => null, { args: ["ptr"], returns: "ptr" });
console.log(s.call_ptr(same.ptr, buf), s.call_ptr(nul.ptr, buf));
const ch = new JSCallback((c) => c + 1, { args: ["char"], returns: "char" });
const u8 = new JSCallback(() => 300, { args: [], returns: "u8" });
console.log(s.call_char(ch.ptr), s.call_u8(u8.ptr));
const boom = new JSCallback((x) => { if (x === 2) throw new Error("boom in callback"); return x; }, { args: ["i32"], returns: "i32" });
console.log("after throw", s.call_twice(boom.ptr));
const dead = boom.ptr;
boom.close();
console.log("closed callback returns 0:", s.call_twice(dead), boom.ptr);
const p = ptr(buf);
console.log(read.ptr(new BigUint64Array([BigInt(p)])) === p, read.intptr(new BigUint64Array([BigInt(p)])) === p, toBuffer(p, 0, 0).length);
const many = [];
try { for (let i = 0; i < 20; i++) many.push(new JSCallback(() => i, { args: [], returns: "i32" })); } catch (e) { console.log(e.name, e.message, many.length); }
many[0].close();
console.log(typeof new JSCallback(() => 0, { args: [], returns: "i32" }).ptr);
try { new JSCallback(() => 0, { args: Array(9).fill("i32"), returns: "i32" }); } catch (e) { console.log(e.name, e.message); }
"""
    r = js(code)
    assert out(r) == golden("ffi_callback_argument_types_and_failures")
    assert (r.returncode, err(r)) == (0, "uncaught exception in bun:ffi JSCallback: Error: boom in callback\n")
