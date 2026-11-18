//! Line weights and object styles: `line_weights`, `object_styles`.
//!
//! Line weights are what each pen draws on paper: the model's 16 pens at each of a list of scales,
//! and the annotation's 16 at any scale. A project that hasn't set them has none in its file and
//! draws in the defaults of its units (metric or imperial scales). Object styles are the pens each
//! model category draws its own lines in, seen and cut; the file holds only the categories a
//! project has set apart (`component` standing for every family category).

use super::common::R;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "line_weights" => line_weights(&mut s.project, p),
        "object_styles" => object_styles(&mut s.project, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- serde, as the original reads

/// The keys of an object as serde_json's (sorted) map hands them over.
pub fn sorted_items(m: &Map) -> Vec<(&String, &Value)> {
    let mut v: Vec<(&String, &Value)> = m.items.iter().map(|(k, v)| (k, v)).collect();
    v.sort_by(|a, b| a.0.cmp(b.0));
    // a key given twice keeps its last value, as a BTreeMap would
    let mut out: Vec<(&String, &Value)> = Vec::with_capacity(v.len());
    for (k, x) in v {
        if let Some(last) = out.last_mut() {
            if last.0 == k {
                last.1 = x;
                continue;
            }
        }
        out.push((k, x));
    }
    out
}

pub fn invalid_type(v: &Value, expected: &str) -> String {
    format!("invalid type: {}, expected {}", v.kind_name(), expected)
}

/// An f64, as serde reads one (any JSON number).
pub fn de_f64(v: &Value) -> R<f64> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid_type(v, "f64")),
    }
}

/// `[f64; 16]`, as serde reads one from a JSON value.
pub fn de_pens16(v: &Value) -> R<[f64; 16]> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(invalid_type(v, "an array of length 16")),
    };
    let mut out = [0.0; 16];
    for i in 0..16 {
        match a.get(i) {
            Some(x) => out[i] = de_f64(x)?,
            None => return Err(format!("invalid length {}, expected an array of length 16", i)),
        }
    }
    if a.len() > 16 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

/// serde's list of the fields a struct has, as its "unknown field" error words it.
pub fn one_of(fields: &[&str]) -> String {
    match fields.len() {
        0 => "there are no fields".to_string(),
        1 => format!("`{}`", fields[0]),
        2 => format!("`{}` or `{}`", fields[0], fields[1]),
        _ => {
            let q: Vec<String> = fields.iter().map(|f| format!("`{}`", f)).collect();
            format!("one of {}", q.join(", "))
        }
    }
}

/// A struct's fields as serde's derive (with deny_unknown_fields) reads them from a map, in the
/// map's (sorted) order, or from a sequence, in the fields' order: each field's value, as the
/// field's reader made it; `None` for a field not given. Errors as serde words them.
pub fn de_struct<T>(
    v: &Value,
    name: &str,
    fields: &[&str],
    mut read: impl FnMut(usize, &Value) -> R<T>,
) -> R<Vec<Option<T>>> {
    let mut out: Vec<Option<T>> = (0..fields.len()).map(|_| None).collect();
    match v {
        Value::Obj(m) => {
            for (k, x) in sorted_items(m) {
                match fields.iter().position(|f| *f == k.as_str()) {
                    Some(i) => out[i] = Some(read(i, x)?),
                    None => return Err(format!("unknown field `{}`, expected {}", k, one_of(fields))),
                }
            }
            Ok(out)
        }
        Value::Arr(a) => {
            for i in 0..fields.len() {
                match a.get(i) {
                    Some(x) => out[i] = Some(read(i, x)?),
                    None => {
                        return Err(format!(
                            "invalid length {}, expected struct {} with {} elements",
                            i,
                            name,
                            fields.len()
                        ))
                    }
                }
            }
            if a.len() > fields.len() {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(out)
        }
        _ => Err(invalid_type(v, &format!("struct {}", name))),
    }
}

/// `true` or `false`, else "`key` is true or false, not …"; null or absent: None.
pub fn flag(p: &Value, cmd: &str, key: &str) -> R<Option<bool>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(b)) => Ok(Some(*b)),
        Some(v) => Err(format!("{}: `{}` is true or false, not {}", cmd, key, v.to_compact())),
    }
}

