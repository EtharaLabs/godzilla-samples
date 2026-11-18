//! PLY, as text or binary in either byte order: the header (up to `end_header` in its first MiB),
//! the elements before the vertices stepped over, and the vertices' x, y and z, their colour
//! (red, green and blue; r, g and b; or diffuse_red…) and their intensity.

use super::read::{Raw, Source};

#[derive(Clone, Copy, PartialEq, Debug)]
enum Ty {
    I8,
    U8,
    I16,
    U16,
    I32,
    U32,
    F32,
    F64,
}

impl Ty {
    fn parse(s: &str) -> Option<Ty> {
        Some(match s {
            "char" | "int8" => Ty::I8,
            "uchar" | "uint8" => Ty::U8,
            "short" | "int16" => Ty::I16,
            "ushort" | "uint16" => Ty::U16,
            "int" | "int32" => Ty::I32,
            "uint" | "uint32" => Ty::U32,
            "float" | "float32" => Ty::F32,
            "double" | "float64" => Ty::F64,
            _ => return None,
        })
    }
    fn size(self) -> usize {
        match self {
            Ty::I8 | Ty::U8 => 1,
            Ty::I16 | Ty::U16 => 2,
            Ty::I32 | Ty::U32 | Ty::F32 => 4,
            Ty::F64 => 8,
        }
    }
    fn is_float(self) -> bool {
        matches!(self, Ty::F32 | Ty::F64)
    }
    fn get(self, b: &[u8], big: bool) -> f64 {
        macro_rules! rd {
            ($t:ty, $n:expr) => {{
                let mut a = [0u8; $n];
                a.copy_from_slice(&b[..$n]);
                if big {
                    <$t>::from_be_bytes(a) as f64
                } else {
                    <$t>::from_le_bytes(a) as f64
                }
            }};
        }
        match self {
            Ty::I8 => b[0] as i8 as f64,
            Ty::U8 => b[0] as f64,
            Ty::I16 => rd!(i16, 2),
            Ty::U16 => rd!(u16, 2),
            Ty::I32 => rd!(i32, 4),
            Ty::U32 => rd!(u32, 4),
            Ty::F32 => rd!(f32, 4),
            Ty::F64 => rd!(f64, 8),
        }
    }
}

struct Prop {
    name: String,
    /// None for a list.
    ty: Option<Ty>,
}

struct Element {
    name: String,
    count: u64,
    props: Vec<Prop>,
}

#[derive(Clone, Copy, PartialEq)]
enum Enc {
    Ascii,
    Le,
    Be,
}

pub struct Ply<'a> {
    body: &'a [u8],
    enc: Enc,
    /// Elements before the vertices: their names, counts and record sizes (binary).
    before: Vec<(String, u64, usize)>,
    count: u64,
    /// The vertex record: each property's type, and its offset (binary) or column (text).
    props: Vec<Ty>,
    offsets: Vec<usize>,
    size: usize,
    xyz: [usize; 3],
    rgb: Option<[usize; 3]>,
    intensity: Option<usize>,
    float_rgb: bool,
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    if hay.len() < needle.len() {
        return None;
    }
    (0..=hay.len() - needle.len()).find(|&i| &hay[i..i + needle.len()] == needle)
}

fn prop_index(props: &[Prop], names: &[&str]) -> Option<usize> {
    for n in names {
        if let Some(i) = props.iter().position(|p| p.name.eq_ignore_ascii_case(n)) {
            return Some(i);
        }
    }
    None
}

