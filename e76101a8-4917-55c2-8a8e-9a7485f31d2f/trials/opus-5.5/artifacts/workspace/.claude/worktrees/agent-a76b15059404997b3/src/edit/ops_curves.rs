//! Split on detail lines of other shapes: arcs, polylines, circles, ellipses and splines. A
//! closed one (a circle, a whole ellipse, a closed polyline) opens where it's split instead.

use super::common::*;
use super::ops_arcs::arc_nearest;
use super::ops_geom::*;
use super::ops_lines::{kind, not_on, set_shape};
use crate::json::Value;
use crate::project::Project;

const BETWEEN: &str = "split: split between the line's ends";

fn pts_of(v: Option<&Value>) -> Vec<P> {
    v.and_then(|x| x.as_arr()).map(|a| a.iter().map(|p| pt_of(Some(p))).collect()).unwrap_or_default()
}

fn nums_of(v: Option<&Value>) -> Vec<f64> {
    v.and_then(|x| x.as_arr()).map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect()).unwrap_or_default()
}

fn pts_val(ps: &[P]) -> Value {
    Value::Arr(ps.iter().map(|p| ptv(*p)).collect())
}

fn nums_val(xs: &[f64]) -> Value {
    Value::Arr(xs.iter().map(|x| Value::f(*x)).collect())
}

/// Adds a copy of a detail line with a shape of its own; its id.
fn add_copy(pr: &mut Project, e: &Value, shape: Vec<(&str, Value)>) -> u64 {
    let nid = pr.alloc_id();
    let mut ne = e.clone();
    ne.set("guid", Value::s(&crate::rand::guid()));
    set_shape(&mut ne, shape);
    pr.elements.insert(nid, ne);
    nid
}

/// The shape fields of a run of polyline points: a line (with its arc) for one segment, else a
/// polyline (with its arcs where any turns).
fn run_shape(ps: &[P], arcs: &[f64]) -> Vec<(&'static str, Value)> {
    if ps.len() == 2 {
        let mut f = vec![("start", ptv(ps[0])), ("end", ptv(ps[1]))];
        if arcs.first().copied().unwrap_or(0.0) != 0.0 {
            f.push(("arc", Value::f(arcs[0])));
        }
        return f;
    }
    let mut f = vec![("points", pts_val(ps))];
    if arcs.iter().any(|a| *a != 0.0) {
        f.push(("arcs", nums_val(arcs)));
    }
    f
}

pub fn split_curve(pr: &mut Project, id: u64, at: P) -> R<Value> {
    let e = pr.el(id).unwrap().clone();
    match kind(&e) {
        "arc" => split_arc(pr, id, &e, at),
        "polyline" => split_polyline(pr, id, &e, at),
        "circle" => open_circle(pr, id, &e, at),
        "ellipse" | "partial ellipse" => split_ellipse(pr, id, &e, at),
        "spline" => split_spline(pr, id, &e, at),
        _ => split_fit(pr, id, &e, at),
    }
}

// ---------------------------------------------------------------- arcs

fn split_arc(pr: &mut Project, id: u64, e: &Value, at: P) -> R<Value> {
    let a = pt_of(e.get("start"));
    let b = pt_of(e.get("end"));
    let deg = e.get("arc").and_then(|x| x.as_f64()).unwrap_or(0.0);
    let arc = arc_of(a, b, deg);
    let (u, d) = arc_nearest(&arc, at);
    if d > 100.0 {
        return Err(not_on(at, id, d));
    }
    let s = u * arc.r;
    if !(s > 1.0 && arc.len() - s > 1.0) {
        return Err(BETWEEN.into());
    }
    let q = arc.at(arc.a0 + arc.sweep.signum() * u);
    let first = arc.sweep.signum() * u.to_degrees();
    let second = deg - first;
    let nid = add_copy(pr, e, vec![("start", ptv(q)), ("end", ptv(b)), ("arc", Value::f(second))]);
    let w = pr.el_mut(id).unwrap();
    set_pt(w, "end", q);
    w.set("arc", Value::f(first));
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}

