//! Constrained Delaunay triangulation of a region (an outline less its holes) with points inside
//! and lines it must keep as edges; corners welded within `TOL`, the predicates exact on a
//! 0.01 mm grid. Used by the shapes of floors and flat roofs.

use super::*;

/// Corners closer than this are one, mm.
pub const TOL: f64 = 0.01;

#[derive(Clone, Debug, Default)]
pub struct Triangulation {
    pub pts: Vec<P2>,
    /// Counter-clockwise triangles of the region, by corner index.
    pub tris: Vec<[usize; 3]>,
}

fn grid(p: P2) -> (i128, i128) {
    ((p[0] * 100.0).round() as i128, (p[1] * 100.0).round() as i128)
}

fn orient_i(a: (i128, i128), b: (i128, i128), c: (i128, i128)) -> i128 {
    (b.0 - a.0) * (c.1 - a.1) - (b.1 - a.1) * (c.0 - a.0)
}

/// > 0 when d is inside the circle through a, b, c (counter-clockwise).
fn incircle_i(a: (i128, i128), b: (i128, i128), c: (i128, i128), d: (i128, i128)) -> i128 {
    let (ax, ay) = (a.0 - d.0, a.1 - d.1);
    let (bx, by) = (b.0 - d.0, b.1 - d.1);
    let (cx, cy) = (c.0 - d.0, c.1 - d.1);
    let a2 = ax * ax + ay * ay;
    let b2 = bx * bx + by * by;
    let c2 = cx * cx + cy * cy;
    ax * (by * c2 - b2 * cy) - ay * (bx * c2 - b2 * cx) + a2 * (bx * cy - by * cx)
}

struct Mesh {
    g: Vec<(i128, i128)>,
    tris: Vec<[usize; 3]>,
    alive: Vec<bool>,
}

impl Mesh {
    fn edge_tris(&self, a: usize, b: usize) -> Vec<(usize, usize)> {
        // (triangle, index of the vertex opposite the edge)
        let mut out = Vec::new();
        for (t, tr) in self.tris.iter().enumerate() {
            if !self.alive[t] {
                continue;
            }
            for k in 0..3 {
                let u = tr[(k + 1) % 3];
                let v = tr[(k + 2) % 3];
                if (u == a && v == b) || (u == b && v == a) {
                    out.push((t, k));
                }
            }
        }
        out
    }

    /// Flips the edge a-b shared by two triangles into the other diagonal; false if it can't.
    fn flip(&mut self, a: usize, b: usize) -> bool {
        let et = self.edge_tris(a, b);
        if et.len() != 2 {
            return false;
        }
        let (t1, k1) = et[0];
        let (t2, k2) = et[1];
        let c = self.tris[t1][k1];
        let d = self.tris[t2][k2];
        // the quad a c b d must be convex for the flip
        let ga = self.g[a];
        let gb = self.g[b];
        let gc = self.g[c];
        let gd = self.g[d];
        let s1 = orient_i(gc, gd, ga);
        let s2 = orient_i(gc, gd, gb);
        if s1 == 0 || s2 == 0 || (s1 > 0) == (s2 > 0) {
            return false;
        }
        // new triangles c d a / d c b, counter-clockwise
        let mk = |p: usize, q: usize, r: usize, g: &Vec<(i128, i128)>| -> [usize; 3] {
            if orient_i(g[p], g[q], g[r]) > 0 {
                [p, q, r]
            } else {
                [p, r, q]
            }
        };
        self.tris[t1] = mk(c, d, a, &self.g);
        self.tris[t2] = mk(d, c, b, &self.g);
        true
    }
}

/// Where segments p-q and r-s cross in their interiors (exactly).
fn crosses(g: &[(i128, i128)], p: usize, q: usize, r: usize, s: usize) -> bool {
    if p == r || p == s || q == r || q == s {
        return false;
    }
    let d1 = orient_i(g[p], g[q], g[r]);
    let d2 = orient_i(g[p], g[q], g[s]);
    let d3 = orient_i(g[r], g[s], g[p]);
    let d4 = orient_i(g[r], g[s], g[q]);
    ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
}

