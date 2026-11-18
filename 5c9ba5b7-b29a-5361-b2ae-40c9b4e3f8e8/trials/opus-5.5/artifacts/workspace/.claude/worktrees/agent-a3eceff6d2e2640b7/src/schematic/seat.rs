// Satellites seated at the pins their wires touch. A chain leaves an anchor
// pin along the pin's facing: an element posed along that ray stands in the
// pin's row, clear of the anchor by a pin pitch; an element posed across it
// turns the chain into a lane — a lattice column off the pin, clear of the
// anchor by a pitch past the lattice cells the element covers (a part keeps
// half the scope's gap besides) — and stacks along it, clear of every wired
// pin row it passes on that side. Each next element clears the one before by
// a pitch. Every seated point sits on the lattice: a part's or a tag's
// centre, a symbol's connection point.
//
// The lanes of a side start together, at the outermost lane any of its
// chains needs. Pins whose chains run up go first, top pin first; then the
// pins whose chains run down, bottom pin first. On one pin the parts' chains
// take their lanes in declaration order, each at the innermost lane it fits
// (an up and a down chain share one); a chain of labels alone starts at the
// outermost lane the pin already uses.

use super::net::{origin_in, Dir, Kind, Term, Wire};
use super::place::{ceil_lattice, is_part, PITCH};
use crate::compile::Ctx;

// a satellite's placement, anchor-local
#[derive(Clone, Debug)]
pub struct Seat {
    pub node: usize,
    pub x: f64,
    pub y: f64,
    // the lattice cells it reserves (x0, y0, x1, y1), anchor-local
    pub res: [f64; 4],
    // a part stood in a pin's row reads its labels: -1 stacked above, +1
    // stacked below, 0 split
    pub stack: i8,
    // the facing of the pin its lane leaves (labels stand on the far side)
    pub side: Option<Dir>,
}

// the extent of a node's own box (stroke included) around its origin
pub fn body(ctx: &Ctx, i: usize) -> [f64; 4] {
    let n = &ctx.nodes[i];
    let (ow, oh) = crate::layout::outer(ctx, i);
    let (cx, cy) = (-n.geo_off.0, -n.geo_off.1);
    [cx - ow / 2.0, cy - oh / 2.0, cx + ow / 2.0, cy + oh / 2.0]
}

// the half-extent of the lattice cells covering a reach `d` past a lattice
// line (cell edges sit halfway between lattice lines)
pub fn cell_half(d: f64) -> f64 {
    if d <= PITCH / 2.0 + 1e-9 {
        PITCH / 2.0
    } else {
        PITCH / 2.0 + PITCH * ((d - PITCH / 2.0) / PITCH - 1e-9).ceil()
    }
}

pub fn sgn(d: Dir) -> f64 {
    match d {
        Dir::R | Dir::D => 1.0,
        _ => -1.0,
    }
}

// the coordinate of a point along d's axis
pub fn coord(d: Dir, p: (f64, f64)) -> f64 {
    if d.horizontal() {
        p.0
    } else {
        p.1
    }
}

// the first lattice coordinate at or past `v` going `d`
pub fn snap_out(d: Dir, v: f64) -> f64 {
    if sgn(d) > 0.0 {
        ceil_lattice(v)
    } else {
        -ceil_lattice(-v)
    }
}

// a box's reach behind and ahead of a point along `d`
fn reach(b: &[f64; 4], p: (f64, f64), d: Dir) -> (f64, f64) {
    match d {
        Dir::R => (p.0 - b[0], b[2] - p.0),
        Dir::L => (b[2] - p.0, p.0 - b[0]),
        Dir::D => (p.1 - b[1], b[3] - p.1),
        Dir::U => (b[3] - p.1, p.1 - b[1]),
    }
}

// the station a part leaves by, entered at `t`
pub fn exit_of(ctx: &Ctx, t: &Term) -> Option<Term> {
    if t.kind != Kind::Station {
        return None;
    }
    for &c in &ctx.nodes[t.dev].children {
        if c != t.node && ctx.nodes[c].id.is_some() && ctx.comp[c].pin.as_deref() == Some("center") {
            let o = origin_in(ctx, c, t.dev);
            return Some(Term { node: c, dev: t.dev, kind: Kind::Station, off: o, dir: Dir::of_vec(o.0, o.1), through: None });
        }
    }
    None
}

