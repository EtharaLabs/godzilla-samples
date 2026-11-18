//! Taking a picture into a project: a PNG or a JPEG read, laid over white, halved until no side
//! passes 1024 px, and kept as the PNG `png::encode` writes, named `img-` and its FNV-1a hash.

use super::png::{self, Image};

/// The most pixels a picture may have before it's halved.
pub const MAX_PIXELS: u64 = 16_000_000;
/// The longest side a picture is kept with.
pub const MAX_SIDE: u32 = 1024;
/// The most pictures a project holds.
pub const MAX_PICTURES: usize = 24;

/// A picture as a project keeps it.
pub struct Picture {
    pub id: String,
    pub name: String,
    pub png: Vec<u8>,
    pub w: u32,
    pub h: u32,
}

/// Why a picture couldn't be taken: a message, or the panic the original would have had.
pub enum Fail {
    Msg(String),
    Panic { at: &'static str, msg: String },
}

/// The name a picture takes from its file: the file's stem, as Rust's `Path::file_stem` has it.
pub fn stem(path: &str) -> String {
    std::path::Path::new(path).file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default()
}

/// Reads a picture file and makes the picture a project keeps (`path:` leads every message).
pub fn load(path: &str) -> Result<Picture, Fail> {
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => return Err(Fail::Msg(format!("{}: {}", path, crate::commands::io_err(&e)))),
    };
    let img = decode_any(&bytes).map_err(|f| match f {
        Fail::Msg(m) => Fail::Msg(format!("{}: {}", path, m)),
        p => p,
    })?;
    Ok(keep(img, &stem(path)))
}

/// A PNG or a JPEG, by its first bytes, to 8-bit RGBA.
pub fn decode_any(bytes: &[u8]) -> Result<Image, Fail> {
    if bytes.len() >= 8 && &bytes[..8] == b"\x89PNG\r\n\x1a\n" {
        if bytes.len() < 24 {
            return Err(Fail::Msg("it's cut short".into()));
        }
        let w = u32::from_be_bytes(bytes[16..20].try_into().unwrap());
        let h = u32::from_be_bytes(bytes[20..24].try_into().unwrap());
        check_size(w, h)?;
        return match png::decode(bytes) {
            Ok(i) => Ok(i),
            Err(png::Fail::Error(e)) => Err(Fail::Msg(format!("it isn't a PNG BIMCraft can read: {}", e))),
            Err(png::Fail::Panic { at, msg }) => Err(Fail::Panic { at, msg }),
        };
    }
    if bytes.len() >= 3 && bytes[..3] == [0xff, 0xd8, 0xff] {
        return match super::jpeg::decode(bytes) {
            Ok(i) => Ok(i),
            Err(super::jpeg::Fail::Size(w, h)) => {
                check_size(w, h)?;
                Err(Fail::Msg(format!("it's {} by {} px; a picture has up to {} pixels", w, h, MAX_PIXELS)))
            }
            Err(super::jpeg::Fail::Error(e)) => Err(Fail::Msg(format!("it isn't a JPEG BIMCraft can read: {}", e))),
        };
    }
    Err(Fail::Msg("it's neither a PNG nor a JPEG".into()))
}

pub fn check_size(w: u32, h: u32) -> Result<(), Fail> {
    if w == 0 || h == 0 || w as u64 * h as u64 > MAX_PIXELS {
        return Err(Fail::Msg(format!("it's {} by {} px; a picture has up to {} pixels", w, h, MAX_PIXELS)));
    }
    Ok(())
}

/// Lays the picture over white, halves it until it fits, and keeps it as a PNG.
pub fn keep(mut img: Image, name: &str) -> Picture {
    flatten(&mut img);
    while img.w > MAX_SIDE || img.h > MAX_SIDE {
        img = halve(&img);
    }
    let png = png::encode(&img);
    let id = format!("img-{:016x}", crate::util::fnv1a64(&png));
    Picture { id, name: name.to_string(), png, w: img.w, h: img.h }
}

/// Over white: each colour weighted by its alpha, rounded; alpha made opaque.
fn flatten(img: &mut Image) {
    for p in img.rgba.chunks_exact_mut(4) {
        let a = p[3] as u32;
        if a == 255 {
            continue;
        }
        for c in p.iter_mut().take(3) {
            *c = ((*c as u32 * a + 255 * (255 - a) + 127) / 255) as u8;
        }
        p[3] = 255;
    }
}

/// Half the size (at least 1 px a side), each pixel the rounded mean of the 2 by 2 it covers
/// (the last row or column standing in for one that's missing).
fn halve(img: &Image) -> Image {
    let (w, h) = (img.w as usize, img.h as usize);
    let (nw, nh) = ((w / 2).max(1), (h / 2).max(1));
    let mut out = vec![0u8; nw * nh * 4];
    for y in 0..nh {
        let y0 = (2 * y).min(h - 1);
        let y1 = (2 * y + 1).min(h - 1);
        for x in 0..nw {
            let x0 = (2 * x).min(w - 1);
            let x1 = (2 * x + 1).min(w - 1);
            for c in 0..4 {
                let s = img.rgba[(y0 * w + x0) * 4 + c] as u32
                    + img.rgba[(y0 * w + x1) * 4 + c] as u32
                    + img.rgba[(y1 * w + x0) * 4 + c] as u32
                    + img.rgba[(y1 * w + x1) * 4 + c] as u32;
                out[(y * nw + x) * 4 + c] = ((s + 2) / 4) as u8;
            }
        }
    }
    Image { w: nw as u32, h: nh as u32, rgba: out }
}

/// What the original prints when its PNG reader panics, and the error the command gives then.
pub fn panic_error(cmd: &str, at: &str, msg: &str) -> String {
    eprintln!(
        "\nthread 'main' ({}) panicked at {}:\n{}\nnote: run with `RUST_BACKTRACE=1` environment variable to display a backtrace",
        std::process::id(),
        at,
        msg
    );
    format!("internal error in `{}`: {}", cmd, msg)
}
