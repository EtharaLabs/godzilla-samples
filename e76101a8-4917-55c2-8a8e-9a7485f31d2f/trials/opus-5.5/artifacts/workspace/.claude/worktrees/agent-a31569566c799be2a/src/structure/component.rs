//! `component`: a family's type placed at a point on a level, turned, raised and mirrored, its
//! instance parameters its own; its model rules and what `elements` shows of it.
//!
//! The file holds a component as `{guid, category, family, type, level, at, angle, offset,
//! mirrored?, params?}`: its family and type by GUID (the `family` and `family-type` library
//! entries), its level by GUID, and `params` keyed by GUID (a family parameter's
//! `family-parameter` entry, or a project parameter's), a material value by its GUID.

use crate::commands::params::{get, opt_bool, opt_num, opt_text, req_point};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::{add_element, new_guid, R};
use crate::structure::family::{self, check as fcheck, geom, model::Family, model::Kind, Eval, PVal};

const CMD: &str = "component";

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "component" => place(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

fn family_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = pr.section("families").map(|f| f.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// What `component` is asked, read in the original's order (its own refusals cut at 2000
/// characters).
struct Asked {
    fname: String,
    fam: Family,
    ty: String,
    params: Option<Map>,
    level: u64,
    at: [f64; 2],
    angle: f64,
    offset: f64,
    mirrored: bool,
}

fn asked(pr: &Project, p: &Value) -> R<Asked> {
    let fname = match opt_text(p, CMD, "family")? {
        Some(f) => f,
        None => return Err(format!("{}: `family` is required; `inspect` lists the families", CMD)),
    };
    let fam = match family::family_of(pr, &fname) {
        Some(f) => f,
        None => {
            return Err(format!("{}: family `{}` doesn't exist (there are: {})", CMD, fname, family_names(pr).join(", ")))
        }
    };
    let ty = match opt_text(p, CMD, "type")? {
        Some(t) => crate::structure::members::read::type_name_param(pr, &t),
        None => fam.types.first().map(|(n, _)| n.clone()).unwrap_or_default(),
    };
    let params = match get(p, "params") {
        None => None,
        Some(Value::Obj(m)) => Some(m.clone()),
        Some(v) => return Err(format!("{}: `params` is {{parameter: value}}, not {}", CMD, v.to_compact())),
    };
    let level = crate::structure::members::read::level_param(pr, CMD, p)?;
    let at = req_point(p, CMD, "at")?;
    let angle = opt_num(p, CMD, "angle")?.unwrap_or(0.0);
    let offset = opt_num(p, CMD, "offset")?.unwrap_or(0.0);
    let mirrored = opt_bool(p, CMD, "mirrored")?.unwrap_or(false);
    Ok(Asked { fname, fam, ty, params, level, at, angle, offset, mirrored })
}

fn place(s: &mut Session, p0: &Value) -> R<Value> {
    let p = &crate::structure::types::names_for_guids(&s.project, p0);
    let pr = &s.project;
    let Asked { fname, fam, ty, params, level, at, angle, offset, mirrored } =
        asked(pr, p).map_err(crate::structure::types::clip)?;

    let mut e = Map::new();
    e.insert("guid", Value::s(&new_guid()));
    e.insert("category", Value::s("component"));
    e.insert("family", Value::s(&pr.lib_guid(family::ids::FAMILY, &fname).unwrap_or_default()));
    e.insert("type", Value::s(&family::type_guid(pr, &fname, &ty).unwrap_or(ty.clone())));
    e.insert("level", Value::s(&pr.guid_of(level).unwrap_or_default()));
    e.insert("at", Value::Arr(vec![Value::f(at[0]), Value::f(at[1])]));
    e.insert("angle", Value::f(angle));
    e.insert("offset", Value::f(offset));
    if mirrored {
        e.insert("mirrored", Value::Bool(true));
    }
    if let Some(m) = &params {
        // a name neither the family's nor a project parameter of components' (what the model's
        // rules refuse first, in name order)
        let project: Vec<String> =
            crate::styles::parameters::for_category(pr, "component").into_iter().map(|(n, _, _)| n).collect();
        let mut unknown: Vec<&String> =
            m.keys().filter(|k| fam.param(k).is_none() && !project.contains(k) && !m.get(k).map(|v| v.is_null()).unwrap_or(true)).collect();
        unknown.sort();
        if let Some(k) = unknown.first() {
            let mut id = pr.next_id();
            while pr.elements.contains_key(&id) {
                id += 1;
            }
            return Err(format!("{} {}: `{}` isn't a parameter of components; add it with `parameter`", CMD, id, k));
        }
        let held = params_to_file(pr, &fname, &fam, m);
        if !held.is_empty() {
            e.insert("params", Value::Obj(held));
        }
    }
    let id = add_element(s, Value::Obj(e));
    Ok(crate::jobj! {"id" => id})
}

/// A component's `params` as the file keys them: a family parameter by its entry's GUID, a
/// project parameter by its; a material value by its GUID (what the project hasn't, as given).
pub fn params_to_file(pr: &Project, fname: &str, fam: &Family, m: &Map) -> Map {
    let mut out = Map::new();
    for (k, v) in m.iter() {
        if v.is_null() {
            continue;
        }
        let (key, val) = match fam.param(k) {
            Some(fp) => {
                let key = family::param_guid(pr, fname, k).unwrap_or_else(|| k.clone());
                let val = match (fp.kind, v) {
                    (Kind::Material, Value::Str(s)) if !s.is_empty() => {
                        Value::s(&pr.lib_guid("material", s).unwrap_or_else(|| s.clone()))
                    }
                    _ => v.clone(),
                };
                (key, val)
            }
            None => (crate::styles::parameters::key_of(pr, k).unwrap_or_else(|| k.clone()), v.clone()),
        };
        out.insert_sorted(&key, val);
    }
    out
}

/// A component as the original holds it: its family's name, its type's name (what the file
/// names, where it names none the project has), its values by parameter name.
pub struct Held {
    pub family: String,
    pub ty: String,
    /// Its own values of its family's parameters, by name.
    pub params: Map,
}

/// Reads a component's family, type and own values of its family's parameters.
pub fn held(pr: &Project, e: &Value) -> Option<Held> {
    let fg = e.get("family")?.as_str()?;
    let family = family::name_of_guid(pr, fg).or_else(|| if family::exists(pr, fg) { Some(fg.to_string()) } else { None })?;
    let t = e.get("type").and_then(|t| t.as_str()).unwrap_or("");
    let ty = family::type_name_of_guid(pr, &family, t).or_else(|| other_type_name(pr, t)).unwrap_or_else(|| t.to_string());
    let fam = family::family_of(pr, &family);
    let mut params = Map::new();
    if let Some(m) = e.get("params").and_then(|p| p.as_obj()) {
        for (k, v) in m.iter() {
            let name = match family::param_name_of_guid(pr, &family, k) {
                Some(n) => n,
                None => {
                    // a name the file holds as it is (a family's parameter, given by name)
                    if fam.as_ref().map(|f| f.param(k).is_some()).unwrap_or(false) {
                        k.clone()
                    } else {
                        continue;
                    }
                }
            };
            let kind = fam.as_ref().and_then(|f| f.param(&name)).map(|p| p.kind);
            let v = match (kind, v) {
                (Some(Kind::Material), Value::Str(s)) => Value::s(&material_name(pr, s)),
                _ => v.clone(),
            };
            params.insert_sorted(&name, v);
        }
    }
    Some(Held { family, ty, params })
}

/// The type a family-type GUID of another family names (its name after the family's).
fn other_type_name(pr: &Project, g: &str) -> Option<String> {
    let id = pr.lib_find_guid(g)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some(family::ids::FAMILY_TYPE) {
        return None;
    }
    let n = e.get("name").and_then(|n| n.as_str())?;
    n.split_once(": ").map(|(_, t)| t.to_string())
}

/// A `params` key the original can't read as a parameter of the component's own family: a
/// family parameter's GUID of another family (or of any, where it has no family).
fn foreign_key(pr: &Project, family: Option<&str>, k: &str) -> bool {
    let Some(id) = pr.lib_find_guid(k) else { return false };
    let Some(e) = pr.library.get(&id) else { return false };
    if e.get("kind").and_then(|x| x.as_str()) != Some(family::ids::FAMILY_PARAMETER) {
        return false;
    }
    let n = e.get("name").and_then(|x| x.as_str()).unwrap_or("");
    match family {
        Some(f) => !n.starts_with(&format!("{}: ", f)),
        None => true,
    }
}

fn material_name(pr: &Project, s: &str) -> String {
    if let Some(id) = pr.lib_find_guid(s) {
        if let Some(e) = pr.library.get(&id) {
            if e.get("kind").and_then(|k| k.as_str()) == Some("material") {
                return e.get("name").and_then(|n| n.as_str()).unwrap_or(s).to_string();
            }
        }
    }
    s.to_string()
}

/// A component's own values held to its family (`fam`, named `fname`): where it stands, each value of
/// its (sorted by name), its type, and the family worked out with its values.
pub fn check_held(pr: &Project, h: &Held, fname: &str, fam: &Family) -> R<()> {
    if fam.hosted() {
        return Err(format!(
            "family `{}` is a door's or a window's: it stands in a wall, placed with `door` or `window`",
            fname
        ));
    }
    for (k, v) in h.params.iter() {
        let Some(p) = fam.param(k) else { continue };
        if !p.instance {
            return Err(format!("`{}` is a type parameter of `{}`; change it in its type, with `family`", k, fname));
        }
        if p.formula.is_some() {
            return Err(format!("`{}` is worked out by its formula", k));
        }
        let fits = match (p.kind, v) {
            (_, Value::Null) => true,
            (Kind::Material, Value::Str(_)) => true,
            (Kind::YesNo, Value::Bool(_) | Value::Num(_)) => true,
            (Kind::Length | Kind::Number | Kind::Angle, Value::Num(_)) => true,
            _ => false,
        };
        if !fits {
            let holds = match p.kind {
                Kind::YesNo => "yes or no",
                Kind::Material => "a material's name",
                _ => "a number",
            };
            return Err(format!("parameter `{}` holds {}, not {}", k, holds, v.to_compact()));
        }
        if p.kind == Kind::Material {
            if let Value::Str(m) = v {
                if !m.is_empty() && !family::has_material(pr, m) {
                    return Err(format!("material `{}` isn't in the library; add it with `material`", m));
                }
            }
        }
    }
    if fam.type_values(&h.ty).is_none() {
        return Err(format!("type `{}` doesn't exist (there are: {})", h.ty, fam.type_names().join(", ")));
    }
    let ev = Eval::new(fam, Some(&h.ty), Some(&h.params), None);
    fcheck::parts_worked_out(fam, &ev)
}

/// The model rules of this part, checked after every command: each component (by id) of a
/// family the project has, held to it.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) != Some("component") {
            continue;
        }
        let fname = e.get("family").and_then(|f| f.as_str()).and_then(|g| family::name_of_guid(pr, g));
        if let Some(m) = e.get("params").and_then(|p| p.as_obj()) {
            for (k, _) in m.iter() {
                if foreign_key(pr, fname.as_deref(), k) {
                    return Err(format!("component {}: `{}` isn't a parameter of components; add it with `parameter`", id, k));
                }
            }
        }
        let Some(h) = held(pr, e) else { continue };
        let Some(fam) = family::family_of(pr, &h.family) else { continue };
        check_held(pr, &h, &h.family, &fam).map_err(|m| format!("component {}: {}", id, m))?;
    }
    Ok(())
}