/// The constrained Delaunay triangulation of the region.
pub fn constrained(outline: &[P2], holes: &[Vec<P2>], points: &[P2], lines: &[(P2, P2)]) -> Result<Triangulation, String> {
    // corners, welded
    let mut pts: Vec<P2> = Vec::new();
    let idx = |p: P2, pts: &mut Vec<P2>| -> usize {
        for (i, q) in pts.iter().enumerate() {
            if dist(*q, p) <= TOL {
                return i;
            }
        }
        pts.push(p);
        pts.len() - 1
    };
    let mut cons: Vec<(usize, usize)> = Vec::new();
    let mut rings: Vec<Vec<usize>> = Vec::new();
    for r in std::iter::once(outline).chain(holes.iter().map(|h| h.as_slice())) {
        let ids: Vec<usize> = r.iter().map(|p| idx(*p, &mut pts)).collect();
        rings.push(ids);
    }
    for p in points {
        idx(*p, &mut pts);
    }
    let mut line_ids = Vec::new();
    for (a, b) in lines {
        let ia = idx(*a, &mut pts);
        let ib = idx(*b, &mut pts);
        line_ids.push((ia, ib));
    }
    for r in &rings {
        let n = r.len();
        for i in 0..n {
            cons.push((r[i], r[(i + 1) % n]));
        }
    }
    cons.extend(line_ids.iter().copied());
    let n = pts.len();
    if n < 3 {
        return Err("too few corners".into());
    }
    let g: Vec<(i128, i128)> = pts.iter().map(|p| grid(*p)).collect();
    // constraint edges cut at corners lying on them (a split line bends through any point within
    // a millimetre of it)
    let ring_edges = cons.len() - line_ids.len();
    let mut cut: Vec<(usize, usize)> = Vec::new();
    for (ci, &(a, b)) in cons.iter().enumerate() {
        if a == b {
            continue;
        }
        let mut on: Vec<(f64, usize)> = Vec::new();
        for k in 0..n {
            if k == a || k == b {
                continue;
            }
            let d = sub(pts[b], pts[a]);
            let t = dot(sub(pts[k], pts[a]), d) / dot(d, d);
            let hit = if ci < ring_edges { orient_i(g[a], g[b], g[k]) == 0 } else { seg_dist(pts[a], pts[b], pts[k]) <= 1.0 };
            if hit && t > 0.0 && t < 1.0 {
                on.push((t, k));
            }
        }
        on.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
        let mut prev = a;
        for (_, k) in on {
            cut.push((prev, k));
            prev = k;
        }
        cut.push((prev, b));
    }
    // Bowyer-Watson over a super triangle, corners in order of x then y
    let (lo, hi) = bbox(&pts);
    let span = (hi[0] - lo[0]).max(hi[1] - lo[1]).max(1.0) * 100.0;
    let cx = (lo[0] + hi[0]) / 2.0;
    let cy = (lo[1] + hi[1]) / 2.0;
    let s0 = grid([cx - 20.0 * span, cy - 20.0 * span]);
    let s1 = grid([cx + 20.0 * span, cy - 20.0 * span]);
    let s2 = grid([cx, cy + 20.0 * span]);
    let mut gg = g.clone();
    gg.push(s0);
    gg.push(s1);
    gg.push(s2);
    let mut mesh = Mesh { g: gg, tris: vec![[n, n + 1, n + 2]], alive: vec![true] };
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|a, b| pts[*a][0].partial_cmp(&pts[*b][0]).unwrap().then(pts[*a][1].partial_cmp(&pts[*b][1]).unwrap()));
    for &p in &order {
        let gp = mesh.g[p];
        let mut bad: Vec<usize> = Vec::new();
        for (t, tr) in mesh.tris.iter().enumerate() {
            if !mesh.alive[t] {
                continue;
            }
            if incircle_i(mesh.g[tr[0]], mesh.g[tr[1]], mesh.g[tr[2]], gp) > 0 {
                bad.push(t);
            }
        }
        if bad.is_empty() {
            // on an edge or a corner: the triangles whose closed interior holds it
            for (t, tr) in mesh.tris.iter().enumerate() {
                if !mesh.alive[t] {
                    continue;
                }
                let o = [
                    orient_i(mesh.g[tr[0]], mesh.g[tr[1]], gp),
                    orient_i(mesh.g[tr[1]], mesh.g[tr[2]], gp),
                    orient_i(mesh.g[tr[2]], mesh.g[tr[0]], gp),
                ];
                if o.iter().all(|x| *x >= 0) {
                    bad.push(t);
                }
            }
        }
        // the hole's boundary: edges of bad triangles not shared by two of them
        let mut edges: Vec<(usize, usize)> = Vec::new();
        for &t in &bad {
            let tr = mesh.tris[t];
            for k in 0..3 {
                let e = (tr[k], tr[(k + 1) % 3]);
                if let Some(pos) = edges.iter().position(|x| *x == (e.1, e.0)) {
                    edges.remove(pos);
                } else {
                    edges.push(e);
                }
            }
        }
        for &t in &bad {
            mesh.alive[t] = false;
        }
        for (a, b) in edges {
            if orient_i(mesh.g[a], mesh.g[b], gp) > 0 {
                mesh.tris.push([a, b, p]);
                mesh.alive.push(true);
            }
        }
    }
    // the constraints brought in by flips
    let mut constrained_edges: Vec<(usize, usize)> = Vec::new();
    for &(a, b) in &cut {
        let mut guard = 0;
        loop {
            if !mesh.edge_tris(a, b).is_empty() {
                break;
            }
            // an edge crossing a-b
            let mut crossing: Option<(usize, usize)> = None;
            for (t, tr) in mesh.tris.iter().enumerate() {
                if !mesh.alive[t] {
                    continue;
                }
                for k in 0..3 {
                    let u = tr[k];
                    let v = tr[(k + 1) % 3];
                    if crosses(&mesh.g, a, b, u, v) && !constrained_edges.iter().any(|&(x, y)| (x == u && y == v) || (x == v && y == u)) {
                        crossing = Some((u, v));
                        break;
                    }
                }
                if crossing.is_some() {
                    break;
                }
            }
            let Some((u, v)) = crossing else { break };
            if !mesh.flip(u, v) {
                // try the others crossing first
                let mut done = false;
                let all: Vec<(usize, usize)> = mesh
                    .tris
                    .iter()
                    .enumerate()
                    .filter(|(t, _)| mesh.alive[*t])
                    .flat_map(|(_, tr)| (0..3).map(move |k| (tr[k], tr[(k + 1) % 3])))
                    .filter(|&(u2, v2)| crosses(&mesh.g, a, b, u2, v2))
                    .collect();
                for (u2, v2) in all {
                    if mesh.flip(u2, v2) {
                        done = true;
                        break;
                    }
                }
                if !done {
                    break;
                }
            }
            guard += 1;
            if guard > 100_000 {
                return Err("the triangulation gave up".into());
            }
        }
        constrained_edges.push((a, b));
    }
    // Lawson's flips, never across a constraint
    let mut changed = true;
    let mut guard = 0;
    while changed && guard < 10_000 {
        changed = false;
        guard += 1;
        let snapshot: Vec<[usize; 3]> = mesh.tris.iter().enumerate().filter(|(t, _)| mesh.alive[*t]).map(|(_, t)| *t).collect();
        for tr in snapshot {
            for k in 0..3 {
                let a = tr[k];
                let b = tr[(k + 1) % 3];
                if constrained_edges.iter().any(|&(x, y)| (x == a && y == b) || (x == b && y == a)) {
                    continue;
                }
                let et = mesh.edge_tris(a, b);
                if et.len() != 2 {
                    continue;
                }
                let (t1, k1) = et[0];
                let (t2, k2) = et[1];
                let c = mesh.tris[t1][k1];
                let d = mesh.tris[t2][k2];
                let t1v = mesh.tris[t1];
                if incircle_i(mesh.g[t1v[0]], mesh.g[t1v[1]], mesh.g[t1v[2]], mesh.g[d]) > 0 && mesh.flip(a, b) {
                    let _ = c;
                    changed = true;
                    break;
                }
            }
            if changed {
                break;
            }
        }
    }
    // the region's triangles: inside the outline and outside each hole
    let mut tris = Vec::new();
    for (t, tr) in mesh.tris.iter().enumerate() {
        if !mesh.alive[t] || tr.iter().any(|v| *v >= n) {
            continue;
        }
        let c = [
            (pts[tr[0]][0] + pts[tr[1]][0] + pts[tr[2]][0]) / 3.0,
            (pts[tr[0]][1] + pts[tr[1]][1] + pts[tr[2]][1]) / 3.0,
        ];
        if !inside_raw(outline, c) {
            continue;
        }
        if holes.iter().any(|h| inside_raw(h, c)) {
            continue;
        }
        tris.push(*tr);
    }
    Ok(Triangulation { pts, tris })
}

