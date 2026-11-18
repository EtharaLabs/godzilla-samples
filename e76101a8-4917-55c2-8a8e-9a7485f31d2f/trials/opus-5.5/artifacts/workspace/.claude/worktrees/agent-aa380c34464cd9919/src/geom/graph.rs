//! The planar graph of lines in plan (wall centre lines, room separation lines): the lines split
//! where they cross or touch, their ends welded within a tolerance, and the faces they bound,
//! traced edge by edge as the original does (each edge's two sides in the order of its ends'
//! numbers, the lower-numbered end first).

use super::*;

/// How close two points are to count as one, mm.
pub const WELD: f64 = 1.0;

#[derive(Clone, Debug, Default)]
pub struct Graph {
    pub verts: Vec<P2>,
    /// Undirected edges, each from its lower-numbered end, in the order of their ends' numbers
    /// (vertices are numbered as the lines, start to end, come to them); half-edge 2i runs
    /// edges[i].0 to edges[i].1, 2i+1 back. `src[i]` is the line the edge came from.
    pub edges: Vec<(usize, usize)>,
    pub src: Vec<usize>,
}

#[derive(Clone, Debug)]
pub struct Face {
    /// Vertex indices round the face, starting where the tracing started.
    pub ring: Vec<usize>,
    /// The lines (sources) of its edges, one per edge.
    pub lines: Vec<usize>,
    pub area: f64,
}

impl Graph {
    fn vid(&mut self, p: P2, tol: f64) -> usize {
        for (i, v) in self.verts.iter().enumerate() {
            if dist(*v, p) <= tol {
                return i;
            }
        }
        self.verts.push(p);
        self.verts.len() - 1
    }

    /// The graph of segments (in order), split where they cross or touch.
    pub fn build(segs: &[(P2, P2)], tol: f64) -> Graph {
        let mut g = Graph::default();
        let n = segs.len();
        // first where a later line ends on an earlier one (not at its start: its foot on it), and
        // where two cross away from their ends (a point along the earlier line); ends meeting
        // ends are welded after
        for j in 0..n {
            for i in 0..j {
                let (a0, a1) = segs[i];
                let (b0, b1) = segs[j];
                let mut on = false;
                if !parallel(a0, a1, b0, b1) {
                    for q in [b0, b1] {
                        if let Some(f) = foot_inside(a0, a1, q, tol) {
                            g.vid(f, tol);
                            on = true;
                        }
                    }
                }
                if on {
                    continue;
                }
                if let Some(p) = crossing(a0, a1, b0, b1, tol) {
                    if [a0, a1, b0, b1].iter().all(|q| dist(p, *q) > tol) {
                        g.vid(p, tol);
                    }
                }
            }
        }
        for s in segs {
            g.vid(s.0, tol);
            g.vid(s.1, tol);
        }
        // each line cut at the vertices on it
        let mut chains: Vec<(usize, Vec<usize>)> = Vec::new();
        for (si, s) in segs.iter().enumerate() {
            let (a, b) = *s;
            let d = sub(b, a);
            let l2 = dot(d, d);
            if l2 <= 0.0 {
                continue;
            }
            let ia = g.vid(a, tol);
            let ib = g.vid(b, tol);
            let mut on: Vec<(f64, usize)> = Vec::new();
            for (vi, v) in g.verts.iter().enumerate() {
                if vi == ia || vi == ib {
                    continue;
                }
                let t = dot(sub(*v, a), d) / l2;
                if t <= 0.0 || t >= 1.0 {
                    continue;
                }
                if seg_dist(a, b, *v) <= tol {
                    on.push((t, vi));
                }
            }
            on.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal));
            let mut chain = vec![ia];
            for (_, vi) in on {
                if *chain.last().unwrap() != vi {
                    chain.push(vi);
                }
            }
            if *chain.last().unwrap() != ib {
                chain.push(ib);
            }
            chains.push((si, chain));
        }
        // the vertices numbered as the lines come to them, each edge once from its lower-numbered
        // end, the edges in the order of their ends' numbers (the line first drawing one keeps it)
        let mut new_id = vec![usize::MAX; g.verts.len()];
        let mut order: Vec<usize> = Vec::new();
        for (_, chain) in &chains {
            for &v in chain {
                if new_id[v] == usize::MAX {
                    new_id[v] = order.len();
                    order.push(v);
                }
            }
        }
        for v in 0..g.verts.len() {
            if new_id[v] == usize::MAX {
                new_id[v] = order.len();
                order.push(v);
            }
        }
        let verts: Vec<P2> = order.iter().map(|&v| g.verts[v]).collect();
        let mut keyed: std::collections::BTreeMap<(usize, usize), usize> = std::collections::BTreeMap::new();
        for (si, chain) in &chains {
            for w in chain.windows(2) {
                let (u, v) = (new_id[w[0]], new_id[w[1]]);
                if u == v {
                    continue;
                }
                keyed.entry((u.min(v), u.max(v))).or_insert(*si);
            }
        }
        g.verts = verts;
        for (k, si) in keyed {
            g.edges.push(k);
            g.src.push(si);
        }
        g
    }

    /// Each vertex's neighbours (by edge index), sorted by angle.
    fn fans(&self) -> Vec<Vec<(f64, usize, usize)>> {
        let mut out: Vec<Vec<(f64, usize, usize)>> = vec![Vec::new(); self.verts.len()];
        for (ei, &(a, b)) in self.edges.iter().enumerate() {
            let pa = self.verts[a];
            let pb = self.verts[b];
            out[a].push(((pb[1] - pa[1]).atan2(pb[0] - pa[0]), b, ei));
            out[b].push(((pa[1] - pb[1]).atan2(pa[0] - pb[0]), a, ei));
        }
        for o in out.iter_mut() {
            o.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal));
        }
        out
    }

    /// Every face, traced from each half-edge not yet walked, in the half-edges' order: at each
    /// vertex the walk takes the edge next clockwise from the one it came in by, so a bounded
    /// region comes out counter-clockwise and the outside of each connected part clockwise.
    pub fn faces(&self) -> Vec<Face> {
        let fans = self.fans();
        let m = self.edges.len();
        let mut used = vec![false; 2 * m];
        let mut faces = Vec::new();
        for h in 0..2 * m {
            if used[h] {
                continue;
            }
            let mut ring = Vec::new();
            let mut lines = Vec::new();
            let mut cur = h;
            let mut guard = 0;
            loop {
                used[cur] = true;
                let (a, b) = self.edges[cur / 2];
                let (u, v) = if cur % 2 == 0 { (a, b) } else { (b, a) };
                ring.push(u);
                lines.push(self.src[cur / 2]);
                // at v, the edge next clockwise from v→u
                let fan = &fans[v];
                let k = fan.iter().position(|x| x.2 == cur / 2 && x.1 == u).unwrap_or(0);
                let next = fan[(k + fan.len() - 1) % fan.len()];
                let ne = next.2;
                let (na, _) = self.edges[ne];
                cur = if na == v { 2 * ne } else { 2 * ne + 1 };
                guard += 1;
                if cur == h || guard > 4 * m + 4 {
                    break;
                }
            }
            let pts: Vec<P2> = ring.iter().map(|i| self.verts[*i]).collect();
            let a = area(&pts);
            faces.push(Face { ring, lines, area: a });
        }
        faces
    }

    pub fn pts(&self, ring: &[usize]) -> Vec<P2> {
        ring.iter().map(|i| self.verts[*i]).collect()
    }

    /// Which connected part each vertex is in.
    pub fn parts(&self) -> Vec<usize> {
        let n = self.verts.len();
        let mut p: Vec<usize> = (0..n).collect();
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
        for &(a, b) in &self.edges {
            let ra = find(&mut p, a);
            let rb = find(&mut p, b);
            if ra != rb {
                p[ra.max(rb)] = ra.min(rb);
            }
        }
        (0..n).map(|i| find(&mut p, i)).collect()
    }
}

