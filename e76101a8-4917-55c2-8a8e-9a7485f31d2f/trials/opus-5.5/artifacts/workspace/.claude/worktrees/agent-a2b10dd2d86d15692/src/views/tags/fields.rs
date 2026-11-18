//! The fields a tag's `label` may name (its host's category's schedule fields: its own, the phasing
//! ones, the project parameters of the category and, for a component, its families' parameters)
//! and how a tag letters their values (as a schedule shows them, in the project's units).

use super::super::common::*;
use super::super::model::{base_top, location_line, type_entry, wall_thickness};
use crate::json::Value;
use crate::project::Project;

const PHASING: [&str; 3] = ["Phase Created", "Phase Demolished", "Design Option"];

/// The key the types section keeps a category's types under (`types.<key>`, or `types.runs.<key>`).
fn types_key(c: &str) -> &str {
    match c {
        "structuralcolumn" => "structural_column",
        x => x,
    }
}

pub fn is_run(c: &str) -> bool {
    matches!(
        c,
        "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "cable" | "downconductor" | "groundconductor" | "beam" | "stripfooting"
    )
}

/// An element's type's entry in the types section.
pub fn type_def<'a>(pr: &'a Project, e: &Value) -> Option<&'a Value> {
    let c = cat(e);
    if is_run(c) {
        let name = lib_ref_name(pr, e, "type")?;
        return pr.section("types")?.get("runs")?.get(c)?.get(&name);
    }
    type_entry(pr, types_key(c), e)
}

/// The family an element is of (a component, or a door or a window made from one): its name.
pub fn family_name(pr: &Project, e: &Value) -> Option<String> {
    lib_ref_name(pr, e, "family")
}

fn family_def<'a>(pr: &'a Project, e: &Value) -> Option<&'a Value> {
    let n = family_name(pr, e)?;
    pr.section("families")?.get(&n)
}

/// The name of an element's type (a family's type's own name, without its family's).
pub fn type_name(pr: &Project, e: &Value) -> Option<String> {
    let n = lib_ref_name(pr, e, "type")?;
    if let Some(f) = family_name(pr, e) {
        if let Some(rest) = n.strip_prefix(&format!("{}: ", f)) {
            return Some(rest.to_string());
        }
    }
    Some(n)
}

/// A parameter's value for an element of a family: its own, its type's, else the family's.
fn family_value(pr: &Project, e: &Value, name: &str) -> Option<(Value, String)> {
    let f = family_def(pr, e)?;
    let def = f.get("parameters")?.as_arr()?.iter().find(|p| s_of(p, "name") == Some(name))?;
    let kind = s_of(def, "kind").unwrap_or("length").to_string();
    if let Some(v) = e.get("params").and_then(|m| m.get(name)) {
        if !v.is_null() {
            return Some((v.clone(), kind));
        }
    }
    if let Some(t) = type_name(pr, e) {
        if let Some(v) = f.get("types").and_then(|ts| ts.get(&t)).and_then(|t| t.get(name)) {
            return Some((v.clone(), kind));
        }
    }
    def.get("value").map(|v| (v.clone(), kind))
}

/// The parameters of every family the project has, each once, in the families' order.
fn family_params(pr: &Project) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let Some(fams) = pr.section("families") else { return out };
    let mut names: Vec<&String> = fams.keys().collect();
    names.sort();
    for n in names {
        if let Some(ps) = fams.get(n).and_then(|f| f.get("parameters")).and_then(|p| p.as_arr()) {
            for p in ps {
                if let Some(pn) = s_of(p, "name") {
                    if !out.iter().any(|x| x == pn) {
                        out.push(pn.to_string());
                    }
                }
            }
        }
    }
    out
}

/// The fields of an element's category's schedule, in its order.
pub fn field_names(pr: &Project, id: u64) -> Vec<String> {
    let c = cat_of(pr, id);
    let mut out: Vec<String> = crate::styles::parameters::own_fields(&c).iter().map(|s| s.to_string()).collect();
    out.extend(PHASING.iter().map(|s| s.to_string()));
    for (n, _, _) in crate::styles::parameters::for_category(pr, &c) {
        out.push(n);
    }
    if c == "component" {
        for n in family_params(pr) {
            if !out.contains(&n) {
                out.push(n);
            }
        }
    }
    out
}