/// A float as Rust's Display shows it.
fn disp(x: f64) -> String {
    format!("{}", x)
}

// ---------------------------------------------------------------- line weights

/// The pens' widths on paper at 1 : 100, and the annotation's, as a project starts.
pub const ANNOTATION: [f64; 16] = [0.1, 0.13, 0.15, 0.18, 0.2, 0.22, 0.25, 0.28, 0.3, 0.35, 0.4, 0.5, 0.7, 1.0, 1.4, 2.0];

/// The model's pens of a metric project as it starts.
pub const METRIC: &[(f64, [f64; 16])] = &[
    (10.0, [0.18, 0.23, 0.27, 0.32, 0.36, 0.39, 0.44, 0.5, 0.53, 0.62, 0.71, 0.89, 1.24, 1.78, 2.49, 3.56]),
    (20.0, [0.15, 0.19, 0.22, 0.27, 0.3, 0.33, 0.37, 0.42, 0.45, 0.52, 0.6, 0.75, 1.05, 1.5, 2.09, 2.99]),
    (50.0, [0.12, 0.15, 0.18, 0.21, 0.24, 0.26, 0.3, 0.33, 0.36, 0.42, 0.48, 0.59, 0.83, 1.19, 1.66, 2.38]),
    (100.0, [0.1, 0.13, 0.15, 0.18, 0.2, 0.22, 0.25, 0.28, 0.3, 0.35, 0.4, 0.5, 0.7, 1.0, 1.4, 2.0]),
    (200.0, [0.08, 0.11, 0.13, 0.15, 0.17, 0.18, 0.21, 0.24, 0.25, 0.29, 0.34, 0.42, 0.59, 0.84, 1.18, 1.68]),
    (500.0, [0.07, 0.09, 0.1, 0.12, 0.13, 0.15, 0.17, 0.19, 0.2, 0.23, 0.27, 0.33, 0.47, 0.67, 0.94, 1.34]),
];

/// The model's pens of a project in inches or feet as it starts: the architect's scales.
pub const IMPERIAL: &[(f64, [f64; 16])] = &[
    (12.0, [0.17, 0.22, 0.25, 0.31, 0.34, 0.37, 0.42, 0.48, 0.51, 0.59, 0.68, 0.85, 1.19, 1.7, 2.38, 3.4]),
    (24.0, [0.14, 0.19, 0.21, 0.26, 0.29, 0.31, 0.36, 0.4, 0.43, 0.5, 0.57, 0.71, 1.0, 1.43, 2.0, 2.86]),
    (48.0, [0.12, 0.16, 0.18, 0.22, 0.24, 0.26, 0.3, 0.34, 0.36, 0.42, 0.48, 0.6, 0.84, 1.2, 1.68, 2.4]),
    (96.0, [0.1, 0.13, 0.15, 0.18, 0.2, 0.22, 0.25, 0.28, 0.3, 0.35, 0.4, 0.51, 0.71, 1.01, 1.41, 2.02]),
    (192.0, [0.08, 0.11, 0.13, 0.15, 0.17, 0.19, 0.21, 0.24, 0.25, 0.3, 0.34, 0.42, 0.59, 0.85, 1.19, 1.7]),
    (384.0, [0.07, 0.09, 0.11, 0.13, 0.14, 0.16, 0.18, 0.2, 0.21, 0.25, 0.29, 0.36, 0.5, 0.71, 1.0, 1.43]),
];

