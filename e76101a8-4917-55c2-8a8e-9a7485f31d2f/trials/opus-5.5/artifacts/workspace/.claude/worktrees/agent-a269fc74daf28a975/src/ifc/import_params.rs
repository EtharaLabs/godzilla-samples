//! Project parameters (a `Project Parameters` property set, and the single values of other
//! programs' sets), marks from names, and phases and design options from `BIMCraft_Phasing`.

use super::import::Ctx;
use super::import_build::r3;
use super::step::P;
use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// What this module keeps for later passes.
#[derive(Default)]
pub struct State {
    /// The project parameters made: name → (kind, categories).
    pub made: BTreeMap<String, (String, Vec<String>)>,
}

/// Sets one of an element's parameter values (its `params`, kept sorted by key), the key
/// placed where the element's kind keeps it.
pub fn set_param(e: &mut Value, key: &str, v: Value) {
    if let Value::Obj(m) = e {
        if !m.contains("params") {
            insert_params(m);
        }
        if let Some(Value::Obj(p)) = m.get_mut("params") {
            p.insert_sorted(key, v);
        }
    }
}

/// Puts an empty `params` where an element's kind keeps it: last but for a room's, a
/// column's (`room_bounding` after it) and a wall's (`room_bounding` before it) fields.
fn insert_params(m: &mut Map) {
    let cat = m.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
    let after: &[&str] = match cat.as_str() {
        "room" => &["base_offset", "top_level", "limit_offset", "frozen", "kept"],
        "column" | "structuralcolumn" | "footing" => &["room_bounding"],
        "railing" => &[],
        _ => &[],
    };
    let pos = m.items.iter().position(|(k, _)| after.contains(&k.as_str())).unwrap_or(m.items.len());
    m.items.insert(pos, ("params".to_string(), Value::obj()));
}

