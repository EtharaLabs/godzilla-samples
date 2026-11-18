//! What a wall attaches to: the top and the underside of a floor or a roof as planar pieces in
//! plan, and the heights an attached wall's base and top reach over its footprint.

use super::util::*;
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;

/// A planar piece of a surface: its ring in plan and its plane, N . (x, y, z) = d with
/// N = (-g, 1) for the gradient g, plus a lift (a slab's depth, plumb); and the way up its slope
/// (a unit vector) with its rise over run (0 for a level piece).
#[derive(Clone, Debug)]
pub struct Piece {
    pub ring: Vec<P2>,
    pub n3: [f64; 3],
    pub d: f64,
    pub lift: f64,
    pub up: P2,
    pub tan: f64,
}

impl Piece {
    /// The piece through height z0 at o, rising `tan` per mm toward `up`.
    pub fn new(ring: Vec<P2>, o: P2, z0: f64, up: P2, tan: f64, lift: f64) -> Piece {
        let g = [up[0] * tan, up[1] * tan];
        let n3 = [-g[0], -g[1], 1.0];
        let d = n3[0] * o[0] + n3[1] * o[1] + n3[2] * z0;
        Piece { ring, n3, d, lift, up, tan }
    }

    fn from_gradient(ring: Vec<P2>, o: P2, z0: f64, g: P2, lift: f64) -> Piece {
        let tan = geom::len(g);
        let up = if tan > 0.0 { [g[0] / tan, g[1] / tan] } else { [0.0, 0.0] };
        let n3 = [-g[0], -g[1], 1.0];
        let d = n3[0] * o[0] + n3[1] * o[1] + n3[2] * z0;
        Piece { ring, n3, d, lift, up, tan }
    }

    pub fn z_at(&self, q: P2) -> f64 {
        (self.d - self.n3[0] * q[0] - self.n3[1] * q[1]) / self.n3[2] + self.lift
    }

    fn holds(&self, q: P2) -> bool {
        let n = self.ring.len();
        n >= 3 && (geom::inside_raw(&self.ring, q) || (0..n).any(|i| geom::seg_dist(self.ring[i], self.ring[(i + 1) % n], q) <= 1e-6))
    }
}

/// The plane through three points with heights: (origin, z there, gradient).
fn plane3(p: [P2; 3], z: [f64; 3]) -> (P2, f64, P2) {
    let e1 = geom::sub(p[1], p[0]);
    let e2 = geom::sub(p[2], p[0]);
    let (d1, d2) = (z[1] - z[0], z[2] - z[0]);
    let det = geom::cross(e1, e2);
    if det.abs() < 1e-12 {
        return (p[0], z[0], [0.0, 0.0]);
    }
    (p[0], z[0], [(d1 * e2[1] - d2 * e1[1]) / det, (e1[0] * d2 - e2[0] * d1) / det])
}

fn level_base(pr: &Project, e: &Value) -> f64 {
    level_of(pr, e).map(|l| elev(pr, l)).unwrap_or(0.0) + numd(e, "offset", 0.0)
}

fn own_thickness(pr: &Project, e: &Value, c: &str) -> f64 {
    type_name(pr, e).map(|n| thickness(pr, c, &n)).unwrap_or(0.0)
}

/// A shaped top's triangles over the outline as if its openings were closed (a roof's
/// courtyards stay open), each corner lifted by the point there: the pieces of the top, lifted.
fn shaped_pieces(e: &Value, base: f64, lift: f64) -> Option<Vec<Piece>> {
    let sh = super::shape::Shape::read(e);
    if sh.is_empty() {
        return None;
    }
    let b = pts(e, "boundary").unwrap_or_default();
    let holes = if cat(e) == "roof" { rings(e, "courtyards") } else { Vec::new() };
    let ps: Vec<P2> = sh.points.iter().map(|p| p.at).collect();
    let lines: Vec<(P2, P2)> = sh.lines.iter().map(|l| (l.a, l.b)).collect();
    let t = crate::geom::tri::constrained(&b, &holes, &ps, &lines).ok()?;
    let z: Vec<f64> = t
        .pts
        .iter()
        .map(|q| sh.points.iter().find(|p| geom::dist(p.at, *q) <= crate::geom::tri::TOL).map(|p| p.z).unwrap_or(0.0))
        .collect();
    let mut out = Vec::new();
    for tr in &t.tris {
        let p = [t.pts[tr[0]], t.pts[tr[1]], t.pts[tr[2]]];
        let (o, z0, g) = plane3(p, [base + z[tr[0]], base + z[tr[1]], base + z[tr[2]]]);
        out.push(Piece::from_gradient(p.to_vec(), o, z0, g, lift));
    }
    Some(out)
}

/// The pieces of a floor's or a roof's top (`top`) or underside.
pub fn pieces(pr: &Project, e: &Value, top: bool) -> Vec<Piece> {
    match cat(e) {
        "floor" => floor_pieces(pr, e, top),
        "roof" => roof_pieces(pr, e, top),
        _ => Vec::new(),
    }
}

