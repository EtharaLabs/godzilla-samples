//! A room's area and perimeter as its tag reads them: the region the room-bounding walls' centre
//! lines (or, with `room_area` at `finish`, their faces) and the room separators of its level
//! enclose round its point, less the columns standing in it at its level's computation height.

use super::super::common::*;
use crate::json::Value;
use crate::project::Project;

type P = [f64; 2];

fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
fn add(a: P, b: P) -> P {
    [a[0] + b[0], a[1] + b[1]]
}
fn mul(a: P, k: f64) -> P {
    [a[0] * k, a[1] * k]
}
fn cross(a: P, b: P) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
fn dot(a: P, b: P) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
fn dist(a: P, b: P) -> f64 {
    dot(sub(a, b), sub(a, b)).sqrt()
}
fn normalize(a: P) -> P {
    let l = dot(a, a).sqrt();
    if l == 0.0 {
        [0.0, 0.0]
    } else {
        mul(a, 1.0 / l)
    }
}
fn perp(a: P) -> P {
    [-a[1], a[0]]
}

const EPS: f64 = 1e-6;

/// A boundary segment and how far its face lies from it (half a wall's thickness; none for a
/// room separator).
#[derive(Clone, Copy)]
struct Seg {
    a: P,
    b: P,
    half: f64,
}

/// The height a level's rooms are found at (its computation height over it).
fn computation_z(pr: &Project, level: u64) -> f64 {
    let e = pr.el(level);
    let elev = e.and_then(|l| f_of(l, "elevation")).unwrap_or(0.0);
    elev + e.and_then(|l| f_of(l, "computation_height")).unwrap_or(1200.0)
}

fn boundaries(pr: &Project, level: u64) -> Vec<Seg> {
    let z = computation_z(pr, level);
    let mut out = Vec::new();
    for (_, e) in &pr.elements {
        match cat(e) {
            "wall" => {
                if e.get("room_bounding").and_then(|r| r.as_bool()) == Some(false) {
                    continue;
                }
                let (base, top) = super::super::model::base_top(pr, e);
                if !(base <= z && z < top) {
                    continue;
                }
                let half = super::super::model::wall_thickness(pr, e) / 2.0;
                let c = super::super::model::centre_line(pr, e);
                let pts = if c.is_arc() {
                    let (_, r) = c.circle().unwrap();
                    c.points(super::super::linework::plan::arc_chords(c.arc, r))
                } else {
                    vec![c.start, c.end]
                };
                for w in pts.windows(2) {
                    if dist(w[0], w[1]) > EPS {
                        out.push(Seg { a: w[0], b: w[1], half });
                    }
                }
            }
            "roomseparator" => {
                if ref_id(pr, e, "level") != Some(level) {
                    continue;
                }
                if let (Some(a), Some(b)) = (pt_of(e, "start"), pt_of(e, "end")) {
                    if dist(a, b) > EPS {
                        out.push(Seg { a, b, half: 0.0 });
                    }
                }
            }
            _ => {}
        }
    }
    out
}

/// The segments split wherever they cross or meet one another.
fn split_all(segs: &[Seg]) -> Vec<Seg> {
    let mut out = Vec::new();
    for (i, s) in segs.iter().enumerate() {
        let d = sub(s.b, s.a);
        let l2 = dot(d, d);
        let mut ts = vec![0.0, 1.0];
        for (j, o) in segs.iter().enumerate() {
            if i == j {
                continue;
            }
            let e = sub(o.b, o.a);
            let den = cross(d, e);
            if den.abs() > 1e-12 {
                let t = cross(sub(o.a, s.a), e) / den;
                let u = cross(sub(o.a, s.a), d) / den;
                if (-1e-9..=1.0 + 1e-9).contains(&t) && (-1e-9..=1.0 + 1e-9).contains(&u) {
                    ts.push(t.clamp(0.0, 1.0));
                }
            } else {
                // along the same line: the other's ends where they lie on this one
                for v in [o.a, o.b] {
                    if cross(sub(v, s.a), d).abs() / l2.sqrt() < EPS {
                        let t = dot(sub(v, s.a), d) / l2;
                        if (0.0..=1.0).contains(&t) {
                            ts.push(t);
                        }
                    }
                }
            }
        }
        ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
        ts.dedup_by(|x, y| (*x - *y).abs() * l2.sqrt() < EPS);
        for w in ts.windows(2) {
            let a = add(s.a, mul(d, w[0]));
            let b = add(s.a, mul(d, w[1]));
            if dist(a, b) > EPS {
                out.push(Seg { a, b, half: s.half });
            }
        }
    }
    out
}

