//! A roof by footprint's surface, its straight skeleton: every edge of its outline (and of its
//! courtyards) moving inward at a speed of its own (the run per unit of rise of its slope; an
//! upright gable end not at all), the wavefront splitting where a reflex corner runs into an edge
//! and closing where edges shrink away, until nothing is left. The height of the surface at a point
//! is the rise at which the wavefront passes over it.
//!
//! It is worked out as stages between events, each a set of wavefront loops whose corners move in
//! straight lines; the ground each wavefront edge sweeps in a stage is a trapezoid, and a point's
//! height is when the edge whose trapezoid holds it passes over it. At each event the wavefront is
//! made whole again geometrically: wherever corners meet, or a corner touches an edge, the pieces
//! of wavefront through that point are paired anew around it (so loops split, join, and close).

use super::geom::{self, P};

#[derive(Clone, Debug)]
struct Line {
    /// Unit inward normal.
    n: P,
    /// Speed along `n` per unit of rise.
    w: f64,
    /// The outline's edge (as numbered for `gables` and `slopes`).
    id: usize,
}

#[derive(Clone, Debug)]
struct Vx {
    p: P,
    /// The wavefront edge coming in (from the previous corner) and going out, by line.
    l: usize,
    r: usize,
    v: P,
}

/// One edge's sweep in a stage.
#[derive(Clone, Debug)]
struct Sweep {
    quad: [P; 4],
    line: usize,
    t0: f64,
    /// n·x of the edge's line at t0.
    c0: f64,
}

#[derive(Clone, Debug, Default)]
pub struct Skeleton {
    lines: Vec<Line>,
    sweeps: Vec<Sweep>,
    /// The highest rise reached (where the last of the wavefront closes).
    pub top: f64,
    region: Vec<Vec<P>>,
}

fn line_dir(l: &Line) -> P {
    // n = left(d) = [-d.y, d.x] → d = [n.y, -n.x]
    [l.n[1], -l.n[0]]
}

fn velocity(lines: &[Line], a: usize, b: usize) -> P {
    let (la, lb) = (&lines[a], &lines[b]);
    let det = geom::cross(la.n, lb.n);
    if det.abs() < 1e-12 {
        // parallel: collinear edges go on together (opposed ones are a spent corner)
        if geom::dot(la.n, lb.n) > 0.0 {
            let w = (la.w + lb.w) / 2.0;
            return geom::mul(la.n, w);
        }
        return [0.0, 0.0];
    }
    // n_a·v = w_a, n_b·v = w_b
    let vx = (la.w * lb.n[1] - lb.w * la.n[1]) / det;
    let vy = (la.n[0] * lb.w - lb.n[0] * la.w) / det;
    [vx, vy]
}

/// The wavefront as a graph of corners, for making it whole at an event.
struct Wave {
    vs: Vec<Vx>,
    next: Vec<usize>,
    prev: Vec<usize>,
    alive: Vec<bool>,
}

impl Wave {
    fn new(loops: Vec<Vec<Vx>>) -> Wave {
        let mut w = Wave { vs: Vec::new(), next: Vec::new(), prev: Vec::new(), alive: Vec::new() };
        for lp in loops {
            let base = w.vs.len();
            let m = lp.len();
            for (i, v) in lp.into_iter().enumerate() {
                w.vs.push(v);
                w.next.push(base + (i + 1) % m);
                w.prev.push(base + (i + m - 1) % m);
                w.alive.push(true);
            }
        }
        w
    }

    fn add(&mut self, v: Vx) -> usize {
        self.vs.push(v);
        self.next.push(usize::MAX);
        self.prev.push(usize::MAX);
        self.alive.push(true);
        self.vs.len() - 1
    }

    fn loops(&self) -> Vec<Vec<Vx>> {
        let mut seen = vec![false; self.vs.len()];
        let mut out = Vec::new();
        for s in 0..self.vs.len() {
            if !self.alive[s] || seen[s] {
                continue;
            }
            let mut lp = Vec::new();
            let mut u = s;
            let mut ok = true;
            loop {
                if seen[u] || !self.alive[u] {
                    ok = u == s;
                    break;
                }
                seen[u] = true;
                lp.push(self.vs[u].clone());
                u = self.next[u];
                if u == usize::MAX {
                    ok = false;
                    break;
                }
            }
            if ok {
                out.push(lp);
            }
        }
        out
    }

