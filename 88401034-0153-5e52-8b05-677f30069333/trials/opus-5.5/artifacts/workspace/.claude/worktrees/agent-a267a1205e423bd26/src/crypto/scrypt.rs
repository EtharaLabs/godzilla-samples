//! scrypt (RFC 7914).

use super::hash::HashAlg;
use super::kdf::try_pbkdf2;
use super::{CryptoError, ErrorKind};

fn salsa20_8(b: &mut [u32; 16]) {
    let mut x = *b;
    for _ in 0..4 {
        // Column round.
        x[4] ^= x[0].wrapping_add(x[12]).rotate_left(7);
        x[8] ^= x[4].wrapping_add(x[0]).rotate_left(9);
        x[12] ^= x[8].wrapping_add(x[4]).rotate_left(13);
        x[0] ^= x[12].wrapping_add(x[8]).rotate_left(18);
        x[9] ^= x[5].wrapping_add(x[1]).rotate_left(7);
        x[13] ^= x[9].wrapping_add(x[5]).rotate_left(9);
        x[1] ^= x[13].wrapping_add(x[9]).rotate_left(13);
        x[5] ^= x[1].wrapping_add(x[13]).rotate_left(18);
        x[14] ^= x[10].wrapping_add(x[6]).rotate_left(7);
        x[2] ^= x[14].wrapping_add(x[10]).rotate_left(9);
        x[6] ^= x[2].wrapping_add(x[14]).rotate_left(13);
        x[10] ^= x[6].wrapping_add(x[2]).rotate_left(18);
        x[3] ^= x[15].wrapping_add(x[11]).rotate_left(7);
        x[7] ^= x[3].wrapping_add(x[15]).rotate_left(9);
        x[11] ^= x[7].wrapping_add(x[3]).rotate_left(13);
        x[15] ^= x[11].wrapping_add(x[7]).rotate_left(18);
        // Row round.
        x[1] ^= x[0].wrapping_add(x[3]).rotate_left(7);
        x[2] ^= x[1].wrapping_add(x[0]).rotate_left(9);
        x[3] ^= x[2].wrapping_add(x[1]).rotate_left(13);
        x[0] ^= x[3].wrapping_add(x[2]).rotate_left(18);
        x[6] ^= x[5].wrapping_add(x[4]).rotate_left(7);
        x[7] ^= x[6].wrapping_add(x[5]).rotate_left(9);
        x[4] ^= x[7].wrapping_add(x[6]).rotate_left(13);
        x[5] ^= x[4].wrapping_add(x[7]).rotate_left(18);
        x[11] ^= x[10].wrapping_add(x[9]).rotate_left(7);
        x[8] ^= x[11].wrapping_add(x[10]).rotate_left(9);
        x[9] ^= x[8].wrapping_add(x[11]).rotate_left(13);
        x[10] ^= x[9].wrapping_add(x[8]).rotate_left(18);
        x[12] ^= x[15].wrapping_add(x[14]).rotate_left(7);
        x[13] ^= x[12].wrapping_add(x[15]).rotate_left(9);
        x[14] ^= x[13].wrapping_add(x[12]).rotate_left(13);
        x[15] ^= x[14].wrapping_add(x[13]).rotate_left(18);
    }
    for i in 0..16 {
        b[i] = b[i].wrapping_add(x[i]);
    }
}

/// BlockMix_salsa20/8 over `2r` 64-byte blocks (`input`/`output` have `32*r` words).
fn block_mix(input: &[u32], output: &mut [u32], r: usize) {
    let mut x = [0u32; 16];
    x.copy_from_slice(&input[(2 * r - 1) * 16..2 * r * 16]);
    for i in 0..2 * r {
        for k in 0..16 {
            x[k] ^= input[i * 16 + k];
        }
        salsa20_8(&mut x);
        // Even blocks go to the first half, odd blocks to the second half.
        let dst = if i % 2 == 0 { (i / 2) * 16 } else { (r + i / 2) * 16 };
        output[dst..dst + 16].copy_from_slice(&x);
    }
}

fn romix_block(block: &mut [u8], n: usize, r: usize, v: &mut [u32]) {
    let words = 32 * r;
    let mut x = vec![0u32; words];
    let mut y = vec![0u32; words];
    for (i, w) in x.iter_mut().enumerate() {
        *w = u32::from_le_bytes([block[i * 4], block[i * 4 + 1], block[i * 4 + 2], block[i * 4 + 3]]);
    }
    for i in 0..n {
        v[i * words..(i + 1) * words].copy_from_slice(&x);
        block_mix(&x, &mut y, r);
        std::mem::swap(&mut x, &mut y);
    }
    let mask = (n - 1) as u64;
    for _ in 0..n {
        let j_lo = x[(2 * r - 1) * 16] as u64;
        let j_hi = x[(2 * r - 1) * 16 + 1] as u64;
        let j = (((j_hi << 32) | j_lo) & mask) as usize;
        let vj = &v[j * words..(j + 1) * words];
        for k in 0..words {
            x[k] ^= vj[k];
        }
        block_mix(&x, &mut y, r);
        std::mem::swap(&mut x, &mut y);
    }
    for (i, w) in x.iter().enumerate() {
        block[i * 4..i * 4 + 4].copy_from_slice(&w.to_le_bytes());
    }
}

