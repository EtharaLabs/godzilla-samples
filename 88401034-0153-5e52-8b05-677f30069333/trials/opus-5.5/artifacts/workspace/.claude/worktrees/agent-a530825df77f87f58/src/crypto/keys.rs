//! Asymmetric key containers and their DER/PEM/JWK encodings (SPKI, PKCS#8, PKCS#1, SEC1),
//! mirroring what the original runtime accepts and produces.

use super::asn1::{self, Tlv};
use super::bigint::BigUint;
use super::curve25519;
use super::p256;
use super::rsa::{RsaPrivateKey, RsaPublicKey};
use super::CryptoError;

pub const OID_RSA: &str = "1.2.840.113549.1.1.1";
/// RSASSA-PSS keys are accepted and treated as plain RSA by the original.
pub const OID_RSA_PSS: &str = "1.2.840.113549.1.1.10";
pub const OID_EC: &str = "1.2.840.10045.2.1";
pub const OID_P256: &str = "1.2.840.10045.3.1.7";
pub const OID_ED25519: &str = "1.3.101.112";
pub const OID_X25519: &str = "1.3.101.110";

/// `asymmetricKeyType`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyKind {
    Rsa,
    Ec,
    Ed25519,
    X25519,
}

impl KeyKind {
    pub fn name(&self) -> &'static str {
        match self {
            KeyKind::Rsa => "rsa",
            KeyKind::Ec => "ec",
            KeyKind::Ed25519 => "ed25519",
            KeyKind::X25519 => "x25519",
        }
    }
}

/// An asymmetric key. EC keys are always P-256 (`namedCurve: 'prime256v1'`); `point` is the
/// SEC1 point encoding as imported (normally uncompressed).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AsymKey {
    RsaPublic(RsaPublicKey),
    RsaPrivate(RsaPrivateKey),
    EcPublic { point: Vec<u8> },
    EcPrivate { d: [u8; 32], point: Vec<u8> },
    Ed25519Public([u8; 32]),
    Ed25519Private { seed: [u8; 32], public: [u8; 32] },
    X25519Public([u8; 32]),
    X25519Private { secret: [u8; 32], public: [u8; 32] },
}

fn curve_name_for_oid(oid: &str) -> String {
    match oid {
        OID_P256 => "prime256v1".into(),
        "1.3.132.0.34" => "secp384r1".into(),
        "1.3.132.0.35" => "secp521r1".into(),
        "1.3.132.0.10" => "secp256k1".into(),
        "1.3.132.0.33" => "secp224r1".into(),
        "1.2.840.10045.3.1.1" => "prime192v1".into(),
        other => other.into(),
    }
}

fn unsupported_curve(oid: &str) -> CryptoError {
    CryptoError::error(format!("EC curve {} is not supported in lumen (only prime256v1)", curve_name_for_oid(oid)))
}

fn arr32(b: &[u8]) -> Result<[u8; 32], CryptoError> {
    if b.len() != 32 {
        return Err(asn1::truncated());
    }
    let mut a = [0u8; 32];
    a.copy_from_slice(b);
    Ok(a)
}

/// Left-pad / validate an EC private scalar to 32 bytes.
fn scalar32(b: &[u8]) -> Result<[u8; 32], CryptoError> {
    let m = asn1::integer_magnitude(b);
    if m.len() > 32 {
        return Err(asn1::malformed());
    }
    let mut a = [0u8; 32];
    a[32 - m.len()..].copy_from_slice(m);
    Ok(a)
}

fn bitstring_bytes(t: &Tlv<'_>) -> Result<Vec<u8>, CryptoError> {
    if t.tag != asn1::TAG_BIT_STRING || t.content.is_empty() {
        return Err(asn1::malformed());
    }
    Ok(t.content[1..].to_vec())
}

fn int_value(t: Option<&Tlv<'_>>) -> Result<BigUint, CryptoError> {
    let t = asn1::expect(t, asn1::TAG_INTEGER)?;
    Ok(BigUint::from_bytes_be(asn1::integer_magnitude(t.content)))
}