fn floor_pieces(pr: &Project, e: &Value, top: bool) -> Vec<Piece> {
    let b = pts(e, "boundary").unwrap_or_default();
    if b.len() < 3 {
        return Vec::new();
    }
    let t = own_thickness(pr, e, "floor");
    let base = level_base(pr, e);
    // under a variable layer a shaped floor's underside stays level where it was
    let var = type_name(pr, e).and_then(|n| variable_layer(pr, "floor", &n)).is_some();
    if top || !var {
        if let Some(ps) = shaped_pieces(e, base, if top { 0.0 } else { -t }) {
            return ps;
        }
    }
    let slope = numd(e, "slope", 0.0);
    let arrow = pts(e, "arrow");
    match &arrow {
        Some(a) if slope != 0.0 && a.len() == 2 && geom::dist(a[0], a[1]) > 0.0 => {
            let u = geom::unit(geom::sub(a[1], a[0]));
            let r = slope.to_radians();
            vec![Piece::new(b, a[0], base, u, r.tan(), if top { 0.0 } else { -t / r.cos() })]
        }
        _ => vec![Piece::new(b.clone(), b[0], base, [0.0, 0.0], 0.0, if top { 0.0 } else { -t })],
    }
}

fn roof_pieces(pr: &Project, e: &Value, top: bool) -> Vec<Piece> {
    let t = own_thickness(pr, e, "roof");
    let base = level_base(pr, e);
    if let Some(x) = e.get("extrusion").filter(|x| !x.is_null()) {
        return extrusion_pieces(x, base, t, top);
    }
    let var = type_name(pr, e).and_then(|n| variable_layer(pr, "roof", &n)).is_some();
    if numd(e, "slope", 30.0) == 0.0 && (top || !var) {
        if let Some(ps) = shaped_pieces(e, base, if top { t } else { 0.0 }) {
            return ps;
        }
    }
    let (faces, _) = super::roofs::roof_faces(pr, e);
    let mut out = Vec::new();
    for f in faces {
        if f.ring.len() < 3 {
            continue;
        }
        let lift = if top { t / f.slope.to_radians().cos() } else { 0.0 };
        out.push(Piece::new(f.ring, f.origin, f.z0, f.up, f.tan, lift));
    }
    out
}

/// An extrusion's pieces: between each two points of its profile, across from `from` to `to`
/// left of its line.
fn extrusion_pieces(x: &Value, base: f64, t: f64, top: bool) -> Vec<Piece> {
    let line = pts(x, "line").unwrap_or_default();
    let prof = pts(x, "profile").unwrap_or_default();
    if line.len() < 2 || geom::dist(line[0], line[1]) <= 0.0 {
        return Vec::new();
    }
    let from = numd(x, "from", 0.0);
    let to = numd(x, "to", 0.0);
    let a = line[0];
    let u = geom::unit(geom::sub(line[1], line[0]));
    let n = geom::left(u);
    let at = |s: f64, w: f64| geom::add(a, geom::add(geom::scale(u, s), geom::scale(n, w)));
    let mut out = Vec::new();
    for k in 0..prof.len().saturating_sub(1) {
        let (s0, h0) = (prof[k][0], prof[k][1]);
        let (s1, h1) = (prof[k + 1][0], prof[k + 1][1]);
        if s1 == s0 {
            continue;
        }
        let m = (h1 - h0) / (s1 - s0);
        let lift = if top { t / m.abs().atan().cos() } else { 0.0 };
        let ring = vec![at(s0, from), at(s1, from), at(s1, to), at(s0, to)];
        let up = if m < 0.0 { [-u[0], -u[1]] } else { u };
        out.push(Piece::new(ring, at(s0, from), base + h0, up, m.abs(), lift));
    }
    out
}

/// The surface's height at q (the first piece holding it), None off it.
pub fn z_at(ps: &[Piece], q: P2) -> Option<f64> {
    ps.iter().find(|p| p.holds(q)).map(|p| p.z_at(q))
}

/// The lowest (`low`) or highest a surface reaches over a polygon in plan, the parts of the polygon
/// off it taking `off`.
pub fn extreme_over(ps: &[Piece], poly: &[P2], low: bool, off: f64) -> f64 {
    let mut cands: Vec<P2> = poly.to_vec();
    let n = poly.len();
    for p in ps {
        let m = p.ring.len();
        for j in 0..m {
            let (b0, b1) = (p.ring[j], p.ring[(j + 1) % m]);
            if geom::inside_raw(poly, b0) {
                cands.push(b0);
            }
            for i in 0..n {
                if let Some((t, _)) = geom::seg_cross(poly[i], poly[(i + 1) % n], b0, b1) {
                    cands.push(geom::lerp(poly[i], poly[(i + 1) % n], t));
                }
            }
        }
    }
    // a point a little inside each corner tells a polygon reaching off the surface
    let mut best: Option<f64> = None;
    let mut take = |z: f64| {
        best = Some(match best {
            None => z,
            Some(b) => {
                if low {
                    b.min(z)
                } else {
                    b.max(z)
                }
            }
        })
    };
    let mut is_off = false;
    for q in &cands {
        match z_at(ps, *q) {
            Some(z) => take(z),
            None => is_off = true,
        }
    }
    if is_off {
        take(off);
    }
    best.unwrap_or(off)
}

