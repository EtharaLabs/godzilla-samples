//! Brotli decoder (RFC 7932) replicating the original runtime's custom
//! decoder: same error messages (all prefixed `brotli: `), same check order.
//!
//! Notable behaviours: large-window streams are rejected; padding bits before
//! metadata / uncompressed data must be zero but the final padding after the
//! last meta-block is not checked; trailing bytes after the stream are
//! ignored; an insert that overruns the meta-block length is detected only
//! after all of its literals were decoded.

use super::CodecError;

fn err(msg: &str) -> CodecError {
    CodecError::new(format!("brotli: {}", msg))
}

pub static DICT: &[u8; 122784] = include_bytes!("brotli_dict.bin");

pub const NDBITS: [u32; 25] = [
    0, 0, 0, 0, 10, 10, 11, 11, 10, 10, 10, 10, 10, 9, 9, 8, 7, 7, 8, 7, 7, 6, 6, 5, 5,
];
pub const DOFFSET: [u32; 25] = [
    0, 0, 0, 0, 0, 4096, 9216, 21504, 35840, 44032, 53248, 63488, 74752, 87040, 93696, 100864,
    104704, 106752, 108928, 113536, 115968, 118528, 119872, 121280, 122016,
];

// Transform types
const T_IDENTITY: u8 = 0;
const T_UPPER_FIRST: u8 = 10;
const T_UPPER_ALL: u8 = 11;
// 1..=9: omit last k; 12..=20: omit first k (k = t - 11)

macro_rules! tr {
    ($p:expr, $t:expr, $s:expr) => {
        ($p.as_bytes(), $t, $s.as_bytes())
    };
}

const OF1: u8 = 12;
const OL1: u8 = 1;

