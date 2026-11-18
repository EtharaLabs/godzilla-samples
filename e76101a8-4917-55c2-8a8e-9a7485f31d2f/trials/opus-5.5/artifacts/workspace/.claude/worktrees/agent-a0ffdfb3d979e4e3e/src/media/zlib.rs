//! A zlib stream decoded as the png crate's decompressor (fdeflate) decodes one: its errors by
//! name, and how much output was known at given points of the input, so that a PNG's chunks can
//! be replayed in the order the png crate meets them.

/// The ways fdeflate finds a stream corrupt, as its `Debug` names them.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ZErr {
    BadZlibHeader,
    InsufficientInput,
    InvalidBlockType,
    InvalidUncompressedBlockLength,
    InvalidHlit,
    InvalidHdist,
    InvalidCodeLengthRepeat,
    BadCodeLengthHuffmanTree,
    BadLiteralLengthHuffmanTree,
    BadDistanceHuffmanTree,
    InvalidLiteralLengthCode,
    InvalidDistanceCode,
    DistanceTooFarBack,
}

impl ZErr {
    pub fn name(self) -> &'static str {
        match self {
            ZErr::BadZlibHeader => "BadZlibHeader",
            ZErr::InsufficientInput => "InsufficientInput",
            ZErr::InvalidBlockType => "InvalidBlockType",
            ZErr::InvalidUncompressedBlockLength => "InvalidUncompressedBlockLength",
            ZErr::InvalidHlit => "InvalidHlit",
            ZErr::InvalidHdist => "InvalidHdist",
            ZErr::InvalidCodeLengthRepeat => "InvalidCodeLengthRepeat",
            ZErr::BadCodeLengthHuffmanTree => "BadCodeLengthHuffmanTree",
            ZErr::BadLiteralLengthHuffmanTree => "BadLiteralLengthHuffmanTree",
            ZErr::BadDistanceHuffmanTree => "BadDistanceHuffmanTree",
            ZErr::InvalidLiteralLengthCode => "InvalidLiteralLengthCode",
            ZErr::InvalidDistanceCode => "InvalidDistanceCode",
            ZErr::DistanceTooFarBack => "DistanceTooFarBack",
        }
    }
}

/// How the stream ended, and where.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum End {
    /// The final block and the checksum were read: the stream took this many bytes.
    Done(usize),
    /// Corrupt, found once this many bytes were in; and whether only after the output had
    /// reached the cap (the png crate then reads the rows first).
    Error(ZErr, usize, bool),
    /// The input ran out first.
    Short,
}

pub struct Decoded {
    pub out: Vec<u8>,
    /// For each point given, how many output bytes were known once that much input was in.
    pub known: Vec<usize>,
    pub end: End,
}

enum Stop {
    Short,
    Err(ZErr),
}

struct Bits<'a> {
    d: &'a [u8],
    /// next byte to load
    next: usize,
    buf: u64,
    n: u32,
    /// bits consumed in all
    used: usize,
}

impl<'a> Bits<'a> {
    #[inline]
    fn fill(&mut self) {
        while self.n <= 56 && self.next < self.d.len() {
            self.buf |= (self.d[self.next] as u64) << self.n;
            self.next += 1;
            self.n += 8;
        }
    }
    #[inline]
    fn bits(&mut self, k: u32) -> Result<u32, Stop> {
        if k == 0 {
            return Ok(0);
        }
        if self.n < k {
            self.fill();
            if self.n < k {
                return Err(Stop::Short);
            }
        }
        let v = (self.buf & ((1u64 << k) - 1)) as u32;
        self.buf >>= k;
        self.n -= k;
        self.used += k as usize;
        Ok(v)
    }
    #[inline]
    fn peek(&mut self, k: u32) -> (u32, u32) {
        if self.n < k {
            self.fill();
        }
        let have = self.n.min(k);
        ((self.buf & ((1u64 << k) - 1)) as u32, have)
    }
    #[inline]
    fn drop_bits(&mut self, k: u32) {
        self.buf >>= k;
        self.n -= k;
        self.used += k as usize;
    }
    /// Input bytes needed to have read everything up to here.
    #[inline]
    fn need(&self) -> usize {
        (self.used + 7) / 8
    }
    fn align(&mut self) {
        let r = (self.used % 8) as u32;
        if r != 0 {
            self.drop_bits(8 - r);
        }
    }
}

