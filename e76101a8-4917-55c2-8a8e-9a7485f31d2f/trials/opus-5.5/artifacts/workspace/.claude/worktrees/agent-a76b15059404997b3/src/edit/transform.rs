//! Move, Copy, Rotate and Mirror: elements of every category, and the walls joined to them.
//!
//! The original works its geometry as glam's DVec2 does (a direction normalised by the reciprocal
//! of its length), its products summed with fused multiply-adds (`x1 * x2 + y1 * y2` is
//! `x1.mul_add(x2, y1 * y2)`); a turned or mirrored point is rounded to 0.001 mm, and an angle is the direction
//! between a point and one 1000 mm along it, both taken through the transform, rounded to 1e-9
//! degree. A moved wall's end joined to walls it isn't moved with (an end within 1 mm of theirs, or
//! on one of them) goes where its new line crosses the first of them (by id), and their ends go
//! with it; a wall ending on a moved one goes to where its line crosses the moved one's. Doors and
//! windows of moved walls go with them, and those of walls that stretch stay where they stand.

use super::common::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use std::collections::{BTreeMap, BTreeSet};

pub type P = [f64; 2];

// ---------------------------------------------------------------- vectors, as glam does them

pub fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
pub fn add(a: P, b: P) -> P {
    [a[0] + b[0], a[1] + b[1]]
}
pub fn mul(a: P, k: f64) -> P {
    [a[0] * k, a[1] * k]
}
/// `a + b * k`, fused as the original's arithmetic is.
pub fn add_mul(a: P, b: P, k: f64) -> P {
    [b[0].mul_add(k, a[0]), b[1].mul_add(k, a[1])]
}
pub fn dot(a: P, b: P) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
pub fn cross(a: P, b: P) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
/// A length, as the original's arithmetic works it: its squares summed by a fused multiply-add.
pub fn length(a: P) -> f64 {
    a[0].mul_add(a[0], a[1] * a[1]).sqrt()
}
pub fn normalize(a: P) -> P {
    mul(a, 1.0 / length(a))
}
pub fn dist(a: P, b: P) -> f64 {
    length(sub(a, b))
}