/// The components of a family held to what a change makes of it (before the project takes the
/// change), as the model's rules would hold them after it; and its doors' and windows' types
/// (what the rest of an opening's rules say comes after the change, from its family's values).
pub fn check_family_users(pr: &Project, name: &str, new: &Family) -> R<()> {
    let Some(g) = pr.lib_guid(family::ids::FAMILY, name) else { return Ok(()) };
    for (id, e) in &pr.elements {
        if e.get("family").and_then(|f| f.as_str()) != Some(g.as_str()) {
            continue;
        }
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        if cat == "door" || cat == "window" {
            if let Some(h) = held(pr, e) {
                if new.type_values(&h.ty).is_none() {
                    return Err(format!(
                        "{} {}: type `{}` doesn't exist (there are: {})",
                        cat,
                        id,
                        h.ty,
                        new.type_names().join(", ")
                    ));
                }
            }
            continue;
        }
        if cat != "component" {
            continue;
        }
        let Some(h) = held(pr, e) else { continue };
        // a value of a parameter the family no longer has is one of components', unknown
        for (k, _) in h.params.iter() {
            if new.param(k).is_none() {
                return Err(format!("component {}: `{}` isn't a parameter of components; add it with `parameter`", id, k));
            }
        }
        check_held(pr, &h, name, new).map_err(|m| format!("component {}: {}", id, m))?;
    }
    Ok(())
}

