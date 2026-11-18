//! A stand-in for the schedules' fields that view filters' rules read: each category's fields
//! (as `schedule {category}`'s `available` lists them, project parameters after), what kind of
//! value each holds, each element's value, and how a rule compares them (text in any case,
//! numbers as the schedule shows them, an unset yes or no as no).

use crate::json::Value;
use crate::project::Project;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Kind {
    Text,
    Length,
    Area,
    Number,
    YesNo,
}

impl Kind {
    /// How a rule's error names what the field compares.
    pub fn compares(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Length => "a length (mm)",
            Kind::Area => "an area (m²)",
            Kind::Number => "a number",
            Kind::YesNo => "yes or no",
        }
    }

    pub fn holds(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Length => "a length",
            Kind::Area => "an area",
            Kind::Number => "a number",
            Kind::YesNo => "yes or no",
        }
    }
}

/// A field's value of an element.
#[derive(Clone, PartialEq, Debug)]
pub enum FV {
    Text(String),
    Num(f64),
    Bool(bool),
}

use Kind::*;

const PHASING: &[(&str, Kind)] = &[("Phase Created", Text), ("Phase Demolished", Text), ("Design Option", Text)];

/// A category's own fields, in the schedule's order.
fn own_fields(cat: &str) -> Vec<(&'static str, Kind)> {
    let base: &[(&str, Kind)] = match cat {
        "room" => &[
            ("Number", Text),
            ("Name", Text),
            ("Level", Text),
            ("Area", Area),
            ("Perimeter", Length),
            ("Count", Number),
            ("Unbounded Height", Length),
            ("Volume", Number),
        ],
        "door" => &[
            ("Mark", Text),
            ("Type", Text),
            ("Width", Length),
            ("Height", Length),
            ("Level", Text),
            ("Wall", Number),
            ("Family", Text),
            ("Operation", Text),
            ("Count", Number),
        ],
        "window" => &[
            ("Mark", Text),
            ("Type", Text),
            ("Width", Length),
            ("Height", Length),
            ("Sill", Length),
            ("Level", Text),
            ("Wall", Number),
            ("Family", Text),
            ("Operation", Text),
            ("Count", Number),
        ],
        "wall" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Length", Length),
            ("Height", Length),
            ("Thickness", Length),
            ("Count", Number),
        ],
        "floor" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Area", Area),
            ("Thickness", Length),
            ("Offset", Length),
            ("Count", Number),
            ("Structural", YesNo),
        ],
        "ceiling" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Offset", Length),
            ("Area", Area),
            ("Thickness", Length),
            ("Count", Number),
        ],
        "roof" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Slope", Number),
            ("Plan Area", Area),
            ("Offset", Length),
            ("Count", Number),
        ],
        "column" | "structuralcolumn" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Width", Length),
            ("Depth", Length),
            ("Height", Length),
            ("Count", Number),
        ],
        "footing" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Width", Length),
            ("Depth", Length),
            ("Thickness", Length),
            ("Count", Number),
        ],
        "beam" | "stripfooting" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("Length", Length),
            ("Width", Length),
            ("Depth", Length),
            ("System", Text),
            ("Count", Number),
        ],
        "rebar" => &[
            ("Id", Number),
            ("Level", Text),
            ("Grade", Text),
            ("Diameter", Length),
            ("Length", Length),
            ("Count", Number),
            ("Weight", Number),
            ("Host", Number),
            ("Layer", Text),
        ],
        "pipe" | "conduit" | "cable" | "wire" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("System", Text),
            ("Length", Length),
            ("Diameter", Length),
            ("Count", Number),
        ],
        "cabletray" | "duct" | "downconductor" | "groundconductor" => &[
            ("Id", Number),
            ("Type", Text),
            ("Level", Text),
            ("System", Text),
            ("Length", Length),
            ("Width", Length),
            ("Depth", Length),
            ("Count", Number),
        ],
        "component" => &[("Family", Text), ("Type", Text), ("Level", Text), ("Count", Number)],
        "stair" => &[
            ("Id", Number),
            ("Level", Text),
            ("Width", Length),
            ("Height", Length),
            ("Risers", Number),
            ("Riser Height", Length),
            ("Tread", Length),
            ("Length", Length),
            ("Count", Number),
        ],
        "ramp" => &[
            ("Id", Number),
            ("Level", Text),
            ("Width", Length),
            ("Height", Length),
            ("Length", Length),
            ("Slope", Number),
            ("Count", Number),
        ],
        "railing" => &[("Id", Number), ("Type", Text), ("Level", Text), ("Length", Length), ("Height", Length), ("Count", Number)],
        "mass" => &[
            ("Name", Text),
            ("Level", Text),
            ("Height", Length),
            ("Area", Area),
            ("Volume", Number),
            ("Gross Floor Area", Area),
            ("Count", Number),
        ],
        "massfloor" => &[
            ("Mass", Text),
            ("Level", Text),
            ("Area", Area),
            ("Perimeter", Length),
            ("Volume", Number),
            ("Count", Number),
        ],
        "level" => &[("Elevation", Length), ("Name", Text), ("Count", Number)],
        _ => &[],
    };
    let mut v = base.to_vec();
    if !matches!(cat, "rebar" | "massfloor" | "level") {
        v.extend_from_slice(PHASING);
    }
    v
}

