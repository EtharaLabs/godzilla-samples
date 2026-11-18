//! A type's compound structure: its layers (width, material, deck, function) after the schema's
//! tag of `VerticalRegionsStructure`.

use super::bytes::*;
use super::doc::Doc;

#[derive(Clone, Debug)]
pub struct Layer {
    /// Feet.
    pub width: f64,
    pub material: Option<u64>,
    pub function: u32,
}

/// What a type's data says of its layers.
#[derive(Clone, Debug)]
pub enum Layers {
    /// No structure in its data, an empty one, or one that does not read.
    None,
    /// Layers that read, of which none has a thickness.
    Thin,
    Read(Vec<Layer>),
}

/// BIMCraft's function for a layer's function in the file (1 structure, 2 substrate, 3 thermal,
/// 4 and 5 finish, 100 membrane, 200 a structural deck, 0 none).
pub fn function_name(f: u32) -> Option<&'static str> {
    match f {
        1 | 200 => Some("structure"),
        0 | 2 => Some("substrate"),
        3 => Some("thermal"),
        4 | 5 => Some("finish"),
        100 => Some("membrane"),
        _ => None,
    }
}

fn record_len(release: u32) -> usize {
    if release >= 2026 {
        41
    } else if release >= 2024 {
        37
    } else {
        29
    }
}

/// The layers of a type, from its data.
pub fn layers(doc: &Doc, d: &[u8], is_material: &dyn Fn(u64) -> bool) -> Layers {
    let tag = match doc.schema.tag("VerticalRegionsStructure") {
        Some(t) => t,
        None => return Layers::None,
    };
    let mut mk = vec![0xffu8; 4];
    mk.extend_from_slice(&tag.to_le_bytes());
    let p = match find(d, &mk, 0, d.len()) {
        Some(p) => p + 6,
        None => return Layers::None,
    };
    let n = match rd_u32(d, p) {
        Some(n) => n as usize,
        None => return Layers::None,
    };
    let rl = record_len(doc.release);
    if n == 0 || n > 64 || p + 4 + n * rl > d.len() {
        return Layers::None;
    }
    let wide = doc.wide();
    let mut out = Vec::new();
    for k in 0..n {
        let o = p + 4 + k * rl;
        let width = rd_f64(d, o).unwrap();
        let (material, deck, function) = if wide {
            (rd_u64(d, o + 8).unwrap(), rd_u64(d, o + 16).unwrap(), rd_u32(d, o + 24).unwrap())
        } else {
            let f = rd_u32(d, o + 8).unwrap();
            let m = rd_u32(d, o + 16).unwrap();
            let dk = rd_u32(d, o + 20).unwrap();
            let ext = |v: u32| if v == u32::MAX { u64::MAX } else { v as u64 };
            (ext(m), ext(dk), f)
        };
        let _ = deck;
        if function_name(function).is_none() {
            return Layers::None;
        }
        if !width.is_finite() || width < 0.0 || width > 100.0 {
            return Layers::None;
        }
        let material = if material == u64::MAX {
            None
        } else if is_material(material) {
            Some(material)
        } else {
            return Layers::None;
        };
        out.push(Layer { width, material, function });
    }
    // a layer of no width that is not a membrane (a deck) adds nothing and is no layer here
    let kept: Vec<Layer> = out.into_iter().filter(|l| l.width > 0.0 || l.function == 100).collect();
    let total: f64 = kept.iter().map(|l| l.width).sum();
    if total <= 0.0 {
        return Layers::Thin;
    }
    Layers::Read(kept)
}
