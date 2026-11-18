//! Raw deflate (RFC 1951) decoding as the original reader's decoder (miniz_oxide, streaming)
//! does it: Huffman codes must be complete (or use one symbol at most), a block need not have
//! an end-of-block code, and a match reaching back past the start reads the zeroed window.

pub enum Error {
    /// Not a deflate stream the decoder takes.
    Corrupt,
    /// The input ended before the final block did.
    Truncated,
    /// The output would pass the cap.
    TooBig,
}

pub struct Inflated {
    pub data: Vec<u8>,
    /// Bytes of input taken, up to the end of the final block.
    pub consumed: usize,
}

struct Bits<'a> {
    s: &'a [u8],
    pos: usize,
    bit: u64,
    n: u32,
}

impl<'a> Bits<'a> {
    fn need(&mut self, k: u32) -> Result<(), Error> {
        while self.n < k {
            if self.pos >= self.s.len() {
                return Err(Error::Truncated);
            }
            self.bit |= (self.s[self.pos] as u64) << self.n;
            self.pos += 1;
            self.n += 8;
        }
        Ok(())
    }
    fn get(&mut self, k: u32) -> Result<u32, Error> {
        if k == 0 {
            return Ok(0);
        }
        self.need(k)?;
        let v = (self.bit & ((1u64 << k) - 1)) as u32;
        self.bit >>= k;
        self.n -= k;
        Ok(v)
    }
    fn align(&mut self) {
        let r = self.n % 8;
        self.bit >>= r;
        self.n -= r;
    }
}

struct Huff {
    counts: [u16; 16],
    symbols: Vec<u16>,
}

impl Huff {
    /// A canonical code from its lengths: complete, or with one symbol at most.
    fn new(lengths: &[u8]) -> Result<Huff, Error> {
        let mut counts = [0u16; 16];
        for &l in lengths {
            counts[l as usize] += 1;
        }
        counts[0] = 0;
        let used: u32 = counts.iter().map(|c| *c as u32).sum();
        let mut total: u64 = 0;
        for len in 1..16 {
            total += (counts[len] as u64) << (16 - len);
        }
        if total != 65_536 && used > 1 {
            return Err(Error::Corrupt);
        }
        let mut offs = [0u16; 16];
        for len in 1..15 {
            offs[len + 1] = offs[len] + counts[len];
        }
        let mut symbols = vec![0u16; lengths.len()];
        for (sym, &l) in lengths.iter().enumerate() {
            if l != 0 {
                symbols[offs[l as usize] as usize] = sym as u16;
                offs[l as usize] += 1;
            }
        }
        Ok(Huff { counts, symbols })
    }
    fn decode(&self, b: &mut Bits) -> Result<u16, Error> {
        let mut code: i32 = 0;
        let mut first: i32 = 0;
        let mut index: i32 = 0;
        for len in 1..16 {
            code |= b.get(1)? as i32;
            let count = self.counts[len] as i32;
            if code - count < first {
                return Ok(self.symbols[(index + (code - first)) as usize]);
            }
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        Err(Error::Corrupt)
    }
}

const LBASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEXT: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
const DBASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289,
    16385, 24577,
];
const DEXT: [u8; 30] = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

/// Decodes a raw deflate stream, its output at most `cap` bytes.
pub fn inflate(input: &[u8], cap: usize) -> Result<Inflated, Error> {
    let mut out = Vec::new();
    let consumed = inflate_into(input, cap, &mut out)?;
    Ok(Inflated { data: out, consumed })
}

/// Decodes what it can of a raw deflate stream: on `Truncated`, `out` holds what was decoded
/// before the input ended. Gives the bytes of input taken.
pub fn inflate_into(input: &[u8], cap: usize, out: &mut Vec<u8>) -> Result<usize, Error> {
    let mut b = Bits { s: input, pos: 0, bit: 0, n: 0 };
    out.clear();
    loop {
        let last = b.get(1)?;
        let typ = b.get(2)?;
        match typ {
            0 => {
                b.align();
                let len = b.get(16)? as usize;
                let nlen = b.get(16)? as usize;
                if len != (!nlen & 0xffff) {
                    return Err(Error::Corrupt);
                }
                for _ in 0..len {
                    let v = if b.n >= 8 {
                        b.get(8)? as u8
                    } else {
                        if b.pos >= b.s.len() {
                            return Err(Error::Truncated);
                        }
                        b.pos += 1;
                        b.s[b.pos - 1]
                    };
                    out.push(v);
                    if out.len() > cap {
                        return Err(Error::TooBig);
                    }
                }
            }
            1 | 2 => {
                let (lit, dist) = if typ == 1 {
                    let mut l = [0u8; 288];
                    for (i, x) in l.iter_mut().enumerate() {
                        *x = if i < 144 {
                            8
                        } else if i < 256 {
                            9
                        } else if i < 280 {
                            7
                        } else {
                            8
                        };
                    }
                    (Huff::new(&l)?, Huff::new(&[5u8; 32])?)
                } else {
                    let hlit = b.get(5)? as usize + 257;
                    let hdist = b.get(5)? as usize + 1;
                    let hclen = b.get(4)? as usize + 4;
                    if hlit > 286 || hdist > 30 {
                        return Err(Error::Corrupt);
                    }
                    const ORD: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
                    let mut cl = [0u8; 19];
                    for &o in ORD.iter().take(hclen) {
                        cl[o] = b.get(3)? as u8;
                    }
                    let ch = Huff::new(&cl)?;
                    let total = hlit + hdist;
                    let mut lens = vec![0u8; total + 138];
                    let mut i = 0;
                    while i < total {
                        let sym = ch.decode(&mut b)?;
                        match sym {
                            0..=15 => {
                                lens[i] = sym as u8;
                                i += 1;
                            }
                            16 => {
                                if i == 0 {
                                    return Err(Error::Corrupt);
                                }
                                let prev = lens[i - 1];
                                let r = 3 + b.get(2)? as usize;
                                for _ in 0..r {
                                    lens[i] = prev;
                                    i += 1;
                                }
                            }
                            17 | 18 => {
                                let r = if sym == 17 { 3 + b.get(3)? as usize } else { 11 + b.get(7)? as usize };
                                i += r;
                            }
                            _ => return Err(Error::Corrupt),
                        }
                    }
                    if i != total {
                        return Err(Error::Corrupt);
                    }
                    let d = Huff::new(&lens[hlit..total])?;
                    let l = Huff::new(&lens[..hlit])?;
                    (l, d)
                };
                loop {
                    let sym = lit.decode(&mut b)? as usize;
                    if sym < 256 {
                        out.push(sym as u8);
                        if out.len() > cap {
                            return Err(Error::TooBig);
                        }
                    } else if sym == 256 {
                        break;
                    } else {
                        let si = sym - 257;
                        if si >= 29 {
                            return Err(Error::Corrupt);
                        }
                        let len = LBASE[si] as usize + b.get(LEXT[si] as u32)? as usize;
                        let ds = dist.decode(&mut b)? as usize;
                        if ds >= 30 {
                            return Err(Error::Corrupt);
                        }
                        let d = DBASE[ds] as usize + b.get(DEXT[ds] as u32)? as usize;
                        // before the start, the window is zeros
                        for _ in 0..len {
                            let p = out.len();
                            let c = if d > p { 0 } else { out[p - d] };
                            out.push(c);
                        }
                        if out.len() > cap {
                            return Err(Error::TooBig);
                        }
                    }
                }
            }
            _ => return Err(Error::Corrupt),
        }
        if last == 1 {
            break;
        }
    }
    Ok(b.pos - (b.n / 8) as usize)
}
