//! Checksums used by the codecs: CRC-32 (gzip / `zlib.crc32`), Adler-32 (zlib
//! container) and XXH64 (zstd content checksum).

const fn make_crc_tables() -> [[u32; 256]; 8] {
    let mut t = [[0u32; 256]; 8];
    let mut n = 0;
    while n < 256 {
        let mut c = n as u32;
        let mut k = 0;
        while k < 8 {
            c = if c & 1 != 0 { 0xEDB8_8320 ^ (c >> 1) } else { c >> 1 };
            k += 1;
        }
        t[0][n] = c;
        n += 1;
    }
    let mut n = 0;
    while n < 256 {
        let mut k = 1;
        while k < 8 {
            let prev = t[k - 1][n];
            t[k][n] = (prev >> 8) ^ t[0][(prev & 0xff) as usize];
            k += 1;
        }
        n += 1;
    }
    t
}

static CRC_TABLES: [[u32; 256]; 8] = make_crc_tables();

/// Standard CRC-32 (IEEE 802.3, reflected, as in zlib's `crc32()`), continuing
/// from `init` (the CRC of the preceding data; 0 to start).
pub fn crc32(data: &[u8], init: u32) -> u32 {
    let t = &CRC_TABLES;
    let mut c = !init;
    let mut chunks = data.chunks_exact(8);
    for ch in &mut chunks {
        let lo = c ^ u32::from_le_bytes([ch[0], ch[1], ch[2], ch[3]]);
        let hi = u32::from_le_bytes([ch[4], ch[5], ch[6], ch[7]]);
        c = t[7][(lo & 0xff) as usize]
            ^ t[6][((lo >> 8) & 0xff) as usize]
            ^ t[5][((lo >> 16) & 0xff) as usize]
            ^ t[4][(lo >> 24) as usize]
            ^ t[3][(hi & 0xff) as usize]
            ^ t[2][((hi >> 8) & 0xff) as usize]
            ^ t[1][((hi >> 16) & 0xff) as usize]
            ^ t[0][(hi >> 24) as usize];
    }
    for &b in chunks.remainder() {
        c = t[0][((c ^ b as u32) & 0xff) as usize] ^ (c >> 8);
    }
    !c
}

/// Adler-32 as in zlib's `adler32()`, continuing from `init` (1 to start).
pub fn adler32(data: &[u8], init: u32) -> u32 {
    const MOD: u32 = 65521;
    // Largest n such that 255*n*(n+1)/2 + (n+1)*(MOD-1) <= 2^32-1.
    const NMAX: usize = 5552;
    let mut a = init & 0xffff;
    let mut b = init >> 16;
    // An `init` from outside could hold out-of-range halves; reduce them first.
    a %= MOD;
    b %= MOD;
    for chunk in data.chunks(NMAX) {
        for &x in chunk {
            a += x as u32;
            b += a;
        }
        a %= MOD;
        b %= MOD;
    }
    (b << 16) | a
}

const P1: u64 = 0x9E37_79B1_85EB_CA87;
const P2: u64 = 0xC2B2_AE3D_27D4_EB4F;
const P3: u64 = 0x1656_67B1_9E37_79F9;
const P4: u64 = 0x85EB_CA77_C2B2_AE63;
const P5: u64 = 0x27D4_EB2F_1656_67C5;

#[inline]
fn xxh_round(acc: u64, input: u64) -> u64 {
    acc.wrapping_add(input.wrapping_mul(P2)).rotate_left(31).wrapping_mul(P1)
}

#[inline]
fn xxh_merge(acc: u64, val: u64) -> u64 {
    (acc ^ xxh_round(0, val)).wrapping_mul(P1).wrapping_add(P4)
}

#[inline]
fn rd64(b: &[u8]) -> u64 {
    u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]])
}

#[inline]
fn rd32(b: &[u8]) -> u32 {
    u32::from_le_bytes([b[0], b[1], b[2], b[3]])
}

/// One-shot XXH64 (used by zstd frames with the content-checksum flag; zstd
/// stores the low 32 bits, little-endian).
pub fn xxh64(data: &[u8], seed: u64) -> u64 {
    let len = data.len();
    let mut p = 0usize;
    let mut h: u64;
    if len >= 32 {
        let mut v1 = seed.wrapping_add(P1).wrapping_add(P2);
        let mut v2 = seed.wrapping_add(P2);
        let mut v3 = seed;
        let mut v4 = seed.wrapping_sub(P1);
        while p + 32 <= len {
            v1 = xxh_round(v1, rd64(&data[p..]));
            v2 = xxh_round(v2, rd64(&data[p + 8..]));
            v3 = xxh_round(v3, rd64(&data[p + 16..]));
            v4 = xxh_round(v4, rd64(&data[p + 24..]));
            p += 32;
        }
        h = v1
            .rotate_left(1)
            .wrapping_add(v2.rotate_left(7))
            .wrapping_add(v3.rotate_left(12))
            .wrapping_add(v4.rotate_left(18));
        h = xxh_merge(h, v1);
        h = xxh_merge(h, v2);
        h = xxh_merge(h, v3);
        h = xxh_merge(h, v4);
    } else {
        h = seed.wrapping_add(P5);
    }
    h = h.wrapping_add(len as u64);
    while p + 8 <= len {
        let k1 = xxh_round(0, rd64(&data[p..]));
        h = (h ^ k1).rotate_left(27).wrapping_mul(P1).wrapping_add(P4);
        p += 8;
    }
    if p + 4 <= len {
        h = (h ^ (rd32(&data[p..]) as u64).wrapping_mul(P1))
            .rotate_left(23)
            .wrapping_mul(P2)
            .wrapping_add(P3);
        p += 4;
    }
    while p < len {
        h = (h ^ (data[p] as u64).wrapping_mul(P5)).rotate_left(11).wrapping_mul(P1);
        p += 1;
    }
    h ^= h >> 33;
    h = h.wrapping_mul(P2);
    h ^= h >> 29;
    h = h.wrapping_mul(P3);
    h ^= h >> 32;
    h
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_values() {
        assert_eq!(crc32(b"", 0), 0);
        assert_eq!(crc32(b"hello world", 0), 0x0d4a_1185);
        assert_eq!(crc32(b"world", crc32(b"hello ", 0)), 0x0d4a_1185);
        assert_eq!(adler32(b"", 1), 1);
        assert_eq!(adler32(b"hello world", 1), 0x1a0b_045d);
        assert_eq!(xxh64(b"", 0), 0xEF46_DB37_51D8_E999);
        // zstd frame of "hello world" carries 0xb21e6968 as its checksum.
        assert_eq!(xxh64(b"hello world", 0) as u32, 0xb21e_6968);
    }
}