/// Parse `RSAPublicKey ::= SEQUENCE { n INTEGER, e INTEGER }`.
pub fn parse_pkcs1_public(der: &[u8]) -> Result<AsymKey, CryptoError> {
    let seq = asn1::read_tlv(der, 0)?;
    if seq.tag != asn1::TAG_SEQUENCE {
        return Err(asn1::malformed());
    }
    let k = asn1::children(seq.content)?;
    Ok(AsymKey::RsaPublic(RsaPublicKey { n: int_value(k.first())?, e: int_value(k.get(1))? }))
}

/// Parse PKCS#1 `RSAPrivateKey` (version, n, e, d, p, q, dp, dq, qi).
pub fn parse_pkcs1_private(der: &[u8]) -> Result<AsymKey, CryptoError> {
    let seq = asn1::read_tlv(der, 0)?;
    if seq.tag != asn1::TAG_SEQUENCE {
        return Err(asn1::malformed());
    }
    let k = asn1::children(seq.content)?;
    Ok(AsymKey::RsaPrivate(RsaPrivateKey {
        n: int_value(k.get(1))?,
        e: int_value(k.get(2))?,
        d: int_value(k.get(3))?,
        p: int_value(k.get(4))?,
        q: int_value(k.get(5))?,
        dp: int_value(k.get(6))?,
        dq: int_value(k.get(7))?,
        qi: int_value(k.get(8))?,
    }))
}

/// Parse SEC1 `ECPrivateKey` (P-256 only). `default_curve_oid` is used when the optional
/// `[0] parameters` field is absent (as inside PKCS#8). A missing `[1] publicKey` is derived.
pub fn parse_sec1(der: &[u8], default_curve_oid: &str) -> Result<AsymKey, CryptoError> {
    let seq = asn1::read_tlv(der, 0)?;
    if seq.tag != asn1::TAG_SEQUENCE {
        return Err(asn1::malformed());
    }
    let k = asn1::children(seq.content)?;
    let d = scalar32(asn1::expect(k.get(1), asn1::TAG_OCTET_STRING)?.content)?;
    let mut curve = default_curve_oid.to_string();
    let mut point: Option<Vec<u8>> = None;
    for t in k.iter().skip(2) {
        match t.tag {
            0xa0 => {
                let inner = asn1::read_tlv(t.content, 0)?;
                if inner.tag == asn1::TAG_OID {
                    curve = asn1::decode_oid(inner.content);
                }
            }
            0xa1 => {
                let inner = asn1::read_tlv(t.content, 0)?;
                point = Some(bitstring_bytes(&inner)?);
            }
            _ => {}
        }
    }
    if curve != OID_P256 {
        return Err(unsupported_curve(&curve));
    }
    let point = match point {
        Some(p) => p,
        None => p256::public_from_private(&d)?,
    };
    Ok(AsymKey::EcPrivate { d, point })
}

/// Parse `SubjectPublicKeyInfo`. Errors: `Public key algorithm <oid> is not supported in
/// lumen`, `EC curve <name> is not supported in lumen (only prime256v1)`, DER errors.
pub fn parse_spki(der: &[u8]) -> Result<AsymKey, CryptoError> {
    let seq = asn1::read_tlv(der, 0)?;
    if seq.tag != asn1::TAG_SEQUENCE {
        return Err(asn1::malformed());
    }
    let k = asn1::children(seq.content)?;
    let alg = asn1::expect(k.first(), asn1::TAG_SEQUENCE)?;
    let alg_kids = asn1::children(alg.content)?;
    let oid = asn1::decode_oid(asn1::expect(alg_kids.first(), asn1::TAG_OID)?.content);
    if ![OID_RSA, OID_RSA_PSS, OID_EC, OID_ED25519, OID_X25519].contains(&oid.as_str()) {
        return Err(CryptoError::error(format!("Public key algorithm {} is not supported in lumen", oid)));
    }
    let key = bitstring_bytes(k.get(1).ok_or_else(asn1::malformed)?)?;
    match oid.as_str() {
        OID_RSA | OID_RSA_PSS => parse_pkcs1_public(&key),
        OID_EC => {
            let curve = alg_kids.get(1).filter(|t| t.tag == asn1::TAG_OID).map(|t| asn1::decode_oid(t.content));
            let curve = curve.unwrap_or_default();
            if curve != OID_P256 {
                return Err(unsupported_curve(&curve));
            }
            Ok(AsymKey::EcPublic { point: key })
        }
        OID_ED25519 => Ok(AsymKey::Ed25519Public(arr32(&key)?)),
        OID_X25519 => Ok(AsymKey::X25519Public(arr32(&key)?)),
        other => Err(CryptoError::error(format!("Public key algorithm {} is not supported in lumen", other))),
    }
}

