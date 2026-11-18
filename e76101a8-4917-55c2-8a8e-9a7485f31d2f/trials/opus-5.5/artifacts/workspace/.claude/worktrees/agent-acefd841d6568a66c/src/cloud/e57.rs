//! ASTM E57 (E2807), read from the standard: the 48-byte header, pages of 1024 bytes whose last
//! four are a CRC-32C (not checked), the XML section, and each `data3D` scan's points: a
//! CompressedVector section whose data packets carry a bit-packed bytestream for each field of
//! the prototype, run on from packet to packet. Cartesian or spherical coordinates, placed by
//! the scan's pose; a point marked invalid doesn't come in; colour scaled from `colorLimits`
//! (or its field's range) to eight bits.

use super::read::{Raw, Source};
use super::xml::{self, Element};

const PAGE: u64 = 1024;
const PAGE_DATA: u64 = 1020;
/// The most scans a file may hold.
pub const MAX_SCANS: usize = 4096;
/// The most points the scans of a file may hold together.
pub const MAX_FILE_POINTS: u64 = 100_000_000;
/// The most fields a point may have.
pub const MAX_FIELDS: usize = 32;
/// How far one bytestream may run ahead of the others.
pub const MAX_AHEAD: usize = 4 << 20;

/// The file's bytes, read through its pages.
struct Paged<'a> {
    data: &'a [u8],
}

impl<'a> Paged<'a> {
    /// A physical offset as a logical one, unless it falls on a checksum.
    fn logical(&self, phys: u64) -> Result<u64, String> {
        if phys % PAGE >= PAGE_DATA {
            return Err(format!("offset {} falls on a page's checksum", phys));
        }
        Ok(phys / PAGE * PAGE_DATA + phys % PAGE)
    }
    /// `len` logical bytes from logical offset `pos`.
    fn read(&self, mut pos: u64, mut len: u64) -> Result<Vec<u8>, String> {
        let mut out = Vec::with_capacity(len.min(1 << 24) as usize);
        while len > 0 {
            let page = pos / PAGE_DATA;
            let within = pos % PAGE_DATA;
            let phys = page as u128 * PAGE as u128 + within as u128;
            let n = len.min(PAGE_DATA - within);
            if phys + n as u128 > self.data.len() as u128 {
                return Err(format!("it's cut short: byte {} is past its {} bytes", phys, self.data.len()));
            }
            let phys = phys as u64;
            out.extend_from_slice(&self.data[phys as usize..(phys + n) as usize]);
            pos += n;
            len -= n;
        }
        Ok(out)
    }
}

fn u32_at(b: &[u8], i: usize) -> u32 {
    u32::from_le_bytes([b[i], b[i + 1], b[i + 2], b[i + 3]])
}
fn u64_at(b: &[u8], i: usize) -> u64 {
    let mut a = [0u8; 8];
    a.copy_from_slice(&b[i..i + 8]);
    u64::from_le_bytes(a)
}
fn u16_at(b: &[u8], i: usize) -> u16 {
    u16::from_le_bytes([b[i], b[i + 1]])
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    F32,
    F64,
    Int { min: i64, bits: u32 },
    Scaled { min: i64, bits: u32, scale: f64, offset: f64 },
}

impl Kind {
    fn bits(&self) -> u32 {
        match self {
            Kind::F32 => 32,
            Kind::F64 => 64,
            Kind::Int { bits, .. } | Kind::Scaled { bits, .. } => *bits,
        }
    }
}

struct Field {
    name: String,
    kind: Kind,
    /// The range its values span (for colour): an integer's minimum and maximum.
    lo: f64,
    hi: f64,
}

#[derive(Clone, Copy)]
enum Coords {
    Cartesian([usize; 3]),
    Spherical([usize; 3]),
}

struct Pose {
    r: [[f64; 3]; 3],
    t: [f64; 3],
}

/// What a scan's XML says, checked.
struct Plan {
    count: u64,
    offset: u64,
    fields: Vec<Field>,
    coords: Coords,
    invalid: Option<usize>,
    intensity: Option<usize>,
    rgb: Option<([usize; 3], [(f64, f64); 3])>,
    pose: Option<Pose>,
}

