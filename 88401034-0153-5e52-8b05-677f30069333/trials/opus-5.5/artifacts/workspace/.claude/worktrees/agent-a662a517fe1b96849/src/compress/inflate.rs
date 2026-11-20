//! DEFLATE decoder (RFC 1951) plus the zlib (RFC 1950) and gzip (RFC 1952)
//! container parsers, replicating the original runtime's custom decoder:
//!
//! * Huffman decoding behaves exactly like zlib's `puff.c` reference decoder
//!   (canonical codes, symbols ordered by (length, value), codes read bit by
//!   bit up to 15 bits). Code tables are never validated: over-subscribed or
//!   incomplete codes are accepted and decode the way puff would decode them.
//!   A fast lookup table is used, but it is derived from the puff algorithm so
//!   the observable behaviour is identical.
//! * No checks for HLIT > 286, HDIST > 30, missing end-of-block code, or
//!   stored-block NLEN.
//! * Decoding stops after the final block; anything after it is ignored.
//! * Errors are `inflate: ...` messages (see `CodecError`).

use super::CodecError;

pub(crate) const E_EOF: &str = "inflate: unexpected end of input";
const E_RESERVED: &str = "inflate: reserved block type";
const E_STORED_TRUNC: &str = "inflate: truncated stored block";
const E_STORED_OVERRUN: &str = "inflate: stored block overruns input";
const E_BAD_CODE: &str = "inflate: invalid Huffman code";
const E_REPEAT_FIRST: &str = "inflate: repeat with no previous length";
const E_CL_OVERRUN: &str = "inflate: code-length overrun";
const E_LIT_SYM: &str = "inflate: invalid literal/length symbol";
const E_DIST_SYM: &str = "inflate: invalid distance symbol";
const E_FAR: &str = "inflate: distance too far back";

const MAXBITS: usize = 15;
const FAST_BITS: u32 = 10;

const LEN_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115,
    131, 163, 195, 227, 258,
];
const LEN_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DIST_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
    2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
const DIST_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13,
    13,
];
const CL_ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

/// LSB-first bit reader with strict end-of-input semantics (a read fails only
/// when the requested bits are not all available).
struct Bits<'a> {
    data: &'a [u8],
    pos: usize, // next byte to load into `buf`
    buf: u64,
    cnt: u32,
}

impl<'a> Bits<'a> {
    fn new(data: &'a [u8]) -> Self {
        Bits { data, pos: 0, buf: 0, cnt: 0 }
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
    fn bits(&mut self, n: u32) -> Result<u32, CodecError> {
        if n == 0 {
            return Ok(0);
        }
        if self.cnt < n {
            self.refill();
            if self.cnt < n {
                return Err(CodecError::new(E_EOF));
            }
        }
        let v = (self.buf & ((1u64 << n) - 1)) as u32;
        self.buf >>= n;
        self.cnt -= n;
        Ok(v)
    }

    /// Up to `n` (<= 32) bits without consuming; returns (bits, available).
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

    /// Drop the bits left in the current byte; return the next byte offset.
    fn align(&mut self) -> usize {
        let drop = self.cnt % 8;
        self.consume(drop);
        self.pos - (self.cnt / 8) as usize
    }

    fn seek(&mut self, byte: usize) {
        self.pos = byte;
        self.buf = 0;
        self.cnt = 0;
    }
}

/// puff-style Huffman decoding table.
struct Huffman {
    count: [u16; MAXBITS + 1],
    symbol: Vec<u16>,
    /// `fast[v]` for the next FAST_BITS stream bits `v`: `(symbol << 4) | length`,
    /// 0 when puff would need more than FAST_BITS bits (or fail).
    fast: Vec<u32>,
}

impl Huffman {
    fn new(lengths: &[u8]) -> Huffman {
        let mut count = [0u16; MAXBITS + 1];
        for &l in lengths {
            count[l as usize] += 1;
        }
        let mut offs = [0usize; MAXBITS + 2];
        for len in 1..=MAXBITS {
            offs[len + 1] = offs[len] + count[len] as usize;
        }
        let total = offs[MAXBITS + 1];
        let mut symbol = vec![0u16; total];
        for (s, &l) in lengths.iter().enumerate() {
            if l != 0 {
                symbol[offs[l as usize]] = s as u16;
                offs[l as usize] += 1;
            }
        }
        let mut h = Huffman { count, symbol, fast: vec![0; 1 << FAST_BITS] };
        for v in 0..(1u32 << FAST_BITS) {
            let (mut code, mut first, mut index) = (0i64, 0i64, 0i64);
            for len in 1..=FAST_BITS as usize {
                code |= ((v >> (len - 1)) & 1) as i64;
                let c = h.count[len] as i64;
                if code - c < first {
                    let sym = h.symbol[(index + (code - first)) as usize] as u32;
                    h.fast[v as usize] = (sym << 4) | len as u32;
                    break;
                }
                index += c;
                first += c;
                first <<= 1;
                code <<= 1;
            }
        }
        h
    }

