//! Message digests (MD5, SHA-1, SHA-2 family) and HMAC.

use super::md5::Md5;
use super::sha1::Sha1;
use super::sha256::Sha256;
use super::sha512::{Sha512, IV384, IV512, IV512_224, IV512_256};
use super::CryptoError;

/// A digest algorithm.
///
/// `Sha224` exists for completeness (internal use / tests) but the original runtime does
/// NOT accept it by name: [`hash_alg_from_name`] never returns it.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum HashAlg {
    Md5,
    Sha1,
    Sha224,
    Sha256,
    Sha384,
    Sha512,
    Sha512_224,
    Sha512_256,
}

/// The list returned by `crypto.getHashes()` (and `Bun.CryptoHasher.algorithms`), in order.
pub const HASH_NAMES: [&str; 7] = ["md5", "sha1", "sha256", "sha384", "sha512", "sha512-224", "sha512-256"];

/// Resolve a digest name the way the original's `resolveHash` does: `String(name)` is
/// lower-cased (full Unicode lower-casing, like JS `toLowerCase`) and looked up in a fixed
/// table. Accepted (case-insensitively): `md5`, `sha1`, `sha-1`, `sha256`, `sha-256`,
/// `sha384`, `sha-384`, `sha512`, `sha-512`, `sha512-224`, `sha512-256`.
/// Everything else (`sha224`, `RSA-SHA256`, `sha3-256`, `ripemd160`, `md4`, names with
/// surrounding whitespace, ...) is rejected: see [`unsupported_digest_error`].
pub fn hash_alg_from_name(name: &str) -> Option<HashAlg> {
    let lower = name.to_lowercase();
    Some(match lower.as_str() {
        "md5" => HashAlg::Md5,
        "sha1" | "sha-1" => HashAlg::Sha1,
        "sha256" | "sha-256" => HashAlg::Sha256,
        "sha384" | "sha-384" => HashAlg::Sha384,
        "sha512" | "sha-512" => HashAlg::Sha512,
        "sha512-224" => HashAlg::Sha512_224,
        "sha512-256" => HashAlg::Sha512_256,
        _ => return None,
    })
}

/// The original's `normalizeDigest` (used by `createSign`/`createVerify`/`crypto.sign`/
/// `crypto.verify`): lower-case, then strip — each at most once and in this order — a
/// leading `rsa-`, a leading `ecdsa-with-`, a leading `id-`, and a trailing
/// `withrsaencryption`. E.g. `RSA-SHA256` / `sha256WithRSAEncryption` /
/// `ecdsa-with-SHA256` / `id-sha256` / `rsa-id-sha256` all become `sha256`;
/// `id-rsa-sha256` becomes `rsa-sha256` (then rejected). The *normalized* string is what
/// appears in the "Digest method not supported: ..." message for these APIs.
pub fn normalize_digest_name(name: &str) -> String {
    let lower = name.to_lowercase();
    let mut s: &str = lower.as_str();
    if let Some(rest) = s.strip_prefix("rsa-") {
        s = rest;
    }
    if let Some(rest) = s.strip_prefix("ecdsa-with-") {
        s = rest;
    }
    if let Some(rest) = s.strip_prefix("id-") {
        s = rest;
    }
    if let Some(rest) = s.strip_suffix("withrsaencryption") {
        s = rest;
    }
    s.to_string()
}

/// `hash_alg_from_name(&normalize_digest_name(name))` — digest resolution for sign/verify.
/// Note `RSA-SHA224` is still rejected since sha224 is.
pub fn sign_hash_alg_from_name(name: &str) -> Option<HashAlg> {
    hash_alg_from_name(&normalize_digest_name(name))
}

/// The exact error the original throws for an unknown digest name (plain `Error`, no code).
/// `name` must be the JS `String(algorithm)` of the user's argument (not lower-cased).
pub fn unsupported_digest_error(name: &str) -> CryptoError {
    CryptoError::error(format!(
        "Digest method not supported: {} (lumen supports md5, sha1, sha256, sha384, sha512, sha512-224, sha512-256)",
        name
    ))
}

impl HashAlg {
    /// Digest size in bytes.
    pub fn output_len(&self) -> usize {
        match self {
            HashAlg::Md5 => 16,
            HashAlg::Sha1 => 20,
            HashAlg::Sha224 => 28,
            HashAlg::Sha256 => 32,
            HashAlg::Sha384 => 48,
            HashAlg::Sha512 => 64,
            HashAlg::Sha512_224 => 28,
            HashAlg::Sha512_256 => 32,
        }
    }

    /// Internal block size in bytes (64 for MD5/SHA-1/SHA-224/SHA-256, 128 for the SHA-512 family).
    pub fn block_len(&self) -> usize {
        match self {
            HashAlg::Md5 | HashAlg::Sha1 | HashAlg::Sha224 | HashAlg::Sha256 => 64,
            _ => 128,
        }
    }