fn bits_for(min: i64, max: i64) -> u32 {
    let span = (max as i128 - min as i128) as u128;
    if span == 0 {
        0
    } else {
        128 - span.leading_zeros()
    }
}

/// A number from an element's text, or nothing where it isn't one.
fn num_text(e: Option<&Element>) -> f64 {
    e.and_then(|e| e.text.trim().parse::<f64>().ok()).unwrap_or(0.0)
}

fn parse_pose(scan: &Element) -> Result<Option<Pose>, String> {
    let pose = match scan.child("pose") {
        None => return Ok(None),
        Some(p) => p,
    };
    let (w, x, y, z) = match pose.child("rotation") {
        None => (1.0, 0.0, 0.0, 0.0),
        Some(r) => (num_text(r.child("w")), num_text(r.child("x")), num_text(r.child("y")), num_text(r.child("z"))),
    };
    let n = (w * w + x * x + y * y + z * z).sqrt();
    if !(n.is_finite() && n > 1e-9) {
        return Err("its pose's rotation isn't a rotation".into());
    }
    let t = match pose.child("translation") {
        None => [0.0; 3],
        Some(t) => [num_text(t.child("x")), num_text(t.child("y")), num_text(t.child("z"))],
    };
    if t.iter().any(|v| !v.is_finite()) {
        return Err("its pose's translation isn't a place".into());
    }
    let (a, b, c, d) = (w / n, x / n, y / n, z / n);
    let r = [
        [1.0 - 2.0 * (c * c + d * d), 2.0 * (b * c - a * d), 2.0 * (b * d + a * c)],
        [2.0 * (b * c + a * d), 1.0 - 2.0 * (b * b + d * d), 2.0 * (c * d - a * b)],
        [2.0 * (b * d - a * c), 2.0 * (c * d + a * b), 1.0 - 2.0 * (b * b + c * c)],
    ];
    Ok(Some(Pose { r, t }))
}

fn int_attr(f: &Element, name: &str, key: &str, default: i64) -> Result<i64, String> {
    match f.attr(key) {
        None => Ok(default),
        Some(s) => s.trim().parse::<i64>().map_err(|_| format!("<{}>'s {} isn't an integer: {}", name, key, s)),
    }
}

fn num_attr(f: &Element, name: &str, key: &str, default: f64) -> Result<f64, String> {
    match f.attr(key) {
        None => Ok(default),
        Some(s) => s.trim().parse::<f64>().map_err(|_| format!("<{}>'s {} isn't a number: {}", name, key, s)),
    }
}

fn parse_field(f: &Element) -> Result<Field, String> {
    let name = f.name.clone();
    let ty = match f.attr("type") {
        Some(t) => t,
        None => return Err(format!("its field <{}> is a thing of no type, which BIMCraft doesn't read", name)),
    };
    match ty {
        "Float" => {
            let kind = if f.attr("precision") == Some("single") { Kind::F32 } else { Kind::F64 };
            Ok(Field { name, kind, lo: 0.0, hi: 255.0 })
        }
        "Integer" | "ScaledInteger" => {
            let min = int_attr(f, &name, "minimum", i64::MIN)?;
            let max = int_attr(f, &name, "maximum", i64::MAX)?;
            if max < min {
                return Err(format!("<{}>'s maximum {} is under its minimum {}", name, max, min));
            }
            let bits = bits_for(min, max);
            if ty == "Integer" {
                return Ok(Field { name, kind: Kind::Int { min, bits }, lo: min as f64, hi: max as f64 });
            }
            let scale = num_attr(f, &name, "scale", 1.0)?;
            let offset = num_attr(f, &name, "offset", 0.0)?;
            if !(scale.is_finite() && scale != 0.0 && offset.is_finite()) {
                return Err(format!("<{}>'s scale {} and offset {} aren't usable", name, scale, offset));
            }
            Ok(Field {
                name,
                kind: Kind::Scaled { min, bits, scale, offset },
                lo: min as f64 * scale + offset,
                hi: max as f64 * scale + offset,
            })
        }
        other => Err(format!("its field <{}> is a {}, which BIMCraft doesn't read", name, other)),
    }
}