    /// Puts a corner on an edge wherever another corner lies on it (not at its ends).
    fn insert_touches(&mut self, tol: f64) -> bool {
        let mut changed = false;
        let pts: Vec<(usize, P)> = (0..self.vs.len()).filter(|&i| self.alive[i]).map(|i| (i, self.vs[i].p)).collect();
        for u in 0..self.vs.len() {
            if !self.alive[u] {
                continue;
            }
            let mut guard = 0;
            loop {
                guard += 1;
                if guard > 100 {
                    break;
                }
                let n = self.next[u];
                let (a, b) = (self.vs[u].p, self.vs[n].p);
                let mut hit: Option<(f64, P)> = None;
                for &(q, qp) in &pts {
                    if q == u || q == n || !self.alive[q] {
                        continue;
                    }
                    if geom::dist(qp, a) <= tol || geom::dist(qp, b) <= tol {
                        continue;
                    }
                    if geom::dist_to_segment(qp, a, b) < tol {
                        let d = geom::dist(qp, a);
                        if hit.map(|h| d < h.0).unwrap_or(true) {
                            hit = Some((d, qp));
                        }
                    }
                }
                match hit {
                    Some((_, qp)) => {
                        let line = self.vs[u].r;
                        let k = self.add(Vx { p: qp, l: line, r: line, v: [0.0, 0.0] });
                        self.next[u] = k;
                        self.prev[k] = u;
                        self.next[k] = n;
                        self.prev[n] = k;
                        changed = true;
                        // the piece from u on may hold another
                    }
                    None => break,
                }
            }
        }
        changed
    }

    /// Groups of live corners within `tol` of one another (two or more).
    fn clusters(&self, tol: f64) -> Vec<Vec<usize>> {
        let ids: Vec<usize> = (0..self.vs.len()).filter(|&i| self.alive[i]).collect();
        let mut group: Vec<usize> = (0..ids.len()).collect();
        fn root(g: &mut Vec<usize>, i: usize) -> usize {
            let mut r = i;
            while g[r] != r {
                r = g[r];
            }
            let mut j = i;
            while g[j] != r {
                let k = g[j];
                g[j] = r;
                j = k;
            }
            r
        }
        for a in 0..ids.len() {
            for b in a + 1..ids.len() {
                if geom::dist(self.vs[ids[a]].p, self.vs[ids[b]].p) < tol {
                    let ra = root(&mut group, a);
                    let rb = root(&mut group, b);
                    if ra != rb {
                        group[ra] = rb;
                    }
                }
            }
        }
        let mut out: std::collections::BTreeMap<usize, Vec<usize>> = std::collections::BTreeMap::new();
        for a in 0..ids.len() {
            let r = root(&mut group, a);
            out.entry(r).or_default().push(ids[a]);
        }
        out.into_values().filter(|c| c.len() >= 2).collect()
    }

    /// Pairs anew the pieces of wavefront through one point: each piece going out of it with the
    /// next coming in, counter-clockwise round it (the ground between them is inside).
    fn relink(&mut self, c: &[usize], lines: &[Line]) -> bool {
        let inc: std::collections::BTreeSet<usize> = c.iter().copied().filter(|&u| self.alive[u]).collect();
        if inc.len() < 2 {
            return false;
        }
        // visits: runs of consecutive corners in the group
        struct Visit {
            lin: usize,
            lout: usize,
            before: usize,
            after: usize,
        }
        let mut visits: Vec<Visit> = Vec::new();
        for &u in &inc {
            if inc.contains(&self.prev[u]) {
                continue;
            }
            let mut w = u;
            let mut n = 0;
            while inc.contains(&self.next[w]) && n < inc.len() {
                w = self.next[w];
                n += 1;
            }
            visits.push(Visit { lin: self.vs[u].l, lout: self.vs[w].r, before: self.prev[u], after: self.next[w] });
        }
        let mut pos = [0.0, 0.0];
        for &u in &inc {
            pos = geom::add(pos, self.vs[u].p);
        }
        pos = geom::mul(pos, 1.0 / inc.len() as f64);
        for &u in &inc {
            self.alive[u] = false;
        }
        if visits.is_empty() {
            // a whole loop closed to this point
            return true;
        }
        // rays round the point: (angle, is_out, visit)
        let ang = |d: P| d[1].atan2(d[0]);
        let mut rays: Vec<(f64, bool, usize)> = Vec::new();
        for (k, v) in visits.iter().enumerate() {
            let din = line_dir(&lines[v.lin]);
            let dout = line_dir(&lines[v.lout]);
            rays.push((ang(geom::mul(din, -1.0)), false, k));
            rays.push((ang(dout), true, k));
        }
        rays.sort_by(|a, b| {
            if (a.0 - b.0).abs() < 1e-9 {
                b.1.cmp(&a.1) // at one angle, out before in
            } else {
                a.0.partial_cmp(&b.0).unwrap()
            }
        });
        let nr = rays.len();
        let mut used_in = vec![false; visits.len()];
        let mut made: Vec<(usize, usize)> = Vec::new(); // (out visit, in visit)
        for i in 0..nr {
            if !rays[i].1 {
                continue;
            }
            for k in 1..=nr {
                let r = &rays[(i + k) % nr];
                if !r.1 && !used_in[r.2] {
                    used_in[r.2] = true;
                    made.push((rays[i].2, r.2));
                    break;
                }
            }
        }
        for (a, b) in made {
            let (va, vb) = (&visits[a], &visits[b]);
            let (before, after, l, r) = (vb.before, va.after, vb.lin, va.lout);
            let k = self.add(Vx { p: pos, l, r, v: [0.0, 0.0] });
            self.prev[k] = before;
            self.next[k] = after;
            if before != usize::MAX {
                self.next[before] = k;
            }
            if after != usize::MAX {
                self.prev[after] = k;
            }
        }
        // a visit's own neighbours inside the group are gone: links to dead corners close up
        for k in 0..self.vs.len() {
            if self.alive[k] && (self.next[k] == usize::MAX || !self.alive[self.next[k]]) {
                self.alive[k] = false;
            }
        }
        true
    }