pub static TRANSFORMS: [(&[u8], u8, &[u8]); 121] = [
    tr!("", T_IDENTITY, ""),
    tr!("", T_IDENTITY, " "),
    tr!(" ", T_IDENTITY, " "),
    tr!("", OF1, ""),
    tr!("", T_UPPER_FIRST, " "),
    tr!("", T_IDENTITY, " the "),
    tr!(" ", T_IDENTITY, ""),
    tr!("s ", T_IDENTITY, " "),
    tr!("", T_IDENTITY, " of "),
    tr!("", T_UPPER_FIRST, ""),
    tr!("", T_IDENTITY, " and "),
    tr!("", OF1 + 1, ""),
    tr!("", OL1, ""),
    tr!(", ", T_IDENTITY, " "),
    tr!("", T_IDENTITY, ", "),
    tr!(" ", T_UPPER_FIRST, " "),
    tr!("", T_IDENTITY, " in "),
    tr!("", T_IDENTITY, " to "),
    tr!("e ", T_IDENTITY, " "),
    tr!("", T_IDENTITY, "\""),
    tr!("", T_IDENTITY, "."),
    tr!("", T_IDENTITY, "\">"),
    tr!("", T_IDENTITY, "\n"),
    tr!("", OL1 + 2, ""),
    tr!("", T_IDENTITY, "]"),
    tr!("", T_IDENTITY, " for "),
    tr!("", OF1 + 2, ""),
    tr!("", OL1 + 1, ""),
    tr!("", T_IDENTITY, " a "),
    tr!("", T_IDENTITY, " that "),
    tr!(" ", T_UPPER_FIRST, ""),
    tr!("", T_IDENTITY, ". "),
    tr!(".", T_IDENTITY, ""),
    tr!(" ", T_IDENTITY, ", "),
    tr!("", OF1 + 3, ""),
    tr!("", T_IDENTITY, " with "),
    tr!("", T_IDENTITY, "'"),
    tr!("", T_IDENTITY, " from "),
    tr!("", T_IDENTITY, " by "),
    tr!("", OF1 + 4, ""),
    tr!("", OF1 + 5, ""),
    tr!(" the ", T_IDENTITY, ""),
    tr!("", OL1 + 3, ""),
    tr!("", T_IDENTITY, ". The "),
    tr!("", T_UPPER_ALL, ""),
    tr!("", T_IDENTITY, " on "),
    tr!("", T_IDENTITY, " as "),
    tr!("", T_IDENTITY, " is "),
    tr!("", OL1 + 6, ""),
    tr!("", OL1, "ing "),
    tr!("", T_IDENTITY, "\n\t"),
    tr!("", T_IDENTITY, ":"),
    tr!(" ", T_IDENTITY, ". "),
    tr!("", T_IDENTITY, "ed "),
    tr!("", OF1 + 8, ""),
    tr!("", OF1 + 6, ""),
    tr!("", OL1 + 5, ""),
    tr!("", T_IDENTITY, "("),
    tr!("", T_UPPER_FIRST, ", "),
    tr!("", OL1 + 7, ""),
    tr!("", T_IDENTITY, " at "),
    tr!("", T_IDENTITY, "ly "),
    tr!(" the ", T_IDENTITY, " of "),
    tr!("", OL1 + 4, ""),
    tr!("", OL1 + 8, ""),
    tr!(" ", T_UPPER_FIRST, ", "),
    tr!("", T_UPPER_FIRST, "\""),
    tr!(".", T_IDENTITY, "("),
    tr!("", T_UPPER_ALL, " "),
    tr!("", T_UPPER_FIRST, "\">"),
    tr!("", T_IDENTITY, "=\""),
    tr!(" ", T_IDENTITY, "."),
    tr!(".com/", T_IDENTITY, ""),
    tr!(" the ", T_IDENTITY, " of the "),
    tr!("", T_UPPER_FIRST, "'"),
    tr!("", T_IDENTITY, ". This "),
    tr!("", T_IDENTITY, ","),
    tr!(".", T_IDENTITY, " "),
    tr!("", T_UPPER_FIRST, "("),
    tr!("", T_UPPER_FIRST, "."),
    tr!("", T_IDENTITY, " not "),
    tr!(" ", T_IDENTITY, "=\""),
    tr!("", T_IDENTITY, "er "),
    tr!(" ", T_UPPER_ALL, " "),
    tr!("", T_IDENTITY, "al "),
    tr!(" ", T_UPPER_ALL, ""),
    tr!("", T_IDENTITY, "='"),
    tr!("", T_UPPER_ALL, "\""),
    tr!("", T_UPPER_FIRST, ". "),
    tr!(" ", T_IDENTITY, "("),
    tr!("", T_IDENTITY, "ful "),
    tr!(" ", T_UPPER_FIRST, ". "),
    tr!("", T_IDENTITY, "ive "),
    tr!("", T_IDENTITY, "less "),
    tr!("", T_UPPER_ALL, "'"),
    tr!("", T_IDENTITY, "est "),
    tr!(" ", T_UPPER_FIRST, "."),
    tr!("", T_UPPER_ALL, "\">"),
    tr!(" ", T_IDENTITY, "='"),
    tr!("", T_UPPER_FIRST, ","),
    tr!("", T_IDENTITY, "ize "),
    tr!("", T_UPPER_ALL, "."),
    tr!("\u{a0}", T_IDENTITY, ""),
    tr!(" ", T_IDENTITY, ","),
    tr!("", T_UPPER_FIRST, "=\""),
    tr!("", T_UPPER_ALL, "=\""),
    tr!("", T_IDENTITY, "ous "),
    tr!("", T_UPPER_ALL, ", "),
    tr!("", T_UPPER_FIRST, "='"),
    tr!(" ", T_UPPER_FIRST, ","),
    tr!(" ", T_UPPER_ALL, "=\""),
    tr!(" ", T_UPPER_ALL, ", "),
    tr!("", T_UPPER_ALL, ","),
    tr!("", T_UPPER_ALL, "("),
    tr!("", T_UPPER_ALL, ". "),
    tr!(" ", T_UPPER_ALL, "."),
    tr!("", T_UPPER_ALL, "='"),
    tr!(" ", T_UPPER_ALL, ". "),
    tr!(" ", T_UPPER_FIRST, "=\""),
    tr!(" ", T_UPPER_ALL, "='"),
    tr!(" ", T_UPPER_FIRST, "='"),
];

/// Uppercase one (pseudo-)UTF-8 character in place at `w[i..]`; returns the step.
/// Modifications that would land beyond the end of `w` are dropped.
fn to_upper(w: &mut [u8], i: usize) -> usize {
    let c = w[i];
    if c < 0xc0 {
        if c.is_ascii_lowercase() {
            w[i] ^= 32;
        }
        return 1;
    }
    if c < 0xe0 {
        if i + 1 < w.len() {
            w[i + 1] ^= 32;
        }
        return 2;
    }
    if i + 2 < w.len() {
        w[i + 2] ^= 5;
    }
    3
}