/// The number of planes the triangles make lifted to heights `z` (one per corner), neighbours
/// in one plane (within 0.01 mm at the corners they don't share) merged.
pub fn planes(t: &Triangulation, z: &[f64]) -> usize {
    plane_groups(t, z).len()
}

/// The triangles (by index) of each plane the lifted triangles make, as `planes` merges them:
/// the planes in the order of their first triangles, each's triangles in order.
pub fn plane_groups(t: &Triangulation, z: &[f64]) -> Vec<Vec<usize>> {
    let m = t.tris.len();
    let mut parent: Vec<usize> = (0..m).collect();
    fn find(p: &mut Vec<usize>, x: usize) -> usize {
        let mut r = x;
        while p[r] != r {
            r = p[r];
        }
        let mut y = x;
        while p[y] != r {
            let nx = p[y];
            p[y] = r;
            y = nx;
        }
        r
    }
    let plane_at = |tr: &[usize; 3], q: P2| -> f64 {
        let (a, b, c) = (t.pts[tr[0]], t.pts[tr[1]], t.pts[tr[2]]);
        let (za, zb, zc) = (z[tr[0]], z[tr[1]], z[tr[2]]);
        let den = orient(a, b, c);
        let l1 = orient(q, b, c) / den;
        let l2 = orient(a, q, c) / den;
        let l3 = 1.0 - l1 - l2;
        l1 * za + l2 * zb + l3 * zc
    };
    for i in 0..m {
        for j in i + 1..m {
            let a = t.tris[i];
            let b = t.tris[j];
            let shared: Vec<usize> = a.iter().filter(|v| b.contains(v)).copied().collect();
            if shared.len() != 2 {
                continue;
            }
            let other = *b.iter().find(|v| !shared.contains(v)).unwrap();
            let mine = *a.iter().find(|v| !shared.contains(v)).unwrap();
            let ok1 = (plane_at(&a, t.pts[other]) - z[other]).abs() <= 0.01;
            let ok2 = (plane_at(&b, t.pts[mine]) - z[mine]).abs() <= 0.01;
            if ok1 && ok2 {
                let ra = find(&mut parent, i);
                let rb = find(&mut parent, j);
                if ra != rb {
                    parent[ra.max(rb)] = ra.min(rb);
                }
            }
        }
    }
    let mut groups: Vec<(usize, Vec<usize>)> = Vec::new();
    for i in 0..m {
        let r = find(&mut parent, i);
        match groups.iter_mut().find(|g| g.0 == r) {
            Some(g) => g.1.push(i),
            None => groups.push((r, vec![i])),
        }
    }
    groups.into_iter().map(|g| g.1).collect()
}

