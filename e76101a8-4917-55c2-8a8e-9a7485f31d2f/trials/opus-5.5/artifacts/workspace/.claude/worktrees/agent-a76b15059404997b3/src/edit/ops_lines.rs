//! Corner, split and fillet on detail lines: their shapes, as the original reads and writes them.

use super::common::*;
use super::ops_geom::*;
use crate::json::Value;
use crate::session::Session;

/// The fields of a detail line, in the order the original writes them.
pub const LINE_ORDER: &[&str] = &[
    "guid",
    "category",
    "view",
    "style",
    "insulation",
    "centre_mark",
    "cloud",
    "revision",
    "start",
    "end",
    "through",
    "arc",
    "points",
    "arcs",
    "closed",
    "centre",
    "radius",
    "radii",
    "angle",
    "span",
    "control",
    "knots",
    "fit",
    "start_tangent",
    "end_tangent",
];

/// The fields that hold a detail line's shape.
pub const SHAPE_FIELDS: &[&str] = &[
    "start",
    "end",
    "through",
    "arc",
    "points",
    "arcs",
    "closed",
    "centre",
    "radius",
    "radii",
    "angle",
    "span",
    "control",
    "knots",
    "fit",
    "start_tangent",
    "end_tangent",
];

/// What shape a detail line is, by the fields it has.
pub fn kind(e: &Value) -> &'static str {
    let has = |k: &str| e.get(k).map(|v| !v.is_null()).unwrap_or(false);
    if has("points") {
        "polyline"
    } else if has("centre") && has("radius") {
        "circle"
    } else if has("centre") && has("radii") {
        if has("span") {
            "partial ellipse"
        } else {
            "ellipse"
        }
    } else if has("control") {
        "spline"
    } else if has("fit") {
        "fitted spline"
    } else if has("arc") && e.get("arc").and_then(|x| x.as_f64()).unwrap_or(0.0) != 0.0 {
        "arc"
    } else {
        "line"
    }
}

/// Replaces a detail line's shape by the fields given (each in its place).
pub fn set_shape(e: &mut Value, fields: Vec<(&str, Value)>) {
    if let Value::Obj(m) = e {
        m.items.retain(|(k, _)| !SHAPE_FIELDS.contains(&k.as_str()));
    }
    for (k, v) in fields {
        set_ordered(e, LINE_ORDER, k, v);
    }
}

fn view_of(e: &Value) -> Option<&Value> {
    e.get("view")
}

/// A straight line or an arc of a detail line: its ends and its turn in degrees.
fn line_or_arc(e: &Value) -> Option<(P, P, f64)> {
    match kind(e) {
        "line" | "arc" => {
            let a = pt_of(e.get("start"));
            let b = pt_of(e.get("end"));
            let arc = e.get("arc").and_then(|x| x.as_f64()).unwrap_or(0.0);
            Some((a, b, arc))
        }
        _ => None,
    }
}

const NO_MEET: &str =
    "corner: the lines don't meet, run on as far as need be: they're parallel, or an arc's circle misses the other";

// ---------------------------------------------------------------- corner

/// A straight line's ends once trimmed or extended to `c`, keeping the part `k` is on (a point
/// exactly at the corner keeps the part toward the end).
fn trim_line(a: P, b: P, c: P, k: P) -> (P, P) {
    let d = sub(b, a);
    if dot(sub(k, c), d) >= 0.0 {
        (c, b)
    } else {
        (a, c)
    }
}

pub fn corner_lines(s: &mut Session, p: &Value, ia: u64, ib: u64) -> R<Value> {
    let pr = &mut s.project;
    let ea = pr.el(ia).unwrap().clone();
    let eb = pr.el(ib).unwrap().clone();
    if view_of(&ea) != view_of(&eb) {
        return Err(format!("corner: detail lines {} and {} are in different views; trim lines of one view", ia, ib));
    }
    let keep = super::corner::keep_param(p, "line")?;
    let (Some(la), Some(lb)) = (line_or_arc(&ea), line_or_arc(&eb)) else {
        return Err(NO_MEET.into());
    };
    if la.2 != 0.0 || lb.2 != 0.0 {
        return super::ops_arcs::corner_arcs(pr, ia, ib, la, lb, keep);
    }
    let Some(c) = line_cross(la.0, la.1, lb.0, lb.1) else {
        return Err(NO_MEET.into());
    };
    if !(c[0].abs() <= 1e9 && c[1].abs() <= 1e9) {
        return Err(NO_MEET.into());
    }
    let c = r3p(c);
    let ka = keep.map(|k| k[0]).unwrap_or(mul(add(la.0, la.1), 0.5));
    let kb = keep.map(|k| k[1]).unwrap_or(mul(add(lb.0, lb.1), 0.5));
    let na = trim_line(la.0, la.1, c, ka);
    let nb = trim_line(lb.0, lb.1, c, kb);
    if na.0 == na.1 || nb.0 == nb.1 {
        return Err(NO_MEET.into());
    }
    for (id, old, new) in [(ia, la, na), (ib, lb, nb)] {
        let e = pr.el_mut(id).unwrap();
        if new.0 != old.0 {
            set_pt(e, "start", new.0);
        }
        if new.1 != old.1 {
            set_pt(e, "end", new.1);
        }
    }
    Ok(crate::jobj! {"ids" => vec![Value::u(ia), Value::u(ib)]})
}

