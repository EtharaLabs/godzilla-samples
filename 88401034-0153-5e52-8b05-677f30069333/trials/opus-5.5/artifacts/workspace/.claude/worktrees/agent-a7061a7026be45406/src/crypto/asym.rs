//! High-level asymmetric operations with the original's dispatch and error ordering:
//! `crypto.sign` / `crypto.verify` (and `Sign#sign` / `Verify#verify`), `publicEncrypt`,
//! `privateDecrypt`, `privateEncrypt`, `publicDecrypt` and `crypto.diffieHellman`.
//!
//! The binding converts JS values first (key → [`AsymKey`] via `createPrivateKey` /
//! `createPublicKey` semantics, data/signature via `toBytes`) and then calls these.

use super::hash::{hash_alg_from_name, normalize_digest_name, unsupported_digest_error, HashAlg};
use super::keys::{AsymKey, KeyKind};
use super::{curve25519, p256, rsa, CryptoError};

/// `RSA_PKCS1_PADDING`, `RSA_NO_PADDING`, `RSA_PKCS1_OAEP_PADDING`, `RSA_PKCS1_PSS_PADDING`.
pub const RSA_PKCS1_PADDING: i64 = 1;
pub const RSA_NO_PADDING: i64 = 3;
pub const RSA_PKCS1_OAEP_PADDING: i64 = 4;
pub const RSA_PKCS1_PSS_PADDING: i64 = 6;

/// Options read from the key-options object (`{key, padding, saltLength, dsaEncoding}`).
#[derive(Clone, Debug, Default)]
pub struct SignOptions {
    /// `padding` (RSA only): `RSA_PKCS1_PADDING` (default) or `RSA_PKCS1_PSS_PADDING`.
    pub padding: Option<i64>,
    /// `saltLength` (PSS): absent → digest length when signing, auto-detect when verifying.
    pub salt_length: Option<i64>,
    /// `dsaEncoding` (EC only): `'der'` (default) or `'ieee-p1363'`.
    pub dsa_encoding: Option<String>,
}

fn resolve_digest(name: &str) -> Result<HashAlg, CryptoError> {
    let n = normalize_digest_name(name);
    hash_alg_from_name(&n).ok_or_else(|| unsupported_digest_error(&n))
}

fn p1363(opts: &SignOptions) -> Result<bool, CryptoError> {
    match opts.dsa_encoding.as_deref() {
        None | Some("der") => Ok(false),
        Some("ieee-p1363") => Ok(true),
        Some(other) => Err(CryptoError::type_error(format!("Invalid ECDSA signature encoding '{}'", other))),
    }
}

/// Shared prologue: kind checks then digest resolution.
fn prologue(fname: &str, verb: &str, algorithm: Option<&str>, key: &AsymKey) -> Result<Option<HashAlg>, CryptoError> {
    match key.kind() {
        KeyKind::X25519 => Err(CryptoError::error(format!("{}: X25519 keys cannot {}", fname, verb))),
        KeyKind::Ed25519 => {
            if algorithm.is_some() {
                return Err(CryptoError::error(format!("{}: algorithm must be null/undefined for Ed25519 keys", fname)));
            }
            Ok(None)
        }
        kind => {
            let name = algorithm.ok_or_else(|| {
                CryptoError::error(format!("{}: a digest algorithm is required for {} keys", fname, kind.name()))
            })?;
            Ok(Some(resolve_digest(name)?))
        }
    }
}

/// `crypto.sign(algorithm, data, key)`. `algorithm`: `None` for JS null/undefined, else
/// `String(algorithm)`. `key` must be private (else TypeError `crypto: cannot create a
/// private key from a public key`). Errors in the original's order: X25519 → `crypto.sign:
/// X25519 keys cannot sign`; Ed25519 with an algorithm → `crypto.sign: algorithm must be
/// null/undefined for Ed25519 keys`; RSA/EC without → `crypto.sign: a digest algorithm is
/// required for rsa keys` / `... ec keys`; digest name errors; RSA padding other than 1/6 →
/// `crypto.sign: RSA padding <n> is not supported in lumen`; EC `dsaEncoding` other than
/// der/ieee-p1363 → TypeError `Invalid ECDSA signature encoding '<x>'`; then the primitive's
/// errors (e.g. `RSA PKCS#1 v1.5 digest 'sha512-224' is not supported in lumen`,
/// `RSA: modulus too short for this digest`, `RSA-PSS: salt too long for the modulus`).
pub fn sign(algorithm: Option<&str>, data: &[u8], key: &AsymKey, opts: &SignOptions) -> Result<Vec<u8>, CryptoError> {
    if !key.is_private() {
        return Err(CryptoError::type_error("crypto: cannot create a private key from a public key"));
    }
    let alg = prologue("crypto.sign", "sign", algorithm, key)?;
    match key {
        AsymKey::RsaPrivate(k) => {
            let alg = alg.unwrap();
            match opts.padding.unwrap_or(RSA_PKCS1_PADDING) {
                RSA_PKCS1_PADDING => rsa::rsa_pkcs1v15_sign(k, alg, data),
                RSA_PKCS1_PSS_PADDING => rsa::rsa_pss_sign(k, alg, data, opts.salt_length.unwrap_or(rsa::PSS_SALTLEN_DIGEST)),
                p => Err(CryptoError::error(format!("crypto.sign: RSA padding {} is not supported in lumen", p))),
            }
        }
        AsymKey::EcPrivate { d, .. } => {
            let enc = p1363(opts)?;
            p256::ecdsa_sign(d, alg.unwrap(), data, enc)
        }
        AsymKey::Ed25519Private { seed, .. } => Ok(curve25519::ed25519_sign(seed, data).to_vec()),
        _ => Err(CryptoError::type_error("crypto: cannot create a private key from a public key")),
    }
}