/// NBR 16861's pens (steps of the square root of 2), its annotation's and its model's.
pub const NBR_ANNOTATION: [f64; 16] = [0.13, 0.15, 0.18, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.4, 2.0];
pub const NBR: &[(f64, [f64; 16])] = &[
    (10.0, [0.23, 0.27, 0.32, 0.36, 0.44, 0.53, 0.62, 0.71, 0.89, 1.07, 1.24, 1.42, 1.78, 2.13, 2.49, 3.56]),
    (20.0, [0.19, 0.22, 0.27, 0.3, 0.37, 0.45, 0.52, 0.6, 0.75, 0.9, 1.05, 1.2, 1.5, 1.79, 2.09, 2.99]),
    (25.0, [0.18, 0.21, 0.25, 0.28, 0.35, 0.42, 0.49, 0.57, 0.71, 0.85, 0.99, 1.13, 1.41, 1.7, 1.98, 2.83]),
    (50.0, [0.15, 0.18, 0.21, 0.24, 0.3, 0.36, 0.42, 0.48, 0.59, 0.71, 0.83, 0.95, 1.19, 1.43, 1.66, 2.38]),
    (100.0, [0.13, 0.15, 0.18, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.4, 2.0]),
    (200.0, [0.11, 0.13, 0.15, 0.17, 0.21, 0.25, 0.29, 0.34, 0.42, 0.5, 0.59, 0.67, 0.84, 1.01, 1.18, 1.68]),
    (500.0, [0.09, 0.1, 0.12, 0.13, 0.17, 0.2, 0.23, 0.27, 0.33, 0.4, 0.47, 0.53, 0.67, 0.8, 0.94, 1.34]),
];

pub struct Weights {
    pub model: Vec<(f64, [f64; 16])>,
    pub annotation: [f64; 16],
}

/// Whether a project's units are inches or feet.
pub fn imperial(units: &str) -> bool {
    matches!(units, "in" | "ft" | "ft-in")
}

pub fn project_units(pr: &Project) -> String {
    pr.get("units").and_then(|v| v.as_str()).unwrap_or("mm").to_string()
}

/// What a project in these units starts with.
pub fn defaults(units: &str) -> Weights {
    let model = if imperial(units) { IMPERIAL } else { METRIC };
    Weights { model: model.to_vec(), annotation: ANNOTATION }
}

fn pens_in(v: Option<&Value>) -> Option<[f64; 16]> {
    let a = v?.as_arr()?;
    if a.len() != 16 {
        return None;
    }
    let mut out = [0.0; 16];
    for (i, x) in a.iter().enumerate() {
        out[i] = x.as_f64()?;
    }
    Some(out)
}

/// The project's own line weights, if its file holds them.
pub fn own(pr: &Project) -> Option<Weights> {
    let lw = pr.get("line_weights")?.as_obj()?;
    let mut model = Vec::new();
    for e in lw.get("model").and_then(|m| m.as_arr()).map(|a| a.as_slice()).unwrap_or(&[]) {
        let scale = e.get("scale").and_then(|x| x.as_f64())?;
        model.push((scale, pens_in(e.get("widths"))?));
    }
    let annotation = pens_in(lw.get("annotation")).unwrap_or(ANNOTATION);
    Some(Weights { model, annotation })
}

pub fn current(pr: &Project) -> (Weights, bool) {
    match own(pr) {
        Some(w) => (w, true),
        None => (defaults(&project_units(pr)), false),
    }
}

fn pens_value(w: &[f64; 16]) -> Value {
    Value::Arr(w.iter().map(|x| Value::f(*x)).collect())
}

/// The section a file holds for these line weights.
pub fn section_value(w: &Weights) -> Value {
    let model: Vec<Value> = w
        .model
        .iter()
        .map(|(s, ws)| jobj! {"scale" => Value::f(*s), "widths" => pens_value(ws)})
        .collect();
    jobj! {"model" => Value::Arr(model), "annotation" => pens_value(&w.annotation)}
}

/// Sets the project's own line weights.
pub fn set_own(pr: &mut Project, w: &Weights) {
    pr.insert_top("line_weights", section_value(w));
}

/// A scale as the project's units name it: 1 : 100, or 1/8" = 1'-0" and 1" = 10'-0" in inches
/// and feet where the scale is one of the architect's or the engineer's.
pub fn scale_name(scale: f64, units: &str) -> String {
    if imperial(units) {
        if let Some(n) = imperial_name(scale) {
            return n;
        }
    }
    format!("1 : {}", disp(scale))
}