// ---------------------------------------------------------------- lettering values

/// A number rounded half away from zero to `places` decimals.
fn round_to(x: f64, places: i32) -> f64 {
    let k = 10f64.powi(places);
    (x * k).round() / k
}

fn trim_zeros(s: String) -> String {
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s
    }
}

fn no_neg_zero(s: String) -> String {
    let t = s.trim_start_matches('-');
    if t.chars().all(|c| c == '0' || c == '.' || c == '\'' || c == '"' || c == '-') && s.starts_with('-') {
        return t.to_string();
    }
    s
}

/// A plain number: two decimals at most.
pub fn number_text(x: f64) -> String {
    no_neg_zero(trim_zeros(format!("{:.2}", round_to(x, 2))))
}

/// Sixteenths of an inch as inches and a reduced fraction (`35 5/8`, `1/16`, `12`); with
/// `whole`, the inches always (`0 1/16`).
fn inches_text(sixteenths: i64) -> String {
    inches_text_with(sixteenths, false)
}

fn inches_text_with(sixteenths: i64, whole_always: bool) -> String {
    let whole = sixteenths / 16;
    let mut num = sixteenths % 16;
    let mut den = 16;
    while num != 0 && num % 2 == 0 {
        num /= 2;
        den /= 2;
    }
    if num == 0 {
        format!("{}", whole)
    } else if whole == 0 && !whole_always {
        format!("{}/{}", num, den)
    } else {
        format!("{} {}/{}", whole, num, den)
    }
}

/// A length in the project's units, as its schedules show one.
pub fn length_text(pr: &Project, mm: f64) -> String {
    let units = crate::styles::weights::project_units(pr);
    let neg = mm < 0.0;
    let s = match units.as_str() {
        "cm" => trim_zeros(format!("{:.1}", mm.round() / 10.0)),
        "m" => format!("{:.2}", (mm / 10.0).round() / 100.0),
        "ft" => format!("{:.2}'", round_to(mm / 304.8, 2)),
        "in" => {
            let n = (mm.abs() / 25.4 * 16.0).round() as i64;
            let t = format!("{}\"", inches_text(n));
            if neg && n != 0 {
                format!("-{}", t)
            } else {
                t
            }
        }
        "ft-in" => {
            let n = (mm.abs() / 25.4 * 16.0).round() as i64;
            let feet = n / (12 * 16);
            let rest = n % (12 * 16);
            let t = format!("{}'-{}\"", feet, inches_text_with(rest, true));
            if neg && n != 0 {
                format!("-{}", t)
            } else {
                t
            }
        }
        _ => format!("{}", mm.round() as i64),
    };
    no_neg_zero(s)
}

/// An area (m²) as schedules show one: two decimals, in ft² where the units are imperial.
pub fn area_text(pr: &Project, m2: f64) -> String {
    let units = crate::styles::weights::project_units(pr);
    let v = if crate::styles::weights::imperial(&units) { m2 * 10.763910416709722 } else { m2 };
    no_neg_zero(format!("{:.2}", round_to(v, 2)))
}

/// A volume (m³) as schedules show one.
pub fn volume_text(pr: &Project, m3: f64) -> String {
    let units = crate::styles::weights::project_units(pr);
    let v = if crate::styles::weights::imperial(&units) { m3 * 35.31466672148859 } else { m3 };
    no_neg_zero(format!("{:.2}", round_to(v, 2)))
}

fn yes_no(b: bool) -> String {
    if b { "Yes" } else { "No" }.to_string()
}

fn opt_text(s: Option<String>) -> String {
    match s {
        Some(t) if !t.is_empty() => t,
        _ => "?".into(),
    }
}

