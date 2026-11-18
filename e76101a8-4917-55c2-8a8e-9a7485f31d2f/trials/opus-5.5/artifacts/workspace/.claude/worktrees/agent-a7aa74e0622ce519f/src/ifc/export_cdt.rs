//! A constrained Delaunay triangulation of points in plan: the points swept in order (by x,
//! then y), each joined to the hull edges it sees and the new edges flipped until every circle
//! through a triangle is empty; then each constrained edge forced in (the triangles it crosses
//! taken out and the holes either side of it filled again), and the triangles outside the
//! region left out.

use super::geom::*;
use std::collections::HashMap;

pub fn orient(a: V2, b: V2, c: V2) -> f64 {
    (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
}

/// Positive when `d` is inside the circle through `a`, `b`, `c` (counter-clockwise).
pub fn incircle(a: V2, b: V2, c: V2, d: V2) -> f64 {
    let adx = a.x - d.x;
    let bdx = b.x - d.x;
    let cdx = c.x - d.x;
    let ady = a.y - d.y;
    let bdy = b.y - d.y;
    let cdy = c.y - d.y;
    let abdet = adx * bdy - bdx * ady;
    let bcdet = bdx * cdy - cdx * bdy;
    let cadet = cdx * ady - adx * cdy;
    let alift = adx * adx + ady * ady;
    let blift = bdx * bdx + bdy * bdy;
    let clift = cdx * cdx + cdy * cdy;
    alift * bcdet + blift * cadet + clift * abdet
}

struct Mesh<'a> {
    p: &'a [V2],
    tris: Vec<[usize; 3]>,
    alive: Vec<bool>,
    /// The triangle holding each directed edge.
    edge: HashMap<(usize, usize), usize>,
    fixed: std::collections::HashSet<(usize, usize)>,
}

impl<'a> Mesh<'a> {
    fn add(&mut self, a: usize, b: usize, c: usize) -> usize {
        let t = self.tris.len();
        self.tris.push([a, b, c]);
        self.alive.push(true);
        self.edge.insert((a, b), t);
        self.edge.insert((b, c), t);
        self.edge.insert((c, a), t);
        t
    }

    fn remove(&mut self, t: usize) {
        if !self.alive[t] {
            return;
        }
        self.alive[t] = false;
        let [a, b, c] = self.tris[t];
        for e in [(a, b), (b, c), (c, a)] {
            if self.edge.get(&e) == Some(&t) {
                self.edge.remove(&e);
            }
        }
    }

    /// The vertex across the edge `a`→`b` of its triangle.
    fn apex(&self, a: usize, b: usize) -> Option<usize> {
        let t = *self.edge.get(&(a, b))?;
        let [x, y, z] = self.tris[t];
        Some(if x != a && x != b {
            x
        } else if y != a && y != b {
            y
        } else {
            z
        })
    }

    /// Flips the edge `a`→`b` (its triangle `a, b, c`) while the point across it is inside
    /// the circle through that triangle, and the edges that come to face `c` after it.
    fn legalize(&mut self, a: usize, b: usize) {
        if self.fixed.contains(&(a, b)) || self.fixed.contains(&(b, a)) {
            return;
        }
        let Some(c) = self.apex(a, b) else { return };
        let Some(d) = self.apex(b, a) else { return };
        let p = self.p;
        if incircle(p[a], p[b], p[c], p[d]) <= 0.0 {
            return;
        }
        let t1 = self.edge[&(a, b)];
        let t2 = self.edge[&(b, a)];
        self.remove(t1);
        self.remove(t2);
        self.add(a, d, c);
        self.add(d, b, c);
        self.legalize(a, d);
        self.legalize(d, b);
    }
}