/// The kind of a family parameter as a schedule compares it.
fn param_kind(k: &str) -> Kind {
    match k {
        "length" => Length,
        "yesno" => YesNo,
        "material" | "text" => Text,
        _ => Number,
    }
}

/// The project parameters of a category: (name, kind, GUID).
fn project_params(pr: &Project, cat: &str) -> Vec<(String, Kind, Option<String>)> {
    let mut out = Vec::new();
    if let Some(m) = pr.section("parameters") {
        for (name, v) in &m.items {
            let cats: Vec<String> = v
                .get("categories")
                .and_then(|c| c.as_arr())
                .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
                .unwrap_or_default();
            if !cats.iter().any(|c| c == cat) {
                continue;
            }
            let kind = param_kind(v.get("kind").and_then(|k| k.as_str()).unwrap_or("text"));
            out.push((name.clone(), kind, pr.lib_guid("parameter", name)));
        }
    }
    out
}

/// A field a rule names, of a category: its name, kind and, for a project parameter, its GUID.
#[derive(Clone, Debug)]
pub struct Field {
    pub name: String,
    pub kind: Kind,
    pub param: Option<String>,
}

/// Every field of a category, in the order its schedule lists them.
pub fn fields_of(pr: &Project, cat: &str) -> Vec<Field> {
    let mut out: Vec<Field> =
        own_fields(cat).into_iter().map(|(n, k)| Field { name: n.to_string(), kind: k, param: None }).collect();
    if cat == "component" {
        // the families' parameters, family by family in name order, each once
        if let Some(fams) = pr.section("families") {
            let mut names: Vec<&String> = fams.keys().collect();
            names.sort();
            for f in names {
                let params = fams.get(f).and_then(|x| x.get("parameters")).and_then(|x| x.as_arr()).cloned().unwrap_or_default();
                for p in params {
                    let Some(n) = p.get("name").and_then(|x| x.as_str()) else { continue };
                    if out.iter().any(|x| x.name == n) {
                        continue;
                    }
                    let k = param_kind(p.get("kind").and_then(|x| x.as_str()).unwrap_or("length"));
                    out.push(Field { name: n.to_string(), kind: k, param: None });
                }
            }
        }
    }
    for (n, k, g) in project_params(pr, cat) {
        if out.iter().any(|x| x.name == n) {
            continue;
        }
        out.push(Field { name: n, kind: k, param: g });
    }
    out
}

/// A field of a category by name or, for a project parameter, its GUID.
pub fn field(pr: &Project, cat: &str, name: &str) -> Option<Field> {
    fields_of(pr, cat).into_iter().find(|f| f.name == name || f.param.as_deref() == Some(name))
}

// ---------------------------------------------------------------- values

fn s<'a>(e: &'a Value, k: &str) -> Option<&'a str> {
    e.get(k).and_then(|x| x.as_str())
}

fn f(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

fn pt(v: &Value) -> Option<[f64; 3]> {
    let a = v.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?, a.get(2).and_then(|z| z.as_f64()).unwrap_or(0.0)])
}

fn dist(a: [f64; 3], b: [f64; 3]) -> f64 {
    ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2) + (b[2] - a[2]).powi(2)).sqrt()
}