    /// Takes off spent corners (their two edges opposed along one line: a strip closed to nothing)
    /// and straight ones (between two pieces of one edge).
    fn remove_spikes(&mut self, lines: &[Line]) -> bool {
        let mut changed = false;
        for u in 0..self.vs.len() {
            if !self.alive[u] {
                continue;
            }
            let (p, n) = (self.prev[u], self.next[u]);
            if p == n || p == u {
                continue;
            }
            let (l, r) = (self.vs[u].l, self.vs[u].r);
            let opposed = geom::dot(lines[l].n, lines[r].n) < -1.0 + 1e-9;
            if l == r {
                self.next[p] = n;
                self.prev[n] = p;
                self.alive[u] = false;
                changed = true;
            } else if opposed {
                let dp = geom::dist(self.vs[u].p, self.vs[p].p);
                let dn = geom::dist(self.vs[u].p, self.vs[n].p);
                if dp <= dn {
                    self.vs[p].r = r;
                } else {
                    self.vs[n].l = l;
                }
                self.next[p] = n;
                self.prev[n] = p;
                self.alive[u] = false;
                changed = true;
            }
        }
        changed
    }
}

impl Skeleton {
    /// The skeleton of the region inside `outer` and outside `holes`, each edge given its speed
    /// (by edge number: the outer loop's from 0, the holes' numbered on): `speed(i)`.
    pub fn new(outer: &[P], holes: &[Vec<P>], speed: &dyn Fn(usize) -> f64) -> Skeleton {
        let mut lines: Vec<Line> = Vec::new();
        let mut loops: Vec<Vec<Vx>> = Vec::new();
        let mut region = Vec::new();
        let mut first_id = 0usize;
        let all: Vec<Vec<P>> = std::iter::once(outer.to_vec()).chain(holes.iter().cloned()).collect();
        for (k, pts) in all.iter().enumerate() {
            let n = pts.len();
            let ids: Vec<usize> = (0..n).map(|i| first_id + i).collect();
            first_id += n;
            if n < 3 {
                continue;
            }
            region.push(pts.clone());
            // the region lies to the left of every edge: the outline counter-clockwise, holes clockwise
            let ccw = geom::signed_area(pts) > 0.0;
            let want_ccw = k == 0;
            let (ps, es): (Vec<P>, Vec<usize>) = if ccw == want_ccw {
                (pts.clone(), ids.clone())
            } else {
                // reversed: point j is p[n-1-j]; edge j runs p[n-1-j] → p[n-2-j], edge n-2-j
                let ps: Vec<P> = (0..n).map(|j| pts[n - 1 - j]).collect();
                let es: Vec<usize> = (0..n).map(|j| ids[(2 * n - 2 - j) % n]).collect();
                (ps, es)
            };
            let mut q: Vec<(P, usize)> = Vec::new();
            for i in 0..n {
                let a = ps[i];
                let b = ps[(i + 1) % n];
                if geom::dist(a, b) > 1e-9 {
                    q.push((a, es[i]));
                }
            }
            let m = q.len();
            if m < 3 {
                continue;
            }
            let base = lines.len();
            for i in 0..m {
                let a = q[i].0;
                let b = q[(i + 1) % m].0;
                let d = geom::unit(geom::sub(b, a));
                let nrm = geom::left(d);
                lines.push(Line { n: nrm, w: speed(q[i].1).max(0.0), id: q[i].1 });
            }
            let mut lp = Vec::new();
            for i in 0..m {
                let l = base + (i + m - 1) % m;
                let r = base + i;
                lp.push(Vx { p: q[i].0, l, r, v: [0.0, 0.0] });
            }
            loops.push(lp);
        }
        let mut sk = Skeleton { lines, sweeps: Vec::new(), top: 0.0, region };
        sk.run(loops);
        sk
    }