/// `crypto.verify(algorithm, data, key, signature)`; `key` may be public or private.
/// Same error rules as [`sign`] with `crypto.verify` / `cannot verify` wording; invalid
/// signatures just return `Ok(false)`.
pub fn verify(algorithm: Option<&str>, data: &[u8], key: &AsymKey, signature: &[u8], opts: &SignOptions) -> Result<bool, CryptoError> {
    let alg = prologue("crypto.verify", "verify", algorithm, key)?;
    match key.to_public() {
        AsymKey::RsaPublic(k) => {
            let alg = alg.unwrap();
            match opts.padding.unwrap_or(RSA_PKCS1_PADDING) {
                RSA_PKCS1_PADDING => rsa::rsa_pkcs1v15_verify(&k, alg, data, signature),
                RSA_PKCS1_PSS_PADDING => Ok(rsa::rsa_pss_verify(&k, alg, data, signature, opts.salt_length)),
                p => Err(CryptoError::error(format!("crypto.verify: RSA padding {} is not supported in lumen", p))),
            }
        }
        AsymKey::EcPublic { point } => {
            let enc = p1363(opts)?;
            Ok(p256::ecdsa_verify(&point, alg.unwrap(), data, signature, enc))
        }
        AsymKey::Ed25519Public(pk) => Ok(curve25519::ed25519_verify(&pk, data, signature)),
        _ => Ok(false),
    }
}

/// Which of the four RSA encryption entry points.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RsaOp {
    PublicEncrypt,
    PrivateDecrypt,
    PrivateEncrypt,
    PublicDecrypt,
}

impl RsaOp {
    pub fn name(&self) -> &'static str {
        match self {
            RsaOp::PublicEncrypt => "publicEncrypt",
            RsaOp::PrivateDecrypt => "privateDecrypt",
            RsaOp::PrivateEncrypt => "privateEncrypt",
            RsaOp::PublicDecrypt => "publicDecrypt",
        }
    }

    /// Whether the key is obtained with `createPrivateKey` (else `createPublicKey`).
    pub fn needs_private(&self) -> bool {
        matches!(self, RsaOp::PrivateDecrypt | RsaOp::PrivateEncrypt)
    }
}

/// The RSA-kind check every entry point does right after key creation:
/// `Error: <fn>: only RSA keys are supported in lumen`.
pub fn require_rsa(op: RsaOp, key: &AsymKey) -> Result<(), CryptoError> {
    if key.kind() != KeyKind::Rsa {
        return Err(CryptoError::error(format!("{}: only RSA keys are supported in lumen", op.name())));
    }
    Ok(())
}

