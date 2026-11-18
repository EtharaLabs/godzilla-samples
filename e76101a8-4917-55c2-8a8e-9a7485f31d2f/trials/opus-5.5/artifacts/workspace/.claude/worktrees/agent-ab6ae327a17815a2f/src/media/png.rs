//! PNG pictures: read as the png crate (0.17.16) reads them, expanded to 8-bit RGBA, with its
//! errors word for word and in the order it meets them; and written as a picture is kept in a
//! project (8-bit RGBA, each row Sub-filtered and packed as fdeflate packs it, or stored).

use super::zlib::{self, End};
use crate::inflate::crc32;

/// A picture's pixels: 8-bit RGBA, row by row.
pub struct Image {
    pub w: u32,
    pub h: u32,
    pub rgba: Vec<u8>,
}

/// Why a PNG can't be read: the png crate's error, or the panic it would have had.
pub enum Fail {
    Error(String),
    Panic { at: &'static str, msg: String },
}

fn err<T>(s: impl Into<String>) -> Result<T, Fail> {
    Err(Fail::Error(s.into()))
}

const EOF: &str = "unexpected end of file";

/// A chunk type as the png crate's `Debug` shows it.
pub fn chunk_debug(t: [u8; 4]) -> String {
    let mut ty = String::new();
    for &c in &t {
        ty.extend(char::from(c).escape_debug());
    }
    format!(
        "ChunkType {{ type: {}, critical: {}, private: {}, reserved: {}, safecopy: {} }}",
        ty,
        t[0] & 32 == 0,
        t[1] & 32 != 0,
        t[2] & 32 != 0,
        t[3] & 32 != 0
    )
}

fn critical(t: [u8; 4]) -> bool {
    t[0] & 32 == 0
}

struct Rd<'a> {
    d: &'a [u8],
    pos: usize,
}

impl<'a> Rd<'a> {
    fn u32(&mut self) -> Result<u32, Fail> {
        if self.pos + 4 > self.d.len() {
            self.pos = self.d.len();
            return err(EOF);
        }
        let v = u32::from_be_bytes(self.d[self.pos..self.pos + 4].try_into().unwrap());
        self.pos += 4;
        Ok(v)
    }
    fn tag(&mut self) -> Result<[u8; 4], Fail> {
        if self.pos + 4 > self.d.len() {
            self.pos = self.d.len();
            return err(EOF);
        }
        let v: [u8; 4] = self.d[self.pos..self.pos + 4].try_into().unwrap();
        self.pos += 4;
        Ok(v)
    }
}

#[derive(Clone, Copy, PartialEq)]
enum Color {
    Gray,
    Rgb,
    Indexed,
    GrayA,
    Rgba,
}

impl Color {
    fn name(self) -> &'static str {
        match self {
            Color::Gray => "Grayscale",
            Color::Rgb => "Rgb",
            Color::Indexed => "Indexed",
            Color::GrayA => "GrayscaleAlpha",
            Color::Rgba => "Rgba",
        }
    }
    fn channels(self) -> usize {
        match self {
            Color::Gray | Color::Indexed => 1,
            Color::GrayA => 2,
            Color::Rgb => 3,
            Color::Rgba => 4,
        }
    }
}

fn depth_name(d: u8) -> &'static str {
    match d {
        1 => "One",
        2 => "Two",
        4 => "Four",
        8 => "Eight",
        _ => "Sixteen",
    }
}

struct Header {
    w: u32,
    h: u32,
    depth: u8,
    color: Color,
    interlaced: bool,
}

/// What the chunks before the image data told.
#[derive(Default)]
struct Info {
    header: Option<Header>,
    palette: Option<Vec<u8>>,
    trns: Option<Vec<u8>>,
    gama: bool,
    chrm: bool,
    srgb: bool,
    phys: bool,
    seq: Option<u32>,
}

/// Reads big-endian numbers out of a chunk's data; running short is "Chunk is too short".
struct Body<'a> {
    d: &'a [u8],
    pos: usize,
    kind: [u8; 4],
}

impl<'a> Body<'a> {
    fn short(&self) -> Fail {
        Fail::Error(format!("Chunk is too short: {}", chunk_debug(self.kind)))
    }
    fn u8(&mut self) -> Result<u8, Fail> {
        if self.pos + 1 > self.d.len() {
            return Err(self.short());
        }
        self.pos += 1;
        Ok(self.d[self.pos - 1])
    }
    fn u16(&mut self) -> Result<u16, Fail> {
        if self.pos + 2 > self.d.len() {
            return Err(self.short());
        }
        self.pos += 2;
        Ok(u16::from_be_bytes([self.d[self.pos - 2], self.d[self.pos - 1]]))
    }
    fn u32(&mut self) -> Result<u32, Fail> {
        if self.pos + 4 > self.d.len() {
            return Err(self.short());
        }
        self.pos += 4;
        Ok(u32::from_be_bytes(self.d[self.pos - 4..self.pos].try_into().unwrap()))
    }
}

