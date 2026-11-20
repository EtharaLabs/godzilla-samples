//! Zstandard decoder (RFC 8878) replicating the original runtime's custom
//! decoder, including its exact error messages and check order.
//!
//! Notable behaviours: frames (and skippable frames) are decoded until the
//! input ends and any trailing bytes are an error; the window descriptor is
//! ignored (no window limit; matches may reach into earlier frames of the
//! same input); non-zero dictionary ids are rejected; Frame_Content_Size is
//! verified after the last block; the content checksum is verified. Checks
//! run in parse order and the first failure wins; nothing is returned on
//! error.
//!
//! The 55 messages (all prefixed `zstd: `), by phase:
//! * input/frames: `empty input`, `truncated frame` (1-3 bytes left at a
//!   frame boundary), `truncated skippable frame`, `bad magic number`,
//!   `truncated frame header`, `reserved frame header bit set`,
//!   `dictionary frames are not supported`, `frame content size mismatch`,
//!   `truncated content checksum`, `content checksum mismatch`;
//! * blocks: `truncated block header`, `block size exceeds maximum`
//!   (> 128 KiB, any type), `reserved block type`, `truncated raw block`,
//!   `truncated RLE block`, `truncated compressed block`;
//! * literals: `missing literals section header`, `truncated literals
//!   section`, `literals section too large`, `treeless literals without a
//!   previous Huffman table`, `truncated literals jump table`, `literals
//!   jump table exceeds section`, `corrupted 4-stream literals sizes`,
//!   `empty bitstream`, `bitstream missing sentinel bit`, `Huffman stream
//!   overrun`, `Huffman stream not fully consumed`;
//! * Huffman tree: `missing Huffman tree header`, `truncated Huffman
//!   weights`, `truncated Huffman tree description`, `truncated Huffman
//!   weights bitstream`, `too many Huffman weights`, `Huffman weight too
//!   large`, `empty Huffman table`, `Huffman code length too large` (> 11),
//!   `corrupted Huffman weights`;
//! * FSE table descriptions: `FSE accuracy log too large`, `too many symbols
//!   in FSE distribution`, `corrupted FSE distribution`;
//! * sequences: `missing sequences section header`, `truncated sequences
//!   header`, `trailing bytes after empty sequences section`, `missing
//!   sequence compression modes`, `reserved sequence mode bits set`,
//!   `truncated RLE sequence table`, `RLE sequence symbol out of range`,
//!   `truncated FSE table description`, `repeat mode without a previous
//!   sequence table`, `missing sequences bitstream`, `truncated sequences
//!   bitstream`, `sequence literals overrun`, `invalid repeat offset`,
//!   `sequence offset too far back`, `block regenerated size too large`,
//!   `sequences bitstream not fully consumed`.

use super::checksum::xxh64;
use super::CodecError;

const MAXB: usize = 131072;

fn err(msg: &str) -> CodecError {
    CodecError::new(format!("zstd: {}", msg))
}

const LL_BASE: [u32; 36] = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 28, 32, 40, 48, 64,
    128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536,
];
const LL_BITS: [u8; 36] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 3, 3, 4, 6, 7, 8, 9, 10, 11,
    12, 13, 14, 15, 16,
];
const ML_BASE: [u32; 53] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27,
    28, 29, 30, 31, 32, 33, 34, 35, 37, 39, 41, 43, 47, 51, 59, 67, 83, 99, 131, 259, 515, 1027,
    2051, 4099, 8195, 16387, 32771, 65539,
];
const ML_BITS: [u8; 53] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 1, 1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
];
const LL_DEFAULT: [i16; 36] = [
    4, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 2, 1, 1, 1, 1,
    1, -1, -1, -1, -1,
];
const ML_DEFAULT: [i16; 53] = [
    1, 4, 3, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1,
];
const OF_DEFAULT: [i16; 29] = [
    1, 1, 1, 1, 1, 1, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1,
];