fn polyline_len(v: Option<&Value>) -> Option<f64> {
    let a = v?.as_arr()?;
    let pts: Vec<[f64; 3]> = a.iter().filter_map(pt).collect();
    if pts.len() < 2 {
        return None;
    }
    Some(pts.windows(2).map(|w| dist(w[0], w[1])).sum())
}

fn area_m2(v: Option<&Value>) -> Option<f64> {
    let a = v?.as_arr()?;
    let pts: Vec<[f64; 3]> = a.iter().filter_map(pt).collect();
    if pts.len() < 3 {
        return None;
    }
    let mut s = 0.0;
    for i in 0..pts.len() {
        let p = pts[i];
        let q = pts[(i + 1) % pts.len()];
        s += p[0] * q[1] - q[0] * p[1];
    }
    Some((s / 2.0).abs() / 1e6)
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// The name of a library entry an element's field names (its GUID).
fn lib_name(pr: &Project, e: &Value, k: &str) -> Option<String> {
    pr.lib_name(s(e, k)?)
}

fn el_name(pr: &Project, g: &str) -> Option<String> {
    let id = pr.find_guid(g)?;
    pr.el(id)?.get("name")?.as_str().map(|s| s.to_string())
}

/// The element a door or a window stands in.
fn host<'a>(pr: &'a Project, e: &Value) -> Option<(u64, &'a Value)> {
    let id = pr.find_guid(s(e, "host")?)?;
    Some((id, pr.el(id)?))
}

/// A type's properties (`types` of the category, or of runs) by the element's type.
fn type_props(pr: &Project, cat: &str, e: &Value) -> Option<Value> {
    let name = lib_name(pr, e, "type")?;
    let types = pr.section("types")?;
    let key = match cat {
        "structuralcolumn" => "structural_column",
        c => c,
    };
    if let Some(t) = types.get(key).and_then(|m| m.get(&name)) {
        return Some(t.clone());
    }
    types.get("runs").and_then(|r| r.get(cat)).and_then(|m| m.get(&name)).cloned()
}

/// A component's value of one of its family's parameters: its own, else its type's, else the
/// family's (a material by name).
fn family_value(pr: &Project, e: &Value, name: &str) -> Option<FV> {
    let fam = lib_name(pr, e, "family")?;
    let def = pr.section("families")?.get(&fam)?.clone();
    let params = def.get("parameters").and_then(|p| p.as_arr()).cloned().unwrap_or_default();
    let p = params.iter().find(|p| p.get("name").and_then(|n| n.as_str()) == Some(name))?;
    let kind = p.get("kind").and_then(|k| k.as_str()).unwrap_or("length").to_string();
    let ty = lib_name(pr, e, "type").map(|t| t.split_once(": ").map(|(_, t)| t.to_string()).unwrap_or(t));
    let mut v = p.get("value").cloned();
    if let Some(t) = ty.and_then(|t| def.get("types").and_then(|ts| ts.get(&t)).cloned()) {
        if let Some(x) = t.get(name) {
            v = Some(x.clone());
        }
    }
    let own = pr
        .lib_guid("family-parameter", &format!("{}: {}", fam, name))
        .and_then(|g| e.get("params").and_then(|ps| ps.get(&g)).cloned())
        .or_else(|| e.get("params").and_then(|ps| ps.get(name)).cloned());
    if let Some(x) = own {
        v = Some(x);
    }
    match v? {
        Value::Num(n) => Some(FV::Num(if kind == "length" { round2(n.as_f64()) } else { n.as_f64() })),
        Value::Bool(b) => Some(FV::Bool(b)),
        Value::Str(s) => {
            if kind == "material" {
                Some(FV::Text(pr.lib_name(&s).unwrap_or(s)))
            } else {
                s.parse::<f64>().ok().map(FV::Num).or(Some(FV::Text(s)))
            }
        }
        _ => None,
    }
}

fn elev_of(pr: &Project, g: Option<&str>) -> Option<f64> {
    let id = pr.find_guid(g?)?;
    pr.el(id)?.get("elevation")?.as_f64()
}

/// A room's height from its base to its upper limit.
fn room_height(pr: &Project, e: &Value) -> Option<f64> {
    let base = elev_of(pr, s(e, "level"))? + f(e, "base_offset").unwrap_or(0.0);
    match s(e, "top_level") {
        Some(t) => Some(elev_of(pr, Some(t))? + f(e, "limit_offset").unwrap_or(0.0) - base),
        None => Some(f(e, "limit_offset").unwrap_or(2500.0)),
    }
}

