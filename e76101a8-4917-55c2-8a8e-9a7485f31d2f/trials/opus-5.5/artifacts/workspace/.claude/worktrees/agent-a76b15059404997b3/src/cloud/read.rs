//! Reading a scan: the format by its extension, a first pass to measure the file (`Stats`), and
//! a second to keep its points: every `stride`th so the cap is never passed, then one in each
//! cube of `spacing`, as `f32` about the middle of its bounds, with colour in eight bits.

use super::{e57, las, ply, text};

/// The most scans a project holds.
pub const MAX_CLOUDS: usize = 16;
/// The most points a project's scans hold among them.
pub const MAX_CLOUD_POINTS: u64 = 5_000_000;
/// The most files a scan's stations come from.
pub const MAX_STATIONS: usize = 256;
/// The widest a scan may be along any axis, in mm (its points are `f32` about its middle).
pub const MAX_SPAN: f64 = 20_000_000.0;
/// How far a point may lie from its file's origin, in mm.
pub const MAX_FAR: f64 = 1e12;
/// A point's grey where its file has no colour for it.
pub const GREY: u8 = 160;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Format {
    Pts,
    Xyz,
    Ply,
    Las,
    E57,
}

impl Format {
    /// The format a file's extension names, or why it isn't one BIMCraft reads.
    pub fn from_path(path: &str) -> Result<Format, String> {
        let ext = std::path::Path::new(path)
            .extension()
            .map(|e| e.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default();
        match ext.as_str() {
            "pts" => Ok(Format::Pts),
            "xyz" | "txt" => Ok(Format::Xyz),
            "ply" => Ok(Format::Ply),
            "las" => Ok(Format::Las),
            "e57" => Ok(Format::E57),
            "laz" => Err("LAZ is compressed LAS, which BIMCraft doesn't read: decompress it to LAS first (laszip or PDAL)".into()),
            "rcp" | "rcs" => {
                Err("ReCap's RCP and RCS are closed formats: export the scan from ReCap as E57, LAS or PTS".into())
            }
            _ => Err(format!("a .{} file isn't a point cloud BIMCraft reads: PTS, XYZ, PLY, LAS or E57", ext)),
        }
    }
}

pub struct Options {
    /// mm in each of the file's units.
    pub scale: f64,
    /// The most points to keep.
    pub cap: u64,
    /// One point kept in each cube this wide (mm); 0 keeps them all.
    pub spacing: f64,
}

/// How a file's colour values come to eight bits.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Depth {
    /// Floats from nought to one.
    Unit,
    /// Eight bits already.
    Byte,
    /// Sixteen bits.
    Word,
}

/// A point as its file gives it: its place in the file's units, and what colours it.
#[derive(Clone, Copy, Default)]
pub struct Raw {
    pub p: [f64; 3],
    pub rgb: Option<[f64; 3]>,
    pub intensity: Option<f64>,
    /// A colour the reader has brought to eight bits itself (E57's, scaled by its limits).
    pub rgb8: Option<[u8; 3]>,
}

/// What a file's colour values are: whether they are floats (so nought to one may be their range).
#[derive(Clone, Copy, Default)]
pub struct ColourKind {
    pub float: bool,
}

/// The source of a file's points, walked twice.
pub trait Source {
    /// Calls `f` with each point in the file's order; stops at the first error.
    fn each(&mut self, f: &mut dyn FnMut(&Raw) -> Result<(), String>) -> Result<(), String>;
    /// Whether colours of fractions no greater than one are read as nought to one (text's are).
    fn unit_rule(&self) -> bool {
        false
    }
}

/// What the first pass learns.
#[derive(Clone)]
pub struct Stats {
    pub count: u64,
    pub lo: [f64; 3],
    pub hi: [f64; 3],
    pub ilo: f64,
    pub ihi: f64,
    pub has_i: bool,
    pub cmax: f64,
    pub has_rgb: bool,
    pub frac_rgb: bool,
    pub has_rgb8: bool,
}

impl Stats {
    fn new() -> Stats {
        Stats {
            count: 0,
            lo: [f64::INFINITY; 3],
            hi: [f64::NEG_INFINITY; 3],
            ilo: f64::INFINITY,
            ihi: f64::NEG_INFINITY,
            has_i: false,
            cmax: f64::NEG_INFINITY,
            has_rgb: false,
            frac_rgb: false,
            has_rgb8: false,
        }
    }
    pub fn has_colour(&self) -> bool {
        self.has_rgb || self.has_i || self.has_rgb8
    }
}

/// A scan read: its points about `origin` (mm), their colours, and how many the file held.
#[derive(Clone)]
pub struct Scan {
    pub origin: [f64; 3],
    pub points: Vec<[f32; 3]>,
    pub colours: Option<Vec<[u8; 3]>>,
    pub read: u64,
}

const AXES: [&str; 3] = ["x", "y", "z"];

/// The place of a point in mm, checked: a number, and not past `MAX_FAR`.
fn place(raw: &Raw, scale: f64, n: u64) -> Result<[f64; 3], String> {
    let mut p = [0.0; 3];
    for k in 0..3 {
        let mm = raw.p[k] * scale;
        if !mm.is_finite() {
            return Err(format!("point {} isn't a number along {}", n, AXES[k]));
        }
        if !(mm.abs() <= MAX_FAR) {
            return Err(format!(
                "point {} lies {:.0} mm from the file's origin, farther than {:.0} mm",
                n, mm, MAX_FAR
            ));
        }
        p[k] = mm;
    }
    Ok(p)
}