impl<'a> Ply<'a> {
    pub fn new(data: &'a [u8]) -> Result<Ply<'a>, String> {
        if !data.starts_with(b"ply") {
            return Err("it isn't a PLY file: it doesn't start with ply".into());
        }
        let head = &data[..data.len().min(1 << 20)];
        let end = find(head, b"end_header").ok_or_else(|| "its header has no end_header".to_string())?;
        let header = std::str::from_utf8(&data[..end]).map_err(|_| "its header isn't text".to_string())?;
        let after = end + b"end_header".len();
        let body_start = match data[after..].iter().position(|b| *b == b'\n') {
            Some(i) => after + i + 1,
            None => data.len(),
        };
        let body = &data[body_start..];

        let mut enc = None;
        let mut elements: Vec<Element> = Vec::new();
        for line in header.split('\n').skip(1) {
            let t = line.trim();
            let toks: Vec<&str> = t.split_whitespace().collect();
            if toks.is_empty() {
                continue;
            }
            let bad = || format!("its header says {:?}, which isn't PLY", t);
            match toks[0] {
                "comment" | "obj_info" => {}
                "format" => {
                    if toks.len() != 3 {
                        return Err(bad());
                    }
                    enc = Some(toks[1].to_string());
                }
                "element" => {
                    if toks.len() != 3 {
                        return Err(bad());
                    }
                    let count: u64 =
                        toks[2].parse().map_err(|_| format!("element {} {}: not a count", toks[1], toks[2]))?;
                    elements.push(Element { name: toks[1].to_string(), count, props: Vec::new() });
                }
                "property" => {
                    let el = elements.last_mut().ok_or_else(|| "a property before any element".to_string())?;
                    if toks.len() == 3 {
                        let ty = Ty::parse(toks[1]).ok_or_else(|| {
                            format!("property {} is of type {}, which PLY doesn't have", toks[2], toks[1])
                        })?;
                        el.props.push(Prop { name: toks[2].to_string(), ty: Some(ty) });
                    } else if toks.len() == 5 && toks[1] == "list" {
                        el.props.push(Prop { name: toks[4].to_string(), ty: None });
                    } else {
                        return Err(bad());
                    }
                }
                _ => return Err(bad()),
            }
        }
        let enc = match enc.ok_or_else(|| "its header has no format".to_string())?.as_str() {
            "ascii" => Enc::Ascii,
            "binary_little_endian" => Enc::Le,
            "binary_big_endian" => Enc::Be,
            other => {
                return Err(format!(
                    "its format is {}: PLY is ascii, binary_little_endian or binary_big_endian",
                    other
                ))
            }
        };
        let vi = elements
            .iter()
            .position(|e| e.name == "vertex")
            .ok_or_else(|| "it has no vertex element".to_string())?;
        let v = &elements[vi];
        if v.props.iter().any(|p| p.ty.is_none()) {
            return Err("its vertices hold a list, which a point can't".into());
        }
        let mut xyz = [0usize; 3];
        for (k, n) in ["x", "y", "z"].iter().enumerate() {
            xyz[k] = prop_index(&v.props, &[n]).ok_or_else(|| format!("its vertices have no {}", n))?;
        }
        let r = prop_index(&v.props, &["red", "r", "diffuse_red"]);
        let g = prop_index(&v.props, &["green", "g", "diffuse_green"]);
        let b = prop_index(&v.props, &["blue", "b", "diffuse_blue"]);
        let rgb = match (r, g, b) {
            (Some(r), Some(g), Some(b)) => Some([r, g, b]),
            _ => None,
        };
        let intensity = prop_index(&v.props, &["intensity", "scalar_intensity"]);
        let props: Vec<Ty> = v.props.iter().map(|p| p.ty.unwrap()).collect();
        let mut offsets = Vec::with_capacity(props.len());
        let mut size = 0;
        for t in &props {
            offsets.push(size);
            size += t.size();
        }
        let float_rgb = rgb.map(|c| c.iter().any(|i| props[*i].is_float())).unwrap_or(false);
        let mut before = Vec::new();
        for e in &elements[..vi] {
            if enc != Enc::Ascii && e.props.iter().any(|p| p.ty.is_none()) {
                return Err(format!(
                    "its {} elements, before its vertices, hold a list, which BIMCraft can't step over",
                    e.name
                ));
            }
            let sz: usize = e.props.iter().map(|p| p.ty.map(|t| t.size()).unwrap_or(0)).sum();
            before.push((e.name.clone(), e.count, sz));
        }
        Ok(Ply { body, enc, before, count: v.count, props, offsets, size, xyz, rgb, intensity, float_rgb })
    }

    fn raw_of(&self, val: &dyn Fn(usize) -> f64) -> Raw {
        let p = [val(self.xyz[0]), val(self.xyz[1]), val(self.xyz[2])];
        let rgb = self.rgb.map(|c| {
            let mut v = [val(c[0]), val(c[1]), val(c[2])];
            if self.float_rgb {
                for x in v.iter_mut() {
                    *x *= 255.0;
                }
            }
            v
        });
        let intensity = self.intensity.map(val);
        Raw { p, rgb, intensity, rgb8: None }
    }
}

impl<'a> Source for Ply<'a> {
    fn each(&mut self, f: &mut dyn FnMut(&Raw) -> Result<(), String>) -> Result<(), String> {
        match self.enc {
            Enc::Ascii => {
                let mut lines = self.body.split(|b| *b == b'\n');
                for (name, count, _) in &self.before {
                    let mut left = *count;
                    while left > 0 {
                        match lines.next() {
                            None => return Err(format!("it's cut short in its {} elements", name)),
                            Some(l) => {
                                if l.iter().all(|b| b.is_ascii_whitespace()) {
                                    continue;
                                }
                                left -= 1;
                            }
                        }
                    }
                }
                let mut n: u64 = 0;
                let mut vals: Vec<f64> = Vec::with_capacity(self.props.len());
                // the values a point needs: up to the last of the properties it reads
                let mut need = self.xyz.iter().copied().max().unwrap_or(0);
                if let Some(c) = self.rgb {
                    need = need.max(c[0]).max(c[1]).max(c[2]);
                }
                if let Some(i) = self.intensity {
                    need = need.max(i);
                }
                let need = need + 1;
                while n < self.count {
                    let l = match lines.next() {
                        None => return Err(format!("it's cut short: {} vertices of {}", n, self.count)),
                        Some(l) => l,
                    };
                    let s = std::str::from_utf8(l).map_err(|_| format!("vertex {} isn't text", n + 1))?;
                    vals.clear();
                    for tok in s.split_whitespace() {
                        let v: f64 = tok.parse().map_err(|_| format!("vertex {}: {} isn't a number", n + 1, tok))?;
                        vals.push(v);
                    }
                    if vals.is_empty() {
                        continue;
                    }
                    if vals.len() < need {
                        return Err(format!("vertex {} has too few values", n + 1));
                    }
                    n += 1;
                    let raw = self.raw_of(&|i| vals[i]);
                    f(&raw)?;
                }
                Ok(())
            }
            Enc::Le | Enc::Be => {
                let big = self.enc == Enc::Be;
                let mut off: u128 = 0;
                for (_, count, sz) in &self.before {
                    off += *count as u128 * *sz as u128;
                }
                let need = self.count as u128 * self.size as u128;
                if off + need > self.body.len() as u128 {
                    return Err(format!("it's cut short: {} vertices don't fit in it", self.count));
                }
                let mut pos = off as usize;
                for _ in 0..self.count {
                    let rec = &self.body[pos..pos + self.size];
                    pos += self.size;
                    let props = &self.props;
                    let offsets = &self.offsets;
                    let raw = self.raw_of(&|i| props[i].get(&rec[offsets[i]..], big));
                    f(&raw)?;
                }
                Ok(())
            }
        }
    }
}
