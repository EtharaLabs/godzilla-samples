//! The types elements come in with: named for the file's type (or for what they measure), with
//! the layers of the file's material layer sets and the materials those name.

use super::import::Ctx;
use super::import_build::{self as build, num_name, r3};
use super::import_walls::Usage;
use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// The colour (0–255) and transparency (0–1) a material's style gives it, when it has a style
/// with a shading.
pub fn material_style(ctx: &Ctx, mat: u64) -> Option<(Option<[u64; 3]>, Option<f64>)> {
    let m = &ctx.m;
    for id in m.of("IFCMATERIALDEFINITIONREPRESENTATION") {
        let e = match m.get(*id) {
            Some(e) => e,
            None => continue,
        };
        if e.p(3).r() != Some(mat) {
            continue;
        }
        for sr in e.p(2).refs() {
            let sre = match m.get(sr) {
                Some(x) => x,
                None => continue,
            };
            for si in sre.p(3).refs() {
                if let Some(c) = styled_item_colour(ctx, si) {
                    return Some(c);
                }
            }
        }
    }
    None
}

/// A library material given a style's colour and transparency (none, or nothing to see
/// through, takes it away).
pub fn apply_style(v: &mut Value, rgb: Option<[u64; 3]>, tr: Option<f64>) {
    if let Some(c) = rgb {
        v.set("color", Value::Arr(c.iter().map(|x| Value::u(*x)).collect()));
    }
    match tr.map(|t| (t.clamp(0.0, 1.0) * 100.0).round() as u64).filter(|t| *t > 0) {
        Some(t) => v.set("transparency", Value::u(t)),
        None => {
            v.remove("transparency");
        }
    }
}

/// A new library material of a style's colour and transparency.
pub fn new_material(rgb: Option<[u64; 3]>, tr: Option<f64>) -> Value {
    let c = rgb.unwrap_or([200, 200, 200]);
    let mut v = crate::jobj! {
        "color" => Value::Arr(c.iter().map(|x| Value::u(*x)).collect()),
        "cut" => "none",
        "surface" => "none",
    };
    if let Some(t) = tr.map(|t| (t.clamp(0.0, 1.0) * 100.0).round() as u64).filter(|t| *t > 0) {
        v.set("transparency", Value::u(t));
    }
    v
}

/// The library's materials that the file's materials name, coloured as the file colours them
/// (each in the file's order; one the library hasn't is made only where an element needs it).
pub fn library_colours(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCMATERIAL").to_vec();
    for id in ids {
        let name = match ctx.m.get(id).and_then(|e| e.p(0).str()).map(|n| n.trim().to_string()).filter(|n| !n.is_empty()) {
            Some(n) => n,
            None => continue,
        };
        let style = match material_style(ctx, id) {
            Some(s) => s,
            None => continue,
        };
        if let Some(v) = ctx.pr.section_mut("materials").get_mut(&name) {
            apply_style(v, style.0, style.1);
        }
    }
}

/// The library material of a file's material that the library has (by name), and its GUID.
pub fn existing_material(ctx: &mut Ctx, mat: u64) -> Option<String> {
    let e = ctx.m.get(mat)?;
    if e.name != "IFCMATERIAL" {
        return None;
    }
    let name = e.p(0).str()?.trim().to_string();
    if name.is_empty() || !ctx.pr.section_mut("materials").contains(&name) {
        return None;
    }
    Some(ctx.lib.get(&ctx.pr, "material", &name))
}

/// The surface colour of a styled item (or a surface style): its shading's colour.
pub fn styled_item_colour(ctx: &Ctx, si: u64) -> Option<(Option<[u64; 3]>, Option<f64>)> {
    let m = &ctx.m;
    let e = m.get(si)?;
    let styles: Vec<u64> = match e.name.as_str() {
        "IFCSTYLEDITEM" => {
            let mut v = Vec::new();
            for s in e.p(1).refs() {
                // IFC2x3: IfcPresentationStyleAssignment(Styles)
                match m.get(s).map(|x| x.name.as_str()) {
                    Some("IFCPRESENTATIONSTYLEASSIGNMENT") => v.extend(m.get(s).unwrap().p(0).refs()),
                    _ => v.push(s),
                }
            }
            v
        }
        "IFCSURFACESTYLE" => vec![si],
        _ => return None,
    };
    for s in styles {
        let se = match m.get(s) {
            Some(x) => x,
            None => continue,
        };
        if se.name != "IFCSURFACESTYLE" {
            continue;
        }
        for el in se.p(2).refs() {
            let ee = match m.get(el) {
                Some(x) => x,
                None => continue,
            };
            if ee.name == "IFCSURFACESTYLESHADING" || ee.name == "IFCSURFACESTYLERENDERING" {
                let c = ee.p(0).r().and_then(|c| m.get(c));
                let rgb = c.and_then(|c| {
                    if c.name != "IFCCOLOURRGB" {
                        return None;
                    }
                    let f = |i: usize| -> Option<u64> {
                        let x = c.p(i).num()?;
                        Some((x.clamp(0.0, 1.0) * 255.0).round() as u64)
                    };
                    Some([f(1)?, f(2)?, f(3)?])
                });
                let tr = ee.p(1).num();
                return Some((rgb, tr));
            }
        }
    }
    None
}