// the way a wire travels on entering `t`'s element
pub fn travel(ctx: &Ctx, t: &Term) -> Dir {
    match t.kind {
        Kind::Station => match exit_of(ctx, t) {
            Some(o) => Dir::of_vec(o.off.0 - t.off.0, o.off.1 - t.off.1),
            None => t.dir.opposite(),
        },
        _ => t.dir.opposite(),
    }
}

// the point of an element that sits on the lattice: a part's or a tag's
// centre, a symbol's connection point
fn lattice_point(t: &Term) -> (f64, f64) {
    match t.kind {
        Kind::Symbol => t.off,
        _ => (0.0, 0.0),
    }
}

fn overlaps(a: &[f64; 4], b: &[f64; 4]) -> bool {
    a[0] < b[2] - 1e-9 && b[0] < a[2] - 1e-9 && a[1] < b[3] - 1e-9 && b[1] < a[3] - 1e-9
}

pub fn is_satellite(ctx: &Ctx, i: usize) -> bool {
    super::place::role(ctx, i) == super::place::Role::Satellite
}

// one chain's planned elements
#[derive(Clone, Debug)]
struct Plan {
    pin: usize,
    f: Dir,
    d1: Dir,
    row: f64,
    // elements with the lane at 0 (turned) or final (straight)
    els: Vec<(usize, f64, f64, [f64; 4])>,
    // the first wire's run along the lane: (from, to) on the lane's axis
    run: (f64, f64),
    min_lane: f64,
    key: usize,
    parts: bool,
}

// a turned chain's first hop: (pin node, pin term, entry term, the pin's
// facing, the travel, the pin's row, the first element's lattice coordinate)
pub type Turn = (usize, Term, Term, Dir, Dir, f64, f64, bool);

// a chain standing in its pin's row: the facing, its first element's lattice
// coordinate along it, its elements as planned (the first at `a`)
#[derive(Clone, Debug)]
pub struct Straight {
    pub f: Dir,
    pub a: f64,
    pub els: Vec<(usize, f64, f64, [f64; 4])>,
    pub stack: i8,
    // the pin's coordinate across the facing (the side's order)
    pub row: f64,
    pub parts: bool,
    // a no-connect cross keeps its own place
    pub aligns: bool,
    pub pin: usize,
    // the first element's reach behind its lattice point
    pub behind: f64,
    // the pin also turns chains into lanes on this side: the chain stands
    // past them, seated after the lanes
    pub deferred: bool,
}

pub struct Seater<'a> {
    pub ctx: &'a Ctx,
    pub wires: &'a [Wire],
    pub gap: f64,
    // per device: its origin, anchor-local (NaN: seated by another anchor)
    pub placed: std::collections::HashMap<usize, (f64, f64)>,
    pub seats: Vec<Seat>,
    aext: [f64; 4],
    straight: Vec<[f64; 4]>,
    deferred: Vec<Straight>,
    // the first parts of the anchor's chains: another chain's walk ends
    // there (a tap)
    claimed: Vec<usize>,
}

impl<'a> Seater<'a> {
    pub fn new(ctx: &'a Ctx, wires: &'a [Wire], gap: f64) -> Self {
        Seater { ctx, wires, gap, placed: Default::default(), seats: vec![], aext: [0.0; 4], straight: vec![], deferred: vec![], claimed: vec![] }
    }

    pub fn gap_margin(&self) -> f64 {
        PITCH / 2.0 + PITCH * (self.gap / (2.0 * PITCH)).floor()
    }

