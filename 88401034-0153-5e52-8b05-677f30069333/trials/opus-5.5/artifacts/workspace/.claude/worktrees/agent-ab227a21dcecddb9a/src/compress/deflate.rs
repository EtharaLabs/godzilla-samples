//! DEFLATE encoder replicating the original runtime byte-for-byte.
//!
//! The original ignores every option (level, windowBits, memLevel, strategy,
//! dictionary) and always produces ONE final block with the FIXED Huffman
//! code (BFINAL=1, BTYPE=01), using greedy LZ77 parsing:
//!
//! * hash = ((b0 << 16) | (b1 << 8) | b2).wrapping_mul(0x9E37_79B1) >> 17
//!   (15-bit buckets), one chain per bucket linking every previous position
//!   (all positions are inserted, including those inside matches);
//! * at each position the 128 most recent chain entries are examined (hash
//!   collisions count), keeping the first longest match (min 3, max 258);
//! * the window is UNLIMITED: matches farther than 32768 bytes are emitted
//!   with distance code 29 and the extra-bits value `dist - 24577` written
//!   without masking to 13 bits, so the excess high bits are OR-ed into the
//!   following bits of the stream. Such streams are corrupt (they decode to
//!   different data or fail), exactly like the original's output.
//!
//! Containers: zlib = `78 9c` + data + Adler-32 (BE); gzip = `1f 8b 08 00`
//! + mtime 0 + XFL 0 + OS 0xff + data + CRC-32 (LE) + ISIZE (LE).

use super::checksum::{adler32, crc32};

/// LSB-first bit writer that, like the original, does not mask `value` to
/// `n` bits: excess high bits leak into the bits written afterwards.
pub(crate) struct BitWriter {
    pub(crate) out: Vec<u8>,
    acc: u64,
    n: u32,
}

impl BitWriter {
    pub(crate) fn new() -> Self {
        BitWriter { out: Vec::new(), acc: 0, n: 0 }
    }

    pub(crate) fn with_capacity(cap: usize) -> Self {
        BitWriter { out: Vec::with_capacity(cap), acc: 0, n: 0 }
    }

    #[inline]
    pub(crate) fn put(&mut self, value: u32, n: u32) {
        self.acc |= (value as u64) << self.n;
        self.n += n;
        while self.n >= 8 {
            self.out.push(self.acc as u8);
            self.acc >>= 8;
            self.n -= 8;
        }
    }

    /// Write a Huffman code given MSB-first (`code` has `len` significant bits).
    #[inline]
    pub(crate) fn put_code(&mut self, code: u32, len: u32) {
        if len == 0 {
            return;
        }
        let rev = code.reverse_bits() >> (32 - len);
        self.put(rev, len);
    }

    /// Flush the partial byte (zero padding) and return the bytes.
    pub(crate) fn finish(mut self) -> Vec<u8> {
        if self.n > 0 {
            self.out.push(self.acc as u8);
        }
        self.out
    }
}

const LEN_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115,
    131, 163, 195, 227, 258,
];
const LEN_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DIST_BASE: [u32; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
    2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
const DIST_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13,
    13,
];

const HASH_BITS: u32 = 15;
const MAX_CHAIN: usize = 128;
const MIN_MATCH: usize = 3;
const MAX_MATCH: usize = 258;
const NIL: u32 = u32::MAX;

#[inline]
fn put_fixed_symbol(w: &mut BitWriter, sym: u32) {
    match sym {
        0..=143 => w.put_code(0x30 + sym, 8),
        144..=255 => w.put_code(0x190 + (sym - 144), 9),
        256..=279 => w.put_code(sym - 256, 7),
        _ => w.put_code(0xC0 + (sym - 280), 8),
    }
}

#[inline]
fn hash3(d: &[u8], p: usize) -> usize {
    let v = ((d[p] as u32) << 16) | ((d[p + 1] as u32) << 8) | d[p + 2] as u32;
    (v.wrapping_mul(0x9E37_79B1) >> (32 - HASH_BITS)) as usize
}

