//! Fillet Arc: the corner of two straight detail lines or walls rounded by an arc.

use super::common::*;
use super::ops_geom::*;
use crate::json::Value;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let p = lib_names(&s.project, p);
    let ids = ids_param(&s.project, "fillet", &p)?;
    if ids.len() != 2 {
        return Err("fillet: `ids` is two detail lines".into());
    }
    let ca = s.project.category(ids[0]).unwrap_or("").to_string();
    let cb = s.project.category(ids[1]).unwrap_or("").to_string();
    if ca == "wall" && cb == "wall" {
        return walls(s, &p, ids[0], ids[1]);
    }
    for (id, c) in [(ids[0], &ca), (ids[1], &cb)] {
        if c != "line" {
            return Err(format!("fillet: {} is not a detail line", id));
        }
    }
    super::ops_lines::fillet_lines(s, &p, ids[0], ids[1])
}

/// `radius`: more than 1 mm.
pub fn radius_param(p: &Value) -> R<f64> {
    let r = match crate::commands::params::get(p, "radius") {
        None => return Err("fillet: `radius`, mm, is required".into()),
        Some(v) => crate::commands::params::mm_of(v)
            .ok_or_else(|| format!("fillet: `radius` must be a number in mm, got {}", v.to_compact()))?,
    };
    if !(r > 1.0) {
        return Err(format!("fillet: `radius` is more than 1 mm, not {}", num(r)));
    }
    Ok(r)
}

/// Where a fillet of two straight lines goes: the arc's ends on each (rounded), its turn in
/// degrees from the first to the second, and which end of each is cut back (or run on) to it.
pub struct Fillet {
    pub t1: P,
    pub t2: P,
    pub arc: f64,
    pub a_moves_start: bool,
    pub b_moves_start: bool,
}

/// The part of a line a fillet keeps: the side of the corner its middle is on (the end's side,
/// where the middle is at the corner). Returns the end kept and whether the start is the end cut.
fn kept_end(a: P, b: P, c: P) -> (P, bool) {
    let m = mul(add(a, b), 0.5);
    if dot(sub(m, c), sub(b, a)) >= 0.0 {
        (b, true)
    } else {
        (a, false)
    }
}

pub fn fillet_geometry(la: (P, P), lb: (P, P), r: f64) -> Option<Fillet> {
    let c = line_cross(la.0, la.1, lb.0, lb.1)?;
    let (fa, a_moves_start) = kept_end(la.0, la.1, c);
    let (fb, b_moves_start) = kept_end(lb.0, lb.1, c);
    let da = dist(fa, c);
    let db = dist(fb, c);
    if !(da > 0.0 && db > 0.0) {
        return None;
    }
    let u = dir(sub(fa, c));
    let v = dir(sub(fb, c));
    let cosv = dot(u, v).clamp(-1.0, 1.0);
    let theta = cosv.acos();
    if !(theta > 1e-9 && theta < std::f64::consts::PI - 1e-9) {
        return None;
    }
    let t = r / (theta / 2.0).tan();
    if !(da - t > 1.0 && db - t > 1.0) {
        return None;
    }
    let p1 = add(c, mul(u, t));
    let p2 = add(c, mul(v, t));
    // the arc turns twice the angle between its start's tangent (toward the corner) and its chord
    let tg = dir(sub(c, p1));
    let ch = sub(p2, p1);
    let arc = (2.0 * cross(tg, ch).atan2(dot(tg, ch))).to_degrees();
    Some(Fillet { t1: r3p(p1), t2: r3p(p2), arc, a_moves_start, b_moves_start })
}

/// Rounds to nine decimals, as a wall's `arc` is kept.
pub fn r9(x: f64) -> f64 {
    let y = (x * 1e9).round() / 1e9;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

fn walls(s: &mut Session, p: &Value, ia: u64, ib: u64) -> R<Value> {
    let now_phase = s.now_phase.clone();
    let now_option = s.now_option.clone();
    let radius = radius_param(p)?;
    let pr = &mut s.project;
    let la = wall_line(pr.el(ia).unwrap());
    let lb = wall_line(pr.el(ib).unwrap());
    const NO_FIT: &str =
        "fillet: the walls are straight, meet at an angle and are long enough for the arc; these aren't, or it doesn't fit";
    if la.2 != 0.0 || lb.2 != 0.0 {
        return Err(NO_FIT.into());
    }
    let Some(f) = fillet_geometry((la.0, la.1), (lb.0, lb.1), radius) else {
        return Err(NO_FIT.into());
    };
    let na = if f.a_moves_start { (f.t1, la.1, 0.0) } else { (la.0, f.t1, 0.0) };
    let nb = if f.b_moves_start { (f.t2, lb.1, 0.0) } else { (lb.0, f.t2, 0.0) };
    // the doors and windows of each stay where they stand, and must stay on what's left of it
    let mut moves: Vec<(u64, f64)> = Vec::new();
    for (wid, old, new) in [(ia, la, na), (ib, lb, nb)] {
        let len = dist(new.0, new.1);
        for oid in openings(pr, wid) {
            let o = pr.el(oid).unwrap();
            let off = offset_of(o);
            let no = r3(station(new, along(old, off)));
            let w = opening_width(pr, o);
            if no - w / 2.0 < -1.0 || no + w / 2.0 > len + 1.0 {
                return Err(format!(
                    "fillet: {} {} is in the part of wall {} the fillet cuts away; move it along the wall first",
                    cat_of(o),
                    oid,
                    wid
                ));
            }
            if no != off {
                moves.push((oid, no));
            }
        }
    }
    let nid = pr.alloc_id();
    let mut ne = pr.el(ia).unwrap().clone();
    ne.set("guid", Value::s(&crate::rand::guid()));
    set_pt(&mut ne, "start", f.t1);
    set_pt(&mut ne, "end", f.t2);
    set_ordered(&mut ne, WALL_ORDER, "arc", Value::f(r9(f.arc)));
    drop_mass_face(&mut ne);
    crate::styles::phasing::stamp_new(pr, now_phase.as_deref(), now_option.as_deref(), &mut ne);
    set_pt(pr.el_mut(ia).unwrap(), if f.a_moves_start { "start" } else { "end" }, f.t1);
    set_pt(pr.el_mut(ib).unwrap(), if f.b_moves_start { "start" } else { "end" }, f.t2);
    for (oid, no) in moves {
        pr.el_mut(oid).unwrap().set("offset", Value::f(no));
    }
    pr.elements.insert(nid, ne);
    Ok(crate::jobj! {"id" => nid, "ids" => vec![Value::u(ia), Value::u(ib)]})
}

/// What a mass made is ordinary in a copy: its `Mass Face` goes (and `params` with its last).
pub fn drop_mass_face(e: &mut Value) {
    crate::styles::phasing::remove_param(e, "Mass Face");
}