/// A component's family worked out for its type and its own values.
fn worked(pr: &Project, e: &Value) -> Option<(Held, Family)> {
    let h = held(pr, e)?;
    let fam = family::family_of(pr, &h.family)?;
    Some((h, fam))
}

/// A number as `elements` shows a connector's.
fn num(x: f64) -> Value {
    Value::f(x)
}

/// What `elements` shows of a component besides its fields: its family and type by name (the
/// family's GUID as `family_guid`), its own values by parameter name, every parameter's value
/// worked out (`values`), how high it reaches over its base (`height`), and its connectors worked
/// out (`load_va` in all, `load_va_by_phase`).
pub fn element_view(pr: &Project, _id: u64, x: &mut Value) {
    let e = x.clone();
    let Some((h, fam)) = worked(pr, &e) else { return };
    if let Some(g) = e.get("family").and_then(|f| f.as_str()) {
        x.set("family_guid", Value::s(g));
    }
    x.set("family", Value::s(&h.family));
    x.set("type", Value::s(&h.ty));
    if let Some(m) = e.get("params").and_then(|p| p.as_obj()) {
        let mut shown = Map::new();
        for (k, v) in m.iter() {
            if let Some(n) = family::param_name_of_guid(pr, &h.family, k) {
                let v = match (fam.param(&n).map(|p| p.kind), v) {
                    (Some(Kind::Material), Value::Str(s)) => Value::s(&material_name(pr, s)),
                    _ => v.clone(),
                };
                shown.insert_sorted(&n, v);
            } else if let Some(n) = crate::styles::parameters::param_of_key(pr, k) {
                shown.insert_sorted(&n, v.clone());
            } else {
                shown.insert_sorted(k, v.clone());
            }
        }
        x.set("params", Value::Obj(shown));
    }
    let ev = Eval::new(&fam, Some(&h.ty), Some(&h.params), None);
    if let Ok(vals) = ev.values() {
        x.set("values", family::eval::values_view(&vals));
    }
    // to the hundredth of a millimetre, as `elements` shows lengths
    let h = fcheck::height(&fcheck::pieces(&fam, &ev));
    x.set("height", Value::f((h * 100.0).round() / 100.0));
    if !fam.connectors.is_empty() {
        // none shown where one of them doesn't work out for its values
        let worked: Result<Vec<_>, String> = fam.connectors.iter().map(|c| fcheck::connector_values(c, &ev)).collect();
        let Ok(worked) = worked else { return };
        let mut out = Vec::new();
        for (c, v) in fam.connectors.iter().zip(worked) {
            let mut m = Map::new();
            m.insert("classification", Value::s(&c.classification));
            if let Some(g) = &c.guid {
                m.insert("guid", g.value());
            }
            if let Some(id) = c.id {
                m.insert("id", Value::u(id));
            }
            m.insert("kind", Value::s(c.kind.name()));
            let total = if v.load_by_phase.is_empty() { -0.0 } else { v.load() };
            m.insert("load_va", num(total));
            m.insert("load_va_by_phase", Value::Arr(v.load_by_phase.iter().map(|l| num(*l)).collect()));
            m.insert("poles", Value::u(c.poles as u64));
            m.insert("power_factor", num(v.power_factor));
            m.insert("system", Value::s(c.system.name()));
            m.insert("voltage", num(v.voltage));
            out.push(Value::Obj(m));
        }
        x.set("connectors", Value::Arr(out));
    }
}