    /// Canonical lower-case name (as in `getHashes()`; `sha224` for Sha224).
    pub fn name(&self) -> &'static str {
        match self {
            HashAlg::Md5 => "md5",
            HashAlg::Sha1 => "sha1",
            HashAlg::Sha224 => "sha224",
            HashAlg::Sha256 => "sha256",
            HashAlg::Sha384 => "sha384",
            HashAlg::Sha512 => "sha512",
            HashAlg::Sha512_224 => "sha512-224",
            HashAlg::Sha512_256 => "sha512-256",
        }
    }

    /// WebCrypto-style name (`SHA-256`, ...), where one exists.
    pub fn webcrypto_name(&self) -> Option<&'static str> {
        match self {
            HashAlg::Sha1 => Some("SHA-1"),
            HashAlg::Sha256 => Some("SHA-256"),
            HashAlg::Sha384 => Some("SHA-384"),
            HashAlg::Sha512 => Some("SHA-512"),
            _ => None,
        }
    }
}

#[derive(Clone)]
enum Inner {
    Md5(Md5),
    Sha1(Sha1),
    Sha256(Sha256),
    Sha512(Sha512),
}

/// Incremental hasher. `Clone` gives `Hash.prototype.copy()` semantics.
#[derive(Clone)]
pub struct Hasher {
    alg: HashAlg,
    inner: Inner,
}

impl Hasher {
    pub fn new(alg: HashAlg) -> Self {
        let inner = match alg {
            HashAlg::Md5 => Inner::Md5(Md5::new()),
            HashAlg::Sha1 => Inner::Sha1(Sha1::new()),
            HashAlg::Sha224 => Inner::Sha256(Sha256::new224()),
            HashAlg::Sha256 => Inner::Sha256(Sha256::new()),
            HashAlg::Sha384 => Inner::Sha512(Sha512::with_iv(IV384, 48)),
            HashAlg::Sha512 => Inner::Sha512(Sha512::with_iv(IV512, 64)),
            HashAlg::Sha512_224 => Inner::Sha512(Sha512::with_iv(IV512_224, 28)),
            HashAlg::Sha512_256 => Inner::Sha512(Sha512::with_iv(IV512_256, 32)),
        };
        Hasher { alg, inner }
    }

    pub fn alg(&self) -> HashAlg {
        self.alg
    }

    pub fn update(&mut self, data: &[u8]) {
        match &mut self.inner {
            Inner::Md5(h) => h.update(data),
            Inner::Sha1(h) => h.update(data),
            Inner::Sha256(h) => h.update(data),
            Inner::Sha512(h) => h.update(data),
        }
    }

    /// Writes the digest into `out[..output_len]`. Panics if `out` is too short.
    pub fn finalize_into(self, out: &mut [u8]) {
        let n = self.alg.output_len();
        assert!(out.len() >= n, "digest output buffer too small");
        match self.inner {
            Inner::Md5(h) => h.finalize_into(out),
            Inner::Sha1(h) => h.finalize_into(out),
            Inner::Sha256(h) => h.finalize_into(out),
            Inner::Sha512(h) => h.finalize_into(out),
        }
    }

    pub fn finalize(self) -> Vec<u8> {
        let mut out = vec![0u8; self.alg.output_len()];
        self.finalize_into(&mut out);
        out
    }
}

/// One-shot digest.
pub fn digest(alg: HashAlg, data: &[u8]) -> Vec<u8> {
    let mut h = Hasher::new(alg);
    h.update(data);
    h.finalize()
}

/// Incremental HMAC (RFC 2104). Keys longer than the block size are hashed first.
#[derive(Clone)]
pub struct Hmac {
    inner: Hasher,
    outer: Hasher,
}

impl Hmac {
    pub fn new(alg: HashAlg, key: &[u8]) -> Self {
        let bl = alg.block_len();
        let mut k = [0u8; 128];
        if key.len() > bl {
            let mut h = Hasher::new(alg);
            h.update(key);
            h.finalize_into(&mut k);
        } else {
            k[..key.len()].copy_from_slice(key);
        }
        let mut ipad = [0u8; 128];
        let mut opad = [0u8; 128];
        for i in 0..bl {
            ipad[i] = k[i] ^ 0x36;
            opad[i] = k[i] ^ 0x5c;
        }
        let mut inner = Hasher::new(alg);
        inner.update(&ipad[..bl]);
        let mut outer = Hasher::new(alg);
        outer.update(&opad[..bl]);
        Hmac { inner, outer }
    }

    pub fn alg(&self) -> HashAlg {
        self.inner.alg()
    }

    pub fn update(&mut self, data: &[u8]) {
        self.inner.update(data);
    }

    /// Writes the MAC into `out[..output_len]`.
    pub fn finalize_into(self, out: &mut [u8]) {
        let n = self.inner.alg().output_len();
        let mut ih = [0u8; 64];
        self.inner.finalize_into(&mut ih);
        let mut outer = self.outer;
        outer.update(&ih[..n]);
        outer.finalize_into(out);
    }

    pub fn finalize(self) -> Vec<u8> {
        let mut out = vec![0u8; self.inner.alg().output_len()];
        self.finalize_into(&mut out);
        out
    }
}

/// One-shot HMAC.
pub fn hmac(alg: HashAlg, key: &[u8], data: &[u8]) -> Vec<u8> {
    let mut h = Hmac::new(alg, key);
    h.update(data);
    h.finalize()
}