fn dup(kind: &[u8; 4]) -> Fail {
    Fail::Error(format!("Chunk {} must appear at most once.", chunk_debug(*kind)))
}

const TEXT_NO_NULL: &str = "No null separator in tEXt chunk.";
const TEXT_KEYWORD: &str = "Keyword empty or longer than 79 bytes.";
const TEXT_METHOD: &str = "Using an unrecognized byte as compression method.";
const TEXT_UNREPRESENTABLE: &str = "Unrepresentable data in tEXt chunk.";

/// What the png crate does with a chunk's data before the image data: Ok(true) for IEND.
fn parse_chunk(info: &mut Info, kind: [u8; 4], data: &[u8]) -> Result<bool, Fail> {
    let mut b = Body { d: data, pos: 0, kind };
    match &kind {
        b"IHDR" => {
            if info.header.is_some() {
                return Err(dup(&kind));
            }
            let w = b.u32()?;
            let h = b.u32()?;
            if w == 0 || h == 0 {
                return err("Invalid image dimensions");
            }
            let depth = b.u8()?;
            if !matches!(depth, 1 | 2 | 4 | 8 | 16) {
                return err(format!("Invalid bit depth {}.", depth));
            }
            let ct = b.u8()?;
            let color = match ct {
                0 => Color::Gray,
                2 => Color::Rgb,
                3 => Color::Indexed,
                4 => Color::GrayA,
                6 => Color::Rgba,
                n => return err(format!("Invalid color type {}.", n)),
            };
            let ok = match color {
                Color::Gray => true,
                Color::Indexed => depth <= 8,
                _ => depth >= 8,
            };
            if !ok {
                return err(format!("Invalid color/depth combination in header: {}/{}", color.name(), depth_name(depth)));
            }
            let comp = b.u8()?;
            if comp != 0 {
                return err(format!("Unknown compression method {}.", comp));
            }
            let filter = b.u8()?;
            if filter != 0 {
                return err(format!("Unknown filter method {}.", filter));
            }
            let interlaced = match b.u8()? {
                0 => false,
                1 => true,
                n => return err(format!("Unknown interlace method {}.", n)),
            };
            info.header = Some(Header { w, h, depth, color, interlaced });
        }
        b"PLTE" => {
            if info.palette.is_some() {
                return Err(dup(&kind));
            }
            info.palette = Some(data.to_vec());
        }
        b"tRNS" => {
            if info.trns.is_some() {
                // as the png crate says it
                return Err(dup(b"PLTE"));
            }
            let hdr = info.header.as_ref().unwrap();
            let len = data.len();
            match hdr.color {
                Color::Gray => {
                    if len < 2 {
                        return err(format!("Not enough palette entries, expect 2 got {}.", len));
                    }
                    let v = if hdr.depth < 16 { vec![data[1]] } else { data.to_vec() };
                    info.trns = Some(v);
                }
                Color::Rgb => {
                    if len < 6 {
                        return err(format!("Not enough palette entries, expect 6 got {}.", len));
                    }
                    let v = if hdr.depth < 16 { vec![data[1], data[3], data[5]] } else { data.to_vec() };
                    info.trns = Some(v);
                }
                Color::Indexed => {
                    if info.palette.is_none() {
                        return err(format!("Chunk {} is invalid before PLTE chunk.", chunk_debug(kind)));
                    }
                    info.trns = Some(data.to_vec());
                }
                c => return err(format!("Transparency chunk found for color type {}.", c.name())),
            }
        }
        b"gAMA" => {
            if info.gama {
                return Err(dup(&kind));
            }
            b.u32()?;
            info.gama = true;
        }
        b"cHRM" => {
            if info.chrm {
                return Err(dup(&kind));
            }
            for _ in 0..8 {
                b.u32()?;
            }
            info.chrm = true;
        }
        b"sRGB" => {
            if info.srgb {
                return Err(dup(&kind));
            }
            let v = b.u8()?;
            if v > 3 {
                return err(format!("Invalid sRGB rendering intent {}.", v));
            }
            info.srgb = true;
        }
        b"pHYs" => {
            if info.phys {
                return Err(dup(&kind));
            }
            b.u32()?;
            b.u32()?;
            let unit = b.u8()?;
            if unit > 1 {
                return err(format!("Invalid physical pixel size unit {}.", unit));
            }
            info.phys = true;
        }
        b"acTL" => {
            b.u32()?;
            b.u32()?;
        }
        b"fcTL" => {
            let seq = b.u32()?;
            let expect = match info.seq {
                Some(s) => s.wrapping_add(1),
                None => 0,
            };
            if seq != expect {
                return err(format!("Sequence is not in order, expected #{} got #{}.", expect, seq));
            }
            info.seq = Some(seq);
            let w = b.u32()?;
            let h = b.u32()?;
            let x = b.u32()?;
            let y = b.u32()?;
            b.u16()?;
            b.u16()?;
            let dispose = b.u8()?;
            if dispose > 2 {
                return err(format!("Invalid dispose operation {}.", dispose));
            }
            let blend = b.u8()?;
            if blend > 1 {
                return err(format!("Invalid blend operation {}.", blend));
            }
            if w == 0 || h == 0 {
                return err("Invalid image dimensions");
            }
            let hdr = info.header.as_ref().unwrap();
            if x as u64 + w as u64 > hdr.w as u64 || y as u64 + h as u64 > hdr.h as u64 {
                return err("Sub frame is out-of-bounds.");
            }
        }
        b"fdAT" => {
            return err(format!("Unexpected restart of {} chunk sequence", chunk_debug(kind)));
        }
        b"tEXt" => {
            let nul = match data.iter().position(|&c| c == 0) {
                Some(i) => i,
                None => return err(TEXT_NO_NULL),
            };
            if nul == 0 || nul > 79 {
                return err(TEXT_KEYWORD);
            }
        }
        b"zTXt" => {
            let nul = match data.iter().position(|&c| c == 0) {
                Some(i) => i,
                None => return err(TEXT_NO_NULL),
            };
            if nul == 0 || nul > 79 {
                return err(TEXT_KEYWORD);
            }
            match data.get(nul + 1) {
                Some(0) => {}
                _ => return err(TEXT_METHOD),
            }
        }
        b"iTXt" => {
            let nul = match data.iter().position(|&c| c == 0) {
                Some(i) => i,
                None => return err(TEXT_NO_NULL),
            };
            if nul == 0 || nul > 79 {
                return err(TEXT_KEYWORD);
            }
            let flag = match data.get(nul + 1) {
                Some(&f) => f,
                None => return err("No compression flag in the iTXt chunk."),
            };
            let method = match data.get(nul + 2) {
                Some(&m) => m,
                None => return err(TEXT_METHOD),
            };
            let rest = &data[nul + 3..];
            let n2 = match rest.iter().position(|&c| c == 0) {
                Some(i) => i,
                None => return err(TEXT_NO_NULL),
            };
            let rest2 = &rest[n2 + 1..];
            let n3 = match rest2.iter().position(|&c| c == 0) {
                Some(i) => i,
                None => return err(TEXT_NO_NULL),
            };
            let compressed = match flag {
                0 => false,
                1 => true,
                _ => return err("Using a flag that is not 0 or 255 as a compression flag for iTXt chunk."),
            };
            if compressed && method != 0 {
                return err(TEXT_METHOD);
            }
            let lang = &rest[..n2];
            if !lang.iter().all(|c| c.is_ascii()) {
                return err(TEXT_UNREPRESENTABLE);
            }
            if std::str::from_utf8(&rest2[..n3]).is_err() {
                return err(TEXT_UNREPRESENTABLE);
            }
            if !compressed && std::str::from_utf8(&rest2[n3 + 1..]).is_err() {
                return err(TEXT_UNREPRESENTABLE);
            }
        }
        b"IEND" => return Ok(true),
        _ => {}
    }
    Ok(false)
}

