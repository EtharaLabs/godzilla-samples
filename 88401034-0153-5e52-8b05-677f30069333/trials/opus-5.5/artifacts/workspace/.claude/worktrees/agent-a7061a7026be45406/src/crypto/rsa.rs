//! RSA (RFC 8017): key generation, raw operations, PKCS#1 v1.5 / PSS signatures,
//! OAEP / PKCS#1 v1.5 encryption — with the original runtime's error messages.

use super::bigint::BigUint;
use super::hash::{digest, HashAlg, Hasher};
use super::prime::generate_prime;
use super::random::fill_random;
use super::CryptoError;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RsaPublicKey {
    pub n: BigUint,
    pub e: BigUint,
}

/// RSA private key. `p`, `q`, `dp`, `dq`, `qi` may be zero when unknown (e.g. a JWK with
/// only `n`, `e`, `d`); then private operations use `d` directly.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RsaPrivateKey {
    pub n: BigUint,
    pub e: BigUint,
    pub d: BigUint,
    pub p: BigUint,
    pub q: BigUint,
    pub dp: BigUint,
    pub dq: BigUint,
    pub qi: BigUint,
}

impl RsaPublicKey {
    /// Modulus length in bytes (`k`).
    pub fn size(&self) -> usize {
        self.n.bits().div_ceil(8)
    }
    /// `modulusLength` (bits).
    pub fn modulus_bits(&self) -> usize {
        self.n.bits()
    }
}

impl RsaPrivateKey {
    pub fn public_key(&self) -> RsaPublicKey {
        RsaPublicKey { n: self.n.clone(), e: self.e.clone() }
    }

    pub fn size(&self) -> usize {
        self.n.bits().div_ceil(8)
    }

    /// Build from `n, e, d, p, q`, deriving the CRT parameters.
    /// Degenerate factors (`<= 1`) leave the CRT parameters zero (non-CRT path is used).
    pub fn from_primes(n: BigUint, e: BigUint, d: BigUint, p: BigUint, q: BigUint) -> RsaPrivateKey {
        let one = BigUint::one();
        if p <= one || q <= one {
            let z = BigUint::zero();
            return RsaPrivateKey { n, e, d, p, q, dp: z.clone(), dq: z.clone(), qi: z };
        }
        let dp = d.rem(&p.sub(&one));
        let dq = d.rem(&q.sub(&one));
        let qi = q.modinv(&p).unwrap_or_default();
        RsaPrivateKey { n, e, d, p, q, dp, dq, qi }
    }

    fn has_crt(&self) -> bool {
        !self.p.is_zero() && !self.q.is_zero() && !self.dp.is_zero() && !self.dq.is_zero() && !self.qi.is_zero()
    }
}

fn err(msg: &str) -> CryptoError {
    CryptoError::error(msg)
}

/// Generate a key the way the original does: `p` gets `ceil(bits/2)` bits, `q` the rest,
/// both with their two top bits set and `gcd(e, prime-1) = 1`; `p > q`;
/// `d = e^-1 mod (p-1)(q-1)` (Euler phi, not Carmichael lambda — this differs from
/// OpenSSL); `dp = d mod (p-1)`, `dq = d mod (q-1)`, `qi = q^-1 mod p`.
/// `bits` range checking (`[512, 8192]`) is the binding's job. Errors if `e` is even or < 3
/// (the original never terminates for such exponents).
pub fn rsa_generate(bits: usize, e: &BigUint) -> Result<RsaPrivateKey, CryptoError> {
    if e.is_even() || e < &BigUint::from_u64(3) {
        return Err(CryptoError::range_error("RSA publicExponent must be an odd integer greater than 1"));
    }
    if bits < 16 {
        return Err(CryptoError::range_error("RSA modulusLength is too small"));
    }
    let pbits = bits.div_ceil(2);
    let qbits = bits - pbits;
    let one = BigUint::one();
    loop {
        let p = loop {
            let c = generate_prime(pbits, false, None, None);
            if c.sub(&one).gcd(e).is_one() {
                break c;
            }
        };
        let q = loop {
            let c = generate_prime(qbits, false, None, None);
            if c.sub(&one).gcd(e).is_one() {
                break c;
            }
        };
        if p == q {
            continue;
        }
        let (p, q) = if p > q { (p, q) } else { (q, p) };
        let n = p.mul(&q);
        if n.bits() != bits {
            continue;
        }
        let phi = p.sub(&one).mul(&q.sub(&one));
        let d = match e.modinv(&phi) {
            Some(d) => d,
            None => continue,
        };
        return Ok(RsaPrivateKey::from_primes(n, e.clone(), d, p, q));
    }
}