/// `publicEncrypt` / `privateDecrypt` / `privateEncrypt` / `publicDecrypt`.
/// `padding` defaults: OAEP for publicEncrypt/privateDecrypt, PKCS#1 for the other two.
/// `oaep_hash` is the already-resolved `oaepHash` (binding: `resolveHash(opts.oaepHash ||
/// 'sha1')`, resolved only when OAEP is used), `oaep_label` = `toBytes(opts.oaepLabel)` or
/// empty. Order: [`require_rsa`] → padding dispatch → primitive. `privateDecrypt` with
/// `RSA_PKCS1_PADDING` → TypeError `RSA_PKCS1_PADDING is no longer supported for private
/// decryption`; unsupported paddings → `Error: <fn>: padding <n> is not supported in lumen`.
pub fn rsa_encrypt_op(
    op: RsaOp,
    key: &AsymKey,
    data: &[u8],
    padding: Option<i64>,
    oaep_hash: HashAlg,
    oaep_label: &[u8],
) -> Result<Vec<u8>, CryptoError> {
    require_rsa(op, key)?;
    let unsupported = |p: i64| CryptoError::error(format!("{}: padding {} is not supported in lumen", op.name(), p));
    let private = || match key {
        AsymKey::RsaPrivate(k) => Ok(k),
        _ => Err(CryptoError::type_error("crypto: cannot create a private key from a public key")),
    };
    let public = key.rsa_public().unwrap();
    match op {
        RsaOp::PublicEncrypt => match padding.unwrap_or(RSA_PKCS1_OAEP_PADDING) {
            RSA_PKCS1_OAEP_PADDING => rsa::rsa_oaep_encrypt(&public, oaep_hash, oaep_label, data),
            RSA_PKCS1_PADDING => rsa::rsa_pkcs1v15_encrypt(&public, data),
            RSA_NO_PADDING => rsa::rsa_public_no_padding(&public, data),
            p => Err(unsupported(p)),
        },
        RsaOp::PrivateDecrypt => match padding.unwrap_or(RSA_PKCS1_OAEP_PADDING) {
            RSA_PKCS1_OAEP_PADDING => rsa::rsa_oaep_decrypt(private()?, oaep_hash, oaep_label, data),
            RSA_PKCS1_PADDING => Err(CryptoError::type_error("RSA_PKCS1_PADDING is no longer supported for private decryption")),
            RSA_NO_PADDING => rsa::rsa_private_no_padding(private()?, data),
            p => Err(unsupported(p)),
        },
        RsaOp::PrivateEncrypt => match padding.unwrap_or(RSA_PKCS1_PADDING) {
            RSA_NO_PADDING => rsa::rsa_private_no_padding(private()?, data),
            RSA_PKCS1_PADDING => rsa::rsa_private_encrypt_pkcs1(private()?, data),
            p => Err(unsupported(p)),
        },
        RsaOp::PublicDecrypt => match padding.unwrap_or(RSA_PKCS1_PADDING) {
            RSA_NO_PADDING => rsa::rsa_public_no_padding(&public, data),
            RSA_PKCS1_PADDING => rsa::rsa_public_decrypt_pkcs1(&public, data),
            p => Err(unsupported(p)),
        },
    }
}