// ---------------------------------------------------------------- polylines

/// The point of a segment (straight, or an arc of `deg`) nearest `p`: how far along it (0 to 1),
/// the point, and how far `p` is from it; and, for an arc, the turn to that point.
fn seg_nearest(a: P, b: P, deg: f64, p: P) -> (f64, P, f64, f64) {
    if deg == 0.0 {
        let d = sub(b, a);
        let l2 = dot(d, d);
        let t = if l2 > 0.0 { (dot(sub(p, a), d) / l2).clamp(0.0, 1.0) } else { 0.0 };
        let q = add(a, mul(d, t));
        return (t, q, dist(p, q), 0.0);
    }
    let arc = arc_of(a, b, deg);
    let (u, d) = arc_nearest(&arc, p);
    let q = arc.at(arc.a0 + arc.sweep.signum() * u);
    (u / arc.sweep.abs(), q, d, arc.sweep.signum() * u.to_degrees())
}

fn split_polyline(pr: &mut Project, id: u64, e: &Value, at: P) -> R<Value> {
    let ps = pts_of(e.get("points"));
    let closed = e.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
    let n = ps.len();
    let nseg = if closed { n } else { n - 1 };
    let mut arcs = nums_of(e.get("arcs"));
    arcs.resize(nseg, 0.0);
    // the nearest segment
    let mut best: Option<(usize, f64, P, f64, f64)> = None;
    for i in 0..nseg {
        let a = ps[i];
        let b = ps[(i + 1) % n];
        let (t, q, d, turn) = seg_nearest(a, b, arcs[i], at);
        if best.map(|x| d < x.3).unwrap_or(true) {
            best = Some((i, t, q, d, turn));
        }
    }
    let (i, _t, q, d, turn) = best.unwrap();
    if d > 100.0 {
        return Err(not_on(at, id, d));
    }
    // within a millimetre of a corner, at the corner
    let a = ps[i];
    let b = ps[(i + 1) % n];
    let vertex = if dist(q, a) <= 1.0 {
        Some(i)
    } else if dist(q, b) <= 1.0 {
        Some((i + 1) % n)
    } else {
        None
    };
    if closed {
        let (pts, arr) = match vertex {
            Some(k) => {
                let mut pts: Vec<P> = ps[k..].to_vec();
                pts.extend_from_slice(&ps[..k]);
                pts.push(ps[k]);
                let mut arr: Vec<f64> = arcs[k..].to_vec();
                arr.extend_from_slice(&arcs[..k]);
                (pts, arr)
            }
            None => {
                let mut pts = vec![q];
                pts.extend_from_slice(&ps[i + 1..]);
                pts.extend_from_slice(&ps[..=i]);
                pts.push(q);
                let mut arr = vec![arcs[i] - turn];
                arr.extend_from_slice(&arcs[i + 1..]);
                arr.extend_from_slice(&arcs[..i]);
                arr.push(turn);
                (pts, arr)
            }
        };
        let mut f = vec![("points", pts_val(&pts))];
        if arr.iter().any(|x| *x != 0.0) {
            f.push(("arcs", nums_val(&arr)));
        }
        set_shape(pr.el_mut(id).unwrap(), f);
        return Ok(crate::jobj! {"ids" => vec![Value::u(id)], "opened" => true});
    }
    let (p1, a1, p2, a2) = match vertex {
        Some(k) => {
            if k == 0 || k == n - 1 {
                return Err(BETWEEN.into());
            }
            (ps[..=k].to_vec(), arcs[..k].to_vec(), ps[k..].to_vec(), arcs[k..].to_vec())
        }
        None => {
            let mut p1 = ps[..=i].to_vec();
            p1.push(q);
            let mut a1 = arcs[..i].to_vec();
            a1.push(turn);
            let mut p2 = vec![q];
            p2.extend_from_slice(&ps[i + 1..]);
            let mut a2 = vec![arcs[i] - turn];
            a2.extend_from_slice(&arcs[i + 1..]);
            (p1, a1, p2, a2)
        }
    };
    let nid = add_copy(pr, e, run_shape(&p2, &a2));
    set_shape(pr.el_mut(id).unwrap(), run_shape(&p1, &a1));
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}

