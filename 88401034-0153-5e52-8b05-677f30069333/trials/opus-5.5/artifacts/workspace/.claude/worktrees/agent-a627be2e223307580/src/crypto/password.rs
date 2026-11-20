//! `Bun.password` (the original's `__password` native): Argon2 PHC strings and bcrypt.

use super::argon2::{argon2, Argon2Params, Argon2Variant};
use super::blowfish_tables::{P_INIT, S_INIT};
use super::hash::{digest, HashAlg};
use super::CryptoError;

// ---- bcrypt ----------------------------------------------------------------------------

struct Blowfish {
    p: [u32; 18],
    s: [[u32; 256]; 4],
}

impl Blowfish {
    fn initial() -> Blowfish {
        let mut s = [[0u32; 256]; 4];
        for (i, sb) in s.iter_mut().enumerate() {
            sb.copy_from_slice(&S_INIT[i * 256..(i + 1) * 256]);
        }
        Blowfish { p: P_INIT, s }
    }

    #[inline]
    fn f(&self, x: u32) -> u32 {
        let a = self.s[0][(x >> 24) as usize];
        let b = self.s[1][((x >> 16) & 0xff) as usize];
        let c = self.s[2][((x >> 8) & 0xff) as usize];
        let d = self.s[3][(x & 0xff) as usize];
        (a.wrapping_add(b) ^ c).wrapping_add(d)
    }

    #[inline]
    fn encrypt(&self, mut l: u32, mut r: u32) -> (u32, u32) {
        for i in (0..16).step_by(2) {
            l ^= self.p[i];
            r ^= self.f(l);
            r ^= self.p[i + 1];
            l ^= self.f(r);
        }
        l ^= self.p[16];
        r ^= self.p[17];
        (r, l)
    }

    fn stream_word(data: &[u8], pos: &mut usize) -> u32 {
        let mut w = 0u32;
        for _ in 0..4 {
            w = (w << 8) | data[*pos] as u32;
            *pos = (*pos + 1) % data.len();
        }
        w
    }

    /// EksBlowfish ExpandKey(state, salt, key); `salt = None` is ExpandKey(state, 0, key).
    fn expand(&mut self, salt: Option<&[u8]>, key: &[u8]) {
        let mut kpos = 0;
        for i in 0..18 {
            self.p[i] ^= Self::stream_word(key, &mut kpos);
        }
        let mut spos = 0;
        let (mut l, mut r) = (0u32, 0u32);
        let mut next = |l: &mut u32, r: &mut u32, this: &Blowfish| {
            if let Some(s) = salt {
                *l ^= Self::stream_word(s, &mut spos);
                *r ^= Self::stream_word(s, &mut spos);
            }
            let (a, b) = this.encrypt(*l, *r);
            *l = a;
            *r = b;
        };
        for i in (0..18).step_by(2) {
            next(&mut l, &mut r, self);
            self.p[i] = l;
            self.p[i + 1] = r;
        }
        for sb in 0..4 {
            for k in (0..256).step_by(2) {
                next(&mut l, &mut r, self);
                self.s[sb][k] = l;
                self.s[sb][k + 1] = r;
            }
        }
    }
}

/// Raw bcrypt: returns the 23 output bytes used in the hash string. `key` is the full key
/// material (callers append the NUL terminator / truncate as the variant requires).
pub fn bcrypt_raw(cost: u32, salt: &[u8; 16], key: &[u8]) -> [u8; 23] {
    let cost = cost.min(31);
    let mut st = Blowfish::initial();
    let key: &[u8] = if key.is_empty() { &[0] } else { key };
    st.expand(Some(salt), key);
    let rounds = 1u64 << cost;
    for _ in 0..rounds {
        st.expand(None, key);
        st.expand(None, salt);
    }
    let mut ctext = [0u32; 6];
    let magic = b"OrpheanBeholderScryDoubt";
    for i in 0..6 {
        ctext[i] = u32::from_be_bytes([magic[i * 4], magic[i * 4 + 1], magic[i * 4 + 2], magic[i * 4 + 3]]);
    }
    for _ in 0..64 {
        for j in (0..6).step_by(2) {
            let (l, r) = st.encrypt(ctext[j], ctext[j + 1]);
            ctext[j] = l;
            ctext[j + 1] = r;
        }
    }
    let mut out = [0u8; 24];
    for i in 0..6 {
        out[i * 4..i * 4 + 4].copy_from_slice(&ctext[i].to_be_bytes());
    }
    let mut r = [0u8; 23];
    r.copy_from_slice(&out[..23]);
    r
}

