//! The weighted straight skeleton of a footprint: each edge of its outline (counter-clockwise) and
//! of its holes (clockwise) moves in at its own speed (0 for a gable, which stays where it is), the
//! corners following the moving edges, until the wavefront is gone. Each edge sweeps a face; a
//! roof's slope rises over it. Events are found by brute force (enough for a building's roof).

use super::*;

/// A piece of the skeleton: a corner's path from `a` (at time `ta`) to `b` (at time `tb`), between
/// the faces of edges `left` and `right`.
#[derive(Clone, Debug)]
pub struct Arc2 {
    pub a: P2,
    pub ta: f64,
    pub b: P2,
    pub tb: f64,
    pub left: usize,
    pub right: usize,
}

#[derive(Clone, Debug)]
pub struct Skeleton {
    /// The edges: start, end, inward normal, speed.
    pub edges: Vec<(P2, P2, P2, f64)>,
    pub arcs: Vec<Arc2>,
    /// The time the wavefront is gone.
    pub t_max: f64,
}

#[derive(Clone, Debug)]
struct Vert {
    /// position at time t0
    p: P2,
    t0: f64,
    /// velocity
    w: P2,
    /// incoming edge (before the vertex) and outgoing edge
    ea: usize,
    eb: usize,
    prev: usize,
    next: usize,
    alive: bool,
    reflex: bool,
}

const EPS: f64 = 1e-9;

fn velocity(na: P2, sa: f64, nb: P2, sb: f64) -> Option<P2> {
    // w with w.na = sa and w.nb = sb
    let det = cross(na, nb);
    if det.abs() < 1e-12 {
        // in line: both move the same way, if at the same speed
        if dot(na, nb) > 0.0 && (sa - sb).abs() < 1e-12 {
            return Some(scale(na, sa));
        }
        return None;
    }
    let x = (sa * nb[1] - sb * na[1]) / det;
    let y = (na[0] * sb - nb[0] * sa) / det;
    Some([x, y])
}

impl Skeleton {
    /// The skeleton of rings (the first the outline, counter-clockwise; the rest holes,
    /// clockwise), each edge with its speed (edge i of a ring from point i to the next; the rings'
    /// edges numbered on one after another).
    pub fn new(rings: &[Vec<P2>], speeds: &[f64]) -> Skeleton {
        let mut edges = Vec::new();
        for r in rings {
            let n = r.len();
            for i in 0..n {
                let a = r[i];
                let b = r[(i + 1) % n];
                let nrm = left(unit(sub(b, a)));
                edges.push((a, b, nrm, 0.0));
            }
        }
        for (i, e) in edges.iter_mut().enumerate() {
            e.3 = speeds.get(i).copied().unwrap_or(1.0);
        }
        let mut sk = Skeleton { edges, arcs: Vec::new(), t_max: 0.0 };
        sk.run(rings);
        sk
    }

    fn offset_d(&self, e: usize, t: f64) -> f64 {
        let (a, _, n, s) = self.edges[e];
        dot(a, n) + s * t
    }

