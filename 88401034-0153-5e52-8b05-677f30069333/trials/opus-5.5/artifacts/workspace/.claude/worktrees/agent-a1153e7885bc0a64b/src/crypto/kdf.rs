//! PBKDF2 (RFC 8018) and HKDF (RFC 5869).

use super::hash::{HashAlg, Hmac};
use super::CryptoError;

/// PBKDF2-HMAC. `iterations == 0` behaves like 1 (the original's JS loop runs the first
/// HMAC unconditionally). `key_len == 0` yields an empty vector. Allocates `key_len` bytes
/// up front (aborts on allocation failure — use [`try_pbkdf2`] for untrusted sizes).
pub fn pbkdf2(alg: HashAlg, password: &[u8], salt: &[u8], iterations: u32, key_len: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(key_len);
    pbkdf2_into(alg, password, salt, iterations, key_len, &mut out);
    out
}

/// [`pbkdf2`] that reports allocation failure as RangeError `Array buffer allocation failed`.
pub fn try_pbkdf2(alg: HashAlg, password: &[u8], salt: &[u8], iterations: u32, key_len: usize) -> Result<Vec<u8>, CryptoError> {
    let mut out = Vec::new();
    if out.try_reserve_exact(key_len).is_err() {
        return Err(CryptoError::range_error("Array buffer allocation failed"));
    }
    pbkdf2_into(alg, password, salt, iterations, key_len, &mut out);
    Ok(out)
}

fn pbkdf2_into(alg: HashAlg, password: &[u8], salt: &[u8], iterations: u32, key_len: usize, out: &mut Vec<u8>) {
    let h_len = alg.output_len();
    let base = Hmac::new(alg, password);
    let mut block_index: u32 = 1;
    let mut u = [0u8; 64];
    let mut t = [0u8; 64];
    while out.len() < key_len {
        let mut mac = base.clone();
        mac.update(salt);
        mac.update(&block_index.to_be_bytes());
        mac.finalize_into(&mut u);
        t[..h_len].copy_from_slice(&u[..h_len]);
        for _ in 1..iterations {
            let mut mac = base.clone();
            mac.update(&u[..h_len]);
            mac.finalize_into(&mut u);
            for k in 0..h_len {
                t[k] ^= u[k];
            }
        }
        let take = (key_len - out.len()).min(h_len);
        out.extend_from_slice(&t[..take]);
        block_index = block_index.wrapping_add(1);
    }
}

/// HKDF-Extract: `PRK = HMAC(salt, ikm)`. An empty salt is equivalent to `HashLen` zero bytes.
pub fn hkdf_extract(alg: HashAlg, salt: &[u8], ikm: &[u8]) -> Vec<u8> {
    let mut m = Hmac::new(alg, salt);
    m.update(ikm);
    m.finalize()
}

/// HKDF-Expand. Errors (RangeError, no code, message
/// `hkdf: requested key length is too large`) when `key_len > 255 * HashLen`.
pub fn hkdf_expand(alg: HashAlg, prk: &[u8], info: &[u8], key_len: usize) -> Result<Vec<u8>, CryptoError> {
    let h_len = alg.output_len();
    let n = key_len.div_ceil(h_len);
    if n > 255 {
        return Err(CryptoError::range_error("hkdf: requested key length is too large"));
    }
    let base = Hmac::new(alg, prk);
    let mut okm = Vec::with_capacity(n * h_len);
    let mut prev: Vec<u8> = Vec::new();
    for i in 1..=n {
        let mut m = base.clone();
        m.update(&prev);
        m.update(info);
        m.update(&[i as u8]);
        prev = m.finalize();
        okm.extend_from_slice(&prev);
    }
    okm.truncate(key_len);
    Ok(okm)
}

/// HKDF (extract + expand), as `crypto.hkdfSync` computes it. The JS layer returns the
/// result as an `ArrayBuffer`.
pub fn hkdf(alg: HashAlg, ikm: &[u8], salt: &[u8], info: &[u8], key_len: usize) -> Result<Vec<u8>, CryptoError> {
    let h_len = alg.output_len();
    if key_len.div_ceil(h_len) > 255 {
        return Err(CryptoError::range_error("hkdf: requested key length is too large"));
    }
    let prk = hkdf_extract(alg, salt, ikm);
    hkdf_expand(alg, &prk, info, key_len)
}