/// The levels a mass spans, from its base's up to (not including) its top's.
fn mass_levels(pr: &Project, e: &Value) -> usize {
    let Some(base) = elev_of(pr, s(e, "level")) else { return 0 };
    let top = elev_of(pr, s(e, "top_level")).unwrap_or(base + f(e, "height").unwrap_or(0.0));
    crate::model::levels(pr)
        .iter()
        .filter_map(|l| pr.el(*l).and_then(|x| x.get("elevation")).and_then(|x| x.as_f64()))
        .filter(|z| *z >= base - 1e-6 && *z < top - 1e-6)
        .count()
}

fn type_num(pr: &Project, cat: &str, e: &Value, k: &str) -> Option<f64> {
    type_props(pr, cat, e)?.get(k)?.as_f64()
}

/// The phase an element is made in (doors and windows follow their wall).
fn phase_of(pr: &Project, e: &Value, key: &str, depth: usize) -> Option<String> {
    if let Some(v) = e.get("params").and_then(|p| p.get(key)).and_then(|v| v.as_str()) {
        return Some(crate::styles::phasing::phase_name_of(pr, v));
    }
    let c = s(e, "category").unwrap_or("");
    if matches!(c, "door" | "window") && depth < 4 {
        if let Some((_, h)) = host(pr, e) {
            return phase_of(pr, h, key, depth + 1);
        }
    }
    if key == "Phase Created" {
        return crate::styles::phasing::phases(pr).first().cloned();
    }
    None
}

fn run_len(e: &Value) -> Option<f64> {
    let a = pt(e.get("start")?)?;
    let b = pt(e.get("end")?)?;
    let d = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
    let rise = f(e, "end_offset").map(|eo| eo - f(e, "offset").unwrap_or(0.0)).unwrap_or(0.0);
    Some((d * d + rise * rise).sqrt())
}

fn wall_len(e: &Value) -> Option<f64> {
    let a = pt(e.get("start")?)?;
    let b = pt(e.get("end")?)?;
    let chord = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
    match f(e, "arc") {
        Some(deg) if deg.abs() > 1e-9 => {
            let t = deg.abs().to_radians();
            Some(chord * (t / 2.0) / (t / 2.0).sin())
        }
        _ => Some(chord),
    }
}

