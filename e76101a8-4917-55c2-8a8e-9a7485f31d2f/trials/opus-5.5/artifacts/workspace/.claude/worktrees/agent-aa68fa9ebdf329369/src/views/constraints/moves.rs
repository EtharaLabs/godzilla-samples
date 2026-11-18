//! Moving what a dimension measures to, as `move` moves it: a wall's line moves, and the walls
//! joined to it keep their lines and stay joined (their shared end goes where the lines now
//! cross, an end on it slides onto it); doors and windows stay where they are along their walls
//! (those of the moved wall go with it, sliding along it); grids and detail lines move whole.

use super::super::common::*;
use super::super::dims::geom::{self as g, P};
use crate::json::Value;
use crate::project::Project;

/// Moves an element in plan by `v`, as `move` moves it.
pub fn move_by(pr: &mut Project, id: u64, v: P) {
    let c = cat_of(pr, id);
    match c.as_str() {
        "wall" => move_walls(pr, &[id], v),
        "door" | "window" => slide_opening(pr, id, v),
        "grid" => {
            if let Some(e) = pr.el_mut(id) {
                for k in ["start", "end"] {
                    if let Some(p) = pt_of(e, k) {
                        e.set(k, pt_value(g::add(p, v)));
                    }
                }
            }
        }
        "line" => {
            if let Some(e) = pr.el_mut(id) {
                move_line(e, v);
            }
        }
        _ => {
            if let Some(e) = pr.el_mut(id) {
                for k in ["at", "start", "end", "centre"] {
                    if let Some(p) = pt_of(e, k) {
                        e.set(k, pt_value(g::add(p, v)));
                    }
                }
            }
        }
    }
}

/// A detail line moved whole: its points, ends, centre.
fn move_line(e: &mut Value, v: P) {
    for k in ["start", "end", "centre", "through"] {
        if let Some(p) = pt_of(e, k) {
            e.set(k, pt_value(r3p(g::add(p, v))));
        }
    }
    for k in ["points", "control", "fit"] {
        if let Some(ps) = pts_of(e, k) {
            let moved: Vec<P> = ps.iter().map(|p| r3p(g::add(*p, v))).collect();
            e.set(k, pts_value(&moved));
        }
    }
}

/// A door or window slid along its wall by as much of `v` as runs along it.
fn slide_opening(pr: &mut Project, id: u64, v: P) {
    let Some(e) = pr.el(id) else { return };
    let Some(host) = ref_id(pr, e, "host") else { return };
    let Some(w) = g::wall_base(pr, host) else { return };
    let along = if w.straight() {
        g::dot(v, w.dir())
    } else {
        // along a curved wall, by the arc its point turns through
        g::dot(v, w.tangent(false))
    };
    let off = f_of(e, "offset").unwrap_or(0.0) + along;
    if let Some(e) = pr.el_mut(id) {
        e.set("offset", Value::f(off));
    }
}

/// Where a door or window stands: its point on its wall's location line.
fn opening_point(pr: &Project, id: u64) -> Option<(u64, P)> {
    let e = pr.el(id)?;
    let host = ref_id(pr, e, "host")?;
    let w = g::wall_base(pr, host)?;
    let off = f_of(e, "offset").unwrap_or(0.0);
    if w.straight() {
        let d = g::unit(g::sub(w.loc.end, w.loc.start));
        Some((host, g::add(w.loc.start, g::mul(d, off))))
    } else {
        None
    }
}

/// The line of a wall, through its location line's start along it.
fn line_of(pr: &Project, id: u64) -> Option<(P, P)> {
    let e = pr.el(id)?;
    let s = pt_of(e, "start")?;
    let t = pt_of(e, "end")?;
    Some((s, g::sub(t, s)))
}

