//! Brotli encoder replicating the original runtime byte-for-byte.
//!
//! The original ignores every parameter (quality, lgwin, mode, size hint,
//! large window, npostfix/ndirect, ...). Output layout:
//!
//! * WBITS = 22 (stream header nibble `1011`); empty input -> `3b`.
//! * The whole input is ONE meta-block (inputs above 2^24 bytes cannot occur
//!   in the original because of its 1 MiB typed-array limit; this module
//!   splits them into 2^24-byte meta-blocks).
//! * Stored ("uncompressed") meta-block when len <= 16, or when the literal
//!   Huffman bits + 1400 >= 8 * len (only for >= 5 distinct byte values);
//!   followed by an empty last meta-block (`03`).
//! * Otherwise a compressed ISLAST meta-block containing a single
//!   insert-only command: NBLTYPES 1/1/1, NPOSTFIX 0, NDIRECT 0, context
//!   mode LSB6, NTREES 1/1, literal prefix code (simple code for <= 4
//!   distinct bytes, otherwise a complex code), insert&copy code = simple
//!   1-symbol code (copy-length code 0, explicit-distance group), distance
//!   code = simple 1-symbol code `0`, then the insert-length extra bits and
//!   the Huffman-coded literals.

use super::deflate::BitWriter;

/// Huffman code lengths as the original builds them: a plain Huffman merge
/// (on equal counts: internal nodes before leaves, the most recently created
/// internal node first, leaves with the larger symbol value first); if the
/// deepest code exceeds `limit`, every count is halved (rounding up, minimum
/// 1) and the tree is rebuilt.
pub(crate) fn huffman_lengths(hist: &[u32], limit: u32) -> Vec<u8> {
    let mut out = vec![0u8; hist.len()];
    let used: Vec<usize> = (0..hist.len()).filter(|&i| hist[i] > 0).collect();
    if used.is_empty() {
        return out;
    }
    if used.len() == 1 {
        out[used[0]] = 1;
        return out;
    }
    let mut counts: Vec<u64> = used.iter().map(|&s| hist[s] as u64).collect();
    loop {
        let mut parent: Vec<usize> = vec![usize::MAX; used.len()];
        // (count, class, tiebreak, node id); class 0 = internal, 1 = leaf.
        let mut live: Vec<(u64, u32, i64, usize)> = used
            .iter()
            .enumerate()
            .map(|(k, &s)| (counts[k], 1, -(s as i64), k))
            .collect();
        let mut created: i64 = 0;
        while live.len() > 1 {
            let a = pop_min(&mut live);
            let b = pop_min(&mut live);
            let id = parent.len();
            parent.push(usize::MAX);
            parent[a.3] = id;
            parent[b.3] = id;
            created += 1;
            live.push((a.0 + b.0, 0, -created, id));
        }
        // Parents always have larger ids than their children.
        let mut depth = vec![0u32; parent.len()];
        for id in (0..parent.len()).rev() {
            if parent[id] != usize::MAX {
                depth[id] = depth[parent[id]] + 1;
            }
        }
        let maxd = depth[..used.len()].iter().copied().max().unwrap_or(0);
        if maxd <= limit {
            for (k, &s) in used.iter().enumerate() {
                out[s] = depth[k] as u8;
            }
            return out;
        }
        for c in counts.iter_mut() {
            *c = c.div_ceil(2).max(1);
        }
    }
}

fn pop_min(live: &mut Vec<(u64, u32, i64, usize)>) -> (u64, u32, i64, usize) {
    let mut bi = 0;
    for i in 1..live.len() {
        let (a, b) = (&live[i], &live[bi]);
        if (a.0, a.1, a.2) < (b.0, b.1, b.2) {
            bi = i;
        }
    }
    live.swap_remove(bi)
}

/// Canonical prefix codes (MSB-first values) for the given lengths.
pub(crate) fn canonical_codes(lens: &[u8]) -> Vec<u32> {
    let mut bl_count = [0u32; 33];
    for &l in lens {
        if l > 0 {
            bl_count[l as usize] += 1;
        }
    }
    let mut next = [0u32; 33];
    let mut code = 0u32;
    for b in 1..33 {
        code = (code + bl_count[b - 1]) << 1;
        next[b] = code;
    }
    let mut codes = vec![0u32; lens.len()];
    for (i, &l) in lens.iter().enumerate() {
        if l > 0 {
            codes[i] = next[l as usize];
            next[l as usize] += 1;
        }
    }
    codes
}