/// Parse PKCS#8 `PrivateKeyInfo` / `OneAsymmetricKey`. Errors: `Private key algorithm <oid>
/// is not supported in lumen`, curve errors, DER errors.
pub fn parse_pkcs8(der: &[u8]) -> Result<AsymKey, CryptoError> {
    let seq = asn1::read_tlv(der, 0)?;
    if seq.tag != asn1::TAG_SEQUENCE {
        return Err(asn1::malformed());
    }
    let k = asn1::children(seq.content)?;
    asn1::expect(k.first(), asn1::TAG_INTEGER)?;
    let alg = asn1::expect(k.get(1), asn1::TAG_SEQUENCE)?;
    let alg_kids = asn1::children(alg.content)?;
    let oid = asn1::decode_oid(asn1::expect(alg_kids.first(), asn1::TAG_OID)?.content);
    let pk = asn1::expect(k.get(2), asn1::TAG_OCTET_STRING)?;
    match oid.as_str() {
        OID_RSA | OID_RSA_PSS => parse_pkcs1_private(pk.content),
        OID_EC => {
            let curve = alg_kids.get(1).filter(|t| t.tag == asn1::TAG_OID).map(|t| asn1::decode_oid(t.content));
            let curve = curve.unwrap_or_else(|| OID_P256.to_string());
            if curve != OID_P256 {
                return Err(unsupported_curve(&curve));
            }
            parse_sec1(pk.content, &curve)
        }
        OID_ED25519 | OID_X25519 => {
            let inner = asn1::read_tlv(pk.content, 0)?;
            if inner.tag != asn1::TAG_OCTET_STRING {
                return Err(asn1::malformed());
            }
            let secret = arr32(inner.content)?;
            if oid == OID_ED25519 {
                Ok(AsymKey::Ed25519Private { seed: secret, public: curve25519::ed25519_public_key(&secret) })
            } else {
                Ok(AsymKey::X25519Private { secret, public: curve25519::x25519_public_key(&secret) })
            }
        }
        other => Err(CryptoError::error(format!("Private key algorithm {} is not supported in lumen", other))),
    }
}

/// Which parser to use for a PEM block / DER input, following the original's
/// `createPublicKey` / `createPrivateKey` dispatch.
///
/// * `createPrivateKey`: label `RSA PRIVATE KEY` or `type: 'pkcs1'` → PKCS#1; label
///   `EC PRIVATE KEY` or `type: 'sec1'` → SEC1; anything else → PKCS#8. A result without a
///   private part → `crypto: key data does not contain a private key`.
/// * `createPublicKey`: label `CERTIFICATE` → the certificate's SPKI; `RSA PUBLIC KEY` or
///   `type: 'pkcs1'` → PKCS#1 public; `RSA PRIVATE KEY` → PKCS#1 private; `EC PRIVATE KEY`
///   → SEC1; `PRIVATE KEY` → PKCS#8; else SPKI. Private results are reduced to public keys.
pub fn parse_private_key(der: &[u8], pem_label: Option<&str>, der_type: Option<&str>) -> Result<AsymKey, CryptoError> {
    let key = if pem_label == Some("RSA PRIVATE KEY") || der_type == Some("pkcs1") {
        parse_pkcs1_private(der)?
    } else if pem_label == Some("EC PRIVATE KEY") || der_type == Some("sec1") {
        parse_sec1(der, OID_P256)?
    } else {
        parse_pkcs8(der)?
    };
    if !key.is_private() {
        return Err(CryptoError::error("crypto: key data does not contain a private key"));
    }
    Ok(key)
}

