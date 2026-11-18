//! ASPRS LAS 1.0 to 1.4, uncompressed: the public header, then point records of formats 0 to 10,
//! each scaled and offset, with their intensity, and their colour where the format has one.

use super::read::{Raw, Source};

/// Each point format's record length, and where its colour is (if it has one).
const FORMATS: [(usize, Option<usize>); 11] = [
    (20, None),
    (28, None),
    (26, Some(20)),
    (34, Some(28)),
    (57, None),
    (63, Some(28)),
    (30, None),
    (36, Some(30)),
    (38, Some(30)),
    (59, None),
    (67, Some(30)),
];

pub struct Las<'a> {
    data: &'a [u8],
    offset: usize,
    count: u64,
    reclen: usize,
    rgb_at: Option<usize>,
    scale: [f64; 3],
    add: [f64; 3],
}

fn u16_at(b: &[u8], i: usize) -> u16 {
    u16::from_le_bytes([b[i], b[i + 1]])
}
fn u32_at(b: &[u8], i: usize) -> u32 {
    u32::from_le_bytes([b[i], b[i + 1], b[i + 2], b[i + 3]])
}
fn u64_at(b: &[u8], i: usize) -> u64 {
    let mut a = [0u8; 8];
    a.copy_from_slice(&b[i..i + 8]);
    u64::from_le_bytes(a)
}
fn f64_at(b: &[u8], i: usize) -> f64 {
    f64::from_bits(u64_at(b, i))
}

impl<'a> Las<'a> {
    pub fn new(data: &'a [u8]) -> Result<Las<'a>, String> {
        if !data.starts_with(b"LASF") {
            return Err("it isn't a LAS file: it doesn't start with LASF".into());
        }
        if data.len() < 227 {
            return Err("its header is cut short".into());
        }
        let (major, minor) = (data[24], data[25]);
        if major != 1 || minor > 4 {
            return Err(format!("it's LAS {}.{}; BIMCraft reads 1.0 to 1.4", major, minor));
        }
        let hsize = u16_at(data, 94) as usize;
        if hsize < 227 || data.len() < hsize {
            return Err("its header is cut short".into());
        }
        let offset = u32_at(data, 96) as u64;
        let fmt = data[104];
        let reclen = u16_at(data, 105) as usize;
        let legacy = u32_at(data, 107) as u64;
        if fmt & 0xC0 != 0 {
            return Err("its points are compressed (LAZ): decompress it to LAS first (laszip or PDAL)".into());
        }
        if fmt > 10 {
            return Err(format!("its point format {} isn't one LAS has (0 to 10)", fmt));
        }
        let (need, rgb_at) = FORMATS[fmt as usize];
        if reclen < need {
            return Err(format!("its point records are {} bytes; point format {} needs {}", reclen, fmt, need));
        }
        let mut scale = [0.0; 3];
        let mut add = [0.0; 3];
        let axes = ["x", "y", "z"];
        for k in 0..3 {
            scale[k] = f64_at(data, 131 + 8 * k);
            add[k] = f64_at(data, 155 + 8 * k);
            if scale[k] == 0.0 || !scale[k].is_finite() {
                return Err(format!("its scale along {} is {}", axes[k], scale[k]));
            }
            if !add[k].is_finite() {
                return Err(format!("its offset along {} is {}", axes[k], add[k]));
            }
        }
        // LAS 1.4 counts its points in 64 bits too, the only count of its new point formats
        let count64 = if minor >= 4 && hsize >= 255 { u64_at(data, 247) } else { 0 };
        let count = if minor >= 4 && fmt >= 6 {
            count64
        } else if legacy != 0 {
            legacy
        } else {
            count64
        };
        let end = offset as u128 + count as u128 * reclen as u128;
        if offset < hsize as u64 || end > data.len() as u128 {
            return Err(format!(
                "its points are cut short: {} of {} bytes from byte {} don't fit in {} bytes",
                count,
                reclen,
                offset,
                data.len()
            ));
        }
        Ok(Las { data, offset: offset as usize, count, reclen, rgb_at, scale, add })
    }
}

impl<'a> Source for Las<'a> {
    fn each(&mut self, f: &mut dyn FnMut(&Raw) -> Result<(), String>) -> Result<(), String> {
        let mut pos = self.offset;
        for _ in 0..self.count {
            let r = &self.data[pos..pos + self.reclen];
            pos += self.reclen;
            let mut p = [0.0; 3];
            for k in 0..3 {
                let raw = i32::from_le_bytes([r[4 * k], r[4 * k + 1], r[4 * k + 2], r[4 * k + 3]]);
                p[k] = raw as f64 * self.scale[k] + self.add[k];
            }
            let intensity = Some(u16_at(r, 12) as f64);
            let rgb = self.rgb_at.map(|a| [u16_at(r, a) as f64, u16_at(r, a + 2) as f64, u16_at(r, a + 4) as f64]);
            f(&Raw { p, rgb, intensity, rgb8: None })?;
        }
        Ok(())
    }
}