/// The height the lifted triangles have at a point (None outside them).
pub fn height_at(t: &Triangulation, z: &[f64], q: P2) -> Option<f64> {
    for tr in &t.tris {
        let (a, b, c) = (t.pts[tr[0]], t.pts[tr[1]], t.pts[tr[2]]);
        let den = orient(a, b, c);
        if den == 0.0 {
            continue;
        }
        let l1 = orient(q, b, c) / den;
        let l2 = orient(a, q, c) / den;
        let l3 = 1.0 - l1 - l2;
        let e = -1e-9;
        if l1 >= e && l2 >= e && l3 >= e {
            return Some(l1 * z[tr[0]] + l2 * z[tr[1]] + l3 * z[tr[2]]);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn square_with_centre_and_diagonal_point() {
        let outline = vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 10000.0], [0.0, 10000.0]];
        let pts = vec![[5000.0, 5000.0], [2000.0, 8000.0]];
        let lines = vec![([5000.0, 5000.0], [2000.0, 8000.0])];
        let t = constrained(&outline, &[], &pts, &lines).unwrap();
        for tr in &t.tris {
            eprintln!("{:?} {:?} {:?}", t.pts[tr[0]], t.pts[tr[1]], t.pts[tr[2]]);
        }
        let z: Vec<f64> = t.pts.iter().map(|p| if *p == [5000.0, 5000.0] { -30.0 } else if *p == [2000.0, 8000.0] { -12.0 } else { 0.0 }).collect();
        eprintln!("planes {}", planes(&t, &z));
    }
}