/// An element's value of a field (None where it has none).
pub fn value_of(pr: &Project, cat: &str, id: u64, fd: &Field) -> Option<FV> {
    let e = pr.el(id)?;
    if let Some(g) = &fd.param {
        return match e.get("params").and_then(|p| p.get(g)) {
            Some(Value::Str(t)) => Some(FV::Text(t.clone())),
            Some(Value::Bool(b)) => Some(FV::Bool(*b)),
            Some(Value::Num(n)) => Some(FV::Num(n.as_f64())),
            _ => None,
        };
    }
    let num = |x: Option<f64>| x.map(FV::Num);
    let text = |x: Option<String>| x.filter(|t| !t.is_empty()).map(FV::Text);
    let len = |x: Option<f64>| x.map(|v| FV::Num(round2(v)));
    if cat == "component" && !matches!(fd.name.as_str(), "Family" | "Type" | "Level" | "Count") && !PHASING.iter().any(|(n, _)| *n == fd.name) {
        return family_value(pr, e, &fd.name);
    }
    if matches!(cat, "door" | "window") && e.get("family").is_some() {
        // a family's opening: its type's parameters, its family's operation
        match fd.name.as_str() {
            "Width" | "Height" => return family_value(pr, e, &fd.name),
            "Type" => {
                let n = lib_name(pr, e, "type")?;
                return text(Some(n.split_once(": ").map(|(_, t)| t.to_string()).unwrap_or(n)));
            }
            "Operation" => {
                let fam = lib_name(pr, e, "family")?;
                let op = pr.section("families")?.get(&fam)?.get("operation")?.as_str()?.to_string();
                let words: Vec<String> = op
                    .split('-')
                    .map(|w| {
                        let mut c = w.chars();
                        match c.next() {
                            Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                            None => String::new(),
                        }
                    })
                    .collect();
                return text(Some(words.join(" ")));
            }
            _ => {}
        }
    }
    if cat == "room" {
        // what the room's boundary gives (nothing, for a room nothing bounds)
        let measured = || super::rooms::measure(pr, id).unwrap_or((0.0, 0.0));
        match fd.name.as_str() {
            "Area" => return Some(FV::Num(measured().0)),
            // a room's perimeter goes to the 10 mm
            "Perimeter" => return Some(FV::Num((measured().1 / 10.0).round() * 10.0)),
            "Volume" => {
                let (a, _) = measured();
                return Some(FV::Num(a * room_height(pr, e).unwrap_or(0.0) / 1000.0));
            }
            "Unbounded Height" => return len(room_height(pr, e)),
            _ => {}
        }
    }
    if cat == "mass" {
        match fd.name.as_str() {
            "Volume" => {
                let a = area_m2(e.get("boundary"))?;
                let h = f(e, "height")?;
                return num(Some(round2(a * h / 1000.0)));
            }
            "Gross Floor Area" => {
                let a = area_m2(e.get("boundary"))?;
                return num(Some(round2(a * mass_levels(pr, e) as f64)));
            }
            _ => {}
        }
    }
    match fd.name.as_str() {
        "Id" => Some(FV::Num(id as f64)),
        "Count" => Some(FV::Num(1.0)),
        "Type" => {
            let n = lib_name(pr, e, "type")?;
            let n = if cat == "component" { n.split_once(": ").map(|(_, t)| t.to_string()).unwrap_or(n) } else { n };
            text(Some(n))
        }
        "Family" => text(lib_name(pr, e, "family")),
        "Level" => {
            let lv = match s(e, "level") {
                Some(g) => el_name(pr, g),
                None => host(pr, e).and_then(|(_, h)| s(h, "level").and_then(|g| el_name(pr, g))),
            };
            text(lv)
        }
        "Name" => text(s(e, "name").map(|x| x.to_string())),
        "Number" => text(s(e, "number").map(|x| x.to_string())),
        "Mark" => text(s(e, "mark").map(|x| x.to_string())),
        "Grade" => text(s(e, "grade").map(|x| x.to_string())),
        "Layer" => text(s(e, "layer").map(|x| x.to_string())),
        "System" => text(s(e, "system").and_then(|g| pr.lib_name(g).or_else(|| Some(g.to_string())))),
        "Elevation" => len(f(e, "elevation")),
        "Wall" => host(pr, e).map(|(h, _)| FV::Num(h as f64)),
        "Host" => Some(FV::Num(s(e, "host").and_then(|g| pr.find_guid(g)).map(|h| h as f64).unwrap_or(0.0))),
        "Sill" => len(f(e, "sill")),
        "Offset" => len(Some(f(e, "offset").unwrap_or(0.0))),
        "Structural" => Some(FV::Bool(e.get("structural").and_then(|x| x.as_bool()).unwrap_or(false))),
        "Slope" => num(f(e, "slope")),
        "Tread" => len(f(e, "tread")),
        "Diameter" => match cat {
            "rebar" => len(f(e, "diameter")),
            _ => len(type_num(pr, cat, e, "width")),
        },
        "Width" => match cat {
            "stair" | "ramp" => len(f(e, "width")),
            _ => len(type_num(pr, cat, e, "width")),
        },
        "Depth" => len(type_num(pr, cat, e, "depth")),
        "Thickness" => match cat {
            "footing" => len(f(e, "height")),
            _ => len(type_num(pr, cat, e, "thickness")),
        },
        "Height" => match cat {
            "door" | "window" => len(type_num(pr, cat, e, "height")),
            "railing" => len(type_num(pr, cat, e, "height")),
            _ => len(f(e, "height")),
        },
        "Length" => match cat {
            "wall" => len(wall_len(e)),
            "railing" => len(polyline_len(e.get("path"))),
            "rebar" => len(polyline_len(e.get("path"))),
            "stair" => {
                let h = f(e, "height")?;
                let r = f(e, "riser")?;
                let n = (h / r).ceil();
                len(Some((n - 1.0) * f(e, "tread")?))
            }
            "ramp" => {
                let h = f(e, "height")?;
                let sl = f(e, "slope")?;
                if sl.abs() < 1e-12 {
                    None
                } else {
                    len(Some(h / (sl / 100.0)))
                }
            }
            _ => len(run_len(e)),
        },
        "Risers" => {
            let h = f(e, "height")?;
            let r = f(e, "riser")?;
            num(Some((h / r).ceil()))
        }
        "Riser Height" => {
            let h = f(e, "height")?;
            let r = f(e, "riser")?;
            len(Some(h / (h / r).ceil()))
        }
        "Weight" => {
            let d = f(e, "diameter")?;
            let l = polyline_len(e.get("path"))?;
            num(Some(((d * d * 0.00617 * l / 1000.0) * 1000.0).round() / 1000.0))
        }
        "Area" => match cat {
            "floor" | "ceiling" => {
                let mut a = area_m2(e.get("boundary"))?;
                if let Some(holes) = e.get("openings").and_then(|o| o.as_arr()) {
                    for h in holes {
                        a -= area_m2(Some(h)).unwrap_or(0.0);
                    }
                }
                Some(FV::Num(round2(a)))
            }
            "mass" => area_m2(e.get("boundary")).map(|a| FV::Num(round2(a))),
            _ => None,
        },
        "Plan Area" => area_m2(e.get("boundary")).map(|a| FV::Num(round2(a))),
        "Phase Created" | "Phase Demolished" => text(phase_of(pr, e, &fd.name, 0)),
        "Design Option" => {
            let v = e.get("params").and_then(|p| p.get("Design Option")).and_then(|v| v.as_str())?;
            text(Some(crate::styles::common::name_of_guid(pr, "design-option", v).unwrap_or_else(|| v.to_string())))
        }
        _ => None,
    }
}