struct Graph {
    pts: Vec<P>,
    /// Edges as (from, to, half) both ways.
    out: Vec<Vec<(usize, f64)>>,
}

fn graph(segs: &[Seg]) -> Graph {
    let mut pts: Vec<P> = Vec::new();
    let idx = |p: P, pts: &mut Vec<P>| -> usize {
        if let Some(i) = pts.iter().position(|q| dist(*q, p) < 1e-3) {
            return i;
        }
        pts.push(p);
        pts.len() - 1
    };
    let mut edges: Vec<(usize, usize, f64)> = Vec::new();
    for s in segs {
        let a = idx(s.a, &mut pts);
        let b = idx(s.b, &mut pts);
        if a == b {
            continue;
        }
        let (lo, hi) = (a.min(b), a.max(b));
        if !edges.iter().any(|(x, y, _)| *x == lo && *y == hi) {
            edges.push((lo, hi, s.half));
        }
    }
    let mut out = vec![Vec::new(); pts.len()];
    for (a, b, h) in edges {
        out[a].push((b, h));
        out[b].push((a, h));
    }
    Graph { pts, out }
}

/// The faces of the graph, each a cycle of (vertex, half thickness of the edge leaving it): the
/// bounded ones run counter-clockwise.
fn faces(g: &Graph) -> Vec<Vec<(usize, f64)>> {
    let mut used: std::collections::HashSet<(usize, usize)> = std::collections::HashSet::new();
    let mut out = Vec::new();
    for u in 0..g.pts.len() {
        for &(v, h) in &g.out[u] {
            if used.contains(&(u, v)) {
                continue;
            }
            let mut cycle = Vec::new();
            let (mut a, mut b, mut hh) = (u, v, h);
            let start = (u, v);
            loop {
                used.insert((a, b));
                cycle.push((a, hh));
                // at b, the edge turning least clockwise from the way back
                let back = sub(g.pts[a], g.pts[b]);
                let ab = back[1].atan2(back[0]);
                let mut best: Option<(f64, usize, f64)> = None;
                for &(w, hw) in &g.out[b] {
                    let d = sub(g.pts[w], g.pts[b]);
                    let aw = d[1].atan2(d[0]);
                    let mut cw = ab - aw;
                    while cw <= 1e-12 {
                        cw += std::f64::consts::TAU;
                    }
                    while cw > std::f64::consts::TAU + 1e-12 {
                        cw -= std::f64::consts::TAU;
                    }
                    if best.map(|(c, _, _)| cw < c).unwrap_or(true) {
                        best = Some((cw, w, hw));
                    }
                }
                let Some((_, w, hw)) = best else { break };
                a = b;
                b = w;
                hh = hw;
                if (a, b) == start || cycle.len() > 100_000 {
                    break;
                }
            }
            out.push(cycle);
        }
    }
    out
}

fn ring_area(r: &[P]) -> f64 {
    let n = r.len();
    let mut s = 0.0;
    for i in 0..n {
        s += cross(r[i], r[(i + 1) % n]);
    }
    s / 2.0
}

fn inside(p: P, poly: &[P]) -> bool {
    let n = poly.len();
    let mut c = false;
    let mut j = n - 1;
    for k in 0..n {
        let (a, b) = (poly[k], poly[j]);
        if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0] {
            c = !c;
        }
        j = k;
    }
    c
}

