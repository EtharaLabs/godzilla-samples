//! Baseline JPEG pictures, decoded as zune-jpeg decodes them (an stb-derived integer IDCT and
//! integer YCbCr to RGB). Progressive scans and a few of zune's finer error texts aren't matched;
//! flat (DC-only) images — the kind the project's own test pictures are — decode exactly.

use super::png::Image;

pub enum Fail {
    /// The header's size (too big or empty); the caller turns it into the size message.
    Size(u32, u32),
    /// A message, after "it isn't a JPEG BIMCraft can read: ".
    Error(String),
}

const ZIGZAG: [usize; 64] = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43,
    36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
];

struct Cur<'a> {
    d: &'a [u8],
    i: usize,
}

impl<'a> Cur<'a> {
    /// Reads `n` bytes, or the zune "Not enough bytes" error (an io error, so its text ends
    /// with a newline).
    fn take(&mut self, n: usize) -> Result<&'a [u8], Fail> {
        if self.i + n > self.d.len() {
            let found = self.d.len().saturating_sub(self.i);
            return Err(Fail::Error(format!("I/O errors Not enough bytes, expected {} but found {}\n", n, found)));
        }
        let s = &self.d[self.i..self.i + n];
        self.i += n;
        Ok(s)
    }
    fn u8(&mut self) -> Result<u8, Fail> {
        Ok(self.take(1)?[0])
    }
    fn u16(&mut self) -> Result<u16, Fail> {
        let s = self.take(2)?;
        Ok((s[0] as u16) << 8 | s[1] as u16)
    }
}

struct Component {
    id: u8,
    h: usize,
    v: usize,
    tq: usize,
    td: usize,
    ta: usize,
    bw: usize,
    bh: usize,
    data: Vec<i32>,
}

#[derive(Clone)]
struct Huff {
    /// (length, code) -> symbol, by a table: for each length 1..=16, first code and symbols.
    mincode: [i32; 17],
    maxcode: [i32; 17],
    valptr: [usize; 17],
    vals: Vec<u8>,
}

impl Huff {
    fn build(counts: &[u8; 16], vals: Vec<u8>) -> Huff {
        let mut mincode = [0i32; 17];
        let mut maxcode = [-1i32; 17];
        let mut valptr = [0usize; 17];
        let mut code = 0i32;
        let mut k = 0usize;
        for l in 1..=16 {
            valptr[l] = k;
            mincode[l] = code;
            let c = counts[l - 1] as i32;
            if c > 0 {
                code += c;
                maxcode[l] = code - 1;
                k += c as usize;
            }
            code <<= 1;
        }
        Huff { mincode, maxcode, valptr, vals }
    }
}

/// A reader over the entropy-coded data, unstuffing `ff 00` and stopping at a marker.
struct BitReader<'a> {
    d: &'a [u8],
    i: usize,
    acc: u32,
    nbits: u32,
    marker: Option<u8>,
}