/// Append the transformed dictionary word to `out`.
pub fn transform_word(out: &mut Vec<u8>, word: &[u8], t: usize) {
    let (prefix, ty, suffix) = TRANSFORMS[t];
    out.extend_from_slice(prefix);
    let mut w: Vec<u8> = if (1..=9).contains(&ty) {
        let k = ty as usize;
        word[..word.len().saturating_sub(k)].to_vec()
    } else if (12..=20).contains(&ty) {
        let k = (ty - 11) as usize;
        if k >= word.len() {
            Vec::new()
        } else {
            word[k..].to_vec()
        }
    } else {
        word.to_vec()
    };
    if ty == T_UPPER_FIRST {
        if !w.is_empty() {
            to_upper(&mut w, 0);
        }
    } else if ty == T_UPPER_ALL {
        let mut i = 0;
        while i < w.len() {
            i += to_upper(&mut w, i);
        }
    }
    out.extend_from_slice(&w);
    out.extend_from_slice(suffix);
}

const LUT0: [u8; 256] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 4, 0, 0, 4, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    8, 12, 16, 12, 12, 20, 12, 16, 24, 28, 12, 12, 32, 12, 36, 12,
    44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 32, 32, 24, 40, 28, 12,
    12, 48, 52, 52, 52, 48, 52, 52, 52, 48, 52, 52, 52, 52, 52, 48,
    52, 52, 52, 52, 52, 48, 52, 52, 52, 52, 52, 24, 12, 28, 12, 12,
    12, 56, 60, 60, 60, 56, 60, 60, 60, 56, 60, 60, 60, 60, 60, 56,
    60, 60, 60, 60, 60, 56, 60, 60, 60, 60, 60, 24, 12, 28, 12, 0,
    0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
    0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
    0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
    0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
    2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3,
    2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3,
    2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3,
    2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 3,
];
const LUT1: [u8; 256] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1,
    1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1,
    1, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 1, 1, 1, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
];
const LUT2: [u8; 256] = [
    0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 7,
];


const INS_BASE: [u32; 24] = [
    0, 1, 2, 3, 4, 5, 6, 8, 10, 14, 18, 26, 34, 50, 66, 98, 130, 194, 322, 578, 1090, 2114, 6210,
    22594,
];
const INS_EXTRA: [u32; 24] = [
    0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 12, 14, 24,
];
const COPY_BASE: [u32; 24] = [
    2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 18, 22, 30, 38, 54, 70, 102, 134, 198, 326, 582, 1094,
    2118,
];
const COPY_EXTRA: [u32; 24] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 24,
];
const BLEN_BASE: [u32; 26] = [
    1, 5, 9, 13, 17, 25, 33, 41, 49, 65, 81, 97, 113, 145, 177, 209, 241, 305, 369, 497, 753,
    1265, 2289, 4337, 8433, 16625,
];
const BLEN_EXTRA: [u32; 26] = [
    2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 7, 8, 9, 10, 11, 12, 13, 24,
];
const CL_ORDER: [usize; 18] = [1, 2, 3, 4, 0, 5, 17, 6, 16, 7, 8, 9, 10, 11, 12, 13, 14, 15];
/// Static prefix code for code-length-code lengths, indexed by the next 4 bits.
const CLCL_LEN: [u32; 16] = [2, 2, 2, 3, 2, 2, 2, 4, 2, 2, 2, 3, 2, 2, 2, 4];
const CLCL_VAL: [u8; 16] = [0, 4, 3, 2, 0, 4, 3, 1, 0, 4, 3, 2, 0, 4, 3, 5];
/// Block length for a category with a single block type (per meta-block).
const SINGLE_TYPE_BLOCK_LEN: u32 = 1 << 24;

/// LSB-first bit reader; any read needing bits past the end fails.
struct Br<'a> {
    data: &'a [u8],
    pos: usize, // next byte to load into `buf`
    buf: u64,
    cnt: u32,
}

impl<'a> Br<'a> {
    fn new(data: &'a [u8]) -> Self {
        Br { data, pos: 0, buf: 0, cnt: 0 }
    }