const CL_ORDER: [usize; 18] = [1, 2, 3, 4, 0, 5, 17, 6, 16, 7, 8, 9, 10, 11, 12, 13, 14, 15];
/// Static code for code-length-code lengths 0..=5: (bits as written LSB-first, count).
const CLCL: [(u32, u32); 6] = [(0, 2), (7, 4), (3, 3), (2, 2), (1, 2), (15, 4)];
const INS_BASE: [u32; 24] = [
    0, 1, 2, 3, 4, 5, 6, 8, 10, 14, 18, 26, 34, 50, 66, 98, 130, 194, 322, 578, 1090, 2114, 6210,
    22594,
];
const INS_EXTRA: [u32; 24] = [
    0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 12, 14, 24,
];
const MAX_METABLOCK: usize = 1 << 24;

fn write_meta_header(w: &mut BitWriter, mlen: usize, islast: bool) {
    w.put(islast as u32, 1);
    if islast {
        w.put(0, 1); // ISLASTEMPTY
    }
    let m = (mlen - 1) as u64;
    let mut nibbles = 4u32;
    while nibbles < 6 && m >= (1u64 << (4 * nibbles)) {
        nibbles += 1;
    }
    w.put(nibbles - 4, 2);
    for i in 0..nibbles {
        w.put(((m >> (4 * i)) & 15) as u32, 4);
    }
}

fn histogram(data: &[u8]) -> Vec<u32> {
    let mut hist = vec![0u32; 256];
    for &b in data {
        hist[b as usize] += 1;
    }
    hist
}

/// The original's choice between a compressed and a stored meta-block.
fn should_compress(data: &[u8], hist: &[u32]) -> bool {
    if data.len() <= 16 {
        return false;
    }
    if hist.iter().filter(|&&c| c > 0).count() <= 4 {
        return true;
    }
    let lens = huffman_lengths(hist, 15);
    let bits: u64 = (0..256).map(|i| hist[i] as u64 * lens[i] as u64).sum();
    bits + 1400 < 8 * data.len() as u64
}