    fn run(&mut self, loops: Vec<Vec<Vx>>) {
        let mut t = 0.0f64;
        let mut loops = self.clean(loops);
        let mut guard = 0;
        while !loops.is_empty() && guard < 5000 {
            guard += 1;
            for lp in loops.iter_mut() {
                for v in lp.iter_mut() {
                    v.v = velocity(&self.lines, v.l, v.r);
                }
            }
            let dt = match self.next_event(&loops) {
                Some(dt) => dt,
                None => break,
            };
            for lp in &loops {
                let m = lp.len();
                for i in 0..m {
                    let a = &lp[i];
                    let b = &lp[(i + 1) % m];
                    let line = a.r;
                    if self.lines[line].w <= 0.0 {
                        continue;
                    }
                    let a1 = geom::add(a.p, geom::mul(a.v, dt));
                    let b1 = geom::add(b.p, geom::mul(b.v, dt));
                    let c0 = geom::dot(self.lines[line].n, a.p);
                    self.sweeps.push(Sweep { quad: [a.p, b.p, b1, a1], line, t0: t, c0 });
                }
            }
            for lp in loops.iter_mut() {
                for v in lp.iter_mut() {
                    v.p = geom::add(v.p, geom::mul(v.v, dt));
                }
            }
            t += dt;
            self.top = t;
            loops = self.clean(loops);
        }
    }

    /// The rise to the next event from now: an edge shrinking away, or a reflex corner reaching an
    /// edge it isn't next to.
    fn next_event(&self, loops: &[Vec<Vx>]) -> Option<f64> {
        let mut best: Option<f64> = None;
        let mut take = |dt: f64| {
            if dt > 1e-9 && best.map(|b| dt < b).unwrap_or(true) {
                best = Some(dt);
            }
        };
        for lp in loops {
            let m = lp.len();
            for i in 0..m {
                let a = &lp[i];
                let b = &lp[(i + 1) % m];
                let d = line_dir(&self.lines[a.r]);
                let l = geom::dot(geom::sub(b.p, a.p), d);
                let rate = geom::dot(geom::sub(b.v, a.v), d);
                if rate < -1e-12 {
                    take(-l / rate);
                }
            }
        }
        for (li, lp) in loops.iter().enumerate() {
            let m = lp.len();
            for i in 0..m {
                let v = &lp[i];
                let din = line_dir(&self.lines[v.l]);
                let dout = line_dir(&self.lines[v.r]);
                if geom::cross(din, dout) >= -1e-12 {
                    continue; // not reflex
                }
                for (lj, lq) in loops.iter().enumerate() {
                    let mq = lq.len();
                    for j in 0..mq {
                        let jn = (j + 1) % mq;
                        if li == lj && (j == i || jn == i) {
                            continue;
                        }
                        let a = &lq[j];
                        let b = &lq[jn];
                        let f = &self.lines[a.r];
                        let s = geom::dot(f.n, geom::sub(v.p, a.p));
                        let rate = geom::dot(f.n, v.v) - f.w;
                        if rate >= -1e-12 || s < -1e-6 {
                            continue;
                        }
                        let dt = s / -rate;
                        if dt <= 1e-9 {
                            continue;
                        }
                        let x = geom::add(v.p, geom::mul(v.v, dt));
                        let a1 = geom::add(a.p, geom::mul(a.v, dt));
                        let b1 = geom::add(b.p, geom::mul(b.v, dt));
                        let d = line_dir(f);
                        let la = geom::dot(geom::sub(x, a1), d);
                        let lb = geom::dot(geom::sub(b1, x), d);
                        if la >= -1e-6 && lb >= -1e-6 {
                            take(dt);
                        }
                    }
                }
            }
        }
        best
    }

