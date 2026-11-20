//! Argon2d / Argon2i / Argon2id (RFC 9106), version 0x13 (and 0x10).

use super::blake2b::Blake2b;
use super::CryptoError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Argon2Variant {
    Argon2d = 0,
    Argon2i = 1,
    Argon2id = 2,
}

impl Argon2Variant {
    /// Exact (case-sensitive) names accepted by `crypto.argon2[Sync]`: `argon2d`, `argon2i`,
    /// `argon2id`. (Anything else → TypeError
    /// `crypto.argon2Sync: algorithm must be 'argon2d', 'argon2i', or 'argon2id'`.)
    pub fn from_name(name: &str) -> Option<Argon2Variant> {
        match name {
            "argon2d" => Some(Argon2Variant::Argon2d),
            "argon2i" => Some(Argon2Variant::Argon2i),
            "argon2id" => Some(Argon2Variant::Argon2id),
            _ => None,
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            Argon2Variant::Argon2d => "argon2d",
            Argon2Variant::Argon2i => "argon2i",
            Argon2Variant::Argon2id => "argon2id",
        }
    }
}

/// Argon2 inputs, named like the `crypto.argon2` `parameters` object.
#[derive(Clone, Copy, Debug)]
pub struct Argon2Params<'a> {
    /// Password `P`.
    pub message: &'a [u8],
    /// Salt `S` (the original requires >= 8 bytes).
    pub nonce: &'a [u8],
    /// Optional secret `K` (empty = none).
    pub secret: &'a [u8],
    /// Optional associated data `X` (empty = none).
    pub associated_data: &'a [u8],
    /// Lanes `p`, 1..=2^24-1.
    pub parallelism: u32,
    /// Output length `T` in bytes, >= 4.
    pub tag_length: u32,
    /// Memory `m` in KiB (`crypto.argon2` requires >= 8*p; smaller values are rounded up to
    /// 8*p blocks as Bun.password does).
    pub memory: u32,
    /// Passes `t`, >= 1.
    pub passes: u32,
    /// 0x13 (the only value the original uses — its `version` option is ignored) or 0x10.
    pub version: u32,
}

const BLOCK_WORDS: usize = 128;
type Block = [u64; BLOCK_WORDS];

/// Variable-length hash H' (RFC 9106 §3.3).
pub fn blake2b_long(out: &mut [u8], input: &[&[u8]]) {
    let out_len = out.len();
    let len_prefix = (out_len as u32).to_le_bytes();
    if out_len <= 64 {
        let mut h = Blake2b::new(out_len);
        h.update(&len_prefix);
        for i in input {
            h.update(i);
        }
        h.finalize_into(out);
        return;
    }
    let mut h = Blake2b::new(64);
    h.update(&len_prefix);
    for i in input {
        h.update(i);
    }
    let mut v = [0u8; 64];
    h.finalize_into(&mut v);
    out[..32].copy_from_slice(&v[..32]);
    let mut pos = 32;
    while out_len - pos > 64 {
        let mut h = Blake2b::new(64);
        h.update(&v);
        h.finalize_into(&mut v);
        out[pos..pos + 32].copy_from_slice(&v[..32]);
        pos += 32;
    }
    let rest = out_len - pos;
    let mut h = Blake2b::new(rest);
    h.update(&v);
    h.finalize_into(&mut out[pos..]);
}

#[inline(always)]
fn fbla(x: u64, y: u64) -> u64 {
    let m = (x as u32 as u64).wrapping_mul(y as u32 as u64);
    x.wrapping_add(y).wrapping_add(m.wrapping_mul(2))
}