/// scrypt's ROMix applied in place to every `128*r`-byte chunk of `b` (i.e. to all `p`
/// chunks of `B`). This is the native the original exposes as `__crypto.scryptRomix(B, N, r)`;
/// `N` must be a power of two >= 2. Errors if `b.len()` is not a multiple of `128*r` or the
/// `128*r*N`-byte scratch buffer cannot be allocated.
pub fn scrypt_romix(b: &mut [u8], n: u64, r: u32) -> Result<(), CryptoError> {
    let r = r as usize;
    if n < 2 || (n & (n - 1)) != 0 || r == 0 {
        return Err(CryptoError::coded(ErrorKind::RangeError, "ERR_CRYPTO_INVALID_SCRYPT_PARAMS", "Invalid scrypt params"));
    }
    let chunk = 128 * r;
    if b.len() % chunk != 0 {
        return Err(CryptoError::coded(ErrorKind::RangeError, "ERR_CRYPTO_INVALID_SCRYPT_PARAMS", "Invalid scrypt params"));
    }
    let words = (n as u128) * (32 * r as u128);
    if words > (usize::MAX / 8) as u128 {
        return Err(memory_limit_error());
    }
    let mut v: Vec<u32> = Vec::new();
    if v.try_reserve_exact(words as usize).is_err() {
        return Err(memory_limit_error());
    }
    v.resize(words as usize, 0);
    for blk in b.chunks_mut(chunk) {
        romix_block(blk, n as usize, r, &mut v);
    }
    Ok(())
}

fn memory_limit_error() -> CryptoError {
    CryptoError::coded(
        ErrorKind::RangeError,
        "ERR_CRYPTO_INVALID_SCRYPT_PARAMS",
        "Invalid scrypt params: error:030000AC:digital envelope routines::memory limit exceeded",
    )
}

/// Default `maxmem` used by `crypto.scrypt[Sync]` (32 MiB).
pub const SCRYPT_DEFAULT_MAXMEM: u64 = 32 * 1024 * 1024;

/// The numeric parameter checks of the original `scryptSync` (after defaults were applied:
/// `N || 16384`, `r || 8`, `p || 1`, `maxmem || 32 MiB`):
/// * `N < 2` or not a power of two → RangeError `ERR_CRYPTO_INVALID_SCRYPT_PARAMS`
///   `Invalid scrypt params`;
/// * `128*r*p + 128*r*(N+2) > maxmem` → RangeError `ERR_CRYPTO_INVALID_SCRYPT_PARAMS`
///   `Invalid scrypt params: error:030000AC:digital envelope routines::memory limit exceeded`.
pub fn scrypt_check_params(n: u64, r: u64, p: u64, maxmem: u64) -> Result<(), CryptoError> {
    if n < 2 || (n & (n - 1)) != 0 {
        return Err(CryptoError::coded(ErrorKind::RangeError, "ERR_CRYPTO_INVALID_SCRYPT_PARAMS", "Invalid scrypt params"));
    }
    let need = 128u128 * r as u128 * p as u128 + 128u128 * r as u128 * (n as u128 + 2);
    if need > maxmem as u128 {
        return Err(memory_limit_error());
    }
    Ok(())
}

/// scrypt key derivation: `PBKDF2-SHA256(P, S, 1, 128rp)` → ROMix each chunk →
/// `PBKDF2-SHA256(P, B', 1, dkLen)`. Validates `N` (power of two >= 2), `r >= 1`, `p >= 1`
/// but NOT `maxmem` — call [`scrypt_check_params`] first for the original's semantics.
pub fn scrypt(password: &[u8], salt: &[u8], n: u64, r: u32, p: u32, key_len: usize) -> Result<Vec<u8>, CryptoError> {
    if n < 2 || (n & (n - 1)) != 0 || r == 0 || p == 0 {
        return Err(CryptoError::coded(ErrorKind::RangeError, "ERR_CRYPTO_INVALID_SCRYPT_PARAMS", "Invalid scrypt params"));
    }
    let blen = 128u128 * r as u128 * p as u128;
    if blen > (isize::MAX as u128) / 2 {
        return Err(memory_limit_error());
    }
    let mut b = try_pbkdf2(HashAlg::Sha256, password, salt, 1, blen as usize).map_err(|_| memory_limit_error())?;
    scrypt_romix(&mut b, n, r)?;
    try_pbkdf2(HashAlg::Sha256, password, &b, 1, key_len)
}