    // the lattice cells an element at (x, y) reserves; a part in a lane keeps
    // the gap margin across the lane (`lane`: the pin's facing)
    fn reserve(&self, dev: usize, x: f64, y: f64, lp: (f64, f64), lane: Option<Dir>) -> [f64; 4] {
        let b = body(self.ctx, dev);
        let (px, py) = (x + lp.0, y + lp.1);
        let (x0, x1) = (px - cell_half(px - (x + b[0])), px + cell_half(x + b[2] - px));
        let (y0, y1) = (py - cell_half(py - (y + b[1])), py + cell_half(y + b[3] - py));
        let mut r = [x0, y0, x1, y1];
        if let Some(f) = lane {
            if is_part(self.ctx, dev) {
                let m = self.gap_margin();
                if f.horizontal() {
                    r[0] = r[0].min(px - m);
                    r[2] = r[2].max(px + m);
                } else {
                    r[1] = r[1].min(py - m);
                    r[3] = r[3].max(py + m);
                }
            }
        }
        r
    }

    // the lattice cells of an element in a pin's row: its body and its
    // value and reference as they will stand (stacked or split)
    fn reserve_row(&self, dev: usize, x: f64, y: f64, lp: (f64, f64), stack: i8) -> [f64; 4] {
        let ctx = self.ctx;
        let mut b = body(ctx, dev);
        let (rot, _) = super::net::pose_of(ctx, dev);
        if is_part(ctx, dev) && (rot == 90 || rot == 270) {
            let e = super::place::extent(ctx, dev);
            b = [b[0].min(e[0]), b[1].min(e[1]), b[2].max(e[2]), b[3].max(e[3])];
        }
        if is_part(ctx, dev) && rot != 90 && rot != 270 {
            let h = ctx.nodes[dev].h;
            let mut val = None;
            let mut rf = None;
            for &k in &ctx.nodes[dev].children {
                if super::place::has(ctx, k, "part-value") {
                    val = Some(k);
                } else if super::place::has(ctx, k, "ref") {
                    rf = Some(k);
                }
            }
            let size = |k: usize| crate::layout::outer(ctx, k);
            let mut add = |k: usize, cy: f64| {
                let (w, lh) = size(k);
                b[0] = b[0].min(-w / 2.0);
                b[2] = b[2].max(w / 2.0);
                b[1] = b[1].min(cy - lh / 2.0);
                b[3] = b[3].max(cy + lh / 2.0);
            };
            match stack {
                -1 => {
                    let mut at = -h / 2.0;
                    for k in [val, rf].into_iter().flatten() {
                        let lh = size(k).1;
                        let cy = if at == -h / 2.0 { at - (20.0 - lh / 2.0) } else { at - 16.0 };
                        add(k, cy);
                        at = cy;
                    }
                }
                1 => {
                    let mut at = h / 2.0;
                    for k in [rf, val].into_iter().flatten() {
                        let lh = size(k).1;
                        let cy = if at == h / 2.0 { at + (20.0 - lh / 2.0) } else { at + 16.0 };
                        add(k, cy);
                        at = cy;
                    }
                }
                _ => {
                    if let Some(k) = rf {
                        let lh = size(k).1;
                        add(k, -h / 2.0 - (20.0 - lh / 2.0));
                    }
                    if let Some(k) = val {
                        let lh = size(k).1;
                        add(k, h / 2.0 + (20.0 - lh / 2.0));
                    }
                }
            }
        }
        let (px, py) = (x + lp.0, y + lp.1);
        let (x0, x1) = (px - cell_half(px - (x + b[0])), px + cell_half(x + b[2] - px));
        let (y0, y1) = (py - cell_half(py - (y + b[1])), py + cell_half(y + b[3] - py));
        [x0, y0, x1, y1]
    }

    fn put(&mut self, dev: usize, x: f64, y: f64, res: [f64; 4], stack: i8, side: Option<Dir>) {
        self.placed.insert(dev, (x, y));
        self.seats.push(Seat { node: dev, x, y, res, stack, side });
    }