/// Reads a file: what it holds, thinned to `opts`.
pub fn read(path: &str, fmt: Format, opts: &Options) -> Result<Scan, String> {
    let data = std::fs::read(path).map_err(|e| e.to_string())?;
    if !(opts.spacing >= 0.0) {
        return Err(format!("a spacing of {} mm isn't one", opts.spacing));
    }
    match fmt {
        Format::Pts => scan_of(&mut text::Text::new(&data, true), opts),
        Format::Xyz => scan_of(&mut text::Text::new(&data, false), opts),
        Format::Ply => scan_of(&mut ply::Ply::new(&data)?, opts),
        Format::Las => scan_of(&mut las::Las::new(&data)?, opts),
        Format::E57 => scan_of(&mut e57::E57::new(&data)?, opts),
    }
}

/// The two passes over a source.
pub fn scan_of(src: &mut dyn Source, opts: &Options) -> Result<Scan, String> {
    let scale = opts.scale;
    // the first pass: measure
    let mut st = Stats::new();
    src.each(&mut |r: &Raw| {
        let p = place(r, scale, st.count + 1)?;
        st.count += 1;
        for k in 0..3 {
            if p[k] < st.lo[k] {
                st.lo[k] = p[k];
            }
            if p[k] > st.hi[k] {
                st.hi[k] = p[k];
            }
        }
        if let Some(i) = r.intensity {
            st.has_i = true;
            if !i.is_finite() {
                // a value that isn't one takes no part in the range
            } else if i < st.ilo {
                st.ilo = i;
            }
            if i.is_finite() && i > st.ihi {
                st.ihi = i;
            }
        }
        if let Some(c) = r.rgb {
            st.has_rgb = true;
            for v in c {
                if !v.is_finite() {
                    continue;
                }
                if v > st.cmax {
                    st.cmax = v;
                }
                if v.fract() != 0.0 {
                    st.frac_rgb = true;
                }
            }
        }
        if r.rgb8.is_some() {
            st.has_rgb8 = true;
        }
        Ok(())
    })?;
    if st.count == 0 {
        return Err("it holds no points".into());
    }
    for k in 0..3 {
        let w = st.hi[k] - st.lo[k];
        if w > MAX_SPAN {
            return Err(format!("it's {:.0} mm wide along {}; up to {:.0} mm", w, AXES[k], MAX_SPAN));
        }
    }
    let origin = [(st.lo[0] + st.hi[0]) / 2.0, (st.lo[1] + st.hi[1]) / 2.0, (st.lo[2] + st.hi[2]) / 2.0];
    let depth = if src.unit_rule() && st.frac_rgb && st.cmax <= 1.0 {
        Depth::Unit
    } else if st.cmax <= 255.0 {
        Depth::Byte
    } else {
        Depth::Word
    };
    let stride = stride_for(st.count, opts.cap);
    let lo = st.lo;
    let spacing = opts.spacing;
    let mut seen: std::collections::HashSet<[i64; 3]> = std::collections::HashSet::new();
    let with_colour = st.has_colour();
    let mut points: Vec<[f32; 3]> = Vec::new();
    let mut colours: Vec<[u8; 3]> = Vec::new();
    let mut n: u64 = 0;
    src.each(&mut |r: &Raw| {
        let i = n;
        n += 1;
        if i % stride != 0 {
            return Ok(());
        }
        let p = place(r, scale, i + 1)?;
        if spacing > 0.0 {
            let key = cube(&p, &lo, spacing);
            if !seen.insert(key) {
                return Ok(());
            }
        }
        points.push([(p[0] - origin[0]) as f32, (p[1] - origin[1]) as f32, (p[2] - origin[2]) as f32]);
        if with_colour {
            colours.push(colour_of(r, &st, depth));
        }
        Ok(())
    })?;
    Ok(Scan { origin, points, colours: if with_colour { Some(colours) } else { None }, read: st.count })
}

/// Every how many points one is kept so `cap` isn't passed.
pub fn stride_for(count: u64, cap: u64) -> u64 {
    if cap == 0 {
        return count.max(1);
    }
    if count <= cap {
        1
    } else {
        count.div_ceil(cap)
    }
}

/// The cube of `spacing` a point lies in, counted from `lo`.
pub fn cube(p: &[f64; 3], lo: &[f64; 3], spacing: f64) -> [i64; 3] {
    [
        ((p[0] - lo[0]) / spacing).floor() as i64,
        ((p[1] - lo[1]) / spacing).floor() as i64,
        ((p[2] - lo[2]) / spacing).floor() as i64,
    ]
}

pub fn byte_of(v: f64, depth: Depth) -> u8 {
    if !v.is_finite() {
        return GREY;
    }
    let x = match depth {
        Depth::Unit => v * 255.0,
        Depth::Byte => v,
        Depth::Word => v / 257.0,
    };
    x.round().clamp(0.0, 255.0) as u8
}

pub fn grey_of(i: f64, st: &Stats) -> u8 {
    if i.is_finite() && st.ihi > st.ilo {
        ((i - st.ilo) / (st.ihi - st.ilo) * 255.0).round().clamp(0.0, 255.0) as u8
    } else {
        GREY
    }
}

fn colour_of(r: &Raw, st: &Stats, depth: Depth) -> [u8; 3] {
    if let Some(c) = r.rgb8 {
        return c;
    }
    if let Some(c) = r.rgb {
        return [byte_of(c[0], depth), byte_of(c[1], depth), byte_of(c[2], depth)];
    }
    if let Some(i) = r.intensity {
        let g = grey_of(i, st);
        return [g, g, g];
    }
    [GREY, GREY, GREY]
}
