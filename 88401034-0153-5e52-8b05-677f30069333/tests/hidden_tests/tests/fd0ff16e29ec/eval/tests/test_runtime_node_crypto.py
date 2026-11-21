"""node:crypto — hashes/HMAC, KDFs (pbkdf2/hkdf/scrypt/argon2), AES ciphers, RSA/EC/Ed25519 keys and
signatures, ECDH/X25519/DH, X.509 parsing, randomness and secret keys. All keys are fixed test keys."""

from conftest import golden, write_files


def _ok(r):
    assert (r.returncode, r.stderr) == (0, b""), r.stderr


RSA_PRIV = """-----BEGIN PRIVATE__KEY-----
MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAJZ6ItGiI5jOmx+U
uNAyYnft3z7ZijCJD1RaRWMYpR3eecOr3iD99jccwLUipELmIgauW8D77qqWB63j
QFAH5ECfRM/+5fMS1/O7ZSpAzCcaLz2apLO8lWWQRDjr/FlekCjm2WjJLMeCb1mS
3A5Tyt+9FgynslyiNSSEfuoLZN/hAgMBAAECgYBvjLUZIJAw7CA0xiRHOsKiUzVm
uw9lMYWqq4y6jH+C5/TuKA9v97Q5YNg+ryKD8WQR/dlI87oWvUeOEWQQr/j1B9tM
C2l/rx2b7tUj5WPAolqDQHMhGq5Vds6PrjN7JfUfSBybO7l0EKIXkVMhcOPSf5Di
0QYKH8k+C8KhDwRUjQJBAMWqT5CopZv3voiHd5f76tbcw8MiKiN4X+jNhsNv7mfk
jgcYOEnTLR2XhVCaDANn/IoB5+Ngh14Tw4EPKF5MwFMCQQDC4r1PCspOs2xp6LkG
+m6dvOXAsRLFNyLZzSx0oa2AnAhoC+l7HXh4MPV2xgtALSojdVb34X7RgTEvBVqW
uqh7AkBWnzwe+MkagIdO7Y7LW+qeHkDr0p0Ezku5idf07ahcfxx+n26La6/pt+0E
VX3OQFO7Zvpn+nVYFPEoLaxTJu9hAkEAth3i4Ilp0q/S4QnMVlwSoK8UWMRgkRFc
LQKRx5AKrgOhy3FOR3Gb0V2XFN4vR1KtbSNLGSuNMkSzbIhpRi+6HwJAcdGS77hU
2hYoqonQ1D/Ki/M2EB8rWVANfOYx0Ns+WCrXAWx+LTKmH/FLwcSAw2vSFphE5UEE
ipc5WsBi8t71gw==
-----END PRIVATE__KEY-----
""".replace("PRIVATE__KEY", "PRIVATE KEY")

RSA_PUB = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCWeiLRoiOYzpsflLjQMmJ37d8+
2YowiQ9UWkVjGKUd3nnDq94g/fY3HMC1IqRC5iIGrlvA++6qlget40BQB+RAn0TP
/uXzEtfzu2UqQMwnGi89mqSzvJVlkEQ46/xZXpAo5tloySzHgm9ZktwOU8rfvRYM
p7JcojUkhH7qC2Tf4QIDAQAB
-----END PUBLIC KEY-----
"""

EC_PRIV = """-----BEGIN PRIVATE__KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgjuD+FdmEZOMs9MSg
uO6gzKrGoi9tB3cm0h4OcWNojPehRANCAARlspdkmIJ46yoyQBgG/RZxCcMP5ujX
mKAjLgPhkyf99ay/nKkw46Bm4Rd0N2VMtpD5lO9ZSi7RCVBOpkWp7ZbV
-----END PRIVATE__KEY-----
""".replace("PRIVATE__KEY", "PRIVATE KEY")

EC_PUB = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEZbKXZJiCeOsqMkAYBv0WcQnDD+bo
15igIy4D4ZMn/fWsv5ypMOOgZuEXdDdlTLaQ+ZTvWUou0QlQTqZFqe2W1Q==
-----END PUBLIC KEY-----
"""

ED_PRIV = """-----BEGIN PRIVATE__KEY-----
MC4CAQAwBQYDK2VwBCIEIJRejAAdF06knANY2d1uB9jklWTZfVd9WqFM48GpNx4U
-----END PRIVATE__KEY-----
""".replace("PRIVATE__KEY", "PRIVATE KEY")