/// Backward bit reader. Bits below index 0 read as zero; `pos` may become
/// negative, which callers treat as overrun.
struct Rev<'a> {
    d: &'a [u8],
    pos: i64,
}

impl<'a> Rev<'a> {
    /// Caller guarantees `d` is non-empty and its last byte is non-zero.
    fn new(d: &'a [u8]) -> Self {
        let last = d[d.len() - 1];
        let hb = 7 - last.leading_zeros() as i64;
        Rev { d, pos: (d.len() as i64 - 1) * 8 + hb }
    }

    /// Bits [start, start + nb) as a little-endian number (nb <= 56).
    #[inline]
    fn get(&self, start: i64, nb: u32) -> u64 {
        let end = start + nb as i64;
        if nb == 0 || end <= 0 {
            return 0;
        }
        let s = start.max(0);
        let byte0 = (s >> 3) as usize;
        let shift = (s & 7) as u32;
        let mut v: u64 = 0;
        if byte0 + 8 <= self.d.len() {
            v = u64::from_le_bytes(self.d[byte0..byte0 + 8].try_into().unwrap());
        } else {
            for (i, &b) in self.d[byte0..].iter().enumerate() {
                v |= (b as u64) << (8 * i);
            }
        }
        let width = (end - s) as u32;
        ((v >> shift) & ((1u64 << width) - 1)) << (s - start)
    }

    #[inline]
    fn read(&mut self, nb: u32) -> u64 {
        if nb == 0 {
            return 0;
        }
        let p = self.pos - nb as i64;
        let v = self.get(p, nb);
        self.pos = p;
        v
    }

    #[inline]
    fn peek(&self, nb: u32) -> u64 {
        self.get(self.pos - nb as i64, nb)
    }
}

#[derive(Clone)]
struct Fse {
    log: u32,
    sym: Vec<u16>,
    nbits: Vec<u8>,
    base: Vec<u32>,
}

fn fse_build(norm: &[i16], log: u32) -> Fse {
    let size = 1usize << log;
    let mut sym = vec![0u16; size];
    let mut high: i64 = size as i64 - 1;
    for (s, &c) in norm.iter().enumerate() {
        if c == -1 {
            sym[high as usize] = s as u16;
            high -= 1;
        }
    }
    let step = (size >> 1) + (size >> 3) + 3;
    let mask = size - 1;
    let mut pos = 0usize;
    for (s, &c) in norm.iter().enumerate() {
        for _ in 0..c.max(0) {
            sym[pos] = s as u16;
            pos = (pos + step) & mask;
            while pos as i64 > high {
                pos = (pos + step) & mask;
            }
        }
    }
    let mut next: Vec<u32> = norm.iter().map(|&c| if c == -1 { 1 } else { c.max(0) as u32 }).collect();
    let mut nbits = vec![0u8; size];
    let mut base = vec![0u32; size];
    for u in 0..size {
        let s = sym[u] as usize;
        let ns = next[s];
        next[s] += 1;
        let nb = log - (31 - ns.leading_zeros());
        nbits[u] = nb as u8;
        base[u] = (ns << nb) - size as u32;
    }
    Fse { log, sym, nbits, base }
}