    // the elements past the one at (sx, sy) entered at `q`, travelling `d`
    // (planned, not yet seated): appended to `els`
    fn walk(&self, q: &Term, sx: f64, sy: f64, d: Dir, lane: Option<Dir>, els: &mut Vec<(usize, f64, f64, [f64; 4])>, seen: &mut Vec<usize>) {
        let ctx = self.ctx;
        let exit = match q.kind {
            Kind::Station => match exit_of(ctx, q) {
                Some(e) => e,
                None => return,
            },
            _ => q.clone(),
        };
        let sb = body(ctx, q.dev);
        let sbox = [sx + sb[0], sy + sb[1], sx + sb[2], sy + sb[3]];
        let ep = (sx + exit.off.0, sy + exit.off.1);
        let nexts: Vec<Term> = self
            .wires
            .iter()
            .filter_map(|w| {
                if w.a.node == exit.node && w.b.dev != q.dev {
                    Some(w.b.clone())
                } else if w.b.node == exit.node && w.a.dev != q.dev {
                    Some(w.a.clone())
                } else {
                    None
                }
            })
            .collect();
        for t in nexts {
            if self.placed.contains_key(&t.dev) || seen.contains(&t.dev) || !is_satellite(ctx, t.dev) {
                continue;
            }
            let t = super::net::flag_end(ctx, &t, d.opposite());
            let d2 = if t.kind == Kind::Flag { d } else { travel(ctx, &t) };
            if d2 != d {
                continue;
            }
            let b = body(ctx, t.dev);
            let lp = lattice_point(&t);
            let far = match d {
                Dir::R => sbox[2],
                Dir::L => -sbox[0],
                Dir::D => sbox[3],
                Dir::U => -sbox[1],
            };
            let (behind, _) = reach(&b, lp, d);
            let a = snap_out(d, sgn(d) * (far + PITCH + behind));
            let (x, y) = if d.horizontal() { (a - lp.0, ep.1 - t.off.1) } else { (ep.0 - t.off.0, a - lp.1) };
            let res = self.reserve(t.dev, x, y, lp, lane);
            seen.push(t.dev);
            els.push((t.dev, x, y, res));
            self.walk(&t, x, y, d2, lane, els, seen);
        }
    }

    // Seat the chains leaving an anchor: `aext` its drawn extent, `hops` the
    // first wires off its pins (pin node, pin term, far term), `wired` every
    // wired pin of it (term).
    pub fn seat_first(&mut self, aext: [f64; 4], hops: &[(usize, Term, Term)], wired: &[Term]) -> (Vec<Straight>, Vec<Turn>) {
        let ctx = self.ctx;
        self.aext = aext;
        let mut straight: Vec<Straight> = Vec::new();
        let mut turned: Vec<Turn> = Vec::new();
        self.claimed = hops.iter().map(|h| h.2.dev).collect();
        for (pin, p, q0) in hops {
            if self.placed.contains_key(&q0.dev)
                || turned.iter().any(|t| t.2.dev == q0.dev)
                || straight.iter().any(|s| s.els.iter().any(|e| e.0 == q0.dev))
            {
                continue;
            }
            let f = p.dir;
            let ext = match f {
                Dir::R => aext[2],
                Dir::L => -aext[0],
                Dir::D => aext[3],
                Dir::U => -aext[1],
            };
            let q = super::net::flag_end(ctx, q0, f.opposite());
            let d1 = if q.kind == Kind::Flag { f } else { travel(ctx, &q) };
            let b = body(ctx, q.dev);
            let lp = lattice_point(&q);
            if d1 == f {
                // straight: in the pin's row, labels away from the side's other pins
                // (a symbol's line reaching back past its point aside)
                let (mut behind, _) = reach(&b, lp, f);
                if q.kind == Kind::Symbol {
                    behind = (behind - 0.75).max(0.0);
                }
                let a = snap_out(f, sgn(f) * (ext + PITCH + behind));
                let (x, y) = if f.horizontal() { (a - lp.0, p.off.1 - q.off.1) } else { (p.off.0 - q.off.0, a - lp.1) };
                let stack = stack_mode(ctx, p, wired, *pin);
                let res = self.reserve_row(q.dev, x, y, lp, stack);
                if std::env::var("LINI_SCH_DBG").is_ok() {
                    eprintln!("first {} body {:?} at {} {} lp {:?} res {:?} w {} h {}", q.dev, b, x, y, lp, res, ctx.nodes[q.dev].w, ctx.nodes[q.dev].h);
                }
                let mut els = vec![(q.dev, x, y, res)];
                let mut seen: Vec<usize> = vec![q.dev];
                for s in &straight {
                    seen.extend(s.els.iter().map(|e| e.0));
                }
                seen.extend(self.claimed.iter().cloned().filter(|&d| d != q.dev));
                self.walk(&q, x, y, d1, None, &mut els, &mut seen);
                let row = if f.horizontal() { p.off.1 } else { p.off.0 };
                let parts = els.iter().any(|e| is_part(ctx, e.0));
                let aligns = crate::render::prop_str(ctx, q.dev, "symbol").as_deref() != Some("nc");
                straight.push(Straight { f, a, els, stack, row, parts, aligns, pin: *pin, behind, deferred: false });
                continue;
            }
            if d1 == f.opposite() {
                continue;
            }
            // turned: the chain stands in a lane, clear of the wired rows it
            // passes on this side; a chain running into another pin's chain
            // (a tapped bridge) straddles that pin's row: it clears its own
            // row alone and keeps out of the row its side's first parts share
            let row = coord(d1, p.off);
            let tapped = self.taps(&q);
            let mut clear = row;
            for w in wired {
                if w.dir != f || tapped {
                    continue;
                }
                let r = coord(d1, w.off);
                if sgn(d1) * (r - clear) > 0.0 {
                    clear = r;
                }
            }
            let (behind, _) = reach(&b, lp, d1);
            let a = snap_out(d1, clear + sgn(d1) * (PITCH + behind));
            turned.push((*pin, p.clone(), q.clone(), f, d1, row, a, !tapped));
        }
        for st in straight.iter_mut() {
            if turned.iter().any(|t| t.0 == st.pin && t.3 == st.f) {
                st.deferred = true;
                st.aligns = false;
            }
        }
        (straight, turned)
    }

