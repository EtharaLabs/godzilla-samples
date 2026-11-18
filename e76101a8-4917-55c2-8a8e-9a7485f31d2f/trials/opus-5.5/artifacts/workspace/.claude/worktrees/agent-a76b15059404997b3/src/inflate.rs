//! Raw deflate (RFC 1951) decoding, with zlib (RFC 1950) and gzip (RFC 1952) wrappers.

#[derive(Debug, Clone, PartialEq)]
pub enum InflateError {
    /// The data is not a deflate stream ("corrupt deflate stream").
    Corrupt,
    /// The input ended before the final block did; what was decoded so far is kept.
    Truncated,
    /// The output would pass the cap given.
    TooBig,
}

pub struct Inflated {
    pub data: Vec<u8>,
    /// Bytes of input the stream took, up to the end of its final block.
    pub consumed: usize,
}

struct Bits<'a> {
    s: &'a [u8],
    pos: usize, // byte position
    bit: u32,   // bit buffer
    n: u32,     // bits in buffer
}

impl<'a> Bits<'a> {
    fn need(&mut self, k: u32) -> Result<(), InflateError> {
        while self.n < k {
            if self.pos >= self.s.len() {
                return Err(InflateError::Truncated);
            }
            self.bit |= (self.s[self.pos] as u32) << self.n;
            self.pos += 1;
            self.n += 8;
        }
        Ok(())
    }
    fn get(&mut self, k: u32) -> Result<u32, InflateError> {
        if k == 0 {
            return Ok(0);
        }
        self.need(k)?;
        let v = self.bit & ((1u32 << k) - 1);
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
    fn new(lengths: &[u8]) -> Result<Huff, InflateError> {
        let mut counts = [0u16; 16];
        for &l in lengths {
            counts[l as usize] += 1;
        }
        counts[0] = 0;
        // over-subscribed sets are corrupt; incomplete ones are allowed (single-code trees)
        let mut left: i32 = 1;
        for len in 1..16 {
            left <<= 1;
            left -= counts[len] as i32;
            if left < 0 {
                return Err(InflateError::Corrupt);
            }
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
    fn decode(&self, b: &mut Bits) -> Result<u16, InflateError> {
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
        Err(InflateError::Corrupt)
    }
}

const LBASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEXT: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
const DBASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289,
    16385, 24577,
];
const DEXT: [u8; 30] = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

/// Decodes a raw deflate stream. On `Truncated`, `partial` holds what was decoded.
pub fn inflate_raw(input: &[u8], cap: usize, partial: &mut Vec<u8>) -> Result<Inflated, InflateError> {
    let mut b = Bits { s: input, pos: 0, bit: 0, n: 0 };
    let out = partial;
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
                    return Err(InflateError::Corrupt);
                }
                // the bit buffer is empty after two whole 16-bit reads from an aligned spot
                for _ in 0..len {
                    if b.n >= 8 {
                        let v = b.get(8)? as u8;
                        out.push(v);
                    } else {
                        if b.pos >= b.s.len() {
                            return Err(InflateError::Truncated);
                        }
                        out.push(b.s[b.pos]);
                        b.pos += 1;
                    }
                    if out.len() > cap {
                        return Err(InflateError::TooBig);
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
                    (Huff::new(&l)?, Huff::new(&[5u8; 30])?)
                } else {
                    let hlit = b.get(5)? as usize + 257;
                    let hdist = b.get(5)? as usize + 1;
                    let hclen = b.get(4)? as usize + 4;
                    if hlit > 286 || hdist > 30 {
                        return Err(InflateError::Corrupt);
                    }
                    const ORD: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
                    let mut cl = [0u8; 19];
                    for &o in ORD.iter().take(hclen) {
                        cl[o] = b.get(3)? as u8;
                    }
                    let ch = Huff::new(&cl)?;
                    let mut lens = vec![0u8; hlit + hdist];
                    let mut i = 0;
                    while i < hlit + hdist {
                        let sym = ch.decode(&mut b)?;
                        match sym {
                            0..=15 => {
                                lens[i] = sym as u8;
                                i += 1;
                            }
                            16 => {
                                if i == 0 {
                                    return Err(InflateError::Corrupt);
                                }
                                let prev = lens[i - 1];
                                let r = 3 + b.get(2)? as usize;
                                if i + r > lens.len() {
                                    return Err(InflateError::Corrupt);
                                }
                                for _ in 0..r {
                                    lens[i] = prev;
                                    i += 1;
                                }
                            }
                            17 | 18 => {
                                let r = if sym == 17 { 3 + b.get(3)? as usize } else { 11 + b.get(7)? as usize };
                                if i + r > lens.len() {
                                    return Err(InflateError::Corrupt);
                                }
                                i += r;
                            }
                            _ => return Err(InflateError::Corrupt),
                        }
                    }
                    if lens[256] == 0 {
                        return Err(InflateError::Corrupt);
                    }
                    (Huff::new(&lens[..hlit])?, Huff::new(&lens[hlit..])?)
                };
                loop {
                    let sym = lit.decode(&mut b)? as usize;
                    if sym < 256 {
                        out.push(sym as u8);
                        if out.len() > cap {
                            return Err(InflateError::TooBig);
                        }
                    } else if sym == 256 {
                        break;
                    } else {
                        let si = sym - 257;
                        if si >= 29 {
                            return Err(InflateError::Corrupt);
                        }
                        let len = LBASE[si] as usize + b.get(LEXT[si] as u32)? as usize;
                        let ds = dist.decode(&mut b)? as usize;
                        if ds >= 30 {
                            return Err(InflateError::Corrupt);
                        }
                        let d = DBASE[ds] as usize + b.get(DEXT[ds] as u32)? as usize;
                        if d > out.len() {
                            return Err(InflateError::Corrupt);
                        }
                        let start = out.len() - d;
                        for k in 0..len {
                            let c = out[start + k];
                            out.push(c);
                        }
                        if out.len() > cap {
                            return Err(InflateError::TooBig);
                        }
                    }
                }
            }
            _ => return Err(InflateError::Corrupt),
        }
        if last == 1 {
            break;
        }
    }
    // bytes consumed: whole bytes read less those still buffered
    let consumed = b.pos - (b.n / 8) as usize;
    Ok(Inflated { data: std::mem::take(out), consumed })
}