/// Rounds to 1e-9 (an angle in degrees, a unit vector's components).
pub fn r9(x: f64) -> f64 {
    let y = (x * 1e9).round() / 1e9;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

pub fn r3p(p: P) -> P {
    [r3(p[0]), r3(p[1])]
}

// ---------------------------------------------------------------- the transform

#[derive(Clone, Copy, Debug)]
pub enum Xf {
    Move(P),
    Rotate { c: P, cos: f64, sin: f64 },
    Mirror { a: P, d: P },
    /// Turned about `c`, then moved by `by` (Align), rounded once.
    Align { c: P, cos: f64, sin: f64, by: P },
}

impl Xf {
    pub fn rotate(c: P, deg: f64) -> Xf {
        let (sin, cos) = deg.to_radians().sin_cos();
        Xf::Rotate { c, cos, sin }
    }
    pub fn align(c: P, deg: f64, by: P) -> Xf {
        let (sin, cos) = deg.to_radians().sin_cos();
        Xf::Align { c, cos, sin, by }
    }
    pub fn mirror(a: P, b: P) -> Xf {
        Xf::Mirror { a, d: normalize(sub(b, a)) }
    }
    pub fn mirrors(&self) -> bool {
        matches!(self, Xf::Mirror { .. })
    }
    pub fn is_move(&self) -> bool {
        matches!(self, Xf::Move(_))
    }
    /// A point of the plan, where the transform takes it.
    pub fn pt(&self, p: P) -> P {
        match *self {
            Xf::Move(by) => add(p, by),
            Xf::Rotate { c, .. } => {
                let r = self.vec(sub(p, c));
                r3p(add(c, r))
            }
            Xf::Mirror { a, .. } => {
                let r = self.vec(sub(p, a));
                r3p(add(a, r))
            }
            Xf::Align { c, by, .. } => {
                let r = self.vec(sub(p, c));
                r3p(add(add(c, r), by))
            }
        }
    }
    /// A direction or a displacement, as the transform turns it (unrounded).
    pub fn vec(&self, v: P) -> P {
        match *self {
            Xf::Move(_) => v,
            Xf::Rotate { cos, sin, .. } | Xf::Align { cos, sin, .. } => {
                [v[0] * cos - v[1] * sin, v[1] * cos + v[0] * sin]
            }
            Xf::Mirror { d, .. } => {
                let k = dot(v, d) * 2.0;
                sub(mul(d, k), v)
            }
        }
    }
    /// An angle (degrees) of something at `p`, after the transform: a move keeps it.
    pub fn ang(&self, p: P, deg: f64) -> f64 {
        if self.is_move() {
            return deg;
        }
        let t = deg.to_radians();
        let q = add(p, mul([t.cos(), t.sin()], 1000.0));
        let a = self.pt(p);
        let b = self.pt(q);
        r9((b[1] - a[1]).atan2(b[0] - a[0]).to_degrees())
    }
}

// ---------------------------------------------------------------- reading values

pub fn get_pt(e: &Value, k: &str) -> Option<P> {
    let a = e.get(k)?.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn pv(p: P) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

fn num(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

/// Sets a field where the original's struct puts it (its place in `modify`'s schema).
pub fn set_ordered(e: &mut Value, k: &str, v: Value) {
    if e.get(k).is_some() {
        e.set(k, v);
        return;
    }
    let cat = cat_of(e).to_string();
    let order: Vec<&str> = super::modify_schema::fields(&cat).map(|f| f.iter().map(|x| x.name).collect()).unwrap_or_default();
    let Value::Obj(m) = e else { return };
    let rank = |key: &str| order.iter().position(|o| *o == key);
    let Some(r) = rank(k) else {
        m.items.push((k.to_string(), v));
        return;
    };
    let pos = m.items.iter().position(|(kk, _)| rank(kk).map(|x| x > r).unwrap_or(false)).unwrap_or(m.items.len());
    m.items.insert(pos, (k.to_string(), v));
}

fn map_pt(e: &mut Value, k: &str, xf: &Xf) {
    if let Some(p) = get_pt(e, k) {
        let q = xf.pt(p);
        if let Some(Value::Arr(a)) = e.get_mut(k) {
            a[0] = Value::f(q[0]);
            a[1] = Value::f(q[1]);
        }
    }
}

fn map_pt_list(v: &mut Value, xf: &Xf) {
    if let Value::Arr(a) = v {
        for x in a.iter_mut() {
            if let Value::Arr(c) = x {
                if c.len() >= 2 {
                    if let (Some(px), Some(py)) = (c[0].as_f64(), c[1].as_f64()) {
                        let q = xf.pt([px, py]);
                        c[0] = Value::f(q[0]);
                        c[1] = Value::f(q[1]);
                    }
                }
            }
        }
    }
}

fn map_pts(e: &mut Value, k: &str, xf: &Xf) {
    if let Some(v) = e.get_mut(k) {
        map_pt_list(v, xf);
    }
}

fn map_loops(e: &mut Value, k: &str, xf: &Xf) {
    if let Some(Value::Arr(a)) = e.get_mut(k) {
        for l in a.iter_mut() {
            map_pt_list(l, xf);
        }
    }
}

/// The signed area of a loop of points (counter-clockwise positive).
fn signed_area(v: &Value) -> f64 {
    let pts: Vec<P> = v.as_arr().map(|a| a.iter().filter_map(|x| super::common::pt(Some(x))).collect()).unwrap_or_default();
    let n = pts.len();
    let mut s = 0.0;
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    s / 2.0
}

/// A mirrored outline runs counter-clockwise again (its twin, a mass's top, with it).
fn ccw_again(e: &mut Value, k: &str, twin: Option<&str>) {
    let rev = e.get(k).map(|v| signed_area(v) < 0.0).unwrap_or(false);
    if !rev {
        return;
    }
    for key in std::iter::once(k).chain(twin) {
        if let Some(Value::Arr(a)) = e.get_mut(key) {
            a.reverse();
        }
    }
}

fn map_vec(e: &mut Value, k: &str, xf: &Xf) {
    if let Some(p) = get_pt(e, k) {
        let q = xf.vec(p);
        if let Some(Value::Arr(a)) = e.get_mut(k) {
            a[0] = Value::f(q[0]);
            a[1] = Value::f(q[1]);
        }
    }
}

fn neg(v: &Value) -> Value {
    match v.as_f64() {
        Some(x) => Value::f(-x),
        None => v.clone(),
    }
}

/// An angle field turned with the element at `p` (left out where the original leaves out a 0).
fn map_angle(e: &mut Value, k: &str, p: P, xf: &Xf, keep_zero: bool) {
    if xf.is_move() {
        return;
    }
    let old = num(e, k).unwrap_or(0.0);
    let new = xf.ang(p, old);
    if e.get(k).is_some() && (keep_zero || new != 0.0) {
        e.set(k, Value::f(new));
    } else if new != 0.0 || keep_zero {
        set_ordered(e, k, Value::f(new));
    } else if e.get(k).is_some() {
        e.remove(k);
    }
}

fn toggle(e: &mut Value, k: &str) {
    let now = e.get(k).and_then(|x| x.as_bool()).unwrap_or(false);
    if now {
        e.remove(k);
    } else {
        set_ordered(e, k, Value::Bool(true));
    }
}

/// A curve (a detail line, a sketch line) through the transform.
fn map_curve(e: &mut Value, xf: &Xf) {
    for k in ["start", "end", "through", "centre"] {
        map_pt(e, k, xf);
    }
    for k in ["points", "control", "fit"] {
        map_pts(e, k, xf);
    }
    for k in ["start_tangent", "end_tangent"] {
        map_vec(e, k, xf);
    }
    if xf.mirrors() {
        if let Some(a) = e.get("arc").cloned() {
            e.set("arc", neg(&a));
        }
        if let Some(Value::Arr(a)) = e.get_mut("arcs") {
            for x in a.iter_mut() {
                *x = neg(x);
            }
        }
        if let Some(Value::Arr(a)) = e.get_mut("radii") {
            if a.len() >= 2 {
                a[1] = neg(&a[1]);
            }
        }
    }
    // an ellipse's axis: its direction through the transform, rounded to 1e-9
    if e.get("radii").is_some() {
        let old = num(e, "angle").unwrap_or(0.0);
        let t = old.to_radians();
        let u = xf.vec([t.cos(), t.sin()]);
        let new = r9(u[1]).atan2(r9(u[0])).to_degrees();
        if e.get("angle").is_some() {
            e.set("angle", Value::f(new));
        } else if new != 0.0 {
            set_ordered(e, "angle", Value::f(new));
        }
    }
}

fn map_sketch(e: &mut Value, k: &str, xf: &Xf) {
    if let Some(Value::Arr(a)) = e.get_mut(k) {
        for l in a.iter_mut() {
            map_curve(l, xf);
        }
    }
}

/// A floor's or a region's model pattern: its origin (0, 0 unless set) and its angle go with it.
fn map_pattern(e: &mut Value, xf: &Xf) {
    let o = get_pt(e, "pattern_origin").unwrap_or([0.0, 0.0]);
    let no = xf.pt(o);
    if no != [0.0, 0.0] || e.get("pattern_origin").is_some() {
        set_ordered(e, "pattern_origin", pv(no));
    }
    map_angle(e, "pattern_angle", o, xf, false);
}

fn map_shape(e: &mut Value, xf: &Xf) {
    if let Some(sh) = e.get_mut("shape") {
        if let Some(Value::Arr(pts)) = sh.get_mut("points") {
            for p in pts.iter_mut() {
                map_pt(p, "at", xf);
            }
        }
        if let Some(Value::Arr(ls)) = sh.get_mut("lines") {
            for l in ls.iter_mut() {
                map_pt(l, "a", xf);
                map_pt(l, "b", xf);
            }
        }
    }
}

fn map_pt3s(e: &mut Value, k: &str, xf: &Xf) {
    if let Some(Value::Arr(a)) = e.get_mut(k) {
        for x in a.iter_mut() {
            map_pt3(x, xf);
        }
    }
}

fn map_pt3(x: &mut Value, xf: &Xf) {
    if let Value::Arr(c) = x {
        if c.len() >= 2 {
            if let (Some(px), Some(py)) = (c[0].as_f64(), c[1].as_f64()) {
                let q = xf.pt([px, py]);
                c[0] = Value::f(q[0]);
                c[1] = Value::f(q[1]);
            }
        }
    }
}

// ---------------------------------------------------------------- walls

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Line {
    pub a: P,
    pub b: P,
    pub arc: f64,
}

pub fn wall_line(e: &Value) -> Line {
    Line {
        a: get_pt(e, "start").unwrap_or([0.0, 0.0]),
        b: get_pt(e, "end").unwrap_or([0.0, 0.0]),
        arc: num(e, "arc").unwrap_or(0.0),
    }
}

/// An arc's centre, radius, start angle and sweep (radians), from its ends and its turn.
fn arc_geom(l: &Line) -> (P, f64, f64, f64) {
    let t = l.arc.to_radians();
    let ch = sub(l.b, l.a);
    let c_len = length(ch);
    let r = c_len / 2.0 / (t / 2.0).sin().abs();
    let m = mul(add(l.a, l.b), 0.5);
    let n = mul([-ch[1], ch[0]], 1.0 / c_len);
    let d = c_len / 2.0 / (t / 2.0).tan();
    let c = add(m, mul(n, d));
    let a0 = (l.a[1] - c[1]).atan2(l.a[0] - c[0]);
    (c, r, a0, t)
}

pub fn line_len(l: &Line) -> f64 {
    if l.arc == 0.0 {
        return dist(l.a, l.b);
    }
    let (_, r, _, t) = arc_geom(l);
    r * t.abs()
}

/// The point `s` mm along a wall's line from its start.
pub fn point_at(l: &Line, s: f64) -> P {
    if l.arc == 0.0 {
        let u = normalize(sub(l.b, l.a));
        return add(l.a, mul(u, s));
    }
    let (c, r, a0, t) = arc_geom(l);
    let ang = a0 + t.signum() * s / r;
    [c[0] + r * ang.cos(), c[1] + r * ang.sin()]
}

/// How far along a wall's line (from its start) the point nearest `p` is.
pub fn station(l: &Line, p: P) -> f64 {
    if l.arc == 0.0 {
        let u = normalize(sub(l.b, l.a));
        return dot(sub(p, l.a), u);
    }
    let (c, r, a0, t) = arc_geom(l);
    let ang = (p[1] - c[1]).atan2(p[0] - c[0]);
    let two = std::f64::consts::PI * 2.0;
    let mut da = (ang - a0) * t.signum();
    while da < -std::f64::consts::PI {
        da += two;
    }
    while da > std::f64::consts::PI * 1.5 {
        da -= two;
    }
    da * r
}

/// A door or window moved without its wall slides along it: its offset gains the move along the
/// wall's chord.
fn slide(l: &Line, off: f64, xf: &Xf) -> f64 {
    match *xf {
        Xf::Move(by) | Xf::Align { by, .. } => off + dot(by, normalize(sub(l.b, l.a))),
        _ => off,
    }
}

/// How far `p` is from the segment a-b.
fn seg_dist(p: P, a: P, b: P) -> f64 {
    let d = sub(b, a);
    let l2 = dot(d, d);
    if l2 == 0.0 {
        return dist(p, a);
    }
    let t = (dot(sub(p, a), d) / l2).clamp(0.0, 1.0);
    dist(p, add(a, mul(d, t)))
}

/// Where the lines through a, b and c, d cross; None for parallel ones.
fn line_cross(a: P, b: P, c: P, d: P) -> Option<P> {
    let r = sub(b, a);
    let s = sub(d, c);
    let den = cross(r, s);
    let scale = length(r) * length(s);
    if !(den.abs() > 1e-12 * scale) {
        return None;
    }
    let t = cross(sub(c, a), s) / den;
    Some(add(a, mul(r, t)))
}

const JOIN: f64 = 1.0;

/// How high a wall stands: from its base (its level and base offset) to its top (its top level
/// and top offset, or its height).
pub fn wall_span(pr: &Project, id: u64) -> (f64, f64) {
    let Some(e) = pr.el(id) else { return (0.0, 0.0) };
    let elev = |k: &str| -> Option<f64> {
        let g = e.get(k)?.as_str()?;
        let l = pr.find_guid(g)?;
        pr.el(l)?.get("elevation")?.as_f64()
    };
    let z0 = elev("level").unwrap_or(0.0) + num(e, "base_offset").unwrap_or(0.0);
    let z1 = match elev("top_level") {
        Some(t) => t + num(e, "top_offset").unwrap_or(0.0),
        None => z0 + num(e, "height").unwrap_or(0.0),
    };
    (z0, z1)
}

/// Walls join only where they stand at heights they share.
pub fn spans_meet(a: (f64, f64), b: (f64, f64)) -> bool {
    a.0 < b.1 && b.0 < a.1
}

/// The doors and windows a wall hosts.
pub fn openings_of(pr: &Project, wall: u64) -> Vec<u64> {
    let Some(g) = pr.guid_of(wall) else { return Vec::new() };
    pr.elements
        .iter()
        .filter(|(_, e)| matches!(cat_of(e), "door" | "window") && e.get("host").and_then(|h| h.as_str()) == Some(g.as_str()))
        .map(|(id, _)| *id)
        .collect()
}

fn set_line(pr: &mut Project, id: u64, l: Line) {
    if let Some(e) = pr.el_mut(id) {
        e.set("start", pv(l.a));
        e.set("end", pv(l.b));
    }
}

/// Moves walls (and their doors and windows) by the transform, and stretches the walls joined to
/// them so they stay joined.
fn move_walls(pr: &mut Project, walls: &[u64], xf: &Xf, lone: &BTreeSet<u64>) {
    let moved: BTreeSet<u64> = walls.iter().copied().collect();
    let old: BTreeMap<u64, Line> = pr.ids_of("wall").into_iter().map(|id| (id, wall_line(pr.el(id).unwrap()))).collect();
    let spans: BTreeMap<u64, (f64, f64)> = pr.ids_of("wall").into_iter().map(|id| (id, wall_span(pr, id))).collect();
    let apart = |a: u64, b: u64| !spans_meet(spans[&a], spans[&b]);
    // where each opening stands before
    let mut opening_at: BTreeMap<u64, (u64, P)> = BTreeMap::new();
    for (&w, l) in &old {
        for o in openings_of(pr, w) {
            let off = num(pr.el(o).unwrap(), "offset").unwrap_or(0.0);
            opening_at.insert(o, (w, point_at(l, off)));
        }
    }
    let mut new: BTreeMap<u64, Line> = old.clone();
    // the moved walls' lines as the transform takes them (joins are worked out against these)
    let mut xl: BTreeMap<u64, Line> = BTreeMap::new();
    for &w in walls {
        let l = old[&w];
        let (a, b) = if xf.mirrors() { (xf.pt(l.b), xf.pt(l.a)) } else { (xf.pt(l.a), xf.pt(l.b)) };
        new.insert(w, Line { a, b, arc: l.arc });
        xl.insert(w, Line { a, b, arc: l.arc });
    }
    // the ends of the moved walls joined to walls that stay
    let mut followed: BTreeSet<(u64, usize)> = BTreeSet::new();
    for &w in &moved {
        let lw = old[&w];
        for end in 0..2 {
            let p = if end == 0 { lw.a } else { lw.b };
            let mut joined: Vec<(u64, Option<usize>)> = Vec::new();
            for (&o, lo) in &old {
                if moved.contains(&o) || apart(o, w) {
                    continue;
                }
                if dist(lo.a, p) <= JOIN {
                    joined.push((o, Some(0)));
                } else if dist(lo.b, p) <= JOIN {
                    joined.push((o, Some(1)));
                } else if lo.arc == 0.0 && seg_dist(p, lo.a, lo.b) <= JOIN {
                    joined.push((o, None));
                }
            }
            if joined.is_empty() {
                continue;
            }
            let nw = xl[&w];
            let first = joined[0].0;
            let lf = old[&first];
            // the moved wall's end of that name as the transform put it (a mirrored wall runs back
            // the other way, and the original still names its ends as they were)
            let at_end = if end == 0 { nw.a } else { nw.b };
            let node = if nw.arc != 0.0 || lf.arc != 0.0 {
                at_end
            } else {
                match line_cross(nw.a, nw.b, lf.a, lf.b) {
                    Some(x) => r3p(x),
                    None => at_end,
                }
            };
            let mut nl = new[&w];
            if end == 0 {
                nl.a = node;
            } else {
                nl.b = node;
            }
            new.insert(w, nl);
            for (o, oe) in joined {
                if let Some(k) = oe {
                    // the first moved wall to take an end along keeps it
                    if !followed.insert((o, k)) {
                        continue;
                    }
                    let mut ol = new[&o];
                    if k == 0 {
                        ol.a = node;
                    } else {
                        ol.b = node;
                    }
                    new.insert(o, ol);
                }
            }
        }
    }
    // walls ending on a moved wall go to where their lines cross its new line
    for (&o, lo) in &old {
        if moved.contains(&o) || lo.arc != 0.0 {
            continue;
        }
        for end in 0..2 {
            let p = if end == 0 { lo.a } else { lo.b };
            for &w in walls {
                if apart(o, w) {
                    continue;
                }
                let lw = old[&w];
                if lw.arc != 0.0 || dist(lw.a, p) <= JOIN || dist(lw.b, p) <= JOIN {
                    continue;
                }
                if seg_dist(p, lw.a, lw.b) > JOIN {
                    continue;
                }
                let nw = new[&w];
                let cur = new[&o];
                let q = match line_cross(cur.a, cur.b, nw.a, nw.b) {
                    Some(x) => r3p(x),
                    None => xf.pt(p),
                };
                let mut ol = cur;
                if end == 0 {
                    ol.a = q;
                } else {
                    ol.b = q;
                }
                new.insert(o, ol);
                break;
            }
        }
    }
    for (&id, l) in &new {
        if *l != old[&id] {
            set_line(pr, id, *l);
        }
    }
    // doors and windows: those of moved walls go with them, the others stay where they stand (or,
    // moved without their wall, where they slid to)
    for (o, (w, at)) in opening_at {
        let nl = new[&w];
        let ol = old[&w];
        let lone_door = lone.contains(&o);
        let off0 = num(pr.el(o).unwrap(), "offset").unwrap_or(0.0);
        let off = if moved.contains(&w) {
            station(&nl, xf.pt(at))
        } else if nl != ol {
            let target = match *xf {
                Xf::Move(by) | Xf::Align { by, .. } if lone_door => add(at, by),
                _ => at,
            };
            station(&nl, target)
        } else if lone_door {
            slide(&ol, off0, xf)
        } else {
            continue;
        };
        if let Some(e) = pr.el_mut(o) {
            e.set("offset", Value::f(off));
            if moved.contains(&w) && xf.mirrors() {
                let h = e.get("flip_hand").and_then(|x| x.as_bool()).unwrap_or(false);
                e.set("flip_hand", Value::Bool(!h));
            }
        }
    }
}

/// Moves one end of a wall; the walls joined there follow it, and those ending on it stretch.
fn move_end(pr: &mut Project, w: u64, end: usize, by: P) {
    let old: BTreeMap<u64, Line> = pr.ids_of("wall").into_iter().map(|id| (id, wall_line(pr.el(id).unwrap()))).collect();
    let span = wall_span(pr, w);
    let mut opening_at: BTreeMap<u64, (u64, P)> = BTreeMap::new();
    for (&id, l) in &old {
        for o in openings_of(pr, id) {
            let off = num(pr.el(o).unwrap(), "offset").unwrap_or(0.0);
            opening_at.insert(o, (id, point_at(l, off)));
        }
    }
    let lw = old[&w];
    let p = if end == 0 { lw.a } else { lw.b };
    let node = add(p, by);
    let mut new = old.clone();
    let mut nw = lw;
    if end == 0 {
        nw.a = node;
    } else {
        nw.b = node;
    }
    new.insert(w, nw);
    for (&o, lo) in &old {
        if o == w || !spans_meet(wall_span(pr, o), span) {
            continue;
        }
        let mut ol = *lo;
        let mut changed = false;
        for k in 0..2 {
            let q = if k == 0 { lo.a } else { lo.b };
            let np = if dist(q, p) <= JOIN {
                Some(node)
            } else {
                let other = if end == 0 { lw.b } else { lw.a };
                if dist(q, other) <= JOIN || lo.arc != 0.0 || lw.arc != 0.0 {
                    None
                } else if seg_dist(q, lw.a, lw.b) <= JOIN {
                    let r = if k == 0 { ol.b } else { ol.a };
                    Some(match line_cross(r, q, nw.a, nw.b) {
                        Some(x) => r3p(x),
                        None => add(q, by),
                    })
                } else {
                    None
                }
            };
            if let Some(np) = np {
                if k == 0 {
                    ol.a = np;
                } else {
                    ol.b = np;
                }
                changed = true;
            }
        }
        if changed {
            new.insert(o, ol);
        }
    }
    for (&id, l) in &new {
        if *l != old[&id] {
            set_line(pr, id, *l);
        }
    }
    for (o, (wall, at)) in opening_at {
        let nl = new[&wall];
        if nl == old[&wall] {
            continue;
        }
        let off = station(&nl, at);
        if let Some(e) = pr.el_mut(o) {
            e.set("offset", Value::f(off));
        }
    }
}

// ---------------------------------------------------------------- parameters

struct Args {
    ids: Vec<u64>,
    xf: Xf,
    copy: bool,
    end: Option<usize>,
}

fn read_args(pr: &Project, cid: &str, p: &Value) -> R<Args> {
    use crate::commands::params::*;
    let ids = ids_param(pr, cid, p)?;
    let mut copy = cid == "copy";
    let mut end = None;
    let xf = match cid {
        "move" | "copy" => {
            let by = req_point(p, cid, "by")?;
            if cid == "move" {
                if let Some(e) = opt_text(p, cid, "end")? {
                    let k = match e.as_str() {
                        "start" => 0,
                        "end" => 1,
                        _ => return Err(format!("{}: `end` is `start` or `end`, not `{}`", cid, e)),
                    };
                    let ok = ids.len() == 1 && pr.category(ids[0]) == Some("wall");
                    if !ok {
                        return Err(format!("{}: `end` moves an end of one wall; give `ids` one wall", cid));
                    }
                    end = Some(k);
                }
            }
            Xf::Move(by)
        }
        "rotate" => {
            let about = req_point(p, cid, "about")?;
            let angle = match get(p, "angle") {
                None => return Err(format!("{}: `angle` in degrees, counter-clockwise, is required", cid)),
                Some(v) => mm_of(v).ok_or_else(|| format!("{}: `angle` must be a number in mm, got {}", cid, v.to_compact()))?,
            };
            copy = opt_bool(p, cid, "copy")?.unwrap_or(false);
            Xf::rotate(about, angle)
        }
        _ => {
            let axis = match get(p, "axis") {
                Some(Value::Arr(a)) => a.clone(),
                _ => return Err(format!("{}: `axis` [[x, y], …] is required", cid)),
            };
            let mut pts = Vec::new();
            for v in &axis {
                match point_of(v) {
                    Some(q) => pts.push(q),
                    None => return Err(format!("{}: `axis`: {} is not a point [x, y] in mm", cid, v.to_compact())),
                }
            }
            if pts.len() != 2 || dist(pts[0], pts[1]) <= 1.0 {
                return Err(format!("{}: `axis` is two different points [[x, y], [x, y]]", cid));
            }
            copy = opt_bool(p, cid, "copy")?.unwrap_or(false);
            Xf::mirror(pts[0], pts[1])
        }
    };
    Ok(Args { ids, xf, copy, end })
}

/// What the original refuses to move, turn or mirror.
fn refusal(pr: &Project, cid: &str, id: u64, xf: &Xf, chosen: &BTreeSet<u64>) -> Option<String> {
    let e = pr.el(id)?;
    let cat = cat_of(e);
    let msg = match cat {
        "level" => Some(format!("level {} has no place in plan; change its elevation, or add a level", id)),
        "sheet" => Some(format!("sheet {} has no place in plan; move the views on it", id)),
        "planview" | "schedule" => Some(format!("{} {} has no place in plan; move its viewport on its sheet", cat, id)),
        "view3d" if e.get("camera").map(|c| c.is_null()).unwrap_or(true) => {
            Some(format!("{} {} has no place in plan; move its viewport on its sheet", cat, id))
        }
        "railing" => {
            let host = e.get("host").and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g));
            match host {
                Some(h) if !chosen.contains(&h) => {
                    Some(format!("railing {} goes only with its stair or ramp; select that too", id))
                }
                _ => None,
            }
        }
        "door" | "window" if !xf.is_move() => {
            let host = e.get("host").and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g));
            match host {
                Some(h) if chosen.contains(&h) => None,
                _ => Some(format!("{} {} turns and mirrors only with its wall; select the wall too", cat, id)),
            }
        }
        "pointcloud" if xf.mirrors() => Some(crate::cloud::mirror_refusal(id)),
        "cadimport" if xf.mirrors() => Some(format!(
            "CAD import {} can't be mirrored; mirror it in the program that made the drawing, or turn it",
            id
        )),
        _ => None,
    };
    msg.map(|m| format!("{}: {}", cid, m))
}

