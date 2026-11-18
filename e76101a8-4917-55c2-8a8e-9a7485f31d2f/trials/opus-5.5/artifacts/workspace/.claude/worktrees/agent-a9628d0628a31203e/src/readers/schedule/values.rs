//! Each field's value for one element, as a schedule's row holds it: what the element's view
//! (`elements`) shows of it, its project parameters' values, its phases and design option.

use super::defs::{self, Kind};
use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, Ctx};

/// A field of a schedule's category: its name as shown, what it holds and where it comes from.
#[derive(Clone, Debug)]
pub struct FieldDef {
    pub name: String,
    pub kind: Kind,
    pub src: Src,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Src {
    /// The category's own (or, in a multi-category schedule, one its categories share).
    Own,
    PhaseCreated,
    PhaseDemolished,
    DesignOption,
    /// A project parameter: the key elements hold its values under (its GUID, or its name).
    Param(String),
    /// A family's parameter (components).
    Family,
}

/// The fields there are for a schedule of `cat`, in the order `available` lists them: its own,
/// Count among them, the phases and design option, the project parameters for it (by name), and
/// for components every family's parameters (families by name, each's in order).
pub fn available(pr: &Project, cat: &str) -> Vec<FieldDef> {
    let mut out: Vec<FieldDef> = defs::own_fields(cat)
        .iter()
        .map(|(n, k)| FieldDef { name: n.to_string(), kind: *k, src: Src::Own })
        .collect();
    if defs::phased(cat) {
        out.push(FieldDef { name: defs::PHASE_CREATED.into(), kind: Kind::Text, src: Src::PhaseCreated });
        out.push(FieldDef { name: defs::PHASE_DEMOLISHED.into(), kind: Kind::Text, src: Src::PhaseDemolished });
        out.push(FieldDef { name: defs::DESIGN_OPTION.into(), kind: Kind::Text, src: Src::DesignOption });
    }
    if cat != "multicategory" {
        for (name, guid, kind) in crate::styles::parameters::for_category(pr, cat) {
            let k = match kind.as_str() {
                "number" => Kind::Number,
                "length" => Kind::Length,
                "yesno" => Kind::YesNo,
                _ => Kind::Text,
            };
            let key = guid.unwrap_or_else(|| name.clone());
            out.push(FieldDef { name, kind: k, src: Src::Param(key) });
        }
    }
    if cat == "component" {
        for (name, kind) in family_parameters(pr) {
            if out.iter().any(|f| f.name == name) {
                continue;
            }
            out.push(FieldDef { name, kind, src: Src::Family });
        }
    }
    out
}

/// Every family's parameters, families by name and each's in its order, each name once.
pub fn family_parameters(pr: &Project) -> Vec<(String, Kind)> {
    let mut out: Vec<(String, Kind)> = Vec::new();
    let Some(fams) = pr.section("families") else {
        return out;
    };
    let mut names: Vec<&String> = fams.keys().collect();
    names.sort();
    for n in names {
        let Some(ps) = fams.get(n).and_then(|f| f.get("parameters")).and_then(|p| p.as_arr()) else {
            continue;
        };
        for p in ps {
            let Some(pn) = p.get("name").and_then(|x| x.as_str()) else {
                continue;
            };
            if out.iter().any(|(x, _)| x == pn) {
                continue;
            }
            let kind = match p.get("kind").and_then(|k| k.as_str()).unwrap_or("length") {
                "length" => Kind::Length,
                "yesno" => Kind::YesNo,
                "material" => Kind::Text,
                _ => Kind::Number,
            };
            out.push((pn.to_string(), kind));
        }
    }
    out
}

// ---------------------------------------------------------------- reading the view

fn num(v: &Value, k: &str) -> Option<f64> {
    v.get(k).and_then(|x| x.as_f64())
}

fn txt<'v>(v: &'v Value, k: &str) -> Option<&'v str> {
    v.get(k).and_then(|x| x.as_str())
}

fn fnum(x: Option<f64>) -> Value {
    match x {
        Some(x) if x.is_finite() => Value::f(x),
        _ => Value::Null,
    }
}

fn ftext(x: Option<&str>) -> Value {
    match x {
        Some(s) => Value::s(s),
        None => Value::Null,
    }
}

fn is_guid(s: &str) -> bool {
    crate::model::normalize_guid(s).as_deref() == Some(s)
}

