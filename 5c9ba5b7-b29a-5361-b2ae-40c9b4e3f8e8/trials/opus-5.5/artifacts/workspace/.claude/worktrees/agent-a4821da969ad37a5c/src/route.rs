// Orthogonal link routing: a sparse-grid search over obstacles inflated by
// the clearance, then segment placement (staircase segments centre in their
// channel, detours hug what they go around), port spreading along shared
// sides and track spreading for parallel runs.

use std::collections::BinaryHeap;

pub const EPS: f64 = 1e-6;

// A box. Edges are kept for geometry; the centre and size are kept exactly
// as laid out so ports and side lengths match the layout's arithmetic.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
    pub ccx: f64,
    pub ccy: f64,
    pub cw: f64,
    pub ch: f64,
}

impl Rect {
    pub fn new(x0: f64, y0: f64, x1: f64, y1: f64) -> Rect {
        Rect { x0, y0, x1, y1, ccx: (x0 + x1) / 2.0, ccy: (y0 + y1) / 2.0, cw: x1 - x0, ch: y1 - y0 }
    }
    pub fn centered(cx: f64, cy: f64, w: f64, h: f64) -> Rect {
        Rect { x0: cx - w / 2.0, y0: cy - h / 2.0, x1: cx + w / 2.0, y1: cy + h / 2.0, ccx: cx, ccy: cy, cw: w, ch: h }
    }
    pub fn grow(&self, k: f64) -> Rect {
        Rect {
            x0: self.x0 - k,
            y0: self.y0 - k,
            x1: self.x1 + k,
            y1: self.y1 + k,
            ccx: self.ccx,
            ccy: self.ccy,
            cw: self.cw + 2.0 * k,
            ch: self.ch + 2.0 * k,
        }
    }
    pub fn cx(&self) -> f64 {
        self.ccx
    }
    pub fn cy(&self) -> f64 {
        self.ccy
    }
    pub fn w(&self) -> f64 {
        self.cw
    }
    pub fn h(&self) -> f64 {
        self.ch
    }
    pub fn overlaps(&self, o: &Rect) -> bool {
        self.x0 < o.x1 && o.x0 < self.x1 && self.y0 < o.y1 && o.y0 < self.y1
    }
    pub fn contains_open(&self, x: f64, y: f64) -> bool {
        x > self.x0 + EPS && x < self.x1 - EPS && y > self.y0 + EPS && y < self.y1 - EPS
    }
}

// Sides, clockwise from the top; the direction is the outward normal.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Side {
    Top,
    Right,
    Bottom,
    Left,
}

pub const SIDES: [Side; 4] = [Side::Top, Side::Right, Side::Bottom, Side::Left];

impl Side {
    pub fn dir(self) -> (f64, f64) {
        match self {
            Side::Top => (0.0, -1.0),
            Side::Right => (1.0, 0.0),
            Side::Bottom => (0.0, 1.0),
            Side::Left => (-1.0, 0.0),
        }
    }
    pub fn horizontal(self) -> bool {
        matches!(self, Side::Top | Side::Bottom)
    }
    pub fn parse(s: &str) -> Option<Side> {
        match s {
            "top" => Some(Side::Top),
            "right" => Some(Side::Right),
            "bottom" => Some(Side::Bottom),
            "left" => Some(Side::Left),
            _ => None,
        }
    }
    pub fn idx(self) -> usize {
        match self {
            Side::Top => 0,
            Side::Right => 1,
            Side::Bottom => 2,
            Side::Left => 3,
        }
    }
}

// The point on a rect side at the given offset from the side's centre
// (along x for top/bottom, along y for left/right).
pub fn side_point(r: &Rect, s: Side, off: f64) -> (f64, f64) {
    match s {
        Side::Top => (r.cx() + off, r.y0),
        Side::Bottom => (r.cx() + off, r.y1),
        Side::Left => (r.x0, r.cy() + off),
        Side::Right => (r.x1, r.cy() + off),
    }
}

