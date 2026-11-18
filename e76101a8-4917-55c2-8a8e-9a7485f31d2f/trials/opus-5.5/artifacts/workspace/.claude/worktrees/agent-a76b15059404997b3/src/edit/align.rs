//! Align: an element's picked line onto a reference, and the padlock that keeps it there.
//!
//! The picked line turns about its middle by the smaller angle that lays it along the reference,
//! then moves square onto it: one transform, rounded to 0.001 mm as a turn is, with the walls
//! joined to what moves following as they do on a move. The padlock is a dimension of no length
//! (`alignment`), locked, between the reference's line and the aligned one.

use super::common::*;
use super::transform::{add, cross, dot, length, normalize, sub, transform_in_place, Xf, P};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

const CMD: &str = "align";

fn two_points(p: &Value, key: &str) -> R<[P; 2]> {
    let a = match crate::commands::params::get(p, key) {
        Some(Value::Arr(a)) => a.clone(),
        _ => return Err(format!("{}: `{}` [[x, y], …] is required", CMD, key)),
    };
    let mut pts = Vec::new();
    for v in &a {
        match crate::commands::params::point_of(v) {
            Some(q) => pts.push(q),
            None => return Err(format!("{}: `{}`: {} is not a point [x, y] in mm", CMD, key, v.to_compact())),
        }
    }
    if pts.len() != 2 {
        return Err(format!("{}: `{}` must contain two points", CMD, key));
    }
    Ok([pts[0], pts[1]])
}

/// What can't be aligned: what has no straight line in plan to pick.
fn alignable(e: &Value) -> bool {
    match cat_of(e) {
        "level" | "sheet" | "planview" | "schedule" | "viewport" | "tag" | "dimension" | "dimension3d" | "view3d"
        | "room" | "spot" | "rebar" => false,
        "line" => {
            let curved = |k: &str| e.get(k).map(|x| !x.is_null()).unwrap_or(false);
            let arc = e.get("arc").and_then(|x| x.as_f64()).map(|a| a != 0.0).unwrap_or(false);
            !(arc || curved("through") || curved("centre") || curved("control") || curved("fit"))
        }
        _ => true,
    }
}

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let p = &super::ops_geom::lib_names(&s.project, p);
    let id = match p.get("id") {
        None | Some(Value::Null) => return Err(format!("{}: `id` is required", CMD)),
        Some(v) => element_param(&s.project, CMD, "id", v)?,
    };
    let reference = two_points(p, "reference")?;
    let line = two_points(p, "line")?;
    if length(sub(reference[1], reference[0])) <= 1.0 || length(sub(line[1], line[0])) <= 1.0 {
        return Err(format!("{}: a reference or target line has no length", CMD));
    }
    let lock = crate::commands::params::opt_bool(p, CMD, "lock")?.unwrap_or(false);
    let pr = &mut s.project;
    let cat = pr.category(id).unwrap_or("").to_string();
    if !alignable(pr.el(id).unwrap()) {
        return Err(format!("{}: element {} has no straight alignment line in plan", CMD, id));
    }
    if cat == "railing" {
        if let Some(h) = pr.el(id).and_then(|e| e.get("host")).and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g)) {
            let _ = h;
            return Err(format!("{}: railing {} goes only with its stair or ramp; select that too", CMD, id));
        }
    }
    // the smaller turn that lays the line along the reference
    let lu = normalize(sub(line[1], line[0]));
    let ru = normalize(sub(reference[1], reference[0]));
    let raw = cross(lu, ru).atan2(dot(lu, ru)).to_degrees();
    let mut angle = (raw + 90.0).rem_euclid(180.0) - 90.0;
    if angle == 0.0 {
        angle = 0.0;
    }
    if matches!(cat.as_str(), "door" | "window") {
        // only along its wall: a line across the wall (a jamb's) onto one parallel to it
        let wall = pr.el(id).and_then(|e| e.get("host")).and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g));
        let across = wall
            .and_then(|w| pr.el(w))
            .map(|w| {
                let l = super::transform::wall_line(w);
                let wu = normalize(sub(l.b, l.a));
                dot(wu, lu).abs() < 1e-9
            })
            .unwrap_or(false);
        if angle != 0.0 || !across {
            return Err(format!(
                "{}: a door or window can only slide along its host wall; align its jambs, or align the wall",
                CMD
            ));
        }
    }
    let m = [(line[0][0] + line[1][0]) / 2.0, (line[0][1] + line[1][1]) / 2.0];
    // square onto the reference: along its normal by how far off it the middle is
    let n = [-ru[1], ru[0]];
    let d = dot(sub(reference[0], m), n);
    let by = [n[0] * d, n[1] * d];
    let xf = Xf::align(m, angle, by);
    // the lock's refs, found before the elements move (the aligned one) and after (the reference)
    let own_face = if lock {
        match face_along(pr, id, line) {
            Some(f) => Some(f),
            None => return Err(format!("{}: element {} has no line along the one aligned to lock", CMD, id)),
        }
    } else {
        None
    };
    transform_in_place(pr, &[id], &xf);
    let new_line = [xf.pt(line[0]), xf.pt(line[1])];
    let mut lock_id = Value::Null;
    if let Some(own) = own_face {
        let to = match p.get("to") {
            None | Some(Value::Null) => None,
            Some(v) => Some(element_param(pr, CMD, "to", v)?),
        };
        let (rid, rface) = match to {
            Some(t) => match face_along(pr, t, reference) {
                Some(f) => (t, f),
                None => return Err(format!("{}: element {} has no line along the reference to lock to", CMD, t)),
            },
            None => {
                let ids: Vec<u64> = pr.elements.keys().copied().filter(|x| *x != id).collect();
                let mut found = None;
                for e in ids {
                    if let Some(f) = face_along(pr, e, reference) {
                        found = Some((e, f));
                        break;
                    }
                }
                match found {
                    Some(x) => x,
                    None => {
                        return Err(format!(
                            "{}: nothing has a line along the reference to lock to: a wall's face or centre, a grid…",
                            CMD
                        ))
                    }
                }
            }
        };
        let nid = make_lock(pr, id, &own, rid, &rface, new_line);
        lock_id = Value::u(nid);
    }
    Ok(jobj! {
        "aligned" => id,
        "angle" => angle,
        "by" => Value::Arr(vec![Value::f(by[0]), Value::f(by[1])]),
        "line" => Value::Arr(vec![super::transform::pv(new_line[0]), super::transform::pv(new_line[1])]),
        "lock" => lock_id,
    })
}