/// The name of the level a GUID (or a name, as a view may give it) names.
fn level_name(pr: &Project, g: &str) -> Option<String> {
    if is_guid(g) {
        let (_, l) = common::by_guid(pr, g)?;
        return common::text(l, "name").map(|s| s.to_string());
    }
    Some(g.to_string())
}

/// The element a field of a view points at (by GUID): its id.
fn target_id(pr: &Project, v: &Value, k: &str) -> Option<u64> {
    let g = txt(v, k)?;
    pr.find_guid(g)
}

/// A family's name: the view's `family` (its name), or the family its GUID names.
fn family_name(pr: &Project, v: &Value) -> Option<String> {
    let f = txt(v, "family")?;
    if is_guid(f) {
        return common::family(pr, f).map(|(n, _)| n).or_else(|| pr.lib_name(f));
    }
    Some(f.to_string())
}

/// A type's name: the view's `type` (its name), or the type its GUID names.
fn type_name(pr: &Project, cat: &str, v: &Value) -> Option<String> {
    let t = txt(v, "type")?;
    if !is_guid(t) {
        return Some(t.to_string());
    }
    if let Some((n, _)) = common::type_of(pr, cat, t) {
        return Some(n);
    }
    if let Some(f) = family_name(pr, v) {
        if let Some(n) = common::family_type(pr, &f, t) {
            return Some(n);
        }
    }
    let n = pr.lib_name(t)?;
    match n.split_once(": ") {
        Some((_, rest)) if pr.lib_find_guid(t).map(|id| common::text(&pr.library[&id], "kind") == Some("family-type")).unwrap_or(false) => {
            Some(rest.to_string())
        }
        _ => Some(n),
    }
}

/// The definition of an element's project type (doors and windows of the project's own types).
fn type_def<'p>(pr: &'p Project, cat: &str, v: &Value) -> Option<&'p Value> {
    if v.get("family").is_some() {
        return None;
    }
    let g = txt(v, "type_guid").or_else(|| txt(v, "type"))?;
    common::type_of(pr, cat, g).map(|(_, d)| d)
}

/// How an operation's key reads: `double-swing` as Double Swing.
fn operation_text(op: &str) -> String {
    op.split(['-', '_', ' '])
        .filter(|w| !w.is_empty())
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// A path's length along its points.
fn path_length(v: &Value) -> Option<f64> {
    let a = v.get("path")?.as_arr()?;
    let pts: Vec<Vec<f64>> = a.iter().filter_map(|p| p.as_arr().map(|q| q.iter().filter_map(|x| x.as_f64()).collect())).collect();
    if pts.len() < 2 {
        return None;
    }
    let mut s = 0.0;
    for w in pts.windows(2) {
        let n = w[0].len().min(w[1].len());
        let d: f64 = (0..n).map(|i| (w[1][i] - w[0][i]).powi(2)).sum();
        s += d.sqrt();
    }
    Some(s)
}

fn round6(x: f64) -> f64 {
    let v = (x * 1e6).round() / 1e6;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// The material of a layered type's structure layer, by name.
fn structure_material(pr: &Project, def: &Value) -> Option<String> {
    let layers = def.get("layers")?.as_arr()?;
    let l = layers.iter().find(|l| txt(l, "function") == Some("structure"))?;
    let m = txt(l, "material")?;
    if is_guid(m) {
        common::material_name(pr, m)
    } else {
        Some(m.to_string())
    }
}

fn material_text(pr: &Project, m: &str) -> String {
    if is_guid(m) {
        common::material_name(pr, m).unwrap_or_else(|| m.to_string())
    } else {
        m.to_string()
    }
}

/// What a multi-category schedule's Material is: a layered type's structure layer's, a run's
/// type's, a family's (its first material parameter's value).
fn material(pr: &Project, cat: &str, v: &Value) -> Value {
    if v.get("family").is_some() {
        if let Some(vals) = v.get("values") {
            if let Some(m) = txt(vals, "Material") {
                return Value::s(&material_text(pr, m));
            }
            let fname = family_name(pr, v);
            let fam = fname.as_ref().and_then(|n| pr.section("families").and_then(|f| f.get(n)));
            if let Some(ps) = fam.and_then(|f| f.get("parameters")).and_then(|p| p.as_arr()) {
                for p in ps {
                    if txt(p, "kind") == Some("material") {
                        if let Some(n) = txt(p, "name") {
                            if let Some(m) = txt(vals, n) {
                                return Value::s(&material_text(pr, m));
                            }
                        }
                    }
                }
            }
        }
        return Value::Null;
    }
    let g = txt(v, "type_guid").or_else(|| txt(v, "type"));
    let Some(g) = g else {
        return Value::Null;
    };
    let Some((_, def)) = common::type_of(pr, cat, g) else {
        return Value::Null;
    };
    if let Some(m) = structure_material(pr, def) {
        return Value::s(&m);
    }
    if let Some((_, true, _)) = common::type_home(cat) {
        if let Some(m) = txt(def, "material") {
            return Value::s(&material_text(pr, m));
        }
    }
    Value::Null
}

// ---------------------------------------------------------------- phases and options

/// The name a library entry of a kind has, by its GUID (or the text itself).
fn lib_text(pr: &Project, kind: &str, g: &str) -> String {
    common::lib_name_of(pr, kind, g).unwrap_or_else(|| g.to_string())
}

fn param_of<'v>(e: &'v Value, k: &str) -> Option<&'v Value> {
    e.get("params").and_then(|p| p.get(k)).filter(|v| !v.is_null())
}