/// Adam7's passes: (x0, y0, dx, dy).
const ADAM7: [(u32, u32, u32, u32); 7] = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)];

/// A run of rows the image data holds: a pass (or the whole image), its width and rows.
struct Pass {
    x0: u32,
    y0: u32,
    dx: u32,
    dy: u32,
    w: u32,
    h: u32,
}

fn passes(hdr: &Header) -> Vec<Pass> {
    if !hdr.interlaced {
        return vec![Pass { x0: 0, y0: 0, dx: 1, dy: 1, w: hdr.w, h: hdr.h }];
    }
    let mut v = Vec::new();
    for &(x0, y0, dx, dy) in &ADAM7 {
        let w = if hdr.w > x0 { (hdr.w - x0 + dx - 1) / dx } else { 0 };
        let h = if hdr.h > y0 { (hdr.h - y0 + dy - 1) / dy } else { 0 };
        if w > 0 && h > 0 {
            v.push(Pass { x0, y0, dx, dy, w, h });
        }
    }
    v
}

/// The palette as the png crate expands it, or the panic its expansion would have.
fn rgba_palette(palette: &[u8], trns: &[u8]) -> Result<[[u8; 4]; 256], Fail> {
    let trns: &[u8] = if trns.len() <= palette.len() / 3 { trns } else { &[] };
    let mut pal = [[0u8, 0, 0, 255]; 256];
    let mut p = palette;
    let mut i = 0usize;
    while p.len() >= 4 {
        if i >= 256 {
            return Err(Fail::Panic {
                at: "/src/vendor/png-0.17.16/src/decoder/transform/palette.rs:68:13",
                msg: "index out of bounds: the len is 0 but the index is 0".into(),
            });
        }
        pal[i].copy_from_slice(&p[0..4]);
        p = &p[3..];
        i += 1;
    }
    if !p.is_empty() {
        if i >= 256 {
            return Err(Fail::Panic {
                at: "/src/vendor/png-0.17.16/src/decoder/transform/palette.rs:74:13",
                msg: "index out of bounds: the len is 0 but the index is 0".into(),
            });
        }
        if p.len() < 3 {
            return Err(Fail::Panic {
                at: "/src/vendor/png-0.17.16/src/decoder/transform/palette.rs:74:61",
                msg: format!("range end index 3 out of range for slice of length {}", p.len()),
            });
        }
        pal[i][0..3].copy_from_slice(&p[0..3]);
    }
    for (a, e) in trns.iter().zip(pal.iter_mut()) {
        e[3] = *a;
    }
    let n = palette.len() / 3;
    for e in pal[trns.len().min(256)..n.min(256)].iter_mut() {
        e[3] = 255;
    }
    Ok(pal)
}

