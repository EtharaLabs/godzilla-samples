// Bundled font metrics and outlines (TrueType, parsed at first use).

use std::collections::HashMap;
use std::sync::OnceLock;

pub static SANS_400: &[u8] = include_bytes!("../fonts/sans-400.ttf");
pub static SANS_500: &[u8] = include_bytes!("../fonts/sans-500.ttf");
pub static SANS_600: &[u8] = include_bytes!("../fonts/sans-600.ttf");
pub static SANS_700: &[u8] = include_bytes!("../fonts/sans-700.ttf");
pub static CODE_400: &[u8] = include_bytes!("../fonts/code-400.ttf");
pub static CODE_500: &[u8] = include_bytes!("../fonts/code-500.ttf");
pub static CODE_600: &[u8] = include_bytes!("../fonts/code-600.ttf");
pub static CODE_700: &[u8] = include_bytes!("../fonts/code-700.ttf");

pub struct Font {
    pub data: &'static [u8],
    pub upem: f64,
    pub cmap: HashMap<u32, u16>,
    pub adv: Vec<u16>,
    pub loca: Vec<u32>,
    pub glyf_off: usize,
    pub ascent: i16,
    pub descent: i16,
}

fn rd16(d: &[u8], o: usize) -> u16 {
    u16::from_be_bytes([d[o], d[o + 1]])
}
fn rd32(d: &[u8], o: usize) -> u32 {
    u32::from_be_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]])
}

impl Font {
    fn parse(data: &'static [u8]) -> Font {
        let n = rd16(data, 4) as usize;
        let mut tables: HashMap<String, (usize, usize)> = HashMap::new();
        for i in 0..n {
            let o = 12 + 16 * i;
            let tag = String::from_utf8_lossy(&data[o..o + 4]).to_string();
            tables.insert(tag, (rd32(data, o + 8) as usize, rd32(data, o + 12) as usize));
        }
        let head = tables["head"].0;
        let upem = rd16(data, head + 18) as f64;
        let index_to_loc = rd16(data, head + 50) as i16;
        let hhea = tables["hhea"].0;
        let ascent = rd16(data, hhea + 4) as i16;
        let descent = rd16(data, hhea + 6) as i16;
        let nhm = rd16(data, hhea + 34) as usize;
        let maxp = tables["maxp"].0;
        let ng = rd16(data, maxp + 4) as usize;
        let hmtx = tables["hmtx"].0;
        let mut adv = Vec::with_capacity(ng);
        for i in 0..ng {
            if i < nhm {
                adv.push(rd16(data, hmtx + 4 * i));
            } else {
                let last = *adv.last().unwrap_or(&0);
                adv.push(last);
            }
        }
        let mut cmap = HashMap::new();
        let cm = tables["cmap"].0;
        let nt = rd16(data, cm + 2) as usize;
        for i in 0..nt {
            let so = cm + rd32(data, cm + 4 + 8 * i + 4) as usize;
            let fmt = rd16(data, so);
            if fmt == 12 {
                let ngr = rd32(data, so + 12) as usize;
                for j in 0..ngr {
                    let a = rd32(data, so + 16 + 12 * j);
                    let b = rd32(data, so + 20 + 12 * j);
                    let g = rd32(data, so + 24 + 12 * j);
                    for c in a..=b {
                        cmap.insert(c, (g + (c - a)) as u16);
                    }
                }
            } else if fmt == 4 {
                let segx2 = rd16(data, so + 6) as usize;
                let seg = segx2 / 2;
                for k in 0..seg {
                    let end = rd16(data, so + 14 + 2 * k) as u32;
                    let start = rd16(data, so + 16 + segx2 + 2 * k) as u32;
                    let delta = rd16(data, so + 16 + 2 * segx2 + 2 * k) as i16 as i32;
                    let roff_pos = so + 16 + 3 * segx2 + 2 * k;
                    let roff = rd16(data, roff_pos) as usize;
                    for c in start..=end {
                        if c == 0xffff {
                            continue;
                        }
                        let g = if roff == 0 {
                            ((c as i32 + delta) & 0xffff) as u16
                        } else {
                            let p = roff_pos + roff + 2 * (c - start) as usize;
                            let g = rd16(data, p);
                            if g != 0 {
                                ((g as i32 + delta) & 0xffff) as u16
                            } else {
                                0
                            }
                        };
                        cmap.entry(c).or_insert(g);
                    }
                }
            }
        }
        let mut loca = Vec::with_capacity(ng + 1);
        if let Some(&(lo, _)) = tables.get("loca") {
            for i in 0..=ng {
                if index_to_loc == 0 {
                    loca.push(rd16(data, lo + 2 * i) as u32 * 2);
                } else {
                    loca.push(rd32(data, lo + 4 * i));
                }
            }
        }
        let glyf_off = tables.get("glyf").map(|x| x.0).unwrap_or(0);
        Font { data, upem, cmap, adv, loca, glyf_off, ascent, descent }
    }