/// FSE table description reader (bits past the end read as zero).
/// Returns (normalized counts, accuracy log, bytes consumed).
fn read_ncount(data: &[u8], maxsym: usize, maxlog: u32) -> Result<(Vec<i16>, u32, usize), CodecError> {
    let get = |bitpos: usize, nb: u32| -> u32 {
        let mut v = 0u32;
        for i in 0..nb as usize {
            let b = bitpos + i;
            if (b >> 3) < data.len() && (data[b >> 3] >> (b & 7)) & 1 == 1 {
                v |= 1 << i;
            }
        }
        v
    };
    let mut bitpos = 0usize;
    let log = get(0, 4) + 5;
    bitpos += 4;
    if log > maxlog {
        return Err(err("FSE accuracy log too large"));
    }
    let mut remaining: i32 = (1 << log) + 1;
    let mut threshold: i32 = 1 << log;
    let mut nb_bits = log + 1;
    let mut norm: Vec<i16> = Vec::new();
    let mut prev0 = false;
    let n = maxsym + 1;
    while remaining > 1 {
        if norm.len() > n {
            return Err(err("too many symbols in FSE distribution"));
        }
        if prev0 {
            loop {
                let r = get(bitpos, 2) as usize;
                bitpos += 2;
                norm.extend(std::iter::repeat_n(0, r));
                if r != 3 {
                    break;
                }
                if norm.len() > n + 3 {
                    // Runs only grow; stop early (same verdict as checking later).
                    break;
                }
            }
            if norm.len() > n {
                return Err(err("too many symbols in FSE distribution"));
            }
        }
        let max = (2 * threshold - 1) - remaining;
        let low = get(bitpos, nb_bits - 1) as i32;
        let mut count;
        if low < max {
            count = low;
            bitpos += nb_bits as usize - 1;
        } else {
            count = get(bitpos, nb_bits) as i32;
            if count >= threshold {
                count -= max;
            }
            bitpos += nb_bits as usize;
        }
        count -= 1;
        remaining -= count.abs();
        norm.push(count as i16);
        prev0 = count == 0;
        while remaining < threshold {
            nb_bits -= 1;
            threshold >>= 1;
        }
    }
    if norm.len() > n {
        return Err(err("corrupted FSE distribution"));
    }
    Ok((norm, log, bitpos.div_ceil(8)))
}

struct Huf {
    log: u32,
    sym: Vec<u8>,
    len: Vec<u8>,
}

struct Seqs {
    fse: Fse,
}

struct State {
    out: Vec<u8>,
    huf: Option<Huf>,
    ll: Option<Seqs>,
    of: Option<Seqs>,
    ml: Option<Seqs>,
    rep: [u64; 3],
}

pub fn decode(d: &[u8]) -> Result<Vec<u8>, CodecError> {
    if d.is_empty() {
        return Err(err("empty input"));
    }
    let mut st = State { out: Vec::new(), huf: None, ll: None, of: None, ml: None, rep: [1, 4, 8] };
    let mut p = 0usize;
    while p < d.len() {
        if d.len() - p < 4 {
            return Err(err("truncated frame"));
        }
        let m = u32::from_le_bytes([d[p], d[p + 1], d[p + 2], d[p + 3]]);
        if m & 0xFFFF_FFF0 == 0x184D_2A50 {
            if d.len() - p < 8 {
                return Err(err("truncated skippable frame"));
            }
            let sz = u32::from_le_bytes([d[p + 4], d[p + 5], d[p + 6], d[p + 7]]) as usize;
            if sz > d.len() - p - 8 {
                return Err(err("truncated skippable frame"));
            }
            p += 8 + sz;
            continue;
        }
        if m != 0xFD2F_B528 {
            return Err(err("bad magic number"));
        }
        p = frame(d, p + 4, &mut st)?;
    }
    Ok(st.out)
}

fn le(b: &[u8]) -> u64 {
    b.iter().rev().fold(0u64, |acc, &x| (acc << 8) | x as u64)
}