    // does the chain entered at `q` run into another chain's first part?
    fn taps(&self, q: &Term) -> bool {
        let ctx = self.ctx;
        let mut cur = q.clone();
        let mut seen = vec![q.dev];
        for _ in 0..64 {
            let exit = match q.kind {
                Kind::Station => match exit_of(ctx, &cur) {
                    Some(e) => e,
                    None => return false,
                },
                _ => return false,
            };
            let mut next: Option<Term> = None;
            for w in self.wires {
                for (u, v) in [(&w.a, &w.b), (&w.b, &w.a)] {
                    if u.node == exit.node && v.dev != cur.dev && !seen.contains(&v.dev) && next.is_none() {
                        next = Some(v.clone());
                    }
                }
            }
            let n = match next {
                Some(n) => n,
                None => return false,
            };
            if self.claimed.contains(&n.dev) {
                return true;
            }
            if n.kind != Kind::Station || !is_satellite(ctx, n.dev) {
                return false;
            }
            seen.push(n.dev);
            cur = n;
        }
        false
    }

    // the chains standing in their pins' rows, their first elements aligned:
    // the chains holding parts first, then those of labels alone, each in
    // its side's pin order; a chain whose cells meet those of one seated
    // before, or whose keep meets a seated keep (a part stood on end keeps
    // the gap margin to either side; anything else keeps its cells), steps
    // down (across a row) or right (across a column) a pitch at a time
    pub fn seat_straight(&mut self, straight: Vec<Straight>, a_of: &[f64]) {
        let ctx = self.ctx;
        let m = self.gap_margin();
        let mut order: Vec<usize> = (0..straight.len()).collect();
        // the chains holding parts in their parts' declaration order, then
        // the chains of labels alone
        let key = |s: &Straight| -> (bool, usize) {
            let first_part = s.els.iter().map(|e| e.0).find(|&d| is_part(ctx, d));
            (!s.parts, first_part.unwrap_or(s.els[0].0))
        };
        order.sort_by(|&i, &j| key(&straight[i]).cmp(&key(&straight[j])));
        let mut cells: Vec<[f64; 4]> = Vec::new();
        let mut keeps: Vec<[f64; 4]> = Vec::new();
        for k in order {
            let s = &straight[k];
            if s.deferred {
                self.deferred.push(s.clone());
                continue;
            }
            let dv = a_of[k] - s.a;
            // (cells, keep) at the aligned place
            let boxes: Vec<([f64; 4], [f64; 4])> = s
                .els
                .iter()
                .map(|&(dev, x, y, res)| {
                    let r = shift_box(&res, s.f, dv);
                    let (rot, _) = super::net::pose_of(ctx, dev);
                    let keep = if is_part(ctx, dev) && (rot == 90 || rot == 270) && !s.f.horizontal() {
                        [x - m, r[1], x + m, r[3]]
                    } else {
                        r
                    };
                    let _ = y;
                    (r, keep)
                })
                .collect();
            let across = |b: &[f64; 4], d: f64| -> [f64; 4] {
                if s.f.horizontal() {
                    [b[0], b[1] + d, b[2], b[3] + d]
                } else {
                    [b[0] + d, b[1], b[2] + d, b[3]]
                }
            };
            if std::env::var("LINI_SCH_DBG").is_ok() {
                eprintln!("straight f {:?} a {} row {} parts {} boxes {:?} cells {:?} keeps {:?}", s.f, a_of[k], s.row, s.parts, boxes, cells, keeps);
            }
            // a part stepped down out of its pin's row reads its labels below
            let stepped: Vec<([f64; 4], [f64; 4])> = s
                .els
                .iter()
                .zip(boxes.iter())
                .map(|(&(dev, x, y, _), &(r, kp))| {
                    if s.f.horizontal() && is_part(ctx, dev) && s.stack != 1 {
                        let r2 = self.reserve_row(dev, x + dv, y, (0.0, 0.0), 1);
                        (r2, if kp == r { r2 } else { kp })
                    } else {
                        (r, kp)
                    }
                })
                .collect();
            let mut off = 0.0;
            for _ in 0..400 {
                let bx = if off > 0.0 { &stepped } else { &boxes };
                let hit = bx.iter().any(|(r, kp)| {
                    let (r, kp) = (across(r, off), across(kp, off));
                    cells.iter().any(|o| overlaps(&r, o)) || keeps.iter().any(|o| overlaps(&kp, o))
                });
                if !hit {
                    break;
                }
                off += PITCH;
            }
            let stack = if off > 0.0 && s.f.horizontal() { 1 } else { s.stack };
            let bx = if off > 0.0 { &stepped } else { &boxes };
            for (e, (r, kp)) in s.els.iter().zip(bx.iter()) {
                let (x, y) = if s.f.horizontal() { (e.1 + dv, e.2 + off) } else { (e.1 + off, e.2 + dv) };
                let (r, kp) = (across(r, off), across(kp, off));
                cells.push(r);
                keeps.push(kp);
                // the scope's hull takes both
                let u = [r[0].min(kp[0]), r[1].min(kp[1]), r[2].max(kp[2]), r[3].max(kp[3])];
                self.put(e.0, x, y, u, stack, None);
            }
        }
        self.straight = cells;
    }