    /// The wavefront made whole: corners that met joined, the pieces through a point where corners
    /// meet or touch an edge paired anew, spent corners taken off, what has closed dropped.
    fn clean(&self, loops: Vec<Vec<Vx>>) -> Vec<Vec<Vx>> {
        let tol = 1e-5;
        let mut w = Wave::new(loops);
        for _ in 0..200 {
            let mut changed = w.insert_touches(tol);
            for c in w.clusters(tol) {
                if w.relink(&c, &self.lines) {
                    changed = true;
                }
            }
            if w.remove_spikes(&self.lines) {
                changed = true;
            }
            if !changed {
                break;
            }
        }
        let mut out = Vec::new();
        for lp in w.loops() {
            if lp.len() < 3 {
                continue;
            }
            let pts: Vec<P> = lp.iter().map(|v| v.p).collect();
            if geom::signed_area(&pts).abs() <= 1e-3 {
                continue;
            }
            out.push(lp);
        }
        out
    }

    /// The rise of the surface over `p` and the outline's edge whose slope it is on; None outside
    /// the region.
    pub fn at(&self, p: P) -> Option<(f64, usize)> {
        if self.region.is_empty() {
            return None;
        }
        let on = |r: &Vec<P>| geom::dist_to_outline(r, p) < 1e-6;
        if !(geom::inside(&self.region[0], p) || on(&self.region[0])) {
            return None;
        }
        for r in &self.region[1..] {
            if geom::inside(r, p) && !on(r) {
                return None;
            }
        }
        let mut best: Option<(f64, usize, f64)> = None;
        for s in &self.sweeps {
            let gap = quad_gap(&s.quad, p);
            if gap > 1e-6 {
                continue;
            }
            let l = &self.lines[s.line];
            let h = s.t0 + (geom::dot(l.n, p) - s.c0) / l.w;
            let better = match best {
                None => true,
                Some((bh, _, _)) => h < bh,
            };
            if better {
                best = Some((h, l.id, gap));
            }
        }
        if let Some((h, id, _)) = best {
            return Some((h.max(0.0), id));
        }
        // nothing swept it (rounding at a corner): the nearest sweep
        let mut near: Option<(f64, f64, usize)> = None;
        for s in &self.sweeps {
            let g = quad_gap(&s.quad, p);
            let l = &self.lines[s.line];
            let h = s.t0 + (geom::dot(l.n, p) - s.c0) / l.w;
            if near.map(|n| g < n.0).unwrap_or(true) {
                near = Some((g, h, l.id));
            }
        }
        near.map(|(_, h, id)| (h.max(0.0), id))
    }
}