fn frame(d: &[u8], mut p: usize, st: &mut State) -> Result<usize, CodecError> {
    if p >= d.len() {
        return Err(err("truncated frame header"));
    }
    let fhd = d[p];
    p += 1;
    if fhd & 8 != 0 {
        return Err(err("reserved frame header bit set"));
    }
    let single = (fhd >> 5) & 1 == 1;
    if !single {
        if p >= d.len() {
            return Err(err("truncated frame header"));
        }
        p += 1; // window descriptor (ignored)
    }
    let dsz = [0usize, 1, 2, 4][(fhd & 3) as usize];
    if p + dsz > d.len() {
        return Err(err("truncated frame header"));
    }
    if le(&d[p..p + dsz]) != 0 {
        return Err(err("dictionary frames are not supported"));
    }
    p += dsz;
    let fsz = [if single { 1 } else { 0 }, 2, 4, 8][(fhd >> 6) as usize];
    if p + fsz > d.len() {
        return Err(err("truncated frame header"));
    }
    let fcs: Option<u64> = if fsz == 0 {
        None
    } else {
        let v = le(&d[p..p + fsz]);
        Some(if fsz == 2 { v + 256 } else { v })
    };
    p += fsz;
    let start = st.out.len();
    st.huf = None;
    st.ll = None;
    st.of = None;
    st.ml = None;
    st.rep = [1, 4, 8];
    loop {
        if p + 3 > d.len() {
            return Err(err("truncated block header"));
        }
        let bh = le(&d[p..p + 3]) as usize;
        p += 3;
        let last = bh & 1 == 1;
        let bt = (bh >> 1) & 3;
        let bs = bh >> 3;
        if bs > MAXB {
            return Err(err("block size exceeds maximum"));
        }
        match bt {
            3 => return Err(err("reserved block type")),
            0 => {
                if p + bs > d.len() {
                    return Err(err("truncated raw block"));
                }
                st.out.extend_from_slice(&d[p..p + bs]);
                p += bs;
            }
            1 => {
                if p + 1 > d.len() {
                    return Err(err("truncated RLE block"));
                }
                let b = d[p];
                st.out.resize(st.out.len() + bs, b);
                p += 1;
            }
            _ => {
                if p + bs > d.len() {
                    return Err(err("truncated compressed block"));
                }
                block(&d[p..p + bs], st)?;
                p += bs;
            }
        }
        if last {
            break;
        }
    }
    if let Some(f) = fcs {
        if (st.out.len() - start) as u64 != f {
            return Err(err("frame content size mismatch"));
        }
    }
    if fhd & 4 != 0 {
        if p + 4 > d.len() {
            return Err(err("truncated content checksum"));
        }
        let want = u32::from_le_bytes([d[p], d[p + 1], d[p + 2], d[p + 3]]);
        if xxh64(&st.out[start..], 0) as u32 != want {
            return Err(err("content checksum mismatch"));
        }
        p += 4;
    }
    Ok(p)
}

fn block(b: &[u8], st: &mut State) -> Result<(), CodecError> {
    if b.is_empty() {
        return Err(err("missing literals section header"));
    }
    let lt = b[0] & 3;
    let sf = (b[0] >> 2) & 3;
    let lits: Vec<u8>;
    let q;
    if lt <= 1 {
        let hs = match sf {
            0 | 2 => 1,
            1 => 2,
            _ => 3,
        };
        if b.len() < hs {
            return Err(err("truncated literals section"));
        }
        let regen = match hs {
            1 => (b[0] >> 3) as usize,
            2 => ((b[0] >> 4) as usize) | ((b[1] as usize) << 4),
            _ => ((b[0] >> 4) as usize) | ((b[1] as usize) << 4) | ((b[2] as usize) << 12),
        };
        if regen > MAXB {
            return Err(err("literals section too large"));
        }
        if lt == 0 {
            if hs + regen > b.len() {
                return Err(err("truncated literals section"));
            }
            lits = b[hs..hs + regen].to_vec();
            q = hs + regen;
        } else {
            if hs + 1 > b.len() {
                return Err(err("truncated literals section"));
            }
            lits = vec![b[hs]; regen];
            q = hs + 1;
        }
    } else {
        let (hs, nb) = match sf {
            0 | 1 => (3usize, 10u32),
            2 => (4, 14),
            _ => (5, 18),
        };
        if b.len() < hs {
            return Err(err("truncated literals section"));
        }
        let v = le(&b[..hs]);
        let regen = ((v >> 4) & ((1 << nb) - 1)) as usize;
        let csize = ((v >> (4 + nb)) & ((1 << nb) - 1)) as usize;
        if regen > MAXB {
            return Err(err("literals section too large"));
        }
        if hs + csize > b.len() {
            return Err(err("truncated literals section"));
        }
        let c = &b[hs..hs + csize];
        q = hs + csize;
        let tsize = if lt == 2 {
            let (h, used) = read_tree(c)?;
            st.huf = Some(h);
            used
        } else {
            if st.huf.is_none() {
                return Err(err("treeless literals without a previous Huffman table"));
            }
            0
        };
        let h = st.huf.as_ref().unwrap();
        lits = huf_lits(h, &c[tsize..], regen, if sf == 0 { 1 } else { 4 })?;
    }
    sequences(&b[q..], &lits, st)
}