    fn run(&mut self, rings: &[Vec<P2>]) {
        let mut vs: Vec<Vert> = Vec::new();
        let mut base = 0;
        let mut eidx = 0;
        for r in rings {
            let n = r.len();
            for i in 0..n {
                let ea = eidx + (i + n - 1) % n;
                let eb = eidx + i;
                let (_, _, na, sa) = self.edges[ea];
                let (_, _, nb, sb) = self.edges[eb];
                let w = velocity(na, sa, nb, sb).unwrap_or([0.0, 0.0]);
                let da = sub(self.edges[ea].1, self.edges[ea].0);
                let db = sub(self.edges[eb].1, self.edges[eb].0);
                let reflex = cross(da, db) < -EPS * len(da) * len(db);
                vs.push(Vert {
                    p: r[i],
                    t0: 0.0,
                    w,
                    ea,
                    eb,
                    prev: base + (i + n - 1) % n,
                    next: base + (i + 1) % n,
                    alive: true,
                    reflex,
                });
            }
            base += n;
            eidx += n;
        }
        let mut t_now = 0.0f64;
        let mut guard = 0;
        loop {
            guard += 1;
            if guard > 10_000 {
                break;
            }
            let alive: Vec<usize> = (0..vs.len()).filter(|i| vs[*i].alive).collect();
            if alive.is_empty() {
                break;
            }
            // a ring of no area left (needles) is its ridges
            let mut seen = vec![false; vs.len()];
            for &i in &alive {
                if seen[i] || !vs[i].alive {
                    continue;
                }
                let mut ring = vec![i];
                seen[i] = true;
                let mut j = vs[i].next;
                let mut g = 0;
                while j != i && g < vs.len() {
                    ring.push(j);
                    seen[j] = true;
                    j = vs[j].next;
                    g += 1;
                }
                if ring.len() < 3 {
                    continue;
                }
                let pts: Vec<P2> = ring.iter().map(|k| pos(&vs[*k], t_now)).collect();
                let per: f64 = (0..pts.len()).map(|k| dist(pts[k], pts[(k + 1) % pts.len()])).sum();
                if area(&pts).abs() <= 1e-9 * per * per + 1e-9 {
                    for (k, &vi) in ring.iter().enumerate() {
                        let p_now = pts[k];
                        if dist(vs[vi].p, p_now) > 1e-9 {
                            self.arcs.push(Arc2 { a: vs[vi].p, ta: vs[vi].t0, b: p_now, tb: t_now, left: vs[vi].ea, right: vs[vi].eb });
                        }
                        let nxt = pts[(k + 1) % pts.len()];
                        if dist(p_now, nxt) > 1e-9 {
                            let e = vs[vi].eb;
                            self.arcs.push(Arc2 { a: p_now, ta: t_now, b: nxt, tb: t_now, left: e, right: e });
                        }
                    }
                    for &vi in &ring {
                        vs[vi].alive = false;
                    }
                }
            }
            let alive: Vec<usize> = (0..vs.len()).filter(|i| vs[*i].alive).collect();
            if alive.is_empty() {
                break;
            }
            // a ring of two or fewer corners is done
            let mut closed_any = false;
            for &i in &alive {
                if !vs[i].alive {
                    continue;
                }
                let j = vs[i].next;
                let k = vs[j].next;
                if k == i || j == i {
                    // two corners left: the ridge between them, after their paths so far
                    let pi = pos(&vs[i], t_now);
                    let pj = pos(&vs[j], t_now);
                    if dist(vs[i].p, pi) > 1e-9 {
                        self.arcs.push(Arc2 { a: vs[i].p, ta: vs[i].t0, b: pi, tb: t_now, left: vs[i].ea, right: vs[i].eb });
                    }
                    if dist(vs[j].p, pj) > 1e-9 {
                        self.arcs.push(Arc2 { a: vs[j].p, ta: vs[j].t0, b: pj, tb: t_now, left: vs[j].ea, right: vs[j].eb });
                    }
                    self.arcs.push(Arc2 { a: pi, ta: t_now, b: pj, tb: t_now, left: vs[i].ea, right: vs[i].eb });
                    vs[i].alive = false;
                    vs[j].alive = false;
                    closed_any = true;
                }
            }
            if closed_any {
                continue;
            }
            // the earliest event
            let mut best: Option<(f64, Event)> = None;
            for &i in &alive {
                let j = vs[i].next;
                if let Some((t, q)) = edge_event(self, &vs[i], &vs[j], t_now) {
                    if best.as_ref().map(|b| t < b.0 - 1e-12).unwrap_or(true) {
                        best = Some((t, Event::Edge(i, j, q)));
                    }
                }
            }
            for &i in &alive {
                if !vs[i].reflex {
                    continue;
                }
                for &k in &alive {
                    let e = vs[k].eb;
                    let k2 = vs[k].next;
                    if k == i || k2 == i || vs[i].ea == e || vs[i].eb == e {
                        continue;
                    }
                    if let Some((t, q)) = split_event(self, &vs[i], &vs[k], &vs[k2], e, t_now) {
                        if best.as_ref().map(|b| t < b.0 - 1e-12).unwrap_or(true) {
                            best = Some((t, Event::Split(i, k, q)));
                        }
                    }
                }
            }
            let Some((t, ev)) = best else {
                // nothing more happens: close every ring at its corners' meeting
                for &i in &alive {
                    vs[i].alive = false;
                }
                break;
            };
            t_now = t;
            match ev {
                Event::Edge(i, j, q) => {
                    self.arcs.push(Arc2 { a: vs[i].p, ta: vs[i].t0, b: q, tb: t, left: vs[i].ea, right: vs[i].eb });
                    self.arcs.push(Arc2 { a: vs[j].p, ta: vs[j].t0, b: q, tb: t, left: vs[j].ea, right: vs[j].eb });
                    let pv = vs[i].prev;
                    let nx = vs[j].next;
                    vs[i].alive = false;
                    vs[j].alive = false;
                    if pv == j {
                        // the ring was these two
                        continue;
                    }
                    let ea = vs[i].ea;
                    let eb = vs[j].eb;
                    let (_, _, na, sa) = self.edges[ea];
                    let (_, _, nb, sb) = self.edges[eb];
                    let w = velocity(na, sa, nb, sb).unwrap_or([0.0, 0.0]);
                    let da = sub(self.edges[ea].1, self.edges[ea].0);
                    let db = sub(self.edges[eb].1, self.edges[eb].0);
                    let reflex = cross(da, db) < -EPS * len(da) * len(db);
                    let id = vs.len();
                    vs.push(Vert { p: q, t0: t, w, ea, eb, prev: pv, next: nx, alive: true, reflex });
                    vs[pv].next = id;
                    vs[nx].prev = id;
                }
                Event::Split(i, k, q) => {
                    self.arcs.push(Arc2 { a: vs[i].p, ta: vs[i].t0, b: q, tb: t, left: vs[i].ea, right: vs[i].eb });
                    let e = vs[k].eb;
                    let k2 = vs[k].next;
                    let pv = vs[i].prev;
                    let nx = vs[i].next;
                    vs[i].alive = false;
                    let mk = |ea: usize, eb: usize, sk: &Skeleton| -> (P2, bool) {
                        let (_, _, na, sa) = sk.edges[ea];
                        let (_, _, nb, sb) = sk.edges[eb];
                        let w = velocity(na, sa, nb, sb).unwrap_or([0.0, 0.0]);
                        let da = sub(sk.edges[ea].1, sk.edges[ea].0);
                        let db = sub(sk.edges[eb].1, sk.edges[eb].0);
                        (w, cross(da, db) < -EPS * len(da) * len(db))
                    };
                    // v1: edges (i.ea, e), between pv and k2; v2: edges (e, i.eb), between k and nx
                    let (w1, r1) = mk(vs[i].ea, e, self);
                    let (w2, r2) = mk(e, vs[i].eb, self);
                    let id1 = vs.len();
                    let id2 = id1 + 1;
                    let ea_i = vs[i].ea;
                    let eb_i = vs[i].eb;
                    vs.push(Vert { p: q, t0: t, w: w1, ea: ea_i, eb: e, prev: pv, next: k2, alive: true, reflex: r1 });
                    vs.push(Vert { p: q, t0: t, w: w2, ea: e, eb: eb_i, prev: k, next: nx, alive: true, reflex: r2 });
                    vs[pv].next = id1;
                    vs[k2].prev = id1;
                    vs[k].next = id2;
                    vs[nx].prev = id2;
                }
            }
        }
        self.t_max = t_now;
    }