    #[inline]
    fn refill(&mut self) {
        while self.cnt <= 56 && self.pos < self.data.len() {
            self.buf |= (self.data[self.pos] as u64) << self.cnt;
            self.pos += 1;
            self.cnt += 8;
        }
    }

    #[inline]
    fn read(&mut self, n: u32) -> Result<u32, CodecError> {
        if n == 0 {
            return Ok(0);
        }
        if self.cnt < n {
            self.refill();
            if self.cnt < n {
                return Err(err("unexpected end of input"));
            }
        }
        let v = (self.buf & ((1u64 << n) - 1)) as u32;
        self.buf >>= n;
        self.cnt -= n;
        Ok(v)
    }

    /// Up to 24 bits of look-ahead: (value with zero fill, available bits).
    #[inline]
    fn peek(&mut self, n: u32) -> (u32, u32) {
        if self.cnt < n {
            self.refill();
        }
        ((self.buf & ((1u64 << n) - 1)) as u32, self.cnt.min(n))
    }

    #[inline]
    fn consume(&mut self, n: u32) {
        self.buf >>= n;
        self.cnt -= n;
    }

    /// Skip to the byte boundary; the skipped bits must be zero.
    fn padding(&mut self) -> Result<(), CodecError> {
        let k = self.cnt % 8;
        if self.buf & ((1u64 << k) - 1) != 0 {
            return Err(err("non-zero padding bits"));
        }
        self.consume(k);
        Ok(())
    }

    /// Byte offset of the next unread byte (only valid when byte aligned).
    fn byte_pos(&self) -> usize {
        self.pos - (self.cnt / 8) as usize
    }

    fn seek(&mut self, byte: usize) {
        self.pos = byte;
        self.buf = 0;
        self.cnt = 0;
    }
}

/// Canonical prefix code (always complete, or a single 0-bit symbol).
struct Huff {
    single: Option<u16>,
    fast: Vec<u32>, // (symbol << 4) | len for codes of <= fast_bits bits, else 0
    fast_bits: u32,
    count: [u16; 16],
    symbol: Vec<u16>,
}

impl Huff {
    fn single(sym: u16) -> Huff {
        Huff { single: Some(sym), fast: Vec::new(), fast_bits: 0, count: [0; 16], symbol: Vec::new() }
    }

    fn from_lengths(lengths: &[u8]) -> Huff {
        let mut count = [0u16; 16];
        for &l in lengths {
            count[l as usize] += 1;
        }
        count[0] = 0;
        let mut offs = [0usize; 17];
        for len in 1..16 {
            offs[len + 1] = offs[len] + count[len] as usize;
        }
        let mut symbol = vec![0u16; offs[16]];
        for (s, &l) in lengths.iter().enumerate() {
            if l != 0 {
                symbol[offs[l as usize]] = s as u16;
                offs[l as usize] += 1;
            }
        }
        let max_len = (1..16).rev().find(|&l| count[l] != 0).unwrap_or(1) as u32;
        let fast_bits = max_len.min(10);
        let mut fast = vec![0u32; 1 << fast_bits];
        let mut next = [0u32; 16];
        let mut code = 0u32;
        for len in 1..16usize {
            next[len] = code;
            code = (code + count[len] as u32) << 1;
        }
        for (s, &l) in lengths.iter().enumerate() {
            if l == 0 {
                continue;
            }
            let l = l as u32;
            let c = next[l as usize];
            next[l as usize] += 1;
            if l <= fast_bits {
                let rev = c.reverse_bits() >> (32 - l);
                let mut i = rev;
                while i < (1 << fast_bits) {
                    fast[i as usize] = ((s as u32) << 4) | l;
                    i += 1 << l;
                }
            }
        }
        Huff { single: None, fast, fast_bits, count, symbol }
    }

    #[inline]
    fn decode(&self, br: &mut Br) -> Result<u32, CodecError> {
        if let Some(s) = self.single {
            return Ok(s as u32);
        }
        let (v, avail) = br.peek(self.fast_bits);
        let e = self.fast[v as usize];
        let l = e & 15;
        if l != 0 && l <= avail {
            br.consume(l);
            return Ok(e >> 4);
        }
        // Canonical decode over up to 15 look-ahead bits.
        let (v, avail) = br.peek(15);
        let (mut code, mut first, mut index) = (0i32, 0i32, 0i32);
        for len in 1..16u32 {
            if len > avail {
                return Err(err("unexpected end of input"));
            }
            code |= ((v >> (len - 1)) & 1) as i32;
            let c = self.count[len as usize] as i32;
            if code - c < first {
                br.consume(len);
                return Ok(self.symbol[(index + code - first) as usize] as u32);
            }
            index += c;
            first += c;
            first <<= 1;
            code <<= 1;
        }
        Err(err("prefix code is under/over-subscribed"))
    }
}

