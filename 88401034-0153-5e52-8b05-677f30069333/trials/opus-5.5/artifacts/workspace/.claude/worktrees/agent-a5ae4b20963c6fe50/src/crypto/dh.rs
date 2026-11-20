//! Finite-field Diffie-Hellman (`createDiffieHellman`, `getDiffieHellman('modp14')`).

use super::bigint::BigUint;
use super::CryptoError;

/// RFC 3526 2048-bit MODP group 14 prime (the only named group the original supports).
pub const MODP14_HEX: &str = "ffffffffffffffffc90fdaa22168c234c4c6628b80dc1cd129024e088a67cc74020bbea63b139b22514a08798e3404ddef9519b3cd3a431b302b0a6df25f14374fe1356d6d51c245e485b576625e7ec6f44c42e9a637ed6b0bff5cb6f406b7edee386bfb5a899fa5ae9f24117c4b1fe649286651ece45b3dc2007cb8a163bf0598da48361c55d39a69163fa8fd24cf5f83655d23dca3ad961c62f356208552bb9ed529077096966d670c354e4abc9804f1746c08ca18217c32905e462e36ce3be39e772c180e86039b2783a2ec07a28fb5c55df06f4c52c9de2bcbf6955817183995497cea956ae515d2261898fa051015728e5a8aacaa68ffffffffffffffff";

/// `getDiffieHellman(name)` / `createDiffieHellmanGroup(name)`: name is lower-cased;
/// only `modp14` exists. Error: `Unknown DH group '<name>' (lumen supports modp14)`.
pub fn named_group(name: &str) -> Result<(BigUint, BigUint), CryptoError> {
    if name.to_lowercase() != "modp14" {
        return Err(CryptoError::error(format!("Unknown DH group '{}' (lumen supports modp14)", name)));
    }
    Ok((BigUint::from_hex(MODP14_HEX).unwrap(), BigUint::from_u64(2)))
}

/// Byte length used for prime-sized outputs (`ceil(bits(p)/8)`).
pub fn prime_len(p: &BigUint) -> usize {
    p.bits().div_ceil(8)
}

/// Private key like the original: `2 + random(ceil(bits/8) bytes) mod (p - 3)` (p > 4).
pub fn generate_private(p: &BigUint) -> BigUint {
    if p <= &BigUint::from_u64(4) {
        return BigUint::from_u64(2);
    }
    let size = prime_len(p);
    let m = p.sub_u64(3);
    loop {
        let r = BigUint::from_bytes_be(&super::random::random_bytes(size)).rem(&m);
        let x = r.add_u64(2);
        if x > BigUint::one() {
            return x;
        }
    }
}

/// `g^x mod p`, left-padded to the prime length (`getPublicKey()`).
pub fn public_key(p: &BigUint, g: &BigUint, x: &BigUint) -> Vec<u8> {
    if p.is_zero() {
        return Vec::new();
    }
    g.modpow(x, p).to_bytes_be_padded(prime_len(p))
}

/// `computeSecret(other)`: rejects `other <= 1 || other >= p - 1` with
/// `Supplied key is too small`; result is left-padded to the prime length.
pub fn compute_secret(p: &BigUint, x: &BigUint, other: &BigUint) -> Result<Vec<u8>, CryptoError> {
    if p.is_zero() || other <= &BigUint::one() || other >= &p.sub_u64(1) {
        return Err(CryptoError::error("Supplied key is too small"));
    }
    Ok(other.modpow(x, p).to_bytes_be_padded(prime_len(p)))
}

/// `setPrivateKey` validation: `1 < x < p - 1`, else RangeError
/// `Private key is not valid for specified group`.
pub fn check_private(p: &BigUint, x: &BigUint) -> Result<(), CryptoError> {
    if p.is_zero() || x <= &BigUint::one() || x >= &p.sub_u64(1) {
        return Err(CryptoError::range_error("Private key is not valid for specified group"));
    }
    Ok(())
}
