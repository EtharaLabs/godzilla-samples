//! A type as the original holds it, per category: its fields with their defaults, as the file
//! writes them (field order, materials by GUID), as replies show them (keys sorted, materials by
//! name), and the model's rules on it, in the order the original checks them.

use super::layers::{self, real_guid, Layer, MAX_LAYERS};
use crate::commands::params::MAX_MM;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::structure::common::R;

/// The shape of a category's types.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Shape {
    /// Wall, floor, roof, ceiling: a thickness, maybe layers (a ceiling: and a grid).
    Layered,
    /// Door, window: an opening's width and height, its sill, how it operates.
    Opening,
    /// Column, structural column, footing: a section.
    Column,
    /// Beam, strip footing and the MEP runs: a section and a material.
    Run,
    /// Railing: the rail's height and the balusters' spacing.
    Railing,
}

pub fn shape(cat: &str) -> Option<Shape> {
    Some(match cat {
        "wall" | "floor" | "roof" | "ceiling" => Shape::Layered,
        "door" | "window" => Shape::Opening,
        "column" | "structuralcolumn" | "footing" => Shape::Column,
        "railing" => Shape::Railing,
        c if crate::structure::common::is_run(c) => Shape::Run,
        _ => return None,
    })
}

/// How the original names a category's types in its messages.
pub fn word(cat: &str) -> &str {
    match cat {
        "structuralcolumn" => "structural column",
        c => c,
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Spec {
    Layered { thickness: f64, grid: Option<f64>, layers: Vec<Layer> },
    Opening { width: f64, height: f64, sill: f64, operation: Option<String> },
    Column { width: f64, depth: f64, round: bool },
    Run { width: f64, depth: f64, round: bool, material: Option<String> },
    Railing { height: f64, spacing: f64 },
}

fn num(v: &Value, k: &str) -> f64 {
    v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

/// A material reference as the file holds it (its GUID; or a name, from a hand-made file): the
/// material's name, else the reference itself.
pub fn material_name(pr: &Project, r: &str) -> String {
    if let Some(g) = crate::structure::members::read::parse_guid(r) {
        if let Some(id) = crate::structure::members::read::lib_by_guid(pr, &g) {
            let e = &pr.library[&id];
            if e.get("kind").and_then(|k| k.as_str()) == Some("material") {
                if let Some(n) = e.get("name").and_then(|n| n.as_str()) {
                    return n.to_string();
                }
            }
        }
    }
    r.to_string()
}

/// Whether the library has a material of this name.
pub fn has_material(pr: &Project, name: &str) -> bool {
    pr.section("materials").map(|m| m.contains(name)).unwrap_or(false)
}

impl Spec {
    /// A type as the file holds it, its materials by name.
    pub fn from_file(pr: &Project, cat: &str, v: &Value) -> Option<Spec> {
        let mat = |r: &str| material_name(pr, r);
        Some(match shape(cat)? {
            Shape::Layered => Spec::Layered {
                thickness: num(v, "thickness"),
                grid: if cat == "ceiling" { Some(num(v, "grid")) } else { None },
                layers: v
                    .get("layers")
                    .and_then(|l| l.as_arr())
                    .map(|a| a.iter().map(|x| layers::from_file(x, &mat)).collect())
                    .unwrap_or_default(),
            },
            Shape::Opening => Spec::Opening {
                width: num(v, "width"),
                height: num(v, "height"),
                sill: num(v, "sill"),
                operation: v.get("operation").and_then(|o| o.as_str()).map(|s| s.to_string()),
            },
            Shape::Column => Spec::Column {
                width: num(v, "width"),
                depth: num(v, "depth"),
                round: v.get("round").and_then(|r| r.as_bool()).unwrap_or(false),
            },
            Shape::Run => Spec::Run {
                width: num(v, "width"),
                depth: num(v, "depth"),
                round: v.get("round").and_then(|r| r.as_bool()).unwrap_or(false),
                material: v.get("material").and_then(|m| m.as_str()).filter(|m| !m.is_empty()).map(mat),
            },
            Shape::Railing => Spec::Railing { height: num(v, "height"), spacing: num(v, "spacing") },
        })
    }

    /// As the file holds it: fields in the original's order, materials by their GUIDs
    /// (`material_ref` gives a material's from its name).
    pub fn to_file(&self, material_ref: &dyn Fn(&str) -> String) -> Value {
        let mut m = Map::new();
        match self {
            Spec::Layered { thickness, grid, layers } => {
                m.insert("thickness", Value::f(*thickness));
                if let Some(g) = grid {
                    m.insert("grid", Value::f(*g));
                }
                if !layers.is_empty() {
                    let ls: Vec<Value> = layers
                        .iter()
                        .map(|l| {
                            let r = if l.material.is_empty() { String::new() } else { material_ref(&l.material) };
                            layers::to_file(l, &r)
                        })
                        .collect();
                    m.insert("layers", Value::Arr(ls));
                }
            }
            Spec::Opening { width, height, sill, operation } => {
                m.insert("width", Value::f(*width));
                m.insert("height", Value::f(*height));
                m.insert("sill", Value::f(*sill));
                if let Some(o) = operation {
                    m.insert("operation", Value::s(o));
                }
            }
            Spec::Column { width, depth, round } => {
                m.insert("width", Value::f(*width));
                m.insert("depth", Value::f(*depth));
                m.insert("round", Value::Bool(*round));
            }
            Spec::Run { width, depth, round, material } => {
                m.insert("width", Value::f(*width));
                m.insert("depth", Value::f(*depth));
                m.insert("round", Value::Bool(*round));
                if let Some(n) = material {
                    m.insert("material", Value::s(&material_ref(n)));
                }
            }
            Spec::Railing { height, spacing } => {
                m.insert("height", Value::f(*height));
                m.insert("spacing", Value::f(*spacing));
            }
        }
        Value::Obj(m)
    }

    /// As replies show it: keys sorted, materials by name. `fresh` says which layers this
    /// command made (shown without the id and GUID they get after it).
    pub fn view(&self, fresh: &[bool]) -> Value {
        let mut m = Map::new();
        match self {
            Spec::Layered { thickness, grid, layers } => {
                if let Some(g) = grid {
                    m.insert("grid", Value::f(*g));
                }
                if !layers.is_empty() {
                    let ls: Vec<Value> = layers
                        .iter()
                        .enumerate()
                        .map(|(i, l)| {
                            if fresh.get(i).copied().unwrap_or(false) {
                                let mut x = l.clone();
                                x.id = None;
                                x.guid = None;
                                x.view()
                            } else {
                                l.view()
                            }
                        })
                        .collect();
                    m.insert("layers", Value::Arr(ls));
                }
                m.insert("thickness", Value::f(*thickness));
            }
            Spec::Opening { width, height, sill, operation } => {
                m.insert("height", Value::f(*height));
                if let Some(o) = operation {
                    m.insert("operation", Value::s(o));
                }
                m.insert("sill", Value::f(*sill));
                m.insert("width", Value::f(*width));
            }
            Spec::Column { width, depth, round } => {
                m.insert("depth", Value::f(*depth));
                m.insert("round", Value::Bool(*round));
                m.insert("width", Value::f(*width));
            }
            Spec::Run { width, depth, round, material } => {
                m.insert("depth", Value::f(*depth));
                if let Some(n) = material {
                    m.insert("material", Value::s(n));
                }
                m.insert("round", Value::Bool(*round));
                m.insert("width", Value::f(*width));
            }
            Spec::Railing { height, spacing } => {
                m.insert("height", Value::f(*height));
                m.insert("spacing", Value::f(*spacing));
            }
        }
        Value::Obj(m)
    }
}

// ---------------------------------------------------------------- the rules

/// Numbers as the original's messages show them (Rust's Display).
fn d(x: f64) -> String {
    format!("{}", x)
}

fn usable(x: f64) -> bool {
    x.is_finite() && x.abs() <= MAX_MM
}

/// A size: usable, and above zero.
fn size(w: &str, name: &str, field: &str, x: f64) -> R<()> {
    if !usable(x) {
        return Err(format!("{} type `{}` {}: {} is not a usable number", w, name, field, d(x)));
    }
    if x <= 0.0 {
        return Err(format!("{} type `{}` {} must be above zero, got {}", w, name, field, d(x)));
    }
    Ok(())
}

/// The longest a name may be, in characters.
pub const MAX_TEXT: usize = 256;

/// The largest a layer's thickness and their sum may differ, mm.
pub const SUM_TOL: f64 = 1e-6;

/// The model's rules on one type, in the original's order; `materials` says whether the
/// library has a material of a name.
pub fn validate(cat: &str, name: &str, t: &Spec, has_mat: &dyn Fn(&str) -> bool) -> R<()> {
    let w = word(cat);
    match t {
        Spec::Opening { width, height, sill, .. } => {
            size(w, name, "width", *width)?;
            size(w, name, "height", *height)?;
            if !usable(*sill) {
                return Err(format!("{} type `{}` sill: {} is not a usable number", w, name, d(*sill)));
            }
        }
        Spec::Layered { thickness, grid, layers } => {
            size(w, name, "thickness", *thickness)?;
            if layers.len() > MAX_LAYERS {
                return Err(format!("{} type `{}`: more than {} layers", w, name, MAX_LAYERS));
            }
            for (i, l) in layers.iter().enumerate() {
                if l.material.chars().count() > MAX_TEXT {
                    return Err(format!(
                        "{} type `{}` layer {}: material is longer than {} characters",
                        w,
                        name,
                        i + 1,
                        MAX_TEXT
                    ));
                }
                if !l.material.is_empty() && !has_mat(&l.material) {
                    return Err(format!(
                        "{} type `{}` layer {}: material `{}` isn't in the library; add it with `material`",
                        w,
                        name,
                        i + 1,
                        l.material
                    ));
                }
                size(w, name, &format!("layer {} thickness", i + 1), l.thickness)?;
            }
            let variable = layers.iter().filter(|l| l.variable).count();
            if variable > 0 && (cat == "wall" || cat == "ceiling") {
                return Err(format!(
                    "{} type `{}`: only a floor's or a roof's layer can be variable, to take up a shaped top's falls",
                    w, name
                ));
            }
            if variable > 1 {
                return Err(format!(
                    "{} type `{}`: {} variable layers; a type has one variable layer at most",
                    w, name, variable
                ));
            }
            if !layers.is_empty() {
                let sum = layers_sum(layers);
                if (sum - thickness).abs() > SUM_TOL {
                    return Err(format!(
                        "{} type `{}`: its layers add up to {} mm, not its thickness, {} mm",
                        w,
                        name,
                        d(sum),
                        d(*thickness)
                    ));
                }
            }
            if let Some(g) = grid {
                if !(*g == 0.0 || (*g >= 100.0 && *g <= MAX_MM)) {
                    return Err(format!(
                        "{} type `{}`: grid {} mm; its tiles are 100 mm or wider, or 0 for none",
                        w,
                        name,
                        d(*g)
                    ));
                }
            }
        }
        Spec::Column { width, depth, .. } => {
            size(w, name, "width", *width)?;
            size(w, name, "depth", *depth)?;
        }
        Spec::Run { width, depth, round, material } => {
            size(w, name, "width", *width)?;
            size(w, name, "depth", *depth)?;
            if *round && depth != width {
                return Err(format!(
                    "{} type `{}`: a round section is as deep as it is wide ({} mm), not {} mm",
                    w,
                    name,
                    d(*width),
                    d(*depth)
                ));
            }
            if let Some(m) = material {
                if m.chars().count() > MAX_TEXT {
                    return Err(format!("{} type `{}`: material is longer than {} characters", w, name, MAX_TEXT));
                }
                if !has_mat(m) {
                    return Err(format!(
                        "{} type `{}`: material `{}` isn't in the library; add it with `material`",
                        w, name, m
                    ));
                }
            }
        }
        Spec::Railing { height, spacing } => {
            size(w, name, "height", *height)?;
            if !(*spacing == 0.0 || (*spacing >= 50.0 && *spacing <= MAX_MM)) {
                return Err(format!(
                    "{} type `{}`: spacing {} mm; balusters stand 50 mm apart or more, or 0 for none",
                    w,
                    name,
                    d(*spacing)
                ));
            }
        }
    }
    if real_guid(name).is_some() {
        return Err(format!("{} type `{}`: a name isn't a GUID; name it otherwise", w, name));
    }
    Ok(())
}

/// What a type's layers add up to, mm.
pub fn layers_sum(layers: &[Layer]) -> f64 {
    let mut s = 0.0;
    for l in layers {
        s += l.thickness;
    }
    s
}