fn read_varlen8(br: &mut Br) -> Result<u32, CodecError> {
    if br.read(1)? == 0 {
        return Ok(0);
    }
    let n = br.read(3)?;
    if n == 0 {
        return Ok(1);
    }
    Ok(br.read(n)? + (1 << n))
}

fn read_prefix_code(br: &mut Br, alphabet: usize) -> Result<Huff, CodecError> {
    let hskip = br.read(2)?;
    if hskip == 1 {
        let alpha_bits = (32 - ((alphabet as u32) - 1).leading_zeros()).max(1);
        let nsym = br.read(2)? as usize + 1;
        let mut syms = [0u16; 4];
        for s in syms.iter_mut().take(nsym) {
            let v = br.read(alpha_bits)? as usize;
            if v >= alphabet {
                return Err(err("simple code symbol out of range"));
            }
            *s = v as u16;
        }
        for i in 0..nsym {
            for j in i + 1..nsym {
                if syms[i] == syms[j] {
                    return Err(err("duplicate simple code symbol"));
                }
            }
        }
        let mut lengths = vec![0u8; alphabet];
        match nsym {
            1 => return Ok(Huff::single(syms[0])),
            2 => {
                lengths[syms[0] as usize] = 1;
                lengths[syms[1] as usize] = 1;
            }
            3 => {
                lengths[syms[0] as usize] = 1;
                lengths[syms[1] as usize] = 2;
                lengths[syms[2] as usize] = 2;
            }
            _ => {
                if br.read(1)? == 0 {
                    for &s in &syms {
                        lengths[s as usize] = 2;
                    }
                } else {
                    lengths[syms[0] as usize] = 1;
                    lengths[syms[1] as usize] = 2;
                    lengths[syms[2] as usize] = 3;
                    lengths[syms[3] as usize] = 3;
                }
            }
        }
        return Ok(Huff::from_lengths(&lengths));
    }
    // Complex prefix code.
    let mut cl = [0u8; 18];
    let mut space: i32 = 32;
    let mut num_codes = 0;
    for &idx in CL_ORDER.iter().skip(hskip as usize) {
        let (v, avail) = br.peek(4);
        let l = CLCL_LEN[v as usize];
        if l > avail {
            return Err(err("unexpected end of input"));
        }
        br.consume(l);
        let val = CLCL_VAL[v as usize];
        cl[idx] = val;
        if val != 0 {
            space -= 32 >> val;
            num_codes += 1;
            if space <= 0 {
                break;
            }
        }
    }
    if num_codes != 1 && space != 0 {
        return Err(err("corrupt code-length code"));
    }
    let clh = if num_codes == 1 {
        Huff::single(cl.iter().position(|&l| l != 0).unwrap() as u16)
    } else {
        Huff::from_lengths(&cl)
    };
    let mut lengths = vec![0u8; alphabet];
    let mut symbol = 0usize;
    let mut prev_len: u8 = 8;
    let mut repeat: u32 = 0;
    let mut repeat_len: u8 = 0;
    let mut space: i32 = 32768;
    while symbol < alphabet && space > 0 {
        let c = clh.decode(br)? as u8;
        if c < 16 {
            repeat = 0;
            lengths[symbol] = c;
            if c != 0 {
                prev_len = c;
                space -= 32768 >> c;
            }
            symbol += 1;
        } else {
            let extra = if c == 16 { 2 } else { 3 };
            let new_len = if c == 16 { prev_len } else { 0 };
            if repeat_len != new_len {
                repeat = 0;
                repeat_len = new_len;
            }
            let old = repeat;
            if repeat > 0 {
                repeat = (repeat - 2) << extra;
            }
            repeat += br.read(extra)? + 3;
            let delta = (repeat - old) as usize;
            if symbol + delta > alphabet {
                return Err(err("code-length run overflows alphabet"));
            }
            for l in &mut lengths[symbol..symbol + delta] {
                *l = repeat_len;
            }
            symbol += delta;
            if repeat_len != 0 {
                space -= (delta as i32) << (15 - repeat_len);
            }
        }
    }
    if space != 0 {
        return Err(err("prefix code is under/over-subscribed"));
    }
    Ok(Huff::from_lengths(&lengths))
}