// ---------------------------------------------------------------- split

/// Rounds to hundredths, as the original's messages give a distance.
fn r2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

pub fn not_on(at: P, id: u64, d: f64) -> String {
    format!("split: {} isn't on detail line {}: it passes {} mm from it", pt_text(at), id, num(r2(d)))
}

pub fn split_line(s: &mut Session, id: u64, at: P) -> R<Value> {
    let pr = &mut s.project;
    let e = pr.el(id).unwrap().clone();
    match kind(&e) {
        "line" => {
            let a = pt_of(e.get("start"));
            let b = pt_of(e.get("end"));
            let d = sub(b, a);
            let l2 = dot(d, d);
            let u = if l2 > 0.0 { (dot(sub(at, a), d) / l2).clamp(0.0, 1.0) } else { 0.0 };
            let q = add(a, mul(d, u));
            let off = dist(at, q);
            if off > 100.0 {
                return Err(not_on(at, id, off));
            }
            if !(dist(a, q) > 1.0 && dist(q, b) > 1.0) {
                return Err("split: split between the line's ends".into());
            }
            let nid = pr.alloc_id();
            let mut ne = e.clone();
            ne.set("guid", Value::s(&crate::rand::guid()));
            set_pt(&mut ne, "start", q);
            set_pt(pr.el_mut(id).unwrap(), "end", q);
            pr.elements.insert(nid, ne);
            Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
        }
        _ => super::ops_curves::split_curve(pr, id, at),
    }
}

// ---------------------------------------------------------------- fillet

pub fn fillet_lines(s: &mut Session, p: &Value, ia: u64, ib: u64) -> R<Value> {
    let now_phase = s.now_phase.clone();
    let now_option = s.now_option.clone();
    let pr = &mut s.project;
    let ea = pr.el(ia).unwrap().clone();
    let eb = pr.el(ib).unwrap().clone();
    if view_of(&ea) != view_of(&eb) {
        return Err(format!("fillet: detail lines {} and {} are in different views", ia, ib));
    }
    let radius = super::fillet::radius_param(p)?;
    for (id, e) in [(ia, &ea), (ib, &eb)] {
        let k = kind(e);
        if k != "line" {
            return Err(format!("fillet: detail line {} is a {}: Fillet Arc rounds two straight lines", id, k));
        }
    }
    let la = (pt_of(ea.get("start")), pt_of(ea.get("end")));
    let lb = (pt_of(eb.get("start")), pt_of(eb.get("end")));
    let Some(f) = super::fillet::fillet_geometry(la, lb, radius) else {
        return Err("fillet: the lines meet at an angle and are long enough for the arc; these are parallel, or too short for it, or it doesn't fit".into());
    };
    let nid = pr.alloc_id();
    let mut ne = ea.clone();
    ne.set("guid", Value::s(&crate::rand::guid()));
    set_shape(&mut ne, vec![("start", ptv(f.t1)), ("end", ptv(f.t2)), ("arc", Value::f(f.arc))]);
    crate::styles::phasing::stamp_new(pr, now_phase.as_deref(), now_option.as_deref(), &mut ne);
    set_pt(pr.el_mut(ia).unwrap(), if f.a_moves_start { "start" } else { "end" }, f.t1);
    set_pt(pr.el_mut(ib).unwrap(), if f.b_moves_start { "start" } else { "end" }, f.t2);
    pr.elements.insert(nid, ne);
    Ok(crate::jobj! {"id" => nid, "ids" => vec![Value::u(ia), Value::u(ib)]})
}
