//! Zstandard encoder replicating the original runtime byte-for-byte.
//!
//! The original never compresses: one frame, `Single_Segment` set, content
//! checksum always present, no dictionary id, all parameters ignored.
//!
//! * Frame header descriptor: `(fcs_flag << 6) | 0x20 | 0x04` where the
//!   Frame_Content_Size field is 1 byte (len < 256), 2 bytes storing
//!   `len - 256` (len < 65792), 4 bytes (len < 2^32), else 8 bytes.
//! * Blocks of at most 128 KiB: an RLE block when the block is >= 4 bytes
//!   of one repeated value, otherwise a raw block. Empty input = one empty
//!   raw last block.
//! * Content checksum = low 32 bits of XXH64(seed 0), little-endian.

use super::checksum::xxh64;

const MAX_BLOCK: usize = 128 * 1024;

/// `zlib.zstdCompressSync` (options ignored).
pub fn zstd_bytes(data: &[u8]) -> Vec<u8> {
    let n = data.len();
    let mut out = Vec::with_capacity(n + 32 + 3 * (n / MAX_BLOCK));
    out.extend_from_slice(&0xFD2F_B528u32.to_le_bytes());
    let (flag, fcs): (u8, Vec<u8>) = if n < 256 {
        (0, vec![n as u8])
    } else if n < 65536 + 256 {
        (1, ((n - 256) as u16).to_le_bytes().to_vec())
    } else if (n as u64) < (1u64 << 32) {
        (2, (n as u32).to_le_bytes().to_vec())
    } else {
        (3, (n as u64).to_le_bytes().to_vec())
    };
    out.push((flag << 6) | 0x20 | 0x04);
    out.extend_from_slice(&fcs);
    let push_block = |out: &mut Vec<u8>, last: bool, btype: u32, size: usize| {
        let h = (last as u32) | (btype << 1) | ((size as u32) << 3);
        out.extend_from_slice(&h.to_le_bytes()[..3]);
    };
    if n == 0 {
        push_block(&mut out, true, 0, 0);
    } else {
        let count = n.div_ceil(MAX_BLOCK);
        for (i, block) in data.chunks(MAX_BLOCK).enumerate() {
            let last = i + 1 == count;
            if block.len() >= 4 && block.iter().all(|&b| b == block[0]) {
                push_block(&mut out, last, 1, block.len());
                out.push(block[0]);
            } else {
                push_block(&mut out, last, 0, block.len());
                out.extend_from_slice(block);
            }
        }
    }
    out.extend_from_slice(&(xxh64(data, 0) as u32).to_le_bytes());
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
        assert_eq!(hex(&zstd_bytes(b"")), "28b52ffd240001000099e9d851");
        assert_eq!(hex(&zstd_bytes(b"a")), "28b52ffd2401090000615b6e8ca9");
        assert_eq!(hex(&zstd_bytes(b"aaaa")), "28b52ffd24042300006132bf84bf");
        assert_eq!(
            hex(&zstd_bytes(b"hello world")),
            "28b52ffd240b59000068656c6c6f20776f726c6468691eb2"
        );
    }
}