pub fn inflate(input: &[u8], cap: usize) -> Result<Inflated, InflateError> {
    let mut partial = Vec::new();
    inflate_raw(input, cap, &mut partial)
}

pub fn adler32(data: &[u8]) -> u32 {
    let mut a: u32 = 1;
    let mut b: u32 = 0;
    for chunk in data.chunks(5552) {
        for &x in chunk {
            a += x as u32;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    (b << 16) | a
}

/// Decodes a zlib stream (header, deflate, Adler-32).
pub fn zlib_decode(input: &[u8], cap: usize) -> Result<Vec<u8>, InflateError> {
    if input.len() < 2 {
        return Err(InflateError::Truncated);
    }
    let cmf = input[0];
    let flg = input[1];
    if cmf & 0x0f != 8 || ((cmf as u16) << 8 | flg as u16) % 31 != 0 || flg & 0x20 != 0 {
        return Err(InflateError::Corrupt);
    }
    let r = inflate(&input[2..], cap)?;
    let end = 2 + r.consumed;
    if input.len() < end + 4 {
        return Err(InflateError::Truncated);
    }
    let want = u32::from_be_bytes(input[end..end + 4].try_into().unwrap());
    if want != adler32(&r.data) {
        return Err(InflateError::Corrupt);
    }
    Ok(r.data)
}

static CRC_TABLE: std::sync::OnceLock<[u32; 256]> = std::sync::OnceLock::new();

pub fn crc32(data: &[u8]) -> u32 {
    crc32_update(0, data)
}

pub fn crc32_update(crc: u32, data: &[u8]) -> u32 {
    let t = CRC_TABLE.get_or_init(|| {
        let mut t = [0u32; 256];
        for (i, x) in t.iter_mut().enumerate() {
            let mut c = i as u32;
            for _ in 0..8 {
                c = if c & 1 != 0 { 0xEDB88320 ^ (c >> 1) } else { c >> 1 };
            }
            *x = c;
        }
        t
    });
    let mut c = !crc;
    for &b in data {
        c = t[((c ^ b as u32) & 0xff) as usize] ^ (c >> 8);
    }
    !c
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stored_and_fixed() {
        // zlib of "hello" as Python's zlib.compress writes it
        let z = [0x78, 0x9c, 0xcb, 0x48, 0xcd, 0xc9, 0xc9, 0x07, 0x00, 0x06, 0x2c, 0x02, 0x15];
        assert_eq!(zlib_decode(&z, 1 << 20).unwrap(), b"hello");
        assert_eq!(crc32(b"hello"), 0x3610a686);
    }
}