/// A value of a kind (length, number, area, yesno, text, material) as a tag letters it.
fn kind_text(pr: &Project, v: &Value, kind: &str) -> String {
    match (kind, v) {
        (_, Value::Null) => "?".into(),
        ("yesno", Value::Bool(b)) => yes_no(*b),
        ("length", Value::Num(n)) => length_text(pr, n.as_f64()),
        ("material", Value::Str(g)) => pr.lib_name(g).unwrap_or_else(|| g.clone()),
        (_, Value::Num(n)) => number_text(n.as_f64()),
        (_, Value::Str(s)) => opt_text(Some(s.clone())),
        (_, Value::Bool(b)) => yes_no(*b),
        _ => "?".into(),
    }
}

// ---------------------------------------------------------------- geometry the fields read

/// A polygon's area by the shoelace formula.
pub fn polygon_area(pts: &[[f64; 2]]) -> f64 {
    let n = pts.len();
    let mut s = 0.0;
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    (s / 2.0).abs()
}

fn openings_area(e: &Value) -> f64 {
    let Some(a) = e.get("openings").and_then(|o| o.as_arr()) else { return 0.0 };
    a.iter()
        .filter_map(|o| {
            let pts: Option<Vec<[f64; 2]>> = o
                .as_arr()?
                .iter()
                .map(|p| {
                    let q = p.as_arr()?;
                    Some([q.first()?.as_f64()?, q.get(1)?.as_f64()?])
                })
                .collect();
            pts.map(|p| polygon_area(&p))
        })
        .sum()
}

/// A run's length: from its start to its end, up as well as across.
fn run_length(e: &Value) -> f64 {
    let a = pt_of(e, "start").unwrap_or([0.0, 0.0]);
    let b = pt_of(e, "end").unwrap_or(a);
    let z0 = f_of(e, "offset").unwrap_or(0.0);
    let z1 = f_of(e, "end_offset").unwrap_or(z0);
    ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2) + (z1 - z0).powi(2)).sqrt()
}

fn level_name_of(pr: &Project, id: u64) -> String {
    super::host_level(pr, id).map(|l| crate::model::name(pr, l)).unwrap_or_else(|| "?".into())
}

/// A stair's risers: as many as keep each at most `riser` high.
fn risers(e: &Value) -> f64 {
    let h = f_of(e, "height").unwrap_or(3000.0);
    let r = f_of(e, "riser").unwrap_or(180.0);
    if r <= 0.0 {
        return 1.0;
    }
    (h / r - 1e-9).ceil().max(1.0)
}

fn type_num(pr: &Project, e: &Value, k: &str) -> Option<f64> {
    type_def(pr, e).and_then(|t| f_of(t, k))
}

/// A door's or a window's width or height: its family type's, else its type's.
fn opening_size(pr: &Project, e: &Value, k: &str, fam_key: &str) -> Option<f64> {
    if family_name(pr, e).is_some() {
        if let Some((Value::Num(n), _)) = family_value(pr, e, fam_key) {
            return Some(n.as_f64());
        }
    }
    type_num(pr, e, k)
}

fn operation_word(op: &str) -> String {
    match op {
        "swing" => "Swing".into(),
        "double-swing" => "Double Swing".into(),
        "sliding" => "Sliding".into(),
        "double-sliding" => "Double Sliding".into(),
        "folding" => "Folding".into(),
        "fixed" => "Fixed".into(),
        x => x.to_string(),
    }
}

fn param_value<'a>(e: &'a Value, k: &str) -> Option<&'a Value> {
    e.get("params").and_then(|m| m.get(k))
}