/// Where the segments a and b cross or touch, as a point along b; None when they don't, or lie
/// along each other.
pub fn crossing(a0: P2, a1: P2, b0: P2, b1: P2, tol: f64) -> Option<P2> {
    let d = sub(a1, a0);
    let e = sub(b1, b0);
    let den = cross(d, e);
    let la = len(d);
    let lb = len(e);
    if la <= 0.0 || lb <= 0.0 {
        return None;
    }
    if den.abs() <= 1e-12 * la * lb {
        return None;
    }
    let w = sub(b0, a0);
    let t = cross(w, e) / den;
    let u = cross(w, d) / den;
    let _ = tol;
    if (0.0..=1.0).contains(&t) && (0.0..=1.0).contains(&u) {
        // the point along the earlier line
        Some([a0[0] + d[0] * t, a0[1] + d[1] * t])
    } else {
        None
    }
}

/// Whether two lines run the same way (or one has no length), as `crossing` takes them.
fn parallel(a0: P2, a1: P2, b0: P2, b1: P2) -> bool {
    let d = sub(a1, a0);
    let e = sub(b1, b0);
    let (la, lb) = (len(d), len(e));
    la <= 0.0 || lb <= 0.0 || cross(d, e).abs() <= 1e-12 * la * lb
}

/// The foot on line a0→a1 of a point within `tol` of it, past `tol` from its start and short of
/// its end.
fn foot_inside(a0: P2, a1: P2, q: P2, tol: f64) -> Option<P2> {
    let d = sub(a1, a0);
    let s = dot(sub(q, a0), d) / dot(d, d);
    if !(s > 0.0 && s < 1.0) || dist(q, a0) <= tol {
        return None;
    }
    let f = [a0[0] + d[0] * s, a0[1] + d[1] * s];
    if dist(f, q) > tol {
        return None;
    }
    Some(f)
}

/// Chords of an arc from a to b turning `deg` degrees, none further than `tol` from it: the
/// points along it, ends included.
pub fn arc_points(a: P2, b: P2, deg: f64, tol: f64) -> Vec<P2> {
    let arc = Arc::new(a, b, deg);
    let n = chord_count(arc.radius, arc.sweep, tol);
    let mut pts = Vec::with_capacity(n + 1);
    pts.push(a);
    for i in 1..n {
        let ang = arc.a0 + arc.sweep * i as f64 / n as f64;
        pts.push([arc.centre[0] + arc.radius * ang.cos(), arc.centre[1] + arc.radius * ang.sin()]);
    }
    let ang = arc.a0 + arc.sweep;
    pts.push([arc.centre[0] + arc.radius * ang.cos(), arc.centre[1] + arc.radius * ang.sin()]);
    pts
}

/// How many chords an arc of this radius and sweep takes to stay within `tol` of it.
pub fn chord_count(radius: f64, sweep: f64, tol: f64) -> usize {
    if !(radius > tol) {
        return 1.max((sweep.abs() / (std::f64::consts::PI / 2.0)).ceil() as usize);
    }
    let step = 2.0 * (1.0 - tol / radius).acos();
    let n = (sweep.abs() / step).ceil();
    if n.is_finite() && n >= 1.0 {
        (n as usize).min(100_000)
    } else {
        1
    }
}