fn read_block_len(br: &mut Br, h: &Huff) -> Result<u32, CodecError> {
    let c = h.decode(br)? as usize;
    Ok(BLEN_BASE[c] + br.read(BLEN_EXTRA[c])?)
}

fn read_context_map(br: &mut Br, size: usize, ntrees: usize) -> Result<Vec<u8>, CodecError> {
    let mut map = vec![0u8; size];
    if ntrees < 2 {
        return Ok(map);
    }
    let rlemax = if br.read(1)? == 1 { br.read(4)? + 1 } else { 0 };
    let h = read_prefix_code(br, ntrees + rlemax as usize)?;
    let mut i = 0;
    while i < size {
        let code = h.decode(br)?;
        if code == 0 {
            map[i] = 0;
            i += 1;
        } else if code > rlemax {
            map[i] = (code - rlemax) as u8;
            i += 1;
        } else {
            let reps = (1usize << code) + br.read(code)? as usize;
            if i + reps > size {
                return Err(err("context map run overflows"));
            }
            for v in &mut map[i..i + reps] {
                *v = 0;
            }
            i += reps;
        }
    }
    if br.read(1)? == 1 {
        let mut mtf: Vec<u8> = (0..=255u8).collect();
        for v in map.iter_mut() {
            let idx = *v as usize;
            let val = mtf[idx];
            *v = val;
            mtf.copy_within(0..idx, 1);
            mtf[0] = val;
        }
    }
    Ok(map)
}

struct Block {
    ntypes: u32,
    types: Option<(Huff, Huff)>,
    btype: u32,
    rb: [u32; 2],
    left: u32,
}

impl Block {
    fn read(br: &mut Br) -> Result<Block, CodecError> {
        let ntypes = read_varlen8(br)? + 1;
        if ntypes >= 2 {
            let th = read_prefix_code(br, ntypes as usize + 2)?;
            let lh = read_prefix_code(br, 26)?;
            let left = read_block_len(br, &lh)?;
            Ok(Block { ntypes, types: Some((th, lh)), btype: 0, rb: [1, 0], left })
        } else {
            Ok(Block { ntypes, types: None, btype: 0, rb: [1, 0], left: SINGLE_TYPE_BLOCK_LEN })
        }
    }

    /// Account for one symbol of this category, switching blocks if needed.
    #[inline]
    fn next(&mut self, br: &mut Br) -> Result<(), CodecError> {
        if self.left == 0 {
            let (th, lh) = match &self.types {
                Some(t) => t,
                None => return Err(err("block length exhausted with a single block type")),
            };
            let mut t = th.decode(br)?;
            let len = read_block_len(br, lh)?;
            t = match t {
                0 => self.rb[0],
                1 => self.rb[1] + 1,
                n => n - 2,
            };
            if t >= self.ntypes {
                t -= self.ntypes;
            }
            self.rb = [self.rb[1], t];
            self.btype = t;
            self.left = len;
        }
        self.left -= 1;
        Ok(())
    }
}