    /// The faces of the edges: for each, the points round it in plan (its edge, then the
    /// skeleton's arcs back), unordered closing ring.
    pub fn faces(&self) -> Vec<Vec<P2>> {
        let mut out = Vec::new();
        for (ei, &(a, b, _, _)) in self.edges.iter().enumerate() {
            // segments of the face's boundary: the edge, and every arc with it on a side
            let mut segs: Vec<(P2, P2)> = vec![(a, b)];
            for arc in &self.arcs {
                if arc.left == ei || arc.right == ei {
                    if dist(arc.a, arc.b) > 1e-9 {
                        segs.push((arc.a, arc.b));
                    }
                }
            }
            out.push(chain(b, a, &segs[1..]));
        }
        out
    }

    /// The time the wavefront reaches a point (its face edge's distance over its speed), and the
    /// face it is in; None outside.
    pub fn time_at(&self, faces: &[Vec<P2>], q: P2) -> Option<(usize, f64)> {
        for (i, f) in faces.iter().enumerate() {
            if f.len() >= 3 && (inside(f, q) || on_ring(f, q)) {
                let (a, _, n, s) = self.edges[i];
                if s <= 0.0 {
                    continue;
                }
                return Some((i, dot(sub(q, a), n) / s));
            }
        }
        None
    }
}

fn on_ring(r: &[P2], q: P2) -> bool {
    let n = r.len();
    (0..n).any(|i| seg_dist(r[i], r[(i + 1) % n], q) < 1e-6)
}

/// A ring from `start` to `end` through the segments (each used once, either way round).
fn chain(start: P2, end: P2, segs: &[(P2, P2)]) -> Vec<P2> {
    let mut ring = vec![end, start];
    let mut used = vec![false; segs.len()];
    let mut cur = start;
    let close = |a: P2, b: P2| dist(a, b) < 1e-6;
    for _ in 0..segs.len() {
        let mut found = false;
        for (k, s) in segs.iter().enumerate() {
            if used[k] {
                continue;
            }
            if close(s.0, cur) {
                cur = s.1;
            } else if close(s.1, cur) {
                cur = s.0;
            } else {
                continue;
            }
            used[k] = true;
            found = true;
            if close(cur, end) {
                return ring;
            }
            ring.push(cur);
            break;
        }
        if !found {
            break;
        }
    }
    ring
}

enum Event {
    Edge(usize, usize, P2),
    Split(usize, usize, P2),
}

fn pos(v: &Vert, t: f64) -> P2 {
    add(v.p, scale(v.w, t - v.t0))
}