/// The element a door or window is in (its host wall), whose phases it has.
fn host_of<'p>(pr: &'p Project, e: &Value) -> Option<&'p Value> {
    let g = txt(e, "host").or_else(|| txt(e, "wall"))?;
    common::by_guid(pr, g).map(|(_, h)| h)
}

fn follows_host(cat: &str) -> bool {
    matches!(cat, "door" | "window")
}

/// An element's Phase Created: its own, its wall's for a door or window, else the first phase.
pub fn phase_created(pr: &Project, id: u64) -> Option<String> {
    let e = pr.el(id)?;
    let cat = common::category(e);
    let src = if follows_host(cat) { host_of(pr, e).unwrap_or(e) } else { e };
    match param_of(src, defs::PHASE_CREATED).and_then(|v| v.as_str()) {
        Some(g) => Some(lib_text(pr, "phase", g)),
        None => crate::styles::phasing::phases(pr).first().cloned(),
    }
}

/// An element's Phase Demolished (None: never).
pub fn phase_demolished(pr: &Project, id: u64) -> Option<String> {
    let e = pr.el(id)?;
    let cat = common::category(e);
    let src = if follows_host(cat) { host_of(pr, e).unwrap_or(e) } else { e };
    param_of(src, defs::PHASE_DEMOLISHED).and_then(|v| v.as_str()).map(|g| lib_text(pr, "phase", g))
}

/// An element's design option, `Set: Option` (a door or window with none is in its wall's).
pub fn design_option(pr: &Project, id: u64) -> Option<String> {
    let e = pr.el(id)?;
    let cat = common::category(e);
    let own = param_of(e, defs::DESIGN_OPTION).and_then(|v| v.as_str());
    let g = match own {
        Some(g) => Some(g),
        None if follows_host(cat) => host_of(pr, e).and_then(|h| param_of(h, defs::DESIGN_OPTION)).and_then(|v| v.as_str()),
        None => None,
    }?;
    Some(lib_text(pr, "design-option", g))
}

/// A phase's place in the project's order (the last but one for a name that isn't a phase).
pub fn phase_rank(pr: &Project, name: &str) -> usize {
    let ph = crate::styles::phasing::phases(pr);
    ph.iter().position(|p| p == name).unwrap_or(ph.len())
}

// ---------------------------------------------------------------- one element's values

/// What a schedule reads of one element: its id, its category and its view.
pub struct Item {
    pub id: u64,
    pub cat: String,
    pub view: Value,
    /// A mass floor's level (a mass floor's row is the mass at one of its levels).
    pub floor: Option<MassFloor>,
}

#[derive(Clone, Debug)]
pub struct MassFloor {
    pub level: String,
    pub area: f64,
    pub perimeter: f64,
    pub volume: f64,
}