/// See [`parse_private_key`].
pub fn parse_public_key(der: &[u8], pem_label: Option<&str>, der_type: Option<&str>) -> Result<AsymKey, CryptoError> {
    let key = if pem_label == Some("CERTIFICATE") {
        let cert = super::x509::Certificate::parse(der)?;
        parse_spki(&cert.spki)?
    } else if pem_label == Some("RSA PUBLIC KEY") || der_type == Some("pkcs1") {
        parse_pkcs1_public(der)?
    } else if pem_label == Some("RSA PRIVATE KEY") {
        parse_pkcs1_private(der)?
    } else if pem_label == Some("EC PRIVATE KEY") {
        parse_sec1(der, OID_P256)?
    } else if pem_label == Some("PRIVATE KEY") {
        parse_pkcs8(der)?
    } else {
        parse_spki(der)?
    };
    Ok(key.to_public())
}

fn rsa_public_der(k: &RsaPublicKey) -> Vec<u8> {
    asn1::sequence(&[&asn1::integer_unsigned(&k.n.to_bytes_be()), &asn1::integer_unsigned(&k.e.to_bytes_be())])
}

fn rsa_private_der(k: &RsaPrivateKey) -> Vec<u8> {
    let i = |v: &BigUint| asn1::integer_unsigned(&v.to_bytes_be());
    asn1::sequence(&[
        &asn1::integer_u64(0),
        &i(&k.n),
        &i(&k.e),
        &i(&k.d),
        &i(&k.p),
        &i(&k.q),
        &i(&k.dp),
        &i(&k.dq),
        &i(&k.qi),
    ])
}

fn alg_id(kind: KeyKind) -> Vec<u8> {
    match kind {
        KeyKind::Rsa => asn1::sequence(&[&asn1::oid(OID_RSA), &asn1::null()]),
        KeyKind::Ec => asn1::sequence(&[&asn1::oid(OID_EC), &asn1::oid(OID_P256)]),
        KeyKind::Ed25519 => asn1::sequence(&[&asn1::oid(OID_ED25519)]),
        KeyKind::X25519 => asn1::sequence(&[&asn1::oid(OID_X25519)]),
    }
}

/// Export errors with the original's wording.
pub fn export_error(msg: &str) -> CryptoError {
    CryptoError::error(format!("KeyObject.export: {}", msg))
}

impl AsymKey {
    pub fn kind(&self) -> KeyKind {
        match self {
            AsymKey::RsaPublic(_) | AsymKey::RsaPrivate(_) => KeyKind::Rsa,
            AsymKey::EcPublic { .. } | AsymKey::EcPrivate { .. } => KeyKind::Ec,
            AsymKey::Ed25519Public(_) | AsymKey::Ed25519Private { .. } => KeyKind::Ed25519,
            AsymKey::X25519Public(_) | AsymKey::X25519Private { .. } => KeyKind::X25519,
        }
    }

    pub fn is_private(&self) -> bool {
        matches!(
            self,
            AsymKey::RsaPrivate(_) | AsymKey::EcPrivate { .. } | AsymKey::Ed25519Private { .. } | AsymKey::X25519Private { .. }
        )
    }

    /// The public half (identity for public keys).
    pub fn to_public(&self) -> AsymKey {
        match self {
            AsymKey::RsaPrivate(k) => AsymKey::RsaPublic(k.public_key()),
            AsymKey::EcPrivate { point, .. } => AsymKey::EcPublic { point: point.clone() },
            AsymKey::Ed25519Private { public, .. } => AsymKey::Ed25519Public(*public),
            AsymKey::X25519Private { public, .. } => AsymKey::X25519Public(*public),
            other => other.clone(),
        }
    }

    /// RSA public key view (for RSA keys).
    pub fn rsa_public(&self) -> Option<RsaPublicKey> {
        match self {
            AsymKey::RsaPublic(k) => Some(k.clone()),
            AsymKey::RsaPrivate(k) => Some(k.public_key()),
            _ => None,
        }
    }

    /// EC public point encoding (for EC keys).
    pub fn ec_point(&self) -> Option<&[u8]> {
        match self {
            AsymKey::EcPublic { point } | AsymKey::EcPrivate { point, .. } => Some(point),
            _ => None,
        }
    }