/// The library material a file's material comes in as (by its name, given its colour), and
/// its GUID.
pub fn material(ctx: &mut Ctx, mat: u64) -> Option<String> {
    let e = ctx.m.get(mat)?;
    if e.name != "IFCMATERIAL" {
        return None;
    }
    let name = e.p(0).str()?.trim().to_string();
    if name.is_empty() {
        return None;
    }
    let style = material_style(ctx, mat);
    let mats = ctx.pr.section_mut("materials");
    match mats.get_mut(&name) {
        Some(v) => {
            if let Some((rgb, tr)) = style {
                apply_style(v, rgb, tr);
            }
        }
        None => {
            let (rgb, tr) = style.unwrap_or((None, None));
            mats.insert_sorted(&name, new_material(rgb, tr));
        }
    }
    Some(ctx.lib.get(&ctx.pr, "material", &name))
}

/// A material layer set's layers as a type's, when they make up its thickness (`want`, within
/// half a millimetre): each layer's function, material and thickness.
pub fn layers(ctx: &mut Ctx, set: u64, want: f64) -> Option<Vec<Value>> {
    let e = ctx.m.get(set)?.clone();
    let mut out: Vec<(Option<String>, Option<String>, f64)> = Vec::new();
    let mut variable: Vec<bool> = Vec::new();
    let s = ctx.m.scale;
    let ifc4 = ctx.m.is_ifc4();
    // their materials come in only with them
    let sum: f64 = e.p(0).refs().iter().map(|l| ctx.m.get(*l).and_then(|le| le.p(1).num()).unwrap_or(0.0) * s).sum();
    if e.p(0).refs().is_empty() || (r3(sum) - want).abs() >= 0.5 {
        return None;
    }
    for l in e.p(0).refs() {
        let le = ctx.m.get(l)?.clone();
        let th = le.p(1).num().unwrap_or(0.0) * s;
        let mat = le.p(0).r().and_then(|m| material(ctx, m));
        let cat = if ifc4 { le.p(5).str().map(|x| x.to_string()) } else { None };
        // IFC4's Description `Variable`: a layer whose thickness varies (a screed to falls)
        variable.push(ifc4 && le.p(4).str() == Some("Variable"));
        let f = if th == 0.0 {
            Some("membrane".to_string())
        } else {
            cat.as_deref().map(|c| {
                match c {
                    "Finish" => "finish",
                    "Insulation" => "thermal",
                    "LoadBearing" => "structure",
                    "Membrane" => "membrane",
                    _ => "substrate",
                }
                .to_string()
            })
        };
        out.push((f, mat, th));
    }
    if out.is_empty() {
        return None;
    }
    // with no layer saying what it is, the thickest carries the load
    if out.iter().all(|l| l.0.is_none()) {
        let mut best = 0;
        for (i, l) in out.iter().enumerate() {
            if l.2 > out[best].2 {
                best = i;
            }
        }
        out[best].0 = Some("structure".into());
    }
    let v = out
        .into_iter()
        .zip(variable)
        .map(|((f, m, t), var)| {
            let mut o = Map::new();
            o.insert("function", Value::s(f.as_deref().unwrap_or("substrate")));
            o.insert("material", Value::s(m.as_deref().unwrap_or("")));
            o.insert("thickness", Value::f(r3(t)));
            if var {
                o.insert("variable", Value::Bool(true));
            }
            Value::Obj(o)
        })
        .collect();
    Some(v)
}

/// The name of the file's type of an element: its type object's, else its ObjectType.
pub fn file_type_name(ctx: &Ctx, id: u64) -> Option<String> {
    let of_type = ctx.m.type_of.get(&id).and_then(|t| ctx.m.name(*t)).map(|n| n.trim().to_string()).filter(|n| !n.is_empty());
    of_type.or_else(|| ctx.m.object_type(id).map(|n| n.trim().to_string()).filter(|n| !n.is_empty()))
}