    pub fn glyph_for(&self, c: char) -> Option<u16> {
        self.cmap.get(&(c as u32)).copied()
    }

    // Glyph outline as quadratic contours: list of contours, each a list of (x, y, on_curve).
    pub fn outline(&self, gid: u16) -> Vec<Vec<(f64, f64, bool)>> {
        let mut out = Vec::new();
        self.outline_into(gid, 0.0, 0.0, &mut out, 0);
        out
    }

    fn outline_into(&self, gid: u16, dx: f64, dy: f64, out: &mut Vec<Vec<(f64, f64, bool)>>, depth: u32) {
        let g = gid as usize;
        if g + 1 >= self.loca.len() || depth > 8 {
            return;
        }
        let start = self.glyf_off + self.loca[g] as usize;
        let end = self.glyf_off + self.loca[g + 1] as usize;
        if end <= start {
            return;
        }
        let d = self.data;
        let nc = rd16(d, start) as i16;
        if nc >= 0 {
            let nc = nc as usize;
            let mut ends = Vec::with_capacity(nc);
            for i in 0..nc {
                ends.push(rd16(d, start + 10 + 2 * i) as usize);
            }
            let npts = if nc > 0 { ends[nc - 1] + 1 } else { 0 };
            let ilen = rd16(d, start + 10 + 2 * nc) as usize;
            let mut p = start + 12 + 2 * nc + ilen;
            let mut flags = Vec::with_capacity(npts);
            while flags.len() < npts {
                let f = d[p];
                p += 1;
                flags.push(f);
                if f & 8 != 0 {
                    let r = d[p];
                    p += 1;
                    for _ in 0..r {
                        flags.push(f);
                    }
                }
            }
            flags.truncate(npts);
            let mut xs = Vec::with_capacity(npts);
            let mut x: i32 = 0;
            for &f in &flags {
                if f & 2 != 0 {
                    let v = d[p] as i32;
                    p += 1;
                    x += if f & 16 != 0 { v } else { -v };
                } else if f & 16 == 0 {
                    x += rd16(d, p) as i16 as i32;
                    p += 2;
                }
                xs.push(x);
            }
            let mut ys = Vec::with_capacity(npts);
            let mut y: i32 = 0;
            for &f in &flags {
                if f & 4 != 0 {
                    let v = d[p] as i32;
                    p += 1;
                    y += if f & 32 != 0 { v } else { -v };
                } else if f & 32 == 0 {
                    y += rd16(d, p) as i16 as i32;
                    p += 2;
                }
                ys.push(y);
            }
            let mut s = 0;
            for &e in &ends {
                let mut c = Vec::new();
                for k in s..=e {
                    c.push((xs[k] as f64 + dx, ys[k] as f64 + dy, flags[k] & 1 != 0));
                }
                out.push(c);
                s = e + 1;
            }
        } else {
            // composite
            let mut p = start + 10;
            loop {
                let flags = rd16(d, p);
                let sub = rd16(d, p + 2);
                p += 4;
                let (ax, ay);
                if flags & 1 != 0 {
                    ax = rd16(d, p) as i16 as f64;
                    ay = rd16(d, p + 2) as i16 as f64;
                    p += 4;
                } else {
                    ax = (d[p] as i8) as f64;
                    ay = (d[p + 1] as i8) as f64;
                    p += 2;
                }
                if flags & 8 != 0 {
                    p += 2;
                } else if flags & 0x40 != 0 {
                    p += 4;
                } else if flags & 0x80 != 0 {
                    p += 8;
                }
                self.outline_into(sub, dx + ax, dy + ay, out, depth + 1);
                if flags & 0x20 == 0 {
                    break;
                }
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Family {
    Sans,
    Code,
}

static FONTS: OnceLock<Vec<Font>> = OnceLock::new();

fn fonts() -> &'static Vec<Font> {
    FONTS.get_or_init(|| {
        vec![
            Font::parse(SANS_400),
            Font::parse(SANS_500),
            Font::parse(SANS_600),
            Font::parse(SANS_700),
            Font::parse(CODE_400),
            Font::parse(CODE_500),
            Font::parse(CODE_600),
            Font::parse(CODE_700),
        ]
    })
}

pub fn weight_index(weight: u32) -> usize {
    match weight {
        400 => 0,
        500 => 1,
        600 => 2,
        700 => 3,
        w if w < 450 => 0,
        w if w < 550 => 1,
        w if w < 650 => 2,
        _ => 3,
    }
}

pub fn font(family: Family, weight: u32) -> &'static Font {
    let base = if family == Family::Code { 4 } else { 0 };
    &fonts()[base + weight_index(weight)]
}

pub fn font_bytes(family: Family, weight: u32) -> &'static [u8] {
    match (family, weight_index(weight)) {
        (Family::Sans, 0) => SANS_400,
        (Family::Sans, 1) => SANS_500,
        (Family::Sans, 2) => SANS_600,
        (Family::Sans, _) => SANS_700,
        (Family::Code, 0) => CODE_400,
        (Family::Code, 1) => CODE_500,
        (Family::Code, 2) => CODE_600,
        (Family::Code, _) => CODE_700,
    }
}

pub fn is_wide(c: u32) -> bool {
    matches!(c, 0x1100..=0x115F | 0x2E80..=0x9FFF | 0xAC00..=0xD7AF | 0xF900..=0xFAFF | 0xFF00..=0xFF60 | 0x20000..=0x3FFFD)
}

// The advance of a char's bundled glyph in font units: '⌀' borrows 'Ø';
// the code face is monospaced, so a glyph its metrics leave at zero
// advances 0.6 em like the rest.
fn glyph_advance(f: &Font, family: Family, c: char) -> Option<f64> {
    let g = f.glyph_for(if c == '\u{2300}' { '\u{d8}' } else { c })?;
    let a = f.adv[g as usize] as f64;
    if a == 0.0 && family == Family::Code {
        return Some(0.6 * f.upem);
    }
    Some(a)
}

// Advance of one char in em units (1.0 = font size).
pub fn char_advance_em(family: Family, weight: u32, c: char) -> f64 {
    let f = font(family, weight);
    if let Some(a) = glyph_advance(f, family, c) {
        return a / f.upem;
    }
    if is_wide(c as u32) {
        return 1.0;
    }
    0.6
}

// Width in font units summed over the string, then scaled.
pub fn text_width(family: Family, weight: u32, size: f64, s: &str) -> f64 {
    let f = font(family, weight);
    // each glyph's advance is scaled on its own, then summed
    let mut w: f64 = 0.0;
    for c in s.chars() {
        if let Some(a) = glyph_advance(f, family, c) {
            w += a / f.upem * size;
        } else {
            let em = if is_wide(c as u32) { 1.0 } else { 0.6 };
            w += em * f.upem / f.upem * size;
        }
    }
    w
}

// Advance in font units of a char that has a bundled glyph (outlining).
pub fn outline_advance(f: &Font, family: Family, c: char) -> f64 {
    glyph_advance(f, family, c).unwrap_or(0.0)
}