fn imperial_name(n: f64) -> Option<String> {
    // the architect's: so many inches (to a 64th) to the foot
    let s64 = 768.0 / n;
    if s64 >= 1.0 {
        let q = s64.round();
        if (s64 - q).abs() < 1e-9 {
            let q = q as u64;
            let whole = q / 64;
            let mut num = q % 64;
            let mut den = 64u64;
            while num > 0 && num % 2 == 0 {
                num /= 2;
                den /= 2;
            }
            let inches = if num == 0 {
                format!("{}", whole)
            } else if whole == 0 {
                format!("{}/{}", num, den)
            } else {
                format!("{} {}/{}", whole, num, den)
            };
            return Some(format!("{}\" = 1'-0\"", inches));
        }
    }
    // the engineer's: an inch to so many feet, ten or more
    let feet = n / 12.0;
    if feet >= 10.0 {
        let f = feet.round();
        if (feet - f).abs() < 1e-9 {
            return Some(format!("1\" = {}'-0\"", f as u64));
        }
    }
    None
}

/// What `line_weights` replies: the pens, each scale named, and whether the project set them.
pub fn listing(pr: &Project) -> Value {
    let (w, own) = current(pr);
    let units = project_units(pr);
    let model: Vec<Value> = w
        .model
        .iter()
        .map(|(s, ws)| jobj! {"name" => scale_name(*s, &units), "scale" => Value::f(*s), "widths" => pens_value(ws)})
        .collect();
    jobj! {"annotation" => pens_value(&w.annotation), "model" => Value::Arr(model), "own" => own}
}

const MODEL_IS: &str = "`model` is [{scale, widths: [the 16 pens' widths, mm]}, …]";
const ANNOTATION_IS: &str = "`annotation` is the 16 pens' widths, mm";

fn de_model(v: &Value) -> R<Vec<(f64, [f64; 16])>> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(invalid_type(v, "a sequence")),
    };
    let mut out = Vec::new();
    for e in a {
        let f = de_struct(e, "ScalePens", &["scale", "widths"], |i, x| -> R<(f64, [f64; 16])> {
            if i == 0 {
                Ok((de_f64(x)?, [0.0; 16]))
            } else {
                Ok((0.0, de_pens16(x)?))
            }
        })?;
        let scale = match &f[0] {
            Some((s, _)) => *s,
            None => return Err("missing field `scale`".into()),
        };
        let widths = match &f[1] {
            Some((_, w)) => *w,
            None => return Err("missing field `widths`".into()),
        };
        out.push((scale, widths));
    }
    Ok(out)
}

fn width_ok(w: f64) -> bool {
    (0.01..=20.0).contains(&w)
}