/// The lines of an element a dimension can measure to: (face, a, b).
fn lines_of(pr: &Project, id: u64) -> Vec<(String, P, P)> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let mut out = Vec::new();
    match cat_of(e) {
        "wall" => {
            let l = super::transform::wall_line(e);
            if l.arc != 0.0 {
                return out;
            }
            let d = sub(l.b, l.a);
            if length(d) == 0.0 {
                return out;
            }
            let u = normalize(d);
            let n = [-u[1], u[0]];
            let off = super::ops_geom::centre_offset(pr, e);
            let half = super::ops_geom::wall_thickness(pr, e) / 2.0;
            let c0 = add(l.a, super::transform::mul(n, off));
            let c1 = add(l.b, super::transform::mul(n, off));
            out.push(("centre".to_string(), c0, c1));
            out.push(("left".to_string(), add(c0, super::transform::mul(n, half)), add(c1, super::transform::mul(n, half))));
            out.push(("right".to_string(), sub(c0, super::transform::mul(n, half)), sub(c1, super::transform::mul(n, half))));
            // the ends: out to the far face of a wall joined there, or back to the near face of
            // the one ended on
            let sa = sub(l.a, super::transform::mul(u, end_reach(pr, id, l.a, u)));
            let sb = add(l.b, super::transform::mul(u, end_reach(pr, id, l.b, [-u[0], -u[1]])));
            out.push(("start".to_string(), sa, add(sa, n)));
            out.push(("end".to_string(), sb, add(sb, n)));
        }
        "grid" | "roomseparator" => {
            if let (Some(a), Some(b)) = (super::transform::get_pt(e, "start"), super::transform::get_pt(e, "end")) {
                out.push(("centre".to_string(), a, b));
            }
        }
        "line" => {
            let straight = e.get("arc").map(|x| x.is_null() || x.as_f64() == Some(0.0)).unwrap_or(true)
                && e.get("through").is_none();
            if let (true, Some(a), Some(b)) = (straight, super::transform::get_pt(e, "start"), super::transform::get_pt(e, "end")) {
                out.push(("centre".to_string(), a, b));
            }
        }
        _ => {}
    }
    out
}