// ---------------------------------------------------------------- elements

/// Where a tag's offset is measured from: the point the tag names.
fn tag_anchor(pr: &Project, host: u64) -> P {
    let Some(e) = pr.el(host) else { return [0.0, 0.0] };
    match cat_of(e) {
        "door" | "window" => {
            let w = e.get("host").and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g));
            match w.and_then(|w| pr.el(w)) {
                Some(we) => point_at(&wall_line(we), num(e, "offset").unwrap_or(0.0)),
                None => [0.0, 0.0],
            }
        }
        "room" => get_pt(e, "point").unwrap_or([0.0, 0.0]),
        "wall" | "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
        | "groundconductor" | "cable" | "roomseparator" | "grid" => {
            let a = get_pt(e, "start").unwrap_or([0.0, 0.0]);
            let b = get_pt(e, "end").unwrap_or(a);
            mul(add(a, b), 0.5)
        }
        "floor" | "ceiling" | "roof" | "shaft" | "mass" => {
            let pts: Vec<P> = e
                .get("boundary")
                .and_then(|b| b.as_arr())
                .map(|a| a.iter().filter_map(|x| super::common::pt(Some(x))).collect())
                .unwrap_or_default();
            if pts.is_empty() {
                [0.0, 0.0]
            } else {
                let mut s = [0.0, 0.0];
                for q in &pts {
                    s = add(s, *q);
                }
                mul(s, 1.0 / pts.len() as f64)
            }
        }
        _ => get_pt(e, "at").or_else(|| get_pt(e, "start")).or_else(|| get_pt(e, "point")).unwrap_or([0.0, 0.0]),
    }
}