const BCRYPT_B64: &[u8; 64] = b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

fn bcrypt_b64_encode(data: &[u8]) -> String {
    let mut out = String::new();
    let mut i = 0;
    while i < data.len() {
        let c1 = data[i];
        out.push(BCRYPT_B64[(c1 >> 2) as usize] as char);
        let mut c = (c1 & 0x03) << 4;
        if i + 1 >= data.len() {
            out.push(BCRYPT_B64[c as usize] as char);
            break;
        }
        let c2 = data[i + 1];
        c |= c2 >> 4;
        out.push(BCRYPT_B64[c as usize] as char);
        c = (c2 & 0x0f) << 2;
        if i + 2 >= data.len() {
            out.push(BCRYPT_B64[c as usize] as char);
            break;
        }
        let c3 = data[i + 2];
        c |= c3 >> 6;
        out.push(BCRYPT_B64[c as usize] as char);
        out.push(BCRYPT_B64[(c3 & 0x3f) as usize] as char);
        i += 3;
    }
    out
}

fn bcrypt_b64_decode(s: &str, out_len: usize) -> Option<Vec<u8>> {
    let vals: Option<Vec<u8>> = s.bytes().map(|c| BCRYPT_B64.iter().position(|&x| x == c).map(|p| p as u8)).collect();
    let vals = vals?;
    let mut out = Vec::with_capacity(out_len);
    let mut i = 0;
    while out.len() < out_len && i + 1 < vals.len() {
        out.push((vals[i] << 2) | (vals[i + 1] >> 4));
        if out.len() == out_len || i + 2 >= vals.len() {
            break;
        }
        out.push((vals[i + 1] << 4) | (vals[i + 2] >> 2));
        if out.len() == out_len || i + 3 >= vals.len() {
            break;
        }
        out.push((vals[i + 2] << 6) | vals[i + 3]);
        i += 4;
    }
    if out.len() == out_len {
        Some(out)
    } else {
        None
    }
}

/// Key material the way Bun does it: passwords longer than 72 bytes are first replaced by
/// their raw SHA-512 digest; the key is the password plus a NUL terminator, truncated to
/// 72 bytes.
fn bcrypt_key(password: &[u8]) -> Vec<u8> {
    let pw: Vec<u8> = if password.len() > 72 { digest(HashAlg::Sha512, password) } else { password.to_vec() };
    let mut key = pw;
    key.push(0);
    key.truncate(72);
    key
}

/// `$2b$<cost>$<22-char salt><31-char hash>` for a given salt.
pub fn bcrypt_hash_with_salt(password: &[u8], cost: u32, salt: &[u8; 16]) -> String {
    let raw = bcrypt_raw(cost, salt, &bcrypt_key(password));
    format!("$2b${:02}${}{}", cost, bcrypt_b64_encode(salt), bcrypt_b64_encode(&raw))
}

// ---- Argon2 PHC strings -----------------------------------------------------------------

fn b64_nopad(data: &[u8]) -> String {
    super::asn1::base64_encode(data).trim_end_matches('=').to_string()
}

fn b64_nopad_decode(s: &str) -> Option<Vec<u8>> {
    if s.is_empty() || !s.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'+' || c == b'/') || s.len() % 4 == 1 {
        return None;
    }
    Some(super::asn1::base64_decode(s))
}