const FAST: u32 = 10;

/// A canonical Huffman code, with a table for its short codes.
struct Huff {
    count: [u16; 16],
    symbols: Vec<u16>,
    /// for each FAST-bit (bit-reversed) value: symbol << 4 | length, or 0 when longer or none
    fast: Vec<u16>,
}

enum Build {
    Ok(Huff),
    /// No symbol has a code.
    Empty,
    Bad,
}

/// Builds a code from code lengths: complete, or (`single`) one code of length 1.
fn build(lengths: &[u8], single: bool) -> Build {
    let mut count = [0u16; 16];
    for &l in lengths {
        count[l as usize] += 1;
    }
    count[0] = 0;
    let used: u32 = count[1..].iter().map(|&c| c as u32).sum();
    if used == 0 {
        return Build::Empty;
    }
    let mut left: i32 = 1;
    for len in 1..16 {
        left <<= 1;
        left -= count[len] as i32;
        if left < 0 {
            return Build::Bad;
        }
    }
    if left > 0 && !(single && used == 1 && count[1] == 1) {
        return Build::Bad;
    }
    let mut offs = [0u16; 16];
    for len in 1..15 {
        offs[len + 1] = offs[len] + count[len];
    }
    let mut symbols = vec![0u16; used as usize];
    for (s, &l) in lengths.iter().enumerate() {
        if l != 0 {
            symbols[offs[l as usize] as usize] = s as u16;
            offs[l as usize] += 1;
        }
    }
    // the fast table: canonical codes, bit-reversed
    let mut fast = vec![0u16; 1 << FAST];
    let mut code: u32 = 0;
    let mut idx = 0usize;
    for len in 1..16u32 {
        for _ in 0..count[len as usize] {
            if len <= FAST {
                let rev = code.reverse_bits() >> (32 - len);
                let sym = symbols[idx] as u32;
                let mut f = rev;
                while f < (1 << FAST) {
                    fast[f as usize] = (sym << 4 | len) as u16;
                    f += 1 << len;
                }
            }
            code += 1;
            idx += 1;
        }
        code <<= 1;
    }
    Build::Ok(Huff { count, symbols, fast })
}

/// Decodes one symbol; None for a code the (incomplete) tree has no symbol for.
#[inline]
fn decode_sym(b: &mut Bits, h: &Huff) -> Result<Option<u16>, Stop> {
    let (v, have) = b.peek(FAST);
    let e = h.fast[(v & ((1 << FAST) - 1)) as usize];
    if e != 0 {
        let len = (e & 15) as u32;
        if len <= have {
            b.drop_bits(len);
            return Ok(Some(e >> 4));
        }
    }
    // the slow way, a bit at a time
    let mut code: i32 = 0;
    let mut first: i32 = 0;
    let mut index: i32 = 0;
    let save = (b.buf, b.n, b.next, b.used);
    for len in 1..16 {
        let bit = match b.bits(1) {
            Ok(x) => x,
            Err(s) => {
                (b.buf, b.n, b.next, b.used) = save;
                return Err(s);
            }
        };
        code |= bit as i32;
        let count = h.count[len] as i32;
        if code - count < first {
            return Ok(Some(h.symbols[(index + (code - first)) as usize]));
        }
        index += count;
        first += count;
        first <<= 1;
        code <<= 1;
    }
    Ok(None)
}

const LBASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEXT: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
const DBASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
const DEXT: [u8; 30] = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

/// Where the output stood as the input points went by.
struct Marks<'a> {
    points: &'a [usize],
    known: Vec<usize>,
    /// the output the png crate wants (the image's data): past it, fdeflate stops before any
    /// symbol that makes output, until the rows are read
    cap: usize,
    /// set once it stopped so
    capped: bool,
}