    /// `asymmetricKeyDetails`: RSA → `Some((modulusLength, publicExponent))`.
    pub fn rsa_details(&self) -> Option<(usize, BigUint)> {
        self.rsa_public().map(|k| (k.n.bits(), k.e))
    }

    /// `export({type:'spki', format:'der'})` of the public part.
    pub fn export_spki(&self) -> Vec<u8> {
        let key_bits = match self.to_public() {
            AsymKey::RsaPublic(k) => rsa_public_der(&k),
            AsymKey::EcPublic { point } => point,
            AsymKey::Ed25519Public(p) | AsymKey::X25519Public(p) => p.to_vec(),
            _ => unreachable!(),
        };
        asn1::sequence(&[&alg_id(self.kind()), &asn1::bit_string(&key_bits)])
    }

    /// `export({type:'pkcs8', format:'der'})`. For EC the inner ECPrivateKey carries the
    /// public key but no parameters (like OpenSSL/Node).
    pub fn export_pkcs8(&self) -> Result<Vec<u8>, CryptoError> {
        let inner = match self {
            AsymKey::RsaPrivate(k) => rsa_private_der(k),
            AsymKey::EcPrivate { d, point } => asn1::sequence(&[
                &asn1::integer_u64(1),
                &asn1::octet_string(d),
                &asn1::context(1, &asn1::bit_string(point)),
            ]),
            AsymKey::Ed25519Private { seed, .. } => asn1::octet_string(seed),
            AsymKey::X25519Private { secret, .. } => asn1::octet_string(secret),
            _ => return Err(export_error("unsupported public key type 'pkcs8'")),
        };
        Ok(asn1::sequence(&[&asn1::integer_u64(0), &alg_id(self.kind()), &asn1::octet_string(&inner)]))
    }

    /// `export({type:'pkcs1'})`: `RSAPrivateKey` for private, `RSAPublicKey` for public
    /// RSA keys; otherwise `KeyObject.export: 'pkcs1' requires an RSA key`.
    pub fn export_pkcs1(&self) -> Result<Vec<u8>, CryptoError> {
        match self {
            AsymKey::RsaPrivate(k) => Ok(rsa_private_der(k)),
            AsymKey::RsaPublic(k) => Ok(rsa_public_der(k)),
            _ => Err(export_error("'pkcs1' requires an RSA key")),
        }
    }

    /// `export({type:'sec1'})` (EC private keys only; with `[0]` parameters and `[1]` key).
    pub fn export_sec1(&self) -> Result<Vec<u8>, CryptoError> {
        match self {
            AsymKey::EcPrivate { d, point } => Ok(asn1::sequence(&[
                &asn1::integer_u64(1),
                &asn1::octet_string(d),
                &asn1::context(0, &asn1::oid(OID_P256)),
                &asn1::context(1, &asn1::bit_string(point)),
            ])),
            AsymKey::EcPublic { .. } => Err(export_error("unsupported public key type 'sec1'")),
            _ => Err(export_error("'sec1' requires an EC key")),
        }
    }