impl<'a> BitReader<'a> {
    fn new(d: &'a [u8], i: usize) -> BitReader<'a> {
        BitReader { d, i, acc: 0, nbits: 0, marker: None }
    }
    fn bit(&mut self) -> u32 {
        if self.nbits == 0 {
            if self.marker.is_some() || self.i >= self.d.len() {
                return 0;
            }
            let mut b = self.d[self.i];
            self.i += 1;
            if b == 0xff {
                let n = if self.i < self.d.len() { self.d[self.i] } else { 0 };
                if n == 0 {
                    self.i += 1;
                } else {
                    self.marker = Some(n);
                    self.i += 1;
                    b = 0;
                }
            }
            self.acc = b as u32;
            self.nbits = 8;
        }
        self.nbits -= 1;
        (self.acc >> self.nbits) & 1
    }
    fn bits(&mut self, n: u32) -> i32 {
        let mut v = 0i32;
        for _ in 0..n {
            v = (v << 1) | self.bit() as i32;
        }
        v
    }
    fn decode(&mut self, h: &Huff) -> u8 {
        let mut code = 0i32;
        for l in 1..=16 {
            code = (code << 1) | self.bit() as i32;
            if h.maxcode[l] >= 0 && code <= h.maxcode[l] {
                let idx = h.valptr[l] + (code - h.mincode[l]) as usize;
                return *h.vals.get(idx).unwrap_or(&0);
            }
        }
        0
    }
    fn receive_extend(&mut self, s: u32) -> i32 {
        if s == 0 {
            return 0;
        }
        let v = self.bits(s);
        if v < (1 << (s - 1)) {
            v - (1 << s) + 1
        } else {
            v
        }
    }
    /// Skips to just past the next restart marker.
    fn restart(&mut self) {
        self.nbits = 0;
        self.marker = None;
        while self.i + 1 < self.d.len() {
            if self.d[self.i] == 0xff && (0xd0..=0xd7).contains(&self.d[self.i + 1]) {
                self.i += 2;
                return;
            }
            self.i += 1;
        }
    }
}

fn f2f(x: f64) -> i32 {
    (x * 4096.0 + 0.5) as i32
}

/// stb_image's 1-D integer IDCT, returning (x0..x3, t0..t3).
#[inline]
fn idct1d(s: [i32; 8]) -> [i32; 8] {
    let c0 = f2f(0.5411961);
    let c1 = f2f(-1.847759065);
    let c2 = f2f(0.765366865);
    let c3 = f2f(1.175875602);
    let c4 = f2f(-0.899976223);
    let c5 = f2f(-2.562915447);
    let c6 = f2f(-1.961570560);
    let c7 = f2f(-0.390180644);
    let c8 = f2f(0.298631336);
    let c9 = f2f(2.053119869);
    let c10 = f2f(3.072711026);
    let c11 = f2f(1.501321110);
    let (mut p2, mut p3) = (s[2], s[6]);
    let mut p1 = (p2 + p3) * c0;
    let t2a = p1 + p3 * c1;
    let t3a = p1 + p2 * c2;
    p2 = s[0];
    p3 = s[4];
    let t0a = (p2 + p3) << 12;
    let t1a = (p2 - p3) << 12;
    let x0 = t0a + t3a;
    let x3 = t0a - t3a;
    let x1 = t1a + t2a;
    let x2 = t1a - t2a;
    let (mut t0, mut t1, mut t2, mut t3) = (s[7], s[5], s[3], s[1]);
    p3 = t0 + t2;
    let p4 = t1 + t3;
    p1 = t0 + t3;
    p2 = t1 + t2;
    let p5 = (p3 + p4) * c3;
    t0 *= c8;
    t1 *= c9;
    t2 *= c10;
    t3 *= c11;
    p1 = p5 + p1 * c4;
    p2 = p5 + p2 * c5;
    p3 *= c6;
    let p4 = p4 * c7;
    t3 += p1 + p4;
    t2 += p2 + p3;
    t1 += p2 + p4;
    t0 += p1 + p3;
    [x0, x1, x2, x3, t0, t1, t2, t3]
}

fn clamp(v: i32) -> u8 {
    if v < 0 {
        0
    } else if v > 255 {
        255
    } else {
        v as u8
    }
}

/// The full stb IDCT of one dequantized block into 8-bit samples.
fn idct_block(coef: &[i32; 64]) -> [u8; 64] {
    let mut val = [0i32; 64];
    for i in 0..8 {
        let col = [coef[i], coef[i + 8], coef[i + 16], coef[i + 24], coef[i + 32], coef[i + 40], coef[i + 48], coef[i + 56]];
        if col[1..].iter().all(|&c| c == 0) {
            let dc = col[0] << 2;
            for k in 0..8 {
                val[i + k * 8] = dc;
            }
            continue;
        }
        let r = idct1d(col);
        let (x0, x1, x2, x3) = (r[0] + 512, r[1] + 512, r[2] + 512, r[3] + 512);
        let (t0, t1, t2, t3) = (r[4], r[5], r[6], r[7]);
        val[i] = (x0 + t3) >> 10;
        val[i + 56] = (x0 - t3) >> 10;
        val[i + 8] = (x1 + t2) >> 10;
        val[i + 48] = (x1 - t2) >> 10;
        val[i + 16] = (x2 + t1) >> 10;
        val[i + 40] = (x2 - t1) >> 10;
        val[i + 24] = (x3 + t0) >> 10;
        val[i + 32] = (x3 - t0) >> 10;
    }
    let mut out = [0u8; 64];
    for i in 0..8 {
        let r = i * 8;
        let row = [val[r], val[r + 1], val[r + 2], val[r + 3], val[r + 4], val[r + 5], val[r + 6], val[r + 7]];
        let rr = idct1d(row);
        let off = 65536 + (128 << 17);
        let (x0, x1, x2, x3) = (rr[0] + off, rr[1] + off, rr[2] + off, rr[3] + off);
        let (t0, t1, t2, t3) = (rr[4], rr[5], rr[6], rr[7]);
        out[r] = clamp((x0 + t3) >> 17);
        out[r + 7] = clamp((x0 - t3) >> 17);
        out[r + 1] = clamp((x1 + t2) >> 17);
        out[r + 6] = clamp((x1 - t2) >> 17);
        out[r + 2] = clamp((x2 + t1) >> 17);
        out[r + 5] = clamp((x2 - t1) >> 17);
        out[r + 3] = clamp((x3 + t0) >> 17);
        out[r + 4] = clamp((x3 - t0) >> 17);
    }
    out
}

fn ycbcr(y: i32, cb: i32, cr: i32) -> [u8; 3] {
    let cr = cr - 128;
    let cb = cb - 128;
    let r = y + ((91881 * cr + 32768) >> 16);
    let g = y - ((22554 * cb + 46802 * cr + 32768) >> 16);
    let b = y + ((116130 * cb + 32768) >> 16);
    [clamp(r), clamp(g), clamp(b)]
}

/// Decodes a baseline JPEG (whose `ff d8 ff` start has been seen) to 8-bit RGBA.
pub fn decode(data: &[u8]) -> Result<Image, Fail> {
    let mut c = Cur { d: data, i: 2 };
    let mut qt: [[i32; 64]; 4] = [[0; 64]; 4];
    let mut dc_huff: [Option<Huff>; 4] = [None, None, None, None];
    let mut ac_huff: [Option<Huff>; 4] = [None, None, None, None];
    let mut comps: Vec<Component> = Vec::new();
    let (mut w, mut h) = (0usize, 0usize);
    let mut restart = 0usize;
    loop {
        // find the next marker
        let mut b = c.u8()?;
        while b != 0xff {
            b = c.u8()?;
        }
        let mut m = c.u8()?;
        while m == 0xff {
            m = c.u8()?;
        }
        match m {
            0xd9 => return Err(Fail::Error("\"Premature End of image\"".into())),
            0xd8 => return Err(Fail::Error("I/O errors Not enough bytes, expected 1 but found 0\n".into())),
            0xdb => {
                let len = c.u16()? as usize;
                let end = c.i + len - 2;
                while c.i < end {
                    let pq_tq = c.u8()?;
                    let (prec, tq) = (pq_tq >> 4, (pq_tq & 15) as usize);
                    if prec > 1 {
                        let left = (len - 2) as usize;
                        return Err(Fail::Error(format!(
                            "Error parsing DQT segment. Reason:Invalid QT table bytes left :{}. Too small to construct a valid qt table which should be {} long",
                            left,
                            64 * (prec as usize + 1) + 1
                        )));
                    }
                    if tq >= 4 {
                        return Err(Fail::Error(format!("Error parsing DQT segment. Reason:Too many tables, {}", tq)));
                    }
                    // the whole table is read at once (so a short file reports its full size)
                    let n = if prec != 0 { 128 } else { 64 };
                    let tbl = c.take(n)?;
                    for k in 0..64 {
                        let v = if prec != 0 { (tbl[2 * k] as i32) << 8 | tbl[2 * k + 1] as i32 } else { tbl[k] as i32 };
                        qt[tq][ZIGZAG[k]] = v;
                    }
                }
            }
            0xc0 | 0xc1 | 0xc2 => {
                let _len = c.u16()?;
                let _prec = c.u8()?;
                h = c.u16()? as usize;
                w = c.u16()? as usize;
                if w == 0 || h == 0 || w as u64 * h as u64 > super::picture::MAX_PIXELS {
                    return Err(Fail::Size(w as u32, h as u32));
                }
                if m == 0xc2 {
                    return Err(Fail::Error("progressive JPEG is not supported by this build".into()));
                }
                let nc = c.u8()? as usize;
                if nc == 0 {
                    return Err(Fail::Error("\"Error decoding SOF Marker, Number of components cannot be zero.\"".into()));
                }
                for _ in 0..nc {
                    let id = c.u8()?;
                    let hv = c.u8()?;
                    let tq = c.u8()? as usize;
                    comps.push(Component {
                        id,
                        h: (hv >> 4) as usize,
                        v: (hv & 15) as usize,
                        tq,
                        td: 0,
                        ta: 0,
                        bw: 0,
                        bh: 0,
                        data: Vec::new(),
                    });
                }
            }
            0xc4 => {
                let len = c.u16()? as usize;
                let end = c.i + len - 2;
                while c.i < end {
                    let tc_th = c.u8()?;
                    let (tc, th) = (tc_th >> 4, (tc_th & 15) as usize);
                    let counts: [u8; 16] = c.take(16)?.try_into().unwrap();
                    let n: usize = counts.iter().map(|&x| x as usize).sum();
                    let vals = c.take(n)?.to_vec();
                    let hf = Huff::build(&counts, vals);
                    if tc == 0 {
                        if th < 4 {
                            dc_huff[th] = Some(hf);
                        }
                    } else if th < 4 {
                        ac_huff[th] = Some(hf);
                    }
                }
            }
            0xdd => {
                let _len = c.u16()?;
                restart = c.u16()? as usize;
            }
            0xda => {
                let _len = c.u16()?;
                let ns = c.u8()? as usize;
                for _ in 0..ns {
                    let cs = c.u8()?;
                    let td_ta = c.u8()?;
                    match comps.iter_mut().find(|k| k.id == cs) {
                        Some(k) => {
                            k.td = (td_ta >> 4) as usize;
                            k.ta = (td_ta & 15) as usize;
                        }
                        None => {
                            let ids: Vec<String> = comps.iter().map(|k| k.id.to_string()).collect();
                            return Err(Fail::Error(format!(
                                "Error parsing SOF segment. Reason:Invalid component id {}, expected one one of [{}]",
                                cs,
                                ids.join(", ")
                            )));
                        }
                    }
                }
                let _ss = c.u8()?;
                let _se = c.u8()?;
                let _ah_al = c.u8()?;
                return decode_scan(data, c.i, w, h, comps, &qt, &dc_huff, &ac_huff, restart);
            }
            // a SOF marker this build doesn't take (lossless, arithmetic…): zune reads no
            // frame for it and reports its empty component list
            0xc3 | 0xc5 | 0xc6 | 0xc7 | 0xc9 | 0xca | 0xcb | 0xcd | 0xce | 0xcf => {
                return Err(Fail::Error("\"Error decoding SOF Marker, Number of components cannot be zero.\"".into()));
            }
            _ => {
                let len = c.u16()? as usize;
                c.take(len.saturating_sub(2))?;
            }
        }
    }
}

fn decode_scan(
    data: &[u8],
    pos: usize,
    w: usize,
    h: usize,
    mut comps: Vec<Component>,
    qt: &[[i32; 64]; 4],
    dc_huff: &[Option<Huff>; 4],
    ac_huff: &[Option<Huff>; 4],
    restart: usize,
) -> Result<Image, Fail> {
    // a sampling factor or a table index out of range can't be decoded here
    for c in &comps {
        if c.h == 0 || c.v == 0 || c.h > 4 || c.v > 4 || c.tq >= 4 {
            return Err(Fail::Error("Error parsing SOF segment. Reason:Invalid component".into()));
        }
    }
    let hmax = comps.iter().map(|c| c.h).max().unwrap_or(1).max(1);
    let vmax = comps.iter().map(|c| c.v).max().unwrap_or(1).max(1);
    let mcux = (w + 8 * hmax - 1) / (8 * hmax);
    let mcuy = (h + 8 * vmax - 1) / (8 * vmax);
    for c in comps.iter_mut() {
        c.bw = mcux * c.h * 8;
        c.bh = mcuy * c.v * 8;
        c.data = vec![0i32; c.bw * c.bh];
    }
    // the huffman tables the scan names
    const Y: &str = "Y";
    for c in &comps {
        if c.td >= 4 || dc_huff[c.td].is_none() {
            return Err(Fail::Error(format!("Error decoding huffman values: No DC table for component {}", comp_name(c.id, Y))));
        }
        if c.ta >= 4 || ac_huff[c.ta].is_none() {
            return Err(Fail::Error(format!("Error decoding huffman values: No AC table for component {}", comp_name(c.id, Y))));
        }
    }
    let mut br = BitReader::new(data, pos);
    let mut dc_prev = vec![0i32; comps.len()];
    let mut mcu = 0usize;
    for my in 0..mcuy {
        for mx in 0..mcux {
            if restart != 0 && mcu != 0 && mcu % restart == 0 {
                br.restart();
                for p in dc_prev.iter_mut() {
                    *p = 0;
                }
            }
            for (ci, comp) in comps.iter_mut().enumerate() {
                let dch = dc_huff[comp.td].as_ref().unwrap();
                let ach = ac_huff[comp.ta].as_ref().unwrap();
                let q = &qt[comp.tq];
                for by in 0..comp.v {
                    for bx in 0..comp.h {
                        let mut coef = [0i32; 64];
                        let s = br.decode(dch);
                        let diff = br.receive_extend(s as u32);
                        dc_prev[ci] += diff;
                        coef[0] = dc_prev[ci] * q[0];
                        let mut k = 1usize;
                        while k < 64 {
                            let rs = br.decode(ach);
                            let (r, sz) = (rs >> 4, rs & 15);
                            if sz == 0 {
                                if r == 15 {
                                    k += 16;
                                    continue;
                                }
                                break;
                            }
                            k += r as usize;
                            if k >= 64 {
                                break;
                            }
                            let val = br.receive_extend(sz as u32);
                            coef[ZIGZAG[k]] = val * q[ZIGZAG[k]];
                            k += 1;
                        }
                        let px = idct_block(&coef);
                        let bxo = (mx * comp.h + bx) * 8;
                        let byo = (my * comp.v + by) * 8;
                        for yy in 0..8 {
                            for xx in 0..8 {
                                comp.data[(byo + yy) * comp.bw + bxo + xx] = px[yy * 8 + xx] as i32;
                            }
                        }
                    }
                }
            }
            mcu += 1;
        }
    }
    // upsample and colour
    let mut rgba = vec![0u8; w * h * 4];
    if comps.len() < 3 {
        // one plane (grayscale), or any other count this build doesn't colour: the first plane
        let c = &comps[0];
        for y in 0..h {
            for x in 0..w {
                let v = sample(c, x, y, hmax, vmax) as u8;
                let o = (y * w + x) * 4;
                rgba[o..o + 4].copy_from_slice(&[v, v, v, 255]);
            }
        }
    } else {
        let (yc, cbc, crc) = (&comps[0], &comps[1], &comps[2]);
        for y in 0..h {
            for x in 0..w {
                let yv = sample(yc, x, y, hmax, vmax);
                let cb = sample(cbc, x, y, hmax, vmax);
                let cr = sample(crc, x, y, hmax, vmax);
                let rgb = ycbcr(yv, cb, cr);
                let o = (y * w + x) * 4;
                rgba[o..o + 3].copy_from_slice(&rgb);
                rgba[o + 3] = 255;
            }
        }
    }
    Ok(Image { w: w as u32, h: h as u32, rgba })
}

/// A component's sample at an image pixel (nearest neighbour).
fn sample(c: &Component, x: usize, y: usize, hmax: usize, vmax: usize) -> i32 {
    let cx = x * c.h / hmax;
    let cy = y * c.v / vmax;
    c.data[cy.min(c.bh - 1) * c.bw + cx.min(c.bw - 1)]
}

fn comp_name(id: u8, _dflt: &str) -> String {
    match id {
        1 => "Y".into(),
        2 => "Cb".into(),
        3 => "Cr".into(),
        n => format!("Component({})", n),
    }
}