/// An element's name where it isn't its type's (the type as the file names it): its mark.
pub fn mark_of(ctx: &Ctx, id: u64, type_name: &str) -> Option<String> {
    let n = ctx.m.name(id)?.trim().to_string();
    if n.is_empty() || n == type_name {
        return None;
    }
    Some(n)
}

/// The layer set of an element: its usage's, else its type's, else its own.
fn layer_set(ctx: &Ctx, id: u64, usage: Option<&Usage>) -> Option<u64> {
    if let Some(u) = usage {
        return Some(u.set);
    }
    let pick = |x: u64| -> Option<u64> {
        let mid = *ctx.m.material_of.get(&x)?;
        let e = ctx.m.get(mid)?;
        match e.name.as_str() {
            "IFCMATERIALLAYERSET" => Some(mid),
            "IFCMATERIALLAYERSETUSAGE" => e.p(0).r(),
            _ => None,
        }
    };
    if let Some(s) = pick(id) {
        return Some(s);
    }
    let t = *ctx.m.type_of.get(&id)?;
    pick(t)
}

/// A type registered for a category: the same one for the same name and values within the
/// import, else under the name (or `Name (2)`…) next to what the project has.
pub fn register(ctx: &mut Ctx, cat: &str, name: &str, v: Value) -> String {
    let key = (cat.to_string(), name.to_string(), build::strip_ids(&v).to_compact());
    if let Some(n) = ctx.type_names.get(&key) {
        return n.clone();
    }
    // a type the project has is taken only when it is the same in every part (a layer is a
    // part of its own: one made now is never one the project had)
    let m = build::types_map(&mut ctx.pr, cat);
    let mut k = 1;
    let n = loop {
        let cand = if k == 1 { name.to_string() } else { format!("{} ({})", name, k) };
        match m.get(&cand) {
            Some(x) => {
                if *x == v {
                    break cand;
                }
            }
            None => {
                m.insert_sorted(&cand, v);
                break cand;
            }
        }
        k += 1;
    };
    ctx.type_names.insert(key, n.clone());
    n
}

/// A wall's type: the file's type name (or `Imported - 200mm`), its thickness, and its layers
/// where they make up that thickness.
pub fn wall_type(ctx: &mut Ctx, id: u64, thickness: f64, usage: Option<&Usage>) -> String {
    let t = build::r2(thickness);
    let name = file_type_name(ctx, id).unwrap_or_else(|| format!("Imported - {}mm", num_name(t)));
    let mut v = crate::jobj! {"thickness" => t};
    if let Some(set) = layer_set(ctx, id, usage) {
        if let Some(ls) = layers(ctx, set, t) {
            v.set("layers", Value::Arr(ls.into_iter().map(with_part_id).collect()));
        }
    }
    register(ctx, "wall", &name, v)
}

/// A part (a layer) as the core writes one new: its id and GUID first.
pub fn with_part_id(v: Value) -> Value {
    let mut o = Map::new();
    o.insert("id", Value::u(0));
    o.insert("guid", Value::s(&crate::rand::guid()));
    if let Value::Obj(m) = v {
        for (k, x) in m.items {
            o.items.push((k, x));
        }
    }
    Value::Obj(o)
}

/// A door's or window's type: the file's type name (or the element's name), its size and sill,
/// and how it opens.
pub fn opening_type(ctx: &mut Ctx, id: u64, cat: &str, width: f64, height: f64, sill: f64, op: Option<&str>) -> Result<String, String> {
    let name = file_type_name(ctx, id).unwrap_or_else(|| format!("Imported {} x {}", num_name(width), num_name(height)));
    // the project refuses a type of no size
    if width <= 0.0 {
        return Err(format!("{} type `{}` width must be above zero, got {}", cat, name, num_name(width)));
    }
    if height <= 0.0 {
        return Err(format!("{} type `{}` height must be above zero, got {}", cat, name, num_name(height)));
    }
    // the sill is each one's own: a type the project has keeps its own
    let sill = build::type_value(&ctx.pr, cat, &name).and_then(|t| t.get("sill")).and_then(|s| s.as_f64()).unwrap_or(sill);
    let mut v = crate::jobj! {"width" => width, "height" => height, "sill" => sill};
    if let Some(o) = op {
        v.set("operation", Value::s(o));
    }
    Ok(register(ctx, cat, &name, v))
}

pub type TypeNames = BTreeMap<(String, String, String), String>;