/// Raw DEFLATE exactly as the original's `deflateRawSync` produces it.
pub fn deflate_raw_bytes(data: &[u8]) -> Vec<u8> {
    let n = data.len();
    let mut w = BitWriter::with_capacity(n / 2 + 16);
    w.put(1, 1); // BFINAL
    w.put(1, 2); // BTYPE = fixed Huffman
    let mut head = vec![NIL; 1 << HASH_BITS];
    let mut prev = vec![NIL; n];
    let insert = |p: usize, head: &mut Vec<u32>, prev: &mut Vec<u32>| {
        if p + MIN_MATCH <= n {
            let h = hash3(data, p);
            prev[p] = head[h];
            head[h] = p as u32;
        }
    };
    let mut p = 0usize;
    while p < n {
        let mut best_len = 0usize;
        let mut best_dist = 0usize;
        if p + MIN_MATCH <= n {
            let maxlen = (n - p).min(MAX_MATCH);
            let mut cand = head[hash3(data, p)];
            let mut steps = 0;
            while cand != NIL && steps < MAX_CHAIN {
                let c = cand as usize;
                let mut l = 0;
                while l < maxlen && data[c + l] == data[p + l] {
                    l += 1;
                }
                if l > best_len {
                    best_len = l;
                    best_dist = p - c;
                    if l == maxlen {
                        break;
                    }
                }
                cand = prev[c];
                steps += 1;
            }
        }
        if best_len >= MIN_MATCH {
            let li = LEN_BASE.iter().rposition(|&b| b as usize <= best_len).unwrap();
            put_fixed_symbol(&mut w, 257 + li as u32);
            w.put((best_len - LEN_BASE[li] as usize) as u32, LEN_EXTRA[li] as u32);
            let d = best_dist as u32;
            let di = DIST_BASE.iter().rposition(|&b| b <= d).unwrap();
            w.put_code(di as u32, 5);
            // Deliberately unmasked (see module docs).
            w.put(d - DIST_BASE[di], DIST_EXTRA[di] as u32);
            for q in p..p + best_len {
                insert(q, &mut head, &mut prev);
            }
            p += best_len;
        } else {
            put_fixed_symbol(&mut w, data[p] as u32);
            insert(p, &mut head, &mut prev);
            p += 1;
        }
    }
    put_fixed_symbol(&mut w, 256);
    w.finish()
}

/// zlib container around [`deflate_raw_bytes`] (header is always `78 9c`).
pub fn zlib_bytes(data: &[u8]) -> Vec<u8> {
    let raw = deflate_raw_bytes(data);
    let mut out = Vec::with_capacity(raw.len() + 6);
    out.extend_from_slice(&[0x78, 0x9c]);
    out.extend_from_slice(&raw);
    out.extend_from_slice(&adler32(data, 1).to_be_bytes());
    out
}

/// gzip container around [`deflate_raw_bytes`]: no flags, mtime 0, XFL 0,
/// OS 0xff.
pub fn gzip_bytes(data: &[u8]) -> Vec<u8> {
    let raw = deflate_raw_bytes(data);
    let mut out = Vec::with_capacity(raw.len() + 18);
    out.extend_from_slice(&[0x1f, 0x8b, 0x08, 0x00, 0, 0, 0, 0, 0x00, 0xff]);
    out.extend_from_slice(&raw);
    out.extend_from_slice(&crc32(data, 0).to_le_bytes());
    out.extend_from_slice(&(data.len() as u32).to_le_bytes());
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{:02x}", x)).collect()
    }

    #[test]
    fn known_outputs() {
        assert_eq!(hex(&deflate_raw_bytes(b"")), "0300");
        assert_eq!(hex(&zlib_bytes(b"")), "789c030000000001");
        assert_eq!(hex(&gzip_bytes(b"")), "1f8b08000000000000ff03000000000000000000");
        assert_eq!(hex(&zlib_bytes(b"a")), "789c4b040000620062");
        assert_eq!(hex(&deflate_raw_bytes(b"hello hello hello hello hello")), "cb48cdc9c957c0410200");
        assert_eq!(hex(&deflate_raw_bytes(b"abcabcabcabcabcabcabcabcabcabc")), "4b4c4ac68300");
        assert_eq!(
            hex(&gzip_bytes(b"hello world")),
            "1f8b08000000000000ffcb48cdc9c95728cf2fca49010085114a0d0b000000"
        );
    }
}