/// How far past its end point (`p`, the wall running on along `u` from it) a wall's outline
/// reaches: a wall joined there at its end takes it out to that wall's far face; one ended on
/// takes it back to its near face.
fn end_reach(pr: &Project, id: u64, p: P, u: P) -> f64 {
    let level = pr.el(id).and_then(|e| e.get("level")).cloned();
    for (oid, e) in &pr.elements {
        if *oid == id || cat_of(e) != "wall" || e.get("level").cloned() != level {
            continue;
        }
        let l = super::transform::wall_line(e);
        if l.arc != 0.0 {
            continue;
        }
        let d = sub(l.b, l.a);
        if length(d) == 0.0 {
            continue;
        }
        let v = normalize(d);
        let s = cross(u, v).abs();
        if s < 1e-9 {
            continue;
        }
        let half = super::ops_geom::wall_thickness(pr, e) / 2.0;
        let at_end = length(sub(l.a, p)) <= 1.0 || length(sub(l.b, p)) <= 1.0;
        let on = {
            let t = dot(sub(p, l.a), v);
            let foot = add(l.a, super::transform::mul(v, t));
            t > 0.0 && t < length(d) && length(sub(p, foot)) <= 1.0
        };
        if at_end {
            return half / s;
        }
        if on {
            return -half / s;
        }
    }
    0.0
}

/// The face of an element along a line (on it, within a millimetre).
fn face_along(pr: &Project, id: u64, line: [P; 2]) -> Option<String> {
    let lu = normalize(sub(line[1], line[0]));
    for (face, a, b) in lines_of(pr, id) {
        let d = sub(b, a);
        if length(d) == 0.0 {
            continue;
        }
        let u = normalize(d);
        if cross(u, lu).abs() > 1e-6 {
            continue;
        }
        let off = cross(lu, sub(a, line[0])).abs();
        if off <= 1.0 {
            return Some(face);
        }
    }
    None
}

fn make_lock(pr: &mut Project, id: u64, own: &str, rid: u64, rface: &str, line: [P; 2]) -> u64 {
    let level = pr
        .el(id)
        .and_then(|e| e.get("level").or_else(|| e.get("view")))
        .cloned()
        .or_else(|| crate::model::default_level(pr).and_then(|l| pr.guid_of(l)).map(Value::Str))
        .unwrap_or(Value::Null);
    let dim_type = pr.lib_guid("dimension-type", "Diagonal - 2.5mm Arial").or_else(|| {
        pr.library
            .values()
            .find(|x| x.get("kind").and_then(|k| k.as_str()) == Some("dimension-type"))
            .and_then(|x| x.get("guid"))
            .and_then(|g| g.as_str())
            .map(|s| s.to_string())
    });
    let dim_type = dim_type.or_else(|| dimension_type_guid(pr)).unwrap_or_default();
    let at = [(line[0][0] + line[1][0]) / 2.0, (line[0][1] + line[1][1]) / 2.0];
    let e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "dimension",
        "level" => level,
        "kind" => "aligned",
        "refs" => Value::Arr(vec![
            jobj!{"id" => pr.guid_of(rid).unwrap_or_default(), "face" => rface},
            jobj!{"id" => pr.guid_of(id).unwrap_or_default(), "face" => own},
        ]),
        "at" => super::transform::pv(at),
        "type" => dim_type,
        "locked" => Value::Arr(vec![jobj!{"segment" => 0u64, "length" => 0.0}]),
        "alignment" => true,
    };
    let nid = pr.alloc_id();
    pr.elements.insert(nid, e);
    nid
}

/// The GUID of the dimension type aligned dimensions start in.
fn dimension_type_guid(pr: &Project) -> Option<String> {
    for (_, e) in &pr.library {
        let kind = e.get("kind").and_then(|k| k.as_str()).unwrap_or("");
        if kind.contains("dimension") {
            return e.get("guid").and_then(|g| g.as_str()).map(|s| s.to_string());
        }
    }
    None
}