impl<'a> Marks<'a> {
    /// A symbol that needed `need` input bytes is about to add to `len` bytes of output.
    #[inline]
    fn before(&mut self, need: usize, len: usize) {
        if len >= self.cap {
            self.capped = true;
        }
        while self.known.len() < self.points.len() && self.points[self.known.len()] < need {
            self.known.push(len);
        }
    }
    /// A symbol that makes output, or ends a block in its stead, is next.
    #[inline]
    fn output_next(&mut self, len: usize) {
        if len >= self.cap {
            self.capped = true;
        }
    }
}

/// Decodes a zlib stream from the data at hand; `points` (ascending input lengths) get the
/// output known once that much input was in; `cap` is the output the reader wants.
pub fn decode(input: &[u8], points: &[usize], cap: usize) -> Decoded {
    let mut out: Vec<u8> = Vec::new();
    let mut marks = Marks { points, known: Vec::with_capacity(points.len()), cap, capped: false };
    let end = match run(input, &mut out, &mut marks) {
        Ok(n) => End::Done(n),
        Err((Stop::Short, _)) => End::Short,
        Err((Stop::Err(e), at)) => End::Error(e, at, marks.capped),
    };
    let mut known = marks.known;
    while known.len() < points.len() {
        known.push(out.len());
    }
    Decoded { out, known, end }
}