/// What a tag letters for a field of an element.
pub fn field_text(pr: &Project, id: u64, field: &str) -> String {
    let Some(e) = pr.el(id) else { return "?".into() };
    let c = cat(e).to_string();
    // the project parameters of the category, by name
    for (n, g, kind) in crate::styles::parameters::for_category(pr, &c) {
        if n == field {
            let v = g.as_deref().and_then(|g| param_value(e, g)).or_else(|| param_value(e, &n));
            return match v {
                Some(v) => kind_text(pr, v, &kind),
                None if kind == "yesno" => "No".into(),
                None => "?".into(),
            };
        }
    }
    match field {
        "Id" => return id.to_string(),
        "Count" => return "1".into(),
        "Level" => return level_name_of(pr, id),
        "Phase Created" => {
            if let Some(g) = param_value(e, "Phase Created").and_then(|v| v.as_str()) {
                return crate::styles::phasing::phase_name_of(pr, g);
            }
            // a door or a window follows its wall
            if matches!(c.as_str(), "door" | "window") {
                if let Some(w) = ref_id(pr, e, "host") {
                    if let Some(g) = pr.el(w).and_then(|w| param_value(w, "Phase Created")).and_then(|v| v.as_str()) {
                        return crate::styles::phasing::phase_name_of(pr, g);
                    }
                }
            }
            return opt_text(crate::styles::phasing::phases(pr).first().cloned());
        }
        "Phase Demolished" => {
            return opt_text(
                param_value(e, "Phase Demolished").and_then(|v| v.as_str()).map(|g| crate::styles::phasing::phase_name_of(pr, g)),
            )
        }
        "Design Option" => {
            return opt_text(
                param_value(e, "Design Option").and_then(|v| v.as_str()).map(|g| pr.lib_name(g).unwrap_or_else(|| g.to_string())),
            )
        }
        _ => {}
    }
    let len = |x: Option<f64>| x.map(|v| length_text(pr, v)).unwrap_or_else(|| "?".into());
    match (c.as_str(), field) {
        (_, "Type") => opt_text(type_name(pr, e)),
        ("door" | "window", "Mark") => opt_text(s_of(e, "mark").map(|s| s.to_string())),
        ("door" | "window", "Width") => len(opening_size(pr, e, "width", "Width")),
        ("door" | "window", "Height") => len(opening_size(pr, e, "height", "Height")),
        ("window", "Sill") => len(f_of(e, "sill")),
        ("door" | "window", "Wall") => ref_id(pr, e, "host").map(|w| w.to_string()).unwrap_or_else(|| "?".into()),
        ("door" | "window", "Family") => opt_text(family_name(pr, e)),
        ("door" | "window", "Operation") => {
            let op = family_def(pr, e)
                .and_then(|f| s_of(f, "operation").map(|s| s.to_string()))
                .or_else(|| type_def(pr, e).and_then(|t| s_of(t, "operation").map(|s| s.to_string())));
            opt_text(op.map(|o| operation_word(&o)))
        }
        ("wall", "Length") => len(Some(location_line(e).length())),
        ("wall", "Height") => {
            let (b, t) = base_top(pr, e);
            len(Some(t - b))
        }
        ("wall", "Thickness") => len(Some(wall_thickness(pr, e))),
        ("floor", "Area") => match pts_of(e, "boundary") {
            Some(b) => area_text(pr, (polygon_area(&b) - openings_area(e)) / 1e6),
            None => "?".into(),
        },
        ("ceiling", "Area") => match pts_of(e, "boundary") {
            Some(b) => area_text(pr, (polygon_area(&b) - openings_area(e) - columns_through(pr, e, &b)) / 1e6),
            None => "?".into(),
        },
        ("roof", "Plan Area") => match pts_of(e, "boundary") {
            Some(b) => area_text(pr, (polygon_area(&b) - openings_area(e)) / 1e6),
            None => "?".into(),
        },
        ("floor" | "ceiling" | "roof", "Thickness") => len(type_num(pr, e, "thickness")),
        ("floor" | "ceiling" | "roof", "Offset") => len(Some(f_of(e, "offset").unwrap_or(0.0))),
        ("floor", "Structural") => yes_no(e.get("structural").and_then(|s| s.as_bool()).unwrap_or(false)),
        ("roof", "Slope") => number_text(f_of(e, "slope").unwrap_or(0.0)),
        ("column" | "structuralcolumn" | "footing", "Width") => len(type_num(pr, e, "width")),
        ("column" | "structuralcolumn" | "footing", "Depth") => len(type_num(pr, e, "depth").or_else(|| type_num(pr, e, "width"))),
        ("column" | "structuralcolumn", "Height") => {
            let (b, t) = base_top(pr, e);
            len(Some(t - b))
        }
        ("footing", "Thickness") => len(f_of(e, "height").or_else(|| f_of(e, "thickness"))),
        (r, "Length") if is_run(r) => len(Some(run_length(e))),
        (r, "Width") if is_run(r) => len(type_num(pr, e, "width")),
        (r, "Diameter") if is_run(r) => len(type_num(pr, e, "width")),
        (r, "Depth") if is_run(r) => len(type_num(pr, e, "depth")),
        (r, "System") if is_run(r) => opt_text(s_of(e, "system").map(|s| s.to_string())),
        ("component", "Family") => opt_text(family_name(pr, e)),
        ("component", f) => match family_value(pr, e, f) {
            Some((v, kind)) => kind_text(pr, &v, &kind),
            None => "?".into(),
        },
        ("stair", "Width") | ("ramp", "Width") => len(f_of(e, "width")),
        ("stair", "Height") | ("ramp", "Height") => len(f_of(e, "height")),
        ("stair", "Risers") => number_text(risers(e)),
        ("stair", "Riser Height") => len(Some(f_of(e, "height").unwrap_or(3000.0) / risers(e))),
        ("stair", "Tread") => len(f_of(e, "tread")),
        ("stair", "Length") => len(Some((risers(e) - 1.0).max(0.0) * f_of(e, "tread").unwrap_or(280.0))),
        ("ramp", "Length") => {
            let s = f_of(e, "slope").unwrap_or(8.333333333333334);
            len(Some(if s > 0.0 { f_of(e, "height").unwrap_or(3000.0) / s * 100.0 } else { 0.0 }))
        }
        ("ramp", "Slope") => number_text(f_of(e, "slope").unwrap_or(0.0)),
        ("room", "Number") => opt_text(s_of(e, "number").map(|s| s.to_string())),
        ("room", "Name") => opt_text(s_of(e, "name").map(|s| s.to_string())),
        ("room", "Unbounded Height") => len(Some(super::rooms::room_height(pr, e))),
        ("room", "Area") => area_text(pr, super::rooms::room_metrics(pr, id).map(|m| m.0).unwrap_or(0.0)),
        ("room", "Perimeter") => len(Some(super::rooms::room_metrics(pr, id).map(|m| m.1).unwrap_or(0.0))),
        ("room", "Volume") => {
            let a = round_to(super::rooms::room_metrics(pr, id).map(|m| m.0).unwrap_or(0.0), 2);
            number_text(a * (super::rooms::room_height(pr, e) / 1000.0))
        }
        _ => "?".into(),
    }
}

