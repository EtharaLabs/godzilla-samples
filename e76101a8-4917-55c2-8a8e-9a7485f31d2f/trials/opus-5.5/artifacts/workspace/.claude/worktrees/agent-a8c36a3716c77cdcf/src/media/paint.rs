//! `paint`: a material laid over faces of elements, as Revit's Paint does. An element keeps it
//! in `params.Paint`, `{face: the material's GUID}`.

use crate::commands::params::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// The faces an element of a category has to paint.
pub fn faces(cat: &str) -> Option<&'static [&'static str]> {
    match cat {
        "wall" => Some(&["exterior", "interior"]),
        "floor" | "roof" | "ceiling" => Some(&["top", "bottom"]),
        "column" | "component" | "door" | "window" | "stair" | "ramp" | "railing" => Some(&["all"]),
        _ => None,
    }
}

fn not_an_id(v: &Value) -> String {
    format!("paint: {} is not an element id or GUID", v.to_compact())
}

/// An element by its id (a number, or one in a string) or its GUID.
fn element(pr: &Project, v: &Value) -> Result<u64, String> {
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(|| not_an_id(v))?;
            if pr.elements.contains_key(&id) {
                Ok(id)
            } else {
                Err(format!("paint: no element {}", id))
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                return if pr.elements.contains_key(&id) { Ok(id) } else { Err(format!("paint: no element {}", id)) };
            }
            match crate::model::normalize_guid(t) {
                Some(g) => pr.find_guid(&g).ok_or_else(|| format!("paint: no element {}", t)),
                None => Err(not_an_id(v)),
            }
        }
        _ => Err(not_an_id(v)),
    }
}

/// A material of the library by its name (or its GUID): its GUID.
pub fn material_ref(pr: &Project, name: &str) -> Option<String> {
    if super::material::material(pr, name).is_some() {
        return super::material::material_guid(pr, name);
    }
    let g = crate::model::normalize_guid(name)?;
    let n = super::material::material_name(pr, &g)?;
    super::material::material(pr, &n)?;
    Some(g)
}

pub fn cmd(s: &mut Session, p: &Value) -> Result<Value, String> {
    let refs: Vec<Value> = match p.get("ids") {
        Some(Value::Arr(a)) => a.clone(),
        Some(Value::Null) | None => match p.get("id") {
            Some(v) => vec![v.clone()],
            None => return Err("paint: `ids` [id, …] is required".into()),
        },
        Some(_) => return Err("paint: `ids` [id, …] is required".into()),
    };
    let pr = &mut s.project;
    let mut ids: Vec<u64> = Vec::new();
    for r in &refs {
        let id = element(pr, r)?;
        if !ids.contains(&id) {
            ids.push(id);
        }
    }
    let material = match p.get("material") {
        None => return Err("paint: `material` is required: a material's name, or null to take the paint off".into()),
        Some(Value::Null) => None,
        Some(Value::Str(s)) => {
            let n = s.trim();
            match material_ref(pr, n) {
                Some(g) => Some(g),
                None => return Err(format!("paint: the library has no `{}`; add it with `material`", n)),
            }
        }
        Some(v) => return Err(format!("paint: `material` is a material's name, or null, not {}", v.to_compact())),
    };
    let face = opt_text(p, "paint", "face")?;
    // every element first, then the paint
    let mut plan: Vec<(u64, Vec<&'static str>)> = Vec::new();
    for &id in &ids {
        let cat = pr.category(id).unwrap_or("").to_string();
        let fs = match faces(&cat) {
            Some(f) => f,
            None => return Err(format!("paint: {} {} has no face to paint", cat, id)),
        };
        let chosen: Vec<&'static str> = match &face {
            None => fs.to_vec(),
            Some(f) => match fs.iter().find(|x| **x == f.as_str()) {
                Some(x) => vec![*x],
                None => {
                    return Err(format!("paint: a {} has no face `{}`; its faces are {}", cat, f, fs.join(", ")));
                }
            },
        };
        plan.push((id, chosen));
    }
    for (id, chosen) in plan {
        let e = pr.el_mut(id).unwrap();
        let mut params = e.get("params").cloned().unwrap_or_else(Value::obj);
        let mut paint = params.get("Paint").cloned().unwrap_or_else(Value::obj);
        for f in chosen {
            let pm = paint.as_obj_mut().unwrap();
            match &material {
                Some(g) => pm.insert_sorted(f, Value::s(g)),
                None => {
                    pm.remove(f);
                }
            }
        }
        if paint.as_obj().map(|m| m.is_empty()).unwrap_or(true) {
            params.remove("Paint");
        } else if let Some(pm) = params.as_obj_mut() {
            pm.insert_sorted("Paint", paint);
        }
        if params.as_obj().map(|m| m.is_empty()).unwrap_or(true) {
            e.remove("params");
        } else {
            e.set("params", params);
        }
    }
    Ok(jobj! {"painted" => ids})
}