    // the turned chains, their first elements already aligned: lanes
    pub fn seat_lanes(&mut self, turned: Vec<Turn>) {
        let ctx = self.ctx;
        let aext = self.aext;
        let straight_boxes = self.straight.clone();
        let mut plans: Vec<Plan> = Vec::new();
        for (pin, _p, q, f, d1, row, a, _) in turned {
            let b = body(ctx, q.dev);
            let lp = lattice_point(&q);
            let ext = match f {
                Dir::R => aext[2],
                Dir::L => -aext[0],
                Dir::D => aext[3],
                Dir::U => -aext[1],
            };
            // the entry point on lane 0
            let (x, y) = if f.horizontal() { (-q.off.0, a - lp.1) } else { (a - lp.0, -q.off.1) };
            let res = self.reserve(q.dev, x, y, lp, Some(f));
            let mut els = vec![(q.dev, x, y, res)];
            let mut seen = vec![q.dev];
            seen.extend(self.claimed.iter().cloned().filter(|&d| d != q.dev));
            self.walk(&q, x, y, d1, Some(f), &mut els, &mut seen);
            // the lane clears the anchor by a pitch past what it reserves
            let mut near: f64 = 0.0;
            for e in &els {
                let n = match f {
                    Dir::R => -e.3[0],
                    Dir::L => e.3[2],
                    Dir::D => -e.3[1],
                    Dir::U => e.3[3],
                };
                near = near.max(n);
            }
            let _ = b;
            let min_lane = snap_out(f, sgn(f) * (ext + PITCH + near));
            let entry = coord(d1, (x + q.off.0, y + q.off.1));
            let parts = is_part(ctx, q.dev) || els.iter().any(|e| is_part(ctx, e.0));
            plans.push(Plan { pin, f, d1, row, els, run: (row.min(entry), row.max(entry)), min_lane, key: q.dev, parts });
        }
        // the lanes, side by side
        let mut lane_cells: Vec<(usize, Dir, (f64, f64), [f64; 4])> = Vec::new();
        for f in [Dir::L, Dir::R, Dir::U, Dir::D] {
            let mine: Vec<usize> = (0..plans.len()).filter(|&k| plans[k].f == f).collect();
            if mine.is_empty() {
                continue;
            }
            let base = mine.iter().map(|&k| plans[k].min_lane).fold(if sgn(f) > 0.0 { f64::NEG_INFINITY } else { f64::INFINITY }, |a, b| if sgn(f) > 0.0 { a.max(b) } else { a.min(b) });
            // pins whose chains all run toward the lower coordinate first,
            // nearest that end first; then the others, from the far end
            let mut pins: Vec<(usize, Dir, f64)> = Vec::new();
            for &k in &mine {
                let pl = &plans[k];
                match pins.iter_mut().find(|p| p.0 == pl.pin) {
                    Some(p) => {
                        if sgn(pl.d1) > 0.0 {
                            p.1 = pl.d1;
                        }
                    }
                    None => pins.push((pl.pin, pl.d1, pl.row)),
                }
            }
            pins.sort_by(|a, b| {
                let ka = if sgn(a.1) < 0.0 { (0, a.2) } else { (1, -a.2) };
                let kb = if sgn(b.1) < 0.0 { (0, b.2) } else { (1, -b.2) };
                ka.partial_cmp(&kb).unwrap_or(std::cmp::Ordering::Equal)
            });
            let mut boxes: Vec<[f64; 4]> = straight_boxes.clone();
            let mut runs: Vec<(f64, (f64, f64))> = Vec::new();
            for (pin, _, _) in pins {
                let mut chains: Vec<usize> = mine.iter().cloned().filter(|&k| plans[k].pin == pin).collect();
                chains.sort_by_key(|&k| (!plans[k].parts, plans[k].key));
                let mut outer: Option<f64> = None;
                for k in chains {
                    let pl = plans[k].clone();
                    let start = if pl.parts { base } else { outer.unwrap_or(base) };
                    let mut lane = start;
                    for _ in 0..200 {
                        let shifted: Vec<[f64; 4]> = pl.els.iter().map(|e| shift_box(&e.3, f, lane)).collect();
                        let hit_box = shifted.iter().any(|r| boxes.iter().any(|o| overlaps(r, o)));
                        let hit_run = runs.iter().any(|(l, (a, b))| (*l - lane).abs() < 1e-9 && pl.run.0 < *b - 1e-9 && *a < pl.run.1 - 1e-9);
                        // the lane's own wire passes no seated element
                        let hit_wire = boxes.iter().any(|o| {
                            let (c0, c1, a0, a1) = if f.horizontal() { (o[0], o[2], o[1], o[3]) } else { (o[1], o[3], o[0], o[2]) };
                            lane > c0 + 1e-9 && lane < c1 - 1e-9 && a0 < pl.run.1 - 1e-9 && pl.run.0 < a1 - 1e-9
                        });
                        if !hit_box && !hit_run && !hit_wire {
                            break;
                        }
                        lane += sgn(f) * PITCH;
                    }
                    for e in &pl.els {
                        let r = shift_box(&e.3, f, lane);
                        boxes.push(r);
                        let (x, y) = if f.horizontal() { (e.1 + lane, e.2) } else { (e.1, e.2 + lane) };
                        self.put(e.0, x, y, r, 0, Some(f));
                        lane_cells.push((pl.pin, f, pl.run, r));
                    }
                    runs.push((lane, pl.run));
                    // a chain of labels alone starts at the outermost lane of
                    // the pin's parts
                    if pl.parts {
                        outer = Some(match outer {
                            Some(o) if sgn(f) * (o - lane) > 0.0 => o,
                            _ => lane,
                        });
                    }
                }
            }
        }
        // chains in the rows of pins that also turn lanes stand a pitch past
        // the cells of those lanes (and of any lane crossing their row)
        for st in std::mem::take(&mut self.deferred) {
            let f = st.f;
            let mut far: Option<f64> = None;
            for (pin, lf, run, r) in &lane_cells {
                if *lf != f || !(*pin == st.pin || (run.0 < st.row - 1e-9 && st.row < run.1 + 1e-9)) {
                    continue;
                }
                let e = match f {
                    Dir::R => r[2],
                    Dir::L => -r[0],
                    Dir::D => r[3],
                    Dir::U => -r[1],
                };
                far = Some(far.map_or(e, |v: f64| v.max(e)));
            }
            let a = match far {
                Some(v) => snap_out(f, sgn(f) * (v + PITCH + st.behind)),
                None => st.a,
            };
            let a = if sgn(f) * (a - st.a) > 0.0 { a } else { st.a };
            let dv = a - st.a;
            for &(dev, x, y, res) in &st.els {
                let (x, y) = if f.horizontal() { (x + dv, y) } else { (x, y + dv) };
                let res = shift_box(&res, f, dv);
                self.put(dev, x, y, res, st.stack, None);
            }
        }
    }
}

