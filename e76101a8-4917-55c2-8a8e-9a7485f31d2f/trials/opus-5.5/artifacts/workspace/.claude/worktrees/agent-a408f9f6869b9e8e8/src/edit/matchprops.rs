//! Match Properties: the type (and a component's family) of one element given to others.

use super::common::*;
use super::library_util::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const C: &str = "match_properties";

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    match_properties(s, p).map_err(clip_error)
}

fn match_properties(s: &mut Session, p: &Value) -> R<Value> {
    let pr = &mut s.project;
    let Some(fv) = p.get("from") else {
        return Err(format!("{}: `from` (an element id or GUID) is required", C));
    };
    let from = resolve_element(pr, C, fv)?;
    let fe = pr.el(from).cloned().unwrap_or(Value::Null);
    let Some(ftype) = fe.get("type").and_then(|t| t.as_str()).map(|t| t.to_string()) else {
        return Err(format!("{}: element {} has no type", C, from));
    };
    let ffamily = fe.get("family").and_then(|f| f.as_str()).map(|f| f.to_string());
    let ids = element_ids(pr, C, p)?;
    let cat = cat_of(&fe).to_string();
    let mut modified: Vec<u64> = Vec::new();
    let mut skipped: Vec<u64> = Vec::new();
    for id in ids {
        if id == from {
            continue;
        }
        if pr.category(id) == Some(cat.as_str()) {
            modified.push(id);
        } else {
            skipped.push(id);
        }
    }
    if modified.is_empty() {
        return Err(format!("{}: none of the elements is in the category of element {} ({})", C, from, cat));
    }
    for id in &modified {
        let old_family = pr.el(*id).and_then(|e| e.get("family")).and_then(|f| f.as_str()).map(|f| f.to_string());
        let new_params = match &ffamily {
            Some(nf) if old_family.as_deref() != Some(nf.as_str()) => {
                rekeyed_params(pr, pr.el(*id).unwrap(), old_family.as_deref(), nf)
            }
            _ => None,
        };
        let Some(e) = pr.el_mut(*id) else { continue };
        e.set("type", Value::s(&ftype));
        if let Some(nf) = &ffamily {
            set_family(e, nf);
        }
        if let Some(params) = new_params {
            e.set("params", Value::Obj(params));
        }
    }
    family_types_hold(pr, &modified)?;
    let ids_value = |v: &Vec<u64>| Value::Arr(v.iter().map(|i| Value::u(*i)).collect());
    Ok(jobj! {"modified" => ids_value(&modified), "skipped" => ids_value(&skipped)})
}

/// An element's family set: in its place if it has one, else just after its `type` (a door's or
/// a window's, as the original writes them).
fn set_family(e: &mut Value, family: &str) {
    let Some(m) = e.as_obj_mut() else { return };
    if m.contains("family") {
        m.insert("family", Value::s(family));
        return;
    }
    let pos = m.items.iter().position(|(k, _)| k == "type").map(|i| i + 1).unwrap_or(m.items.len());
    m.items.insert(pos, ("family".to_string(), Value::s(family)));
}

/// An element's own values (`params`) as its new family holds them: a value of a parameter of
/// its old family goes to the new family's parameter of that name (its GUID), or stays under the
/// bare name if the new family has none (which the model's check then refuses); the rest stay.
/// Keys in order, as the original keeps them. None if it holds none.
fn rekeyed_params(pr: &Project, e: &Value, old_family: Option<&str>, new_family: &str) -> Option<Map> {
    let params = e.get("params").and_then(|p| p.as_obj())?;
    let old_name = old_family.and_then(|g| pr.lib_name(g));
    let new_name = pr.lib_name(new_family).unwrap_or_default();
    let mut out = Map::new();
    for (k, v) in params.iter() {
        let entry = crate::model::normalize_guid(k).and_then(|g| {
            pr.library.values().find(|x| x.get("guid").and_then(|y| y.as_str()) == Some(g.as_str()))
        });
        let is_family_param = entry.and_then(|x| x.get("kind")).and_then(|x| x.as_str()) == Some("family-parameter");
        if !is_family_param {
            out.insert(k, v.clone());
            continue;
        }
        let full = entry.and_then(|x| x.get("name")).and_then(|x| x.as_str()).unwrap_or("");
        let pname = match old_name.as_deref().and_then(|o| full.strip_prefix(&format!("{}: ", o))) {
            Some(n) => n.to_string(),
            None => full.split_once(": ").map(|(_, n)| n.to_string()).unwrap_or_else(|| full.to_string()),
        };
        let key = pr.lib_guid("family-parameter", &qualified(&new_name, &pname)).unwrap_or(pname);
        out.insert(&key, v.clone());
    }
    out.sort();
    Some(out)
}

/// The model's rule that an element of a family is of one of its family's types: a door taking a
/// project door type keeps its family, which hasn't that type.
fn family_types_hold(pr: &Project, ids: &[u64]) -> R<()> {
    let mut ids: Vec<u64> = ids.to_vec();
    ids.sort();
    for id in ids {
        let Some(e) = pr.el(id) else { continue };
        let Some(fg) = e.get("family").and_then(|f| f.as_str()) else { continue };
        let Some(fname) = pr.lib_name(fg) else { continue };
        let Some(fam) = families(pr).and_then(|m| m.get(&fname)) else { continue };
        let types = family_type_names(fam);
        let tg = e.get("type").and_then(|t| t.as_str()).unwrap_or("");
        let tname = pr.lib_name(tg).unwrap_or_else(|| tg.to_string());
        let ok = types.iter().any(|t| qualified(&fname, t) == tname);
        if !ok {
            return Err(check_error(format!(
                "{} {}: type `{}` doesn't exist (there are: {})",
                cat_of(e),
                id,
                tname,
                types.join(", ")
            )));
        }
    }
    Ok(())
}