/// `zlib.brotliDecompressSync`.
pub fn decode(data: &[u8]) -> Result<Vec<u8>, CodecError> {
    let mut br = Br::new(data);
    let wbits: u32 = if br.read(1)? == 0 {
        16
    } else {
        let n = br.read(3)?;
        if n != 0 {
            17 + n
        } else {
            let m = br.read(3)?;
            if m == 1 {
                return Err(err("large-window streams are not supported"));
            }
            if m != 0 {
                8 + m
            } else {
                17
            }
        }
    };
    let max_backward = (1usize << wbits) - 16;
    let mut out: Vec<u8> = Vec::new();
    let mut dist_rb: [i64; 4] = [16, 15, 11, 4];
    let mut dist_idx: usize = 0;
    loop {
        let islast = br.read(1)? == 1;
        if islast && br.read(1)? == 1 {
            break;
        }
        let mn = br.read(2)?;
        if mn == 3 {
            if br.read(1)? != 0 {
                return Err(err("reserved bit set"));
            }
            let nbytes = br.read(2)?;
            let mut skip = 0usize;
            for i in 0..nbytes {
                let b = br.read(8)? as usize;
                if i + 1 == nbytes && nbytes > 1 && b == 0 {
                    return Err(err("exuberant metadata size byte"));
                }
                skip |= b << (8 * i);
            }
            if nbytes > 0 {
                skip += 1;
            }
            br.padding()?;
            let p = br.byte_pos();
            if skip > data.len() - p {
                return Err(err("metadata overruns input"));
            }
            br.seek(p + skip);
            if islast {
                break;
            }
            continue;
        }
        let nibbles = mn + 4;
        let mut mlen = 0usize;
        for i in 0..nibbles {
            let v = br.read(4)? as usize;
            if i + 1 == nibbles && nibbles > 4 && v == 0 {
                return Err(err("exuberant size nibble"));
            }
            mlen |= v << (4 * i);
        }
        mlen += 1;
        if !islast && br.read(1)? == 1 {
            br.padding()?;
            let p = br.byte_pos();
            if mlen > data.len() - p {
                return Err(err("uncompressed block overruns input"));
            }
            out.extend_from_slice(&data[p..p + mlen]);
            br.seek(p + mlen);
            continue;
        }
        decode_compressed(&mut br, &mut out, mlen, max_backward, &mut dist_rb, &mut dist_idx)?;
        if islast {
            break;
        }
    }
    Ok(out)
}