/// One element (not a wall, door or window) through the transform; `anchors` gives a tag's host
/// point before and after.
fn xf_element(e: &mut Value, xf: &Xf, anchor: Option<(P, P)>) {
    let cat = cat_of(e).to_string();
    match cat.as_str() {
        "room" => {
            map_pt(e, "point", xf);
            if let Some(k) = e.get_mut("kept") {
                for part in ["centre", "finish"] {
                    if let Some(r) = k.get_mut(part) {
                        map_pts(r, "outer", xf);
                        map_loops(r, "holes", xf);
                        if xf.mirrors() {
                            ccw_again(r, "outer", None);
                        }
                    }
                }
            }
        }
        "floor" => {
            map_pts(e, "boundary", xf);
            if xf.mirrors() {
                ccw_again(e, "boundary", None);
            }
            map_loops(e, "openings", xf);
            map_pts(e, "arrow", xf);
            map_pattern(e, xf);
            map_sketch(e, "sketch", xf);
            map_shape(e, xf);
        }
        "ceiling" => {
            map_pts(e, "boundary", xf);
            if xf.mirrors() {
                ccw_again(e, "boundary", None);
            }
            map_loops(e, "openings", xf);
            map_sketch(e, "sketch", xf);
        }
        "roof" => {
            map_pts(e, "boundary", xf);
            map_loops(e, "courtyards", xf);
            map_loops(e, "openings", xf);
            if let Some(x) = e.get_mut("extrusion") {
                map_pts(x, "line", xf);
                if xf.mirrors() {
                    let from = num(x, "from").unwrap_or(0.0);
                    let to = num(x, "to").unwrap_or(0.0);
                    if x.get("from").is_some() {
                        x.set("from", Value::f(-to));
                    }
                    if x.get("to").is_some() {
                        x.set("to", Value::f(-from));
                    }
                }
            }
            map_sketch(e, "sketch", xf);
            map_shape(e, xf);
        }
        "shaft" => {
            map_pts(e, "boundary", xf);
            if xf.mirrors() {
                ccw_again(e, "boundary", None);
            }
            map_sketch(e, "sketch", xf);
        }
        "mass" => {
            map_pts(e, "boundary", xf);
            map_pts(e, "top", xf);
            if xf.mirrors() {
                ccw_again(e, "boundary", Some("top"));
            }
        }
        "column" | "structuralcolumn" | "footing" | "pointcloud" | "link" => {
            let at = get_pt(e, "at").unwrap_or([0.0, 0.0]);
            map_pt(e, "at", xf);
            map_angle(e, "angle", at, xf, true);
        }
        "cadimport" => {
            let at = get_pt(e, "at").unwrap_or([0.0, 0.0]);
            map_pt(e, "at", xf);
            map_angle(e, "angle", at, xf, false);
        }
        "component" => {
            let at = get_pt(e, "at").unwrap_or([0.0, 0.0]);
            map_pt(e, "at", xf);
            map_angle(e, "angle", at, xf, true);
            if xf.mirrors() {
                toggle(e, "mirrored");
            }
        }
        "detailgroup" => {
            let at = get_pt(e, "at").unwrap_or([0.0, 0.0]);
            map_pt(e, "at", xf);
            map_angle(e, "angle", at, xf, false);
            if xf.mirrors() {
                toggle(e, "mirrored");
            }
        }
        "repeatingdetail" => {
            map_pt(e, "start", xf);
            map_pt(e, "end", xf);
            if xf.mirrors() {
                toggle(e, "mirrored");
            }
        }
        "stair" | "ramp" => {
            let at = get_pt(e, "start").unwrap_or([0.0, 0.0]);
            map_pt(e, "start", xf);
            map_angle(e, "angle", at, xf, true);
            if xf.mirrors() {
                if let Some(Value::Arr(ls)) = e.get_mut("landings") {
                    for l in ls.iter_mut() {
                        if let Some(t) = l.get("turn").cloned() {
                            l.set("turn", neg(&t));
                        }
                    }
                }
            }
        }
        "railing" => {
            if e.get("host").map(|h| !h.is_null()).unwrap_or(false) {
                // a mirrored stair's left is its right
                if xf.mirrors() {
                    let side = e.get("side").and_then(|x| x.as_str()).map(|x| x.to_string());
                    match side.as_deref() {
                        Some("left") => e.set("side", Value::s("right")),
                        Some("right") => e.set("side", Value::s("left")),
                        _ => {}
                    }
                }
                return;
            }
            map_pts(e, "path", xf);
        }
        "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
        | "groundconductor" | "cable" | "roomseparator" | "grid" => {
            map_pt(e, "start", xf);
            map_pt(e, "end", xf);
        }
        "section" | "elevation" => {
            if xf.mirrors() {
                let a = get_pt(e, "start").unwrap_or([0.0, 0.0]);
                let b = get_pt(e, "end").unwrap_or([0.0, 0.0]);
                e.set("start", pv(xf.pt(b)));
                e.set("end", pv(xf.pt(a)));
            } else {
                map_pt(e, "start", xf);
                map_pt(e, "end", xf);
            }
        }
        "line" => map_curve(e, xf),
        "region" => {
            map_sketch(e, "sketch", xf);
            map_pattern(e, xf);
        }
        "text" => {
            let at = get_pt(e, "at").unwrap_or([0.0, 0.0]);
            map_pt(e, "at", xf);
            map_pt(e, "leader", xf);
            if !xf.mirrors() {
                map_angle(e, "angle", at, xf, true);
            }
        }
        "dimension" | "spot" | "viewport" => map_pt(e, "at", xf),
        "dimension3d" => {
            if let Some(a) = e.get_mut("at") {
                map_pt3(a, xf);
            }
            if let Some(Value::Arr(rs)) = e.get_mut("refs") {
                for r in rs.iter_mut() {
                    if let Some(a) = r.get_mut("at") {
                        map_pt3(a, xf);
                    }
                }
            }
        }
        "tag" => {
            if let (Some((before, after)), Some(off)) = (anchor, get_pt(e, "offset")) {
                let q = xf.pt(add(before, off));
                e.set("offset", pv(r3p(sub(q, after))));
            }
        }
        "view3d" => {
            if let Some(c) = e.get_mut("camera") {
                for k in ["eye", "target"] {
                    if let Some(a) = c.get_mut(k) {
                        map_pt3(a, xf);
                    }
                }
            }
        }
        "rebar" => map_pt3s(e, "path", xf),
        _ => {}
    }
}