/// A component's forms where it stands: each solid (voids cut), in the project's axes (mm,
/// z over the project's zero: its level's elevation and its offset), with its material's name.
pub struct Placed {
    pub index: usize,
    pub material: String,
    pub triangles: Vec<[geom::V3; 3]>,
}

/// A component's forms worked out where it stands (for IFC and the views): mirrored across its
/// own x axis, turned `angle` degrees about its point, at its level's elevation and offset.
pub fn placed_pieces(pr: &Project, id: u64) -> Vec<Placed> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let Some((h, fam)) = worked(pr, e) else { return Vec::new() };
    let ev = Eval::new(&fam, Some(&h.ty), Some(&h.params), None);
    let pieces = fcheck::cut(&fcheck::pieces(&fam, &ev));
    let at = e.get("at").and_then(|a| a.as_arr()).map(|a| [a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)]).unwrap_or([0.0, 0.0]);
    let angle = e.get("angle").and_then(|a| a.as_f64()).unwrap_or(0.0).to_radians();
    let offset = e.get("offset").and_then(|a| a.as_f64()).unwrap_or(0.0);
    let mirrored = e.get("mirrored").and_then(|m| m.as_bool()).unwrap_or(false);
    let elevation = e
        .get("level")
        .and_then(|l| l.as_str())
        .and_then(|g| crate::structure::members::read::element_by_guid(pr, g))
        .and_then(|lid| pr.el(lid))
        .and_then(|l| l.get("elevation"))
        .and_then(|z| z.as_f64())
        .unwrap_or(0.0);
    let (c, s) = (angle.cos(), angle.sin());
    let f = move |p: geom::V3| -> geom::V3 {
        let y = if mirrored { 0.0 - p[1] } else { p[1] };
        [at[0] + p[0] * c - y * s, at[1] + p[0] * s + y * c, elevation + offset + p[2]]
    };
    pieces
        .into_iter()
        .map(|pc| Placed { index: pc.index, material: pc.material, triangles: geom::mapped(&pc.solid.triangles(), &f, mirrored) })
        .filter(|p| !p.triangles.is_empty())
        .collect()
}