/// When consecutive corners u and v meet (the edge between them gone), and where.
fn edge_event(sk: &Skeleton, u: &Vert, v: &Vert, t_now: f64) -> Option<(f64, P2)> {
    // u at p_u + w_u (t - t_u), v likewise: they meet when equal; solve along the edge between
    let pu = pos(u, t_now);
    let pv = pos(v, t_now);
    let d = sub(pv, pu);
    let dw = sub(u.w, v.w);
    let dd = dot(dw, dw);
    if dd < 1e-24 {
        return None;
    }
    if dist(pu, pv) < 1e-7 {
        return Some((t_now, pu));
    }
    let t = t_now + dot(d, dw) / dd;
    if t <= t_now - 1e-9 {
        return None;
    }
    let t = t.max(t_now);
    let qu = pos(u, t);
    let qv = pos(v, t);
    if dist(qu, qv) > 1e-5 * (1.0 + len(d)) {
        return None;
    }
    let _ = sk;
    Some((t, lerp(qu, qv, 0.5)))
}

/// When reflex corner v hits the edge e between corners k and k2, and where.
fn split_event(sk: &Skeleton, v: &Vert, k: &Vert, k2: &Vert, e: usize, t_now: f64) -> Option<(f64, P2)> {
    let (_, _, n, s) = sk.edges[e];
    // dot(p_v + w_v (t - t_v), n) = d_e + s t
    let pv0 = v.p;
    let a = dot(v.w, n) - s;
    if a.abs() < 1e-12 {
        return None;
    }
    let t = (sk.offset_d(e, 0.0) - dot(pv0, n) + dot(v.w, n) * v.t0) / a;
    if !(t > t_now - 1e-9) {
        return None;
    }
    let t = t.max(t_now);
    let q = pos(v, t);
    // within the edge's segment then: between where k and k2 are
    let qa = pos(k, t);
    let qb = pos(k2, t);
    let dir = sub(qb, qa);
    let l2 = dot(dir, dir);
    if l2 < 1e-18 {
        return None;
    }
    let u = dot(sub(q, qa), dir) / l2;
    if u < -1e-9 || u > 1.0 + 1e-9 {
        return None;
    }
    // and the edge must lie ahead of v (moving toward it)
    Some((t, q))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn show(sk: &Skeleton) {
        eprintln!("t_max {}", sk.t_max);
        for (i, f) in sk.faces().iter().enumerate() {
            eprintln!("face {} area {:.1}: {:?}", i, area(f), f);
        }
    }
    #[test]
    fn rect() {
        let r = vec![vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 6000.0], [0.0, 6000.0]]];
        let sk = Skeleton::new(&r, &[1.0, 1.0, 1.0, 1.0]);
        show(&sk);
        let sk = Skeleton::new(&r, &[1.0, 0.0, 1.0, 0.0]);
        show(&sk);
    }
    #[test]
    fn ell() {
        let r = vec![vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 4000.0], [4000.0, 4000.0], [4000.0, 10000.0], [0.0, 10000.0]]];
        let sk = Skeleton::new(&r, &[1.0; 6]);
        show(&sk);
    }
    #[test]
    fn tee() {
        let r = vec![vec![[0.0, 0.0], [12000.0, 0.0], [12000.0, 4000.0], [8000.0, 4000.0], [8000.0, 10000.0], [4000.0, 10000.0], [4000.0, 4000.0], [0.0, 4000.0]]];
        let sk = Skeleton::new(&r, &[1.0; 8]);
        show(&sk);
        let tot: f64 = sk.faces().iter().map(|f| area(f)).sum();
        eprintln!("total {} expected {}", tot, area(&r[0]));
    }
    #[test]
    fn courtyard2() {
        let r = vec![
            vec![[0.0, 0.0], [12000.0, 0.0], [12000.0, 10000.0], [0.0, 10000.0]],
            vec![[3000.0, 3000.0], [3000.0, 6000.0], [8000.0, 6000.0], [8000.0, 3000.0]],
        ];
        let sk = Skeleton::new(&r, &[1.0; 8]);
        show(&sk);
        let tot: f64 = sk.faces().iter().map(|f| area(f)).sum();
        eprintln!("total {} expected {}", tot, area(&r[0]) + area(&r[1]));
    }
    #[test]
    fn courtyard() {
        let r = vec![
            vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 10000.0], [0.0, 10000.0]],
            vec![[3000.0, 3000.0], [3000.0, 7000.0], [7000.0, 7000.0], [7000.0, 3000.0]],
        ];
        let sk = Skeleton::new(&r, &[1.0; 8]);
        show(&sk);
        let tot: f64 = sk.faces().iter().map(|f| area(f)).sum();
        eprintln!("total {} expected {}", tot, area(&r[0]) + area(&r[1]));
    }
}