// ---------------------------------------------------------------- circles and ellipses

fn open_circle(pr: &mut Project, id: u64, e: &Value, at: P) -> R<Value> {
    let c = pt_of(e.get("centre"));
    let r = e.get("radius").and_then(|x| x.as_f64()).unwrap_or(0.0);
    let d = (dist(at, c) - r).abs();
    if d > 100.0 {
        return Err(not_on(at, id, d));
    }
    let v = sub(at, c);
    let ang = v[1].atan2(v[0]);
    let q = [c[0] + r * ang.cos(), c[1] + r * ang.sin()];
    let o = sub(c, sub(q, c));
    set_shape(
        pr.el_mut(id).unwrap(),
        vec![("points", pts_val(&[q, o, q])), ("arcs", nums_val(&[180.0, 180.0]))],
    );
    Ok(crate::jobj! {"ids" => vec![Value::u(id)], "opened" => true})
}

struct Ellipse {
    c: P,
    a: f64,
    b: f64,
    rot: f64,
}

impl Ellipse {
    fn at(&self, t: f64) -> P {
        let (s, co) = self.rot.sin_cos();
        let x = self.a * t.cos();
        let y = self.b * t.sin();
        [self.c[0] + x * co - y * s, self.c[1] + x * s + y * co]
    }
    fn at_deg(&self, t: f64) -> P {
        self.at(t.to_radians())
    }
    /// The parameter (degrees) of the point nearest `p` from `t0` to `t1`.
    fn nearest(&self, p: P, t0: f64, t1: f64) -> f64 {
        let n = 720;
        let mut bt = t0;
        let mut bd = f64::INFINITY;
        for i in 0..=n {
            let t = t0 + (t1 - t0) * i as f64 / n as f64;
            let d = dist(self.at_deg(t), p);
            if d < bd {
                bd = d;
                bt = t;
            }
        }
        // a point of the curve where it is sampled is that sample
        if bd <= 1e-9 {
            return bt;
        }
        let h = (t1 - t0) / n as f64;
        let (mut lo, mut hi) = ((bt - h).max(t0), (bt + h).min(t1));
        let g = (5f64.sqrt() - 1.0) / 2.0;
        for _ in 0..80 {
            let m1 = hi - g * (hi - lo);
            let m2 = lo + g * (hi - lo);
            if dist(self.at_deg(m1), p) < dist(self.at_deg(m2), p) {
                hi = m2;
            } else {
                lo = m1;
            }
        }
        (lo + hi) / 2.0
    }
}

fn split_ellipse(pr: &mut Project, id: u64, e: &Value, at: P) -> R<Value> {
    let c = pt_of(e.get("centre"));
    let radii = nums_of(e.get("radii"));
    let el = Ellipse {
        c,
        a: radii.first().copied().unwrap_or(0.0),
        b: radii.get(1).copied().unwrap_or(0.0),
        rot: e.get("angle").and_then(|x| x.as_f64()).unwrap_or(0.0).to_radians(),
    };
    let span = nums_of(e.get("span"));
    let deg = if span.len() == 2 { el.nearest(at, span[0], span[1]) } else { el.nearest(at, 0.0, 360.0) };
    let deg = if span.len() != 2 && deg >= 360.0 { deg - 360.0 } else { deg };
    let q = el.at_deg(deg);
    let d = dist(q, at);
    if d > 100.0 {
        return Err(not_on(at, id, d));
    }
    if span.len() != 2 {
        let mut w = pr.el(id).unwrap().clone();
        crate::edit::ops_geom::set_ordered(&mut w, super::ops_lines::LINE_ORDER, "span", nums_val(&[deg, deg + 360.0]));
        *pr.el_mut(id).unwrap() = w;
        return Ok(crate::jobj! {"ids" => vec![Value::u(id)], "opened" => true});
    }
    let (s0, s1) = (span[0], span[1]);
    if !(dist(q, el.at_deg(s0)) > 1.0 && dist(q, el.at_deg(s1)) > 1.0) {
        return Err(BETWEEN.into());
    }
    let mut shape: Vec<(&str, Value)> = vec![("centre", ptv(c)), ("radii", nums_val(&radii))];
    if let Some(a) = e.get("angle") {
        shape.push(("angle", a.clone()));
    }
    let mut second = shape.clone();
    second.push(("span", nums_val(&[deg, s1])));
    let nid = add_copy(pr, e, second);
    pr.el_mut(id).unwrap().set("span", nums_val(&[s0, deg]));
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}

