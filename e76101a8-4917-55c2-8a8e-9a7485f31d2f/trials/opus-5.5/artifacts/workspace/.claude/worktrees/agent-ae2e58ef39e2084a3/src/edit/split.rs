//! Split: a wall, or a detail line of any shape, in two.

use super::common::*;
use super::ops_geom::*;
use crate::json::Value;
use crate::session::Session;

/// The element `id` names, as split reads it: its id and how a message names it (the id, or the
/// GUID it was named by).
fn id_param(s: &Session, p: &Value) -> R<(Option<u64>, String)> {
    let pr = &s.project;
    let bad = |v: &Value| format!("split: `id` must be an element id or GUID, got {}", v.to_compact());
    match p.get("id") {
        None | Some(Value::Null) => Err("split: `id`, a wall or a detail line, is required".into()),
        Some(v @ Value::Num(n)) => {
            let id = num_id(n).ok_or_else(|| bad(v))?;
            Ok((pr.elements.contains_key(&id).then_some(id), id.to_string()))
        }
        Some(v @ Value::Str(t)) => {
            let t = t.trim();
            if let Ok(id) = t.parse::<u64>() {
                return Ok((pr.elements.contains_key(&id).then_some(id), id.to_string()));
            }
            if let Some(g) = strict_guid(t) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok((Some(id), g));
                }
            }
            Err(bad(v))
        }
        Some(v) => Err(bad(v)),
    }
}

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let p = lib_names(&s.project, p);
    let (id, shown) = id_param(s, &p)?;
    let cat = id.and_then(|i| s.project.category(i)).unwrap_or("").to_string();
    let id = match (id, cat.as_str()) {
        (Some(i), "wall") | (Some(i), "line") => i,
        _ => return Err(format!("split: {} is not a wall", shown)),
    };
    let at = crate::commands::params::req_point(&p, "split", "at")?;
    if cat == "line" {
        return super::ops_lines::split_line(s, id, at);
    }
    wall(s, id, at)
}

fn wall(s: &mut Session, id: u64, at: P) -> R<Value> {
    let pr = &mut s.project;
    let e = pr.el(id).unwrap().clone();
    let line = wall_line(&e);
    if line.2 != 0.0 {
        return super::ops_arcs::split_arc_wall(pr, id, at);
    }
    let (a, b, _) = line;
    // `at` is on it within 100 mm of its faces (of its centre line, half its thickness more)
    let tol = wall_thickness(pr, &e) / 2.0 + 100.0;
    let u = dir(sub(b, a));
    let left = mul([-u[1], u[0]], centre_offset(pr, &e));
    if seg_dist(at, add(a, left), add(b, left)) > tol {
        return Err(format!("split: {} isn't on wall {}", pt_text(at), id));
    }
    // where along it `at` is, to the thousandth of a millimetre, and the point there
    let len = dist(a, b);
    let t = r3(station(line, at));
    if !(t > 1.0 && len - t > 1.0) {
        return Err("split: split between the wall's ends".into());
    }
    let q = r3p(along(line, t));
    let ops = openings(pr, id);
    for oid in &ops {
        let o = pr.el(*oid).unwrap();
        let w = opening_width(pr, o);
        if (offset_of(o) - t).abs() < w / 2.0 - 1.0 {
            return Err(format!("split: {} {} is in the way; split elsewhere", cat_of(o), oid));
        }
    }
    let nid = pr.alloc_id();
    let g = crate::rand::guid();
    let mut ne = e.clone();
    super::fillet::drop_mass_face(&mut ne);
    ne.set("guid", Value::s(&g));
    set_pt(&mut ne, "start", q);
    {
        let w = pr.el_mut(id).unwrap();
        super::fillet::drop_mass_face(w);
        set_pt(w, "end", q);
    }
    // each door and window goes with its part, measured from its start
    for oid in ops {
        let o = pr.el_mut(oid).unwrap();
        let off = offset_of(o);
        if off > t {
            o.set("host", Value::s(&g));
            o.set("offset", Value::f(off - t));
        }
    }
    pr.elements.insert(nid, ne);
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}