/// The elements of a category a filter picks from, by id.
pub fn elements_of(pr: &Project, cat: &str) -> Vec<u64> {
    if cat == "massfloor" {
        return Vec::new();
    }
    pr.ids_of(cat)
}

/// Whether a value holds a rule (`op`, against `v`).
pub fn holds(val: Option<&FV>, kind: Kind, op: &str, v: Option<&Value>) -> bool {
    match op {
        "has-value" => return val.is_some(),
        "has-no-value" => return val.is_none(),
        _ => {}
    }
    match kind {
        Kind::Text => {
            let a = match val {
                Some(FV::Text(t)) => Some(t.to_lowercase()),
                Some(FV::Num(n)) => Some(format!("{}", n)),
                Some(FV::Bool(b)) => Some(b.to_string()),
                None => None,
            };
            let b = v.and_then(|x| x.as_str()).unwrap_or("").to_lowercase();
            match (op, a) {
                ("equals", Some(a)) => a == b,
                ("not-equals", Some(a)) => a != b,
                ("not-equals", None) => true,
                ("greater", Some(a)) => a > b,
                ("greater-or-equal", Some(a)) => a >= b,
                ("less", Some(a)) => a < b,
                ("less-or-equal", Some(a)) => a <= b,
                ("contains", Some(a)) => a.contains(&b),
                ("not-contains", Some(a)) => !a.contains(&b),
                ("not-contains", None) => true,
                ("begins-with", Some(a)) => a.starts_with(&b),
                ("not-begins-with", Some(a)) => !a.starts_with(&b),
                ("not-begins-with", None) => true,
                ("ends-with", Some(a)) => a.ends_with(&b),
                ("not-ends-with", Some(a)) => !a.ends_with(&b),
                ("not-ends-with", None) => true,
                _ => false,
            }
        }
        Kind::YesNo => {
            let a = match val {
                Some(FV::Bool(b)) => *b,
                _ => false,
            };
            let b = v.and_then(|x| x.as_bool()).unwrap_or(false);
            match op {
                "equals" => a == b,
                "not-equals" => a != b,
                _ => false,
            }
        }
        _ => {
            let Some(FV::Num(a)) = val else { return op == "not-equals" };
            let Some(b) = v.and_then(|x| x.as_f64()) else { return false };
            // as the schedule shows them: lengths to the millimetre, the rest to two places
            let shown = |x: f64| if kind == Kind::Length { x.round() } else { (x * 100.0).round() / 100.0 };
            let (a, b) = (&shown(*a), shown(b));
            let eq = (a - b).abs() < 1e-9;
            match op {
                "equals" => eq,
                "not-equals" => !eq,
                "greater" => *a > b && !eq,
                "greater-or-equal" => *a > b || eq,
                "less" => *a < b && !eq,
                "less-or-equal" => *a < b || eq,
                _ => false,
            }
        }
    }
}