/// A component's forms worked out in its own axes (voids cut, mirrored across its x axis when it
/// is, so turned out), for IFC, which places them with the component's point, angle and height:
/// what `placed_pieces` gives before it turns and moves them. The triangles come in the
/// original's order, each with its corners in the original's order (mirrored: the last two
/// swapped); a form a void takes away whole is left out. The original's IFC writes each piece
/// as a face set of them: its points those of the corners in order of first use, corners whose
/// coordinates round to the same thousandths being one point (the first one's coordinates
/// written), and a triangle left with fewer than three points of its own left out.
pub fn local_pieces(pr: &Project, id: u64) -> Vec<Placed> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let Some((h, fam)) = worked(pr, e) else { return Vec::new() };
    let ev = Eval::new(&fam, Some(&h.ty), Some(&h.params), None);
    let pieces = fcheck::cut(&fcheck::pieces(&fam, &ev));
    let mirrored = e.get("mirrored").and_then(|m| m.as_bool()).unwrap_or(false);
    let f = move |p: geom::V3| -> geom::V3 {
        if mirrored {
            [p[0], 0.0 - p[1], p[2]]
        } else {
            p
        }
    };
    pieces
        .into_iter()
        .map(|pc| Placed { index: pc.index, material: pc.material, triangles: geom::mapped(&pc.solid.triangles(), &f, mirrored) })
        .filter(|p| !p.triangles.is_empty())
        .collect()
}

/// A component's connectors worked out for its type and its own values.
pub fn connectors(pr: &Project, id: u64) -> Vec<(family::model::Connector, family::ConnectorValues)> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let Some((h, fam)) = worked(pr, e) else { return Vec::new() };
    let ev = Eval::new(&fam, Some(&h.ty), Some(&h.params), None);
    fam.connectors.iter().filter_map(|c| fcheck::connector_values(c, &ev).ok().map(|v| (c.clone(), v))).collect()
}

/// A component's parameter values worked out (as `elements` shows them in `values`).
pub fn values(pr: &Project, id: u64) -> Vec<(String, PVal)> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let Some((h, fam)) = worked(pr, e) else { return Vec::new() };
    Eval::new(&fam, Some(&h.ty), Some(&h.params), None).values().unwrap_or_default()
}
