"""Bun-compatible global APIs: Bun.hash families, CryptoHasher/SHA classes, Bun.password (bcrypt and
Argon2 against fixed hashes), Bun.Cookie/CookieMap, Bun.CSRF, Bun.FileSystemRouter, Bun.file/Bun.write,
Bun.Glob and the small string/buffer/stream helpers."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

# Deterministic byte pattern shared by the hash tests: byte i = (i * 31 + 7) & 0xff.
HASH_PRELUDE = r'''
const pat = (n) => { const u = new Uint8Array(n); for (let i = 0; i < n; i++) u[i] = (i * 31 + 7) & 255; return u; };
const hex = (v) => v.toString(16);
const FAMILIES = ["wyhash", "cityHash32", "cityHash64", "xxHash32", "xxHash64", "xxHash3", "murmur32v2",
                  "murmur32v3", "murmur64v2", "rapidhash", "crc32", "adler32"];
'''


def test_hash_families_every_length(run, workdir):
    """CATCHES: wrong tail/remainder handling in any Bun.hash family (wyhash 16/48-byte rounds, cityHash
    0-4/5-12/13-24/17-32/33-64 branches, xxHash32/64 stripes, xxHash3 1-3/4-8/9-16/17-128/129-240/long
    paths, murmur tails, rapidhash 48/112-byte loops, crc32/adler32) — every length 0..130 plus
    long inputs is hashed with seed 0, so an off-by-one at any boundary changes a value."""
    check_script(run, workdir, G, "hash_families_every_length", HASH_PRELUDE + r'''
console.log("len " + FAMILIES.join(" "));
const lens = [];
for (let n = 0; n <= 130; n++) lens.push(n);
lens.push(160, 191, 192, 200, 239, 240, 241, 255, 256, 257, 300, 511, 1023, 1024, 1025, 1100, 2100, 4096, 65536);
for (const n of lens) {
  const d = pat(n);
  console.log(n + " " + FAMILIES.map((f) => hex(Bun.hash[f](d))).join(" "));
}
console.log(Bun.hash === Bun.hash.wyhash, typeof Bun.hash(""), typeof Bun.hash.cityHash32(""),
            typeof Bun.hash.xxHash3(""), typeof Bun.hash.crc32(""), typeof Bun.hash.adler32(""));
''')


def test_hash_seeds_and_input_coercion(run, workdir):
    """CATCHES: seeds not reduced mod 2^64 (BigInt), negative int32 seeds not sign-extended, non-int52
    doubles/strings not mapped to seed 0, 32-bit families not truncating the seed, cityHash32/crc32
    wrongly honouring a seed, and inputs (strings as UTF-8, TypedArray views with offsets, ArrayBuffer,
    DataView, numbers, undefined/null, no argument) hashed as the wrong bytes."""
    check_script(run, workdir, G, "hash_seeds_and_input_coercion", HASH_PRELUDE + r'''
const inputs = {
  empty: new Uint8Array(0), len3: pat(3), len17: pat(17), len64: pat(64), len129: pat(129), len300: pat(300),
  zero64: new Uint8Array(64), ff64: new Uint8Array(64).fill(255),
  utf8: "héllo wörld 你好 🌍 café Ⓐ ∑∫ 𝕳𝖊𝖑𝖑𝖔",
};
const seeds = [1n, 0xdeadbeefn, 0x7fffffffffffffffn, 0x8000000000000000n, 0xffffffffffffffffn];
for (const f of FAMILIES) {
  for (const s of seeds) {
    console.log(f, hex(s), Object.values(inputs).map((d) => hex(Bun.hash[f](d, s))).join(" "));
  }
}
const d = pat(20);
const seedForms = [["-1", -1], ["2^64-1n", (1n << 64n) - 1n], ["2^64+5n", (1n << 64n) + 5n], ["5", 5], ["5n", 5n],
                   ["-5", -5], ["2^31", 2 ** 31], ["2^50", 2 ** 50], ["2^51", 2 ** 51], ["2^52", 2 ** 52],
                   ["-(2^40)", -(2 ** 40)], ["1.5", 1.5], ["NaN", NaN], ["Infinity", Infinity], ["'7'", "7"],
                   ["null", null], ["true", true], ["-1n", -1n]];
for (const [label, s] of seedForms) {
  console.log("seed", label, hex(Bun.hash(d, s)), hex(Bun.hash.xxHash32(d, s)), hex(Bun.hash.xxHash3(d, s)),
              hex(Bun.hash.murmur32v3(d, s)), hex(Bun.hash.cityHash64(d, s)));
}
console.log("seed-ignored", hex(Bun.hash.cityHash32(d, 99)) === hex(Bun.hash.cityHash32(d)),
            hex(Bun.hash.crc32(d, 99)) === hex(Bun.hash.crc32(d)), hex(Bun.hash.adler32(d, 99)) === hex(Bun.hash.adler32(d)));
console.log("xxHash3-low32", Bun.hash.xxHash3(d, 0x100000005n) === Bun.hash.xxHash3(d, 5));
const big = pat(40);
const forms = [
  ["string", "abc"], ["buffer", Buffer.from("abc")], ["u8", new Uint8Array([97, 98, 99])],
  ["arraybuffer", new Uint8Array([97, 98, 99]).buffer], ["dataview", new DataView(new Uint8Array([0, 97, 98, 99, 0]).buffer, 1, 3)],
  ["subarray", new Uint8Array([0, 0, 97, 98, 99, 0]).subarray(2, 5)], ["u16", new Uint16Array([0x6261, 0x63])],
  ["number", 123], ["numstr", "123"], ["undefined", undefined], ["undefstr", "undefined"], ["null", null],
  ["obj", { toString() { return "abc"; } }], ["none"],
];
for (const [label, ...args] of forms) {
  console.log("input", label, hex(Bun.hash(...args)), Bun.hash.crc32(...args), Bun.hash.adler32(...args),
              hex(Bun.hash.murmur64v2(...args)), hex(Bun.hash.rapidhash(...args)));
}
console.log("view-offset", hex(Bun.hash.xxHash64(big.subarray(7, 33))) === hex(Bun.hash.xxHash64(pat(40).slice(7, 33))));
''')


def test_crypto_hasher_sha_classes_and_uuid_v5(run, workdir):
    """CATCHES: Bun.CryptoHasher not chaining update() across strings/TypedArrays, digest() without an
    encoding not returning a Uint8Array, HMAC mode (second constructor argument) ignored, wrong
    Bun.sha (must be SHA-512/256), wrong per-class one-shots (MD5/SHA1/SHA384/SHA512_256), unsupported
    algorithms not throwing the exact error, and non-deterministic or mis-formatted randomUUIDv5."""
    check_script(run, workdir, G, "crypto_hasher_sha_classes_and_uuid_v5", r'''
const t = (label, f) => {
  try {
    const v = f();
    const shown = v instanceof Uint8Array ? v.constructor.name + "(" + v.length + ") " + Buffer.from(v).toString("hex") : JSON.stringify(v);
    console.log(label, shown);
  } catch (e) { console.log(label, "threw", e.name + ": " + e.message); }
};
t("chain", () => new Bun.CryptoHasher("sha256").update("ab").update(new Uint8Array([99])).digest("hex"));
t("raw", () => new Bun.CryptoHasher("sha1").update("abc").digest());
t("b64", () => new Bun.CryptoHasher("md5").update(new Uint8Array([1, 2, 3]).buffer).digest("base64"));
t("hmac", () => new Bun.CryptoHasher("sha256", "key").update("The quick brown fox jumps over the lazy dog").digest("hex"));
t("hmac512", () => new Bun.CryptoHasher("sha512", "k").update("").digest("hex"));
t("static", () => Bun.CryptoHasher.hash("sha384", "abc", "hex"));
t("static-raw", () => Bun.CryptoHasher.hash("md5", new Uint8Array(0)));
t("algo-prop", () => new Bun.CryptoHasher("sha512-256").algorithm);
t("sha512-224", () => new Bun.CryptoHasher("sha512-224").update("abc").digest("hex"));
t("algorithms", () => Bun.CryptoHasher.algorithms);
for (const [name, C] of [["MD5", Bun.MD5], ["SHA1", Bun.SHA1], ["SHA256", Bun.SHA256], ["SHA384", Bun.SHA384],
                         ["SHA512", Bun.SHA512], ["SHA512_256", Bun.SHA512_256]]) {
  t(name, () => C.hash("abc", "hex"));
  t(name + "-inst", () => new C().update("a").update("bc").digest("base64"));
}
t("SHA256-bytes", () => Bun.SHA256.hash(new Uint8Array(1000).fill(97)));
t("sha", () => Bun.sha("abc", "hex"));
t("sha-raw", () => Bun.sha(""));
t("sha-long", () => Bun.sha("x".repeat(200), "hex"));
t("md4", () => new Bun.CryptoHasher("md4"));
t("bogus", () => Bun.CryptoHasher.hash("whirlpool", "x", "hex"));
t("SHA224", () => Bun.SHA224.hash("abc", "hex"));
t("uuid-dns", () => Bun.randomUUIDv5("example.com", "dns"));
t("uuid-url", () => Bun.randomUUIDv5("https://example.com/a?b", "url"));
t("uuid-oid", () => Bun.randomUUIDv5("1.3.6.1", "oid"));
t("uuid-x500", () => Bun.randomUUIDv5("cn=x", "x500"));
t("uuid-custom", () => Bun.randomUUIDv5("name", "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"));
t("uuid-bytes-name", () => Bun.randomUUIDv5(new Uint8Array([1, 2, 3]), "dns"));
t("uuid-buffer", () => Bun.randomUUIDv5("example.com", "dns", "buffer"));
t("uuid-empty", () => Bun.randomUUIDv5("", "dns"));
t("uuid-bad-ns", () => Bun.randomUUIDv5("x", "not-a-namespace"));
''')


def test_password_verify_known_hashes(run, workdir):
    """CATCHES: broken bcrypt (Blowfish key schedule, cost loop, $2a/$2b/$2y aliasing, 8-bit password
    bytes, the >72-byte SHA-512 pre-hash Bun applies instead of truncation, $2x$ wrongly accepted) or
    Argon2 (2d/2i/2id, version 19, m below 8 blocks, multiple lanes, secret/associated data) — verified
    against hashes produced by Bun 1.2.21, the Openwall bcrypt vectors and the RFC 9106 Argon2 vectors."""
    check_script(run, workdir, G, "password_verify_known_hashes", r'''
const P = Bun.password;
const bytes = (...b) => new Uint8Array(b);
const fixtures = [
  ["bun-argon2id", "hunter2", "$argon2id$v=19$m=64,t=1,p=1$Qlq4y6N6W71yfwUALUE1saUFYrEf6EgHwYFtX0swMtU$3Zy/fZUAYcYmCSCCix/WJ0szZpIJI6SYjmGVcdfGtPw"],
  ["bun-argon2i", "hunter2", "$argon2i$v=19$m=64,t=2,p=1$11HY6+bCFDRtMsONMVaCUvq4sISHSuc8ldW0Umyh3Mc$Mw+4ZZ6qKn8yvUNEUdE3FL5Zv2k37VsNNbgP7NAjafA"],
  ["bun-argon2d", "hunter2", "$argon2d$v=19$m=64,t=2,p=1$g2sFB+MOMkV4ZtklRVjE+oaIPRRdaak2j8tMtt6Arss$ssJ/R8OCdo3od8rL8by1eheI0t7Yn2fYunxA3PDRlhY"],
  ["bun-bcrypt", "hunter2", "$2b$04$vVj0LFIN/tWPPW6l9KVfb./2Cr91.SdAmARN0zGOD41OBzylfgoGK"],
  ["bun-bcrypt-73", "A".repeat(73), "$2b$04$VtsMUcJFE9ep38Tn9ECXQuyLfmvdzbZhhQU6r.bm.ByAvuWAAVSC6"],
  ["bun-bcrypt-binary", bytes(0, 255, 128, 1, 170, 85), "$2b$04$jz6swG09WNYeIYtvADKPH.jmlAMlOvFuuTPm53ndjH0GiNSPbaty."],
  ["openwall-U*U", "U*U", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.E5YPO9kmyuRGyh0XouQYb4YMJKvyOeW"],
  ["openwall-U*U*", "U*U*", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.VGOzA784oUp/Z0DY336zx7pLYAy0lwK"],
  ["openwall-U*U*U", "U*U*U", "$2a$05$XXXXXXXXXXXXXXXXXXXXXOAcXxm9kjPGEMsLznoKqmqw7tc8WCx4a"],
  ["openwall-empty", "", "$2a$05$CCCCCCCCCCCCCCCCCCCCC.7uG0VCzI2bS7j6ymqJi9CdcdxiRTWNy"],
  ["openwall-over72", "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789chars after 72 are ignored",
   "$2a$05$abcdefghijklmnopqrstuu5s2v8.iXieOjg/.AySBTTZIIVFJeBui"],
  ["openwall-a3-2y", bytes(0xa3), "$2y$05$/OK.fbVrR/bpIqNJ5ianF.Sa7shbm4.OzKpvFnX1pQLmQW96oUlCq"],
  ["openwall-a3-2a", bytes(0xa3), "$2a$05$/OK.fbVrR/bpIqNJ5ianF.Sa7shbm4.OzKpvFnX1pQLmQW96oUlCq"],
  ["openwall-a3-2b", bytes(0xa3), "$2b$05$/OK.fbVrR/bpIqNJ5ianF.Sa7shbm4.OzKpvFnX1pQLmQW96oUlCq"],
  ["openwall-a3-2x-bug", bytes(0xa3), "$2x$05$/OK.fbVrR/bpIqNJ5ianF.CE5elHaaO4EbggVDjb8P19RukzXSM3e"],
  ["openwall-ffa3345", bytes(0xff, 0xa3, 0x33, 0x34, 0x35), "$2y$05$/OK.fbVrR/bpIqNJ5ianF.nRht2l/HRhr6zmCp9vYUvvsqynflf9e"],
];
for (const [label, pw, hash] of fixtures) {
  console.log(label, P.verifySync(pw, hash), P.verifySync("wrong", hash));
}
// The same password as a string, a Buffer and an ArrayBuffer must verify identically.
const h = fixtures[3][2];
console.log("forms", P.verifySync(Buffer.from("hunter2"), h), P.verifySync(new TextEncoder().encode("hunter2").buffer, h),
            P.verifySync("hunter2\0", h), P.verifySync("Hunter2", h));

// RFC 9106 test vectors (p=4 lanes, secret + associated data) through crypto.argon2Sync.
const crypto = require("crypto");
const rfc = { message: Buffer.alloc(32, 1), nonce: Buffer.alloc(16, 2), parallelism: 4, tagLength: 32, memory: 32, passes: 3,
              secret: Buffer.alloc(8, 3), associatedData: Buffer.alloc(12, 4) };
for (const alg of ["argon2d", "argon2i", "argon2id"]) console.log("rfc9106", alg, crypto.argon2Sync(alg, rfc).toString("hex"));
const plain = { message: "password", nonce: Buffer.from("somesalt"), parallelism: 1, tagLength: 16, memory: 8, passes: 2 };
console.log("argon2id-16", crypto.argon2Sync("argon2id", plain).toString("hex"));
console.log("argon2i-long-tag", crypto.argon2Sync("argon2i", { ...plain, tagLength: 100 }).toString("base64"));

// A PHC string assembled from crypto.argon2Sync output (two lanes, no padding) verifies through Bun.password.
const b64 = (b) => b.toString("base64").replace(/=+$/, "");
for (const [alg, p, m, t] of [["argon2id", 2, 16, 1], ["argon2i", 3, 24, 2], ["argon2d", 1, 9, 3]]) {
  const salt = Buffer.from("0123456789abcdef");
  const tag = crypto.argon2Sync(alg, { message: "lane-test", nonce: salt, parallelism: p, tagLength: 32, memory: m, passes: t });
  const phc = `$${alg}$v=19$m=${m},t=${t},p=${p}$${b64(salt)}$${b64(tag)}`;
  console.log("phc", phc, P.verifySync("lane-test", phc), P.verifySync("lane-tesT", phc));
}
const v16 = crypto.argon2Sync("argon2id", { message: "pw", nonce: Buffer.from("saltsalt"), parallelism: 1, tagLength: 32, memory: 8, passes: 1 });
console.log("no-version-field", P.verifySync("pw", `$argon2id$m=8,t=1,p=1$${b64(Buffer.from("saltsalt"))}$${b64(v16)}`));
// The callback form runs off-thread and must produce the same bytes.
crypto.argon2("argon2id", rfc, (err, tag) => {
  console.log("async rfc9106", err, tag.toString("hex"));
  crypto.argon2("argon2d", { ...plain, tagLength: 8 }, (err2, tag2) => console.log("async argon2d-8", err2, tag2.toString("hex")));
});
''')


def test_password_hash_roundtrip_options_and_errors(run, workdir):
    """CATCHES: Bun.password.hash/hashSync ignoring algorithm/cost/memoryCost/timeCost (the PHC/bcrypt
    prefix encodes them), the wrong default (argon2id m=65536 t=2), salts of the wrong size, the async
    API not resolving/rejecting like the sync one, bcrypt's 72-byte boundary (73+ bytes pre-hash), and
    inexact validation errors (TypeError/RangeError names and messages, Bun's "Password verification
    failed with error ..." texts)."""
    check_script(run, workdir, G, "password_hash_roundtrip_options_and_errors", r'''
const P = Bun.password;
const shape = (h) => h.replace(/^(\$argon2\w+\$v=19\$m=\d+,t=\d+,p=1\$)([^$]+)\$([^$]+)$/, (_, p, s, t) => `${p}<salt:${s.length}>$<tag:${t.length}>`)
                      .replace(/^(\$2b\$\d\d\$)(.{53})$/, (_, p, r) => `${p}<${r.length} chars>`);
const cases = [
  ["argon2id", { algorithm: "argon2id", memoryCost: 16, timeCost: 1 }],
  ["argon2i", { algorithm: "argon2i", memoryCost: 8, timeCost: 2 }],
  ["argon2d", { algorithm: "argon2d", memoryCost: 4, timeCost: 3 }],
  ["upper", { algorithm: "ARGON2ID", memoryCost: 1, timeCost: 1 }],
  ["bcrypt4", { algorithm: "bcrypt", cost: 4 }],
  ["bcrypt5", { algorithm: "bcrypt", cost: 5 }],
];
for (const [label, opts] of cases) {
  const h = P.hashSync("pässwörd 🔑", opts);
  console.log(label, shape(h), P.verifySync("pässwörd 🔑", h), P.verifySync("passwörd 🔑", h));
}
const a = P.hashSync("same", { algorithm: "bcrypt", cost: 4 }), b = P.hashSync("same", { algorithm: "bcrypt", cost: 4 });
console.log("salted", a !== b, P.verifySync("same", a), P.verifySync("same", b));
console.log("string-option", shape(P.hashSync("alias", "bcrypt")));
console.log("aliases", ["$2a", "$2y", "$2x"].map((p) => P.verifySync("same", p + a.slice(3))).join(","));
const long = "x".repeat(100);
const lb = P.hashSync(long, { algorithm: "bcrypt", cost: 4 });
console.log("long", P.verifySync(long, lb), P.verifySync("x".repeat(72), lb), P.verifySync("x".repeat(99), lb));
const b72 = P.hashSync("y".repeat(72), { algorithm: "bcrypt", cost: 4 });
console.log("72", P.verifySync("y".repeat(72), b72), P.verifySync("y".repeat(73), b72), P.verifySync("y".repeat(71), b72));
const empty = P.hashSync("", { algorithm: "argon2id", memoryCost: 8, timeCost: 1 });
console.log("empty", shape(empty), P.verifySync("", empty), P.verifySync(" ", empty));
const bin = P.hashSync(new Uint8Array([0, 1, 2, 255]), { algorithm: "bcrypt", cost: 4 });
console.log("binary", P.verifySync(new Uint8Array([0, 1, 2, 255]), bin), P.verifySync(new Uint8Array([0, 1, 2]), bin));
const t = (label, f) => { try { console.log(label, "->", f()); } catch (e) { console.log(label, "threw", e.name + ": " + e.message); } };
t("hash md5", () => P.hashSync("x", "md5"));
t("hash scrypt obj", () => P.hashSync("x", { algorithm: "scrypt" }));
t("cost 3", () => P.hashSync("x", { algorithm: "bcrypt", cost: 3 }));
t("cost 32", () => P.hashSync("x", { algorithm: "bcrypt", cost: 32 }));
t("cost 4.5", () => P.hashSync("x", { algorithm: "bcrypt", cost: 4.5 }));
t("cost str", () => P.hashSync("x", { algorithm: "bcrypt", cost: "4" }));
t("memoryCost 0", () => P.hashSync("x", { memoryCost: 0 }));
t("timeCost 0", () => P.hashSync("x", { algorithm: "argon2i", memoryCost: 8, timeCost: 0 }));
t("timeCost 2^32", () => P.hashSync("x", { memoryCost: 8, timeCost: 2 ** 32 }));
t("options 42", () => P.hashSync("x", 42));
t("options null", () => P.hashSync("x", null));
const bad = ["not-a-hash", "", "$1$abc$def", "$2c$04$vVj0LFIN/tWPPW6l9KVfb./2Cr91.SdAmARN0zGOD41OBzylfgoGK",
  "$2b$04$tooshort", "$2b$99$vVj0LFIN/tWPPW6l9KVfb./2Cr91.SdAmARN0zGOD41OBzylfgoGK",
  "$2b$03$vVj0LFIN/tWPPW6l9KVfb./2Cr91.SdAmARN0zGOD41OBzylfgoGK", "$2b$04XvVj0LFIN/tWPPW6l9KVfb./2Cr91.SdAmARN0zGOD41OBzylfgoGK",
  "$2b$04$!!!!LFIN/tWPPW6l9KVfb./2Cr91.SdAmARN0zGOD41OBzylfgoGK",
  "$argon2id$v=19$m=64,t=2,p=1$!!bad!!$tag", "$argon2id$v=19$m=64,t=0,p=1$AAAAAAAA$AAAAAAAA",
  "$argon2id$v=18$m=64,t=1,p=1$AAAAAAAA$AAAAAAAA", "$argon2x$v=19$m=64,t=1,p=1$AAAAAAAA$AAAAAAAA",
  "$argon2id$v=19$m=64,t=1,q=1$AAAAAAAA$AAAAAAAA", "$argon2id$v=19$m=64,t=1$AAAAAAAA$AAAAAAAA",
  "$argon2id$v=19$m=64,t=1,p=1$AAAAAAAA$AAAAAAAA$extra", "$argon2id$v=19$m=64,t=1,p=1$AAAAAAAA",
  "$argon2id$v=19$m=64,t=1,p=1$$AAAAAAAA", "$argon2id$v=19$m=64,t=1,p=1$AAAAAAAA$AA", "$argon2id$v=19$m=x,t=1,p=1$AAAAAAAA$AAAAAAAA",
  "$argon2id$v=19$m=64,t=1,p=1$AAAAA$AAAAAAAA", "$argon2id$v=19$m=64,t=1,p=0$AAAAAAAA$AAAAAAAA"];
for (const h of bad) t("verify " + JSON.stringify(h), () => P.verifySync("x", h));
(async () => {
  const ah = await P.hash("async-pw", { algorithm: "bcrypt", cost: 4 });
  console.log("async", shape(ah), await P.verify("async-pw", ah), await P.verify("nope", ah));
  const aa = await P.hash(new TextEncoder().encode("bytes"), { algorithm: "argon2d", memoryCost: 8, timeCost: 1 });
  console.log("async argon2d", shape(aa), await P.verify("bytes", aa));
  console.log("default", shape(await P.hash("default options")));
  for (const [label, p] of [["verify garbage", () => P.verify("x", "garbage")], ["verify bad b64", () => P.verify("x", "$argon2i$v=19$m=8,t=1,p=1$***$AAAA")],
                            ["hash scrypt", () => P.hash("x", { algorithm: "scrypt" })], ["hash cost 99", () => P.hash("x", { algorithm: "bcrypt", cost: 99 })]]) {
    try { console.log(label, "resolved", await p()); } catch (e) { console.log(label, "rejected", e.name + ": " + e.message); }
  }
  console.log("surface", Object.keys(P).sort().join(","), typeof P.needsRehash);
})();
''')


def test_cookie_and_cookie_map(run, workdir):
    """CATCHES: Bun.Cookie parsing that keeps attribute case (Domain lowercased, SameSite normalised),
    wrong defaults (Path=/, SameSite=Lax), wrong serialisation order or value encoding, Max-Age not
    truncated, isExpired() ignoring maxAge <= 0, toJSON key order, and CookieMap not decoding values,
    skipping malformed pairs, tracking set()/delete() for toSetCookieHeaders, or accepting the
    object/array/Map constructor forms; also the exact TypeError messages for bad input."""
    check_script(run, workdir, G, "cookie_and_cookie_map", r'''
const t = (label, f) => { try { const v = f(); console.log(label, typeof v === "string" ? v : JSON.stringify(v)); } catch (e) { console.log(label, "threw", e.name + ": " + e.message); } };
const c = new Bun.Cookie("session=a b; Domain=EXAMPLE.COM; Max-Age=60; HttpOnly; Secure; SameSite=None; Partitioned; Path=/app");
t("fields", () => [c.name, c.value, c.domain, c.path, c.maxAge, c.secure, c.httpOnly, c.sameSite, c.partitioned, c.isExpired(), c.expires === undefined]);
t("toString", () => c.toString());
t("serialize", () => c.serialize());
t("toJSON", () => c.toJSON());
t("tag", () => Object.prototype.toString.call(c));
t("3-arg", () => String(new Bun.Cookie("id", "x;y=z é", { secure: true, sameSite: "STRICT", maxAge: 3.9, domain: "Sub.Example.org" })));
t("sameSite-true", () => String(new Bun.Cookie("id", "v", { sameSite: true })));
t("sameSite-false", () => String(new Bun.Cookie("id", "v", { sameSite: false })));
t("sameSite-bogus", () => new Bun.Cookie("id", "v", { sameSite: "bogus" }).toJSON());
t("expires", () => String(new Bun.Cookie({ name: "e", value: "1", expires: Date.UTC(2030, 0, 2, 3, 4, 5), httpOnly: 1 })));
t("expires-json", () => new Bun.Cookie({ name: "e", value: "1", expires: Date.UTC(2030, 0, 2, 3, 4, 5) }).toJSON());
t("expired-past", () => new Bun.Cookie({ name: "e", value: "1", expires: Date.UTC(2001, 0, 1) }).isExpired());
t("expired-far-future", () => new Bun.Cookie({ name: "e", value: "1", expires: Date.UTC(2999, 0, 1) }).isExpired());
t("maxAge0", () => [new Bun.Cookie({ name: "o", value: "x", maxAge: 0 }).isExpired(), new Bun.Cookie({ name: "o", value: "x", maxAge: 1 }).isExpired()]);
t("maxAge-neg", () => String(new Bun.Cookie({ name: "neg", value: "x", maxAge: -1 })));
t("attrs-case", () => String(new Bun.Cookie("k=v; PATH=/p; max-age=10; SECURE; samesite=lax; httponly; unknown=1")));
t("empty-value", () => new Bun.Cookie("k=").toJSON());
t("spaces", () => new Bun.Cookie("  k  =  v w  ; path = /x ").toJSON());
t("no-args", () => new Bun.Cookie());
t("no-equals", () => new Bun.Cookie("noequals"));
t("empty-name", () => new Bun.Cookie("=v"));
t("missing-value", () => new Bun.Cookie({ name: "a" }));
const m = new Bun.CookieMap("a=1; b=two%20words; bad; c=%E0%A4%A; d = spaced ;=empty");
t("map-init", () => [m.size, [...m]]);
m.set("c", "three", { httpOnly: true });
m.set({ name: "d", value: "four", secure: true, domain: "Ex.com" });
m.set(new Bun.Cookie("z=9; Path=/z"));
t("map-get", () => [m.size, m.get("b"), m.get("nope") === undefined, m.has("a"), m.has("zz"), m.get("c")]);
t("map-headers", () => m.toSetCookieHeaders());
m.delete("a");
m.delete("c");
m.delete("never-there");
t("map-after-delete", () => [m.toJSON(), m.size, [...m.keys()], [...m.values()]]);
t("map-headers-2", () => m.toSetCookieHeaders());
const seen = [];
m.forEach(function (v, k, mm) { seen.push(k + "=" + v + ":" + (mm === m) + ":" + this.tag); }, { tag: "T" });
t("forEach", () => seen);
t("entries", () => [...m.entries()].length);
t("from-object", () => [...new Bun.CookieMap({ x: 1, y: true })]);
t("from-array", () => [...new Bun.CookieMap([["p", 1], ["q", "2"]])]);
t("from-map", () => [...new Bun.CookieMap(new Map([["m", "v"]]))]);
t("from-nothing", () => [new Bun.CookieMap().size, new Bun.CookieMap("").size, new Bun.CookieMap(null).size, new Bun.CookieMap().toSetCookieHeaders()]);
t("map-tag", () => Object.prototype.toString.call(new Bun.CookieMap()));
''')


def test_csrf_tokens(run, workdir):
    """CATCHES: Bun.CSRF.verify not checking the HMAC over the 32-byte header with the given secret and
    algorithm, ignoring the embedded expiry / maxAge override (0 = never expires), accepting tokens from
    the future, tampered or truncated tokens, or the wrong encoding; generate() producing the wrong token
    length per algorithm/encoding or wrong expiresIn field; and the exact errors for bad options."""
    check_script(run, workdir, G, "csrf_tokens", r'''
const crypto = require("crypto");
// Tokens are header(created u64 BE | 16 nonce bytes | expiresIn u64 BE) + HMAC(header); build fixed ones.
function token(secret, created, expiresIn, { algorithm = "sha256", encoding = "base64url", nonceByte = 7 } = {}) {
  const header = Buffer.alloc(32);
  const dv = new DataView(header.buffer, header.byteOffset, 32);
  dv.setBigUint64(0, BigInt(created));
  header.fill(nonceByte, 8, 24);
  dv.setBigUint64(24, BigInt(expiresIn));
  const mac = crypto.createHmac(algorithm, secret).update(header).digest();
  return Buffer.concat([header, mac]).toString(encoding);
}
const V = Bun.CSRF.verify;
const bunToken = "AAABn1fI5Od0CO5U9mfXAcdR-7jbHCDuAAAAAAAAAACu5U1Sonwv5CNX3c5KeMX_R-OA3WsNYhUqBrFb4TXcXg";
console.log("bun-token", V(bunToken, { secret: "interop-secret" }), V(bunToken, { secret: "other" }), V(bunToken));
const t0 = token("s3", 1600000000000, 0);
console.log("built", t0, t0.length);
console.log("no-expiry", V(t0, { secret: "s3" }), V(t0, { secret: "s4" }), V(t0, { secret: "s3", maxAge: 1000 }));
const t1 = token("s3", 1600000000000, 1000);
console.log("expired", V(t1, { secret: "s3" }), V(t1, { secret: "s3", maxAge: 0 }), V(t1, { secret: "s3", maxAge: 4e12 }));
const tf = token("s3", 4000000000000, 5000);
console.log("from-future", V(tf, { secret: "s3" }), V(tf, { secret: "s3", maxAge: 0 }));
const th = token("k", 1600000000000, 0, { algorithm: "sha512", encoding: "hex" });
console.log("hex-sha512", th.length, V(th, { secret: "k", algorithm: "sha512", encoding: "hex" }), V(th, { secret: "k", encoding: "hex" }),
            V(th, { secret: "k", algorithm: "SHA512", encoding: "hex" }), V(th, { secret: "k", algorithm: "sha512" }));
const t384 = token("k", 1600000000000, 0, { algorithm: "sha384", encoding: "base64" });
console.log("base64-sha384", t384.length, V(t384, { secret: "k", algorithm: "sha384", encoding: "base64" }));
console.log("sha512-256", V(token("k", 1600000000000, 0, { algorithm: "sha512-256" }), { secret: "k", algorithm: "sha512-256" }));
const flip = t0.slice(0, 50) + (t0[50] === "A" ? "B" : "A") + t0.slice(51);
console.log("rejects", V(flip, { secret: "s3" }), V(t0.slice(1), { secret: "s3" }), V(t0 + "AA", { secret: "s3" }), V("", { secret: "s3" }),
            V("!!!", { secret: "s3" }), V(t0, { secret: "s3", algorithm: "md5" }), V(t0, { secret: "s3", encoding: "utf8" }), V(undefined));
const g = Bun.CSRF.generate("sec", { expiresIn: 0 });
console.log("generate", g.length, /^[A-Za-z0-9_-]+$/.test(g), V(g, { secret: "sec" }), V(g, { secret: "nope" }), V(g));
const gd = Bun.CSRF.generate();
console.log("generate-default-secret", gd.length, V(gd), V(gd, { secret: "x" }));
const gh = Bun.CSRF.generate("sec", { encoding: "hex", algorithm: "sha384" });
console.log("generate-hex", gh.length, /^[0-9a-f]+$/.test(gh), V(gh, { secret: "sec", encoding: "hex", algorithm: "sha384" }));
const gb = Bun.CSRF.generate("sec", { encoding: "base64", algorithm: "sha512" });
console.log("generate-base64", gb.length, V(gb, { secret: "sec", encoding: "base64", algorithm: "sha512" }));
const expiresField = (tok) => { const b = Buffer.from(tok, "base64url"); return String(new DataView(b.buffer, b.byteOffset, b.length).getBigUint64(24)); };
console.log("expires-field", expiresField(g), expiresField(Bun.CSRF.generate("s", { expiresIn: 1234 })), expiresField(gd));
for (const opts of [{ encoding: "utf8" }, { algorithm: "md5" }, { algorithm: "sha1" }, { expiresIn: -1 }, { expiresIn: NaN }]) {
  try { Bun.CSRF.generate("s", opts); console.log("no error for", JSON.stringify(opts)); } catch (e) { console.log("error", e.name + ": " + e.message); }
}
''')

PAGES = {name: "" for name in [
    "pages/index.tsx", "pages/settings.tsx", "pages/about.jsx", "pages/readme.md", "pages/blog/index.tsx",
    "pages/blog/[slug].tsx", "pages/[...all].tsx", "pages/docs/[[...path]].js", "pages/api/users/[id].ts",
    "pages/shop/[cat].jsx", "pages/shop/[cat]/[item].tsx"]}


def test_filesystem_router_nextjs(run, workdir):
    """CATCHES: Bun.FileSystemRouter route discovery/ordering mistakes (index files, nested dynamic
    segments, catch-all vs optional catch-all precedence), wrong match() results (kind, name, decoded
    params, query merging repeated keys with params winning, pathname, src built from origin +
    assetPrefix, filePath), reload() not picking up new files, fileExtensions normalisation, and the
    exact constructor/match errors."""
    write_files(workdir, PAGES)
    check_script(run, workdir, G, "filesystem_router_nextjs", r'''
const fs = require("fs");
const base = fs.realpathSync(".");
const clean = (s) => typeof s === "string" ? s.split(base).join("<cwd>") : s;
const router = new Bun.FileSystemRouter({ style: "nextjs", dir: "./pages", origin: "https://example.test/", assetPrefix: "/assets/" });
console.log(clean(router.dir), router.style, router.origin, router.assetPrefix, JSON.stringify(router.fileExtensions));
for (const [k, v] of Object.entries(router.routes)) console.log("route", k, clean(v));
for (const input of ["/", "/blog", "/blog/", "/blog/hello%20world?q=a%20b&q=c&r=1", "/one/two/three", "/docs", "/docs/a/b",
                     "/api/users/42?id=override", "/shop/shoes", "/shop/shoes/red", "/settings?x=1#frag", "/about", "/readme",
                     "http://other.host/blog/x", "https://example.test/settings", "/%E4%BD%A0%E5%A5%BD"]) {
  const r = router.match(input);
  if (!r) { console.log(input, "-> null"); continue; }
  console.log(input, "->", r.kind, r.name, JSON.stringify(r.params), JSON.stringify(r.query), r.pathname, r.src, clean(r.filePath),
              JSON.stringify(Object.keys(r)));
}
console.log("request", router.match(new Request("https://example.test/blog/req?z=1")).name);
try { router.match(42); } catch (e) { console.log(e.name + ": " + e.message); }
fs.writeFileSync("pages/new.tsx", "");
console.log("before reload", router.match("/new").name);
router.reload();
console.log("after reload", router.match("/new").name, Object.keys(router.routes).includes("/new"));
for (const opts of [undefined, {}, { style: "remix", dir: "./pages" }, { style: "nextjs", dir: "./missing" }, { style: "nextjs" },
                    { style: "nextjs", dir: "./pages/index.tsx" }]) {
  try { new Bun.FileSystemRouter(opts); console.log("constructed"); } catch (e) { console.log(e.name + ": " + clean(e.message)); }
}
const r2 = new Bun.FileSystemRouter({ style: "nextjs", dir: "pages", fileExtensions: ["jsx", "*.md"] });
console.log(r2.origin, r2.assetPrefix === "", JSON.stringify(r2.fileExtensions), JSON.stringify(Object.keys(r2.routes)), r2.match("/readme").src,
            r2.match("/nothing-here"), Object.prototype.toString.call(r2));
''')


def test_bun_file_and_write(run, workdir):
    """CATCHES: Bun.write returning something other than the byte count or writing the wrong bytes for
    strings/TypedArrays/ArrayBuffers/arrays of parts/Blobs/Responses/other BunFiles/numbers; Bun.file
    size/type (MIME by extension, explicit type), exists(), text/json/bytes/arrayBuffer/slice/stream/
    stat, FileSink write/flush/end appending, delete(), and the ENOENT error for missing files."""
    r = check_script(run, workdir, G, "bun_file_and_write", r'''
(async () => {
  const log = (...a) => console.log(...a);
  log("written", await Bun.write("a.txt", "héllo\nworld\n"), await Bun.write("b.bin", new Uint8Array([0, 1, 2, 255])),
      await Bun.write("c.json", JSON.stringify({ k: [1, 2], s: "x" })), await Bun.write("d.txt", ["ab", new Uint8Array([67, 68]), "ef"]),
      await Bun.write("e.txt", Bun.file("a.txt")), await Bun.write("f.txt", new Blob(["blob", "!"])),
      await Bun.write("g.txt", new Response("resp body")), await Bun.write(Bun.file("h.txt"), 12345),
      await Bun.write("i.bin", new Uint16Array([0x4142, 0x4344]).buffer), await Bun.write("empty.txt", ""));
  const f = Bun.file("a.txt");
  log("meta", f.name, f.size, f.type, typeof f.lastModified, await f.exists(), await Bun.file("nope.txt").exists(), Bun.file("nope.txt").size);
  log("text", JSON.stringify(await f.text()), JSON.stringify(await Bun.file("c.json").json()));
  log("bytes", Array.from(await Bun.file("b.bin").bytes()).join(","), (await Bun.file("b.bin").arrayBuffer()).byteLength,
      Bun.file("empty.txt").size, JSON.stringify(await Bun.file("empty.txt").text()));
  const types = [];
  for (const n of ["x.js", "x.mjs", "x.cjs", "x.json", "x.html", "x.htm", "x.css", "x.txt", "x.png", "x.jpg", "x.svg", "x.wasm", "x.pdf", "x.unknown",
                   "noext", "X.PNG", "x.md", "x.csv", "x.gz", "x.tar.gz", "x.woff2", "x.ico"]) types.push(n + "=" + Bun.file(n).type);
  log(types.join("\n"));
  log("explicit-type", Bun.file("z.dat", { type: "application/x-custom" }).type);
  const sl = f.slice(1, 5);
  log("slice", sl.constructor.name, sl.size, JSON.stringify(await sl.text()), (await f.slice(-6).text()).trim());
  const rd = f.stream().getReader(); const first = await rd.read(); log("stream", first.value.length, first.done, (await rd.read()).done);
  log("stream-text", await Bun.readableStreamToText(Bun.file("d.txt").stream()));
  const w = Bun.file("sink.txt").writer();
  log("sink", w.write("one "), w.write(new Uint8Array([84, 87, 79])), w.flush(), w.write(" three"), w.end());
  log("sink-content", JSON.stringify(await Bun.file("sink.txt").text()));
  await Bun.file("e.txt").delete();
  log("deleted", await Bun.file("e.txt").exists());
  try { await Bun.file("nope.txt").text(); } catch (e) { log("missing", e.name, e.code); }
  log("rewrite", await Bun.file("h.txt").write("rewritten"), await Bun.file("h.txt").text());
  const st = await Bun.file("b.bin").stat(); log("stat", st.size, st.isFile(), st.isDirectory());
})();
''')
    for name, expected in [("a.txt", "héllo\nworld\n".encode()), ("b.bin", b"\x00\x01\x02\xff"), ("c.json", b'{"k":[1,2],"s":"x"}'),
                           ("d.txt", b"abCDef"), ("f.txt", b"blob!"), ("g.txt", b"resp body"), ("h.txt", b"rewritten"),
                           ("i.bin", b"BADC"), ("sink.txt", b"one TWO three"), ("empty.txt", b"")]:
        assert (workdir / name).read_bytes() == expected, name
    assert not (workdir / "e.txt").exists()


def test_glob_scan_and_match(run, workdir):
    """CATCHES: Bun.Glob '*' crossing directory separators, '**' not matching zero or more directories,
    '?' matching '/', regex metacharacters in patterns not escaped, hidden files returned without
    {dot:true}, directories returned without {onlyFiles:false}, cwd option/string handling, async scan()
    differing from scanSync(); also pins that this runtime treats {a,b} and [ab] literally."""
    write_files(workdir, {name: "" for name in [
        "src/a.ts", "src/b.js", "src/lib/c.ts", "src/lib/deep/d.ts", "src/lib/deep/e.md", ".hidden/h.ts", ".dot.ts",
        "docs/readme.md", "top.ts", "src/we ird[1].ts", "src/a+b(c).ts"]})
    check_script(run, workdir, G, "glob_scan_and_match", r'''
(async () => {
const t = (label, f) => { try { console.log(label, JSON.stringify(f())); } catch (e) { console.log(label, "threw", e.name + ": " + e.message); } };
for (const p of ["*.ts", "**/*.ts", "src/**/*.ts", "src/*", "**/deep/*", "src/?.ts", "**/*.md", "src/**", "src/we ird[1].ts",
                 "src/a+b(c).ts", "**/*.{ts,md}", "*", "**/lib/**/*.ts"]) {
  t(p, () => new Bun.Glob(p).scanSync(".").filter((f) => f !== "glob_scan_and_match.js").sort());
}
t("dot", () => new Bun.Glob("**/*.ts").scanSync({ cwd: ".", dot: true }).sort());
t("dirs", () => new Bun.Glob("src/**").scanSync({ cwd: ".", onlyFiles: false }).sort());
t("cwd-sub", () => new Bun.Glob("**/*.ts").scanSync({ cwd: "src" }).sort());
t("missing-dir", () => new Bun.Glob("*").scanSync("nope"));
const g = new Bun.Glob("src/**/*.ts");
t("match", () => ["src/a.ts", "src/x/y/z.ts", "src/a.js", "lib/a.ts", "src/.ts", "src/a.ts/", "SRC/a.ts"].map((s) => g.match(s)));
t("match2", () => [new Bun.Glob("a?c").match("abc"), new Bun.Glob("a?c").match("a/c"), new Bun.Glob("*.js").match("x/y.js"),
                   new Bun.Glob("**/*.js").match("y.js"), new Bun.Glob("a+b(c)").match("a+b(c)"), new Bun.Glob("a.b").match("axb"),
                   new Bun.Glob("$^|").match("$^|"), new Bun.Glob("*.{js,ts}").match("a.js"), new Bun.Glob("*.{js,ts}").match("a.{js,ts}"),
                   new Bun.Glob("[ab].txt").match("a.txt"), new Bun.Glob("[ab].txt").match("[ab].txt"), new Bun.Glob("").match("")]);
const out = [];
for await (const f of new Bun.Glob("**/*.md").scan(".")) out.push(f);
console.log("async", JSON.stringify(out.sort()));
const out2 = [];
for await (const f of new Bun.Glob("*.ts").scan({ cwd: ".", dot: true })) out2.push(f);
console.log("async-dot", JSON.stringify(out2.sort()), new Bun.Glob("x/*").pattern);
})();
''')


def test_string_helpers_and_deep_equals(run, workdir):
    """CATCHES: Bun.escapeHTML missing one of & < > " ' (or using &#39; instead of &#x27;), not
    stringifying non-strings; Bun.stripANSI leaving CSI/OSC/8-bit CSI sequences; Bun.stringWidth
    counting East-Asian wide/fullwidth chars as 1, counting zero-width/combining marks or ANSI codes;
    Bun.deepEquals strict mode (prototypes, undefined-valued keys) vs loose mode, Dates/RegExps/Maps/
    Sets/TypedArrays/cycles; Bun.deepMatch subset semantics; Bun.inspect formatting."""
    check_script(run, workdir, G, "string_helpers_and_deep_equals", r'''
const t = (label, v) => console.log(label, JSON.stringify(v));
t("escape", [Bun.escapeHTML(`<a href="x" title='y'>Tom & Jerry</a>`), Bun.escapeHTML(42), Bun.escapeHTML(""), Bun.escapeHTML("no specials ünïcode 🌍"),
             Bun.escapeHTML({ toString() { return "<obj>"; } }), Bun.escapeHTML(null), Bun.escapeHTML("&amp;&&"), Bun.escapeHTML("<<>>")]);
t("strip", [Bun.stripANSI("\x1b[31mred\x1b[0m plain \x1b[1;4;38;2;10;20;30mbold\x1b[m"), Bun.stripANSI("\x1b]8;;https://x.test\x07link\x1b]8;;\x07 end"),
            Bun.stripANSI("\u009b32mcsi8\u009bm"), Bun.stripANSI("nothing"), Bun.stripANSI("\x1b[2J\x1b[H\x1b[?25lcur\x1b[?25h"), Bun.stripANSI(7)]);
t("width", [Bun.stringWidth("hello"), Bun.stringWidth(""), Bun.stringWidth("你好"), Bun.stringWidth("\x1b[31mab\x1b[0m"), Bun.stringWidth("🌍x"),
            Bun.stringWidth("é"), Bun.stringWidth("e\u0301"), Bun.stringWidth("a\u200bb"), Bun.stringWidth("ｱＡ"), Bun.stringWidth("한국어"),
            Bun.stringWidth(12345), Bun.stringWidth("\u3000|"), Bun.stringWidth("ᄀ")]);
class A { constructor() { this.x = 1; } }
const cyc1 = { n: 1 }; cyc1.self = cyc1;
const cyc2 = { n: 1 }; cyc2.self = cyc2;
const pairs = [
  ["nested", { a: [1, { b: 2 }] }, { a: [1, { b: 2 }] }], ["extra-undef-key", { a: 1 }, { a: 1, b: undefined }],
  ["array-len", [1, 2], [1, 2, 3]], ["num-vs-str", 1, "1"], ["NaN", NaN, NaN], ["zeros", 0, -0], ["class-vs-plain", new A(), { x: 1 }],
  ["dates", new Date(5), new Date(5)], ["dates-differ", new Date(5), new Date(6)], ["regex", /a/g, /a/g], ["regex-flags", /a/g, /a/i],
  ["maps", new Map([[1, { a: 1 }]]), new Map([[1, { a: 1 }]])], ["maps-differ", new Map([[1, 2]]), new Map([[1, 3]])],
  ["sets", new Set([1, 2]), new Set([2, 1])], ["sets-differ", new Set([1]), new Set([2])], ["u8", new Uint8Array([1, 2]), new Uint8Array([1, 2])],
  ["u8-differ", new Uint8Array([1, 2]), new Uint8Array([1, 3])], ["array-vs-object", [1], { 0: 1 }], ["null-undef", null, undefined],
  ["null-object", null, {}], ["cycles", cyc1, cyc2], ["undef-vs-null-elem", [undefined], [null]], ["hole", [, 1], [undefined, 1]],
  ["different-keys", { a: undefined }, { b: undefined }], ["strings", "abc", "abc"], ["key-order", { a: 1, b: 2 }, { b: 2, a: 1 }],
];
for (const [label, a, b] of pairs) console.log("deepEquals", label, Bun.deepEquals(a, b), Bun.deepEquals(a, b, true));
t("deepMatch", [Bun.deepMatch({ a: 1 }, { a: 1, b: 2 }), Bun.deepMatch({ a: 1, b: 2 }, { a: 1 }), Bun.deepMatch({ a: { b: 1 } }, { a: { b: 1, c: 2 } }),
                Bun.deepMatch([1, 2], [1, 2]), Bun.deepMatch([1], [1, 2]), Bun.deepMatch({ a: [{ x: 1 }] }, { a: [{ x: 1, y: 2 }] }),
                Bun.deepMatch(1, 1), Bun.deepMatch(NaN, NaN), Bun.deepMatch({}, null), Bun.deepMatch({ a: undefined }, {}),
                Bun.deepMatch({ a: undefined }, { a: undefined }), Bun.deepMatch({}, { anything: 1 }), Bun.deepMatch("a", "b")]);
console.log(Bun.inspect({ a: 1, s: "x", arr: [1, 2, [3, [4, [5]]]], m: new Map([["k", 1]]), set: new Set(["v"]), n: null, u: undefined }));
console.log(Bun.inspect("str"), Bun.inspect(12n), Bun.inspect([1, "two", { three: 3 }]), Bun.inspect({ deep: { er: { est: { x: 1 } } } }, { depth: 0 }));
console.log(Bun.inspect({ [Bun.inspect.custom]() { return "CUSTOM"; } }), Bun.inspect.custom === require("util").inspect.custom);
''')


def test_buffer_and_stream_helpers(run, workdir):
    """CATCHES: Bun.concatArrayBuffers ignoring maxLength / the asUint8Array flag or mis-reading
    TypedArray views and strings; Bun.indexOfLine offset handling; Bun.ArrayBufferSink stream vs
    non-stream flush semantics and return types; readableStreamToText/JSON/Bytes/ArrayBuffer/Array/Blob/
    FormData collecting chunks wrongly; Bun.gzipSync/deflateSync round trips returning non-Uint8Array;
    Bun.which not returning null for missing commands or resolving PATH entries wrongly."""
    write_files(workdir, {"bin/mytool": "#!/bin/sh\n", "bin2/mytool": "#!/bin/sh\n"})
    check_script(run, workdir, G, "buffer_and_stream_helpers", r'''
(async () => {
const show = (v) => v instanceof ArrayBuffer ? "ArrayBuffer[" + new Uint8Array(v).join(",") + "]"
  : v instanceof Uint8Array ? v.constructor.name + "[" + Array.from(v).join(",") + "]" : JSON.stringify(v);
const t = (label, v) => console.log(label, show(v));
t("concat", Bun.concatArrayBuffers([new Uint8Array([1, 2]), new Uint8Array([3]).buffer, "hi", new Uint16Array([0x0201])]));
t("concat-max", Bun.concatArrayBuffers([new Uint8Array([1, 2]), new Uint8Array([3, 4, 5])], 4));
t("concat-u8", Bun.concatArrayBuffers([new Uint8Array([1, 2]), new Uint8Array([3, 4, 5])], true));
t("concat-max-u8", Bun.concatArrayBuffers([new Uint8Array([1, 2]), new Uint8Array([3, 4, 5])], 3, true));
t("concat-empty", Bun.concatArrayBuffers([]));
t("concat-view", Bun.concatArrayBuffers([new Uint8Array([9, 8, 7, 6]).subarray(1, 3)], 10));
t("indexOfLine", [Bun.indexOfLine("ab\ncd\n"), Bun.indexOfLine("ab\ncd\n", 3), Bun.indexOfLine("ab\ncd\n", 6),
                  Bun.indexOfLine(new Uint8Array([1, 10, 2, 10]), 2), Bun.indexOfLine("none"), Bun.indexOfLine("\n")]);
const s = new Bun.ArrayBufferSink();
s.start();
t("sink-write", [s.write("ab"), s.write(new Uint8Array([1, 2, 3])), s.write(new Uint8Array([7]).buffer)]);
t("sink-flush", s.flush());
t("sink-end", s.end());
t("sink-end-again", s.end());
const s2 = new Bun.ArrayBufferSink();
s2.start({ stream: true, asUint8Array: true });
s2.write("xy"); t("stream-flush", s2.flush()); s2.write("z"); t("stream-end", s2.end()); t("stream-empty", s2.end());
const mk = (chunks) => new ReadableStream({ start(c) { for (const ch of chunks) c.enqueue(ch); c.close(); } });
const enc = new TextEncoder();
t("toText", await Bun.readableStreamToText(mk([enc.encode("hé"), enc.encode("llo")])));
t("toText-split-utf8", await Bun.readableStreamToText(mk([new Uint8Array([0xe4, 0xbd]), new Uint8Array([0xa0])])));
t("toJSON", await Bun.readableStreamToJSON(mk([enc.encode('{"a":'), enc.encode('[1,2]}')])));
t("toBytes", await Bun.readableStreamToBytes(mk([new Uint8Array([1, 2]), new Uint8Array([3])])));
t("toArrayBuffer", await Bun.readableStreamToArrayBuffer(mk([new Uint8Array([4, 5])])));
t("toArray", await Bun.readableStreamToArray(mk(["a", 1, { x: 2 }])));
t("toText-empty", await Bun.readableStreamToText(mk([])));
const blob = await Bun.readableStreamToBlob(mk([enc.encode("blobby")]));
t("toBlob", [blob.constructor.name, blob.size, await blob.text()]);
try { await Bun.readableStreamToJSON(mk([enc.encode("{bad")])); } catch (e) { t("bad-json", e.name); }
const fd = await Bun.readableStreamToFormData(mk([enc.encode("--B\r\nContent-Disposition: form-data; name=\"f\"\r\n\r\nval\r\n--B--\r\n")]), "B");
t("formData", [fd.get("f")]);
t("allocUnsafe", [Bun.allocUnsafe(5).length, Bun.allocUnsafe(0).length, Buffer.isBuffer(Bun.allocUnsafe(3))]);
const gz = Bun.gzipSync("hello hello hello");
t("gzip", [gz.constructor.name, gz[0], gz[1], new TextDecoder().decode(Bun.gunzipSync(gz))]);
const df = Bun.deflateSync(new Uint8Array(100).fill(65));
t("deflate", [df.constructor.name, df.length < 100, Bun.inflateSync(df).length, Bun.inflateSync(df)[99]]);
const cwd = process.cwd();
t("which", [Bun.which("definitely-not-a-real-command-xyz"), Bun.which("./nope/x"), Bun.which("mytool", { PATH: "" }),
            Bun.which("mytool", { PATH: "bin2:bin" }).replace(cwd, "<cwd>"), Bun.which("mytool", { PATH: "missing:bin" }).replace(cwd, "<cwd>"),
            Bun.which("mytool", { PATH: "bin", cwd: "/" })]);
// A relative path with a slash goes through path.resolve, which (in this runtime) drops the leading "/".
const rel = Bun.which("bin/mytool");
t("which-relative", [rel.startsWith("/"), rel.replace(cwd.slice(1), "<cwd-without-leading-slash>")]);
})();
''')


def test_toml_yaml_semver_color(run, workdir):
    """CATCHES: Bun.TOML.parse mishandling comments, escapes, literal strings, underscores/hex ints,
    floats, multi-line arrays, dotted keys, [table] / [table.sub] / [[array of tables]]; Bun.YAML.parse
    scalars (bool/null/~/numbers/quoted), block and flow sequences/maps, nesting; YAML.stringify layout;
    Bun.semver.satisfies range operators (^ ~ x-ranges, hyphen ranges, ||, prereleases) and order();
    Bun.color input parsing and output formats, null for garbage, error for unknown formats."""
    check_script(run, workdir, G, "toml_yaml_semver_color", r'''
const t = (label, f) => { try { console.log(label, JSON.stringify(f())); } catch (e) { console.log(label, "threw", e.name + ": " + e.message); } };
t("toml", () => Bun.TOML.parse(`
# comment
title = "TOML \\"Example\\"\\t|\\\\" # trailing
literal = 'C:\\path'
int = 1_000
neg = -17
hex = 0xff
flt = 3.14
exp = 5e+2
bool = true
off = false
date = 1979-05-27T07:32:00Z
arr = [1, 2, 3]
nested = [[1, 2], ["a"]]
multi = [
  "x",
  "y", # c
]
inline = { a = 1, b = "two" }
a.b.c = 1
"quoted key" = 2

[server]
host = "localhost"
ports = [8000, 8001]

[server.limits]
max = 10

[[products]]
name = "Hammer"
sku = 738594937

[[products]]
name = "Nail"
color = "gray"
`));
t("toml-empty", () => Bun.TOML.parse(""));
t("yaml", () => Bun.YAML.parse(`
# comment
name: lumen
version: 1.2
count: 42
enabled: true
off: false
nothing: null
tilde: ~
quoted: "a: b"
single: 'it''s'
list:
  - one
  - 2
  - three: 3
flow: [1, two, "3"]
map: {a: 1, b: x}
nested:
  deep:
    deeper: yes
empty:
`));
t("yaml-list", () => Bun.YAML.parse("- a\n- 1\n- true\n"));
t("yaml-stringify", () => Bun.YAML.stringify({ a: 1, b: [1, "two", { c: null }], d: { e: true }, s: "x: y" }));
const sat = [["1.2.3", "^1.0.0"], ["2.0.0", "^1.0.0"], ["1.2.3", "~1.2.0"], ["1.3.0", "~1.2.0"], ["1.2.3", ">=1.2.3 <2"], ["1.2.3", "1.x"],
  ["1.2.3", "1.2.0 - 1.3.0"], ["1.0.0-beta.1", "^1.0.0"], ["1.0.0-beta.2", ">=1.0.0-beta.1"], ["3.0.0", "^1.0.0 || ^3.0.0"],
  ["0.2.5", "^0.2.0"], ["0.3.0", "^0.2.0"], ["1.2.3", "*"], ["v1.2.3", "=1.2.3"], ["not.a.version", "*"], ["1.2.3", "<1.2.3"],
  ["1.2.3", "<=1.2.3"], ["1.2.3", ">1.2"], ["0.0.3", "^0.0.3"], ["0.0.4", "^0.0.3"], ["1.2.3", "~1"], ["2.0.0", "1 - 2"]];
console.log("satisfies", sat.map(([v, r]) => (Bun.semver.satisfies(v, r) ? "Y" : "n")).join(""));
t("order", () => [Bun.semver.order("1.0.0", "1.0.1"), Bun.semver.order("2.0.0", "1.9.9"), Bun.semver.order("1.0.0", "1.0.0"),
                  Bun.semver.order("1.0.0-alpha", "1.0.0"), Bun.semver.order("1.0.0-alpha.1", "1.0.0-alpha.beta"),
                  Bun.semver.order("1.0.0-2", "1.0.0-10"), Bun.semver.order("1.0.0+build", "1.0.0")]);
t("sort", () => ["1.10.0", "1.2.0", "1.2.0-rc.1", "0.9.0", "1.2.0-beta", "10.0.0"].sort(Bun.semver.order));
t("color", () => [Bun.color("red", "hex"), Bun.color("#0f08", "{rgba}"), Bun.color("rgb(10, 20, 30)", "HEX"), Bun.color("rgba(1,2,3,0.5)", "[rgba]"),
                  Bun.color([255, 128, 0], "number"), Bun.color(0x123456, "[rgb]"), Bun.color({ r: 1, g: 2, b: 3 }, "css"),
                  Bun.color("nonsense", "hex"), Bun.color("#12345", "hex"), Bun.color("RebeccaPurple", "{rgb}"), Bun.color("#abc"),
                  Bun.color("teal", "ansi-16m"), Bun.color("  WHITE ", "number"), Bun.color("rgb(30 60 90)", "[rgb]"), Bun.color("#11223344", "{rgba}")]);
t("color-unknown-format", () => Bun.color("red", "weird"));
''')