/// `m^e mod n`. Errors with `RSA: data too large for the modulus` when `m >= n`.
pub fn rsa_public_raw(key: &RsaPublicKey, m: &BigUint) -> Result<BigUint, CryptoError> {
    if m >= &key.n {
        return Err(err("RSA: data too large for the modulus"));
    }
    Ok(m.modpow(&key.e, &key.n))
}

/// `c^d mod n` (CRT when the factors are known). Errors with
/// `RSA: data too large for the modulus` when `c >= n`.
pub fn rsa_private_raw(key: &RsaPrivateKey, c: &BigUint) -> Result<BigUint, CryptoError> {
    if c >= &key.n {
        return Err(err("RSA: data too large for the modulus"));
    }
    if !key.has_crt() {
        return Ok(c.modpow(&key.d, &key.n));
    }
    let m1 = c.rem(&key.p).modpow(&key.dp, &key.p);
    let m2 = c.rem(&key.q).modpow(&key.dq, &key.q);
    let h = key.qi.mul(&m1.sub_mod(&m2, &key.p)).rem(&key.p);
    let m = m2.add(&h.mul(&key.q));
    Ok(m)
}

/// MGF1 mask generation (RFC 8017 B.2.1).
pub fn mgf1(alg: HashAlg, seed: &[u8], len: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(len + alg.output_len());
    let mut counter: u32 = 0;
    while out.len() < len {
        let mut h = Hasher::new(alg);
        h.update(seed);
        h.update(&counter.to_be_bytes());
        out.extend_from_slice(&h.finalize());
        counter += 1;
    }
    out.truncate(len);
    out
}

/// DER `DigestInfo` prefix for EMSA-PKCS1-v1_5 (the original supports md5, sha1, sha256,
/// sha384, sha512 only).
pub fn digest_info_prefix(alg: HashAlg) -> Option<&'static [u8]> {
    Some(match alg {
        HashAlg::Md5 => &[0x30, 0x20, 0x30, 0x0c, 0x06, 0x08, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x02, 0x05, 0x05, 0x00, 0x04, 0x10],
        HashAlg::Sha1 => &[0x30, 0x21, 0x30, 0x09, 0x06, 0x05, 0x2b, 0x0e, 0x03, 0x02, 0x1a, 0x05, 0x00, 0x04, 0x14],
        HashAlg::Sha256 => &[
            0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20,
        ],
        HashAlg::Sha384 => &[
            0x30, 0x41, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x02, 0x05, 0x00, 0x04, 0x30,
        ],
        HashAlg::Sha512 => &[
            0x30, 0x51, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x03, 0x05, 0x00, 0x04, 0x40,
        ],
        _ => return None,
    })
}

fn emsa_pkcs1v15(alg: HashAlg, hashed: &[u8], k: usize) -> Result<Vec<u8>, CryptoError> {
    let prefix = digest_info_prefix(alg)
        .ok_or_else(|| err(&format!("RSA PKCS#1 v1.5 digest '{}' is not supported in lumen", alg.name())))?;
    let t_len = prefix.len() + hashed.len();
    if k < t_len + 11 {
        return Err(err("RSA: modulus too short for this digest"));
    }
    let mut em = Vec::with_capacity(k);
    em.push(0x00);
    em.push(0x01);
    em.extend(std::iter::repeat(0xffu8).take(k - t_len - 3));
    em.push(0x00);
    em.extend_from_slice(prefix);
    em.extend_from_slice(hashed);
    Ok(em)
}

/// RSASSA-PKCS1-v1_5 signature over `msg` (hashed here). Deterministic.
/// Errors: `RSA PKCS#1 v1.5 digest 'sha512-256' is not supported in lumen` (sha224 /
/// sha512-224 / sha512-256), `RSA: modulus too short for this digest`.
pub fn rsa_pkcs1v15_sign(key: &RsaPrivateKey, alg: HashAlg, msg: &[u8]) -> Result<Vec<u8>, CryptoError> {
    rsa_pkcs1v15_sign_prehashed(key, alg, &digest(alg, msg))
}

pub fn rsa_pkcs1v15_sign_prehashed(key: &RsaPrivateKey, alg: HashAlg, hashed: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    let em = emsa_pkcs1v15(alg, hashed, k)?;
    let s = rsa_private_raw(key, &BigUint::from_bytes_be(&em))?;
    Ok(s.to_bytes_be_padded(k))
}