/// A field's value for one element.
pub fn value(cx: &Ctx, f: &FieldDef, it: &Item) -> Value {
    let pr = cx.pr;
    match &f.src {
        Src::PhaseCreated => ftext(phase_created(pr, it.id).as_deref()),
        Src::PhaseDemolished => ftext(phase_demolished(pr, it.id).as_deref()),
        Src::DesignOption => ftext(design_option(pr, it.id).as_deref()),
        Src::Param(key) => {
            let e = pr.el(it.id);
            let v = e.and_then(|e| param_of(e, key)).cloned().or_else(|| {
                // values kept by the parameter's name
                e.and_then(|e| param_of(e, &f.name)).cloned()
            });
            match v {
                Some(v) => v,
                None if f.kind == Kind::YesNo => Value::Bool(false),
                None => Value::Null,
            }
        }
        Src::Family => match it.view.get("values").and_then(|vals| vals.get(&f.name)) {
            Some(Value::Str(s)) if f.kind == Kind::Text => Value::s(&material_text(pr, s)),
            Some(v) if !v.is_null() => match v {
                Value::Num(n) => Value::f(n.as_f64()),
                _ => v.clone(),
            },
            _ if f.kind == Kind::YesNo => Value::Bool(false),
            _ => Value::Null,
        },
        Src::Own => own(cx, &f.name, it),
    }
}

/// An element's own field (by its category's name for it).
pub fn own(cx: &Ctx, name: &str, it: &Item) -> Value {
    let pr = cx.pr;
    let v = &it.view;
    let cat = it.cat.as_str();
    if let Some(mf) = &it.floor {
        return match name {
            "Mass" => ftext(txt(v, "name")),
            "Level" => Value::s(&mf.level),
            "Area" => Value::f(mf.area),
            "Perimeter" => Value::f(mf.perimeter),
            "Volume" => Value::f(mf.volume),
            "Count" => Value::f(1.0),
            _ => Value::Null,
        };
    }
    match name {
        "Id" => Value::f(it.id as f64),
        "Count" => Value::f(1.0),
        "Category" => Value::s(cat),
        "Type" => {
            if cat == "level" || cat == "room" || cat == "mass" || cat == "stair" || cat == "ramp" || cat == "rebar" {
                return Value::Null;
            }
            ftext(type_name(pr, cat, v).as_deref())
        }
        "Family" => {
            if !matches!(cat, "door" | "window" | "component") {
                return Value::Null;
            }
            ftext(family_name(pr, v).as_deref())
        }
        "Level" => {
            if cat == "level" {
                return Value::Null;
            }
            let g = txt(v, "level").map(|s| s.to_string()).or_else(|| {
                if follows_host(cat) {
                    pr.el(it.id).and_then(|e| host_of(pr, e)).and_then(|h| txt(h, "level")).map(|s| s.to_string())
                } else {
                    None
                }
            });
            ftext(g.and_then(|g| level_name(pr, &g)).as_deref())
        }
        "Mark" => {
            if !matches!(cat, "door" | "window") {
                return Value::Null;
            }
            ftext(txt(v, "mark"))
        }
        "Name" => {
            if !matches!(cat, "room" | "mass" | "level") {
                return Value::Null;
            }
            ftext(txt(v, "name"))
        }
        "Number" => ftext(txt(v, "number")),
        "Wall" => match target_id(pr, v, "host") {
            Some(h) => Value::f(h as f64),
            None => Value::Null,
        },
        "Host" => match target_id(pr, v, "host") {
            Some(h) => Value::f(h as f64),
            None => Value::f(0.0),
        },
        "Operation" => match txt(v, "operation") {
            Some(op) => Value::s(&operation_text(op)),
            None => Value::Null,
        },
        "Width" => {
            if !has_own(cat, "Width") {
                return Value::Null;
            }
            fnum(num(v, "width").or_else(|| type_def(pr, cat, v).and_then(|d| num(d, "width"))))
        }
        "Height" => {
            if !has_own(cat, "Height") {
                return Value::Null;
            }
            fnum(num(v, "height").or_else(|| type_def(pr, cat, v).and_then(|d| num(d, "height"))))
        }
        "Sill" => fnum(num(v, "sill").or_else(|| type_def(pr, cat, v).and_then(|d| num(d, "sill")))),
        "Depth" => fnum(num(v, "depth")),
        "Length" => {
            if !has_own(cat, "Length") {
                return Value::Null;
            }
            fnum(num(v, "length").or_else(|| if cat == "railing" { path_length(v) } else { None }))
        }
        "Thickness" => {
            if !has_own(cat, "Thickness") {
                return Value::Null;
            }
            if cat == "footing" {
                return fnum(num(v, "height"));
            }
            fnum(num(v, "thickness"))
        }
        "Diameter" => {
            if cat == "rebar" {
                fnum(num(v, "diameter"))
            } else {
                fnum(num(v, "width").or_else(|| num(v, "diameter")))
            }
        }
        "Area" => match cat {
            "wall" => match (num(v, "length"), num(v, "height")) {
                (Some(l), Some(h)) => Value::f(round6(l * h / 1e6)),
                _ => Value::Null,
            },
            "door" | "window" => {
                let w = num(v, "width").or_else(|| type_def(pr, cat, v).and_then(|d| num(d, "width")));
                let h = num(v, "height").or_else(|| type_def(pr, cat, v).and_then(|d| num(d, "height")));
                match (w, h) {
                    (Some(w), Some(h)) => Value::f(round6(w * h / 1e6)),
                    _ => Value::Null,
                }
            }
            "floor" | "ceiling" | "room" | "mass" | "roof" => fnum(num(v, "area_m2")),
            _ => Value::Null,
        },
        "Plan Area" => fnum(num(v, "area_m2")),
        "Offset" => match cat {
            "floor" => fnum(Some(num(v, "offset").unwrap_or(0.0))),
            _ => fnum(num(v, "offset")),
        },
        "Structural" => Value::Bool(v.get("structural").and_then(|x| x.as_bool()).unwrap_or(false)),
        "Slope" => fnum(num(v, "slope")),
        "System" => ftext(txt(v, "system")),
        "Perimeter" => fnum(num(v, "perimeter_mm").or_else(|| num(v, "perimeter_m").map(|m| m * 1000.0))),
        "Unbounded Height" => fnum(num(v, "unbounded_height")),
        "Volume" => fnum(num(v, "volume_m3")),
        "Gross Floor Area" => fnum(num(v, "gross_floor_area_m2")),
        "Risers" => fnum(num(v, "risers")),
        "Riser Height" => fnum(num(v, "riser_height")),
        "Tread" => fnum(num(v, "tread")),
        "Grade" => ftext(txt(v, "grade")),
        "Weight" => fnum(num(v, "weight_kg")),
        "Layer" => ftext(txt(v, "layer")),
        "Elevation" => fnum(num(v, "elevation")),
        "Material" => material(pr, cat, v),
        _ => Value::Null,
    }
}