/// How far `p` is outside a convex quad (0 inside or on it).
fn quad_gap(q: &[P; 4], p: P) -> f64 {
    let mut pts: Vec<P> = Vec::with_capacity(4);
    for x in q.iter() {
        if pts.last().map(|l| geom::dist(*l, *x) > 1e-9).unwrap_or(true) {
            pts.push(*x);
        }
    }
    while pts.len() > 1 && geom::dist(pts[0], *pts.last().unwrap()) <= 1e-9 {
        pts.pop();
    }
    if pts.len() < 3 {
        return f64::INFINITY;
    }
    let sa = geom::signed_area(&pts);
    if sa.abs() < 1e-9 {
        return f64::INFINITY;
    }
    let s = if sa > 0.0 { 1.0 } else { -1.0 };
    let mut gap: f64 = 0.0;
    let n = pts.len();
    for i in 0..n {
        let a = pts[i];
        let b = pts[(i + 1) % n];
        let d = geom::sub(b, a);
        let l = geom::len(d);
        if l <= 1e-12 {
            continue;
        }
        let side = s * geom::cross(d, geom::sub(p, a)) / l;
        if side < 0.0 {
            gap = gap.max(-side);
        }
    }
    gap
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Vec<P> {
        vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    }

    fn near(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-6
    }

    #[test]
    fn hip_rectangle() {
        let sk = Skeleton::new(&rect(0.0, 0.0, 10000.0, 6000.0), &[], &|_| 1.0);
        assert!(near(sk.top, 3000.0), "{}", sk.top);
        assert!(near(sk.at([5000.0, 1000.0]).unwrap().0, 1000.0));
        assert!(near(sk.at([500.0, 3000.0]).unwrap().0, 500.0));
        assert!(near(sk.at([5000.0, 3000.0]).unwrap().0, 3000.0));
    }

    #[test]
    fn square() {
        let sk = Skeleton::new(&rect(0.0, 0.0, 8000.0, 8000.0), &[], &|_| 1.0);
        assert!(near(sk.top, 4000.0), "{}", sk.top);
        assert!(near(sk.at([4000.0, 4000.0]).unwrap().0, 4000.0));
    }

    #[test]
    fn gable_rectangle() {
        let sk = Skeleton::new(&rect(0.0, 0.0, 10000.0, 6000.0), &[], &|i| if i == 1 || i == 3 { 0.0 } else { 1.0 });
        assert!(near(sk.top, 3000.0), "{}", sk.top);
        assert!(near(sk.at([100.0, 2900.0]).unwrap().0, 2900.0));
        assert!(near(sk.at([9999.0, 3000.0]).unwrap().0, 3000.0));
    }

    #[test]
    fn l_shape() {
        let l = vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 4000.0], [4000.0, 4000.0], [4000.0, 10000.0], [0.0, 10000.0]];
        let sk = Skeleton::new(&l, &[], &|_| 1.0);
        assert!(near(sk.top, 2000.0), "{}", sk.top);
        assert!(near(sk.at([3900.0, 3900.0]).unwrap().0, 100.0));
        assert!(near(sk.at([2000.0, 9000.0]).unwrap().0, 1000.0));
        assert!(near(sk.at([3000.0, 3000.0]).unwrap().0, 1000.0));
    }

    #[test]
    fn l_unequal() {
        let l = vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 4000.0], [6000.0, 4000.0], [6000.0, 10000.0], [0.0, 10000.0]];
        let sk = Skeleton::new(&l, &[], &|_| 1.0);
        assert!(near(sk.top, 3000.0), "{}", sk.top);
        assert!(near(sk.at([5900.0, 4100.0]).unwrap().0, 100.0));
        assert!(near(sk.at([8000.0, 2000.0]).unwrap().0, 2000.0));
        assert!(near(sk.at([3000.0, 7000.0]).unwrap().0, 3000.0));
    }

    #[test]
    fn courtyard() {
        let sk = Skeleton::new(&rect(0.0, 0.0, 10000.0, 6000.0), &[rect(3000.0, 2000.0, 7000.0, 4000.0)], &|_| 1.0);
        assert!(near(sk.top, 1500.0), "{}", sk.top);
        assert!(sk.at([5000.0, 3000.0]).is_none());
        assert!(near(sk.at([5000.0, 1000.0]).unwrap().0, 1000.0));
        assert!(near(sk.at([1500.0, 3000.0]).unwrap().0, 1500.0));
    }

    #[test]
    fn t_shape() {
        // bar 12000 x 4000 on top of a stem 2000 wide
        let t = vec![
            [5000.0, 0.0],
            [7000.0, 0.0],
            [7000.0, 6000.0],
            [12000.0, 6000.0],
            [12000.0, 10000.0],
            [0.0, 10000.0],
            [0.0, 6000.0],
            [5000.0, 6000.0],
        ];
        let sk = Skeleton::new(&t, &[], &|_| 1.0);
        assert!(near(sk.top, 2000.0), "{}", sk.top);
        assert!(near(sk.at([6000.0, 3000.0]).unwrap().0, 1000.0));
        assert!(near(sk.at([6000.0, 8000.0]).unwrap().0, 2000.0));
    }

    #[test]
    fn dbg_courtyard() {
        let sk = Skeleton::new(&rect(0.0, 0.0, 10000.0, 6000.0), &[rect(3000.0, 2000.0, 7000.0, 4000.0)], &|_| 1.0);
        for s in &sk.sweeps {
            eprintln!("t0 {} line {} quad {:?}", s.t0, s.line, s.quad);
        }
    }

    #[test]
    fn shed() {
        // only edge 3 (x = 0) slopes
        let sk = Skeleton::new(&rect(0.0, 0.0, 10000.0, 6000.0), &[], &|i| if i == 3 { 1.0 } else { 0.0 });
        assert!(near(sk.top, 10000.0), "{}", sk.top);
        assert!(near(sk.at([4000.0, 3000.0]).unwrap().0, 4000.0));
    }
}