#[inline(always)]
fn gb(v: &mut [u64; 16], a: usize, b: usize, c: usize, d: usize) {
    v[a] = fbla(v[a], v[b]);
    v[d] = (v[d] ^ v[a]).rotate_right(32);
    v[c] = fbla(v[c], v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(24);
    v[a] = fbla(v[a], v[b]);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = fbla(v[c], v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(63);
}

#[inline(always)]
fn permute(v: &mut [u64; 16]) {
    gb(v, 0, 4, 8, 12);
    gb(v, 1, 5, 9, 13);
    gb(v, 2, 6, 10, 14);
    gb(v, 3, 7, 11, 15);
    gb(v, 0, 5, 10, 15);
    gb(v, 1, 6, 11, 12);
    gb(v, 2, 7, 8, 13);
    gb(v, 3, 4, 9, 14);
}

/// Compression G: `next = P(prev ^ refb) ^ prev ^ refb` (`^ old next` when `with_xor`).
fn fill_block(prev: &Block, refb: &Block, next: &mut Block, with_xor: bool) {
    let mut r: Block = [0; BLOCK_WORDS];
    for i in 0..BLOCK_WORDS {
        r[i] = prev[i] ^ refb[i];
    }
    let mut tmp = r;
    if with_xor {
        for i in 0..BLOCK_WORDS {
            tmp[i] ^= next[i];
        }
    }
    // Rows: 8 rows of 16 consecutive words.
    for row in 0..8 {
        let mut v = [0u64; 16];
        v.copy_from_slice(&r[row * 16..row * 16 + 16]);
        permute(&mut v);
        r[row * 16..row * 16 + 16].copy_from_slice(&v);
    }
    // Columns: column c is the word pairs (2c, 2c+1) of every row.
    for col in 0..8 {
        let mut v = [0u64; 16];
        for i in 0..8 {
            v[2 * i] = r[2 * col + 16 * i];
            v[2 * i + 1] = r[2 * col + 16 * i + 1];
        }
        permute(&mut v);
        for i in 0..8 {
            r[2 * col + 16 * i] = v[2 * i];
            r[2 * col + 16 * i + 1] = v[2 * i + 1];
        }
    }
    for i in 0..BLOCK_WORDS {
        next[i] = tmp[i] ^ r[i];
    }
}

fn next_addresses(address: &mut Block, input: &mut Block) {
    let zero: Block = [0; BLOCK_WORDS];
    input[6] = input[6].wrapping_add(1);
    let mut tmp: Block = [0; BLOCK_WORDS];
    fill_block(&zero, input, &mut tmp, false);
    fill_block(&zero, &tmp, address, false);
}

/// Argon2 tag computation. Errors (plain `RangeError`, generic messages) only when the
/// numeric parameters are outside RFC 9106 limits or memory cannot be allocated — the JS
/// binding is expected to produce the original's exact validation errors itself (see the
/// module docs for the order and wording).
pub fn argon2(variant: Argon2Variant, params: &Argon2Params<'_>) -> Result<Vec<u8>, CryptoError> {
    let p = params.parallelism;
    if p == 0 || p > 0x00ff_ffff {
        return Err(CryptoError::range_error("argon2: parallelism must be between 1 and 16777215"));
    }
    if params.tag_length < 4 {
        return Err(CryptoError::range_error("argon2: tagLength must be at least 4"));
    }
    if params.memory == 0 {
        return Err(CryptoError::range_error("argon2: memory must be at least 1"));
    }
    if params.passes == 0 {
        return Err(CryptoError::range_error("argon2: passes must be at least 1"));
    }
    let version = if params.version == 0x10 { 0x10 } else { 0x13 };
    let lanes = p as usize;
    // Like Zig's std.crypto.pwhash.argon2 (which Bun.password follows): memory below 8*p
    // is accepted and rounded up to 8*p blocks, while H0 still hashes the requested `m`.
    // `crypto.argon2` itself rejects memory < 8*p before getting here.
    let m_blocks = ((params.memory as usize / (4 * lanes)) * 4 * lanes).max(8 * lanes);
    let lane_len = m_blocks / lanes;
    let seg_len = lane_len / 4;

    // H0
    let mut h0 = [0u8; 72];
    {
        let mut h = Blake2b::new(64);
        h.update(&p.to_le_bytes());
        h.update(&params.tag_length.to_le_bytes());
        h.update(&params.memory.to_le_bytes());
        h.update(&params.passes.to_le_bytes());
        h.update(&(version as u32).to_le_bytes());
        h.update(&(variant as u32).to_le_bytes());
        for part in [params.message, params.nonce, params.secret, params.associated_data] {
            h.update(&(part.len() as u32).to_le_bytes());
            h.update(part);
        }
        h.finalize_into(&mut h0[..64]);
    }

    let mut memory: Vec<Block> = Vec::new();
    if memory.try_reserve_exact(m_blocks).is_err() {
        return Err(CryptoError::range_error("argon2: memory allocation failed"));
    }
    memory.resize(m_blocks, [0u64; BLOCK_WORDS]);

    let mut bytes = [0u8; 1024];
    for lane in 0..lanes {
        for j in 0..2u32 {
            h0[64..68].copy_from_slice(&j.to_le_bytes());
            h0[68..72].copy_from_slice(&(lane as u32).to_le_bytes());
            blake2b_long(&mut bytes, &[&h0]);
            let blk = &mut memory[lane * lane_len + j as usize];
            for (i, w) in blk.iter_mut().enumerate() {
                let mut b = [0u8; 8];
                b.copy_from_slice(&bytes[i * 8..i * 8 + 8]);
                *w = u64::from_le_bytes(b);
            }
        }
    }

    for pass in 0..params.passes as usize {
        for slice in 0..4usize {
            for lane in 0..lanes {
                let data_independent = variant == Argon2Variant::Argon2i
                    || (variant == Argon2Variant::Argon2id && pass == 0 && slice < 2);
                let mut address: Block = [0; BLOCK_WORDS];
                let mut input: Block = [0; BLOCK_WORDS];
                if data_independent {
                    input[0] = pass as u64;
                    input[1] = lane as u64;
                    input[2] = slice as u64;
                    input[3] = m_blocks as u64;
                    input[4] = params.passes as u64;
                    input[5] = variant as u64;
                }
                let mut start = 0usize;
                if pass == 0 && slice == 0 {
                    start = 2;
                    if data_independent {
                        next_addresses(&mut address, &mut input);
                    }
                }
                let mut curr = lane * lane_len + slice * seg_len + start;
                let mut prev = if curr % lane_len == 0 { curr + lane_len - 1 } else { curr - 1 };
                for index in start..seg_len {
                    if curr % lane_len == 1 {
                        prev = curr - 1;
                    }
                    let pseudo = if data_independent {
                        if index % BLOCK_WORDS == 0 {
                            next_addresses(&mut address, &mut input);
                        }
                        address[index % BLOCK_WORDS]
                    } else {
                        memory[prev][0]
                    };
                    let mut ref_lane = ((pseudo >> 32) % lanes as u64) as usize;
                    if pass == 0 && slice == 0 {
                        ref_lane = lane;
                    }
                    let same_lane = ref_lane == lane;
                    // index_alpha
                    let area: u64 = if pass == 0 {
                        if slice == 0 {
                            index as u64 - 1
                        } else if same_lane {
                            (slice * seg_len + index) as u64 - 1
                        } else {
                            (slice * seg_len) as u64 - if index == 0 { 1 } else { 0 }
                        }
                    } else if same_lane {
                        (lane_len - seg_len + index) as u64 - 1
                    } else {
                        (lane_len - seg_len) as u64 - if index == 0 { 1 } else { 0 }
                    };
                    let j1 = pseudo & 0xffff_ffff;
                    let x = (j1 * j1) >> 32;
                    let rel = area - 1 - ((area * x) >> 32);
                    let start_pos = if pass != 0 && slice != 3 { (slice + 1) * seg_len } else { 0 };
                    let ref_index = ((start_pos as u64 + rel) % lane_len as u64) as usize;
                    let ref_pos = ref_lane * lane_len + ref_index;

                    let prev_block = memory[prev];
                    let ref_block = memory[ref_pos];
                    let with_xor = version == 0x13 && pass != 0;
                    fill_block(&prev_block, &ref_block, &mut memory[curr], with_xor);
                    curr += 1;
                    prev += 1;
                }
            }
        }
    }

    let mut c = memory[lane_len - 1];
    for lane in 1..lanes {
        let b = &memory[lane * lane_len + lane_len - 1];
        for i in 0..BLOCK_WORDS {
            c[i] ^= b[i];
        }
    }
    for (i, w) in c.iter().enumerate() {
        bytes[i * 8..i * 8 + 8].copy_from_slice(&w.to_le_bytes());
    }
    let mut out = Vec::new();
    if out.try_reserve_exact(params.tag_length as usize).is_err() {
        return Err(CryptoError::range_error("argon2: tagLength too large"));
    }
    out.resize(params.tag_length as usize, 0);
    blake2b_long(&mut out, &[&bytes]);
    Ok(out)
}