/// Verify RSASSA-PKCS1-v1_5. The signature must be exactly `k` bytes and `< n`.
/// Returns `Err` only for an unsupported digest (same messages as signing).
pub fn rsa_pkcs1v15_verify(key: &RsaPublicKey, alg: HashAlg, msg: &[u8], sig: &[u8]) -> Result<bool, CryptoError> {
    let k = key.size();
    let hashed = digest(alg, msg);
    let em = match emsa_pkcs1v15(alg, &hashed, k) {
        Ok(em) => em,
        Err(e) if e.message.starts_with("RSA PKCS#1") => return Err(e),
        Err(_) => return Ok(false),
    };
    if sig.len() != k {
        return Ok(false);
    }
    let s = BigUint::from_bytes_be(sig);
    let m = match rsa_public_raw(key, &s) {
        Ok(m) => m,
        Err(_) => return Ok(false),
    };
    Ok(super::random::timing_safe_eq(&m.to_bytes_be_padded(k), &em))
}

/// PSS salt-length option semantics (`saltLength`): `RSA_PSS_SALTLEN_DIGEST` (-1) = hash
/// length, `RSA_PSS_SALTLEN_MAX_SIGN`/`AUTO` (-2) = maximum when signing / auto-detect when
/// verifying. The original's default (option absent) is the digest length for signing and
/// auto-detect for verification.
pub const PSS_SALTLEN_DIGEST: i64 = -1;
pub const PSS_SALTLEN_MAX_OR_AUTO: i64 = -2;

/// RSASSA-PSS signature with MGF1(`alg`). `salt_len` per [`PSS_SALTLEN_DIGEST`] etc.
/// Error: `RSA-PSS: salt too long for the modulus`.
pub fn rsa_pss_sign(key: &RsaPrivateKey, alg: HashAlg, msg: &[u8], salt_len: i64) -> Result<Vec<u8>, CryptoError> {
    let m_hash = digest(alg, msg);
    let h_len = alg.output_len();
    let mod_bits = key.n.bits();
    if mod_bits < 2 {
        return Err(err("RSA-PSS: salt too long for the modulus"));
    }
    let em_bits = mod_bits - 1;
    let em_len = em_bits.div_ceil(8);
    let s_len = match salt_len {
        PSS_SALTLEN_DIGEST => h_len as i64,
        PSS_SALTLEN_MAX_OR_AUTO => em_len as i64 - h_len as i64 - 2,
        n => n,
    };
    if s_len < 0 || em_len < h_len + s_len as usize + 2 {
        return Err(err("RSA-PSS: salt too long for the modulus"));
    }
    let s_len = s_len as usize;
    let mut salt = vec![0u8; s_len];
    fill_random(&mut salt);
    let mut h = Hasher::new(alg);
    h.update(&[0u8; 8]);
    h.update(&m_hash);
    h.update(&salt);
    let hh = h.finalize();
    let db_len = em_len - h_len - 1;
    let mut db = vec![0u8; db_len];
    db[db_len - s_len - 1] = 0x01;
    db[db_len - s_len..].copy_from_slice(&salt);
    let mask = mgf1(alg, &hh, db_len);
    for i in 0..db_len {
        db[i] ^= mask[i];
    }
    let excess = 8 * em_len - em_bits;
    db[0] &= 0xffu8 >> excess;
    let mut em = db;
    em.extend_from_slice(&hh);
    em.push(0xbc);
    let s = rsa_private_raw(key, &BigUint::from_bytes_be(&em))?;
    Ok(s.to_bytes_be_padded(key.size()))
}

/// Verify RSASSA-PSS. `salt_len`: `None` or -2 = auto-detect, -1 = digest length, n >= 0 exact.
pub fn rsa_pss_verify(key: &RsaPublicKey, alg: HashAlg, msg: &[u8], sig: &[u8], salt_len: Option<i64>) -> bool {
    let k = key.size();
    if sig.len() != k {
        return false;
    }
    let s = BigUint::from_bytes_be(sig);
    let m = match rsa_public_raw(key, &s) {
        Ok(m) => m,
        Err(_) => return false,
    };
    let m_hash = digest(alg, msg);
    let h_len = alg.output_len();
    if key.n.bits() < 2 {
        return false;
    }
    let em_bits = key.n.bits() - 1;
    let em_len = em_bits.div_ceil(8);
    if m.bits() > em_bits {
        return false;
    }
    let em = m.to_bytes_be_padded(em_len);
    if em.len() != em_len || em_len < h_len + 2 || em[em_len - 1] != 0xbc {
        return false;
    }
    let db_len = em_len - h_len - 1;
    let (masked_db, hh) = (&em[..db_len], &em[db_len..em_len - 1]);
    let excess = 8 * em_len - em_bits;
    if excess > 0 && masked_db[0] & !(0xffu8 >> excess) != 0 {
        return false;
    }
    let mask = mgf1(alg, hh, db_len);
    let mut db: Vec<u8> = masked_db.iter().zip(mask.iter()).map(|(a, b)| a ^ b).collect();
    db[0] &= 0xffu8 >> excess;
    let wanted = match salt_len {
        None | Some(PSS_SALTLEN_MAX_OR_AUTO) => None,
        Some(PSS_SALTLEN_DIGEST) => Some(h_len),
        Some(n) if n >= 0 => Some(n as usize),
        Some(_) => return false,
    };
    let sep = match db.iter().position(|&b| b != 0) {
        Some(i) if db[i] == 0x01 => i,
        _ => return false,
    };
    let s_len = db_len - sep - 1;
    if let Some(w) = wanted {
        if w != s_len {
            return false;
        }
    }
    let salt = &db[sep + 1..];
    let mut h = Hasher::new(alg);
    h.update(&[0u8; 8]);
    h.update(&m_hash);
    h.update(salt);
    super::random::timing_safe_eq(&h.finalize(), hh)
}

