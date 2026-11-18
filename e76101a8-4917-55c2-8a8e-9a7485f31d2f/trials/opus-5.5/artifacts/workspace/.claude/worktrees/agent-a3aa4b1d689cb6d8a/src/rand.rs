//! Random numbers for GUIDs and project uids, from the system's entropy.

use std::cell::RefCell;
use std::io::Read;

thread_local! {
    static STATE: RefCell<[u64; 4]> = RefCell::new(seed());
}

fn seed() -> [u64; 4] {
    let mut buf = [0u8; 32];
    let ok = std::fs::File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut buf)).is_ok();
    if !ok {
        use std::collections::hash_map::RandomState;
        use std::hash::{BuildHasher, Hasher};
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0);
        for i in 0..4 {
            let mut h = RandomState::new().build_hasher();
            h.write_u64(t ^ (i as u64));
            buf[i * 8..i * 8 + 8].copy_from_slice(&h.finish().to_le_bytes());
        }
    }
    let mut s = [0u64; 4];
    for i in 0..4 {
        s[i] = u64::from_le_bytes(buf[i * 8..i * 8 + 8].try_into().unwrap());
    }
    if s == [0; 4] {
        s[0] = 0x9e3779b97f4a7c15;
    }
    s
}

/// xoshiro256** over the seed.
pub fn next_u64() -> u64 {
    STATE.with(|st| {
        let mut s = st.borrow_mut();
        let result = s[1].wrapping_mul(5).rotate_left(7).wrapping_mul(9);
        let t = s[1] << 17;
        s[2] ^= s[0];
        s[3] ^= s[1];
        s[1] ^= s[2];
        s[0] ^= s[3];
        s[2] ^= t;
        s[3] = s[3].rotate_left(45);
        result
    })
}

/// A random (version 4) GUID, lowercase and hyphenated.
pub fn guid() -> String {
    let a = next_u64();
    let b = next_u64();
    let mut bytes = [0u8; 16];
    bytes[..8].copy_from_slice(&a.to_be_bytes());
    bytes[8..].copy_from_slice(&b.to_be_bytes());
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let h: String = bytes.iter().map(|b| format!("{:02x}", b)).collect();
    format!("{}-{}-{}-{}-{}", &h[0..8], &h[8..12], &h[12..16], &h[16..20], &h[20..32])
}

/// Random alphanumeric characters, as tempfile names its files.
pub fn alnum(n: usize) -> String {
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    (0..n).map(|_| CHARS[(next_u64() % CHARS.len() as u64) as usize] as char).collect()
}