fn paeth(a: u8, b: u8, c: u8) -> u8 {
    let (ia, ib, ic) = (a as i16, b as i16, c as i16);
    let p = ia + ib - ic;
    let pa = (p - ia).abs();
    let pb = (p - ib).abs();
    let pc = (p - ic).abs();
    if pa <= pb && pa <= pc {
        a
    } else if pb <= pc {
        b
    } else {
        c
    }
}

fn unfilter(kind: u8, bpp: usize, prev: &[u8], row: &mut [u8]) {
    let n = row.len();
    match kind {
        1 => {
            for i in bpp..n {
                row[i] = row[i].wrapping_add(row[i - bpp]);
            }
        }
        2 => {
            for i in 0..n {
                row[i] = row[i].wrapping_add(prev[i]);
            }
        }
        3 => {
            for i in 0..n {
                let a = if i >= bpp { row[i - bpp] as u16 } else { 0 };
                row[i] = row[i].wrapping_add(((a + prev[i] as u16) / 2) as u8);
            }
        }
        4 => {
            for i in 0..n {
                let a = if i >= bpp { row[i - bpp] } else { 0 };
                let c = if i >= bpp { prev[i - bpp] } else { 0 };
                row[i] = row[i].wrapping_add(paeth(a, prev[i], c));
            }
        }
        _ => {}
    }
}

