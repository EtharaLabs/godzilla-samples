//! `elements`: each element as the project file holds it, with its id and what is worked out of
//! it (a wall's length, a room's area, a door's place…), each category by the module that knows it.

use super::common::{self, Ctx};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// An element as `elements` shows it: its fields as stored (what it points at by GUID), its
/// `id`, and its derived values. None for an id the project hasn't.
pub fn element_view(cx: &Ctx, id: u64) -> Option<Value> {
    let pr = cx.pr;
    let e = pr.el(id)?;
    let mut x = e.clone();
    x.set("id", Value::u(id));
    match common::category(e) {
        "wall" | "room" | "roomseparator" => super::walls::view(cx, id, &mut x),
        "floor" | "ceiling" | "roof" | "shaft" | "mass" => super::slabs::view(cx, id, &mut x),
        "door" | "window" | "component" | "column" | "structuralcolumn" | "footing" | "beam"
        | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
        | "groundconductor" | "cable" | "rebar" | "stair" | "ramp" | "railing" => super::parts::view(cx, id, &mut x),
        "pointcloud" => crate::cloud::element_view(pr, &mut x),
        _ => super::notes::view(cx, id, &mut x),
    }
    Some(x)
}

/// One element's view, for a caller without a context of its own.
pub fn view_of(pr: &Project, id: u64) -> Option<Value> {
    let cx = Ctx::new(pr);
    element_view(&cx, id)
}

/// A category as `elements` (and other readers) take one: in any case, its words run together or
/// apart (`structural columns`, `room_separator`), plural or not (`walls`, `masses`).
pub fn category_matches(query: &str, cat: &str) -> bool {
    let q: String = query.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_lowercase()).collect();
    if q.is_empty() {
        return false;
    }
    if q == cat {
        return true;
    }
    let plural = if cat.ends_with('s') { format!("{}es", cat) } else { format!("{}s", cat) };
    if q == plural {
        return true;
    }
    !cat.ends_with('s') && q.trim_end_matches('s') == cat
}

fn whole(p: &Value, key: &str) -> Result<Option<u64>, String> {
    match crate::commands::params::get(p, key) {
        None => Ok(None),
        Some(Value::Num(crate::json::Num::U(u))) => Ok(Some(*u)),
        Some(v) => Err(format!("elements: `{}` must be a whole number, got {}", key, v.to_compact())),
    }
}

/// `elements {category?, level?, limit?, offset?}`.
pub fn cmd_elements(s: &Session, p: &Value) -> Result<Value, String> {
    let pr = &s.project;
    let empty = Value::obj();
    let p = if matches!(p, Value::Obj(_)) { p } else { &empty };
    let cat = crate::commands::params::opt_text(p, "elements", "category")?;
    let level = match crate::commands::params::get(p, "level") {
        None => None,
        Some(v) => Some(crate::model::resolve_level(pr, "elements", "level", v)?),
    };
    let limit = whole(p, "limit")?;
    let offset = whole(p, "offset")?.unwrap_or(0);
    let level_guid = level.and_then(|l| pr.guid_of(l));
    let cx = Ctx::new(pr);
    let mut out = Vec::new();
    let mut count = 0u64;
    for (id, e) in &pr.elements {
        if let Some(want) = &cat {
            if !category_matches(want, common::category(e)) {
                continue;
            }
        }
        // what lies outside the page asked for is counted, not worked out (unless its level,
        // which may be derived, decides whether it counts)
        let wanted = |n: u64| n > offset && limit.map(|l| n - offset <= l).unwrap_or(true);
        if level_guid.is_none() {
            count += 1;
            if wanted(count) {
                if let Some(x) = element_view(&cx, *id) {
                    out.push(x);
                }
            }
            continue;
        }
        let x = match element_view(&cx, *id) {
            Some(x) => x,
            None => continue,
        };
        if let Some(g) = &level_guid {
            if common::text(&x, "level") != Some(g.as_str()) {
                continue;
            }
        }
        count += 1;
        if wanted(count) {
            out.push(x);
        }
    }
    let n = out.len();
    Ok(jobj! {"count" => count, "elements" => Value::Arr(out), "returned" => n})
}
