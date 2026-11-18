//! Delete: elements, and what goes with them.
//!
//! What points at an element that goes goes with it: a wall's doors and windows (and their tags),
//! whatever a tag, a spot elevation, a railing or a bar is on, a view's notes, lines, regions,
//! groups, spots, dimensions and viewports, a sheet's viewports and notes, a level's plan views,
//! a parent view's dependent views, and a dimension left with fewer than two references. The rest
//! just lets go of it: dimensions lose the references, walls their attachments, roofs their join,
//! what a mass made its mass, and views their graphics for it.

use super::common::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use std::collections::BTreeSet;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let p = &super::ops_geom::lib_names(&s.project, p);
    let ids = ids_param(&s.project, "delete", p)?;
    let pr = &mut s.project;
    let set: BTreeSet<u64> = ids.into_iter().collect();
    let gone = delete_elements(pr, &set);
    Ok(jobj! {"deleted" => gone})
}

fn gstr<'a>(e: &'a Value, k: &str) -> Option<&'a str> {
    e.get(k).and_then(|x| x.as_str())
}

/// Deletes the elements and what goes with them; the ids that went, in order.
pub fn delete_elements(pr: &mut Project, ids: &BTreeSet<u64>) -> Vec<u64> {
    let mut gone: BTreeSet<u64> = ids.iter().copied().filter(|id| pr.elements.contains_key(id)).collect();
    loop {
        let guids: BTreeSet<String> = gone.iter().filter_map(|id| pr.guid_of(*id)).collect();
        let is_gone = |k: Option<&str>| k.map(|g| guids.contains(g)).unwrap_or(false);
        let mut more = Vec::new();
        for (id, e) in &pr.elements {
            if gone.contains(id) {
                continue;
            }
            let cat = cat_of(e);
            let mut goes = is_gone(gstr(e, "host")) || is_gone(gstr(e, "view")) || is_gone(gstr(e, "parent"));
            if cat == "viewport" && is_gone(gstr(e, "sheet")) {
                goes = true;
            }
            if matches!(cat, "planview" | "dimension") && is_gone(gstr(e, "level")) {
                goes = true;
            }
            if cat == "dimension" {
                if let Some(refs) = e.get("refs").and_then(|r| r.as_arr()) {
                    let lost = refs.iter().filter(|r| is_gone(gstr(r, "id"))).count();
                    if lost > 0 && refs.len() - lost < 2 {
                        goes = true;
                    }
                }
            }
            if goes {
                more.push(*id);
            }
        }
        if more.is_empty() {
            break;
        }
        gone.extend(more);
    }
    let guids: BTreeSet<String> = gone.iter().filter_map(|id| pr.guid_of(*id)).collect();
    for id in &gone {
        pr.elements.remove(id);
    }
    for e in pr.elements.values_mut() {
        let_go(e, &guids);
    }
    super::insert::drop_unplaced_cads(pr);
    gone.into_iter().collect()
}

/// What an element that stays holds of the elements that went, let go of.
fn let_go(e: &mut Value, guids: &BTreeSet<String>) {
    let is_gone = |v: Option<&Value>| v.and_then(|x| x.as_str()).map(|g| guids.contains(g)).unwrap_or(false);
    if cat_of(e) == "dimension" {
        if let Some(Value::Arr(refs)) = e.get_mut("refs") {
            refs.retain(|r| !r.get("id").and_then(|x| x.as_str()).map(|g| guids.contains(g)).unwrap_or(false));
        }
    }
    for k in ["attach_top", "attach_base", "join"] {
        if is_gone(e.get(k)) {
            e.remove(k);
        }
    }
    // what a mass made forgets it
    let mut empty = false;
    if let Some(Value::Obj(pm)) = e.get_mut("params") {
        pm.items.retain(|(k, v)| {
            !(matches!(k.as_str(), "Mass Floor" | "Mass Face")
                && v.get("mass").and_then(|m| m.as_str()).map(|g| guids.contains(g)).unwrap_or(false))
        });
        empty = pm.is_empty();
    }
    if empty {
        e.remove("params");
    }
    // a view's graphics forget what went
    let mut drop_graphics = false;
    if let Some(g) = e.get_mut("graphics") {
        let mut drop_elements = false;
        if let Some(Value::Obj(m)) = g.get_mut("elements") {
            let before = m.len();
            m.items.retain(|(k, _)| !guids.contains(k));
            drop_elements = m.is_empty() && before > 0;
        }
        if drop_elements {
            g.remove("elements");
        }
        let mut drop_linework = false;
        if let Some(Value::Arr(a)) = g.get_mut("linework") {
            let before = a.len();
            a.retain(|l| !l.get("element").and_then(|x| x.as_str()).map(|x| guids.contains(x)).unwrap_or(false));
            drop_linework = a.is_empty() && before > 0;
        }
        if drop_linework {
            g.remove("linework");
        }
        drop_graphics = g.as_obj().map(|m| m.is_empty()).unwrap_or(false);
    }
    if drop_graphics {
        e.remove("graphics");
    }
}

/// The model's rule on levels: what stands on a level, or rises to one, names one there is.
pub fn check_levels(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        for k in ["level", "top_level"] {
            if let Some(g) = e.get(k).and_then(|x| x.as_str()) {
                let ok = pr.find_guid(g).map(|l| pr.category(l) == Some("level")).unwrap_or(false);
                if !ok && pr.find_guid(g).is_none() {
                    return Err(format!("{} {}: level {} doesn't exist", cat_of(e), id, g));
                }
            }
        }
    }
    Ok(())
}