fn count_attr(points: &Element, key: &str, missing: &str) -> Result<u64, String> {
    match points.attr(key) {
        None => Err(missing.to_string()),
        Some(s) => match s.trim().parse::<i64>() {
            Ok(v) if v >= 0 => Ok(v as u64),
            Ok(_) => Err(missing.to_string()),
            Err(_) => Err(format!("<points>'s {} isn't an integer: {}", key, s)),
        },
    }
}

fn plan_scan(scan: &Element, total: &mut u64) -> Result<Plan, String> {
    let points = scan.child("points").ok_or_else(|| "it has no points".to_string())?;
    if points.attr("type") != Some("CompressedVector") {
        return Err("its points aren't a CompressedVector".into());
    }
    let count = count_attr(points, "recordCount", "it doesn't say how many points it has")?;
    let offset = count_attr(points, "fileOffset", "it doesn't say where its points are")?;
    if let Some(c) = points.child("codecs") {
        if !c.children.is_empty() {
            return Err("its points are packed by a codec BIMCraft doesn't know; E57 writes bit-packed ones".into());
        }
    }
    let proto = points.child("prototype").ok_or_else(|| "its points have no prototype".to_string())?;
    if proto.children.len() > MAX_FIELDS {
        return Err(format!("its points have {} fields; BIMCraft reads up to {}", proto.children.len(), MAX_FIELDS));
    }
    let mut fields = Vec::new();
    for f in &proto.children {
        fields.push(parse_field(f)?);
    }
    let idx = |n: &str| fields.iter().position(|f| f.name == n);
    let coords = match (idx("cartesianX"), idx("cartesianY"), idx("cartesianZ")) {
        (Some(x), Some(y), Some(z)) => Coords::Cartesian([x, y, z]),
        _ => match (idx("sphericalRange"), idx("sphericalAzimuth"), idx("sphericalElevation")) {
            (Some(r), Some(a), Some(e)) => Coords::Spherical([r, a, e]),
            _ => return Err("its points have neither cartesian nor spherical coordinates".into()),
        },
    };
    if fields.iter().all(|f| f.kind.bits() == 0) {
        return Err("its points hold no data".into());
    }
    *total = total.saturating_add(count);
    if *total > MAX_FILE_POINTS {
        return Err(format!(
            "the scans of a file hold up to {} points together; thin the survey where it was made",
            MAX_FILE_POINTS
        ));
    }
    let invalid = match coords {
        Coords::Cartesian(_) => idx("cartesianInvalidState"),
        Coords::Spherical(_) => idx("sphericalInvalidState"),
    };
    let intensity = idx("intensity");
    let rgb = match (idx("colorRed"), idx("colorGreen"), idx("colorBlue")) {
        (Some(r), Some(g), Some(b)) => {
            let limits = scan.child("colorLimits");
            let mut ranges = [(0.0, 255.0); 3];
            for (k, (ch, fi)) in [("Red", r), ("Green", g), ("Blue", b)].iter().enumerate() {
                let f = &fields[*fi];
                let mut range = if f.hi > f.lo { (f.lo, f.hi) } else { (0.0, 255.0) };
                if let Some(l) = limits {
                    let lo = l.child(&format!("color{}Minimum", ch)).and_then(|e| e.text.trim().parse::<f64>().ok());
                    let hi = l.child(&format!("color{}Maximum", ch)).and_then(|e| e.text.trim().parse::<f64>().ok());
                    if let (Some(lo), Some(hi)) = (lo, hi) {
                        if hi > lo {
                            range = (lo, hi);
                        }
                    }
                }
                ranges[k] = range;
            }
            Some(([r, g, b], ranges))
        }
        _ => None,
    };
    let pose = parse_pose(scan)?;
    Ok(Plan { count, offset, fields, coords, invalid, intensity, rgb, pose })
}

pub struct E57<'a> {
    paged: Paged<'a>,
    scans: Vec<Element>,
}