/// RSAES-OAEP encryption with MGF1 over the same hash (`oaepHash`, default sha1 in the
/// binding). Error: `RSA-OAEP: message too long` (also when `k < 2*hLen + 2`).
pub fn rsa_oaep_encrypt(key: &RsaPublicKey, alg: HashAlg, label: &[u8], msg: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    let h_len = alg.output_len();
    if k < 2 * h_len + 2 || msg.len() > k - 2 * h_len - 2 {
        return Err(err("RSA-OAEP: message too long"));
    }
    let l_hash = digest(alg, label);
    let db_len = k - h_len - 1;
    let mut db = Vec::with_capacity(db_len);
    db.extend_from_slice(&l_hash);
    db.extend(std::iter::repeat(0u8).take(k - msg.len() - 2 * h_len - 2));
    db.push(0x01);
    db.extend_from_slice(msg);
    let mut seed = vec![0u8; h_len];
    fill_random(&mut seed);
    let db_mask = mgf1(alg, &seed, db_len);
    for i in 0..db_len {
        db[i] ^= db_mask[i];
    }
    let seed_mask = mgf1(alg, &db, h_len);
    for i in 0..h_len {
        seed[i] ^= seed_mask[i];
    }
    let mut em = Vec::with_capacity(k);
    em.push(0);
    em.extend_from_slice(&seed);
    em.extend_from_slice(&db);
    let c = rsa_public_raw(key, &BigUint::from_bytes_be(&em))?;
    Ok(c.to_bytes_be_padded(k))
}

/// RSAES-OAEP decryption. The ciphertext length is not checked (only `c < n`, error
/// `RSA: data too large for the modulus`); any decoding failure →
/// `RSA-OAEP: decryption error`.
pub fn rsa_oaep_decrypt(key: &RsaPrivateKey, alg: HashAlg, label: &[u8], ct: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    let h_len = alg.output_len();
    let c = BigUint::from_bytes_be(ct);
    let m = rsa_private_raw(key, &c)?;
    let derr = || err("RSA-OAEP: decryption error");
    if k < 2 * h_len + 2 {
        return Err(derr());
    }
    let em = m.to_bytes_be_padded(k);
    if em.len() != k {
        return Err(derr());
    }
    let (y, masked_seed, masked_db) = (em[0], &em[1..1 + h_len], &em[1 + h_len..]);
    let seed_mask = mgf1(alg, masked_db, h_len);
    let seed: Vec<u8> = masked_seed.iter().zip(seed_mask.iter()).map(|(a, b)| a ^ b).collect();
    let db_mask = mgf1(alg, &seed, k - h_len - 1);
    let db: Vec<u8> = masked_db.iter().zip(db_mask.iter()).map(|(a, b)| a ^ b).collect();
    let l_hash = digest(alg, label);
    if y != 0 || !super::random::timing_safe_eq(&db[..h_len], &l_hash) {
        return Err(derr());
    }
    let rest = &db[h_len..];
    match rest.iter().position(|&b| b != 0) {
        Some(i) if rest[i] == 0x01 => Ok(rest[i + 1..].to_vec()),
        _ => Err(derr()),
    }
}