/// Whether a category has a field of this name of its own (a multi-category schedule's Width,
/// Height, Length and Thickness are each category's own).
fn has_own(cat: &str, name: &str) -> bool {
    defs::own_fields(cat).iter().any(|(n, _)| *n == name)
}

// ---------------------------------------------------------------- mass floors

/// A mass's floors: one at each level it crosses, from that level up to the next one (or its top).
pub fn mass_floors(pr: &Project, view: &Value) -> Vec<MassFloor> {
    let mut out = Vec::new();
    let area = num(view, "area_m2").unwrap_or(0.0);
    let perim = match view.get("boundary") {
        Some(b) => {
            let pts = common::points(b);
            let n = pts.len();
            let mut s = 0.0;
            for i in 0..n {
                let a = pts[i];
                let b = pts[(i + 1) % n];
                s += ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
            }
            s
        }
        None => 0.0,
    };
    let base = txt(view, "level").and_then(|g| common::level_elev(pr, g)).unwrap_or(0.0) + num(view, "base_offset").unwrap_or(0.0);
    let top = base + num(view, "height").unwrap_or(0.0);
    let levels: Vec<u64> = view
        .get("levels")
        .and_then(|l| l.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_u64()).collect())
        .unwrap_or_default();
    let all = crate::model::levels(pr);
    for (i, l) in levels.iter().enumerate() {
        let e = crate::model::elev(pr, *l);
        let next = match levels.get(i + 1) {
            Some(n) => crate::model::elev(pr, *n),
            None => all
                .iter()
                .map(|x| crate::model::elev(pr, *x))
                .filter(|x| *x > e)
                .fold(f64::INFINITY, f64::min)
                .min(top),
        };
        let h = (next.min(top) - e).max(0.0);
        out.push(MassFloor {
            level: crate::model::name(pr, *l),
            area,
            perimeter: perim,
            volume: round6(area * h / 1000.0),
        });
    }
    out
}