/// Decodes a PNG (whose signature has been seen) to 8-bit RGBA.
pub fn decode(data: &[u8]) -> Result<Image, Fail> {
    let mut r = Rd { d: data, pos: 8 };
    let mut info = Info::default();
    // the chunks before the image data
    let mut first_len;
    loop {
        let len = r.u32()?;
        let kind = r.tag()?;
        if info.header.is_none() && &kind != b"IHDR" {
            return err(format!("{} chunk appeared before IHDR chunk", chunk_debug(kind)));
        }
        if &kind == b"IDAT" {
            first_len = len;
            break;
        }
        let start = r.pos;
        let avail = data.len().saturating_sub(start);
        if (len as usize) > avail {
            return err(EOF);
        }
        let body = &data[start..start + len as usize];
        r.pos += len as usize;
        if len > 0 && parse_chunk(&mut info, kind, body)? {
            return err("IDAT or fdAT chunk is missing.");
        }
        let crc = r.u32()?;
        let mut tb = kind.to_vec();
        tb.extend_from_slice(body);
        let sum = crc32(&tb);
        if crc != sum && critical(kind) {
            return err(format!(
                "CRC error: expected 0x{:x} have 0x{:x} while decoding {} chunk.",
                crc,
                sum,
                chunk_debug(kind)
            ));
        }
        if &kind == b"IEND" {
            return err("IDAT or fdAT chunk is missing.");
        }
    }
    let hdr = info.header.take().unwrap();
    if hdr.color == Color::Indexed && info.palette.as_ref().map(|p| p.is_empty()).unwrap_or(true) {
        return err("Missing palette of indexed image.");
    }
    // the IDAT chunks, as far as the file goes: (data start, data length, crc ok, whole)
    struct Chunk {
        start: usize,
        len: usize,
        crc_ok: bool,
        whole: bool,
    }
    let mut chunks: Vec<Chunk> = Vec::new();
    // how the sequence ends: false = the file ends first
    let flushed;
    loop {
        let start = r.pos;
        let avail = data.len().saturating_sub(start);
        if (first_len as usize) > avail {
            chunks.push(Chunk { start, len: avail, crc_ok: true, whole: false });
            flushed = false;
            break;
        }
        let len = first_len as usize;
        r.pos += len;
        if r.pos + 4 > data.len() {
            chunks.push(Chunk { start, len, crc_ok: true, whole: false });
            flushed = false;
            break;
        }
        let crc = u32::from_be_bytes(data[r.pos..r.pos + 4].try_into().unwrap());
        r.pos += 4;
        let mut tb = b"IDAT".to_vec();
        tb.extend_from_slice(&data[start..start + len]);
        chunks.push(Chunk { start, len, crc_ok: crc == crc32(&tb), whole: true });
        // the next chunk's length and type
        if r.pos + 8 > data.len() {
            flushed = false;
            break;
        }
        let nlen = u32::from_be_bytes(data[r.pos..r.pos + 4].try_into().unwrap());
        let nkind: [u8; 4] = data[r.pos + 4..r.pos + 8].try_into().unwrap();
        r.pos += 8;
        if &nkind == b"IDAT" {
            first_len = nlen;
            continue;
        }
        flushed = true;
        break;
    }
    // the stream they make, decoded once, with what was known at the end of each chunk
    let mut stream = Vec::new();
    let mut ends = Vec::new();
    for c in &chunks {
        stream.extend_from_slice(&data[c.start..c.start + c.len]);
        ends.push(stream.len());
    }
    let ch = hdr.color.channels();
    let bits = ch * hdr.depth as usize;
    let ps = passes(&hdr);
    let need: usize = ps.iter().map(|p| ((p.w as usize * bits + 7) / 8 + 1) * p.h as usize).sum();
    let dec = zlib::decode(&stream, &ends, need);
    let out = &dec.out;
    // the rows
    let bpp = ((bits + 7) / 8).max(1);
    let mut rows: Vec<(usize, usize, usize)> = Vec::new(); // (pass, row in pass, byte length)
    for (pi, p) in ps.iter().enumerate() {
        let rowlen = (p.w as usize * bits + 7) / 8 + 1;
        for y in 0..p.h as usize {
            rows.push((pi, y, rowlen));
        }
    }
    let mut done_rows = 0usize;
    let mut consumed = 0usize; // output bytes taken by rows so far
    let mut raw_rows: Vec<Vec<u8>> = Vec::with_capacity(rows.len());
    let mut palette: Option<[[u8; 4]; 256]> = None;
    let mut transformed = false;
    // takes the rows whose data is known
    let take_rows = |known: usize,
                         done_rows: &mut usize,
                         consumed: &mut usize,
                         raw_rows: &mut Vec<Vec<u8>>,
                         palette: &mut Option<[[u8; 4]; 256]>,
                         transformed: &mut bool|
     -> Result<(), Fail> {
        while *done_rows < rows.len() {
            let (pi, y, rowlen) = rows[*done_rows];
            if *consumed + rowlen > known {
                break;
            }
            let mut row = out[*consumed..*consumed + rowlen].to_vec();
            *consumed += rowlen;
            let f = row[0];
            if f > 4 {
                return err(format!("Unknown filter method {}.", f));
            }
            let prev: Vec<u8> = if y == 0 { vec![0u8; rowlen - 1] } else { raw_rows.last().unwrap().clone() };
            unfilter(f, bpp, &prev, &mut row[1..]);
            let _ = pi;
            if !*transformed {
                *transformed = true;
                if hdr.color == Color::Indexed {
                    let pal = info.palette.as_deref().unwrap_or(&[]);
                    let trns = info.trns.as_deref().unwrap_or(&[]);
                    *palette = Some(rgba_palette(pal, trns)?);
                }
            }
            raw_rows.push(row[1..].to_vec());
            *done_rows += 1;
        }
        Ok(())
    };
    let mut stream_done = false;
    for (k, c) in chunks.iter().enumerate() {
        if !stream_done {
            match dec.end {
                End::Error(e, at, false) if at <= ends[k] => {
                    return err(format!("Corrupt deflate stream. {}", e.name()));
                }
                End::Done(at) if at <= ends[k] => stream_done = true,
                _ => {}
            }
        }
        let known = if stream_done { out.len() } else { dec.known[k] };
        take_rows(known, &mut done_rows, &mut consumed, &mut raw_rows, &mut palette, &mut transformed)?;
        if done_rows == rows.len() {
            if let End::Error(e, at, true) = dec.end {
                if at <= ends[k] {
                    return err(format!("Corrupt deflate stream. {}", e.name()));
                }
            }
        }
        if !c.whole {
            return err(EOF);
        }
        if !c.crc_ok {
            let crc = u32::from_be_bytes(data[c.start + c.len..c.start + c.len + 4].try_into().unwrap());
            let mut tb = b"IDAT".to_vec();
            tb.extend_from_slice(&data[c.start..c.start + c.len]);
            return err(format!(
                "CRC error: expected 0x{:x} have 0x{:x} while decoding {} chunk.",
                crc,
                crc32(&tb),
                chunk_debug(*b"IDAT")
            ));
        }
    }
    if !flushed {
        return err(EOF);
    }
    if !stream_done {
        return err("Corrupt deflate stream. InsufficientInput");
    }
    take_rows(out.len(), &mut done_rows, &mut consumed, &mut raw_rows, &mut palette, &mut transformed)?;
    if done_rows < rows.len() {
        return err("IDAT or fDAT chunk does not have enough data for image.");
    }
    // expand to RGBA
    let (w, h) = (hdr.w as usize, hdr.h as usize);
    let mut rgba = vec![0u8; w * h * 4];
    let mut ri = 0usize;
    for p in &ps {
        for py in 0..p.h as usize {
            let row = &raw_rows[ri];
            ri += 1;
            let y = p.y0 as usize + py * p.dy as usize;
            for px in 0..p.w as usize {
                let x = p.x0 as usize + px * p.dx as usize;
                let o = (y * w + x) * 4;
                let pix = pixel(&hdr, row, px, palette.as_ref(), info.trns.as_deref());
                rgba[o..o + 4].copy_from_slice(&pix);
            }
        }
    }
    Ok(Image { w: hdr.w, h: hdr.h, rgba })
}