// the first elements of chains turning one way stand in one row
pub fn align(turns: &mut [&mut Turn], dirs: &[Dir]) {
    for &d in dirs {
        let mut deepest: Option<f64> = None;
        for t in turns.iter() {
            if t.4 == d && t.7 {
                deepest = Some(match deepest {
                    Some(v) if sgn(d) * (v - t.6) >= 0.0 => v,
                    _ => t.6,
                });
            }
        }
        if let Some(v) = deepest {
            for t in turns.iter_mut() {
                if t.4 == d && t.7 {
                    t.6 = v;
                }
            }
        }
    }
}

fn side_rank(f: Dir) -> u8 {
    match f {
        Dir::L => 0,
        Dir::R => 1,
        Dir::U => 2,
        Dir::D => 3,
    }
}

fn shift_box(r: &[f64; 4], f: Dir, lane: f64) -> [f64; 4] {
    if f.horizontal() {
        [r[0] + lane, r[1], r[2] + lane, r[3]]
    } else {
        [r[0], r[1] + lane, r[2], r[3] + lane]
    }
}

// a part in a pin's row reads its labels away from the side's other pins:
// above at the top pin, below at the bottom pin, split between
fn stack_mode(ctx: &Ctx, p: &Term, _wired: &[Term], _pin: usize) -> i8 {
    if !p.dir.horizontal() {
        return 0;
    }
    // the anchor's pins on this side
    let mut ys: Vec<f64> = Vec::new();
    for k in super::place::pins_of(ctx, p.dev) {
        if let Some(t) = super::net::term(ctx, ctx.nodes[p.dev].parent.unwrap_or(0), k) {
            if t.dir == p.dir {
                ys.push(t.off.1);
            }
        }
    }
    if ys.len() < 2 {
        return 0;
    }
    let lo = ys.iter().cloned().fold(f64::INFINITY, f64::min);
    let hi = ys.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    if (p.off.1 - lo).abs() < 1e-9 {
        -1
    } else if (p.off.1 - hi).abs() < 1e-9 {
        1
    } else {
        0
    }
}
