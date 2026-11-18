//! A stand-in for a room's boundary (ARCH owns the real thing), for the fields filters read: the
//! face of the walls' centre lines (and room separation lines) round the room's point, at its
//! level's computation height, its faces instead where the project measures at the finish, less
//! the columns standing in it. A room nothing encloses, or whose space a room before it has, is
//! unbounded: no area.

use crate::json::Value;
use crate::project::Project;
use crate::views::model as m;

type P = [f64; 2];

const TOL: f64 = 1e-3;

/// A room's area (m²) and perimeter (mm), None where it is unbounded.
pub fn measure(pr: &Project, id: u64) -> Option<(f64, f64)> {
    let e = pr.el(id)?;
    let face = face_of(pr, e)?;
    // a room before it in the same space keeps it
    let key = face_key(&face.pts);
    let level = e.get("level").and_then(|x| x.as_str()).unwrap_or("");
    for (oid, o) in &pr.elements {
        if *oid >= id {
            break;
        }
        if o.get("category").and_then(|c| c.as_str()) != Some("room") || o.get("level").and_then(|x| x.as_str()) != Some(level) {
            continue;
        }
        if let Some(f) = face_of(pr, o) {
            if face_key(&f.pts) == key {
                return None;
            }
        }
    }
    let finish = pr.get("room_area").and_then(|v| v.as_str()) == Some("finish");
    let pts = if finish { offset_face(&face) } else { face.pts.clone() };
    let mut area = polygon_area(&pts).abs();
    let mut perim = perimeter(&pts);
    for col in columns(pr, e) {
        let inter = clip_convex(&pts, &col);
        let a = polygon_area(&inter).abs();
        if a <= 1e-9 {
            continue;
        }
        area -= a;
        perim += boundary_inside(&col, &pts) - boundary_inside_convex(&pts, &col);
    }
    Some((area / 1e6, perim))
}

struct Face {
    pts: Vec<P>,
    /// How far each edge's wall face lies from it (half the wall's thickness; 0 for a separation
    /// line), edge i from pts[i] to pts[i + 1].
    half: Vec<f64>,
}

fn face_key(pts: &[P]) -> Vec<(i64, i64)> {
    let mut k: Vec<(i64, i64)> = pts.iter().map(|p| ((p[0] * 10.0).round() as i64, (p[1] * 10.0).round() as i64)).collect();
    k.sort();
    k
}

/// The lines that bound rooms at a room's level: walls the computation height cuts, and room
/// separation lines on the level; (from, to, half thickness).
fn bounding_lines(pr: &Project, e: &Value) -> Vec<(P, P, f64)> {
    let level = e.get("level").and_then(|x| x.as_str()).unwrap_or("").to_string();
    let lid = pr.find_guid(&level);
    let lv = lid.and_then(|l| pr.el(l));
    let z0 = lv.and_then(|l| l.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0);
    let ch = lv.and_then(|l| l.get("computation_height")).and_then(|x| x.as_f64()).unwrap_or(1200.0);
    let cut = z0 + ch;
    let mut out = Vec::new();
    for w in pr.elements.values() {
        match w.get("category").and_then(|c| c.as_str()) {
            Some("wall") => {
                if w.get("room_bounding").and_then(|b| b.as_bool()) == Some(false) {
                    continue;
                }
                let (base, top) = m::base_top(pr, w);
                if !(base <= cut + TOL && top >= cut - TOL) {
                    continue;
                }
                let half = m::wall_thickness(pr, w) / 2.0;
                let c = m::centre_line(pr, w);
                let pts = c.points(if c.is_arc() { 32 } else { 1 });
                for s in pts.windows(2) {
                    out.push((s[0], s[1], half));
                }
            }
            Some("roomseparator") => {
                if w.get("level").and_then(|x| x.as_str()) != Some(level.as_str()) {
                    continue;
                }
                let a = w.get("start").and_then(pt);
                let b = w.get("end").and_then(pt);
                if let (Some(a), Some(b)) = (a, b) {
                    out.push((a, b, 0.0));
                }
            }
            _ => {}
        }
    }
    out
}

fn pt(v: &Value) -> Option<P> {
    let a = v.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?])
}