/// A sample of a sub-byte row.
fn sub(row: &[u8], i: usize, depth: usize) -> u8 {
    let per = 8 / depth;
    let byte = row[i / per];
    let shift = 8 - depth * (i % per + 1);
    (byte >> shift) & ((1u16 << depth) - 1) as u8
}

fn pixel(hdr: &Header, row: &[u8], x: usize, pal: Option<&[[u8; 4]; 256]>, trns: Option<&[u8]>) -> [u8; 4] {
    let d = hdr.depth as usize;
    match hdr.color {
        Color::Indexed => {
            let i = if d < 8 { sub(row, x, d) } else { row[x] };
            pal.map(|p| p[i as usize]).unwrap_or([0, 0, 0, 255])
        }
        Color::Gray => {
            if d == 16 {
                let v = &row[x * 2..x * 2 + 2];
                let a = match trns {
                    Some(t) if t.len() >= 2 && t[0] == v[0] && t[1] == v[1] => 0,
                    _ => 255,
                };
                [v[0], v[0], v[0], a]
            } else {
                let s = if d < 8 { sub(row, x, d) } else { row[x] };
                let a = match trns {
                    Some(t) if !t.is_empty() && t[0] == s => 0,
                    _ => 255,
                };
                let max = ((1u16 << d) - 1) as u16;
                let g = (s as u16 * 255 / max) as u8;
                [g, g, g, a]
            }
        }
        Color::Rgb => {
            if d == 16 {
                let v = &row[x * 6..x * 6 + 6];
                let a = match trns {
                    Some(t) if t.len() >= 6 && &t[..6] == v => 0,
                    _ => 255,
                };
                [v[0], v[2], v[4], a]
            } else {
                let v = &row[x * 3..x * 3 + 3];
                let a = match trns {
                    Some(t) if t.len() >= 3 && &t[..3] == v => 0,
                    _ => 255,
                };
                [v[0], v[1], v[2], a]
            }
        }
        Color::GrayA => {
            if d == 16 {
                let v = &row[x * 4..x * 4 + 4];
                [v[0], v[0], v[0], v[2]]
            } else {
                let v = &row[x * 2..x * 2 + 2];
                [v[0], v[0], v[0], v[1]]
            }
        }
        Color::Rgba => {
            if d == 16 {
                let v = &row[x * 8..x * 8 + 8];
                [v[0], v[2], v[4], v[6]]
            } else {
                let v = &row[x * 4..x * 4 + 4];
                [v[0], v[1], v[2], v[3]]
            }
        }
    }
}