fn write_compressed(w: &mut BitWriter, data: &[u8], hist: &[u32], islast: bool) {
    write_meta_header(w, data.len(), islast);
    if !islast {
        w.put(0, 1); // ISUNCOMPRESSED = 0
    }
    w.put(0, 3); // NBLTYPESL, NBLTYPESI, NBLTYPESD = 1
    w.put(0, 2); // NPOSTFIX
    w.put(0, 4); // NDIRECT
    w.put(0, 2); // context mode LSB6
    w.put(0, 2); // NTREESL = 1, NTREESD = 1
    let used: Vec<usize> = (0..256).filter(|&i| hist[i] > 0).collect();
    let mut lens = vec![0u8; 256];
    if used.len() <= 4 {
        // Simple code: symbols by descending count (ties: smaller value first).
        let mut order = used.clone();
        order.sort_by(|&a, &b| hist[b].cmp(&hist[a]).then(a.cmp(&b)));
        w.put(1, 2); // HSKIP = 1 -> simple
        w.put(order.len() as u32 - 1, 2);
        for &s in &order {
            w.put(s as u32, 8);
        }
        let shape: &[u8] = match order.len() {
            1 => &[0],
            2 => &[1, 1],
            3 => &[1, 2, 2],
            _ => &[1, 2, 3, 3],
        };
        if order.len() == 4 {
            w.put(1, 1); // tree-select: lengths 1,2,3,3
        }
        for (k, &s) in order.iter().enumerate() {
            lens[s] = shape[k];
        }
    } else {
        lens = huffman_lengths(hist, 15);
        let last = (0..256).rev().find(|&i| lens[i] != 0).unwrap();
        let seq = &lens[..=last];
        // Code-length code: a "balanced" code (lengths k-1 / k) assigned by
        // descending frequency, ties by first occurrence in `seq`.
        let mut clh = [0u32; 18];
        let mut first = [usize::MAX; 18];
        for (i, &l) in seq.iter().enumerate() {
            clh[l as usize] += 1;
            if first[l as usize] == usize::MAX {
                first[l as usize] = i;
            }
        }
        let mut syms: Vec<usize> = (0..18).filter(|&i| clh[i] > 0).collect();
        syms.sort_by(|&a, &b| clh[b].cmp(&clh[a]).then(first[a].cmp(&first[b])));
        let m = syms.len();
        let mut cl_lens = [0u8; 18];
        if m == 1 {
            cl_lens[syms[0]] = 1;
        } else {
            let k = 32 - ((m as u32) - 1).leading_zeros();
            let nshort = (1usize << k) - m;
            for (i, &s) in syms.iter().enumerate() {
                cl_lens[s] = if i < nshort { (k - 1) as u8 } else { k as u8 };
            }
        }
        w.put(0, 2); // HSKIP = 0
        let last_ord = (0..18).rev().find(|&i| cl_lens[CL_ORDER[i]] != 0).unwrap();
        for &idx in CL_ORDER.iter().take(last_ord + 1) {
            let (v, nb) = CLCL[cl_lens[idx] as usize];
            w.put(v, nb);
        }
        if m > 1 {
            let clc = canonical_codes(&cl_lens);
            for &l in seq {
                w.put_code(clc[l as usize], cl_lens[l as usize] as u32);
            }
        }
    }
    // Insert-and-copy code: one symbol.
    let ilen = data.len() as u32;
    let ic = INS_BASE.iter().rposition(|&b| b <= ilen).unwrap();
    let cmd: u32 = match ic {
        0..=7 => 128 + ((ic as u32) << 3),
        8..=15 => 256 + (((ic - 8) as u32) << 3),
        _ => 448 + (((ic - 16) as u32) << 3),
    };
    w.put(1, 2);
    w.put(0, 2);
    w.put(cmd, 10);
    // Distance code: one symbol (0).
    w.put(1, 2);
    w.put(0, 2);
    w.put(0, 6);
    w.put(ilen - INS_BASE[ic], INS_EXTRA[ic]);
    if used.len() > 1 {
        let codes = canonical_codes(&lens);
        for &b in data {
            w.put_code(codes[b as usize], lens[b as usize] as u32);
        }
    }
}

/// `zlib.brotliCompressSync` (all options ignored).
pub fn brotli_bytes(data: &[u8]) -> Vec<u8> {
    let mut w = BitWriter::with_capacity(data.len() + 16);
    w.put(1, 1);
    w.put(5, 3); // WBITS = 22
    if data.is_empty() {
        w.put(1, 1); // ISLAST
        w.put(1, 1); // ISLASTEMPTY
        return w.finish();
    }
    let chunks: Vec<&[u8]> = data.chunks(MAX_METABLOCK).collect();
    let mut need_empty_last = false;
    for (i, chunk) in chunks.iter().enumerate() {
        let last = i + 1 == chunks.len();
        let hist = histogram(chunk);
        if should_compress(chunk, &hist) {
            write_compressed(&mut w, chunk, &hist, last);
            need_empty_last = false;
        } else {
            write_meta_header(&mut w, chunk.len(), false);
            w.put(1, 1); // ISUNCOMPRESSED
            let mut bytes = std::mem::replace(&mut w, BitWriter::new()).finish();
            bytes.extend_from_slice(chunk);
            w.out = bytes;
            need_empty_last = true;
        }
    }
    if need_empty_last {
        w.put(1, 1);
        w.put(1, 1);
    }
    w.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(b: &[u8]) -> String {
        b.iter().map(|x| format!("{:02x}", x)).collect()
    }

    #[test]
    fn known_outputs() {
        assert_eq!(hex(&brotli_bytes(b"")), "3b");
        assert_eq!(hex(&brotli_bytes(b"a")), "0b00806103");
        assert_eq!(hex(&brotli_bytes(b"hello")), "0b028068656c6c6f03");
        assert_eq!(
            hex(&brotli_bytes(b"abcabcabcabcabcabcabcabcabcabc")),
            "1b1d000020c3c4c602a300a8b5d65a6bad35"
        );
    }
}