// ---------------------------------------------------------------- splines

struct Spline {
    ctrl: Vec<P>,
    knots: Vec<f64>,
    p: usize,
}

impl Spline {
    fn of(e: &Value) -> Spline {
        let ctrl = pts_of(e.get("control"));
        let n = ctrl.len();
        let p = 3.min(n.saturating_sub(1)).max(1);
        let knots = match e.get("knots").and_then(|k| k.as_arr()) {
            Some(_) => nums_of(e.get("knots")),
            None => {
                // clamped, uniform inside
                let mut k = vec![0.0; p + 1];
                let inner = n - p - 1;
                for i in 1..=inner {
                    k.push(i as f64 / (inner + 1) as f64);
                }
                k.extend(std::iter::repeat(1.0).take(p + 1));
                k
            }
        };
        Spline { ctrl, knots, p }
    }
    fn span(&self, t: f64) -> usize {
        let n = self.ctrl.len();
        if t >= self.knots[n] {
            return n - 1;
        }
        let mut k = self.p;
        while k < n - 1 && self.knots[k + 1] <= t {
            k += 1;
        }
        k
    }
    fn at(&self, t: f64) -> P {
        let k = self.span(t);
        let p = self.p;
        let mut d: Vec<P> = (0..=p).map(|j| self.ctrl[j + k - p]).collect();
        for r in 1..=p {
            for j in (r..=p).rev() {
                let i = j + k - p;
                let den = self.knots[i + p + 1 - r] - self.knots[i];
                let a = if den > 0.0 { (t - self.knots[i]) / den } else { 0.0 };
                d[j] = add(mul(d[j - 1], 1.0 - a), mul(d[j], a));
            }
        }
        d[p]
    }
    fn domain(&self) -> (f64, f64) {
        (self.knots[self.p], self.knots[self.ctrl.len()])
    }
    fn nearest(&self, x: P) -> f64 {
        let (t0, t1) = self.domain();
        let n = 1000;
        let mut bt = t0;
        let mut bd = f64::INFINITY;
        for i in 0..=n {
            let t = t0 + (t1 - t0) * i as f64 / n as f64;
            let d = dist(self.at(t), x);
            if d < bd {
                bd = d;
                bt = t;
            }
        }
        if bd <= 1e-9 {
            return bt;
        }
        let h = (t1 - t0) / n as f64;
        let (mut lo, mut hi) = ((bt - h).max(t0), (bt + h).min(t1));
        let g = (5f64.sqrt() - 1.0) / 2.0;
        for _ in 0..80 {
            let m1 = hi - g * (hi - lo);
            let m2 = lo + g * (hi - lo);
            if dist(self.at(m1), x) < dist(self.at(m2), x) {
                hi = m2;
            } else {
                lo = m1;
            }
        }
        let t = (lo + hi) / 2.0;
        // at one of its knots, that knot
        for k in &self.knots {
            if (t - k).abs() <= 1e-9 {
                return *k;
            }
        }
        t
    }
    /// Inserts the knot `t` once (Boehm).
    fn insert(&mut self, t: f64) {
        let k = self.span(t);
        let p = self.p;
        let mut q: Vec<P> = Vec::with_capacity(self.ctrl.len() + 1);
        for i in 0..=self.ctrl.len() {
            if i + p <= k {
                q.push(self.ctrl[i]);
            } else if i > k {
                q.push(self.ctrl[i - 1]);
            } else {
                let den = self.knots[i + p] - self.knots[i];
                let a = if den > 0.0 { (t - self.knots[i]) / den } else { 0.0 };
                q.push(add(mul(self.ctrl[i - 1], 1.0 - a), mul(self.ctrl[i], a)));
            }
        }
        self.ctrl = q;
        self.knots.insert(k + 1, t);
    }
}

