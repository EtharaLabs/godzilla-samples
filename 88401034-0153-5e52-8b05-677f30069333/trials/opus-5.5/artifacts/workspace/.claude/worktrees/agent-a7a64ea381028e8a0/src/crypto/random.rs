//! CSPRNG access (`/dev/urandom`), UUIDv4, `randomInt`, `timingSafeEqual`.

use std::fs::File;
use std::io::Read;
use std::sync::Mutex;

const POOL_SIZE: usize = 4096;

struct Pool {
    file: Option<File>,
    buf: Box<[u8; POOL_SIZE]>,
    pos: usize,
}

static POOL: Mutex<Option<Pool>> = Mutex::new(None);

fn read_os(file: &mut Option<File>, out: &mut [u8]) {
    if file.is_none() {
        *file = File::open("/dev/urandom").ok();
    }
    if let Some(f) = file.as_mut() {
        if f.read_exact(out).is_ok() {
            return;
        }
    }
    // Extremely unlikely fallback (no /dev/urandom): mix time, addresses and a counter
    // through SHA-512. Not expected to be reached on Linux/macOS.
    fallback_fill(out);
}

fn fallback_fill(out: &mut [u8]) {
    use super::hash::{HashAlg, Hasher};
    use std::sync::atomic::{AtomicU64, Ordering};
    static CTR: AtomicU64 = AtomicU64::new(0);
    let mut off = 0;
    while off < out.len() {
        let mut h = Hasher::new(HashAlg::Sha512);
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        h.update(&now.to_le_bytes());
        h.update(&CTR.fetch_add(1, Ordering::Relaxed).to_le_bytes());
        let local = 0u8;
        h.update(&(&local as *const u8 as usize).to_le_bytes());
        h.update(&std::process::id().to_le_bytes());
        let d = h.finalize();
        let take = (out.len() - off).min(d.len());
        out[off..off + take].copy_from_slice(&d[..take]);
        off += take;
    }
}

/// Fill `buf` with cryptographically secure random bytes (backs `randomFillSync`,
/// `getRandomValues`, `randomBytes`). Small requests are served from a 4 KiB pool.
pub fn fill_random(buf: &mut [u8]) {
    if buf.is_empty() {
        return;
    }
    let mut guard = match POOL.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    };
    let pool = guard.get_or_insert_with(|| Pool { file: None, buf: Box::new([0u8; POOL_SIZE]), pos: POOL_SIZE });
    if buf.len() > POOL_SIZE / 2 {
        read_os(&mut pool.file, buf);
        return;
    }
    let mut off = 0;
    while off < buf.len() {
        if pool.pos >= POOL_SIZE {
            let Pool { file, buf: pbuf, pos } = pool;
            read_os(file, &mut pbuf[..]);
            *pos = 0;
        }
        let take = (buf.len() - off).min(POOL_SIZE - pool.pos);
        buf[off..off + take].copy_from_slice(&pool.buf[pool.pos..pool.pos + take]);
        // Never hand out the same pool bytes twice.
        for b in &mut pool.buf[pool.pos..pool.pos + take] {
            *b = 0;
        }
        pool.pos += take;
        off += take;
    }
}

/// `n` random bytes.
pub fn random_bytes(n: usize) -> Vec<u8> {
    let mut v = vec![0u8; n];
    fill_random(&mut v);
    v
}

/// Format 16 bytes as a lower-case 8-4-4-4-12 UUID string.
pub fn format_uuid(b: &[u8; 16]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(36);
    for (i, byte) in b.iter().enumerate() {
        if i == 4 || i == 6 || i == 8 || i == 10 {
            s.push('-');
        }
        s.push(HEX[(byte >> 4) as usize] as char);
        s.push(HEX[(byte & 15) as usize] as char);
    }
    s
}

