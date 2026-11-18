//! Arcs: corner with arcs of detail lines, and curved walls split in two.

use super::common::*;
use super::ops_geom::*;
use crate::json::Value;
use crate::project::Project;

const TAU: f64 = std::f64::consts::PI * 2.0;

/// Where on an arc the point nearest `p` is: how far round from its start (radians, along its
/// sweep, 0 to |sweep|), and how far `p` is from it. Past its ends, its nearer end.
pub fn arc_nearest(arc: &Arc, p: P) -> (f64, f64) {
    let sw = arc.sweep.abs();
    let ang = (p[1] - arc.c[1]).atan2(p[0] - arc.c[0]);
    let mut da = (ang - arc.a0) * arc.sweep.signum();
    da = da.rem_euclid(TAU);
    if da <= sw {
        let d = (dist(p, arc.c) - arc.r).abs();
        return (da, d);
    }
    // past an end: the nearer one
    let to_end = da - sw;
    let to_start = TAU - da;
    let (u, q) = if to_start <= to_end { (0.0, arc.at(arc.a0)) } else { (sw, arc.at(arc.a0 + arc.sweep)) };
    (u, dist(p, q))
}

const NO_MEET: &str =
    "corner: the lines don't meet, run on as far as need be: they're parallel, or an arc's circle misses the other";

/// A line or an arc of a detail line, as corner reads it.
enum Seg {
    Line(P, P),
    Arc(P, P, f64, Arc),
}

impl Seg {
    fn of(l: (P, P, f64)) -> Seg {
        if l.2 == 0.0 {
            Seg::Line(l.0, l.1)
        } else {
            Seg::Arc(l.0, l.1, l.2, arc_of(l.0, l.1, l.2))
        }
    }
    /// The point of it a keep point stands for without one: its middle.
    fn middle(&self) -> P {
        match self {
            Seg::Line(a, b) => mul(add(*a, *b), 0.5),
            Seg::Arc(_, _, _, arc) => arc.at(arc.a0 + arc.sweep / 2.0),
        }
    }
}

/// Where a line crosses a circle: none, or two points (one, twice, where it touches).
fn line_circle(a: P, b: P, c: P, r: f64) -> Vec<P> {
    let u = dir(sub(b, a));
    let t = dot(sub(c, a), u);
    let f = add(a, mul(u, t));
    let d2 = dot(sub(f, c), sub(f, c));
    let h2 = r * r - d2;
    if !(h2 >= 0.0) {
        return Vec::new();
    }
    let h = h2.sqrt();
    vec![sub(f, mul(u, h)), add(f, mul(u, h))]
}

/// Where two circles cross: none, or two points.
fn circle_circle(c1: P, r1: f64, c2: P, r2: f64) -> Vec<P> {
    let d = dist(c1, c2);
    if !(d > 0.0) || d > r1 + r2 || d < (r1 - r2).abs() {
        return Vec::new();
    }
    let a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
    let h = (r1 * r1 - a * a).max(0.0).sqrt();
    let u = dir(sub(c2, c1));
    let m = add(c1, mul(u, a));
    let n = [-u[1], u[0]];
    vec![add(m, mul(n, h)), sub(m, mul(n, h))]
}

/// How far round an arc from its start a point's direction from the centre is, in its sweep's
/// sense, radians: within (half the sweep - pi, half the sweep + pi].
fn arc_param_mid(arc: &Arc, p: P) -> f64 {
    let ang = (p[1] - arc.c[1]).atan2(p[0] - arc.c[0]);
    let d = (ang - arc.a0) * arc.sweep.signum();
    let m = arc.sweep.abs() / 2.0;
    ((d - m + std::f64::consts::PI).rem_euclid(TAU) - std::f64::consts::PI) + m
}

/// The same from 0 up to a full turn.
fn arc_param(arc: &Arc, p: P) -> f64 {
    let ang = (p[1] - arc.c[1]).atan2(p[0] - arc.c[0]);
    ((ang - arc.a0) * arc.sweep.signum()).rem_euclid(TAU)
}

/// What corner makes of one of the two at the corner `x` (`xr` rounded), keeping the part `k`
/// is on: its new start, end and arc.
fn trim_seg(s: &Seg, x: P, xr: P, k: P) -> (P, P, f64) {
    match s {
        Seg::Line(a, b) => {
            if dot(sub(k, xr), sub(*b, *a)) >= 0.0 {
                (xr, *b, 0.0)
            } else {
                (*a, xr, 0.0)
            }
        }
        Seg::Arc(a, b, deg, arc) => {
            let sw = arc.sweep.abs();
            let uk = arc_param(arc, k).min(sw);
            let ux = arc_param_mid(arc, x);
            let sg = arc.sweep.signum();
            let ax = (x[1] - arc.c[1]).atan2(x[0] - arc.c[0]);
            if uk >= ux {
                // the start goes to the corner
                let a1 = (b[1] - arc.c[1]).atan2(b[0] - arc.c[0]);
                let nsw = ((a1 - ax) * sg).rem_euclid(TAU);
                let _ = deg;
                (xr, *b, sg * nsw.to_degrees())
            } else {
                let nsw = ((ax - arc.a0) * sg).rem_euclid(TAU);
                (*a, xr, sg * nsw.to_degrees())
            }
        }
    }
}