fn split_spline(pr: &mut Project, id: u64, e: &Value, at: P) -> R<Value> {
    let mut sp = Spline::of(e);
    if sp.ctrl.len() < 2 {
        return Err(BETWEEN.into());
    }
    let t = sp.nearest(at);
    let q = sp.at(t);
    let d = dist(q, at);
    if d > 100.0 {
        return Err(not_on(at, id, d));
    }
    let n0 = sp.ctrl.len();
    if !(dist(q, sp.ctrl[0]) > 1.0 && dist(q, sp.ctrl[n0 - 1]) > 1.0) {
        return Err(BETWEEN.into());
    }
    let p = sp.p;
    let mult = sp.knots.iter().filter(|k| **k == t).count();
    for _ in mult..p + 1 {
        sp.insert(t);
    }
    // the knot vector now holds t p+1 times: cut there
    let first_t = sp.knots.iter().position(|k| *k == t).unwrap();
    let k1: Vec<f64> = sp.knots[..first_t + p + 1].to_vec();
    let c1: Vec<P> = sp.ctrl[..first_t].to_vec();
    let k2: Vec<f64> = sp.knots[first_t..].to_vec();
    let c2: Vec<P> = sp.ctrl[first_t..].to_vec();
    let nid = add_copy(pr, e, vec![("control", pts_val(&c2)), ("knots", nums_val(&k2))]);
    set_shape(pr.el_mut(id).unwrap(), vec![("control", pts_val(&c1)), ("knots", nums_val(&k1))]);
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}

/// A spline through points: cut at the nearest of the points it passes through, as a run of its
/// points each side (an approximation of the original's resampling).
fn split_fit(pr: &mut Project, id: u64, e: &Value, at: P) -> R<Value> {
    let ps = pts_of(e.get("fit"));
    if ps.len() < 2 {
        return Err(BETWEEN.into());
    }
    let mut best = (0usize, ps[0], f64::INFINITY);
    for i in 0..ps.len() - 1 {
        let (_, q, d, _) = seg_nearest(ps[i], ps[i + 1], 0.0, at);
        if d < best.2 {
            best = (i, q, d);
        }
    }
    let (i, q, d) = best;
    if d > 100.0 {
        return Err(not_on(at, id, d));
    }
    if !(dist(q, ps[0]) > 1.0 && dist(q, ps[ps.len() - 1]) > 1.0) {
        return Err(BETWEEN.into());
    }
    let tan = dir(sub(ps[i + 1], ps[i]));
    let mut p1 = ps[..=i].to_vec();
    p1.push(q);
    let mut p2 = vec![q];
    p2.extend_from_slice(&ps[i + 1..]);
    let mut s1: Vec<(&str, Value)> = vec![("fit", pts_val(&p1))];
    if let Some(v) = e.get("start_tangent") {
        s1.push(("start_tangent", v.clone()));
    }
    s1.push(("end_tangent", ptv(tan)));
    let mut s2: Vec<(&str, Value)> = vec![("fit", pts_val(&p2)), ("start_tangent", ptv(tan))];
    if let Some(v) = e.get("end_tangent") {
        s2.push(("end_tangent", v.clone()));
    }
    let nid = add_copy(pr, e, s2);
    set_shape(pr.el_mut(id).unwrap(), s1);
    Ok(crate::jobj! {"ids" => vec![Value::u(id), Value::u(nid)]})
}