// ---------------------------------------------------------------- the commands

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let p = &super::ops_geom::lib_names(&s.project, p);
    let args = read_args(&s.project, cid, p)?;
    let chosen: BTreeSet<u64> = args.ids.iter().copied().collect();
    for &id in &args.ids {
        if let Some(m) = refusal(&s.project, cid, id, &args.xf, &chosen) {
            return Err(m);
        }
    }
    if args.copy {
        let ids = copy_elements(s, &args.ids, &args.xf);
        return Ok(jobj! {"ids" => ids});
    }
    let pr = &mut s.project;
    if let (Some(end), Xf::Move(by)) = (args.end, args.xf) {
        move_end(pr, args.ids[0], end, by);
        return Ok(jobj! {"moved" => args.ids.clone()});
    }
    transform_in_place(pr, &args.ids, &args.xf);
    let key = match cid {
        "move" => "moved",
        "rotate" => "rotated",
        _ => "mirrored",
    };
    Ok(jobj! {key => args.ids.clone()})
}

/// Moves, turns or mirrors the elements (in place), with the walls joined to them.
pub fn transform_in_place(pr: &mut Project, ids: &[u64], xf: &Xf) {
    let chosen: BTreeSet<u64> = ids.iter().copied().collect();
    let walls: Vec<u64> = ids.iter().copied().filter(|id| pr.category(*id) == Some("wall")).collect();
    // tags' hosts: where they stand before, and after
    let mut tag_hosts: BTreeMap<u64, P> = BTreeMap::new();
    for &id in ids {
        if pr.category(id) == Some("tag") {
            if let Some(h) = pr.el(id).and_then(|e| e.get("host")).and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g)) {
                tag_hosts.insert(id, tag_anchor(pr, h));
            }
        }
    }
    // doors and windows chosen alone slide along their walls
    let mut lone: BTreeSet<u64> = BTreeSet::new();
    for &id in ids {
        let Some(e) = pr.el(id) else { continue };
        if !matches!(cat_of(e), "door" | "window") {
            continue;
        }
        let host = e.get("host").and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g));
        let Some(w) = host else { continue };
        if !chosen.contains(&w) {
            lone.insert(id);
        }
    }
    if !walls.is_empty() || !lone.is_empty() {
        move_walls(pr, &walls, xf, &lone);
    }
    for &id in ids {
        let Some(cat) = pr.category(id).map(|c| c.to_string()) else { continue };
        if matches!(cat.as_str(), "wall" | "door" | "window") {
            continue;
        }
        let anchor = if cat == "tag" {
            tag_hosts.get(&id).map(|before| {
                let h = pr.el(id).and_then(|e| e.get("host")).and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g));
                let after = h.map(|h| tag_anchor(pr, h)).unwrap_or(*before);
                // a host moved with it stands where the transform took it
                let after = if h.map(|h| chosen.contains(&h) || host_moves_with(pr, h, &chosen)).unwrap_or(false) {
                    after
                } else {
                    *before
                };
                (*before, after)
            })
        } else {
            None
        };
        if let Some(e) = pr.el_mut(id) {
            xf_element(e, xf, anchor);
        }
    }
}