// Extent of a side: (start, end) along its axis.
pub fn side_span(r: &Rect, s: Side) -> (f64, f64) {
    if s.horizontal() {
        (r.x0, r.x1)
    } else {
        (r.y0, r.y1)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ObKind {
    Solid,
    // a container holding only the start / only the end: the wire leaves it
    // straight, and outside it is solid
    WallA,
    WallB,
    // a container holding both ends: free inside, a keep-off band outside
    WallBoth,
}

#[derive(Clone, Debug)]
pub struct Ob {
    pub r: Rect,
    pub kind: ObKind,
    pub node: usize,
}

pub struct Env {
    pub k: f64,
    pub obs: Vec<Ob>,
    pub a: Rect,
    pub b: Rect,
}

// Directions as indices: 0 right, 1 down, 2 left, 3 up.
fn dir_of(dx: f64, dy: f64) -> usize {
    if dx > EPS {
        0
    } else if dy > EPS {
        1
    } else if dx < -EPS {
        2
    } else {
        3
    }
}

fn side_dir_idx(s: Side) -> usize {
    match s {
        Side::Right => 0,
        Side::Bottom => 1,
        Side::Left => 2,
        Side::Top => 3,
    }
}

impl Env {
    // Inflated solid obstacles (including the two endpoints).
    pub fn solids(&self) -> Vec<Rect> {
        let mut v: Vec<Rect> = self.obs.iter().filter(|o| o.kind != ObKind::WallBoth).map(|o| o.r.grow(self.k)).collect();
        v.push(self.a.grow(self.k));
        v.push(self.b.grow(self.k));
        v
    }
}

// Is the axis-aligned segment p-q clear of every inflated solid's interior?
fn seg_clear(solids: &[Rect], p: (f64, f64), q: (f64, f64)) -> bool {
    let (x0, x1) = if p.0 < q.0 { (p.0, q.0) } else { (q.0, p.0) };
    let (y0, y1) = if p.1 < q.1 { (p.1, q.1) } else { (q.1, p.1) };
    for r in solids {
        if (y1 - y0).abs() < EPS {
            // horizontal
            if y0 > r.y0 + EPS && y0 < r.y1 - EPS && x0 < r.x1 - EPS && x1 > r.x0 + EPS {
                return false;
            }
        } else if (x1 - x0).abs() < EPS {
            if x0 > r.x0 + EPS && x0 < r.x1 - EPS && y0 < r.y1 - EPS && y1 > r.y0 + EPS {
                return false;
            }
        }
    }
    true
}

// Wall bands: a container that holds an endpoint may be crossed, but only
// head-on; nothing runs along or turns within the clearance of its border.
pub struct Band {
    // the band region (open): the ring just outside a wall's border
    r: Rect,
    // true: the border is horizontal (top/bottom edge) — vertical crossing allowed
    horiz: bool,
    // crossings must fall within this span (along the border)
    lo: f64,
    hi: f64,
}

fn wall_bands(env: &Env) -> Vec<Band> {
    let k = env.k;
    let mut v = Vec::new();
    for o in &env.obs {
        if o.kind != ObKind::WallBoth {
            continue;
        }
        let r = o.r;
        v.push(Band { r: Rect::new(r.x0 - k, r.y0 - k, r.x1 + k, r.y0), horiz: true, lo: r.x0 + k, hi: r.x1 - k });
        v.push(Band { r: Rect::new(r.x0 - k, r.y1, r.x1 + k, r.y1 + k), horiz: true, lo: r.x0 + k, hi: r.x1 - k });
        v.push(Band { r: Rect::new(r.x0 - k, r.y0 - k, r.x0, r.y1 + k), horiz: false, lo: r.y0 + k, hi: r.y1 - k });
        v.push(Band { r: Rect::new(r.x1, r.y0 - k, r.x1 + k, r.y1 + k), horiz: false, lo: r.y0 + k, hi: r.y1 - k });
    }
    v
}

fn in_band(bands: &[Band], x: f64, y: f64) -> bool {
    bands.iter().any(|b| b.r.contains_open(x, y))
}

// A segment may cross a band only perpendicular to its border, away from
// the border's ends.
fn seg_band_ok(bands: &[Band], p: (f64, f64), q: (f64, f64)) -> bool {
    let horiz_seg = (p.1 - q.1).abs() < EPS;
    let (x0, x1) = if p.0 < q.0 { (p.0, q.0) } else { (q.0, p.0) };
    let (y0, y1) = if p.1 < q.1 { (p.1, q.1) } else { (q.1, p.1) };
    for b in bands {
        let r = &b.r;
        let inter = if horiz_seg {
            y0 > r.y0 + EPS && y0 < r.y1 - EPS && x0 < r.x1 - EPS && x1 > r.x0 + EPS
        } else {
            x0 > r.x0 + EPS && x0 < r.x1 - EPS && y0 < r.y1 - EPS && y1 > r.y0 + EPS
        };
        if !inter {
            continue;
        }
        // a horizontal border is crossed by vertical segments only
        if b.horiz == horiz_seg {
            return false;
        }
        let at = if horiz_seg { y0 } else { x0 };
        if at < b.lo - EPS || at > b.hi + EPS {
            return false;
        }
    }
    true
}

#[derive(Clone, Debug)]
pub struct Path {
    pub pts: Vec<(f64, f64)>,
    pub sa: Side,
    pub sb: Side,
    pub cost: f64,
}

fn uniq(mut v: Vec<f64>) -> Vec<f64> {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut o: Vec<f64> = Vec::new();
    for x in v {
        if o.last().map_or(true, |l| (x - *l).abs() > 1e-7) {
            o.push(x);
        }
    }
    o
}

#[derive(PartialEq)]
struct HeapItem {
    cost: f64,
    seq: u64,
    state: usize,
}
impl Eq for HeapItem {}
impl PartialOrd for HeapItem {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for HeapItem {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        // min-heap on cost, then on insertion order
        o.cost.partial_cmp(&self.cost).unwrap_or(std::cmp::Ordering::Equal).then(self.seq.cmp(&o.seq))
    }
}

// Port offsets per side of the two endpoints (default: side centre).
pub struct PortReq<'a> {
    pub sides_a: &'a [Side],
    pub sides_b: &'a [Side],
    // free width a channel must offer across every segment (bundles)
    pub need: f64,
}

// Free width across an axis-aligned segment: the gap between the inflated
// obstacles on either side over the segment's span.
pub fn free_width(solids: &[Rect], p: (f64, f64), q: (f64, f64)) -> f64 {
    let horiz = (p.1 - q.1).abs() < 1e-9;
    let (lo_s, hi_s) = if horiz { (p.0.min(q.0), p.0.max(q.0)) } else { (p.1.min(q.1), p.1.max(q.1)) };
    let pos = if horiz { p.1 } else { p.0 };
    let mut lo = f64::NEG_INFINITY;
    let mut hi = f64::INFINITY;
    for r in solids {
        let (a0, a1, b0, b1) = if horiz { (r.x0, r.x1, r.y0, r.y1) } else { (r.y0, r.y1, r.x0, r.x1) };
        if a0 < hi_s - EPS && a1 > lo_s + EPS {
            if b1 <= pos + EPS && b1 > lo {
                lo = b1;
            }
            if b0 >= pos - EPS && b0 < hi {
                hi = b0;
            }
        }
    }
    hi - lo
}

// The straight stub leaving an endpoint side: out of the endpoint's own
// clearance and through every container that holds only this end, ending
// the clearance beyond the outermost border. None when blocked.
pub fn stub(env: &Env, solids: &[Rect], bands: &[Band], first: bool, sd: Side) -> Option<((f64, f64), (f64, f64))> {
    let k = env.k;
    let node = if first { env.a } else { env.b };
    let other = if first { env.b } else { env.a };
    let wall_kind = if first { ObKind::WallA } else { ObKind::WallB };
    let p = side_point(&node, sd, 0.0);
    let d = sd.dir();
    let mut ext: f64 = 0.0;
    let mut walls: Vec<Rect> = Vec::new();
    for o in &env.obs {
        if o.kind != wall_kind {
            continue;
        }
        let w = o.r;
        let dist = match sd {
            Side::Right => w.x1 - p.0,
            Side::Left => p.0 - w.x0,
            Side::Bottom => w.y1 - p.1,
            Side::Top => p.1 - w.y0,
        };
        // the crossing keeps the clearance from the border's ends
        let (lo, hi, at) = if sd.horizontal() { (w.x0 + k, w.x1 - k, p.0) } else { (w.y0 + k, w.y1 - k, p.1) };
        if at < lo - EPS || at > hi + EPS {
            return None;
        }
        ext = ext.max(dist);
        walls.push(w.grow(k));
    }
    let len = ext + k;
    let e = (p.0 + d.0 * len, p.1 + d.1 * len);
    // clear of everything but the walls it crosses and its own node
    let own = node.grow(k);
    let others: Vec<Rect> = solids.iter().filter(|r| **r != own && !walls.contains(r)).cloned().collect();
    let _ = other;
    if !seg_clear(&others, p, e) || others.iter().any(|r| r.contains_open(e.0, e.1)) {
        return None;
    }
    if !seg_band_ok(bands, p, e) {
        return None;
    }
    Some((p, e))
}

// Find the cheapest orthogonal route: cost = length + 2K per bend.
pub fn search(env: &Env, req: &PortReq) -> Option<Path> {
    let k = env.k;
    let solids = env.solids();
    let bands = wall_bands(env);
    let a = env.a;
    let b = env.b;
    // grid lines
    let mut xs: Vec<f64> = Vec::new();
    let mut ys: Vec<f64> = Vec::new();
    for r in &solids {
        xs.push(r.x0);
        xs.push(r.x1);
        ys.push(r.y0);
        ys.push(r.y1);
    }
    for o in &env.obs {
        if o.kind == ObKind::WallBoth {
            let r = o.r;
            xs.push(r.x0 - k);
            xs.push(r.x0 + k);
            xs.push(r.x1 - k);
            xs.push(r.x1 + k);
            ys.push(r.y0 - k);
            ys.push(r.y0 + k);
            ys.push(r.y1 - k);
            ys.push(r.y1 + k);
        }
    }
    xs.push(a.cx());
    xs.push(b.cx());
    ys.push(a.cy());
    ys.push(b.cy());
    for (first, sides) in [(true, req.sides_a), (false, req.sides_b)] {
        for &sd in sides {
            if let Some((_, e)) = stub(env, &solids, &bands, first, sd) {
                xs.push(e.0);
                ys.push(e.1);
            }
        }
    }
    let xs = uniq(xs);
    let ys = uniq(ys);
    let nx = xs.len();
    let ny = ys.len();
    let xi = |x: f64| xs.iter().position(|v| (v - x).abs() < 1e-7);
    let yi = |y: f64| ys.iter().position(|v| (v - y).abs() < 1e-7);
    let vid = |i: usize, j: usize| j * nx + i;
    let nv = nx * ny;
    // vertex freedom
    let mut free = vec![true; nv];
    let mut banded = vec![false; nv];
    for j in 0..ny {
        for i in 0..nx {
            let (x, y) = (xs[i], ys[j]);
            if solids.iter().any(|r| r.contains_open(x, y)) {
                free[vid(i, j)] = false;
            }
            if in_band(&bands, x, y) {
                banded[vid(i, j)] = true;
            }
        }
    }
    // start / end stubs
    struct End {
        side: Side,
        port: (f64, f64),
        v: usize,
    }
    let mut starts: Vec<End> = Vec::new();
    for &sd in req.sides_a {
        if let Some((p, e)) = stub(env, &solids, &bands, true, sd) {
            let (Some(i), Some(j)) = (xi(e.0), yi(e.1)) else { continue };
            starts.push(End { side: sd, port: p, v: vid(i, j) });
        }
    }
    let mut ends: Vec<End> = Vec::new();
    for &sd in req.sides_b {
        if let Some((p, e)) = stub(env, &solids, &bands, false, sd) {
            let (Some(i), Some(j)) = (xi(e.0), yi(e.1)) else { continue };
            ends.push(End { side: sd, port: p, v: vid(i, j) });
        }
    }
    if starts.is_empty() || ends.is_empty() {
        return None;
    }
    // Dijkstra over (vertex, heading)
    let ns = nv * 4;
    let mut dist = vec![f64::INFINITY; ns];
    let mut prev = vec![usize::MAX; ns];
    let mut heap = BinaryHeap::new();
    let mut seq: u64 = 0;
    for (si, st) in starts.iter().enumerate() {
        let s = st.v * 4 + side_dir_idx(st.side);
        if k < dist[s] {
            dist[s] = k;
            prev[s] = usize::MAX - 1 - si;
            heap.push(HeapItem { cost: k, seq, state: s });
            seq += 1;
        }
    }
    let bend = 2.0 * k;
    let mut best: Option<(f64, usize, usize)> = None; // (cost, state, end idx)
    while let Some(HeapItem { cost, state, .. }) = heap.pop() {
        if cost > dist[state] + 1e-9 {
            continue;
        }
        if let Some((bc, _, _)) = best {
            if cost > bc + 1e-9 {
                break;
            }
        }
        let v = state / 4;
        let d = state % 4;
        let i = v % nx;
        let j = v / nx;
        // reaching an end
        for (ei, en) in ends.iter().enumerate() {
            if en.v == v {
                let need = (side_dir_idx(en.side) + 2) % 4;
                let c = cost + k + if d == need { 0.0 } else { bend };
                if d == (need + 2) % 4 {
                    continue;
                }
                if best.map_or(true, |(bc, _, _)| c < bc - 1e-9) {
                    best = Some((c, state, ei));
                }
            }
        }
        // moves
        for nd in 0..4 {
            if nd == (d + 2) % 4 {
                continue;
            }
            if nd != d && banded[v] {
                continue;
            }
            let (ni, nj) = match nd {
                0 => {
                    if i + 1 >= nx {
                        continue;
                    }
                    (i + 1, j)
                }
                1 => {
                    if j + 1 >= ny {
                        continue;
                    }
                    (i, j + 1)
                }
                2 => {
                    if i == 0 {
                        continue;
                    }
                    (i - 1, j)
                }
                _ => {
                    if j == 0 {
                        continue;
                    }
                    (i, j - 1)
                }
            };
            let nvx = vid(ni, nj);
            if !free[nvx] {
                continue;
            }
            let p = (xs[i], ys[j]);
            let q = (xs[ni], ys[nj]);
            if !seg_clear(&solids, p, q) || !seg_band_ok(&bands, p, q) {
                continue;
            }
            let fw = free_width(&solids, p, q);
            if fw <= 1e-9 || fw < req.need - 1e-9 {
                continue;
            }
            let len = (q.0 - p.0).abs() + (q.1 - p.1).abs();
            let nc = cost + len + if nd == d { 0.0 } else { bend };
            let ns2 = nvx * 4 + nd;
            if nc < dist[ns2] - 1e-9 {
                dist[ns2] = nc;
                prev[ns2] = state;
                heap.push(HeapItem { cost: nc, seq, state: ns2 });
                seq += 1;
            }
        }
    }
    let (cost, st, ei) = best?;
    // rebuild
    let mut verts: Vec<(f64, f64)> = Vec::new();
    let mut cur = st;
    let start_idx;
    loop {
        let v = cur / 4;
        verts.push((xs[v % nx], ys[v / nx]));
        let p = prev[cur];
        if p >= usize::MAX - 1 - starts.len() && p != usize::MAX {
            start_idx = usize::MAX - 1 - p;
            break;
        }
        if p == usize::MAX {
            return None;
        }
        cur = p;
    }
    verts.reverse();
    let mut pts = vec![starts[start_idx].port];
    pts.extend(verts);
    pts.push(ends[ei].port);
    let pts = simplify(&pts);
    Some(Path { pts, sa: starts[start_idx].side, sb: ends[ei].side, cost })
}

// Drop repeated and collinear interior points.
pub fn simplify(pts: &[(f64, f64)]) -> Vec<(f64, f64)> {
    let mut o: Vec<(f64, f64)> = Vec::new();
    for &p in pts {
        if let Some(l) = o.last() {
            if (l.0 - p.0).abs() < 1e-9 && (l.1 - p.1).abs() < 1e-9 {
                continue;
            }
        }
        o.push(p);
    }
    let mut i = 1;
    while i + 1 < o.len() {
        let (a, b, c) = (o[i - 1], o[i], o[i + 1]);
        let col = ((a.0 - b.0).abs() < 1e-9 && (b.0 - c.0).abs() < 1e-9) || ((a.1 - b.1).abs() < 1e-9 && (b.1 - c.1).abs() < 1e-9);
        if col {
            o.remove(i);
        } else {
            i += 1;
        }
    }
    o
}

pub fn seg_dir(p: (f64, f64), q: (f64, f64)) -> usize {
    dir_of(q.0 - p.0, q.1 - p.1)
}

// The channel a staircase segment slides in: between its neighbours' far
// ends and the inflated obstacles overlapping its whole span.
pub fn stair_interval(solids: &[Rect], pts: &[(f64, f64)], j: usize) -> (f64, f64) {
    let p = pts[j];
    let q = pts[j + 1];
    let vertical = (p.0 - q.0).abs() < 1e-9;
    let pos = if vertical { p.0 } else { p.1 };
    let (fa, fb) = if vertical { (pts[j - 1].0, pts[j + 2].0) } else { (pts[j - 1].1, pts[j + 2].1) };
    let mut lo = fa.min(fb);
    let mut hi = fa.max(fb);
    let (s0, s1) = if vertical { (p.1.min(q.1), p.1.max(q.1)) } else { (p.0.min(q.0), p.0.max(q.0)) };
    for r in solids {
        let (a0, a1, b0, b1) = if vertical { (r.y0, r.y1, r.x0, r.x1) } else { (r.x0, r.x1, r.y0, r.y1) };
        if a0 < s1 - EPS && a1 > s0 + EPS {
            if b1 <= pos + EPS && b1 > lo {
                lo = b1;
            }
            if b0 >= pos - EPS && b0 < hi {
                hi = b0;
            }
        }
    }
    (lo, hi)
}

// The interval a U-turn segment could slide in, judged beside its starting
// point: inflated obstacles bound it, a container border holding both ends
// leaves that side open. Infinite where open.
pub fn u_interval(env: &Env, solids: &[Rect], pts: &[(f64, f64)], j: usize) -> (f64, f64) {
    let p = pts[j];
    let q = pts[j + 1];
    let vertical = (p.0 - q.0).abs() < 1e-9;
    let pos = if vertical { p.0 } else { p.1 };
    let at = if vertical { p.1 } else { p.0 };
    let mut lo = f64::NEG_INFINITY;
    let mut hi = f64::INFINITY;
    for r in solids {
        let (a0, a1, b0, b1) = if vertical { (r.y0, r.y1, r.x0, r.x1) } else { (r.x0, r.x1, r.y0, r.y1) };
        if !(at > a0 + EPS && at < a1 - EPS) {
            continue;
        }
        if b1 <= pos + EPS && b1 > lo {
            lo = b1;
        }
        if b0 >= pos - EPS && b0 < hi {
            hi = b0;
        }
    }
    for o in &env.obs {
        if o.kind != ObKind::WallBoth {
            continue;
        }
        let r = o.r;
        let (a0, a1, b0, b1) = if vertical { (r.y0, r.y1, r.x0, r.x1) } else { (r.x0, r.x1, r.y0, r.y1) };
        if !(at > a0 + EPS && at < a1 - EPS) {
            continue;
        }
        // a border between the segment and a bound opens that side
        if b0 < pos && b0 > lo {
            lo = f64::NEG_INFINITY;
        }
        if b1 > pos && b1 < hi {
            hi = f64::INFINITY;
        }
    }
    (lo, hi)
}

pub fn is_u(pts: &[(f64, f64)], j: usize) -> bool {
    let d0 = seg_dir(pts[j - 1], pts[j]);
    let d2 = seg_dir(pts[j + 1], pts[j + 2]);
    d0 == (d2 + 2) % 4
}

// Free segments settle in their channel: staircases midway across their
// span; U-turns midway when boxed in beside their start, else they keep
// hugging what they go around.
pub fn centre_staircases(env: &Env, pts: &mut Vec<(f64, f64)>) {
    let solids = env.solids();
    let n = pts.len();
    if n < 4 {
        return;
    }
    for i in 1..n - 2 {
        // a simple U between the two end stubs always hugs
        if is_u(pts, i) && n == 4 {
            continue;
        }
        let (lo, hi) = if is_u(pts, i) { u_interval(env, &solids, pts, i) } else { stair_interval(&solids, pts, i) };
        if !lo.is_finite() || !hi.is_finite() {
            continue;
        }
        let m = (lo + hi) / 2.0;
        let vertical = (pts[i].0 - pts[i + 1].0).abs() < 1e-9;
        if vertical {
            pts[i].0 = m;
            pts[i + 1].0 = m;
        } else {
            pts[i].1 = m;
            pts[i + 1].1 = m;
        }
    }
}

// Natural routing: an S-curve between two facing side centres (the
// dominant axis between the centres picks the sides).
pub fn natural(a: &Rect, b: &Rect, req: &crate::wires::LinkReq) -> (Vec<(f64, f64)>, [(f64, f64); 4], Side, Side) {
    let dx = b.cx() - a.cx();
    let dy = b.cy() - a.cy();
    let (sa, sb) = if dx.abs() >= dy.abs() {
        if dx >= 0.0 {
            (Side::Right, Side::Left)
        } else {
            (Side::Left, Side::Right)
        }
    } else if dy >= 0.0 {
        (Side::Bottom, Side::Top)
    } else {
        (Side::Top, Side::Bottom)
    };
    let s = side_point(a, sa, 0.0);
    let e = side_point(b, sb, 0.0);
    let ds = sa.dir();
    let de = sb.dir();
    let stub_s = if req.mark_len_s > 0.0 { req.mark_len_s } else { 2.0 };
    let stub_e = if req.mark_len_e > 0.0 { req.mark_len_e } else { 2.0 };
    let s1 = (s.0 + ds.0 * stub_s, s.1 + ds.1 * stub_s);
    let e1 = (e.0 + de.0 * stub_e, e.1 + de.1 * stub_e);
    let dist = ((e1.0 - s1.0).powi(2) + (e1.1 - s1.1).powi(2)).sqrt();
    let along = if sa.horizontal() { (e1.1 - s1.1).abs() } else { (e1.0 - s1.0).abs() };
    let h = (dist / 2.0).min(along.max(dist / 4.0));
    let c1 = (s1.0 + ds.0 * h, s1.1 + ds.1 * h);
    let c2 = (e1.0 + de.0 * h, e1.1 + de.1 * h);
    (vec![s, e], [s1, c1, c2, e1], sa, sb)
}