// ---------------------------------------------------------------- writing

/// fdeflate's one dynamic block header, the code lengths of its literals and lengths.
const HEADER: [u8; 54] = [
    120, 1, 237, 192, 3, 160, 36, 89, 150, 198, 241, 255, 119, 238, 141, 200, 204, 167, 114, 75, 99, 174, 109, 219, 182, 109, 219, 182, 109, 219,
    182, 109, 105, 140, 158, 150, 74, 175, 158, 50, 51, 34, 238, 249, 118, 183, 106, 122, 166, 135, 59, 107, 213, 15,
];

const LENGTHS: [u8; 286] = [
    2, 3, 4, 5, 5, 6, 6, 7, 7, 7, 8, 8, 8, 8, 8, 9, 9, 9, 9, 9, 9, 9, 10, 10, 10, 10, 10, 10, 10, 10, 10, 11, 11, 11, 11, 11, 11, 11, 11, 11,
    11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
    12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
    12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
    12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12,
    12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 11,
    11, 11, 11, 11, 11, 11, 11, 11, 11, 10, 11, 10, 10, 10, 10, 10, 10, 10, 10, 10, 9, 9, 9, 9, 9, 8, 9, 8, 8, 8, 8, 8, 7, 7, 7, 6, 6, 6, 5, 4,
    3, 12, 12, 12, 9, 9, 11, 10, 11, 11, 10, 11, 11, 11, 11, 11, 11, 12, 11, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 9
];

struct Codes {
    code: [u16; 286],
}

fn codes() -> Codes {
    let mut count = [0u16; 16];
    for &l in LENGTHS.iter() {
        count[l as usize] += 1;
    }
    count[0] = 0;
    let mut next = [0u16; 16];
    let mut c = 0u16;
    for len in 1..16 {
        c = (c + count[len - 1]) << 1;
        next[len] = c;
    }
    let mut code = [0u16; 286];
    for (s, &l) in LENGTHS.iter().enumerate() {
        if l > 0 {
            let v = next[l as usize];
            next[l as usize] += 1;
            code[s] = v.reverse_bits() >> (16 - l);
        }
    }
    Codes { code }
}

struct BitOut {
    out: Vec<u8>,
    buf: u64,
    n: u32,
}

impl BitOut {
    #[inline]
    fn put(&mut self, bits: u64, n: u32) {
        if n == 0 {
            return;
        }
        let mut bits = bits;
        let mut n = n;
        // keep the buffer from overflowing
        while n > 0 {
            let room = 64 - self.n;
            let k = n.min(room).min(32);
            self.buf |= (bits & ((1u64 << k) - 1)) << self.n;
            self.n += k;
            bits >>= k;
            n -= k;
            while self.n >= 8 {
                self.out.push(self.buf as u8);
                self.buf >>= 8;
                self.n -= 8;
            }
        }
    }
}

const LEN_BASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEN_EXTRA: [u8; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];

struct Packer {
    bits: BitOut,
    c: Codes,
}

impl Packer {
    #[inline]
    fn lit(&mut self, b: u8) {
        self.bits.put(self.c.code[b as usize] as u64, LENGTHS[b as usize] as u32);
    }
    fn run(&mut self, run: u32) {
        let mut run = run;
        self.lit(0);
        run -= 1;
        while run >= 258 {
            self.bits.put(self.c.code[285] as u64, LENGTHS[285] as u32 + 1);
            run -= 258;
        }
        if run > 4 {
            let mut i = 28;
            while LEN_BASE[i] as u32 > run || i == 28 {
                i -= 1;
            }
            let sym = 257 + i;
            self.bits.put(self.c.code[sym] as u64, LENGTHS[sym] as u32);
            let ext = LEN_EXTRA[i] as u32;
            let extra = (run - 3) & ((1u32 << ext) - 1);
            self.bits.put(extra as u64, ext + 1);
        } else {
            self.bits.put(0, run * LENGTHS[0] as u32);
        }
    }
    /// One write of data, as fdeflate's compressor takes it.
    fn write(&mut self, data: &[u8]) {
        let mut run = 0u32;
        let n8 = data.len() / 8;
        for k in 0..n8 {
            let chunk = &data[k * 8..k * 8 + 8];
            let v = u64::from_le_bytes(chunk.try_into().unwrap());
            if v == 0 {
                run += 8;
                continue;
            } else if run > 0 {
                let extra = v.trailing_zeros() / 8;
                self.run(run + extra);
                run = 0;
                if extra > 0 {
                    run = v.leading_zeros() / 8;
                    for &b in &chunk[extra as usize..8 - run as usize] {
                        self.lit(b);
                    }
                    continue;
                }
            }
            let tail = v.leading_zeros() / 8;
            if tail > 0 {
                for &b in &chunk[..8 - tail as usize] {
                    self.lit(b);
                }
                run = tail;
                continue;
            }
            for &b in chunk {
                self.lit(b);
            }
        }
        if run > 0 {
            self.run(run);
        }
        for &b in &data[n8 * 8..] {
            self.lit(b);
        }
    }
}