/// The face of the bounding lines round a room's point (counter-clockwise), None where nothing
/// encloses it.
fn face_of(pr: &Project, e: &Value) -> Option<Face> {
    let p = e.get("point").and_then(pt)?;
    let lines = bounding_lines(pr, e);
    if lines.is_empty() {
        return None;
    }
    // split every line where another meets it
    let mut verts: Vec<P> = Vec::new();
    let vid = |verts: &mut Vec<P>, q: P| -> usize {
        if let Some(i) = verts.iter().position(|v| m::dist(*v, q) < TOL) {
            return i;
        }
        verts.push(q);
        verts.len() - 1
    };
    let mut edges: Vec<(usize, usize, f64)> = Vec::new();
    for (i, (a, b, h)) in lines.iter().enumerate() {
        let d = m::sub(*b, *a);
        let len2 = m::dot(d, d);
        if len2 < TOL * TOL {
            continue;
        }
        let mut ts: Vec<f64> = vec![0.0, 1.0];
        for (j, (c, dd, _)) in lines.iter().enumerate() {
            if i == j {
                continue;
            }
            for q in crossings(*a, *b, *c, *dd) {
                let t = m::dot(m::sub(q, *a), d) / len2;
                if t > -1e-9 && t < 1.0 + 1e-9 {
                    ts.push(t.clamp(0.0, 1.0));
                }
            }
        }
        ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
        let mut prev: Option<usize> = None;
        for t in ts {
            let q = m::add(*a, m::mul(d, t));
            let v = vid(&mut verts, q);
            if let Some(u) = prev {
                if u != v && !edges.iter().any(|(x, y, _)| (*x == u && *y == v) || (*x == v && *y == u)) {
                    edges.push((u, v, *h));
                }
            }
            prev = Some(v);
        }
    }
    // dangling lines bound nothing
    loop {
        let mut deg = vec![0usize; verts.len()];
        for (u, v, _) in &edges {
            deg[*u] += 1;
            deg[*v] += 1;
        }
        let before = edges.len();
        edges.retain(|(u, v, _)| deg[*u] > 1 && deg[*v] > 1);
        if edges.len() == before {
            break;
        }
    }
    // the edge nearest to the right of the point
    let mut best: Option<(f64, usize, bool)> = None;
    for (k, (u, v, _)) in edges.iter().enumerate() {
        let (a, b) = (verts[*u], verts[*v]);
        if (a[1] - p[1]) * (b[1] - p[1]) > 0.0 || (a[1] - b[1]).abs() < 1e-12 {
            continue;
        }
        let t = (p[1] - a[1]) / (b[1] - a[1]);
        let x = a[0] + t * (b[0] - a[0]);
        if x <= p[0] {
            continue;
        }
        let up = b[1] > a[1];
        if best.map(|(bx, _, _)| x < bx).unwrap_or(true) {
            best = Some((x, k, up));
        }
    }
    let (_, k, up) = best?;
    let (u0, v0) = if up { (edges[k].0, edges[k].1) } else { (edges[k].1, edges[k].0) };
    // walk the face that has the point on its left
    let angle = |from: usize, to: usize| {
        let d = m::sub(verts[to], verts[from]);
        d[1].atan2(d[0])
    };
    let half_of = |u: usize, v: usize| {
        edges.iter().find(|(x, y, _)| (*x == u && *y == v) || (*x == v && *y == u)).map(|e| e.2).unwrap_or(0.0)
    };
    let mut pts = vec![verts[u0]];
    let mut half = vec![half_of(u0, v0)];
    let (mut u, mut v) = (u0, v0);
    for _ in 0..(edges.len() * 2 + 4) {
        // the next edge clockwise from the way back
        let back = angle(v, u);
        let mut next: Option<(f64, usize)> = None;
        for (x, y, _) in &edges {
            let w = if *x == v {
                *y
            } else if *y == v {
                *x
            } else {
                continue;
            };
            if w == u {
                continue;
            }
            let mut turn = back - angle(v, w);
            while turn <= 1e-12 {
                turn += std::f64::consts::TAU;
            }
            if next.map(|(t, _)| turn < t).unwrap_or(true) {
                next = Some((turn, w));
            }
        }
        let w = next.map(|(_, w)| w).unwrap_or(u);
        if v == u0 && w == v0 {
            break;
        }
        pts.push(verts[v]);
        half.push(half_of(v, w));
        u = v;
        v = w;
        if pts.len() > edges.len() * 2 + 2 {
            return None;
        }
    }
    if polygon_area(&pts) <= 1e-6 || !inside(p, &pts) {
        return None;
    }
    Some(Face { pts, half })
}