/// The schedule fields of a category: names a project parameter can't have there.
fn fields(cat: &str) -> &'static [&'static str] {
    const PH: [&str; 3] = ["Phase Created", "Phase Demolished", "Design Option"];
    let _ = PH;
    match cat {
        "room" => &["Number", "Name", "Level", "Area", "Perimeter", "Count", "Unbounded Height", "Volume", "Phase Created", "Phase Demolished", "Design Option"],
        "door" => &["Mark", "Type", "Width", "Height", "Level", "Wall", "Family", "Operation", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "window" => &["Mark", "Type", "Width", "Height", "Sill", "Level", "Wall", "Family", "Operation", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "wall" => &["Id", "Type", "Level", "Length", "Height", "Thickness", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "floor" => &["Id", "Type", "Level", "Area", "Thickness", "Offset", "Count", "Structural", "Phase Created", "Phase Demolished", "Design Option"],
        "ceiling" => &["Id", "Type", "Level", "Offset", "Area", "Thickness", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "roof" => &["Id", "Type", "Level", "Slope", "Plan Area", "Offset", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "column" | "structuralcolumn" => &["Id", "Type", "Level", "Width", "Depth", "Height", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "footing" => &["Id", "Type", "Level", "Width", "Depth", "Thickness", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "beam" | "stripfooting" => &["Id", "Type", "Level", "Length", "Width", "Depth", "System", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "component" => &["Family", "Type", "Level", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "stair" => &["Id", "Level", "Width", "Height", "Risers", "Riser Height", "Tread", "Length", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "ramp" => &["Id", "Level", "Width", "Height", "Length", "Slope", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "railing" => &["Id", "Type", "Level", "Length", "Height", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "level" => &["Elevation", "Name", "Count"],
        "pipe" | "conduit" | "wire" | "cable" => &["Id", "Type", "Level", "System", "Length", "Diameter", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "duct" | "cabletray" | "downconductor" | "groundconductor" => {
            &["Id", "Type", "Level", "System", "Length", "Width", "Depth", "Count", "Phase Created", "Phase Demolished", "Design Option"]
        }
        "mass" => &["Name", "Level", "Height", "Area", "Volume", "Gross Floor Area", "Count", "Phase Created", "Phase Demolished", "Design Option"],
        "rebar" => &["Id", "Level", "Grade", "Diameter", "Length", "Count", "Weight", "Host", "Layer"],
        _ => &["Count", "Phase Created", "Phase Demolished", "Design Option"],
    }
}

/// Whether a name is one a formula can say: a letter first, then letters, digits, underscores
/// and single spaces.
fn sayable(n: &str) -> bool {
    let mut cs = n.chars();
    match cs.next() {
        Some(c) if c.is_alphabetic() => {}
        _ => return false,
    }
    n.chars().all(|c| c.is_alphanumeric() || c == '_' || c == ' ')
}

/// A property's name less the characters a formula can't say (spaces for them, runs of
/// spaces as one, none at the ends).
fn clean(n: &str) -> String {
    let s: String = n.chars().map(|c| if c.is_alphanumeric() || c == '_' { c } else { ' ' }).collect();
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// A property's value as a project parameter's: its kind and value.
fn value_of(ctx: &Ctx, p: &P) -> Option<(&'static str, Value)> {
    let (name, inner) = match p {
        P::Typed(n, v) if v.len() == 1 => (n.as_str(), &v[0]),
        _ => return None,
    };
    match name {
        "IFCLABEL" | "IFCTEXT" | "IFCIDENTIFIER" => Some(("text", Value::s(inner.str()?))),
        "IFCREAL" | "IFCINTEGER" | "IFCNUMERICMEASURE" | "IFCCOUNTMEASURE" => Some(("number", Value::f(inner.num()?))),
        "IFCLENGTHMEASURE" | "IFCPOSITIVELENGTHMEASURE" | "IFCNONNEGATIVELENGTHMEASURE" => Some(("length", Value::f(r3(inner.num()? * ctx.m.scale)))),
        "IFCBOOLEAN" | "IFCLOGICAL" => match inner.enm()? {
            "T" => Some(("yesno", Value::Bool(true))),
            "F" => Some(("yesno", Value::Bool(false))),
            _ => None,
        },
        _ => None,
    }
}

/// After every element is in: their parameters, marks, phases and options.
pub fn params(ctx: &mut Ctx) {
    phasing_project(ctx);
    let ents: Vec<u64> = ctx.made.keys().copied().collect();
    for ent in ents {
        element_params(ctx, ent);
    }
    marks(ctx);
    // the parameters made, each on the categories it holds values on
    let made = std::mem::take(&mut ctx.params.made);
    for (name, (kind, mut cats)) in made {
        cats.sort();
        let sec = ctx.pr.section_mut("parameters");
        sec.insert_sorted(&name, crate::jobj! {"kind" => kind.as_str(), "categories" => Value::Arr(cats.iter().map(|c| Value::s(c)).collect())});
    }
}

/// A project parameter made (or found) for a value of a kind on an element of a category:
/// its GUID, unless it already is one of another kind.
fn parameter(ctx: &mut Ctx, name: &str, kind: &str, cat: &str) -> Option<String> {
    match ctx.params.made.get_mut(name) {
        Some((k, cats)) => {
            if k != kind {
                return None;
            }
            if !cats.iter().any(|c| c == cat) {
                cats.push(cat.to_string());
            }
        }
        None => {
            ctx.params.made.insert(name.to_string(), (kind.to_string(), vec![cat.to_string()]));
        }
    }
    Some(ctx.lib.get(&ctx.pr, "parameter", name))
}

fn element_params(ctx: &mut Ctx, ent: u64) {
    let made = match ctx.made.get(&ent) {
        Some(m) => m.clone(),
        None => return,
    };
    let cat = made.cat.clone();
    if cat == "level" {
        return;
    }
    let sets = ctx.m.psets(ent);
    let mut vals: Vec<(String, Value)> = Vec::new();
    for (set, props) in &sets {
        if set.starts_with("Qto_") || set.starts_with("BIMCraft_") {
            continue;
        }
        let pp = set == "Project Parameters";
        for (pname, pv) in props {
            let name = if pp {
                let n = pname.trim().to_string();
                if !sayable(&n) {
                    continue;
                }
                n
            } else {
                if pname == "LoadBearing" {
                    continue;
                }
                let n = clean(pname);
                if !sayable(&n) {
                    continue;
                }
                n
            };
            if fields(&cat).contains(&name.as_str()) {
                continue;
            }
            let (kind, v) = match value_of(ctx, pv) {
                Some(x) => x,
                None => continue,
            };
            let g = match parameter(ctx, &name, kind, &cat) {
                Some(g) => g,
                None => continue,
            };
            vals.push((g, v));
        }
    }
    // its phase and option
    for (set, props) in &sets {
        if set != "BIMCraft_Phasing" {
            continue;
        }
        for (pname, pv) in props {
            let text = match pv.str() {
                Some(t) => t.to_string(),
                None => continue,
            };
            match pname.as_str() {
                "Phase Created" | "Phase Demolished" => {
                    if pname == "Phase Created" && implied(ctx, ent) {
                        continue;
                    }
                    if !phases(ctx).contains(&text) {
                        ctx.skip(ent, &format!("its {} `{}` is no phase of the project's: it stays, in no phase", pname.to_lowercase(), text));
                        continue;
                    }
                    let g = ctx.lib.get(&ctx.pr, "phase", &text);
                    vals.push((pname.clone(), Value::s(&g)));
                }
                "Design Option" => {
                    if !options(ctx).contains(&text) {
                        ctx.skip(ent, &format!("its design option `{}` is no option of the project's: it stays, in the main model", text));
                        continue;
                    }
                    let g = ctx.lib.get(&ctx.pr, "design-option", &text);
                    vals.push((pname.clone(), Value::s(&g)));
                }
                _ => {}
            }
        }
    }
    if vals.is_empty() {
        return;
    }
    if let Some(e) = ctx.pr.el_mut(made.id) {
        for (k, v) in vals {
            set_param(e, &k, v);
        }
    }
}

/// Whether an element's `Phase Created` is said to be implied (its Description).
fn implied(ctx: &Ctx, ent: u64) -> bool {
    if let Some(defs) = ctx.m.props.get(&ent) {
        for d in defs {
            let e = match ctx.m.get(*d) {
                Some(e) => e,
                None => continue,
            };
            if e.name != "IFCPROPERTYSET" || e.p(2).str() != Some("BIMCraft_Phasing") {
                continue;
            }
            for p in e.p(4).refs() {
                if let Some(pe) = ctx.m.get(p) {
                    if pe.p(0).str() == Some("Phase Created") {
                        return pe.p(1).str().map(|s| s.starts_with("Implied")).unwrap_or(false);
                    }
                }
            }
        }
    }
    false
}

fn phases(ctx: &Ctx) -> Vec<String> {
    match ctx.pr.doc.get("phases").and_then(|p| p.as_arr()) {
        Some(a) => a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect(),
        None => vec!["Existing".into(), "New Construction".into()],
    }
}

fn options(ctx: &Ctx) -> Vec<String> {
    let mut out = Vec::new();
    if let Some(os) = ctx.pr.section("option_sets") {
        for (n, s) in os.iter() {
            if let Some(a) = s.get("options").and_then(|o| o.as_arr()) {
                for o in a {
                    if let Some(o) = o.as_str() {
                        out.push(format!("{}: {}", n, o));
                    }
                }
            }
        }
    }
    out
}

/// The project's phases, phase filters, overrides and option sets, from its
/// `BIMCraft_Phasing` set.
fn phasing_project(ctx: &mut Ctx) {
    let project = match ctx.m.of("IFCPROJECT").first() {
        Some(p) => *p,
        None => return,
    };
    let defs = ctx.m.props.get(&project).cloned().unwrap_or_default();
    for d in defs {
        let e = match ctx.m.get(d) {
            Some(e) => e.clone(),
            None => continue,
        };
        if e.name != "IFCPROPERTYSET" || e.p(2).str() != Some("BIMCraft_Phasing") {
            continue;
        }
        for p in e.p(4).refs() {
            let pe = match ctx.m.get(p) {
                Some(x) => x.clone(),
                None => continue,
            };
            let name = pe.p(0).str().unwrap_or("").to_string();
            match (pe.name.as_str(), name.as_str()) {
                ("IFCPROPERTYLISTVALUE", "Phases") => {
                    let names: Vec<Value> = pe.p(2).list().map(|l| l.iter().filter_map(|x| x.str().map(Value::s)).collect()).unwrap_or_default();
                    if !names.is_empty() {
                        ctx.pr.insert_top("phases", Value::Arr(names));
                    }
                }
                ("IFCPROPERTYSINGLEVALUE", "Phase Filters") => {
                    if let Some(v) = pe.p(2).str().and_then(|s| crate::json::parse(s).ok()) {
                        if v.as_obj().is_some() {
                            ctx.pr.insert_top("phase_filters", v);
                        }
                    }
                }
                ("IFCPROPERTYSINGLEVALUE", "Phase Overrides") => {
                    if let Some(v) = pe.p(2).str().and_then(|s| crate::json::parse(s).ok()) {
                        if v.as_obj().is_some() {
                            ctx.pr.insert_top("phase_overrides", v);
                        }
                    }
                }
                ("IFCPROPERTYSINGLEVALUE", "Design Option Sets") => {
                    if let Some(Value::Obj(sets)) = pe.p(2).str().and_then(|s| crate::json::parse(s).ok()) {
                        let mut out = Map::new();
                        for (sn, sv) in sets.items {
                            let opts: Vec<String> = sv.get("options").and_then(|o| o.as_arr()).map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect()).unwrap_or_default();
                            let primary = sv.get("primary").and_then(|p| p.as_str()).map(|s| s.to_string());
                            let mut m = Map::new();
                            m.insert("options", Value::Arr(opts.iter().map(|o| Value::s(o)).collect()));
                            if let Some(p) = primary {
                                let g = ctx.lib.get(&ctx.pr, "design-option", &format!("{}: {}", sn, p));
                                m.insert("primary", Value::s(&g));
                            }
                            out.insert(&sn, Value::Obj(m));
                        }
                        ctx.pr.insert_top("option_sets", Value::Obj(out));
                    }
                }
                _ => {}
            }
        }
    }
}

/// A beam's, column's, footing's or floor's name, where it isn't its type's, as its Mark.
fn marks(ctx: &mut Ctx) {
    let marks = std::mem::take(&mut ctx.structure.marks);
    for (ent, cat, mark) in marks {
        let g = match parameter(ctx, "Mark", "text", &cat) {
            Some(g) => g,
            None => continue,
        };
        if let Some(m) = ctx.made.get(&ent) {
            let id = m.id;
            if let Some(e) = ctx.pr.el_mut(id) {
                set_param(e, &g, Value::s(&mark));
            }
        }
    }
}