fn line_weights(pr: &mut Project, p: &Value) -> R<Value> {
    const C: &str = "line_weights";
    if flag(p, C, "reset")? == Some(true) {
        pr.remove_top("line_weights");
        return Ok(listing(pr));
    }
    let model = match p.get("model") {
        None | Some(Value::Null) => None,
        Some(v) => Some(de_model(v).map_err(|e| format!("{}: {}: {}", C, MODEL_IS, e))?),
    };
    let annotation = match p.get("annotation") {
        None | Some(Value::Null) => None,
        Some(v) => Some(de_pens16(v).map_err(|e| format!("{}: {}: {}", C, ANNOTATION_IS, e))?),
    };
    if model.is_none() && annotation.is_none() {
        return Ok(listing(pr));
    }
    let model = match model {
        Some(mut m) => {
            if m.is_empty() || m.len() > 32 {
                return Err(format!("{}: the model's line weights hold 1 to 32 scales, not {}", C, m.len()));
            }
            m.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            for (i, (s, _)) in m.iter().enumerate() {
                if !(1.0..=100000.0).contains(s) {
                    return Err(format!("{}: line weights at 1 : {}: a scale is 1 : 1 to 1 : 100000", C, disp(*s)));
                }
                if i > 0 && m[i - 1].0 == *s {
                    return Err(format!("{}: line weights at 1 : {} are given twice", C, disp(*s)));
                }
            }
            for (s, ws) in &m {
                for (i, w) in ws.iter().enumerate() {
                    if !width_ok(*w) {
                        return Err(format!(
                            "{}: model pen {} at 1 : {} is {} mm wide: a pen is 0.01 to 20 mm on paper",
                            C,
                            i + 1,
                            disp(*s),
                            disp(*w)
                        ));
                    }
                }
            }
            Some(m)
        }
        None => None,
    };
    if let Some(a) = &annotation {
        for (i, w) in a.iter().enumerate() {
            if !width_ok(*w) {
                return Err(format!(
                    "{}: annotation pen {} is {} mm wide: a pen is 0.01 to 20 mm on paper",
                    C,
                    i + 1,
                    disp(*w)
                ));
            }
        }
    }
    let (mut w, _) = current(pr);
    if let Some(m) = model {
        w.model = m;
    }
    if let Some(a) = annotation {
        w.annotation = a;
    }
    set_own(pr, &w);
    Ok(listing(pr))
}

// ---------------------------------------------------------------- object styles

/// The model categories Object Styles has, in its order, with the pens (seen, cut) a project
/// starts with.
pub const CATEGORIES: &[(&str, u64, u64)] = &[
    ("wall", 4, 10),
    ("floor", 4, 10),
    ("ceiling", 4, 10),
    ("shaft", 4, 10),
    ("mass", 4, 4),
    ("door", 4, 6),
    ("window", 4, 6),
    ("room", 4, 10),
    ("roomseparator", 4, 10),
    ("column", 4, 10),
    ("structuralcolumn", 4, 10),
    ("footing", 4, 10),
    ("beam", 4, 10),
    ("stripfooting", 4, 10),
    ("pipe", 4, 10),
    ("duct", 4, 10),
    ("conduit", 4, 10),
    ("cabletray", 4, 10),
    ("wire", 4, 10),
    ("downconductor", 4, 10),
    ("groundconductor", 4, 10),
    ("cable", 4, 10),
    ("rebar", 4, 10),
    ("furniture", 4, 10),
    ("casework", 4, 10),
    ("plumbing", 4, 10),
    ("drain", 4, 10),
    ("pipefitting", 4, 10),
    ("pipeaccessory", 4, 10),
    ("equipment", 4, 10),
    ("outlet", 4, 10),
    ("switch", 4, 10),
    ("airterminal", 4, 10),
    ("earthing", 4, 10),
    ("inspectionbox", 4, 10),
    ("lighting", 4, 10),
    ("generic", 4, 10),
    ("dataoutlet", 4, 10),
    ("voiceoutlet", 4, 10),
    ("patchpanel", 4, 10),
    ("rack", 4, 10),
    ("stair", 4, 10),
    ("ramp", 4, 10),
    ("railing", 6, 10),
    ("roof", 4, 10),
];

/// The categories of families, which `component` sets at once.
pub const FAMILY_CATEGORIES: &[&str] = &[
    "furniture",
    "casework",
    "plumbing",
    "drain",
    "pipefitting",
    "pipeaccessory",
    "equipment",
    "outlet",
    "switch",
    "airterminal",
    "earthing",
    "inspectionbox",
    "lighting",
    "generic",
    "dataoutlet",
    "voiceoutlet",
    "patchpanel",
    "rack",
];

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Pens {
    pub projection: u64,
    pub cut: u64,
}

fn base(cat: &str) -> Pens {
    match CATEGORIES.iter().find(|c| c.0 == cat) {
        Some(c) => Pens { projection: c.1, cut: c.2 },
        None => Pens { projection: 4, cut: 10 },
    }
}

fn styles_map(pr: &Project) -> Map {
    pr.section("object_styles").cloned().unwrap_or_default()
}

