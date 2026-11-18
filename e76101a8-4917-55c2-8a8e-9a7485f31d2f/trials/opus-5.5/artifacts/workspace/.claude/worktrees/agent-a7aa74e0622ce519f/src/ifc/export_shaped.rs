//! Shaped floors and flat roofs (points raised or lowered, split lines): their surface
//! triangulated over their corners, their openings' and their points, the triangles that lie
//! in one plane joined into one face, and the solid between that surface and their underside
//! (the same surface lower, or level when a layer of their type is variable).

use super::cdt;
use super::geom::*;
use super::step::refs;
use super::Ex;
use crate::json::Value;

/// A face of the surface: its loops (the outer one counter-clockwise from its least corner,
/// then its holes), and the triangles it is made of.
#[derive(Clone, Debug)]
pub struct Face {
    pub loops: Vec<Vec<usize>>,
    pub tris: Vec<usize>,
}

/// The surface over a shaped outline.
#[derive(Clone, Debug)]
pub struct Shaped {
    /// Every corner, sorted by x, then y.
    pub pts: Vec<V2>,
    /// The height the shape gives each (0 for the corners it leaves alone).
    pub z: Vec<f64>,
    /// Each counter-clockwise from its least corner, sorted.
    pub tris: Vec<[usize; 3]>,
    pub faces: Vec<Face>,
    /// The edges round the outside and the openings, the region to their left, by their start.
    pub sides: Vec<(usize, usize)>,
}

fn pt_of(v: &Value) -> Option<V2> {
    let a = v.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some(v2(a[0].as_f64()?, a[1].as_f64()?))
}

/// Whether an element has a shape of its own: points or split lines.
pub fn has_shape(e: &Value) -> bool {
    let Some(s) = e.get("shape") else { return false };
    let n = |k: &str| s.get(k).and_then(|v| v.as_arr()).map(|a| a.len()).unwrap_or(0);
    n("points") > 0 || n("lines") > 0
}

fn point_in(p: V2, ring: &[V2]) -> bool {
    let n = ring.len();
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (ring[i], ring[j]);
        if (a.y > p.y) != (b.y > p.y) {
            let x = (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x;
            if p.x < x {
                inside = !inside;
            }
        }
        j = i;
    }
    inside
}

/// The plane through a triangle: its unit normal and a point on it.
fn plane_of(a: V3, b: V3, c: V3) -> (V3, V3) {
    let n = (b - a).cross(c - a);
    let l = n.length();
    (if l > 0.0 { n * (1.0 / l) } else { n }, a)
}