/// `$argon2id$v=19$m=<m>,t=<t>,p=1$<salt b64>$<hash b64>` (unpadded standard base64,
/// 32-byte salt and 32-byte hash, parallelism 1) — the format `Bun.password.hash` produces.
pub fn argon2_phc_with_salt(variant: Argon2Variant, password: &[u8], memory_cost: u32, time_cost: u32, salt: &[u8]) -> Result<String, CryptoError> {
    let params = Argon2Params {
        message: password,
        nonce: salt,
        secret: b"",
        associated_data: b"",
        parallelism: 1,
        tag_length: 32,
        memory: memory_cost,
        passes: time_cost,
        version: 0x13,
    };
    let tag = argon2(variant, &params)?;
    Ok(format!(
        "${}$v=19$m={},t={},p=1${}${}",
        variant.name(),
        memory_cost,
        time_cost,
        b64_nopad(salt),
        b64_nopad(&tag)
    ))
}

// ---- Bun.password -----------------------------------------------------------------------

/// `Bun.password` algorithms.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PasswordAlgorithm {
    Argon2d,
    Argon2i,
    Argon2id,
    Bcrypt,
}

impl PasswordAlgorithm {
    /// Case-insensitive (`'ARGON2ID'` works). Unknown → TypeError
    /// `Unsupported password hashing algorithm '<name>'`.
    pub fn from_name(name: &str) -> Result<PasswordAlgorithm, CryptoError> {
        match name.to_lowercase().as_str() {
            "argon2d" => Ok(PasswordAlgorithm::Argon2d),
            "argon2i" => Ok(PasswordAlgorithm::Argon2i),
            "argon2id" => Ok(PasswordAlgorithm::Argon2id),
            "bcrypt" => Ok(PasswordAlgorithm::Bcrypt),
            _ => Err(CryptoError::type_error(format!("Unsupported password hashing algorithm '{}'", name))),
        }
    }
}

/// Defaults: argon2id, `memoryCost` 65536 (KiB), `timeCost` 2, bcrypt `cost` 10.
pub const DEFAULT_MEMORY_COST: u32 = 65536;
pub const DEFAULT_TIME_COST: u32 = 2;
pub const DEFAULT_BCRYPT_COST: u32 = 10;

/// `Bun.password.hash[Sync]` with already-validated options (the binding throws RangeError
/// `memoryCost must be an integer between 1 and 4294967295`, `timeCost must be an integer
/// between 1 and 4294967295`, `cost must be an integer between 4 and 31`). Argon2 uses a
/// random 32-byte salt; bcrypt a random 16-byte salt.
pub fn password_hash(password: &[u8], alg: PasswordAlgorithm, memory_cost: u32, time_cost: u32, cost: u32) -> Result<String, CryptoError> {
    match alg {
        PasswordAlgorithm::Bcrypt => {
            if !(4..=31).contains(&cost) {
                return Err(CryptoError::range_error("cost must be an integer between 4 and 31"));
            }
            let mut salt = [0u8; 16];
            super::random::fill_random(&mut salt);
            Ok(bcrypt_hash_with_salt(password, cost, &salt))
        }
        _ => {
            if memory_cost == 0 {
                return Err(CryptoError::range_error("memoryCost must be an integer between 1 and 4294967295"));
            }
            if time_cost == 0 {
                return Err(CryptoError::range_error("timeCost must be an integer between 1 and 4294967295"));
            }
            let variant = match alg {
                PasswordAlgorithm::Argon2d => Argon2Variant::Argon2d,
                PasswordAlgorithm::Argon2i => Argon2Variant::Argon2i,
                _ => Argon2Variant::Argon2id,
            };
            let mut salt = [0u8; 32];
            super::random::fill_random(&mut salt);
            argon2_phc_with_salt(variant, password, memory_cost, time_cost, &salt)
        }
    }
}

fn verify_error(kind: &str) -> CryptoError {
    CryptoError::error(format!("Password verification failed with error \"{}\"", kind))
}