    /// PEM label for a given export `type` (`spki` → `PUBLIC KEY`, `pkcs8` → `PRIVATE KEY`,
    /// `pkcs1` → `RSA PRIVATE KEY` / `RSA PUBLIC KEY`, `sec1` → `EC PRIVATE KEY`).
    pub fn pem_label(&self, export_type: &str) -> &'static str {
        match export_type {
            "spki" => "PUBLIC KEY",
            "pkcs8" => "PRIVATE KEY",
            "pkcs1" if self.is_private() => "RSA PRIVATE KEY",
            "pkcs1" => "RSA PUBLIC KEY",
            "sec1" => "EC PRIVATE KEY",
            _ => "",
        }
    }

    /// Full `KeyObject.export({type, format})` for `format` `pem` / `der` (JWK: see
    /// [`AsymKey::jwk_fields`]). Errors exactly like the original:
    /// `KeyObject.export: unsupported private key type '<t>'` (private keys accept `pkcs8`,
    /// `pkcs1`, `sec1`), `KeyObject.export: unsupported public key type '<t>'` (public keys
    /// accept `spki`, `pkcs1`), `'pkcs1' requires an RSA key`, `'sec1' requires an EC key`.
    /// Returns DER bytes; PEM-wrap with [`asn1::pem_encode`] and [`AsymKey::pem_label`].
    pub fn export_der(&self, export_type: &str) -> Result<Vec<u8>, CryptoError> {
        if self.is_private() {
            match export_type {
                "pkcs8" => self.export_pkcs8(),
                "pkcs1" => self.export_pkcs1(),
                "sec1" => self.export_sec1(),
                t => Err(export_error(&format!("unsupported private key type '{}'", t))),
            }
        } else {
            match export_type {
                "spki" => Ok(self.export_spki()),
                "pkcs1" => self.export_pkcs1(),
                t => Err(export_error(&format!("unsupported public key type '{}'", t))),
            }
        }
    }

    /// JWK members in the original's order, values base64url (no padding):
    /// RSA `kty,n,e[,d,p,q,dp,dq,qi]`; EC `kty,crv('P-256'),x,y[,d]`;
    /// OKP `kty,crv('Ed25519'|'X25519'),x[,d]`.
    pub fn jwk_fields(&self) -> Vec<(&'static str, String)> {
        let b = |v: &[u8]| asn1::base64url_encode(v);
        let bi = |v: &BigUint| asn1::base64url_encode(&v.to_bytes_be());
        let mut out: Vec<(&'static str, String)> = Vec::new();
        match self {
            AsymKey::RsaPublic(k) => {
                out.push(("kty", "RSA".into()));
                out.push(("n", bi(&k.n)));
                out.push(("e", bi(&k.e)));
            }
            AsymKey::RsaPrivate(k) => {
                out.push(("kty", "RSA".into()));
                out.push(("n", bi(&k.n)));
                out.push(("e", bi(&k.e)));
                out.push(("d", bi(&k.d)));
                out.push(("p", bi(&k.p)));
                out.push(("q", bi(&k.q)));
                out.push(("dp", bi(&k.dp)));
                out.push(("dq", bi(&k.dq)));
                out.push(("qi", bi(&k.qi)));
            }
            AsymKey::EcPublic { point } | AsymKey::EcPrivate { point, .. } => {
                out.push(("kty", "EC".into()));
                out.push(("crv", "P-256".into()));
                // Like the original: slice the stored encoding (an imported compressed point
                // yields an empty `y`).
                let x = point.get(1..33).unwrap_or(&[]);
                let y = point.get(33..65).unwrap_or(&[]);
                out.push(("x", b(x)));
                out.push(("y", b(y)));
                if let AsymKey::EcPrivate { d, .. } = self {
                    out.push(("d", b(d)));
                }
            }
            AsymKey::Ed25519Public(p) | AsymKey::Ed25519Private { public: p, .. } => {
                out.push(("kty", "OKP".into()));
                out.push(("crv", "Ed25519".into()));
                out.push(("x", b(p)));
                if let AsymKey::Ed25519Private { seed, .. } = self {
                    out.push(("d", b(seed)));
                }
            }
            AsymKey::X25519Public(p) | AsymKey::X25519Private { public: p, .. } => {
                out.push(("kty", "OKP".into()));
                out.push(("crv", "X25519".into()));
                out.push(("x", b(p)));
                if let AsymKey::X25519Private { secret, .. } = self {
                    out.push(("d", b(secret)));
                }
            }
        }
        out
    }

    /// Import from JWK members (`get(name)` returns the string value of a member if present).
    /// `want_private` mirrors `createPrivateKey` (requires `d`). Errors:
    /// `JWK kty '<kty>' is not supported in lumen` (public import of an unknown kty),
    /// `crypto: JWK does not contain a private key`,
    /// `EC curve '<crv>' is not supported in lumen (only P-256)`,
    /// `OKP curve '<crv>' is not supported in lumen`.
    pub fn from_jwk(get: &dyn Fn(&str) -> Option<String>, want_private: bool) -> Result<AsymKey, CryptoError> {
        let kty = get("kty");
        let has_d = get("d").is_some();
        if want_private && !has_d {
            return Err(CryptoError::error("crypto: JWK does not contain a private key"));
        }
        let field = |n: &str| asn1::base64_decode(&get(n).unwrap_or_default());
        let bigf = |n: &str| BigUint::from_bytes_be(&field(n));
        match kty.as_deref() {
            Some("RSA") => {
                let public = RsaPublicKey { n: bigf("n"), e: bigf("e") };
                if has_d {
                    let mut k = RsaPrivateKey {
                        n: public.n.clone(),
                        e: public.e.clone(),
                        d: bigf("d"),
                        p: bigf("p"),
                        q: bigf("q"),
                        dp: bigf("dp"),
                        dq: bigf("dq"),
                        qi: bigf("qi"),
                    };
                    if !k.p.is_zero() && !k.q.is_zero() && (k.dp.is_zero() || k.dq.is_zero() || k.qi.is_zero()) {
                        k = RsaPrivateKey::from_primes(k.n, k.e, k.d, k.p, k.q);
                    }
                    Ok(AsymKey::RsaPrivate(k))
                } else {
                    Ok(AsymKey::RsaPublic(public))
                }
            }
            Some("EC") => {
                let crv = get("crv").unwrap_or_else(|| "undefined".into());
                if crv != "P-256" {
                    return Err(CryptoError::error(format!("EC curve '{}' is not supported in lumen (only P-256)", crv)));
                }
                let mut point = vec![4u8];
                point.extend(field("x"));
                point.extend(field("y"));
                if has_d {
                    let d = scalar32(&field("d"))?;
                    Ok(AsymKey::EcPrivate { d, point })
                } else {
                    Ok(AsymKey::EcPublic { point })
                }
            }
            Some("OKP") => {
                let crv = get("crv").unwrap_or_else(|| "undefined".into());
                let pad32 = |v: Vec<u8>| {
                    let mut a = [0u8; 32];
                    let n = v.len().min(32);
                    a[..n].copy_from_slice(&v[..n]);
                    a
                };
                match crv.as_str() {
                    "Ed25519" => {
                        if has_d {
                            let seed = pad32(field("d"));
                            Ok(AsymKey::Ed25519Private { seed, public: curve25519::ed25519_public_key(&seed) })
                        } else {
                            Ok(AsymKey::Ed25519Public(pad32(field("x"))))
                        }
                    }
                    "X25519" => {
                        if has_d {
                            let secret = pad32(field("d"));
                            Ok(AsymKey::X25519Private { secret, public: curve25519::x25519_public_key(&secret) })
                        } else {
                            Ok(AsymKey::X25519Public(pad32(field("x"))))
                        }
                    }
                    other => Err(CryptoError::error(format!("OKP curve '{}' is not supported in lumen", other))),
                }
            }
            other => {
                if want_private {
                    Err(CryptoError::error("crypto: JWK does not contain a private key"))
                } else {
                    Err(CryptoError::error(format!(
                        "JWK kty '{}' is not supported in lumen",
                        other.unwrap_or("undefined")
                    )))
                }
            }
        }
    }

    /// Generate a key pair (`generateKeyPairSync`): `Rsa` needs `(bits, e)`.
    pub fn generate(kind: KeyKind, rsa_bits: usize, rsa_e: &BigUint) -> Result<AsymKey, CryptoError> {
        Ok(match kind {
            KeyKind::Rsa => AsymKey::RsaPrivate(super::rsa::rsa_generate(rsa_bits, rsa_e)?),
            KeyKind::Ec => {
                let (d, point) = p256::generate_keypair();
                AsymKey::EcPrivate { d, point }
            }
            KeyKind::Ed25519 => {
                let mut seed = [0u8; 32];
                super::random::fill_random(&mut seed);
                AsymKey::Ed25519Private { seed, public: curve25519::ed25519_public_key(&seed) }
            }
            KeyKind::X25519 => {
                let mut secret = [0u8; 32];
                super::random::fill_random(&mut secret);
                AsymKey::X25519Private { secret, public: curve25519::x25519_public_key(&secret) }
            }
        })
    }
}