/// The surface of an outline with holes, under the shape's points and split lines.
pub fn build(boundary: &[V2], holes: &[Vec<V2>], points: &[(V2, f64)], lines: &[(V2, V2)]) -> Shaped {
    let mut all: Vec<V2> = Vec::new();
    all.extend(boundary.iter().cloned());
    for h in holes {
        all.extend(h.iter().cloned());
    }
    all.extend(points.iter().map(|p| p.0));
    all.sort_by(|a, b| a.x.partial_cmp(&b.x).unwrap().then(a.y.partial_cmp(&b.y).unwrap()));
    let mut pts: Vec<V2> = Vec::new();
    for p in all {
        if pts.last().map(|l| l.distance(p) < 1e-6).unwrap_or(false) {
            continue;
        }
        pts.push(p);
    }
    let index = |p: V2| -> usize { pts.iter().position(|q| q.distance(p) < 1e-6).unwrap_or(0) };
    let z: Vec<f64> = pts
        .iter()
        .map(|p| points.iter().rev().find(|s| s.0.distance(*p) < 1e-6).map(|s| s.1).unwrap_or(0.0))
        .collect();
    let mut cons: Vec<(usize, usize)> = Vec::new();
    for ring in std::iter::once(boundary).chain(holes.iter().map(|h| h.as_slice())) {
        let n = ring.len();
        for i in 0..n {
            let a = index(ring[i]);
            let b = index(ring[(i + 1) % n]);
            if a != b {
                cons.push((a, b));
            }
        }
    }
    for (a, b) in lines {
        cons.push((index(*a), index(*b)));
    }
    let inside = |p: V2| point_in(p, boundary) && !holes.iter().any(|h| point_in(p, h));
    let mut tris = cdt::triangulate(&pts, &cons, &inside);
    for t in tris.iter_mut() {
        let k = (0..3).min_by_key(|&k| t[k]).unwrap();
        *t = [t[k], t[(k + 1) % 3], t[(k + 2) % 3]];
    }
    tris.sort();
    // the triangles each directed edge belongs to
    let mut owner = std::collections::HashMap::new();
    for (i, t) in tris.iter().enumerate() {
        for k in 0..3 {
            owner.insert((t[k], t[(k + 1) % 3]), i);
        }
    }
    let p3 = |i: usize| v3(pts[i].x, pts[i].y, z[i]);
    let planes: Vec<(V3, V3)> = tris.iter().map(|t| plane_of(p3(t[0]), p3(t[1]), p3(t[2]))).collect();
    let mut group = vec![usize::MAX; tris.len()];
    let mut faces: Vec<Face> = Vec::new();
    for seed in 0..tris.len() {
        if group[seed] != usize::MAX {
            continue;
        }
        let g = faces.len();
        group[seed] = g;
        let (n0, a0) = planes[seed];
        let mut members = vec![seed];
        let mut stack = vec![seed];
        while let Some(t) = stack.pop() {
            let tri = tris[t];
            for k in 0..3 {
                let (u, v) = (tri[k], tri[(k + 1) % 3]);
                let Some(&o) = owner.get(&(v, u)) else { continue };
                if group[o] != usize::MAX {
                    continue;
                }
                let (n1, _) = planes[o];
                let w = tris[o].iter().cloned().find(|x| *x != u && *x != v).unwrap();
                if (n1 - n0).length() < 1e-9 && n0.dot(p3(w) - a0).abs() < 1e-6 {
                    group[o] = g;
                    members.push(o);
                    stack.push(o);
                }
            }
        }
        members.sort();
        // its edges no other of its triangles shares, chained into loops
        let mut edges: Vec<(usize, usize)> = Vec::new();
        for &t in &members {
            let tri = tris[t];
            for k in 0..3 {
                let (u, v) = (tri[k], tri[(k + 1) % 3]);
                let inner = owner.get(&(v, u)).map(|o| group[*o] == g).unwrap_or(false);
                if !inner {
                    edges.push((u, v));
                }
            }
        }
        edges.sort();
        let mut loops = Vec::new();
        while !edges.is_empty() {
            let (s, mut cur) = edges.remove(0);
            let mut lp = vec![s];
            while cur != s {
                lp.push(cur);
                let Some(i) = edges.iter().position(|e| e.0 == cur) else { break };
                cur = edges.remove(i).1;
            }
            loops.push(lp);
        }
        faces.push(Face { loops, tris: members });
    }
    let mut sides: Vec<(usize, usize)> = Vec::new();
    for t in &tris {
        for k in 0..3 {
            let (u, v) = (t[k], t[(k + 1) % 3]);
            if !owner.contains_key(&(v, u)) {
                sides.push((u, v));
            }
        }
    }
    sides.sort();
    Shaped { pts, z, tris, faces, sides }
}

/// An element's shape: its points (where, how high) and its split lines.
pub fn shape_of(e: &Value) -> (Vec<(V2, f64)>, Vec<(V2, V2)>) {
    let mut points = Vec::new();
    let mut lines = Vec::new();
    if let Some(s) = e.get("shape") {
        for p in s.get("points").and_then(|v| v.as_arr()).map(|a| a.as_slice()).unwrap_or(&[]) {
            if let Some(at) = p.get("at").and_then(pt_of) {
                points.push((at, p.get("z").and_then(|v| v.as_f64()).unwrap_or(0.0)));
            }
        }
        for l in s.get("lines").and_then(|v| v.as_arr()).map(|a| a.as_slice()).unwrap_or(&[]) {
            if let (Some(a), Some(b)) = (l.get("a").and_then(pt_of), l.get("b").and_then(pt_of)) {
                lines.push((a, b));
            }
        }
    }
    (points, lines)
}