fn entry_of(m: &Map, cat: &str) -> Option<Pens> {
    let e = m.get(cat)?;
    let b = base(cat);
    let pen = |k: &str, d: u64| e.get(k).and_then(|x| x.as_f64()).map(|x| x as u64).unwrap_or(d);
    Some(Pens { projection: pen("projection", b.projection), cut: pen("cut", b.cut) })
}

/// What a category draws in when it has no entry of its own.
fn inherited(m: &Map, cat: &str) -> Pens {
    if FAMILY_CATEGORIES.contains(&cat) {
        if let Some(c) = entry_of(m, "component") {
            return c;
        }
    }
    base(cat)
}

fn effective(m: &Map, cat: &str) -> Pens {
    entry_of(m, cat).unwrap_or_else(|| inherited(m, cat))
}

fn pens_entry(p: Pens) -> Value {
    jobj! {"projection" => p.projection, "cut" => p.cut}
}

/// Sets a category's pens in the file's section (as a standard does: kept even where they are the
/// defaults).
pub fn put_style(pr: &mut Project, cat: &str, pens: Pens) {
    pr.section_mut("object_styles").insert_sorted(cat, pens_entry(pens));
}

pub fn object_styles_listing(pr: &Project) -> Value {
    let m = styles_map(pr);
    let cats: Vec<Value> = CATEGORIES
        .iter()
        .map(|(c, _, _)| {
            let e = effective(&m, c);
            jobj! {"category" => *c, "cut" => e.cut, "own" => m.contains(c), "projection" => e.projection}
        })
        .collect();
    jobj! {"categories" => Value::Arr(cats)}
}

const CATEGORIES_IS: &str = "`categories` is {category: {projection?: pen, cut?: pen}, …}";

fn de_pen(v: &Value) -> R<Option<u64>> {
    if v.is_null() {
        return Ok(None);
    }
    let x = de_f64(v)?;
    match super::common::pen_of(x) {
        Some(p) => Ok(Some(p)),
        None => Err(format!("a line weight is a pen, a whole number from 0 (a hairline) to 16, not {}", disp(x))),
    }
}

fn de_categories(v: &Value) -> R<Vec<(String, Option<u64>, Option<u64>)>> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(invalid_type(v, "a map")),
    };
    let mut out = Vec::new();
    for (k, x) in sorted_items(m) {
        let f = de_struct(x, "Given", &["projection", "cut"], |_, x| de_pen(x))?;
        out.push((k.clone(), f[0].flatten(), f[1].flatten()));
    }
    Ok(out)
}

fn object_styles(pr: &mut Project, p: &Value) -> R<Value> {
    const C: &str = "object_styles";
    if flag(p, C, "reset")? == Some(true) {
        pr.remove_top("object_styles");
        return Ok(object_styles_listing(pr));
    }
    let given = match p.get("categories") {
        None | Some(Value::Null) => return Ok(object_styles_listing(pr)),
        Some(v) => de_categories(v).map_err(|e| format!("{}: {}: {}", C, CATEGORIES_IS, e))?,
    };
    for (cat, _, _) in &given {
        if cat != "component" && !CATEGORIES.iter().any(|c| c.0 == cat) {
            let names: Vec<&str> = CATEGORIES.iter().map(|c| c.0).collect();
            return Err(format!(
                "{}: `{}` isn't a model category; Object Styles has: {} (and `component`, for every family category)",
                C,
                cat,
                names.join(", ")
            ));
        }
    }
    let mut m = styles_map(pr);
    for (cat, projection, cut) in given {
        let cur = effective(&m, &cat);
        let new = Pens { projection: projection.unwrap_or(cur.projection), cut: cut.unwrap_or(cur.cut) };
        if new == inherited(&m, &cat) {
            m.remove(&cat);
        } else {
            m.insert_sorted(&cat, pens_entry(new));
        }
    }
    if m.is_empty() {
        pr.remove_top("object_styles");
    } else {
        pr.insert_top("object_styles", Value::Obj(m));
    }
    Ok(object_styles_listing(pr))
}