pub fn corner_arcs(
    pr: &mut Project,
    ia: u64,
    ib: u64,
    la: (P, P, f64),
    lb: (P, P, f64),
    keep: Option<[P; 2]>,
) -> R<Value> {
    let sa = Seg::of(la);
    let sb = Seg::of(lb);
    let xs = match (&sa, &sb) {
        (Seg::Line(a, b), Seg::Arc(_, _, _, arc)) | (Seg::Arc(_, _, _, arc), Seg::Line(a, b)) => line_circle(*a, *b, arc.c, arc.r),
        (Seg::Arc(_, _, _, p), Seg::Arc(_, _, _, q)) => circle_circle(p.c, p.r, q.c, q.r),
        (Seg::Line(..), Seg::Line(..)) => Vec::new(),
    };
    if xs.is_empty() {
        return Err(NO_MEET.into());
    }
    let ka = keep.map(|k| k[0]).unwrap_or_else(|| sa.middle());
    let kb = keep.map(|k| k[1]).unwrap_or_else(|| sb.middle());
    // the crossing nearest the two keep points together
    let score = |x: P| dot(sub(ka, x), sub(ka, x)) + dot(sub(kb, x), sub(kb, x));
    let mut x = xs[0];
    for q in &xs[1..] {
        if score(*q) < score(x) {
            x = *q;
        }
    }
    if !(x[0].abs() <= 1e9 && x[1].abs() <= 1e9) {
        return Err(NO_MEET.into());
    }
    let xr = r3p(x);
    let na = trim_seg(&sa, x, xr, ka);
    let nb = trim_seg(&sb, x, xr, kb);
    for n in [&na, &nb] {
        if n.0 == n.1 {
            return Err(NO_MEET.into());
        }
    }
    for (id, old, new) in [(ia, la, na), (ib, lb, nb)] {
        let e = pr.el_mut(id).unwrap();
        if new.0 != old.0 {
            set_pt(e, "start", new.0);
        }
        if new.1 != old.1 {
            set_pt(e, "end", new.1);
        }
        if old.2 != 0.0 && (new.0 != old.0 || new.1 != old.1) {
            e.set("arc", Value::f(new.2));
        }
    }
    Ok(crate::jobj! {"ids" => vec![Value::u(ia), Value::u(ib)]})
}

/// A curved wall split at `at`: two arcs on its circle, its doors and windows with their part.
pub fn split_arc_wall(pr: &mut Project, id: u64, at: P) -> R<Value> {
    let e = pr.el(id).unwrap().clone();
    let (a, b, deg) = wall_line(&e);
    let arc = arc_of(a, b, deg);
    let tol = wall_thickness(pr, &e) / 2.0 + 100.0;
    let (u, _) = arc_nearest(&arc, at);
    // how far `at` is from its centre line, an arc round the same centre
    let centre_line = Arc { r: arc.r - arc.sweep.signum() * centre_offset(pr, &e), ..arc };
    let (_, d) = arc_nearest(&centre_line, at);
    if d > tol {
        return Err(format!("split: {} isn't on wall {}", pt_text(at), id));
    }
    let s = u * arc.r;
    let len = arc.len();
    if !(s > 1.0 && len - s > 1.0) {
        return Err("split: split between the wall's ends".into());
    }
    let ops = openings(pr, id);
    for oid in &ops {
        let o = pr.el(*oid).unwrap();
        let w = opening_width(pr, o);
        if (offset_of(o) - s).abs() < w / 2.0 - 1.0 {
            return Err(format!("split: {} {} is in the way; split elsewhere", cat_of(o), oid));
        }
    }
    let q = r3p(arc.at(arc.a0 + arc.sweep.signum() * u));
    let first = u.to_degrees() * arc.sweep.signum();
    let second = deg - first;
    let nid = pr.alloc_id();
    let g = crate::rand::guid();
    let mut ne = e.clone();
    super::fillet::drop_mass_face(&mut ne);
    ne.set("guid", Value::s(&g));
    set_pt(&mut ne, "start", q);
    ne.set("arc", Value::f(super::fillet::r9(second)));
    {
        let w = pr.el_mut(id).unwrap();
        super::fillet::drop_mass_face(w);
        set_pt(w, "end", q);
        w.set("arc", Value::f(super::fillet::r9(first)));
    }
    for oid in ops {
        let o = pr.el_mut(oid).unwrap();
        let off = offset_of(o);
        if off > s {
            o.set("host", Value::s(&g));
            o.set("offset", Value::f(off - s));
        }
    }
    pr.elements.insert(nid, ne);
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}