/// `Bun.password.verify[Sync]`. Errors (plain Error):
/// `Password verification failed with error "UnsupportedAlgorithm"` (not `$argon2…$` /
/// `$2…$`, including the empty string) and `... "InvalidEncoding"` (malformed PHC/bcrypt
/// string, version other than `v=19`). `$2a$`/`$2b$`/`$2y$`/`$2x$` hashes are compared with
/// the same key derivation.
pub fn password_verify(password: &[u8], hash: &str) -> Result<bool, CryptoError> {
    if let Some(rest) = hash.strip_prefix("$argon2") {
        let parts: Vec<&str> = hash.split('$').collect();
        // ["", "argon2id", "v=19", "m=..,t=..,p=..", salt, hash]
        let variant = match parts.get(1).copied() {
            Some("argon2id") => Argon2Variant::Argon2id,
            Some("argon2i") => Argon2Variant::Argon2i,
            Some("argon2d") => Argon2Variant::Argon2d,
            _ => {
                let _ = rest;
                return Err(verify_error("UnsupportedAlgorithm"));
            }
        };
        if parts.len() != 6 || parts[2] != "v=19" {
            return Err(verify_error("InvalidEncoding"));
        }
        let (mut m, mut t, mut p) = (None, None, None);
        for kv in parts[3].split(',') {
            let (k, v) = kv.split_once('=').ok_or_else(|| verify_error("InvalidEncoding"))?;
            let v: u32 = v.parse().map_err(|_| verify_error("InvalidEncoding"))?;
            match k {
                "m" => m = Some(v),
                "t" => t = Some(v),
                "p" => p = Some(v),
                _ => return Err(verify_error("InvalidEncoding")),
            }
        }
        let (m, t, p) = match (m, t, p) {
            (Some(m), Some(t), Some(p)) if m > 0 && t > 0 && p > 0 => (m, t, p),
            _ => return Err(verify_error("InvalidEncoding")),
        };
        let salt = b64_nopad_decode(parts[4]).ok_or_else(|| verify_error("InvalidEncoding"))?;
        let expected = b64_nopad_decode(parts[5]).ok_or_else(|| verify_error("InvalidEncoding"))?;
        if expected.len() < 4 {
            return Err(verify_error("InvalidEncoding"));
        }
        if salt.len() < 8 {
            // The original reports a mismatch (not an error) for too-short salts.
            return Ok(false);
        }
        let params = Argon2Params {
            message: password,
            nonce: &salt,
            secret: b"",
            associated_data: b"",
            parallelism: p,
            tag_length: expected.len() as u32,
            memory: m,
            passes: t,
            version: 0x13,
        };
        let tag = argon2(variant, &params).map_err(|_| verify_error("InvalidEncoding"))?;
        return Ok(super::random::timing_safe_eq(&tag, &expected));
    }
    if ["$2a$", "$2b$", "$2x$", "$2y$"].iter().any(|p| hash.starts_with(p)) {
        let b = hash.as_bytes();
        // $2b$NN$ + 22 + 31 = 60 chars
        if b.len() != 60 || !hash.is_ascii() || b[6] != b'$' {
            return Err(verify_error("InvalidEncoding"));
        }
        let cost: u32 = hash[4..6].parse().map_err(|_| verify_error("InvalidEncoding"))?;
        if !(4..=31).contains(&cost) {
            return Err(verify_error("InvalidEncoding"));
        }
        let salt = bcrypt_b64_decode(&hash[7..29], 16).ok_or_else(|| verify_error("InvalidEncoding"))?;
        let expected = bcrypt_b64_decode(&hash[29..60], 23).ok_or_else(|| verify_error("InvalidEncoding"))?;
        let mut s16 = [0u8; 16];
        s16.copy_from_slice(&salt);
        let raw = bcrypt_raw(cost, &s16, &bcrypt_key(password));
        return Ok(super::random::timing_safe_eq(&raw, &expected));
    }
    Err(verify_error("UnsupportedAlgorithm"))
}