fn stored_size(raw: usize) -> usize {
    let m = u16::MAX as usize;
    (raw.saturating_sub(1) / m) * (m + 5) + (raw % m + 5) + 6
}

fn adler32(data: &[u8]) -> u32 {
    crate::inflate::adler32(data)
}

fn chunk(out: &mut Vec<u8>, kind: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    let mut tb = kind.to_vec();
    tb.extend_from_slice(data);
    out.extend_from_slice(&tb);
    out.extend_from_slice(&crc32(&tb).to_be_bytes());
}

/// The PNG a picture is kept as: 8-bit RGBA, its rows Sub-filtered and packed as fdeflate
/// packs them, unless storing them is smaller (then they go unfiltered).
pub fn encode(img: &Image) -> Vec<u8> {
    let (w, h) = (img.w as usize, img.h as usize);
    let stride = w * 4;
    let mut p = Packer { bits: BitOut { out: Vec::with_capacity(h * (stride + 1) / 2 + 64), buf: 0, n: 0 }, c: codes() };
    p.bits.out.extend_from_slice(&HEADER[..53]);
    p.bits.put(HEADER[53] as u64, 5);
    let mut raw_all: Vec<u8> = Vec::with_capacity(h * (stride + 1));
    let mut filtered = vec![0u8; stride + 1];
    for y in 0..h {
        let row = &img.rgba[y * stride..(y + 1) * stride];
        filtered[0] = 1;
        for i in 0..stride {
            let a = if i >= 4 { row[i - 4] } else { 0 };
            filtered[i + 1] = row[i].wrapping_sub(a);
        }
        p.write(&filtered);
        raw_all.extend_from_slice(&filtered);
    }
    p.bits.put(p.c.code[256] as u64, LENGTHS[256] as u32);
    if p.bits.n > 0 {
        let b = p.bits.buf as u8;
        p.bits.out.push(b);
        p.bits.buf = 0;
        p.bits.n = 0;
    }
    let mut z = std::mem::take(&mut p.bits.out);
    z.extend_from_slice(&adler32(&raw_all).to_be_bytes());
    let raw_len = (stride + 1) * h;
    if z.len() > stored_size(raw_len) {
        // stored, the rows unfiltered
        let mut plain = Vec::with_capacity(raw_len);
        for y in 0..h {
            plain.push(0);
            plain.extend_from_slice(&img.rgba[y * stride..(y + 1) * stride]);
        }
        let mut s = Vec::with_capacity(raw_len + raw_len / 65535 * 5 + 16);
        s.extend_from_slice(&[0x78, 0x01]);
        let m = u16::MAX as usize;
        let mut i = 0;
        loop {
            let n = (plain.len() - i).min(m);
            let last = i + n >= plain.len();
            s.push(last as u8);
            s.extend_from_slice(&(n as u16).to_le_bytes());
            s.extend_from_slice(&(!(n as u16)).to_le_bytes());
            s.extend_from_slice(&plain[i..i + n]);
            i += n;
            if last {
                break;
            }
        }
        s.extend_from_slice(&adler32(&plain).to_be_bytes());
        z = s;
    }
    let mut out = Vec::with_capacity(z.len() + 64);
    out.extend_from_slice(b"\x89PNG\r\n\x1a\n");
    let mut ihdr = Vec::with_capacity(13);
    ihdr.extend_from_slice(&img.w.to_be_bytes());
    ihdr.extend_from_slice(&img.h.to_be_bytes());
    ihdr.extend_from_slice(&[8, 6, 0, 0, 0]);
    chunk(&mut out, b"IHDR", &ihdr);
    chunk(&mut out, b"IDAT", &z);
    chunk(&mut out, b"IEND", &[]);
    out
}