/// RFC 4122 version-4 UUID, lower-case (`crypto.randomUUID()`).
pub fn random_uuid() -> String {
    let mut b = [0u8; 16];
    fill_random(&mut b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    format_uuid(&b)
}

/// Uniform integer in `[min, max)`, using the original's rejection-sampling algorithm:
/// `range = max - min`, `bytes = max(1, ceil(ceil(log2(range)) / 8))`, draw big-endian
/// `bytes`-byte values `v` until `v < 2^(8*bytes) - (2^(8*bytes) % range)`, return
/// `min + v % range`. Returns `None` when `max <= min` (the JS layer throws
/// RangeError `The value of "max" is out of range. It must be greater than the value of "min".`).
/// Safe-integer validation (`randomInt: min and max must be safe integers`) is the binding's job.
pub fn random_int(min: i64, max: i64) -> Option<i64> {
    if max <= min {
        return None;
    }
    let range = (max as i128 - min as i128) as u128;
    // ceil(log2(range)) — for range == 1 this is 0.
    let bits = if range <= 1 { 0 } else { 128 - (range - 1).leading_zeros() } as usize;
    let bytes = bits.div_ceil(8).max(1);
    let modulus: u128 = 1u128 << (bytes * 8);
    let limit = modulus - (modulus % range);
    loop {
        let mut b = [0u8; 16];
        fill_random(&mut b[..bytes]);
        let mut v: u128 = 0;
        for x in &b[..bytes] {
            v = (v << 8) | *x as u128;
        }
        if v < limit {
            return Some((min as i128 + (v % range) as i128) as i64);
        }
    }
}

/// Constant-time equality. Returns `false` for different lengths (the JS layer throws
/// RangeError `Input buffers must have the same byte length` before calling this).
pub fn timing_safe_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    std::hint::black_box(diff) == 0
}

/// Parse an 8-4-4-4-12 hex UUID string (case-insensitive).
pub fn parse_uuid(s: &str) -> Option<[u8; 16]> {
    let hex: String = s.chars().filter(|c| *c != '-').collect();
    if s.len() != 36 || hex.len() != 32 || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let mut out = [0u8; 16];
    for i in 0..16 {
        out[i] = u8::from_str_radix(&hex[2 * i..2 * i + 2], 16).ok()?;
    }
    Some(out)
}

/// RFC 4122 namespaces by name (`dns`, `url`, `oid`, `x500`), as used by `Bun.randomUUIDv5`.
pub fn uuid_namespace(name: &str) -> Option<[u8; 16]> {
    let s = match name {
        "dns" => "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "url" => "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
        "oid" => "6ba7b812-9dad-11d1-80b4-00c04fd430c8",
        "x500" => "6ba7b814-9dad-11d1-80b4-00c04fd430c8",
        _ => return None,
    };
    parse_uuid(s)
}

/// Version-5 (SHA-1) UUID bytes for `namespace` + `name` (`Bun.randomUUIDv5`).
pub fn uuid_v5(namespace: &[u8; 16], name: &[u8]) -> [u8; 16] {
    let mut h = super::hash::Hasher::new(super::hash::HashAlg::Sha1);
    h.update(namespace);
    h.update(name);
    let d = h.finalize();
    let mut out = [0u8; 16];
    out.copy_from_slice(&d[..16]);
    out[6] = (out[6] & 0x0f) | 0x50;
    out[8] = (out[8] & 0x3f) | 0x80;
    out
}

/// Version-7 UUID bytes: 48-bit big-endian millisecond timestamp + random bits
/// (`Bun.randomUUIDv7`).
pub fn uuid_v7(timestamp_ms: u64) -> [u8; 16] {
    let mut out = [0u8; 16];
    fill_random(&mut out[6..]);
    out[..6].copy_from_slice(&timestamp_ms.to_be_bytes()[2..]);
    out[6] = (out[6] & 0x0f) | 0x70;
    out[8] = (out[8] & 0x3f) | 0x80;
    out
}