fn read_tree(c: &[u8]) -> Result<(Huf, usize), CodecError> {
    if c.is_empty() {
        return Err(err("missing Huffman tree header"));
    }
    let hb = c[0] as usize;
    let mut ws: Vec<u8> = Vec::new();
    let tsize;
    if hb >= 128 {
        let n = hb - 127;
        let nbytes = n.div_ceil(2);
        if 1 + nbytes > c.len() {
            return Err(err("truncated Huffman weights"));
        }
        for i in 0..n {
            let x = c[1 + i / 2];
            ws.push(if i % 2 == 0 { x >> 4 } else { x & 15 });
        }
        tsize = 1 + nbytes;
    } else {
        if 1 + hb > c.len() {
            return Err(err("truncated Huffman tree description"));
        }
        let fc = &c[1..1 + hb];
        let (norm, log, used) = read_ncount(fc, 254, 6)?;
        if used >= fc.len() {
            return Err(err("truncated Huffman weights bitstream"));
        }
        let bs = &fc[used..];
        if bs[bs.len() - 1] == 0 {
            return Err(err("bitstream missing sentinel bit"));
        }
        let t = fse_build(&norm, log);
        let mut br = Rev::new(bs);
        if br.pos < 2 * log as i64 {
            return Err(err("truncated Huffman weights bitstream"));
        }
        let mut s1 = br.read(log) as usize;
        let mut s2 = br.read(log) as usize;
        loop {
            ws.push(t.sym[s1] as u8);
            s1 = t.base[s1] as usize + br.read(t.nbits[s1] as u32) as usize;
            if br.pos < 0 {
                ws.push(t.sym[s2] as u8);
                break;
            }
            ws.push(t.sym[s2] as u8);
            s2 = t.base[s2] as usize + br.read(t.nbits[s2] as u32) as usize;
            if br.pos < 0 {
                ws.push(t.sym[s1] as u8);
                break;
            }
            if ws.len() > 255 {
                break; // can only grow further: same verdict as checking afterwards
            }
        }
        if ws.len() > 255 {
            return Err(err("too many Huffman weights"));
        }
        tsize = 1 + hb;
    }
    if ws.iter().any(|&w| w > 11) {
        return Err(err("Huffman weight too large"));
    }
    let total: u32 = ws.iter().map(|&w| (1u32 << w) >> 1).sum();
    if total == 0 {
        return Err(err("empty Huffman table"));
    }
    let tl = 32 - total.leading_zeros();
    if tl > 11 {
        return Err(err("Huffman code length too large"));
    }
    let rest = (1u32 << tl) - total;
    if rest & (rest.wrapping_sub(1)) != 0 {
        return Err(err("corrupted Huffman weights"));
    }
    ws.push((32 - rest.leading_zeros()) as u8);
    let size = 1usize << tl;
    let mut sym = vec![0u8; size];
    let mut len = vec![0u8; size];
    let mut rank_start = [0usize; 13];
    let mut pos = 0usize;
    for w in 1..=tl as usize {
        rank_start[w] = pos;
        pos += ws.iter().filter(|&&x| x as usize == w).count() << (w - 1);
    }
    for (s, &w) in ws.iter().enumerate() {
        if w == 0 {
            continue;
        }
        let w = w as usize;
        let st = rank_start[w];
        rank_start[w] += 1 << (w - 1);
        for k in st..st + (1 << (w - 1)) {
            sym[k] = s as u8;
            len[k] = (tl as usize + 1 - w) as u8;
        }
    }
    Ok((Huf { log: tl, sym, len }, tsize))
}