impl Shaped {
    /// The volume between two heights at each corner, triangle by triangle.
    pub fn volume(&self, top: &[f64], bottom: &[f64]) -> f64 {
        let mut v = 0.0;
        for t in &self.tris {
            let (a, b, c) = (self.pts[t[0]], self.pts[t[1]], self.pts[t[2]]);
            let area = (b - a).cross(c - a) / 2.0;
            let h = (top[t[0]] - bottom[t[0]]) + (top[t[1]] - bottom[t[1]]) + (top[t[2]] - bottom[t[2]]);
            v += area * h / 3.0;
        }
        v
    }

    /// Each face's outer loop in plan and the plane through it, its height at a point: for
    /// the walls that follow it.
    pub fn face_planes(&self, z: &[f64]) -> Vec<(Vec<V2>, [f64; 3])> {
        let mut out = Vec::new();
        for f in &self.faces {
            let t = self.tris[f.tris[0]];
            let p = |i: usize| v3(self.pts[i].x, self.pts[i].y, z[i]);
            let (a, b, c) = (p(t[0]), p(t[1]), p(t[2]));
            let n = (b - a).cross(c - a);
            // z = a.z - (n.x (x - a.x) + n.y (y - a.y)) / n.z
            let kx = -n.x / n.z;
            let ky = -n.y / n.z;
            let z0 = a.z - kx * a.x - ky * a.y;
            let ring: Vec<V2> = f.loops[0].iter().map(|i| self.pts[*i]).collect();
            out.push((ring, [z0, kx, ky]));
        }
        out
    }
}

impl<'a> Ex<'a> {
    /// A closed faceted Brep between the surface at `top` and at `bottom` (a height for each
    /// corner): each face's top and its underside (turned down), then the sides.
    pub fn shaped_brep(&mut self, s: &Shaped, top: &[f64], bottom: &[f64]) -> usize {
        let t: Vec<usize> = s.pts.iter().zip(top.iter()).map(|(p, z)| self.st.point3(p.x, p.y, *z)).collect();
        let b: Vec<usize> = s.pts.iter().zip(bottom.iter()).map(|(p, z)| self.st.point3(p.x, p.y, *z)).collect();
        let mut faces = Vec::new();
        for f in &s.faces {
            let up: Vec<Vec<usize>> = f.loops.iter().map(|l| l.iter().map(|i| t[*i]).collect()).collect();
            faces.push(self.face_with_holes(&up));
            let down: Vec<Vec<usize>> = f.loops.iter().map(|l| l.iter().rev().map(|i| b[*i]).collect()).collect();
            faces.push(self.face_with_holes(&down));
        }
        for &(u, v) in &s.sides {
            faces.push(self.face(&[b[u], b[v], t[v], t[u]]));
        }
        let shell = self.add(format!("IFCCLOSEDSHELL(({}))", refs(&faces)));
        self.add(format!("IFCFACETEDBREP(#{})", shell))
    }

    /// A face of loops over points written already: the first its outer bound.
    pub fn face_with_holes(&mut self, loops: &[Vec<usize>]) -> usize {
        let mut bounds = Vec::new();
        for (k, l) in loops.iter().enumerate() {
            let lp = self.add(format!("IFCPOLYLOOP(({}))", refs(l)));
            bounds.push(if k == 0 {
                self.add(format!("IFCFACEOUTERBOUND(#{},.T.)", lp))
            } else {
                self.add(format!("IFCFACEBOUND(#{},.T.)", lp))
            });
        }
        self.add(format!("IFCFACE(({}))", refs(&bounds)))
    }

    /// Whether a type of a category has a variable layer.
    pub fn variable_type(&self, cat: &str, tg: &str) -> bool {
        super::walls::type_data(self.pr, cat, tg)
            .and_then(|t| t.get("layers"))
            .and_then(|l| l.as_arr())
            .map(|a| a.iter().any(|l| l.get("variable").and_then(|v| v.as_bool()).unwrap_or(false)))
            .unwrap_or(false)
    }
}