/// `crypto.diffieHellman({privateKey, publicKey})` for two KeyObjects (the binding checks
/// both are KeyObjects: TypeError `diffieHellman requires privateKey and publicKey
/// KeyObjects`). EC P-256 → 32-byte x-coordinate; X25519 → 32 bytes. Errors:
/// `diffieHellman privateKey does not contain a private key` (EC public as private),
/// point errors, `Failed to compute ECDH key`, otherwise
/// `diffieHellman keys must use the same supported curve`.
pub fn diffie_hellman(private: &AsymKey, public: &AsymKey) -> Result<Vec<u8>, CryptoError> {
    match (private, public.to_public()) {
        (AsymKey::EcPrivate { d, .. }, AsymKey::EcPublic { point }) => Ok(p256::ecdh(d, &point)?.to_vec()),
        (AsymKey::EcPublic { .. }, AsymKey::EcPublic { .. }) => {
            Err(CryptoError::error("diffieHellman privateKey does not contain a private key"))
        }
        (AsymKey::X25519Private { secret, .. }, AsymKey::X25519Public(pk)) => Ok(curve25519::x25519(secret, &pk).to_vec()),
        _ => Err(CryptoError::error("diffieHellman keys must use the same supported curve")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dispatch_errors() {
        let ed = AsymKey::generate(KeyKind::Ed25519, 0, &super::super::BigUint::zero()).unwrap();
        let x = AsymKey::generate(KeyKind::X25519, 0, &super::super::BigUint::zero()).unwrap();
        let ec = AsymKey::generate(KeyKind::Ec, 0, &super::super::BigUint::zero()).unwrap();
        let rsa_k = AsymKey::generate(KeyKind::Rsa, 512, &super::super::BigUint::from_u64(65537)).unwrap();
        let o = SignOptions::default();
        let m = |r: Result<Vec<u8>, CryptoError>| r.unwrap_err().message;
        assert_eq!(m(sign(Some("sha3"), b"x", &ed, &o)), "crypto.sign: algorithm must be null/undefined for Ed25519 keys");
        assert_eq!(m(sign(None, b"x", &x, &o)), "crypto.sign: X25519 keys cannot sign");
        assert_eq!(m(sign(None, b"x", &rsa_k, &o)), "crypto.sign: a digest algorithm is required for rsa keys");
        assert_eq!(m(sign(None, b"x", &ec, &o)), "crypto.sign: a digest algorithm is required for ec keys");
        assert!(m(sign(Some("sha3"), b"x", &rsa_k, &o)).starts_with("Digest method not supported: sha3"));
        let pad3 = SignOptions { padding: Some(3), ..Default::default() };
        assert_eq!(m(sign(Some("sha512-224"), b"x", &rsa_k, &pad3)), "crypto.sign: RSA padding 3 is not supported in lumen");
        let bogus = SignOptions { dsa_encoding: Some("bogus".into()), ..Default::default() };
        assert_eq!(m(sign(Some("sha256"), b"x", &ec, &bogus)), "Invalid ECDSA signature encoding 'bogus'");
        assert_eq!(sign(Some("sha256"), b"x", &ec, &pad3).unwrap().len() >= 8, true);
        assert_eq!(m(sign(Some("sha256"), b"x", &rsa_k.to_public(), &o)), "crypto: cannot create a private key from a public key");
        for (k, alg) in [(&ed, None), (&ec, Some("RSA-SHA256")), (&rsa_k, Some("sha256WithRSAEncryption"))] {
            let s = sign(alg, b"msg", k, &o).unwrap();
            assert!(verify(alg, b"msg", k, &s, &o).unwrap());
            assert!(verify(alg, b"msg", &k.to_public(), &s, &o).unwrap());
            assert!(!verify(alg, b"msh", k, &s, &o).unwrap());
        }
        assert_eq!(verify(None, b"x", &x, &[0; 64], &o).unwrap_err().message, "crypto.verify: X25519 keys cannot verify");
        assert_eq!(
            verify(Some("sha512-224"), b"x", &rsa_k, &[0; 64], &o).unwrap_err().message,
            "RSA PKCS#1 v1.5 digest 'sha512-224' is not supported in lumen"
        );
        let pss = SignOptions { padding: Some(6), salt_length: Some(0), ..Default::default() };
        let s = sign(Some("sha256"), b"m", &rsa_k, &pss).unwrap();
        assert!(verify(Some("sha256"), b"m", &rsa_k, &s, &SignOptions { padding: Some(6), ..Default::default() }).unwrap());
        // RSA encryption dispatch
        let ct = rsa_encrypt_op(RsaOp::PublicEncrypt, &rsa_k.to_public(), b"hi", None, HashAlg::Sha1, b"").unwrap();
        assert_eq!(rsa_encrypt_op(RsaOp::PrivateDecrypt, &rsa_k, &ct, None, HashAlg::Sha1, b"").unwrap(), b"hi");
        assert_eq!(
            rsa_encrypt_op(RsaOp::PrivateDecrypt, &rsa_k, &ct, Some(1), HashAlg::Sha1, b"").unwrap_err().message,
            "RSA_PKCS1_PADDING is no longer supported for private decryption"
        );
        let s = rsa_encrypt_op(RsaOp::PrivateEncrypt, &rsa_k, b"hi", None, HashAlg::Sha1, b"").unwrap();
        assert_eq!(rsa_encrypt_op(RsaOp::PublicDecrypt, &rsa_k.to_public(), &s, None, HashAlg::Sha1, b"").unwrap(), b"hi");
        assert_eq!(
            rsa_encrypt_op(RsaOp::PublicEncrypt, &ec, b"hi", Some(9), HashAlg::Sha1, b"").unwrap_err().message,
            "publicEncrypt: only RSA keys are supported in lumen"
        );
        assert_eq!(
            rsa_encrypt_op(RsaOp::PublicEncrypt, &rsa_k, b"hi", Some(5), HashAlg::Sha1, b"").unwrap_err().message,
            "publicEncrypt: padding 5 is not supported in lumen"
        );
        // diffieHellman
        let ec2 = AsymKey::generate(KeyKind::Ec, 0, &super::super::BigUint::zero()).unwrap();
        assert_eq!(diffie_hellman(&ec, &ec2.to_public()).unwrap(), diffie_hellman(&ec2, &ec.to_public()).unwrap());
        let x2 = AsymKey::generate(KeyKind::X25519, 0, &super::super::BigUint::zero()).unwrap();
        assert_eq!(diffie_hellman(&x, &x2).unwrap(), diffie_hellman(&x2, &x).unwrap());
        assert_eq!(diffie_hellman(&ec, &x).unwrap_err().message, "diffieHellman keys must use the same supported curve");
        assert_eq!(diffie_hellman(&ed, &ed).unwrap_err().message, "diffieHellman keys must use the same supported curve");
        assert_eq!(diffie_hellman(&ec.to_public(), &ec).unwrap_err().message, "diffieHellman privateKey does not contain a private key");
    }
}