/// RSAES-PKCS1-v1_5 encryption (block type 2, random non-zero padding).
/// Error: `RSA-PKCS1: message too long` (`msg.len() > k - 11`).
pub fn rsa_pkcs1v15_encrypt(key: &RsaPublicKey, msg: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    if k < 11 || msg.len() > k - 11 {
        return Err(err("RSA-PKCS1: message too long"));
    }
    let ps_len = k - msg.len() - 3;
    let mut ps = vec![0u8; ps_len];
    fill_random(&mut ps);
    for b in ps.iter_mut() {
        while *b == 0 {
            let mut x = [0u8; 1];
            fill_random(&mut x);
            *b = x[0];
        }
    }
    let mut em = Vec::with_capacity(k);
    em.push(0);
    em.push(2);
    em.extend_from_slice(&ps);
    em.push(0);
    em.extend_from_slice(msg);
    let c = rsa_public_raw(key, &BigUint::from_bytes_be(&em))?;
    Ok(c.to_bytes_be_padded(k))
}

/// RSAES-PKCS1-v1_5 decryption. NOTE: the original's `privateDecrypt` refuses this padding
/// (TypeError `RSA_PKCS1_PADDING is no longer supported for private decryption`, like Node
/// 22); provided for completeness. Error: `RSA-PKCS1: decryption error`.
pub fn rsa_pkcs1v15_decrypt(key: &RsaPrivateKey, ct: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    if k < 11 {
        return Err(err("RSA-PKCS1: decryption error"));
    }
    let m = rsa_private_raw(key, &BigUint::from_bytes_be(ct))?;
    let em = m.to_bytes_be_padded(k);
    if em.len() != k || em[0] != 0 || em[1] != 2 {
        return Err(err("RSA-PKCS1: decryption error"));
    }
    match em[2..].iter().position(|&b| b == 0) {
        Some(i) if i >= 8 => Ok(em[2 + i + 1..].to_vec()),
        _ => Err(err("RSA-PKCS1: decryption error")),
    }
}

/// `privateEncrypt` with `RSA_PKCS1_PADDING` (block type 1: `00 01 FF.. 00 M`).
/// Error: `privateEncrypt: message too long` (`msg.len() > k - 11`).
pub fn rsa_private_encrypt_pkcs1(key: &RsaPrivateKey, msg: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    if k < 11 || msg.len() > k - 11 {
        return Err(err("privateEncrypt: message too long"));
    }
    let mut em = Vec::with_capacity(k);
    em.push(0);
    em.push(1);
    em.extend(std::iter::repeat(0xffu8).take(k - msg.len() - 3));
    em.push(0);
    em.extend_from_slice(msg);
    let s = rsa_private_raw(key, &BigUint::from_bytes_be(&em))?;
    Ok(s.to_bytes_be_padded(k))
}

/// `publicDecrypt` with `RSA_PKCS1_PADDING`: `EM = 00 01 FF* 00 M` (any number of FF bytes,
/// including none). Errors: `RSA: data too large for the modulus`,
/// `publicDecrypt: decryption error`.
pub fn rsa_public_decrypt_pkcs1(key: &RsaPublicKey, data: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = key.size();
    let m = rsa_public_raw(key, &BigUint::from_bytes_be(data))?;
    let em = m.to_bytes_be_padded(k);
    let derr = || err("publicDecrypt: decryption error");
    if em.len() < 2 || em[0] != 0 || em[1] != 1 {
        return Err(derr());
    }
    let mut i = 2;
    while i < em.len() && em[i] == 0xff {
        i += 1;
    }
    if i >= em.len() || em[i] != 0 {
        return Err(derr());
    }
    Ok(em[i + 1..].to_vec())
}

/// `RSA_NO_PADDING` for all four operations: `data` must be exactly `k` bytes
/// (`RSA_NO_PADDING requires data with the same size as the modulus`) and `< n`
/// (`RSA: data too large for the modulus`). `private_op` selects `d` vs `e`.
pub fn rsa_no_padding(n: &BigUint, op: impl FnOnce(&BigUint) -> Result<BigUint, CryptoError>, data: &[u8]) -> Result<Vec<u8>, CryptoError> {
    let k = n.bits().div_ceil(8);
    if data.len() != k {
        return Err(err("RSA_NO_PADDING requires data with the same size as the modulus"));
    }
    let r = op(&BigUint::from_bytes_be(data))?;
    Ok(r.to_bytes_be_padded(k))
}

/// Convenience wrappers for [`rsa_no_padding`].
pub fn rsa_public_no_padding(key: &RsaPublicKey, data: &[u8]) -> Result<Vec<u8>, CryptoError> {
    rsa_no_padding(&key.n, |m| rsa_public_raw(key, m), data)
}

pub fn rsa_private_no_padding(key: &RsaPrivateKey, data: &[u8]) -> Result<Vec<u8>, CryptoError> {
    rsa_no_padding(&key.n, |m| rsa_private_raw(key, m), data)
}