impl<'a> E57<'a> {
    pub fn new(data: &'a [u8]) -> Result<E57<'a>, String> {
        if !data.starts_with(b"ASTM-E57") {
            return Err("it isn't an E57 file: it doesn't start with ASTM-E57".into());
        }
        if data.len() >= 12 {
            let major = u32_at(data, 8);
            if major != 1 {
                return Err(format!("it's E57 version {}; BIMCraft reads version 1", major));
            }
        }
        if data.len() < 48 {
            return Err("its header is cut short".into());
        }
        let xml_off = u64_at(data, 24);
        let xml_len = u64_at(data, 32);
        let page = u64_at(data, 40);
        if page != PAGE {
            return Err(format!("its pages are {} bytes; E57's are 1024", page));
        }
        if xml_len > data.len() as u64 {
            return Err("its XML is longer than the file".into());
        }
        let paged = Paged { data };
        let start = paged.logical(xml_off)?;
        let text = paged.read(start, xml_len)?;
        let root = xml::parse(&text)?;
        let d3 = root.child("data3D").ok_or_else(|| "it holds no scans (no data3D)".to_string())?;
        if d3.children.len() > MAX_SCANS {
            return Err(format!("it holds {} scans; BIMCraft reads up to {}", d3.children.len(), MAX_SCANS));
        }
        Ok(E57 { paged, scans: d3.children.clone() })
    }

    /// Reads one scan's points, calling `f` with each valid one.
    fn scan_points(
        &self,
        plan: &Plan,
        f: &mut dyn FnMut(&Raw) -> Result<(), String>,
    ) -> Result<(), String> {
        let sec_l = self.paged.logical(plan.offset)?;
        let head = self.paged.read(sec_l, 32)?;
        if head[0] != 1 {
            return Err(format!("its points at offset {} aren't a compressed vector section", plan.offset));
        }
        let sec_len = u64_at(&head, 8);
        let data_off = u64_at(&head, 16);
        let holds = sec_len.saturating_sub(32);
        let bits: u64 = plan.fields.iter().map(|f| f.kind.bits() as u64).sum();
        let need = ((plan.count as u128 * bits as u128 + 7) / 8) as u128;
        if need > holds as u128 {
            return Err(format!(
                "it's cut short: its {} points take {} bytes and its section holds {}",
                plan.count, need, holds
            ));
        }
        let end = sec_l.saturating_add(sec_len);
        let mut pos = self.paged.logical(data_off)?;
        let nf = plan.fields.len();
        let mut streams: Vec<Stream> = (0..nf).map(|_| Stream::default()).collect();
        let mut done: u64 = 0;
        let mut vals = vec![0.0f64; nf];
        while done < plan.count && pos < end {
            let h = self.paged.read(pos, 4)?;
            let ptype = h[0];
            let plen = u16_at(&h, 2) as u64 + 1;
            match ptype {
                1 => {
                    let pk = self.paged.read(pos, plen)?;
                    if pk.len() < 6 {
                        return Err("a data packet is cut short".into());
                    }
                    let n = u16_at(&pk, 4) as usize;
                    if n != nf {
                        return Err(format!("a data packet has {} streams; its prototype has {}", n, nf));
                    }
                    let mut q = 6 + 2 * n;
                    if q > pk.len() {
                        return Err("a data packet is cut short".into());
                    }
                    let lens: Vec<usize> = (0..n).map(|k| u16_at(&pk, 6 + 2 * k) as usize).collect();
                    if q + lens.iter().sum::<usize>() > pk.len() {
                        return Err("a data packet is cut short".into());
                    }
                    for (k, l) in lens.iter().enumerate() {
                        streams[k].push(&pk[q..q + l]);
                        q += l;
                    }
                    // what a packet brings is held to the cap before anything of it is unpacked
                    for st in streams.iter() {
                        if st.pending() > MAX_AHEAD {
                            return Err(format!(
                                "a stream of its points runs {} bytes ahead of the others; up to {}",
                                st.pending(),
                                MAX_AHEAD
                            ));
                        }
                    }
                    // decode what the streams hold now
                    let mut avail = u64::MAX;
                    for (k, fl) in plan.fields.iter().enumerate() {
                        let b = fl.kind.bits() as u64;
                        if b > 0 {
                            avail = avail.min(streams[k].bits_left() / b);
                        }
                    }
                    let take = avail.min(plan.count - done);
                    for _ in 0..take {
                        for (k, fl) in plan.fields.iter().enumerate() {
                            vals[k] = streams[k].value(fl.kind);
                        }
                        done += 1;
                        if let Some(raw) = self.raw_of(plan, &vals) {
                            f(&raw)?;
                        }
                    }
                    for s in streams.iter_mut() {
                        s.compact();
                    }
                }
                0 | 2 => {}
                t => return Err(format!("a packet of type {}, which E57 doesn't have", t)),
            }
            pos = pos.saturating_add(plen);
        }
        if done < plan.count {
            return Err(format!("it's cut short: {} of its {} points are missing", plan.count - done, plan.count));
        }
        Ok(())
    }

    fn raw_of(&self, plan: &Plan, v: &[f64]) -> Option<Raw> {
        if let Some(i) = plan.invalid {
            if v[i] != 0.0 {
                return None;
            }
        }
        let mut p = match plan.coords {
            Coords::Cartesian([x, y, z]) => [v[x], v[y], v[z]],
            Coords::Spherical([r, a, e]) => {
                let (r, az, el) = (v[r], v[a], v[e]);
                [r * el.cos() * az.cos(), r * el.cos() * az.sin(), r * el.sin()]
            }
        };
        // a scan without a pose stands where it is: placed by the identity
        let (m, t) = match &plan.pose {
            Some(pose) => (pose.r, pose.t),
            None => ([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [0.0; 3]),
        };
        p = [
            m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + t[0],
            m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + t[1],
            m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + t[2],
        ];
        let intensity = plan.intensity.map(|i| v[i]);
        let rgb = plan.rgb.map(|(idx, ranges)| {
            let mut c = [0.0; 3];
            for k in 0..3 {
                let (lo, hi) = ranges[k];
                c[k] = (v[idx[k]] - lo) * 255.0 / (hi - lo);
            }
            c
        });
        Some(Raw { p, rgb, intensity, rgb8: None })
    }
}

/// A field's bytestream: what packets have brought of it, read bit by bit.
#[derive(Default)]
struct Stream {
    buf: Vec<u8>,
    /// The next bit to read, from the start of `buf`.
    bit: u64,
}

impl Stream {
    fn push(&mut self, b: &[u8]) {
        self.buf.extend_from_slice(b);
    }
    fn bits_left(&self) -> u64 {
        self.buf.len() as u64 * 8 - self.bit
    }
    /// Bytes held that aren't read through.
    fn pending(&self) -> usize {
        self.buf.len() - (self.bit / 8) as usize
    }
    fn compact(&mut self) {
        let whole = (self.bit / 8) as usize;
        if whole > 0 {
            self.buf.drain(..whole);
            self.bit -= whole as u64 * 8;
        }
    }
    fn take(&mut self, n: u32) -> u64 {
        // n <= 64 bits, least significant first
        let mut v: u64 = 0;
        let mut got = 0u32;
        while got < n {
            let byte = self.buf[(self.bit / 8) as usize] as u64;
            let off = (self.bit % 8) as u32;
            let can = (8 - off).min(n - got);
            let part = (byte >> off) & ((1u64 << can) - 1);
            v |= part << got;
            got += can;
            self.bit += can as u64;
        }
        v
    }
    fn value(&mut self, k: Kind) -> f64 {
        match k {
            Kind::F32 => f32::from_bits(self.take(32) as u32) as f64,
            Kind::F64 => f64::from_bits(self.take(64)),
            Kind::Int { min, bits } => {
                let raw = if bits == 0 { 0 } else { self.take(bits) };
                min.wrapping_add(raw as i64) as f64
            }
            Kind::Scaled { min, bits, scale, offset } => {
                let raw = if bits == 0 { 0 } else { self.take(bits) };
                min.wrapping_add(raw as i64) as f64 * scale + offset
            }
        }
    }
}

impl<'a> Source for E57<'a> {
    fn each(&mut self, f: &mut dyn FnMut(&Raw) -> Result<(), String>) -> Result<(), String> {
        let mut total: u64 = 0;
        let mut offsets: Vec<u64> = Vec::new();
        for (k, scan) in self.scans.iter().enumerate() {
            let prefix = |e: String| format!("scan {}: {}", k + 1, e);
            let plan = plan_scan(scan, &mut total).map_err(prefix)?;
            if offsets.contains(&plan.offset) {
                return Err(prefix(format!(
                    "its points at offset {} are the section another scan reads; each scan keeps its own",
                    plan.offset
                )));
            }
            offsets.push(plan.offset);
            self.scan_points(&plan, f).map_err(prefix)?;
        }
        Ok(())
    }
}