fn decode_compressed(
    br: &mut Br,
    out: &mut Vec<u8>,
    mlen: usize,
    max_backward: usize,
    dist_rb: &mut [i64; 4],
    dist_idx: &mut usize,
) -> Result<(), CodecError> {
    let mut bl = Block::read(br)?;
    let mut bi = Block::read(br)?;
    let mut bd = Block::read(br)?;
    let npostfix = br.read(2)?;
    let ndirect = br.read(4)? << npostfix;
    let mut cmodes = Vec::with_capacity(bl.ntypes as usize);
    for _ in 0..bl.ntypes {
        cmodes.push(br.read(2)? as u8);
    }
    let ntreesl = read_varlen8(br)? as usize + 1;
    let cmap_l = read_context_map(br, 64 * bl.ntypes as usize, ntreesl)?;
    let ntreesd = read_varlen8(br)? as usize + 1;
    let cmap_d = read_context_map(br, 4 * bd.ntypes as usize, ntreesd)?;
    let mut lit_h = Vec::with_capacity(ntreesl);
    for _ in 0..ntreesl {
        lit_h.push(read_prefix_code(br, 256)?);
    }
    let mut cmd_h = Vec::with_capacity(bi.ntypes as usize);
    for _ in 0..bi.ntypes {
        cmd_h.push(read_prefix_code(br, 704)?);
    }
    let dist_alpha = 16 + ndirect as usize + (48usize << npostfix);
    let mut dist_h = Vec::with_capacity(ntreesd);
    for _ in 0..ntreesd {
        dist_h.push(read_prefix_code(br, dist_alpha)?);
    }
    const GI: [u32; 11] = [0, 0, 0, 0, 8, 8, 0, 16, 8, 16, 16];
    const GC: [u32; 11] = [0, 8, 0, 8, 0, 8, 16, 0, 16, 8, 16];
    let postfix_mask = (1u32 << npostfix) - 1;
    let mut remaining = mlen as i64;
    while remaining > 0 {
        bi.next(br)?;
        let cmd = cmd_h[bi.btype as usize].decode(br)?;
        let group = (cmd >> 6) as usize;
        let ic = (GI[group] + ((cmd >> 3) & 7)) as usize;
        let cc = (GC[group] + (cmd & 7)) as usize;
        let insert_len = INS_BASE[ic] + br.read(INS_EXTRA[ic])?;
        let copy_len = COPY_BASE[cc] + br.read(COPY_EXTRA[cc])?;
        for _ in 0..insert_len {
            bl.next(br)?;
            let n = out.len();
            let p1 = if n >= 1 { out[n - 1] } else { 0 };
            let p2 = if n >= 2 { out[n - 2] } else { 0 };
            let ctx = match cmodes[bl.btype as usize] {
                0 => p1 & 0x3f,
                1 => p1 >> 2,
                2 => LUT0[p1 as usize] | LUT1[p2 as usize],
                _ => (LUT2[p1 as usize] << 3) | LUT2[p2 as usize],
            };
            let tree = cmap_l[bl.btype as usize * 64 + ctx as usize] as usize;
            let lit = lit_h[tree].decode(br)?;
            out.push(lit as u8);
        }
        remaining -= insert_len as i64;
        if remaining < 0 {
            return Err(err("meta-block length mismatch"));
        }
        if remaining == 0 {
            break;
        }
        let dcode: u32;
        let distance: i64;
        let last = |k: usize, rb: &[i64; 4], idx: usize| rb[(idx + 4 - k) & 3];
        if cmd < 128 {
            dcode = 0;
            distance = last(1, dist_rb, *dist_idx);
        } else {
            bd.next(br)?;
            let dctx = if copy_len > 4 { 3 } else { copy_len as usize - 2 };
            let tree = cmap_d[bd.btype as usize * 4 + dctx] as usize;
            dcode = dist_h[tree].decode(br)?;
            distance = if dcode < 16 {
                let (k, delta) = match dcode {
                    0..=3 => (dcode as usize + 1, 0i64),
                    4..=9 => (1, [-1i64, 1, -2, 2, -3, 3][dcode as usize - 4]),
                    _ => (2, [-1i64, 1, -2, 2, -3, 3][dcode as usize - 10]),
                };
                last(k, dist_rb, *dist_idx) + delta
            } else if dcode < 16 + ndirect {
                (dcode - 15) as i64
            } else {
                let x = dcode - ndirect - 16;
                let ndistbits = 1 + (x >> (npostfix + 1));
                let hcode = x >> npostfix;
                let lcode = x & postfix_mask;
                let offset = ((2 + (hcode & 1) as i64) << ndistbits) - 4;
                let extra = br.read(ndistbits)? as i64;
                ((offset + extra) << npostfix) + lcode as i64 + ndirect as i64 + 1
            };
            if distance <= 0 {
                return Err(err("invalid short distance"));
            }
        }
        let max_distance = out.len().min(max_backward) as i64;
        if distance > max_distance {
            let l = copy_len as usize;
            if !(4..=24).contains(&l) {
                return Err(err("invalid dictionary reference length"));
            }
            let word_id = (distance - max_distance - 1) as usize;
            let nb = NDBITS[l];
            let t = word_id >> nb;
            if t >= 121 {
                return Err(err("invalid dictionary transform"));
            }
            let off = DOFFSET[l] as usize + (word_id & ((1 << nb) - 1)) * l;
            let mut word = Vec::with_capacity(l + 16);
            transform_word(&mut word, &DICT[off..off + l], t);
            if word.len() as i64 > remaining {
                return Err(err("meta-block length mismatch"));
            }
            out.extend_from_slice(&word);
            remaining -= word.len() as i64;
        } else {
            if dcode != 0 {
                dist_rb[*dist_idx & 3] = distance;
                *dist_idx += 1;
            }
            if copy_len as i64 > remaining {
                return Err(err("meta-block length mismatch"));
            }
            let d = distance as usize;
            let len = copy_len as usize;
            let start = out.len() - d;
            if d >= len {
                out.extend_from_within(start..start + len);
            } else {
                for k in 0..len {
                    let b = out[start + k];
                    out.push(b);
                }
            }
            remaining -= copy_len as i64;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hx(s: &str) -> Vec<u8> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
    }

    #[test]
    fn small_streams() {
        assert_eq!(decode(&hx("3b")).unwrap(), b"");
        assert_eq!(decode(&hx("0b00806103")).unwrap(), b"a");
        assert_eq!(decode(&hx("deadbeef")).unwrap(), b"");
        assert_eq!(decode(&hx("1b040000a0cbd0d8de040a01488d")).unwrap(), b"hello");
        assert_eq!(decode(&[]).unwrap_err().message, "brotli: unexpected end of input");
        assert_eq!(decode(&hx("11")).unwrap_err().message, "brotli: large-window streams are not supported");
        assert_eq!(decode(&hx("0b0180")).unwrap_err().message, "brotli: uncompressed block overruns input");
    }
}