/// Walls moved by `v`: each one's line moves; at an end joined to another wall the shared end goes
/// where the two lines now cross (the other keeping its line); an end on another wall slides along
/// it; a wall ending on a moved one follows it; their doors and windows go with them.
pub fn move_walls(pr: &mut Project, ids: &[u64], v: P) {
    let before = pr.clone();
    let bases = g::wall_bases(&before);
    let moved = |id: u64| ids.contains(&id);
    // where each door and window stands now, and where it goes
    let mut openings: Vec<(u64, u64, P)> = Vec::new();
    for c in ["door", "window"] {
        for oid in before.ids_of(c) {
            if let Some((host, p)) = opening_point(&before, oid) {
                let p = if moved(host) { g::add(p, v) } else { p };
                openings.push((oid, host, p));
            }
        }
    }
    // the new ends of every wall touched
    let mut ends: std::collections::BTreeMap<u64, (P, P)> = std::collections::BTreeMap::new();
    for w in &bases {
        if moved(w.id) {
            ends.insert(w.id, (g::add(w.loc.start, v), g::add(w.loc.end, v)));
        }
    }
    // the moved walls' ends, re-met with what they're joined to
    for w in bases.iter().filter(|w| moved(w.id)) {
        for at_end in [false, true] {
            let p = if at_end { w.loc.end } else { w.loc.start };
            let (ns, ne) = ends[&w.id];
            let dir = g::sub(ne, ns);
            let here = if at_end { ne } else { ns };
            // walls sharing this end
            let mut joined = false;
            for o in bases.iter().filter(|o| o.id != w.id) {
                for oe in [false, true] {
                    let q = if oe { o.loc.end } else { o.loc.start };
                    if g::dist(p, q) > g::JOIN_GAP || !overlap(w, o) {
                        continue;
                    }
                    joined = true;
                    if moved(o.id) {
                        continue;
                    }
                    let (os, od) = line_of(&before, o.id).unwrap_or((o.loc.start, g::sub(o.loc.end, o.loc.start)));
                    let x = if w.straight() && o.straight() { g::line_meet(here, dir, os, od) } else { None };
                    let x = x.map(r3p).unwrap_or(g::add(q, v));
                    set_end(&mut ends, w.id, at_end, x, &bases);
                    set_end(&mut ends, o.id, oe, x, &bases);
                }
            }
            if joined {
                continue;
            }
            // an end on another wall slides along it
            for o in bases.iter().filter(|o| o.id != w.id && !moved(o.id) && o.straight() && overlap(w, o)) {
                if on_body(o, p, w, at_end) {
                    let (os, od) = line_of(&before, o.id).unwrap_or((o.loc.start, g::sub(o.loc.end, o.loc.start)));
                    if let Some(x) = g::line_meet(here, dir, os, od) {
                        set_end(&mut ends, w.id, at_end, r3p(x), &bases);
                    }
                    break;
                }
            }
        }
    }
    // walls ending on a moved wall follow it
    for o in bases.iter().filter(|o| !moved(o.id)) {
        for oe in [false, true] {
            let q = if oe { o.loc.end } else { o.loc.start };
            let at_corner = bases.iter().any(|w| {
                w.id != o.id && overlap(w, o) && (g::dist(q, w.loc.start) <= g::JOIN_GAP || g::dist(q, w.loc.end) <= g::JOIN_GAP)
            });
            if at_corner {
                continue;
            }
            for w in bases.iter().filter(|w| moved(w.id) && w.straight() && overlap(w, o)) {
                if on_body(w, q, o, oe) {
                    let (ns, ne) = ends[&w.id];
                    let (os, _) = line_of(&before, o.id).unwrap_or((o.loc.start, g::sub(o.loc.end, o.loc.start)));
                    let od = g::sub(o.loc.end, o.loc.start);
                    if let Some(x) = g::line_meet(os, od, ns, g::sub(ne, ns)) {
                        set_end(&mut ends, o.id, oe, r3p(x), &bases);
                    }
                    break;
                }
            }
        }
    }
    for (id, (s, e)) in &ends {
        if let Some(el) = pr.el_mut(*id) {
            el.set("start", pt_value(*s));
            el.set("end", pt_value(*e));
        }
    }
    // doors and windows where they stand, measured from their walls' new starts
    for (oid, host, p) in openings {
        let Some((s, e)) = ends.get(&host).copied() else { continue };
        let d = g::unit(g::sub(e, s));
        let off = g::dot(g::sub(p, s), d);
        if let Some(el) = pr.el_mut(oid) {
            el.set("offset", Value::f(off));
        }
    }
}

fn overlap(a: &g::WallBase, b: &g::WallBase) -> bool {
    a.base < b.top && b.base < a.top
}

/// Whether wall `w`'s end `p` stands on wall `o`'s body (as a wall ending on another does).
fn on_body(o: &g::WallBase, p: P, w: &g::WallBase, w_at_end: bool) -> bool {
    let (off, along) = o.offset_along(p);
    let at_mm = along * o.cl.length();
    if !(at_mm > g::JOIN_GAP && at_mm < o.cl.length() - g::JOIN_GAP) {
        return false;
    }
    let t = w.tangent(w_at_end);
    let u = if w_at_end { g::mul(t, -1.0) } else { t };
    let ot = o.dir();
    if g::cross(g::unit(u), ot).abs() < g::PARALLEL {
        return false;
    }
    let side = if g::dot(u, g::left_of(ot)) > 0.0 { 1.0 } else { -1.0 };
    let s = off * side;
    s >= -o.t / 2.0 && s <= o.t / 2.0 + g::T_SLACK
}

fn set_end(ends: &mut std::collections::BTreeMap<u64, (P, P)>, id: u64, at_end: bool, x: P, bases: &[g::WallBase]) {
    let cur = match ends.get(&id) {
        Some(c) => *c,
        None => {
            let b = bases.iter().find(|b| b.id == id).unwrap();
            (b.loc.start, b.loc.end)
        }
    };
    let new = if at_end { (cur.0, x) } else { (x, cur.1) };
    ends.insert(id, new);
}