fn huf_stream(h: &Huf, data: &[u8], n: usize, out: &mut Vec<u8>) -> Result<(), CodecError> {
    if data.is_empty() {
        return Err(err("empty bitstream"));
    }
    if data[data.len() - 1] == 0 {
        return Err(err("bitstream missing sentinel bit"));
    }
    let mut br = Rev::new(data);
    for _ in 0..n {
        let v = br.peek(h.log) as usize;
        let l = h.len[v] as i64;
        if l > br.pos {
            return Err(err("Huffman stream overrun"));
        }
        br.pos -= l;
        out.push(h.sym[v]);
    }
    if br.pos != 0 {
        return Err(err("Huffman stream not fully consumed"));
    }
    Ok(())
}

fn huf_lits(h: &Huf, c: &[u8], regen: usize, streams: usize) -> Result<Vec<u8>, CodecError> {
    let mut o = Vec::with_capacity(regen);
    if streams == 1 {
        huf_stream(h, c, regen, &mut o)?;
        return Ok(o);
    }
    if c.len() < 6 {
        return Err(err("truncated literals jump table"));
    }
    let s1 = u16::from_le_bytes([c[0], c[1]]) as usize;
    let s2 = u16::from_le_bytes([c[2], c[3]]) as usize;
    let s3 = u16::from_le_bytes([c[4], c[5]]) as usize;
    if 6 + s1 + s2 + s3 > c.len() {
        return Err(err("literals jump table exceeds section"));
    }
    let seg = regen.div_ceil(4);
    if 3 * seg > regen {
        return Err(err("corrupted 4-stream literals sizes"));
    }
    let sizes = [s1, s2, s3, c.len() - 6 - s1 - s2 - s3];
    let counts = [seg, seg, seg, regen - 3 * seg];
    let mut p = 6;
    for k in 0..4 {
        huf_stream(h, &c[p..p + sizes[k]], counts[k], &mut o)?;
        p += sizes[k];
    }
    Ok(o)
}