/// Whether a tag's host moves with the elements chosen (a door or window whose wall is chosen).
fn host_moves_with(pr: &Project, h: u64, chosen: &BTreeSet<u64>) -> bool {
    let Some(e) = pr.el(h) else { return false };
    if matches!(cat_of(e), "door" | "window") {
        if let Some(w) = e.get("host").and_then(|x| x.as_str()).and_then(|g| pr.find_guid(g)) {
            return chosen.contains(&w);
        }
    }
    false
}

// ---------------------------------------------------------------- copies

/// What goes with an element when it's copied: a wall's doors and windows, a stair's or ramp's
/// railings.
fn dependants(pr: &Project, id: u64) -> Vec<u64> {
    let Some(cat) = pr.category(id) else { return Vec::new() };
    let Some(g) = pr.guid_of(id) else { return Vec::new() };
    let want: &[&str] = match cat {
        "wall" => &["door", "window"],
        "stair" | "ramp" => &["railing"],
        _ => return Vec::new(),
    };
    pr.elements
        .iter()
        .filter(|(_, e)| want.contains(&cat_of(e)) && e.get("host").and_then(|h| h.as_str()) == Some(g.as_str()))
        .map(|(id, _)| *id)
        .collect()
}

/// The next mark or number in a series, as a new door, window or room takes one: the series most
/// marks share (two at least; on a tie, the first by name), else the next whole number.
pub fn next_mark(marks: &[String]) -> String {
    let mut groups: BTreeMap<String, (usize, u64, usize)> = BTreeMap::new();
    let mut numeric: Option<u64> = None;
    for m in marks {
        let digits: String = m.chars().rev().take_while(|c| c.is_ascii_digit()).collect::<Vec<_>>().into_iter().rev().collect();
        if digits.is_empty() {
            continue;
        }
        let prefix = &m[..m.len() - digits.len()];
        let n: u64 = match digits.parse() {
            Ok(n) => n,
            Err(_) => continue,
        };
        if prefix.is_empty() {
            numeric = Some(numeric.map(|x| x.max(n)).unwrap_or(n));
            continue;
        }
        let g = groups.entry(prefix.to_string()).or_insert((0, 0, 0));
        g.0 += 1;
        if n >= g.1 {
            g.1 = n;
            g.2 = g.2.max(digits.len());
        }
    }
    let mut best: Option<(&String, &(usize, u64, usize))> = None;
    for (k, v) in &groups {
        if v.0 < 2 {
            continue;
        }
        if best.map(|(_, b)| v.0 > b.0).unwrap_or(true) {
            best = Some((k, v));
        }
    }
    if let Some((prefix, (_, max, width))) = best {
        return format!("{}{:0width$}", prefix, max + 1, width = *width);
    }
    format!("{}", numeric.map(|n| n + 1).unwrap_or(1))
}

