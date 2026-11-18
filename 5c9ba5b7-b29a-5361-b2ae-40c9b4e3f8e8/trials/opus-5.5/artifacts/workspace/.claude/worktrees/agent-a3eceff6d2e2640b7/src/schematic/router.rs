// An orthogonal search between two fixed ports. Every drawn box is an
// obstacle, grown by the clearance. A wire leaves its port straight along
// the port's facing until it is clear of its own body (the landing), then
// searches a sparse grid — the scope's lattice lines and the obstacles'
// edges — for the cheapest route: length plus two clearances per bend.
// Segment placement follows: a staircase step centres in its channel, on
// the lattice line nearest the middle when the channel holds one; a detour
// keeps to the first lattice line clear of what it goes around, or centres
// between that and whatever lies beyond.

use super::net::Dir;
use std::collections::BinaryHeap;

const EPS: f64 = 1e-6;
const PITCH: f64 = 20.0;

#[derive(Clone, Copy, Debug)]
pub struct Rect {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

impl Rect {
    pub fn new(x0: f64, y0: f64, x1: f64, y1: f64) -> Rect {
        Rect { x0, y0, x1, y1 }
    }
    pub fn grow(&self, k: f64) -> Rect {
        Rect::new(self.x0 - k, self.y0 - k, self.x1 + k, self.y1 + k)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Port {
    pub p: (f64, f64),
    // the way the wire leaves the port
    pub d: Dir,
    // one of the port's own obstacles (its body: left straight from the port)
    pub own: Option<usize>,
    // the wire may leave the port any way but back
    pub free: bool,
    // a part's station: a detour off it keeps to its landing
    pub station: bool,
}

pub struct World {
    pub obs: Vec<Rect>,
    // what segment placement measures channels against (a part's own
    // drawing at its full clearance)
    pub place_obs: Vec<Rect>,
    // the drawings themselves (a squeezed detour centres between them)
    pub raw_obs: Vec<Rect>,
    // a nested sheet's own box: what lies beyond when nothing else does
    pub bounds: Option<Rect>,
    pub owner: Vec<usize>,
    // the lattice origin (the scope's centre)
    pub lattice: (f64, f64),
}

fn idx(d: Dir) -> usize {
    match d {
        Dir::R => 0,
        Dir::D => 1,
        Dir::L => 2,
        Dir::U => 3,
    }
}

const DIRS: [Dir; 4] = [Dir::R, Dir::D, Dir::L, Dir::U];

// is the segment p-q clear of every obstacle's open interior (but `skip`)?
pub fn seg_clear(obs: &[Rect], skip: &[usize], p: (f64, f64), q: (f64, f64)) -> bool {
    let (x0, x1) = (p.0.min(q.0), p.0.max(q.0));
    let (y0, y1) = (p.1.min(q.1), p.1.max(q.1));
    for (k, r) in obs.iter().enumerate() {
        if skip.contains(&k) {
            continue;
        }
        if (y1 - y0).abs() < EPS {
            if y0 > r.y0 + EPS && y0 < r.y1 - EPS && x0 < r.x1 - EPS && x1 > r.x0 + EPS {
                return false;
            }
        } else if x0 > r.x0 + EPS && x0 < r.x1 - EPS && y0 < r.y1 - EPS && y1 > r.y0 + EPS {
            return false;
        }
    }
    true
}

impl World {
    fn own_set(&self, p: &Port) -> Vec<usize> {
        match p.own {
            Some(k) => (0..self.obs.len()).filter(|&j| self.owner[j] == self.owner[k]).collect(),
            None => vec![],
        }
    }

    // out of a port along its facing, past every own obstacle it meets (a
    // free port is entered where it lies)
    pub fn landing(&self, port: &Port) -> (f64, f64) {
        let mut p = port.p;
        if port.free {
            return p;
        }
        let own = self.own_set(port);
        loop {
            let mut moved = false;
            for &k in &own {
                let r = self.obs[k];
                let on = match port.d {
                    Dir::R | Dir::L => p.1 > r.y0 + EPS && p.1 < r.y1 - EPS && p.0 > r.x0 - EPS && p.0 < r.x1 - EPS,
                    Dir::U | Dir::D => p.0 > r.x0 + EPS && p.0 < r.x1 - EPS && p.1 > r.y0 - EPS && p.1 < r.y1 - EPS,
                };
                if !on {
                    continue;
                }
                let q = match port.d {
                    Dir::R => (r.x1, p.1),
                    Dir::L => (r.x0, p.1),
                    Dir::D => (p.0, r.y1),
                    Dir::U => (p.0, r.y0),
                };
                if (q.0 - p.0).abs() > EPS || (q.1 - p.1).abs() > EPS {
                    p = q;
                    moved = true;
                }
            }
            if !moved {
                break;
            }
        }
        p
    }

    fn lattice_lines(&self, lo: f64, hi: f64, o: f64) -> Vec<f64> {
        let mut v = Vec::new();
        let mut k = ((lo - o) / PITCH).ceil();
        while k * PITCH + o <= hi + EPS {
            v.push(k * PITCH + o);
            k += 1.0;
        }
        v
    }

    // the cheapest route between two ports: length plus `bend` per bend
    pub fn search(&self, a: &Port, b: &Port, bend: f64) -> Option<Vec<(f64, f64)>> {
        let la = self.landing(a);
        let lb = self.landing(b);
        let skip_a = self.own_set(a);
        let skip_b = self.own_set(b);
        let mut xs = vec![la.0, lb.0];
        let mut ys = vec![la.1, lb.1];
        let (mut x0, mut y0, mut x1, mut y1) = (la.0.min(lb.0), la.1.min(lb.1), la.0.max(lb.0), la.1.max(lb.1));
        for r in &self.obs {
            xs.push(r.x0);
            xs.push(r.x1);
            ys.push(r.y0);
            ys.push(r.y1);
            x0 = x0.min(r.x0);
            y0 = y0.min(r.y0);
            x1 = x1.max(r.x1);
            y1 = y1.max(r.y1);
        }
        xs.extend(self.lattice_lines(x0 - 2.0 * PITCH, x1 + 2.0 * PITCH, self.lattice.0));
        ys.extend(self.lattice_lines(y0 - 2.0 * PITCH, y1 + 2.0 * PITCH, self.lattice.1));
        let xs = uniq(xs);
        let ys = uniq(ys);
        let nx = xs.len();
        let ny = ys.len();
        let find = |v: &[f64], x: f64| v.iter().position(|t| (t - x).abs() < 1e-7);
        let (sx, sy) = (find(&xs, la.0)?, find(&ys, la.1)?);
        let (gx, gy) = (find(&xs, lb.0)?, find(&ys, lb.1)?);
        let state = |ix: usize, iy: usize, d: usize| (iy * nx + ix) * 4 + d;
        let n = nx * ny * 4;
        let mut dist = vec![f64::INFINITY; n];
        let mut prev = vec![usize::MAX; n];
        let mut heap = BinaryHeap::new();
        let mut seq = 0u64;
        let start = state(sx, sy, idx(a.d));
        dist[start] = 0.0;
        heap.push(Item { cost: 0.0, seq, state: start });
        let want = idx(b.d.opposite());
        let order: Vec<Dir> = match std::env::var("LINI_SCH_DIRS") {
            Ok(v) => v
                .chars()
                .filter_map(|c| match c {
                    'L' => Some(Dir::L),
                    'R' => Some(Dir::R),
                    'U' => Some(Dir::U),
                    'D' => Some(Dir::D),
                    _ => None,
                })
                .collect(),
            Err(_) => DIRS.to_vec(),
        };
        let mut best: Option<(f64, usize)> = None;
        while let Some(Item { cost, state: st, .. }) = heap.pop() {
            if cost > dist[st] + EPS {
                continue;
            }
            if let Some((bc, _)) = best {
                if cost > bc + EPS {
                    break;
                }
            }
            let d = st % 4;
            let cell = st / 4;
            let (ix, iy) = (cell % nx, cell / nx);
            if ix == gx && iy == gy {
                let extra = if b.free {
                    if d == (want + 2) % 4 {
                        f64::INFINITY
                    } else {
                        0.0
                    }
                } else if d == want {
                    0.0
                } else if (d + 2) % 4 == want {
                    f64::INFINITY
                } else {
                    bend
                };
                if extra.is_finite() {
                    let c = cost + extra;
                    if best.map_or(true, |(bc, _)| c < bc - EPS) {
                        best = Some((c, st));
                    }
                }
            }
            for nd in order.iter() {
                let k = idx(*nd);
                if k == (d + 2) % 4 {
                    continue;
                }
                let (jx, jy) = match nd {
                    Dir::R if ix + 1 < nx => (ix + 1, iy),
                    Dir::L if ix > 0 => (ix - 1, iy),
                    Dir::D if iy + 1 < ny => (ix, iy + 1),
                    Dir::U if iy > 0 => (ix, iy - 1),
                    _ => continue,
                };
                let p = (xs[ix], ys[iy]);
                let q = (xs[jx], ys[jy]);
                if !seg_clear(&self.obs, &[], p, q) {
                    let mut ok = false;
                    if seg_clear(&self.obs, &skip_a, p, q) && on_stub(a, la, p, q) {
                        ok = true;
                    }
                    if seg_clear(&self.obs, &skip_b, p, q) && on_stub(b, lb, p, q) {
                        ok = true;
                    }
                    // a free port is reached along its own lines through
                    // what it owns
                    for (port, skip) in [(a, &skip_a), (b, &skip_b)] {
                        if port.free && seg_clear(&self.obs, skip, p, q) {
                            let along = if (p.1 - q.1).abs() < EPS { (p.1 - port.p.1).abs() < EPS } else { (p.0 - port.p.0).abs() < EPS };
                            if along {
                                ok = true;
                            }
                        }
                    }
                    if !ok {
                        continue;
                    }
                }
                let len = (q.0 - p.0).abs() + (q.1 - p.1).abs();
                let turn = if k == d || (st == start && a.free) { 0.0 } else { bend };
                // (between routes of one cost, the one running higher)
                let lean = if nd.horizontal() { 1e-9 * p.1 * len } else { 0.0 };
                let nc = cost + len + turn + lean;
                let ns = state(jx, jy, k);
                if nc < dist[ns] - EPS {
                    dist[ns] = nc;
                    prev[ns] = st;
                    seq += 1;
                    heap.push(Item { cost: nc, seq, state: ns });
                }
            }
        }
        let (_, mut st) = best?;
        let mut cells: Vec<(f64, f64)> = Vec::new();
        loop {
            let cell = st / 4;
            cells.push((xs[cell % nx], ys[cell / nx]));
            if prev[st] == usize::MAX {
                break;
            }
            st = prev[st];
        }
        cells.reverse();
        let mut pts = vec![a.p];
        pts.extend(cells);
        pts.push(b.p);
        let mut pts = simplify(&pts);
        if std::env::var("LINI_SCH_DBG").is_ok() {
            eprintln!("  raw path {:?} cost {:?}", pts, best.map(|b| b.0));
        }
        self.place(&mut pts, la, lb, a.station, b.station);
        Some(simplify(&pts))
    }

    // the lattice line nearest `m` within [lo, hi] (halves toward the lower),
    // else `m`
    fn snap_within(&self, m: f64, lo: f64, hi: f64, o: f64) -> f64 {
        let k = (((m - o) / PITCH) - 0.5 + 1e-9).ceil();
        let near = k * PITCH + o;
        let mut cands: Vec<f64> = vec![near, near - PITCH, near + PITCH];
        cands.retain(|c| *c >= lo - EPS && *c <= hi + EPS);
        cands.sort_by(|a, b| {
            let da = (a - m).abs();
            let db = (b - m).abs();
            da.partial_cmp(&db).unwrap().then(a.partial_cmp(b).unwrap())
        });
        cands.first().cloned().unwrap_or(m)
    }

    // segment placement: steps centre in their channel; detours hug, or
    // centre between what they go around and what lies beyond
    fn place(&self, pts: &mut Vec<(f64, f64)>, la: (f64, f64), lb: (f64, f64), sa: bool, sb: bool) {
        let n = pts.len();
        if n < 4 {
            return;
        }
        // (each segment measured on the route as found)
        let orig = pts.clone();
        for k in 1..n - 2 {
            let (a, b, c, d) = (orig[k - 1], orig[k], orig[k + 1], orig[k + 2]);
            let vert = (b.0 - c.0).abs() < EPS;
            let (before, after) = if vert { (b.0 - a.0, d.0 - c.0) } else { (b.1 - a.1, d.1 - c.1) };
            let step = before * after > 0.0;
            let (s0, s1) = if vert { (b.1.min(c.1), b.1.max(c.1)) } else { (b.0.min(c.0), b.0.max(c.0)) };
            let pos = if vert { b.0 } else { b.1 };
            let o = if vert { self.lattice.0 } else { self.lattice.1 };
            // the free channel across the segment
            let mut clo = f64::NEG_INFINITY;
            let mut chi = f64::INFINITY;
            for r in &self.place_obs {
                let (a0, a1, b0, b1) = if vert { (r.y0, r.y1, r.x0, r.x1) } else { (r.x0, r.x1, r.y0, r.y1) };
                if a0 < s1 - EPS && a1 > s0 + EPS {
                    if b1 <= pos + EPS && b1 > clo {
                        clo = b1;
                    }
                    if b0 >= pos - EPS && b0 < chi {
                        chi = b0;
                    }
                    // a box the segment already stands in (a part's own
                    // drawing at its full clearance) bounds it on its side
                    if b0 < pos - EPS && b1 > pos + EPS {
                        if (b0 + b1) / 2.0 > pos {
                            chi = chi.min(b0);
                        } else {
                            clo = clo.max(b1);
                        }
                    }
                }
            }
            // the ports' runs keep their landings
            let mut lo = f64::NEG_INFINITY;
            let mut hi = f64::INFINITY;
            if k == 1 {
                let l = if vert { la.0 } else { la.1 };
                if before > 0.0 {
                    lo = lo.max(l);
                } else {
                    hi = hi.min(l);
                }
            }
            if k + 2 == n - 1 {
                let l = if vert { lb.0 } else { lb.1 };
                if after > 0.0 {
                    hi = hi.min(l);
                } else {
                    lo = lo.max(l);
                }
            }
            let m = if step {
                // within both neighbours' spans
                let (sl, sh) = if vert { (a.0.min(d.0), a.0.max(d.0)) } else { (a.1.min(d.1), a.1.max(d.1)) };
                let lo = lo.max(sl).max(clo);
                let hi = hi.min(sh).min(chi);
                if !lo.is_finite() || !hi.is_finite() || hi < lo - EPS {
                    continue;
                }
                self.snap_within((lo + hi) / 2.0, lo, hi, o)
            } else {
                // a detour off a part's station keeps to the station's landing
                if (k == 1 && sa) || (k + 2 == n - 1 && sb) {
                    continue;
                }
                // a detour: its neighbours come from the side it goes around
                let toward_low = before > 0.0;
                let (hug, mut beyond) = if toward_low { (clo, chi) } else { (chi, clo) };
                if !beyond.is_finite() {
                    if let Some(bd) = self.bounds {
                        beyond = match (vert, toward_low) {
                            (true, true) => bd.x1,
                            (true, false) => bd.x0,
                            (false, true) => bd.y1,
                            (false, false) => bd.y0,
                        };
                    }
                }
                if !hug.is_finite() {
                    continue;
                }
                // the first lattice line clear of what it goes around
                let first = if toward_low {
                    (((hug - o) / PITCH) - 1e-9).ceil() * PITCH + o
                } else {
                    (((hug - o) / PITCH) + 1e-9).floor() * PITCH + o
                };
                if beyond.is_finite() {
                    let (l2, h2) = if toward_low { (hug, beyond) } else { (beyond, hug) };
                    if h2 < l2 + EPS {
                        // no room for the clearance: halfway between the
                        // drawings themselves
                        let mut rlo = f64::NEG_INFINITY;
                        let mut rhi = f64::INFINITY;
                        for r in &self.raw_obs {
                            let (a0, a1, b0, b1) = if vert { (r.y0, r.y1, r.x0, r.x1) } else { (r.x0, r.x1, r.y0, r.y1) };
                            if a0 < s1 - EPS && a1 > s0 + EPS {
                                if b1 <= pos + EPS && b1 > rlo {
                                    rlo = b1;
                                }
                                if b0 >= pos - EPS && b0 < rhi {
                                    rhi = b0;
                                }
                            }
                        }
                        if !rlo.is_finite() || !rhi.is_finite() {
                            continue;
                        }
                        (rlo + rhi) / 2.0
                    } else {
                        self.snap_within((l2 + h2) / 2.0, l2.max(lo), h2.min(hi), o)
                    }
                } else {
                    if first < lo - EPS || first > hi + EPS {
                        continue;
                    }
                    first
                }
            };
            if vert {
                pts[k].0 = m;
                pts[k + 1].0 = m;
            } else {
                pts[k].1 = m;
                pts[k + 1].1 = m;
            }
        }
    }
}

fn uniq(mut v: Vec<f64>) -> Vec<f64> {
    v.retain(|x| x.is_finite());
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut o: Vec<f64> = Vec::new();
    for x in v {
        if o.last().map_or(true, |l: &f64| (x - *l).abs() > 1e-7) {
            o.push(x);
        }
    }
    o
}

#[derive(PartialEq)]
struct Item {
    cost: f64,
    seq: u64,
    state: usize,
}
impl Eq for Item {}
impl PartialOrd for Item {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Item {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        // costs equal to a millionth tie, the earlier found first
        let q = |c: f64| (c * 1e6).round() as i64;
        q(o.cost).cmp(&q(self.cost)).then(o.seq.cmp(&self.seq))
    }
}

pub fn simplify(pts: &[(f64, f64)]) -> Vec<(f64, f64)> {
    let mut o: Vec<(f64, f64)> = Vec::new();
    for &p in pts {
        if let Some(l) = o.last() {
            if (l.0 - p.0).abs() < EPS && (l.1 - p.1).abs() < EPS {
                continue;
            }
        }
        o.push(p);
    }
    let mut k = 1;
    while k + 1 < o.len() {
        let (a, b, c) = (o[k - 1], o[k], o[k + 1]);
        let col = ((a.0 - b.0).abs() < EPS && (b.0 - c.0).abs() < EPS) || ((a.1 - b.1).abs() < EPS && (b.1 - c.1).abs() < EPS);
        if col {
            o.remove(k);
        } else {
            k += 1;
        }
    }
    o
}

fn on_stub(port: &Port, land: (f64, f64), p: (f64, f64), q: (f64, f64)) -> bool {
    let within = |t: (f64, f64)| {
        let (x0, x1) = (port.p.0.min(land.0), port.p.0.max(land.0));
        let (y0, y1) = (port.p.1.min(land.1), port.p.1.max(land.1));
        t.0 >= x0 - EPS && t.0 <= x1 + EPS && t.1 >= y0 - EPS && t.1 <= y1 + EPS
    };
    within(p) && within(q)
}