fn sequences(s: &[u8], lits: &[u8], st: &mut State) -> Result<(), CodecError> {
    if s.is_empty() {
        return Err(err("missing sequences section header"));
    }
    let b0 = s[0] as usize;
    let (n, mut r) = if b0 < 128 {
        (b0, 1)
    } else if b0 < 255 {
        if s.len() < 2 {
            return Err(err("truncated sequences header"));
        }
        (((b0 - 128) << 8) + s[1] as usize, 2)
    } else {
        if s.len() < 3 {
            return Err(err("truncated sequences header"));
        }
        (s[1] as usize + ((s[2] as usize) << 8) + 0x7F00, 3)
    };
    if n == 0 {
        if r != s.len() {
            return Err(err("trailing bytes after empty sequences section"));
        }
        st.out.extend_from_slice(lits);
        return Ok(());
    }
    if s.len() < r + 1 {
        return Err(err("missing sequence compression modes"));
    }
    let modes = s[r];
    r += 1;
    if modes & 3 != 0 {
        return Err(err("reserved sequence mode bits set"));
    }
    let specs: [(u32, &[i16], u32, usize, u32); 3] = [
        (6, &LL_DEFAULT, 6, 35, 9),
        (4, &OF_DEFAULT, 5, 31, 8),
        (2, &ML_DEFAULT, 6, 52, 9),
    ];
    for (k, &(sh, dflt, dlog, maxsym, maxlog)) in specs.iter().enumerate() {
        let mode = (modes >> sh) & 3;
        let slot = match k {
            0 => &mut st.ll,
            1 => &mut st.of,
            _ => &mut st.ml,
        };
        match mode {
            0 => *slot = Some(Seqs { fse: fse_build(dflt, dlog) }),
            1 => {
                if r >= s.len() {
                    return Err(err("truncated RLE sequence table"));
                }
                let sym = s[r] as usize;
                r += 1;
                if sym > maxsym {
                    return Err(err("RLE sequence symbol out of range"));
                }
                *slot = Some(Seqs { fse: Fse { log: 0, sym: vec![sym as u16], nbits: vec![0], base: vec![0] } });
            }
            2 => {
                let (norm, log, used) = read_ncount(&s[r..], maxsym, maxlog)?;
                if r + used > s.len() {
                    return Err(err("truncated FSE table description"));
                }
                *slot = Some(Seqs { fse: fse_build(&norm, log) });
                r += used;
            }
            _ => {
                if slot.is_none() {
                    return Err(err("repeat mode without a previous sequence table"));
                }
            }
        }
    }
    let bs = &s[r..];
    if bs.is_empty() {
        return Err(err("missing sequences bitstream"));
    }
    if bs[bs.len() - 1] == 0 {
        return Err(err("bitstream missing sentinel bit"));
    }
    let mut br = Rev::new(bs);
    let trunc = || err("truncated sequences bitstream");
    let lt = &st.ll.as_ref().unwrap().fse;
    let ot = &st.of.as_ref().unwrap().fse;
    let mt = &st.ml.as_ref().unwrap().fse;
    macro_rules! rd {
        ($nb:expr) => {{
            let v = br.read($nb as u32);
            if br.pos < 0 {
                return Err(trunc());
            }
            v
        }};
    }
    let mut ls = rd!(lt.log) as usize;
    let mut os = rd!(ot.log) as usize;
    let mut ms = rd!(mt.log) as usize;
    let mut lp = 0usize;
    let mut tot = 0usize;
    let out = &mut st.out;
    let rep = &mut st.rep;
    for i in 0..n {
        let llc = lt.sym[ls] as usize;
        let ofc = ot.sym[os] as u32;
        let mlc = mt.sym[ms] as usize;
        let ov = (1u64 << ofc) + rd!(ofc);
        let ml = ML_BASE[mlc] as usize + rd!(ML_BITS[mlc]) as usize;
        let ll = LL_BASE[llc] as usize + rd!(LL_BITS[llc]) as usize;
        let off: u64;
        if ov > 3 {
            off = ov - 3;
            *rep = [off, rep[0], rep[1]];
        } else {
            let idx = (ov - 1) as usize + if ll == 0 { 1 } else { 0 };
            match idx {
                0 => off = rep[0],
                1 => {
                    off = rep[1];
                    *rep = [off, rep[0], rep[2]];
                }
                2 => {
                    off = rep[2];
                    *rep = [off, rep[0], rep[1]];
                }
                _ => {
                    off = rep[0].wrapping_sub(1);
                    *rep = [off, rep[0], rep[1]];
                }
            }
        }
        if lp + ll > lits.len() {
            return Err(err("sequence literals overrun"));
        }
        if off == 0 {
            return Err(err("invalid repeat offset"));
        }
        out.extend_from_slice(&lits[lp..lp + ll]);
        lp += ll;
        if off > out.len() as u64 {
            return Err(err("sequence offset too far back"));
        }
        if tot + ll + ml > MAXB {
            return Err(err("block regenerated size too large"));
        }
        tot += ll + ml;
        let off = off as usize;
        let start = out.len() - off;
        if off >= ml {
            out.extend_from_within(start..start + ml);
        } else {
            for k in 0..ml {
                let b = out[start + k];
                out.push(b);
            }
        }
        if i + 1 < n {
            ls = lt.base[ls] as usize + rd!(lt.nbits[ls]) as usize;
            ms = mt.base[ms] as usize + rd!(mt.nbits[ms]) as usize;
            os = ot.base[os] as usize + rd!(ot.nbits[os]) as usize;
        }
    }
    if br.pos != 0 {
        return Err(err("sequences bitstream not fully consumed"));
    }
    out.extend_from_slice(&lits[lp..]);
    Ok(())
}