/// The face's outline moved in to the walls' faces: each edge moved left by its half thickness,
/// meeting the next where their lines do (round a wall's free end, across it).
fn inset(g: &Graph, cycle: &[(usize, f64)]) -> Vec<P> {
    let n = cycle.len();
    let mut lines: Vec<(P, P)> = Vec::new();
    for k in 0..n {
        let a = g.pts[cycle[k].0];
        let b = g.pts[cycle[(k + 1) % n].0];
        let left = perp(normalize(sub(b, a)));
        let h = cycle[k].1;
        lines.push((add(a, mul(left, h)), add(b, mul(left, h))));
    }
    let mut out = Vec::new();
    for k in 0..n {
        let (a0, a1) = lines[(k + n - 1) % n];
        let (b0, b1) = lines[k];
        let u = sub(a1, a0);
        let w = sub(b1, b0);
        let den = cross(u, w);
        if den.abs() < 1e-9 * dot(u, u).sqrt() * dot(w, w).sqrt() {
            if dot(u, w) < 0.0 {
                // turned back at a free end: across it
                out.push(a1);
                out.push(b0);
            } else {
                out.push(b0);
            }
            continue;
        }
        let s = cross(sub(b0, a0), w) / den;
        out.push(add(a0, mul(u, s)));
    }
    out
}

/// The outline of a column standing in a room at its computation height.
fn columns(pr: &Project, z: f64) -> Vec<Vec<P>> {
    let mut out = Vec::new();
    for (_, e) in &pr.elements {
        if !matches!(cat(e), "column" | "structuralcolumn") {
            continue;
        }
        let (base, top) = super::super::model::base_top(pr, e);
        if !(base <= z && z < top) {
            continue;
        }
        if let Some(r) = super::super::linework::plan::column_ring(pr, e) {
            let r = if ring_area(&r) < 0.0 { r.into_iter().rev().collect() } else { r };
            out.push(r);
        }
    }
    out
}

/// The parameters along a→b where it crosses a polygon's edges.
fn cuts(a: P, b: P, poly: &[P]) -> Vec<f64> {
    let d = sub(b, a);
    let mut ts = Vec::new();
    let n = poly.len();
    for k in 0..n {
        let p = poly[k];
        let q = poly[(k + 1) % n];
        let e = sub(q, p);
        let den = cross(d, e);
        if den.abs() < 1e-12 {
            continue;
        }
        let t = cross(sub(p, a), e) / den;
        let u = cross(sub(p, a), d) / den;
        if (0.0..=1.0).contains(&t) && (-1e-9..=1.0 + 1e-9).contains(&u) {
            ts.push(t);
        }
    }
    ts
}