/// Where two segments meet: a point, or the ends of either within the other where they overlap.
fn crossings(a: P, b: P, c: P, d: P) -> Vec<P> {
    let r = m::sub(b, a);
    let s = m::sub(d, c);
    let den = m::cross(r, s);
    let qp = m::sub(c, a);
    if den.abs() < 1e-12 {
        if m::cross(qp, r).abs() > 1e-6 * m::norm(r).max(1.0) {
            return Vec::new();
        }
        // collinear: the ends inside the other
        let mut out = Vec::new();
        for q in [c, d] {
            let t = m::dot(m::sub(q, a), r) / m::dot(r, r);
            if (-1e-9..=1.0 + 1e-9).contains(&t) {
                out.push(q);
            }
        }
        return out;
    }
    let t = m::cross(qp, s) / den;
    let u = m::cross(qp, r) / den;
    let eps = 1e-9;
    if t >= -eps && t <= 1.0 + eps && u >= -eps && u <= 1.0 + eps {
        vec![m::add(a, m::mul(r, t))]
    } else {
        Vec::new()
    }
}

/// The face moved to its walls' faces: each edge moved in by its half thickness, the corners
/// where the moved edges meet.
fn offset_face(f: &Face) -> Vec<P> {
    let n = f.pts.len();
    let lines: Vec<(P, P)> = (0..n)
        .map(|i| {
            let a = f.pts[i];
            let b = f.pts[(i + 1) % n];
            let nl = m::left_normal(a, b);
            (m::add(a, m::mul(nl, f.half[i])), m::add(b, m::mul(nl, f.half[i])))
        })
        .collect();
    (0..n)
        .map(|i| {
            let (a1, b1) = lines[(i + n - 1) % n];
            let (a2, b2) = lines[i];
            let r = m::sub(b1, a1);
            let s = m::sub(b2, a2);
            let den = m::cross(r, s);
            if den.abs() < 1e-9 {
                a2
            } else {
                let t = m::cross(m::sub(a2, a1), s) / den;
                m::add(a1, m::mul(r, t))
            }
        })
        .collect()
}

/// The columns standing in a room's space: their outlines (counter-clockwise).
fn columns(pr: &Project, e: &Value) -> Vec<Vec<P>> {
    let level = e.get("level").and_then(|x| x.as_str()).unwrap_or("");
    let lv = pr.find_guid(level).and_then(|l| pr.el(l));
    let z0 = lv.and_then(|l| l.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0);
    let ch = lv.and_then(|l| l.get("computation_height")).and_then(|x| x.as_f64()).unwrap_or(1200.0);
    let cut = z0 + ch;
    let mut out = Vec::new();
    for (id, c) in &pr.elements {
        if !matches!(c.get("category").and_then(|x| x.as_str()), Some("column") | Some("structuralcolumn")) {
            continue;
        }
        if c.get("room_bounding").and_then(|b| b.as_bool()) == Some(false) {
            continue;
        }
        let (base, top) = m::base_top(pr, c);
        if !(base <= cut + TOL && top >= cut - TOL) {
            continue;
        }
        // a round column bounds a room as a polygon of 24 sides
        let key = if c.get("category").and_then(|x| x.as_str()) == Some("structuralcolumn") { "structural_column" } else { "column" };
        let t = m::type_entry(pr, key, c);
        let round = t.and_then(|t| t.get("round")).and_then(|r| r.as_bool()).unwrap_or(false);
        let o = if round {
            let at = c.get("at").and_then(pt);
            let w = t.and_then(|t| t.get("width")).and_then(|x| x.as_f64()).unwrap_or(300.0);
            at.map(|at| {
                (0..24)
                    .map(|i| {
                        let a = i as f64 / 24.0 * std::f64::consts::TAU;
                        [at[0] + w / 2.0 * a.cos(), at[1] + w / 2.0 * a.sin()]
                    })
                    .collect::<Vec<P>>()
            })
        } else {
            m::outline(pr, *id)
        };
        if let Some(mut o) = o {
            if polygon_area(&o) < 0.0 {
                o.reverse();
            }
            out.push(o);
        }
    }
    out
}