ED_PUB = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA+0LhLolbRHQfnV6/bPuJ0ctORYaZgYvyhj5g3/Y2sGo=
-----END PUBLIC KEY-----
"""

CERT = """-----BEGIN CERTIFICATE-----
MIICYzCCAcygAwIBAgICEjQwDQYJKoZIhvcNAQELBQAwNzETMBEGA1UEAwwKbHVt
ZW4udGVzdDETMBEGA1UECgwKTHVtZW4gVGVzdDELMAkGA1UEBhMCVVMwHhcNMjYx
MTEwMDA1MTQzWhcNMzYxMTA3MDA1MTQzWjA3MRMwEQYDVQQDDApsdW1lbi50ZXN0
MRMwEQYDVQQKDApMdW1lbiBUZXN0MQswCQYDVQQGEwJVUzCBnzANBgkqhkiG9w0B
AQEFAAOBjQAwgYkCgYEAlnoi0aIjmM6bH5S40DJid+3fPtmKMIkPVFpFYxilHd55
w6veIP32NxzAtSKkQuYiBq5bwPvuqpYHreNAUAfkQJ9Ez/7l8xLX87tlKkDMJxov
PZqks7yVZZBEOOv8WV6QKObZaMksx4JvWZLcDlPK370WDKeyXKI1JIR+6gtk3+EC
AwEAAaN+MHwwHQYDVR0OBBYEFOrjUYyrR8wSe2PxeBZjim2Hj4gMMB8GA1UdIwQY
MBaAFOrjUYyrR8wSe2PxeBZjim2Hj4gMMA8GA1UdEwEB/wQFMAMBAf8wKQYDVR0R
BCIwIIIKbHVtZW4udGVzdIIMKi5sdW1lbi50ZXN0hwR/AAABMA0GCSqGSIb3DQEB
CwUAA4GBAHdWnxsLs9enjTz/9h2e31W333hXSD1njXvvrWdYHgxBWzqUXeLMqqFW
f5gjmn8VAzAtRqycpeO0AgIs+fIo4NqgEnbFlCSLFlJWKc9CBkKUzYo/t/eFU0ES
+rJ9eipLyd/me1JPJ7K+GlrJw7ZPCXMvJxpZIuUi6U/RgTYJ0ZBt
-----END CERTIFICATE-----
"""

KEY_FILES = {"rsa.pem": RSA_PRIV, "rsa_pub.pem": RSA_PUB, "ec.pem": EC_PRIV, "ec_pub.pem": EC_PUB,
             "ed.pem": ED_PRIV, "ed_pub.pem": ED_PUB, "cert.pem": CERT}


PROG_HASHES = r"""
const crypto = require("crypto");
const out = (...a) => console.log(...a);
const algs = crypto.getHashes();
out("hashes", algs.join(","));
const inputs = ["", "abc", "The quick brown fox jumps over the lazy dog", "a".repeat(55), "a".repeat(56), "a".repeat(64), "a".repeat(111), "a".repeat(112), "a".repeat(128), "héllo €"];
for (const a of algs) out(a, inputs.map((s) => crypto.createHash(a).update(s).digest("hex")).join(" "));
const big = Buffer.alloc(3000); for (let i = 0; i < big.length; i++) big[i] = i % 253;
out("3000 bytes", algs.map((a) => crypto.createHash(a).update(big).digest("hex").slice(0, 16)).join(" "));
const h = crypto.createHash("sha256");
h.update("part1"); h.update(Buffer.from("part2")); h.update("706172743", "hex");
const c = h.copy();
out("chunked", h.digest("hex"), c.update("x").digest("base64"), crypto.createHash("sha256").update("part1part2part3").digest("hex"));
out("encodings", crypto.createHash("md5").update("x").digest("base64url"), crypto.createHash("md5").update("x").digest("latin1").length, Buffer.isBuffer(crypto.createHash("md5").update("x").digest()), crypto.createHash("SHA1").update("x").digest("hex"), crypto.createHash("sha-256").update("x").digest("hex").slice(0, 8), crypto.createHash("sha-512").update("x").digest("hex").slice(0, 8));
out("inputs", crypto.createHash("sha1").update(new Uint16Array([1, 2])).digest("hex"), crypto.createHash("sha1").update(new ArrayBuffer(3)).digest("hex"), crypto.createHash("sha1").update("aGk=", "base64").digest("hex"));
out("oneshot", crypto.hash("sha1", "abc"), crypto.hash("md5", "abc", "base64"), Buffer.isBuffer(crypto.hash("sha256", "abc", "buffer")), crypto.hash("sha512", Buffer.from("abc")).slice(0, 16));
try { crypto.createHash("whirlpool"); } catch (e) { out("bad alg", e.name, e.code, e.message); }
try { const d = crypto.createHash("md5"); d.digest(); d.digest(); } catch (e) { out("twice", e.name, e.code, e.message); }
try { crypto.createHash("md5").update(42); } catch (e) { out("bad data", e.name, e.message); }
const hm = (alg, key, data) => crypto.createHmac(alg, key).update(data).digest("hex");
const k20 = Buffer.alloc(20, 0x0b);
out("hmac rfc4231 1", ["sha256", "sha384", "sha512", "sha1", "md5", "sha512-224"].map((a) => hm(a, k20, "Hi There")).join(" "));
out("hmac rfc4231 2", ["sha256", "sha512"].map((a) => hm(a, "Jefe", "what do ya want for nothing?")).join(" "));
const k131 = Buffer.alloc(131, 0xaa);
out("hmac long key", ["sha256", "sha384", "sha512", "sha1", "md5", "sha512-256"].map((a) => hm(a, k131, "Test Using Larger Than Block-Size Key - Hash Key First")).join(" "));
out("hmac empty", hm("sha256", "", ""), crypto.createHmac("sha256", crypto.createSecretKey(Buffer.from("k"))).update("d").digest("base64"));
const hc = crypto.createHmac("sha1", "key"); hc.update("a"); hc.update("b");
out("hmac chunked", hc.digest("hex") === hm("sha1", "key", "ab"));
try { hc.digest(); } catch (e) { out("hmac twice", e.message); }
try { crypto.createHmac("nope", "k"); } catch (e) { out("hmac bad", e.name, e.message); }
"""


def test_crypto_hashes_and_hmac(run):
    """CATCHES: wrong digests for md5/sha1/sha256/sha384/sha512/sha512-224/sha512-256 at padding
    boundaries (55/56/64/111/112/128 bytes) or multi-byte UTF-8, broken update chaining/copy()/digest
    encodings, and HMAC errors (RFC 4231 vectors, keys longer than the block size, KeyObject keys)."""
    r = run(["-e", PROG_HASHES])
    _ok(r)
    assert r.stdout == golden(__file__, "hashes")


PROG_KDF = r"""
const crypto = require("crypto");
const out = (...a) => console.log(...a);
out("pbkdf2 rfc6070", crypto.pbkdf2Sync("password", "salt", 1, 20, "sha1").toString("hex"), crypto.pbkdf2Sync("password", "salt", 2, 20, "sha1").toString("hex"), crypto.pbkdf2Sync("password", "salt", 3, 20, "sha1").toString("hex"));
out("pbkdf2 long", crypto.pbkdf2Sync("passwordPASSWORDpassword", "saltSALTsaltSALTsaltSALTsaltSALTsalt", 2, 25, "sha1").toString("hex"), crypto.pbkdf2Sync("pass\0word", "sa\0lt", 2, 16, "sha1").toString("hex"));
out("pbkdf2 sha256/512", crypto.pbkdf2Sync("password", "salt", 1, 32, "sha256").toString("hex"), crypto.pbkdf2Sync("password", "salt", 2, 64, "sha512").toString("hex"), crypto.pbkdf2Sync(Buffer.from("pw"), Buffer.from("s"), 3, 70, "md5").toString("base64"));
try { crypto.pbkdf2Sync("p", "s", 1, 10, "nope"); } catch (e) { out("pbkdf2 bad", e.name, e.code, e.message); }
const ikm = Buffer.from("0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b", "hex");
const hk = crypto.hkdfSync("sha256", ikm, Buffer.from("000102030405060708090a0b0c", "hex"), Buffer.from("f0f1f2f3f4f5f6f7f8f9", "hex"), 42);
out("hkdf rfc5869", hk instanceof ArrayBuffer, Buffer.from(hk).toString("hex"));
out("hkdf empty salt", Buffer.from(crypto.hkdfSync("sha256", ikm, "", "", 42)).toString("hex"), Buffer.from(crypto.hkdfSync("sha1", "key", "salt", "info", 10)).toString("hex"), Buffer.from(crypto.hkdfSync("sha512", crypto.createSecretKey(Buffer.from("k")), "s", "i", 70)).toString("base64"));
try { crypto.hkdfSync("sha256", "k", "s", "i", 255 * 32 + 1); } catch (e) { out("hkdf too long", e.name, e.code, e.message); }
out("scrypt rfc7914 1", crypto.scryptSync("", "", 64, { N: 16, r: 1, p: 1 }).toString("hex"));
out("scrypt small", crypto.scryptSync("password", "NaCl", 64, { N: 32, r: 2, p: 2 }).toString("hex"));
out("scrypt aliases", crypto.scryptSync("pw", "salt", 16, { cost: 32, blockSize: 2, parallelization: 1 }).toString("hex"), crypto.scryptSync(Buffer.from("pw"), Buffer.from("salt"), 16, { N: 32, r: 2, p: 1 }).toString("hex"));
try { crypto.scryptSync("pw", "salt", 16, { N: 3 }); } catch (e) { out("scrypt bad N", e.name, e.code, e.message); }
const params = { message: Buffer.alloc(32, 1), nonce: Buffer.alloc(16, 2), parallelism: 4, tagLength: 32, memory: 32, passes: 3, secret: Buffer.alloc(8, 3), associatedData: Buffer.alloc(12, 4) };
out("argon2id rfc9106", crypto.argon2Sync("argon2id", params).toString("hex"));
out("argon2d rfc9106", crypto.argon2Sync("argon2d", params).toString("hex"));
out("argon2i rfc9106", crypto.argon2Sync("argon2i", params).toString("hex"));
out("argon2 plain", crypto.argon2Sync("argon2id", { message: "password", nonce: "somesalt", parallelism: 1, tagLength: 24, memory: 16, passes: 2 }).toString("hex"));
try { crypto.argon2Sync("argon2x", {}); } catch (e) { out("argon2 bad", e.name, e.code, e.message); }
(async () => {
  await new Promise((r) => crypto.pbkdf2("password", "salt", 2, 20, "sha1", (err, key) => { out("pbkdf2 cb", err, key.toString("hex")); r(); }));
  await new Promise((r) => crypto.hkdf("sha256", "k", "s", "i", 8, (err, key) => { out("hkdf cb", err, Buffer.from(key).toString("hex")); r(); }));
  await new Promise((r) => crypto.scrypt("pw", "salt", 8, { N: 16 }, (err, key) => { out("scrypt cb", err, key.toString("hex")); r(); }));
  await new Promise((r) => crypto.argon2("argon2id", { message: "m", nonce: "saltsalt", parallelism: 1, tagLength: 16, memory: 8, passes: 1 }, (err, key) => { out("argon2 cb", err, key.toString("hex")); r(); }));
  await new Promise((r) => crypto.pbkdf2("p", "s", 1, 8, "bogus", (err) => { out("pbkdf2 cb err", err && err.message); r(); }));
})();
"""


def test_crypto_kdfs(run):
    """CATCHES: PBKDF2 (RFC 6070, multi-block output, NUL bytes, sha256/512/md5), HKDF (RFC 5869,
    empty salt, length limit), scrypt (RFC 7914 vector, option aliases, invalid N) and argon2d/i/id
    (RFC 9106 vectors with secret+AD) producing wrong bytes or wrong errors, sync and callback forms."""
    r = run(["-e", PROG_KDF])
    _ok(r)
    assert r.stdout == golden(__file__, "kdfs")


PROG_AES = r"""
const crypto = require("crypto");
const out = (...a) => console.log(...a);
const hex = (s) => Buffer.from(s, "hex");
const k128 = hex("2b7e151628aed2a6abf7158809cf4f3c");
const k192 = hex("8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b");
const k256 = hex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4");
const pt = hex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51");
const iv = hex("000102030405060708090a0b0c0d0e0f");
const ctrIv = hex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff");
const enc = (alg, key, iv, data, pad = true) => { const c = crypto.createCipheriv(alg, key, iv); c.setAutoPadding(pad); return Buffer.concat([c.update(data), c.final()]); };
const dec = (alg, key, iv, data, pad = true) => { const c = crypto.createDecipheriv(alg, key, iv); c.setAutoPadding(pad); return Buffer.concat([c.update(data), c.final()]); };
for (const [bits, key] of [[128, k128], [192, k192], [256, k256]]) {
  const ecb = enc(`aes-${bits}-ecb`, key, null, pt, false);
  const cbc = enc(`aes-${bits}-cbc`, key, iv, pt, false);
  const ctr = enc(`aes-${bits}-ctr`, key, ctrIv, pt);
  out(`aes-${bits}`, ecb.toString("hex"), cbc.toString("hex"), ctr.toString("hex"), dec(`aes-${bits}-ecb`, key, null, ecb, false).equals(pt), dec(`aes-${bits}-cbc`, key, iv, cbc, false).equals(pt), dec(`aes-${bits}-ctr`, key, ctrIv, ctr).equals(pt));
}
const padded = enc("aes-128-cbc", k128, iv, "short message");
out("pkcs7", padded.length, padded.toString("base64"), dec("aes-128-cbc", k128, iv, padded).toString());
out("pkcs7 block", enc("aes-128-cbc", k128, iv, Buffer.alloc(16)).length, enc("aes-128-ecb", k128, null, "").toString("hex"));
out("ctr wrap", enc("aes-128-ctr", k128, hex("ffffffffffffffffffffffffffffffff"), Buffer.alloc(40)).toString("hex"));
const c1 = crypto.createCipheriv("aes-256-cbc", k256, iv);
const parts = [c1.update("chunk one, "), c1.update("chunk two, ", "utf8"), c1.update(Buffer.from("three")), c1.final()];
out("streamed", parts.map((p) => p.length).join(","), Buffer.concat(parts).toString("hex"));
const c2 = crypto.createCipheriv("aes-128-ctr", k128, ctrIv);
out("ctr streamed", c2.update("abc", "utf8", "hex") + c2.update("defghijklmnopqrstu", "utf8", "hex") + c2.final("hex"));
const d2 = crypto.createDecipheriv("aes-128-cbc", k128, iv);
out("dec encodings", d2.update(padded.toString("hex"), "hex", "utf8") + d2.final("utf8"));
const gk = hex("feffe9928665731c6d6a8f9467308308");
const giv = hex("cafebabefacedbaddecaf888");
const gpt = hex("d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a721c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39");
const gaad = hex("feedfacedeadbeeffeedfacedeadbeefabaddad2");
const g = crypto.createCipheriv("aes-128-gcm", gk, giv);
g.setAAD(gaad);
const gct = Buffer.concat([g.update(gpt), g.final()]);
const tag = g.getAuthTag();
out("gcm", gct.toString("hex"), tag.toString("hex"));
const gd = crypto.createDecipheriv("aes-128-gcm", gk, giv);
gd.setAAD(gaad); gd.setAuthTag(tag);
out("gcm dec", Buffer.concat([gd.update(gct), gd.final()]).equals(gpt));
const g0 = crypto.createCipheriv("aes-128-gcm", Buffer.alloc(16), Buffer.alloc(12));
g0.update(Buffer.alloc(0)); g0.final();
out("gcm empty", g0.getAuthTag().toString("hex"));
const g256 = crypto.createCipheriv("aes-256-gcm", Buffer.alloc(32, 1), Buffer.alloc(16, 2), { authTagLength: 12 });
const g256ct = Buffer.concat([g256.update("long iv and short tag"), g256.final()]);
const t12 = g256.getAuthTag();
out("gcm 256", g256ct.toString("hex"), t12.toString("hex"), t12.length);
const g192 = crypto.createCipheriv("aes-192-gcm", Buffer.alloc(24, 5), Buffer.alloc(12, 6));
g192.setAAD(Buffer.from("aad only"));
out("gcm 192", Buffer.concat([g192.update("x"), g192.final()]).toString("hex"), g192.getAuthTag().toString("hex"));
try { const bad = crypto.createDecipheriv("aes-128-gcm", gk, giv); bad.setAAD(gaad); bad.setAuthTag(Buffer.alloc(16)); bad.update(gct); bad.final(); } catch (e) { out("gcm auth fail", e.name, e.code, e.message); }
try { dec("aes-128-cbc", k128, iv, padded.subarray(0, 15)); } catch (e) { out("bad length", e.name, e.code, e.message); }
try { dec("aes-128-cbc", k256.subarray(0, 16), iv, padded); } catch (e) { out("bad pad", e.name, e.code, e.message); }
try { enc("aes-128-cbc", k128, iv, "not a multiple", false); } catch (e) { out("nopad len", e.name, e.code, e.message); }
try { crypto.createCipheriv("aes-128-cbc", Buffer.alloc(5), iv); } catch (e) { out("bad key", e.name, e.code, e.message); }
try { crypto.createCipheriv("aes-128-cbc", k128, Buffer.alloc(3)); } catch (e) { out("bad iv", e.name, e.code, e.message); }
try { crypto.createCipheriv("des-ede3", k128, null); } catch (e) { out("bad cipher", e.name, e.code, e.message); }
try { const c = crypto.createCipheriv("aes-128-cbc", k128, iv); c.final(); c.final(); } catch (e) { out("final twice", e.name, e.code, e.message); }
try { crypto.createCipheriv("aes-128-gcm", k128, giv).getAuthTag(); } catch (e) { out("tag early", e.name, e.code, e.message); }
out("aliases", enc("aes128", k128, iv, "alias").toString("hex") === enc("aes-128-cbc", k128, iv, "alias").toString("hex"), enc("AES-128-CBC", k128, iv, "x").length);
out("ciphers", crypto.getCiphers().join(","));
out("info", JSON.stringify(crypto.getCipherInfo("aes-256-gcm")), JSON.stringify(crypto.getCipherInfo("aes-128-cbc")), crypto.getCipherInfo("nope"), JSON.stringify(crypto.getCipherInfo("aes-128-ecb")));
out("curves", crypto.getCurves().join(","), crypto.getFips());
"""


def test_crypto_aes_ciphers(run):
    """CATCHES: AES-128/192/256 in ECB/CBC/CTR/GCM giving wrong ciphertext (NIST SP800-38A/GCM vectors,
    CTR counter wrap, 16-byte GCM IVs, short tags), PKCS#7 padding mistakes, broken streaming update()/
    final() encodings, and wrong OpenSSL-style error codes/messages for bad keys, IVs, padding and tags."""
    r = run(["-e", PROG_AES])
    _ok(r)
    assert r.stdout == golden(__file__, "aes")


PROG_RSA = r"""
const crypto = require("crypto");
const fs = require("fs");
const out = (...a) => console.log(...a);
const big = (k, v) => (typeof v === "bigint" ? v + "n" : v);
const rsaPriv = crypto.createPrivateKey(fs.readFileSync("rsa.pem", "utf8"));
const rsaPub = crypto.createPublicKey(fs.readFileSync("rsa_pub.pem"));
out("rsa", rsaPriv.type, rsaPriv.asymmetricKeyType, JSON.stringify(rsaPriv.asymmetricKeyDetails, big), rsaPub.type, rsaPub.equals(crypto.createPublicKey(rsaPriv)), rsaPub.equals(rsaPriv));
const sig = crypto.sign("sha256", Buffer.from("message"), rsaPriv);
out("rsa sign", sig.toString("base64"), crypto.verify("sha256", Buffer.from("message"), rsaPub, sig), crypto.verify("sha256", Buffer.from("messagX"), rsaPub, sig));
const opensslSig = Buffer.from("8468fb1dcbefd9d58dbe855d894d6bd90b9bc02d92d2a7fd645e93653106bbb089ee3698f373436d78119a39d3f5cf72d27c272323cf717c070053eea98853af8d0dfaf4de9a4d890eba6582cceddc8076f5ea907cde763650aed72c2b606511afb49afbf1ab0a8795b905ef07b27ffcedbe8aa4b15c6960888bacca1546b3af", "hex");
out("verify openssl sig", crypto.verify("sha256", Buffer.from("ec msg"), fs.readFileSync("rsa_pub.pem", "utf8"), opensslSig));
const s2 = crypto.createSign("RSA-SHA1"); s2.update("ab"); s2.update("c"); const sig2 = s2.sign(fs.readFileSync("rsa.pem", "utf8"), "hex");
const v2 = crypto.createVerify("sha1"); v2.update("abc"); out("createSign", sig2.slice(0, 32), v2.verify(fs.readFileSync("rsa_pub.pem", "utf8"), sig2, "hex"));
const pss = crypto.sign("sha256", Buffer.from("pss"), { key: rsaPriv, padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: 0 });
out("pss salt0", pss.toString("hex").slice(0, 32), crypto.verify("sha256", Buffer.from("pss"), { key: rsaPub, padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: 0 }, pss));
const enc = crypto.publicEncrypt(rsaPub, Buffer.from("secret"));
out("oaep", enc.length, crypto.privateDecrypt(rsaPriv, enc).toString());
const enc2 = crypto.publicEncrypt({ key: rsaPub, padding: crypto.constants.RSA_PKCS1_PADDING }, Buffer.from("v15"));
try { crypto.privateDecrypt({ key: rsaPriv, padding: crypto.constants.RSA_PKCS1_PADDING }, enc2); } catch (e) { out("pkcs1 decrypt", e.name, e.code, e.message); }
const pe = crypto.privateEncrypt(rsaPriv, Buffer.from("signed-ish"));
out("privateEncrypt", pe.toString("hex").slice(0, 32), crypto.publicDecrypt(rsaPub, pe).toString());
out("export", rsaPub.export({ type: "spki", format: "pem" }) === fs.readFileSync("rsa_pub.pem", "utf8"), rsaPub.export({ type: "pkcs1", format: "der" }).length, rsaPriv.export({ type: "pkcs8", format: "pem" }) === fs.readFileSync("rsa.pem", "utf8"), rsaPriv.export({ type: "pkcs1", format: "pem" }).split("\n")[0]);
const jwk = rsaPub.export({ format: "jwk" });
out("jwk", JSON.stringify(Object.keys(jwk)), jwk.kty, jwk.e, jwk.n.slice(0, 20), Object.keys(rsaPriv.export({ format: "jwk" })).sort().join(","));
const fromJwk = crypto.createPublicKey({ key: jwk, format: "jwk" });
out("from jwk", fromJwk.equals(rsaPub), crypto.createPublicKey({ key: rsaPub.export({ type: "spki", format: "der" }), format: "der", type: "spki" }).equals(rsaPub));
try { crypto.createPrivateKey("not a key"); } catch (e) { out("bad key", e.name, e.code, e.message); }
"""


def test_crypto_rsa(run, workdir):
    """CATCHES: RSA key import/export (PKCS#8, SPKI, PKCS#1, DER, JWK round-trips, asymmetricKeyDetails),
    deterministic PKCS#1 v1.5 and zero-salt PSS signatures, verifying an OpenSSL-made signature,
    OAEP/privateEncrypt round trips and the refusal of PKCS#1 v1.5 private decryption."""
    write_files(workdir, KEY_FILES)
    r = run(["-e", PROG_RSA], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "rsa")


PROG_ECDSA = r"""
const crypto = require("crypto");
const fs = require("fs");
const out = (...a) => console.log(...a);
const ecPriv = crypto.createPrivateKey(fs.readFileSync("ec.pem"));
const ecPub = crypto.createPublicKey(fs.readFileSync("ec_pub.pem"));
const jwk = ecPub.export({ format: "jwk" });
out("ec", ecPriv.asymmetricKeyType, JSON.stringify(ecPriv.asymmetricKeyDetails), JSON.stringify(jwk), crypto.createPublicKey(ecPriv).equals(ecPub));
out("ec export", ecPub.export({ type: "spki", format: "pem" }) === fs.readFileSync("ec_pub.pem", "utf8"), ecPriv.export({ type: "sec1", format: "pem" }).split("\n")[0], Object.keys(ecPriv.export({ format: "jwk" })).sort().join(","));
const opensslSig = Buffer.from("3045022100e1bb9128845d0cceb5c555ccb77cbc3ba7040db8ac205a0150c81cf4a9146cb802204fcfb0754e08f7ba9a823f3679b632174967b5a30a5d504d8b4d0923a2ff8b63", "hex");
out("ecdsa openssl sig", crypto.verify("sha256", Buffer.from("ec msg"), ecPub, opensslSig), crypto.verify("sha256", Buffer.from("ec msX"), ecPub, opensslSig));
const ecSig = crypto.sign("sha256", Buffer.from("own msg"), ecPriv);
out("ecdsa own sig", ecSig[0], crypto.verify("sha256", Buffer.from("own msg"), ecPub, ecSig));
"""


def test_crypto_ecdsa_p256(run, workdir):
    """CATCHES: P-256 key import and JWK/SPKI/SEC1 export, ECDSA verification of an OpenSSL-made DER
    signature (and rejection of a tampered message), and self-made ECDSA signatures that fail to verify."""
    write_files(workdir, KEY_FILES)
    r = run(["-e", PROG_ECDSA], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "ecdsa")


PROG_ED25519 = r"""
const crypto = require("crypto");
const fs = require("fs");
const out = (...a) => console.log(...a);
const edPriv = crypto.createPrivateKey(fs.readFileSync("ed.pem", "utf8"));
const edPub = crypto.createPublicKey(fs.readFileSync("ed_pub.pem", "utf8"));
const edSig = crypto.sign(null, Buffer.from("ed msg"), edPriv);
out("ed25519", edPriv.asymmetricKeyType, edSig.toString("hex"), crypto.verify(null, Buffer.from("ed msg"), edPub, edSig), crypto.verify(null, Buffer.from("ed msX"), edPub, edSig), crypto.createPublicKey(edPriv).export({ format: "jwk" }).x === edPub.export({ format: "jwk" }).x);
out("ed25519 export", JSON.stringify(edPub.export({ format: "jwk" })), edPriv.export({ type: "pkcs8", format: "der" }).toString("hex"));
const seed = Buffer.from("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60", "hex");
const x = Buffer.from("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "hex");
const rfcPriv = crypto.createPrivateKey({ key: { kty: "OKP", crv: "Ed25519", d: seed.toString("base64url"), x: x.toString("base64url") }, format: "jwk" });
out("rfc8032 test1", crypto.sign(null, Buffer.alloc(0), rfcPriv).toString("hex"));
"""


def test_crypto_ed25519(run, workdir):
    """CATCHES: non-deterministic or wrong Ed25519 signatures (RFC 8032 test 1 and a fixed PEM key),
    verification that accepts a tampered message, and Ed25519 JWK/PKCS#8 export mistakes."""
    write_files(workdir, KEY_FILES)
    r = run(["-e", PROG_ED25519], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "ed25519")


PROG_DH_X509 = r"""
const crypto = require("crypto");
const fs = require("fs");
const out = (...a) => console.log(...a);
const a = crypto.createECDH("prime256v1"); a.setPrivateKey(Buffer.alloc(32, 1));
const b = crypto.createECDH("P-256"); b.setPrivateKey(Buffer.alloc(32, 2));
out("ecdh", a.getPublicKey("hex", "compressed"), a.computeSecret(b.getPublicKey()).toString("hex"), b.computeSecret(a.getPublicKey("base64"), "base64", "hex"), a.getPrivateKey("hex").slice(0, 8), a.getPublicKey().length);
try { crypto.createECDH("secp384r1"); } catch (e) { out("ecdh curve", e.name, e.message); }
const xa = crypto.createPrivateKey({ key: { kty: "OKP", crv: "X25519", d: Buffer.from("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a", "hex").toString("base64url"), x: Buffer.from("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a", "hex").toString("base64url") }, format: "jwk" });
const xb = crypto.createPublicKey({ key: { kty: "OKP", crv: "X25519", x: Buffer.from("de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f", "hex").toString("base64url") }, format: "jwk" });
out("x25519 rfc7748", crypto.diffieHellman({ privateKey: xa, publicKey: xb }).toString("hex"), xa.asymmetricKeyType);
const dh1 = crypto.createDiffieHellman(Buffer.from("17", "hex"), Buffer.from("05", "hex"));
dh1.setPrivateKey(Buffer.from("06", "hex"));
out("dh", dh1.getPrime("hex"), dh1.getGenerator("hex"), typeof dh1.generateKeys);
const g14 = crypto.getDiffieHellman("modp14");
out("modp14", g14.getPrime().length, g14.getGenerator("hex"));
const x = new crypto.X509Certificate(fs.readFileSync("cert.pem", "utf8"));
const rsaPub = crypto.createPublicKey(fs.readFileSync("rsa_pub.pem", "utf8"));
out("x509 names", JSON.stringify(x.subject), JSON.stringify(x.issuer), x.serialNumber, x.validFrom, x.validTo, x.subjectAltName, x.ca);
out("x509 checks", x.checkHost("lumen.test"), x.checkHost("a.lumen.test"), x.checkHost("other.test"), x.checkIP("127.0.0.1"), x.checkIP("10.0.0.1"), x.checkEmail("a@b.c"));
out("x509 keys", x.verify(rsaPub), x.publicKey.asymmetricKeyType, x.publicKey.equals(rsaPub), x.checkIssued(x), x.checkPrivateKey(crypto.createPrivateKey(fs.readFileSync("rsa.pem", "utf8"))));
out("x509 fingerprints", x.fingerprint, x.fingerprint256, x.fingerprint512.slice(0, 23));
out("x509 der", x.raw.length, x.toString() === fs.readFileSync("cert.pem", "utf8"), typeof x.toLegacyObject);
try { new crypto.X509Certificate("garbage"); } catch (e) { out("x509 bad", e.name, e.message); }
"""


def test_crypto_ecdh_dh_x509(run, workdir):
    """CATCHES: P-256 ECDH with fixed private keys (compressed points, encodings), X25519 per RFC 7748,
    finite-field DH accessors (the reference reports generator 02 for a Buffer generator), MODP groups,
    and X509Certificate parsing (subject/issuer/serial/dates/SAN, host/IP checks, fingerprints, verify)."""
    write_files(workdir, KEY_FILES)
    r = run(["-e", PROG_DH_X509], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "dh_x509")


PROG_RANDOM_KEYS = r"""
const crypto = require("crypto");
const out = (...a) => console.log(...a);
const rb = crypto.randomBytes(16);
out("randomBytes", Buffer.isBuffer(rb), rb.length, crypto.randomBytes(0).length);
crypto.randomBytes(8, (err, b) => out("randomBytes cb", err, b.length));
const fill = Buffer.alloc(8); crypto.randomFillSync(fill, 2, 4); out("randomFillSync untouched", fill[0], fill[1], fill[6], fill[7]);
crypto.randomFill(new Uint32Array(4), (err, arr) => out("randomFill cb", err, arr.length, arr instanceof Uint32Array));
const ints = Array.from({ length: 50 }, () => crypto.randomInt(3, 7));
out("randomInt", ints.every((n) => Number.isInteger(n) && n >= 3 && n < 7), Array.from({ length: 20 }, () => crypto.randomInt(5)).every((n) => n >= 0 && n < 5));
crypto.randomInt(10, (err, n) => out("randomInt cb", err, n >= 0 && n < 10));
try { crypto.randomInt(5, 5); } catch (e) { out("randomInt err", e.name, e.code, e.message); }
out("uuid", /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(crypto.randomUUID()), crypto.getRandomValues(new Uint8Array(4)).length);
out("timingSafeEqual", crypto.timingSafeEqual(Buffer.from("abc"), Buffer.from("abc")), crypto.timingSafeEqual(Buffer.from("abc"), Buffer.from("abd")));
try { crypto.timingSafeEqual(Buffer.from("a"), Buffer.from("ab")); } catch (e) { out("tse err", e.name, e.code, e.message); }
const sk = crypto.createSecretKey(Buffer.from("secret-key-bytes"));
out("secretKey", sk.type, sk.symmetricKeySize, sk.export().toString(), sk.equals(crypto.createSecretKey("secret-key-bytes", "utf8")), sk.equals(crypto.createSecretKey(Buffer.from("other"))), JSON.stringify(sk.export({ format: "jwk" })), sk.asymmetricKeyType, sk instanceof crypto.KeyObject);
const gk = crypto.generateKeySync("hmac", { length: 64 }); out("generateKeySync", gk.type, gk.symmetricKeySize);
const ak = crypto.generateKeySync("aes", { length: 256 }); out("aes key", ak.symmetricKeySize);
crypto.generateKey("hmac", { length: 128 }, (err, k) => out("generateKey cb", err, k.symmetricKeySize));
const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
const s = crypto.sign(null, Buffer.from("m"), privateKey);
out("ed25519 pair", publicKey.type, privateKey.type, s.length, crypto.verify(null, Buffer.from("m"), publicKey, s), crypto.verify(null, Buffer.from("n"), publicKey, s));
const pemPair = crypto.generateKeyPairSync("x25519", { publicKeyEncoding: { type: "spki", format: "pem" }, privateKeyEncoding: { type: "pkcs8", format: "pem" } });
out("x25519 pem", pemPair.publicKey.split("\n")[0], pemPair.privateKey.split("\n")[0]);
out("checkPrime", crypto.checkPrimeSync(7n), crypto.checkPrimeSync(Buffer.from([0x0f])), crypto.checkPrimeSync(2n ** 61n - 1n), crypto.checkPrimeSync(561n));
const p = crypto.generatePrimeSync(32, { bigint: true }); out("generatePrime", typeof p, p.toString(2).length, crypto.checkPrimeSync(p));
crypto.checkPrime(13n, (err, r) => out("checkPrime cb", err, r));
out("constants", crypto.constants.RSA_PKCS1_PSS_PADDING, crypto.constants.POINT_CONVERSION_COMPRESSED, typeof crypto.webcrypto.subtle, crypto.subtle === crypto.webcrypto.subtle);
try { crypto.setFips(1); } catch (e) { out("fips", e.message); }
try { crypto.setEngine("x"); } catch (e) { out("engine", e.name, e.message); }
out("secureHeap", JSON.stringify(crypto.secureHeapUsed()));
"""


def test_crypto_random_and_secret_keys(run):
    """CATCHES: randomness APIs with wrong shapes/ranges (randomBytes/randomFill offsets/randomInt
    bounds and errors/randomUUID v4 format), timingSafeEqual length checks, secret KeyObjects (export,
    equals, JWK), generateKey(Sync)/generateKeyPairSync usability, and Miller-Rabin prime helpers."""
    r = run(["-e", PROG_RANDOM_KEYS], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "random_keys")