/// The triangles (each counter-clockwise) of points sorted by x, then y, with no two the same,
/// that keep the `constraints` as edges and lie inside `inside`.
pub fn triangulate(p: &[V2], constraints: &[(usize, usize)], inside: &dyn Fn(V2) -> bool) -> Vec<[usize; 3]> {
    let n = p.len();
    let mut m = Mesh { p, tris: Vec::new(), alive: Vec::new(), edge: HashMap::new(), fixed: Default::default() };
    if n < 3 {
        return Vec::new();
    }
    // the first point off the line of those before it
    let mut k = 2;
    while k < n && orient(p[0], p[1], p[k]) == 0.0 {
        k += 1;
    }
    if k == n {
        return Vec::new();
    }
    let mut hull: Vec<usize>;
    if orient(p[0], p[k - 1], p[k]) > 0.0 {
        for i in 0..k - 1 {
            m.add(i, i + 1, k);
        }
        hull = (0..=k).collect();
    } else {
        for i in 0..k - 1 {
            m.add(i + 1, i, k);
        }
        hull = (0..k).rev().collect();
        hull.push(k);
    }
    for q in k + 1..n {
        let h = hull.len();
        let vis: Vec<bool> = (0..h).map(|i| orient(p[hull[i]], p[hull[(i + 1) % h]], p[q]) < 0.0).collect();
        if !vis.iter().any(|v| *v) {
            continue;
        }
        // the run of edges it sees, from its first to its last
        let mut first = 0;
        while !(vis[first] && !vis[(first + h - 1) % h]) {
            first += 1;
        }
        let mut run = Vec::new();
        let mut i = first;
        while vis[i] {
            run.push(i);
            i = (i + 1) % h;
            if i == first {
                break;
            }
        }
        let mut bases = Vec::new();
        for &i in &run {
            let u = hull[i];
            let v = hull[(i + 1) % h];
            m.add(u, q, v);
            bases.push((v, u));
        }
        for (a, b) in bases {
            m.legalize(a, b);
        }
        // the hull: the run's inner corners give way to the new point
        let start = run[0];
        let end = (run[run.len() - 1] + 1) % h;
        let mut nh = Vec::with_capacity(h + 1);
        let mut j = end;
        loop {
            nh.push(hull[j]);
            if j == start {
                break;
            }
            j = (j + 1) % h;
        }
        nh.push(q);
        hull = nh;
    }
    for &(a, b) in constraints {
        insert_constraint(&mut m, a, b);
    }
    let mut out = Vec::new();
    for (t, tri) in m.tris.iter().enumerate() {
        if !m.alive[t] {
            continue;
        }
        let c = (p[tri[0]] + p[tri[1]] + p[tri[2]]) * (1.0 / 3.0);
        if inside(c) {
            out.push(*tri);
        }
    }
    out
}

fn insert_constraint(m: &mut Mesh, a: usize, b: usize) {
    if a == b {
        return;
    }
    if m.edge.contains_key(&(a, b)) || m.edge.contains_key(&(b, a)) {
        m.fixed.insert((a, b));
        return;
    }
    let p = m.p;
    // a point on the way splits it
    let d = p[b] - p[a];
    let len2 = d.dot(d);
    let mut on: Option<(f64, usize)> = None;
    for i in 0..p.len() {
        if i == a || i == b {
            continue;
        }
        let w = p[i] - p[a];
        let t = w.dot(d) / len2;
        if t <= 1e-12 || t >= 1.0 - 1e-12 {
            continue;
        }
        if (d.cross(w)).abs() / len2.sqrt() < 1e-9 && on.map(|o| t < o.0).unwrap_or(true) {
            on = Some((t, i));
        }
    }
    if let Some((_, c)) = on {
        insert_constraint(m, a, c);
        insert_constraint(m, c, b);
        return;
    }
    // the triangles the segment crosses, and the points either side of it (from a on)
    let mut crossed: Vec<usize> = Vec::new();
    let mut left: Vec<usize> = Vec::new();
    let mut right: Vec<usize> = Vec::new();
    // the triangle at a whose far edge the segment passes through
    let mut cur: Option<(usize, usize, usize)> = None;
    for (t, tri) in m.tris.iter().enumerate() {
        if !m.alive[t] {
            continue;
        }
        for r in 0..3 {
            if tri[r] != a {
                continue;
            }
            let u = tri[(r + 1) % 3];
            let v = tri[(r + 2) % 3];
            // u to the right of a→b, v to the left
            if orient(p[a], p[b], p[u]) < 0.0 && orient(p[a], p[b], p[v]) > 0.0 {
                cur = Some((t, u, v));
            }
        }
    }
    let Some((mut t, mut u, mut v)) = cur else { return };
    right.push(u);
    left.push(v);
    loop {
        crossed.push(t);
        // across the edge v→u (seen from the triangle a.. side: the edge u, v)
        let Some(&nt) = m.edge.get(&(v, u)) else { return };
        let w = m.apex(v, u).unwrap();
        if w == b {
            crossed.push(nt);
            break;
        }
        let o = orient(p[a], p[b], p[w]);
        if o > 0.0 {
            // w on the left: the segment goes on through u→w
            left.push(w);
            v = w;
        } else if o < 0.0 {
            right.push(w);
            u = w;
        } else {
            // through a point: never, the points on the way were taken first
            return;
        }
        t = nt;
    }
    for t in crossed {
        m.remove(t);
    }
    m.fixed.insert((a, b));
    // each side's points in order along the edge as seen from that side: the left's from a
    // to b, the right's from b to a
    let mut l = left;
    l.dedup();
    let mut r = right;
    r.dedup();
    r.reverse();
    fill(m, a, b, &l);
    fill(m, b, a, &r);
}

/// Triangulates the polygon of the edge `a`→`b` and the points `pts` (in order from a to b)
/// on its left: the point whose circle with `a` and `b` holds no other first, then each side.
fn fill(m: &mut Mesh, a: usize, b: usize, pts: &[usize]) {
    if pts.is_empty() {
        return;
    }
    let p = m.p;
    let mut ci = 0;
    for i in 1..pts.len() {
        if incircle(p[a], p[b], p[pts[ci]], p[pts[i]]) > 0.0 {
            ci = i;
        }
    }
    let c = pts[ci];
    m.add(a, b, c);
    fill(m, a, c, &pts[..ci]);
    fill(m, c, b, &pts[ci + 1..]);
}