fn marks_of(pr: &Project, cat: &str, key: &str) -> Vec<String> {
    pr.elements
        .values()
        .filter(|e| cat_of(e) == cat)
        .filter_map(|e| e.get(key).and_then(|m| m.as_str()).map(|s| s.to_string()))
        .collect()
}

fn grid_name(pr: &Project) -> String {
    let names: Vec<String> = marks_of(pr, "grid", "name");
    let last = names.last().cloned().unwrap_or_default();
    let mut c = last.chars();
    if let (Some(ch), None) = (c.next(), c.next()) {
        if ch.is_ascii_uppercase() && ch != 'Z' {
            let mut ch = (ch as u8 + 1) as char;
            loop {
                let cand = ch.to_string();
                if !names.contains(&cand) || ch == 'Z' {
                    return cand;
                }
                ch = (ch as u8 + 1) as char;
            }
        }
    }
    let mut n = names
        .iter()
        .filter(|n| !n.is_empty() && n.chars().all(|c| c.is_ascii_digit()))
        .filter_map(|n| n.parse::<u64>().ok())
        .max()
        .unwrap_or(0)
        + 1;
    loop {
        let cand = n.to_string();
        if !names.contains(&cand) {
            return cand;
        }
        n += 1;
    }
}

/// The word a project's language names sections and elevations by.
fn view_word(lang: &str, cat: &str) -> &'static str {
    match (cat, lang) {
        ("section", "pt") => "Corte",
        ("section", "es") => "Sección",
        ("section", "sv") => "Sektion",
        ("section", "cs") => "Řez",
        ("section", "fr") => "Coupe",
        ("section", "nl") => "Doorsnede",
        ("section", "de") => "Schnitt",
        ("section", "it") => "Sezione",
        ("section", _) => "Section",
        (_, "pt") => "Elevação",
        (_, "es") => "Elevación",
        (_, "sv") => "Fasad",
        (_, "cs") => "Pohled",
        (_, "fr") => "Élévation",
        (_, "nl") => "Gevel",
        (_, "de") => "Ansicht",
        (_, "it") => "Prospetto",
        _ => "Elevation",
    }
}