/// Area (mm²) and perimeter (mm) of a region less some holes, from the pieces of their outlines
/// that bound what is left: the region's outside the holes as they run, the holes' inside the
/// region and outside the others turned back.
fn less_holes(region: &[P], holes: &[Vec<P>]) -> (f64, f64) {
    const PROBE: f64 = 1e-3;
    /// A ring's edges cut where the others' outlines cross them, each piece with the point just
    /// to its left and just to its right.
    fn pieces(ring: &[P], others: &[&Vec<P>]) -> Vec<(P, P, P, P)> {
        let n = ring.len();
        let mut out = Vec::new();
        for k in 0..n {
            let a = ring[k];
            let b = ring[(k + 1) % n];
            if dist(a, b) < EPS {
                continue;
            }
            let left = perp(normalize(sub(b, a)));
            let mut ts = vec![0.0, 1.0];
            for o in others {
                ts.extend(cuts(a, b, o));
                // the others' corners on it
                for v in o.iter() {
                    let d = sub(b, a);
                    let l2 = dot(d, d);
                    if cross(sub(*v, a), d).abs() / l2.sqrt() < EPS {
                        let t = dot(sub(*v, a), d) / l2;
                        if (0.0..=1.0).contains(&t) {
                            ts.push(t);
                        }
                    }
                }
            }
            ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
            for w in ts.windows(2) {
                if w[1] - w[0] < 1e-12 {
                    continue;
                }
                let p = add(a, mul(sub(b, a), w[0]));
                let q = add(a, mul(sub(b, a), w[1]));
                let m = add(a, mul(sub(b, a), (w[0] + w[1]) / 2.0));
                out.push((p, q, add(m, mul(left, PROBE)), sub(m, mul(left, PROBE))));
            }
        }
        out
    }
    let mut kept: Vec<(P, P)> = Vec::new();
    let hole_refs: Vec<&Vec<P>> = holes.iter().collect();
    // the region's outline where what lies inside it isn't a hole's
    for (a, b, l, _) in pieces(region, &hole_refs) {
        if !holes.iter().any(|h| inside(l, h)) {
            kept.push((a, b));
        }
    }
    let region_v = region.to_vec();
    let mut taken: Vec<(P, P)> = Vec::new();
    for (i, h) in holes.iter().enumerate() {
        let mut others: Vec<&Vec<P>> = holes.iter().enumerate().filter(|(j, _)| *j != i).map(|(_, x)| x).collect();
        others.push(&region_v);
        // a hole's outline where what lies outside it is the room's and no other hole's, once
        for (a, b, _, r) in pieces(h, &others) {
            if !inside(r, region) || holes.iter().enumerate().any(|(j, o)| j != i && inside(r, o)) {
                continue;
            }
            if taken.iter().any(|(x, y)| dist(*x, a) < EPS && dist(*y, b) < EPS) {
                continue;
            }
            taken.push((a, b));
            // it runs the other way round what is left
            kept.push((b, a));
        }
    }
    let area2: f64 = kept.iter().map(|(a, b)| cross(*a, *b)).sum();
    let per: f64 = kept.iter().map(|(a, b)| dist(*a, *b)).sum();
    (area2 / 2.0, per)
}

/// A room's area (m²) and perimeter (mm), measured as the project measures rooms; None for one
/// nothing encloses.
pub fn room_metrics(pr: &Project, id: u64) -> Option<(f64, f64)> {
    let e = pr.el(id)?;
    let level = ref_id(pr, e, "level")?;
    let point = pt_of(e, "point")?;
    let segs = split_all(&boundaries(pr, level));
    let g = graph(&segs);
    let mut best: Option<(f64, Vec<(usize, f64)>)> = None;
    for f in faces(&g) {
        let ring: Vec<P> = f.iter().map(|(v, _)| g.pts[*v]).collect();
        let a = ring_area(&ring);
        if a <= 0.0 || !inside(point, &ring) {
            continue;
        }
        if best.as_ref().map(|(ba, _)| a < *ba).unwrap_or(true) {
            best = Some((a, f));
        }
    }
    let (_, cycle) = best?;
    let finish = crate::styles::settings::room_area_of(pr) == "finish";
    let region: Vec<P> = if finish { inset(&g, &cycle) } else { cycle.iter().map(|(v, _)| g.pts[*v]).collect() };
    let holes = columns(pr, computation_z(pr, level));
    let (area, per) = less_holes(&region, &holes);
    Some((area / 1e6, per))
}

/// A room's height as Revit's: from its base over its level up to its upper limit and offset.
pub fn room_height(pr: &Project, e: &Value) -> f64 {
    let lv = super::super::model::level_elevation(pr, e, "level").unwrap_or(0.0);
    let base = lv + f_of(e, "base_offset").unwrap_or(0.0);
    match super::super::model::level_elevation(pr, e, "top_level") {
        Some(t) => t + f_of(e, "limit_offset").unwrap_or(0.0) - base,
        None => f_of(e, "height").unwrap_or(2500.0),
    }
}