fn run(input: &[u8], out: &mut Vec<u8>, marks: &mut Marks) -> Result<usize, (Stop, usize)> {
    let mut b = Bits { d: input, next: 0, buf: 0, n: 0, used: 0 };
    macro_rules! t {
        ($e:expr) => {
            match $e {
                Ok(v) => v,
                Err(s) => return Err((s, b.need())),
            }
        };
    }
    macro_rules! fail {
        ($e:expr) => {
            return Err((Stop::Err($e), b.need()))
        };
    }
    // the zlib header
    if input.len() < 2 {
        return Err((Stop::Short, input.len()));
    }
    let (cmf, flg) = (input[0], input[1]);
    if cmf & 0x0f != 8 || cmf >> 4 > 7 || flg & 0x20 != 0 || ((cmf as u16) << 8 | flg as u16) % 31 != 0 {
        return Err((Stop::Err(ZErr::BadZlibHeader), 2));
    }
    t!(b.bits(16));
    let mut fixed_lit: Option<Huff> = None;
    let mut fixed_dist: Option<Huff> = None;
    loop {
        let last = t!(b.bits(1));
        let kind = t!(b.bits(2));
        match kind {
            0 => {
                b.align();
                let len = t!(b.bits(16));
                let nlen = t!(b.bits(16));
                if len != !nlen & 0xffff {
                    fail!(ZErr::InvalidUncompressedBlockLength);
                }
                for _ in 0..len {
                    marks.output_next(out.len());
                    let v = t!(b.bits(8));
                    marks.before(b.need(), out.len());
                    out.push(v as u8);
                }
            }
            1 | 2 => {
                let dynamic;
                let (lit, dist): (&Huff, Option<&Huff>) = if kind == 1 {
                    if fixed_lit.is_none() {
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
                        fixed_lit = match build(&l, false) {
                            Build::Ok(h) => Some(h),
                            _ => None,
                        };
                        fixed_dist = match build(&[5u8; 32], false) {
                            Build::Ok(h) => Some(h),
                            _ => None,
                        };
                    }
                    (fixed_lit.as_ref().unwrap(), fixed_dist.as_ref())
                } else {
                    let hlit = t!(b.bits(5)) as usize + 257;
                    let hdist = t!(b.bits(5)) as usize + 1;
                    let hclen = t!(b.bits(4)) as usize + 4;
                    if hlit > 286 {
                        fail!(ZErr::InvalidHlit);
                    }
                    if hdist > 30 {
                        fail!(ZErr::InvalidHdist);
                    }
                    const ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
                    let mut cl = [0u8; 19];
                    for &o in ORDER.iter().take(hclen) {
                        cl[o] = t!(b.bits(3)) as u8;
                    }
                    let clh = match build(&cl, false) {
                        Build::Ok(h) => h,
                        _ => fail!(ZErr::BadCodeLengthHuffmanTree),
                    };
                    let total = hlit + hdist;
                    let mut lens = vec![0u8; total];
                    let mut i = 0;
                    while i < total {
                        let sym = match t!(decode_sym(&mut b, &clh)) {
                            Some(s) => s,
                            None => fail!(ZErr::BadCodeLengthHuffmanTree),
                        };
                        match sym {
                            0..=15 => {
                                lens[i] = sym as u8;
                                i += 1;
                            }
                            16 => {
                                if i == 0 {
                                    fail!(ZErr::InvalidCodeLengthRepeat);
                                }
                                let r = 3 + t!(b.bits(2)) as usize;
                                if i + r > total {
                                    fail!(ZErr::InvalidCodeLengthRepeat);
                                }
                                let prev = lens[i - 1];
                                for _ in 0..r {
                                    lens[i] = prev;
                                    i += 1;
                                }
                            }
                            17 | 18 => {
                                let r = if sym == 17 { 3 + t!(b.bits(3)) as usize } else { 11 + t!(b.bits(7)) as usize };
                                if i + r > total {
                                    fail!(ZErr::InvalidCodeLengthRepeat);
                                }
                                i += r;
                            }
                            _ => fail!(ZErr::BadCodeLengthHuffmanTree),
                        }
                    }
                    if lens[256] == 0 {
                        fail!(ZErr::BadLiteralLengthHuffmanTree);
                    }
                    // fdeflate names a bad literal/length code so
                    let lit = match build(&lens[..hlit], false) {
                        Build::Ok(h) => h,
                        _ => fail!(ZErr::BadCodeLengthHuffmanTree),
                    };
                    let dist = match build(&lens[hlit..], true) {
                        Build::Ok(h) => Some(h),
                        Build::Empty => None,
                        Build::Bad => fail!(ZErr::BadDistanceHuffmanTree),
                    };
                    dynamic = (lit, dist);
                    (&dynamic.0, dynamic.1.as_ref())
                };
                loop {
                    let sym = match t!(decode_sym(&mut b, lit)) {
                        Some(s) => s,
                        None => fail!(ZErr::InvalidLiteralLengthCode),
                    };
                    if sym != 256 {
                        marks.output_next(out.len());
                    }
                    if sym < 256 {
                        marks.before(b.need(), out.len());
                        out.push(sym as u8);
                    } else if sym == 256 || sym >= 286 {
                        // fdeflate's fixed code ends the block at 286 and 287 too
                        break;
                    } else {
                        let li = (sym - 257) as usize;
                        let len = LBASE[li] as usize + t!(b.bits(LEXT[li] as u32)) as usize;
                        let dh = match dist {
                            Some(h) => h,
                            None => fail!(ZErr::InvalidDistanceCode),
                        };
                        let ds = match t!(decode_sym(&mut b, dh)) {
                            Some(s) => s as usize,
                            None => fail!(ZErr::InvalidDistanceCode),
                        };
                        if ds >= 30 {
                            fail!(ZErr::InvalidDistanceCode);
                        }
                        let d = DBASE[ds] as usize + t!(b.bits(DEXT[ds] as u32)) as usize;
                        if d > out.len() {
                            fail!(ZErr::DistanceTooFarBack);
                        }
                        marks.before(b.need(), out.len());
                        let start = out.len() - d;
                        if d >= len {
                            out.extend_from_within(start..start + len);
                        } else {
                            for k in 0..len {
                                let v = out[start + k];
                                out.push(v);
                            }
                        }
                    }
                }
            }
            _ => fail!(ZErr::InvalidBlockType),
        }
        if last == 1 {
            break;
        }
    }
    // the checksum: read, and not checked, as the png crate ignores it
    let at = b.need() + 4;
    if at > input.len() {
        return Err((Stop::Short, input.len()));
    }
    Ok(at)
}