/// The wall's footprint in plan: its centre line out to its faces, ends square (an arc's in
/// chords).
pub fn footprint(w: &super::walls::Wall) -> Vec<P2> {
    let h = w.thickness / 2.0;
    if w.is_arc() {
        let (s, e) = w.centre();
        let pts = crate::geom::graph::arc_points(s, e, w.arc, 1.0);
        let a = geom::Arc::new(s, e, w.arc);
        let out_of = |p: P2, d: f64| {
            let r = geom::unit(geom::sub(p, a.centre));
            geom::add(p, geom::scale(r, d))
        };
        let mut ring: Vec<P2> = pts.iter().map(|p| out_of(*p, h)).collect();
        ring.extend(pts.iter().rev().map(|p| out_of(*p, -h)));
        return ring;
    }
    let (s, e) = w.centre();
    let u = geom::unit(geom::sub(e, s));
    let n = geom::scale(geom::left(u), h);
    vec![geom::sub(s, n), geom::sub(e, n), geom::add(e, n), geom::add(s, n)]
}

/// An attached wall's base and top: the lowest the top of what its base is attached to reaches
/// over its footprint, the highest the underside of what its top is attached to reaches (parts
/// off it at its own base or top).
pub fn wall_heights(pr: &Project, w: &super::walls::Wall, e: &Value) -> (f64, f64) {
    let b0 = w.base(pr);
    let t0 = w.top(pr);
    let host = |k: &str| {
        e.get(k)
            .filter(|v| !v.is_null())
            .and_then(|v| by_ref(pr, v))
            .filter(|t| matches!(pr.category(*t), Some("roof") | Some("floor")))
            .and_then(|t| pr.el(t))
    };
    let (hb, ht) = (host("attach_base"), host("attach_top"));
    if hb.is_none() && ht.is_none() {
        return (b0, t0);
    }
    let poly = footprint(w);
    let base = match hb {
        Some(h) => extreme_over(&pieces(pr, h, true), &poly, true, b0),
        None => b0,
    };
    let top = match ht {
        Some(h) => extreme_over(&pieces(pr, h, false), &poly, false, t0),
        None => t0,
    };
    (base, top)
}

/// The height an attached wall has between two distances along it (on its centre line), the least
/// there: from what its base stands on (or its own base) up to what its top runs up to (or its own
/// top).
pub fn height_along(pr: &Project, w: &super::walls::Wall, e: &Value, s0: f64, s1: f64) -> f64 {
    let b0 = w.base(pr);
    let t0 = w.top(pr);
    let host = |k: &str| {
        e.get(k)
            .filter(|v| !v.is_null())
            .and_then(|v| by_ref(pr, v))
            .filter(|t| matches!(pr.category(*t), Some("roof") | Some("floor")))
            .and_then(|t| pr.el(t))
    };
    let (hb, ht) = (host("attach_base"), host("attach_top"));
    if hb.is_none() && ht.is_none() {
        return t0 - b0;
    }
    let pb = hb.map(|h| pieces(pr, h, true)).unwrap_or_default();
    let pt = ht.map(|h| pieces(pr, h, false)).unwrap_or_default();
    // the points along the centre line where either surface may bend
    let mut qs: Vec<P2> = Vec::new();
    if w.is_arc() {
        let (s, e2) = w.centre();
        let a = geom::Arc::new(s, e2, w.arc);
        let len = a.length().max(1e-9);
        let n = 32;
        for i in 0..=n {
            let t = (s0 + (s1 - s0) * i as f64 / n as f64) / len;
            let ang = a.a0 + a.sweep * t;
            qs.push([a.centre[0] + a.radius * ang.cos(), a.centre[1] + a.radius * ang.sin()]);
        }
    } else {
        let (cs, ce) = w.centre();
        let u = geom::unit(geom::sub(ce, cs));
        let q0 = geom::add(cs, geom::scale(u, s0));
        let q1 = geom::add(cs, geom::scale(u, s1));
        qs.push(q0);
        qs.push(q1);
        for p in pb.iter().chain(pt.iter()) {
            let m = p.ring.len();
            for j in 0..m {
                if let Some((t, _)) = geom::seg_cross(q0, q1, p.ring[j], p.ring[(j + 1) % m]) {
                    qs.push(geom::lerp(q0, q1, t));
                }
            }
        }
    }
    let mut best = f64::INFINITY;
    for q in qs {
        let top = if ht.is_some() { z_at(&pt, q).unwrap_or(t0) } else { t0 };
        let base = if hb.is_some() { z_at(&pb, q).unwrap_or(b0) } else { b0 };
        best = best.min(top - base);
    }
    best
}