/// Whether a point lies inside a polygon (even-odd).
pub fn inside(p: [f64; 2], poly: &[[f64; 2]]) -> bool {
    let n = poly.len();
    let mut c = false;
    let mut j = n.wrapping_sub(1);
    for i in 0..n {
        let (a, b) = (poly[i], poly[j]);
        if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0] {
            c = !c;
        }
        j = i;
    }
    c
}

/// The plan area of the columns a ceiling's height passes through, standing inside it.
fn columns_through(pr: &Project, e: &Value, b: &[[f64; 2]]) -> f64 {
    let lv = super::super::model::level_elevation(pr, e, "level").unwrap_or(0.0);
    let z = lv + f_of(e, "offset").unwrap_or(2600.0);
    let mut sum = 0.0;
    for (id, c) in &pr.elements {
        if !matches!(cat(c), "column" | "structuralcolumn") {
            continue;
        }
        let (lo, hi) = base_top(pr, c);
        if !(lo <= z && z <= hi) {
            continue;
        }
        let Some(at) = pt_of(c, "at") else { continue };
        if !inside(at, b) {
            continue;
        }
        if let Some(o) = super::super::model::outline(pr, *id) {
            sum += polygon_area(&o);
        }
    }
    sum
}

/// A number of a door's, a window's or a component's family: its own, its type's, else the family's.
pub fn family_number(pr: &Project, e: &Value, name: &str) -> Option<f64> {
    match family_value(pr, e, name)? {
        (Value::Num(n), _) => Some(n.as_f64()),
        _ => None,
    }
}