pub fn polygon_area(pts: &[P]) -> f64 {
    let n = pts.len();
    let mut s = 0.0;
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    s / 2.0
}

fn perimeter(pts: &[P]) -> f64 {
    let n = pts.len();
    (0..n).map(|i| m::dist(pts[i], pts[(i + 1) % n])).sum()
}

fn inside(p: P, poly: &[P]) -> bool {
    let n = poly.len();
    let mut c = false;
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (poly[i], poly[j]);
        if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0] {
            c = !c;
        }
        j = i;
    }
    c
}

/// The polygon clipped to a convex one (Sutherland and Hodgman).
fn clip_convex(subject: &[P], clip: &[P]) -> Vec<P> {
    let mut out: Vec<P> = subject.to_vec();
    let n = clip.len();
    for i in 0..n {
        let (a, b) = (clip[i], clip[(i + 1) % n]);
        let inp = out.clone();
        out.clear();
        if inp.is_empty() {
            break;
        }
        let side = |p: P| m::cross(m::sub(b, a), m::sub(p, a));
        for j in 0..inp.len() {
            let cur = inp[j];
            let prev = inp[(j + inp.len() - 1) % inp.len()];
            let (sc, sp) = (side(cur), side(prev));
            if sc >= 0.0 {
                if sp < 0.0 {
                    out.push(m::add(prev, m::mul(m::sub(cur, prev), sp / (sp - sc))));
                }
                out.push(cur);
            } else if sp >= 0.0 {
                out.push(m::add(prev, m::mul(m::sub(cur, prev), sp / (sp - sc))));
            }
        }
    }
    out
}

/// How much of a polygon's boundary lies inside a convex one (strictly).
fn boundary_inside_convex(poly: &[P], convex: &[P]) -> f64 {
    let n = poly.len();
    let mut total = 0.0;
    for i in 0..n {
        let (a, b) = (poly[i], poly[(i + 1) % n]);
        // Cyrus and Beck
        let (mut t0, mut t1) = (0.0f64, 1.0f64);
        let d = m::sub(b, a);
        let mut out = false;
        for j in 0..convex.len() {
            let (c, e) = (convex[j], convex[(j + 1) % convex.len()]);
            let nrm = m::left_normal(c, e);
            let num = m::dot(nrm, m::sub(a, c));
            let den = m::dot(nrm, d);
            if den.abs() < 1e-12 {
                if num <= 1e-9 {
                    out = true;
                    break;
                }
                continue;
            }
            let t = -num / den;
            if den > 0.0 {
                t0 = t0.max(t);
            } else {
                t1 = t1.min(t);
            }
        }
        if !out && t1 > t0 {
            total += (t1 - t0) * m::norm(d);
        }
    }
    total
}

/// How much of one polygon's boundary lies inside another.
fn boundary_inside(poly: &[P], other: &[P]) -> f64 {
    let n = poly.len();
    let mut total = 0.0;
    for i in 0..n {
        let (a, b) = (poly[i], poly[(i + 1) % n]);
        let mut ts = vec![0.0, 1.0];
        let d = m::sub(b, a);
        for j in 0..other.len() {
            for q in crossings(a, b, other[j], other[(j + 1) % other.len()]) {
                ts.push(m::dot(m::sub(q, a), d) / m::dot(d, d));
            }
        }
        ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
        for w in ts.windows(2) {
            if w[1] - w[0] < 1e-9 {
                continue;
            }
            let mid = m::add(a, m::mul(d, (w[0] + w[1]) / 2.0));
            if inside(mid, other) && !on_boundary(mid, other) {
                total += (w[1] - w[0]) * m::norm(d);
            }
        }
    }
    total
}

fn on_boundary(p: P, poly: &[P]) -> bool {
    let n = poly.len();
    (0..n).any(|i| {
        let (a, b) = (poly[i], poly[(i + 1) % n]);
        let d = m::sub(b, a);
        let l = m::norm(d);
        if l < 1e-12 {
            return false;
        }
        let t = m::dot(m::sub(p, a), d) / (l * l);
        (-1e-9..=1.0 + 1e-9).contains(&t) && (m::cross(d, m::sub(p, a)) / l).abs() < 1e-6
    })
}