fn view_name(pr: &Project, cat: &str) -> String {
    let word = view_word(&pr.language(), cat);
    let names: Vec<String> = pr
        .elements
        .values()
        .filter(|e| matches!(cat_of(e), "section" | "elevation" | "planview" | "view3d" | "schedule" | "level"))
        .filter_map(|e| e.get("name").and_then(|m| m.as_str()).map(|s| s.to_string()))
        .collect();
    let mut n = 1;
    loop {
        let cand = format!("{} {}", word, n);
        if !names.contains(&cand) {
            return cand;
        }
        n += 1;
    }
}

/// Remaps what an element points at among the ones copied with it.
fn remap(v: &mut Value, map: &BTreeMap<String, String>) {
    match v {
        Value::Str(s) => {
            if let Some(n) = map.get(s.as_str()) {
                *s = n.clone();
            }
        }
        Value::Arr(a) => a.iter_mut().for_each(|x| remap(x, map)),
        Value::Obj(m) => {
            for (k, x) in m.items.iter_mut() {
                if k != "guid" {
                    remap(x, map);
                }
            }
        }
        _ => {}
    }
}

/// Library parts an element holds with ids of their own (a region's sketch lines): new ones.
fn renew_parts(pr: &mut Project, e: &mut Value) {
    for k in ["sketch"] {
        let n = e.get(k).and_then(|a| a.as_arr()).map(|a| a.len()).unwrap_or(0);
        for i in 0..n {
            let has = e.get(k).and_then(|a| a.as_arr()).and_then(|a| a.get(i)).map(|x| x.get("id").is_some()).unwrap_or(false);
            if !has {
                continue;
            }
            let id = pr.alloc_lib_id();
            let g = crate::rand::guid();
            if let Some(Value::Arr(a)) = e.get_mut(k) {
                if let Some(x) = a.get_mut(i) {
                    x.set("id", Value::u(id));
                    x.set("guid", Value::Str(g));
                }
            }
        }
    }
}

fn copy_elements(s: &mut Session, ids: &[u64], xf: &Xf) -> Vec<u64> {
    let now_phase = s.now_phase.clone();
    let now_option = s.now_option.clone();
    let pr = &mut s.project;
    let chosen: BTreeSet<u64> = ids.iter().copied().collect();
    let host_of = |pr: &Project, id: u64| -> Option<u64> {
        pr.el(id).and_then(|e| e.get("host")).and_then(|h| h.as_str()).and_then(|g| pr.find_guid(g))
    };
    // what's copied first, as given; then what goes with it (a wall's doors and windows, a stair's
    // railings), by id; then the annotation that points at them, as given
    let is_note = |pr: &Project, id: u64| matches!(pr.category(id), Some("tag" | "dimension" | "spot"));
    let mut first: Vec<u64> = Vec::new();
    for &id in ids {
        let dep = match pr.category(id) {
            Some("door" | "window" | "railing") => host_of(pr, id).map(|h| chosen.contains(&h)).unwrap_or(false),
            _ => false,
        };
        if !dep && !is_note(pr, id) {
            first.push(id);
        }
    }
    let mut deps: BTreeSet<u64> = BTreeSet::new();
    for &id in &first {
        for d in dependants(pr, id) {
            deps.insert(d);
        }
    }
    let notes: Vec<u64> = ids.iter().copied().filter(|id| is_note(pr, *id)).collect();
    let order: Vec<u64> = first.iter().copied().chain(deps.iter().copied()).chain(notes.iter().copied()).collect();
    let copied: BTreeSet<u64> = order.iter().copied().collect();
    // tags' anchors before
    let mut anchors: BTreeMap<u64, P> = BTreeMap::new();
    for &id in &notes {
        if pr.category(id) == Some("tag") {
            if let Some(h) = host_of(pr, id) {
                anchors.insert(id, tag_anchor(pr, h));
            }
        }
    }
    let mut guid_map: BTreeMap<String, String> = BTreeMap::new();
    let mut id_map: BTreeMap<u64, u64> = BTreeMap::new();
    let mut out = Vec::new();
    for &id in &order {
        let nid = pr.alloc_id();
        let mut e = pr.el(id).cloned().unwrap();
        let cat = cat_of(&e).to_string();
        let ng = crate::rand::guid();
        if let Some(g) = e.get("guid").and_then(|g| g.as_str()).map(|s| s.to_string()) {
            guid_map.insert(g, ng.clone());
        }
        e.set("guid", Value::Str(ng));
        if deps.contains(&id) || notes.contains(&id) {
            remap(&mut e, &guid_map);
        }
        match cat.as_str() {
            "wall" => {
                let l = wall_line(&e);
                let (a, b) = if xf.mirrors() { (xf.pt(l.b), xf.pt(l.a)) } else { (xf.pt(l.a), xf.pt(l.b)) };
                e.set("start", pv(a));
                e.set("end", pv(b));
            }
            "door" | "window" => {
                let host = host_of(pr, id);
                let host_copied = host.map(|h| copied.contains(&h)).unwrap_or(false);
                let off = num(&e, "offset").unwrap_or(0.0);
                if host_copied {
                    if xf.mirrors() {
                        let l = wall_line(pr.el(host.unwrap()).unwrap());
                        e.set("offset", Value::f(line_len(&l) - off));
                        let h = e.get("flip_hand").and_then(|x| x.as_bool()).unwrap_or(false);
                        e.set("flip_hand", Value::Bool(!h));
                    }
                } else if let Some(w) = host {
                    let l = wall_line(pr.el(w).unwrap());
                    e.set("offset", Value::f(slide(&l, off, xf)));
                }
                let mark = next_mark(&marks_of(pr, &cat, "mark"));
                e.set("mark", Value::Str(mark));
            }
            "room" => {
                xf_element(&mut e, xf, None);
                let n = next_mark(&marks_of(pr, "room", "number"));
                e.set("number", Value::Str(n));
            }
            "grid" => {
                xf_element(&mut e, xf, None);
                e.set("name", Value::Str(grid_name(pr)));
            }
            "section" | "elevation" => {
                xf_element(&mut e, xf, None);
                e.set("name", Value::Str(view_name(pr, &cat)));
            }
            "tag" => {
                let anchor = anchors.get(&id).copied().map(|b| {
                    let after = host_of(pr, id).and_then(|h| id_map.get(&h).copied()).map(|nh| tag_anchor(pr, nh));
                    (b, after.unwrap_or(b))
                });
                xf_element(&mut e, xf, anchor);
            }
            _ => xf_element(&mut e, xf, None),
        }
        renew_parts(pr, &mut e);
        crate::styles::phasing::stamp_copy(pr, now_phase.as_deref(), now_option.as_deref(), &mut e);
        pr.elements.insert(nid, e);
        id_map.insert(id, nid);
        out.push(nid);
    }
    out
}