    #[inline]
    fn decode(&self, br: &mut Bits) -> Result<u32, CodecError> {
        let (v, avail) = br.peek(FAST_BITS);
        let e = self.fast[v as usize];
        let l = e & 15;
        if l != 0 && l <= avail {
            br.consume(l);
            return Ok(e >> 4);
        }
        self.decode_slow(br)
    }

    /// Exact puff `decode()`: one bit at a time, at most 15 bits.
    fn decode_slow(&self, br: &mut Bits) -> Result<u32, CodecError> {
        let (mut code, mut first, mut index) = (0i64, 0i64, 0i64);
        for len in 1..=MAXBITS {
            code |= br.bits(1)? as i64;
            let c = self.count[len] as i64;
            if code - c < first {
                return Ok(self.symbol[(index + (code - first)) as usize] as u32);
            }
            index += c;
            first += c;
            first <<= 1;
            code <<= 1;
        }
        Err(CodecError::new(E_BAD_CODE))
    }
}

fn fixed_tables() -> (Huffman, Huffman) {
    let mut l = [0u8; 288];
    for (i, x) in l.iter_mut().enumerate() {
        *x = match i {
            0..=143 => 8,
            144..=255 => 9,
            256..=279 => 7,
            _ => 8,
        };
    }
    // Only 30 distance codes: codes 30/31 are unassigned (5-bit prefixes
    // 11110/11111 then fail like any incomplete code).
    (Huffman::new(&l), Huffman::new(&[5u8; 30]))
}

fn dynamic_tables(br: &mut Bits) -> Result<(Huffman, Huffman), CodecError> {
    let nlen = br.bits(5)? as usize + 257;
    let ndist = br.bits(5)? as usize + 1;
    let ncode = br.bits(4)? as usize + 4;
    let mut cl = [0u8; 19];
    for &o in CL_ORDER.iter().take(ncode) {
        cl[o] = br.bits(3)? as u8;
    }
    let clh = Huffman::new(&cl);
    let total = nlen + ndist;
    let mut lengths = vec![0u8; total];
    let mut index = 0;
    while index < total {
        let sym = clh.decode(br)?;
        if sym < 16 {
            lengths[index] = sym as u8;
            index += 1;
            continue;
        }
        let (len, rep) = match sym {
            16 => {
                if index == 0 {
                    return Err(CodecError::new(E_REPEAT_FIRST));
                }
                (lengths[index - 1], 3 + br.bits(2)? as usize)
            }
            17 => (0, 3 + br.bits(3)? as usize),
            _ => (0, 11 + br.bits(7)? as usize),
        };
        if index + rep > total {
            return Err(CodecError::new(E_CL_OVERRUN));
        }
        for l in &mut lengths[index..index + rep] {
            *l = len;
        }
        index += rep;
    }
    Ok((Huffman::new(&lengths[..nlen]), Huffman::new(&lengths[nlen..])))
}

/// Decode a raw DEFLATE stream. `window` is an optional preset dictionary
/// (back-references may reach into it; it is not part of the output).
/// Returns the output and the number of input bytes consumed (through the
/// byte containing the end of the final block).
pub fn inflate_with_window(data: &[u8], window: &[u8]) -> Result<(Vec<u8>, usize), CodecError> {
    let mut br = Bits::new(data);
    let mut out: Vec<u8> = Vec::with_capacity(window.len() + data.len().saturating_mul(3).min(1 << 24));
    out.extend_from_slice(window);
    let mut fixed: Option<(Huffman, Huffman)> = None;
    loop {
        let last = br.bits(1)? == 1;
        let btype = br.bits(2)?;
        match btype {
            0 => {
                let p = br.align();
                if p + 4 > data.len() {
                    return Err(CodecError::new(E_STORED_TRUNC));
                }
                let len = u16::from_le_bytes([data[p], data[p + 1]]) as usize;
                // NLEN (data[p+2..p+4]) is not checked by the original.
                if p + 4 + len > data.len() {
                    return Err(CodecError::new(E_STORED_OVERRUN));
                }
                out.extend_from_slice(&data[p + 4..p + 4 + len]);
                br.seek(p + 4 + len);
            }
            1 | 2 => {
                let dynamic;
                let (lit, dist) = if btype == 1 {
                    if fixed.is_none() {
                        fixed = Some(fixed_tables());
                    }
                    let f = fixed.as_ref().unwrap();
                    (&f.0, &f.1)
                } else {
                    dynamic = dynamic_tables(&mut br)?;
                    (&dynamic.0, &dynamic.1)
                };
                loop {
                    let sym = lit.decode(&mut br)?;
                    if sym < 256 {
                        out.push(sym as u8);
                        continue;
                    }
                    if sym == 256 {
                        break;
                    }
                    let li = (sym - 257) as usize;
                    if li >= 29 {
                        return Err(CodecError::new(E_LIT_SYM));
                    }
                    let len = LEN_BASE[li] as usize + br.bits(LEN_EXTRA[li] as u32)? as usize;
                    let ds = dist.decode(&mut br)? as usize;
                    if ds >= 30 {
                        return Err(CodecError::new(E_DIST_SYM));
                    }
                    let d = DIST_BASE[ds] as usize + br.bits(DIST_EXTRA[ds] as u32)? as usize;
                    if d > out.len() {
                        return Err(CodecError::new(E_FAR));
                    }
                    let start = out.len() - d;
                    if d >= len {
                        out.extend_from_within(start..start + len);
                    } else {
                        for k in 0..len {
                            let b = out[start + k];
                            out.push(b);
                        }
                    }
                }
            }
            _ => return Err(CodecError::new(E_RESERVED)),
        }
        if last {
            break;
        }
    }
    let consumed = br.align();
    if !window.is_empty() {
        out.drain(..window.len());
    }
    Ok((out, consumed))
}

/// `zlib.inflateRawSync`.
pub fn inflate_raw(data: &[u8], dictionary: Option<&[u8]>) -> Result<Vec<u8>, CodecError> {
    inflate_with_window(data, dictionary.unwrap_or(&[])).map(|r| r.0)
}

/// `zlib.inflateSync`: the original requires >= 6 bytes, checks only the
/// compression-method nibble, never skips a DICTID (FDICT is ignored), and
/// never verifies FCHECK or the Adler-32 trailer.
pub fn zlib_decode(data: &[u8], dictionary: Option<&[u8]>) -> Result<Vec<u8>, CodecError> {
    if data.len() < 6 {
        return Err(CodecError::new("zlib: input too short"));
    }
    if data[0] & 0x0f != 8 {
        return Err(CodecError::new("zlib: unsupported compression method"));
    }
    let mut body = &data[2..];
    if let Some(d) = dictionary {
        // Extension (the original ignores `dictionary` entirely): honour a
        // preset dictionary when one is explicitly supplied.
        if data[1] & 0x20 != 0 && body.len() >= 4 {
            body = &body[4..];
        }
        return inflate_with_window(body, d).map(|r| r.0);
    }
    inflate_with_window(body, &[]).map(|r| r.0)
}

/// `zlib.gunzipSync` / `zlib.unzipSync`: only the first member is decoded,
/// the 8-byte trailer is excluded from the deflate data and never checked,
/// FHCRC is skipped unchecked, reserved flag bits are ignored.
pub fn gzip_decode(data: &[u8]) -> Result<Vec<u8>, CodecError> {
    if data.len() < 18 || data[0] != 0x1f || data[1] != 0x8b {
        return Err(CodecError::new("gzip: bad magic"));
    }
    if data[2] != 8 {
        return Err(CodecError::new("gzip: unsupported compression method"));
    }
    let trunc = || CodecError::new("gzip: truncated");
    let flags = data[3];
    let end = data.len() - 8;
    let mut p = 10usize;
    if flags & 4 != 0 {
        if p + 2 > end {
            return Err(trunc());
        }
        let xlen = u16::from_le_bytes([data[p], data[p + 1]]) as usize;
        p += 2;
        if p + xlen > end {
            return Err(trunc());
        }
        p += xlen;
    }
    for bit in [8u8, 16u8] {
        if flags & bit != 0 {
            match data[p..end].iter().position(|&b| b == 0) {
                Some(i) => p += i + 1,
                None => return Err(trunc()),
            }
        }
    }
    if flags & 2 != 0 {
        if p + 2 > end {
            return Err(trunc());
        }
        p += 2;
    }
    inflate_with_window(&data[p..end], &[]).map(|r| r.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hx(s: &str) -> Vec<u8> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
    }

    #[test]
    fn basic_streams() {
        assert_eq!(inflate_raw(&hx("cb48cdc9c95728cf2fca490100"), None).unwrap(), b"hello world");
        assert_eq!(zlib_decode(&hx("789c030000000001"), None).unwrap(), b"");
        assert_eq!(
            gzip_decode(&hx("1f8b08000000000000ffcb48cdc9c95728cf2fca49010085114a0d0b000000")).unwrap(),
            b"hello world"
        );
    }

    #[test]
    fn error_messages() {
        let m = |r: Result<Vec<u8>, CodecError>| r.unwrap_err().message;
        assert_eq!(m(zlib_decode(&[1, 2, 3], None)), "zlib: input too short");
        assert_eq!(m(zlib_decode(&hx("7a9c03000000"), None)), "zlib: unsupported compression method");
        assert_eq!(m(inflate_raw(&[], None)), E_EOF);
        assert_eq!(m(inflate_raw(&[0x07], None)), E_RESERVED);
        assert_eq!(m(inflate_raw(&[0x00], None)), E_STORED_TRUNC);
        assert_eq!(m(inflate_raw(&hx("010500fbff"), None)), E_STORED_OVERRUN);
        assert_eq!(m(gzip_decode(&[])), "gzip: bad magic");
    }
}
