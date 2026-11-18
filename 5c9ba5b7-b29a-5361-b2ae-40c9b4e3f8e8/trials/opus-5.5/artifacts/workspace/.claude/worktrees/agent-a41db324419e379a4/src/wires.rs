// Wire planning on top of the single-route search: links between the same
// two nodes travel as a bundle (one route, spread ports, stacked tracks),
// then corners get their radii.

use crate::compile::Ctx;
use crate::links::{Routed, World};
use crate::route::*;

#[derive(Clone, Debug)]
pub struct LinkReq {
    pub from: usize,
    pub to: usize,
    pub anchor_a: Option<Side>,
    pub anchor_b: Option<Side>,
    pub k: f64,
    pub radius: f64,
    pub routing: String,
    pub stmt: usize,
    // marker pull-back from the boundary point (0: none)
    pub pull_s: f64,
    pub pull_e: f64,
    // marker glyph length at each end (0: no marker)
    pub mark_len_s: f64,
    pub mark_len_e: f64,
    // a cell the end was promoted from: its port lines up with the cell
    pub cell_a: Option<usize>,
    pub cell_b: Option<usize>,
}

fn facing_on() -> bool {
    std::env::var("LINI_NOFACING").is_err()
}

// End legs of two wires landing on different nodes that run side by side
// (across the gap two facing sides share) keep a clearance apart: both
// ports step away from each other along their sides.
fn part_facing_legs(wires: &mut [W]) {
    struct Leg {
        w: usize,
        end: usize,
        node: usize,
        horiz: bool,
        pos: f64,
        lo: f64,
        hi: f64,
        // where the leg's far end turns: +1 / -1 along the side axis
        turn: f64,
    }
    let legs_of = |wires: &[W]| -> Vec<Leg> {
        let mut v = Vec::new();
        for (wi, w) in wires.iter().enumerate() {
            let m = w.pts.len();
            if m < 3 || w.straight {
                continue;
            }
            for end in 0..2 {
                let (a, b, c) = if end == 0 { (w.pts[0], w.pts[1], w.pts[2]) } else { (w.pts[m - 1], w.pts[m - 2], w.pts[m - 3]) };
                let horiz = (a.1 - b.1).abs() < 1e-9;
                let (pos, lo, hi, turn) = if horiz {
                    (a.1, a.0.min(b.0), a.0.max(b.0), (c.1 - b.1).signum())
                } else {
                    (a.0, a.1.min(b.1), a.1.max(b.1), (c.0 - b.0).signum())
                };
                v.push(Leg { w: wi, end, node: if end == 0 { w.from } else { w.to }, horiz, pos, lo, hi, turn });
            }
        }
        v
    };
    let legs = legs_of(wires);
    let mut moves: Vec<(usize, usize, f64)> = Vec::new();
    for i in 0..legs.len() {
        for j in i + 1..legs.len() {
            let (x, y) = (&legs[i], &legs[j]);
            if x.w == y.w || x.node == y.node || x.horiz != y.horiz {
                continue;
            }
            let k = wires[x.w].k.min(wires[y.w].k);
            let d = (x.pos - y.pos).abs();
            if d >= k - 1e-9 {
                continue;
            }
            if !(x.lo < y.hi - 1e-9 && y.lo < x.hi - 1e-9) {
                continue;
            }
            // the one turning towards larger coordinates moves that way
            let (sx, sy) = if (x.pos - y.pos).abs() > 1e-9 {
                if x.pos > y.pos {
                    (1.0, -1.0)
                } else {
                    (-1.0, 1.0)
                }
            } else if x.turn > y.turn {
                (1.0, -1.0)
            } else {
                (-1.0, 1.0)
            };
            let step = (k - d) / 2.0;
            moves.push((x.w, x.end, sx * step));
            moves.push((y.w, y.end, sy * step));
        }
    }
    for (wi, end, dv) in moves {
        let w = &mut wires[wi];
        let m = w.pts.len();
        let (a, b) = if end == 0 { (0, 1) } else { (m - 1, m - 2) };
        let horiz = (w.pts[a].1 - w.pts[b].1).abs() < 1e-9;
        for q in [a, b] {
            if horiz {
                w.pts[q].1 += dv;
            } else {
                w.pts[q].0 += dv;
            }
        }
    }
}

fn seq_fan() -> bool {
    std::env::var("LINI_NOSEQFAN").is_err()
}

fn no_taken() -> bool {
    std::env::var("LINI_NOTAKEN").is_ok()
}

// Side enumeration order: east, south, west, north.
pub const ORDER: [Side; 4] = [Side::Right, Side::Bottom, Side::Left, Side::Top];
// Target sides are tried facing back: west, north, east, south.
pub const ORDER_B: [Side; 4] = [Side::Right, Side::Bottom, Side::Left, Side::Top];

// Clockwise tangent of a side.
pub fn tangent(s: Side) -> (f64, f64) {
    match s {
        Side::Top => (1.0, 0.0),
        Side::Right => (0.0, 1.0),
        Side::Bottom => (-1.0, 0.0),
        Side::Left => (0.0, -1.0),
    }
}

fn side_len(r: &Rect, s: Side) -> f64 {
    if s.horizontal() {
        r.w()
    } else {
        r.h()
    }
}

fn dvec(d: usize) -> (f64, f64) {
    match d {
        0 => (1.0, 0.0),
        1 => (0.0, 1.0),
        2 => (-1.0, 0.0),
        _ => (0.0, -1.0),
    }
}

struct Bundle {
    reqs: Vec<usize>,
    p: usize,
    q: usize,
    anchor_p: Option<Side>,
    anchor_q: Option<Side>,
}

fn bundles_of(reqs: &[LinkReq]) -> (Vec<Bundle>, Vec<usize>) {
    let mut out: Vec<Bundle> = Vec::new();
    let mut of = vec![usize::MAX; reqs.len()];
    for (i, r) in reqs.iter().enumerate() {
        if r.routing != "orthogonal" || r.from == r.to {
            continue;
        }
        let found = out.iter().position(|b| {
            let first = &reqs[b.reqs[0]];
            if first.k != r.k {
                return false;
            }
            let ok = |x: Option<Side>, y: Option<Side>| x == y;
            if r.from == b.p && r.to == b.q {
                ok(r.anchor_a, b.anchor_p) && ok(r.anchor_b, b.anchor_q)
            } else if r.from == b.q && r.to == b.p {
                ok(r.anchor_b, b.anchor_p) && ok(r.anchor_a, b.anchor_q)
            } else {
                false
            }
        });
        match found {
            Some(bi) => {
                out[bi].reqs.push(i);
                of[i] = bi;
            }
            None => {
                of[i] = out.len();
                out.push(Bundle { reqs: vec![i], p: r.from, q: r.to, anchor_p: r.anchor_a, anchor_q: r.anchor_b });
            }
        }
    }
    (out, of)
}

// Extra cost of a detour segment: it is priced at the middle of its channel
// (an open side counts K + 20 deep), not at the hugging position.
fn detour_penalty(env: &Env, pts: &[(f64, f64)]) -> f64 {
    let mut pen = 0.0;
    let n = pts.len();
    if n < 4 {
        return 0.0;
    }
    for i in 1..n - 2 {
        let d0 = seg_dir(pts[i - 1], pts[i]);
        let d2 = seg_dir(pts[i + 1], pts[i + 2]);
        if d0 != (d2 + 2) % 4 {
            continue;
        }
            pen += channel_depth_ext(env, pts, i, d0);
    }
    pen
}

// Depth beyond a U-turn segment: the boxes facing the segment and the
// nearest box lying across the segment's line beyond either end bound the
// channel (the latter at its far edge).
fn channel_depth_ext(env: &Env, pts: &[(f64, f64)], j: usize, d: usize) -> f64 {
    let p = pts[j];
    let q = pts[j + 1];
    let horizontal = (p.1 - q.1).abs() < 1e-9;
    let lo = if horizontal { p.0.min(q.0) } else { p.1.min(q.1) };
    let hi = if horizontal { p.0.max(q.0) } else { p.1.max(q.1) };
    // a U whose legs are the end stubs faces boxes across both endpoints'
    // clearance boxes
    let (mut elo, mut ehi) = (lo, hi);
    if j == 1 && j + 2 == pts.len() - 1 {
        for r in [env.a.grow(env.k), env.b.grow(env.k)] {
            let (a0, a1) = if horizontal { (r.x0, r.x1) } else { (r.y0, r.y1) };
            elo = elo.min(a0);
            ehi = ehi.max(a1);
        }
    }
    let k = env.k;
    let solids = env.solids();
    let pos = if horizontal { p.1 } else { p.0 };
    // distance from the segment to an edge of r, measured outwards
    let out = |r: &Rect, far_edge: bool| -> f64 {
        let (e0, e1) = if horizontal { (r.y0, r.y1) } else { (r.x0, r.x1) };
        let towards_max = if horizontal { d == 1 } else { d == 0 };
        match (towards_max, far_edge) {
            (true, false) => e0 - pos,
            (true, true) => e1 - pos,
            (false, false) => pos - e1,
            (false, true) => pos - e0,
        }
    };
    let mut far = f64::INFINITY;
    // (distance along the line, depth) of the nearest box across it per end
    let mut across: [Option<(f64, f64)>; 2] = [None, None];
    for r in &solids {
        let (rlo, rhi, plo, phi) = if horizontal { (r.x0, r.x1, r.y0, r.y1) } else { (r.y0, r.y1, r.x0, r.x1) };
        let near = out(r, false);
        if rlo < ehi - EPS && rhi > elo + EPS && near >= -EPS {
            far = far.min(near);
        } else if near < -EPS && plo < pos - EPS && phi > pos + EPS {
            let (end, dist) = if rhi <= lo + EPS {
                (0, lo - rhi)
            } else if rlo >= hi - EPS {
                (1, rlo - hi)
            } else {
                continue;
            };
            if across[end].map_or(true, |(bd, _)| dist < bd) {
                across[end] = Some((dist, out(r, true)));
            }
        }
    }
    for (_, depth) in across.into_iter().flatten() {
        far = far.min(depth);
    }
    // a container holding both ends bounds the channel at its border
    for o in &env.obs {
        if o.kind != ObKind::WallBoth {
            continue;
        }
        let near = out(&o.r, true);
        if near >= -EPS {
            far = far.min(near);
        }
    }
    if far.is_finite() {
        far
    } else {
        k + 20.0
    }
}

// Free depth beyond a segment in direction `d` (towards the open side),
// capped at K + 20 when nothing bounds it.
fn channel_depth(env: &Env, p: (f64, f64), q: (f64, f64), d: usize) -> f64 {
    let k = env.k;
    let solids = env.solids();
    let horizontal = (p.1 - q.1).abs() < 1e-9;
    let (lo, hi) = if horizontal { (p.0.min(q.0), p.0.max(q.0)) } else { (p.1.min(q.1), p.1.max(q.1)) };
    let pos = if horizontal { p.1 } else { p.0 };
    let mut far = f64::INFINITY;
    for r in &solids {
        let (rlo, rhi, near) = if horizontal {
            (r.x0, r.x1, if d == 1 { r.y0 - pos } else { pos - r.y1 })
        } else {
            (r.y0, r.y1, if d == 0 { r.x0 - pos } else { pos - r.x1 })
        };
        if rlo < hi - EPS && rhi > lo + EPS && near >= -EPS {
            far = far.min(near);
        }
    }
    if far.is_finite() {
        far
    } else {
        k + 20.0
    }
}

fn env_for(ctx: &Ctx, world: &World, a: usize, b: usize, k: f64) -> Env {
    Env { k, obs: crate::links::obstacles(ctx, world, a, b), a: world.rects[a], b: world.rects[b] }
}

// A side can hold `n` ports when they fit at half-clearance pitch.
fn side_fits(r: &Rect, s: Side, n: usize, k: f64) -> bool {
    if n <= 1 {
        return true;
    }
    side_len(r, s) - 2.0 * k >= (n as f64 - 1.0) * k / 2.0 - 1e-9
}

// The overlap of two facing sides' port ranges, if they face each other.
fn facing_overlap(a: &Rect, sa: Side, b: &Rect, sb: Side, k: f64) -> Option<(f64, f64)> {
    if (sa.idx() + 2) % 4 != sb.idx() {
        return None;
    }
    let (a0, a1) = side_span(a, sa);
    let (b0, b1) = side_span(b, sb);
    let lo = (a0 + k).max(b0 + k);
    let hi = (a1 - k).min(b1 - k);
    if lo > hi + 1e-9 {
        return None;
    }
    Some((lo, hi))
}

// A U-turn segment already placed in a channel (for capacity checks).
#[derive(Clone, Debug)]
struct ChanUse {
    horiz: bool,
    pos: f64,
    u: usize,
    lo: f64,
    hi: f64,
    depth: f64,
    count: usize,
}

fn seg_span(p: (f64, f64), q: (f64, f64)) -> (bool, f64, f64, f64) {
    let horiz = (p.1 - q.1).abs() < 1e-9;
    if horiz {
        (true, p.1, p.0.min(q.0), p.0.max(q.0))
    } else {
        (false, p.0, p.1.min(q.1), p.1.max(q.1))
    }
}

// U-turn segments of a path: (index, outward direction).
fn u_segments(pts: &[(f64, f64)]) -> Vec<(usize, usize)> {
    let m = pts.len();
    let mut v = Vec::new();
    if m < 4 {
        return v;
    }
    for j in 1..m - 2 {
        let d0 = seg_dir(pts[j - 1], pts[j]);
        let d2 = seg_dir(pts[j + 1], pts[j + 2]);
        if d0 == (d2 + 2) % 4 {
            v.push((j, d0));
        }
    }
    v
}

#[derive(Clone)]
struct Occupancy {
    // per (node, side): the port slots taken (a fan's trunk is one slot)
    sides: std::collections::HashMap<(usize, usize), Vec<i64>>,
    chans: Vec<ChanUse>,
    // runs laid so far (bounded channels fill up)
    taken: Vec<Taken>,
}

// Record a planned bundle route: its side slots, U channels and runs.
fn record(occ: &mut Occupancy, env: &Env, b: &Bundle, keys: &(Vec<i64>, Vec<i64>), path: &Path, sibling: bool) {
    let n = b.reqs.len();
    for (node, side, ks) in [(b.p, path.sa, &keys.0), (b.q, path.sb, &keys.1)] {
        let v = occ.sides.entry((node, side.idx())).or_default();
        for k in ks.iter() {
            if !v.contains(k) {
                v.push(*k);
            }
        }
    }
    for (j, u) in if sibling { vec![] } else { u_segments(&path.pts) } {
        let (horiz, pos, lo, hi) = seg_span(path.pts[j], path.pts[j + 1]);
        let depth = channel_depth(env, path.pts[j], path.pts[j + 1], u);
        occ.chans.push(ChanUse { horiz, pos, u, lo, hi, depth, count: n });
    }
    if !no_taken() {
        let laid = laid_line(env, path, n);
        let ns = laid.len().saturating_sub(1);
        for j in 0..ns {
            let (horiz, pos, lo, hi) = seg_span(laid[j], laid[j + 1]);
            if hi - lo > 1e-9 {
                occ.taken.push(Taken { horiz, pos, lo, hi, count: n, term: j == 0 || j + 1 == ns, sibling });
            }
        }
    }
}

// The line a planned route will be drawn on, as later routes see it: a
// short dog-leg between facing sides is drawn straight.
fn laid_line(env: &Env, path: &Path, n: usize) -> Vec<(f64, f64)> {
    let k = env.k;
    let m = path.pts.len();
    if m < 3 || m > 4 || std::env::var("LINI_NOLAID").is_ok() {
        return path.pts.clone();
    }
    let Some((lo, hi)) = facing_overlap(&env.a, path.sa, &env.b, path.sb, k) else {
        return path.pts.clone();
    };
    if n > 1 && hi - lo < (n as f64 - 1.0) * k / 2.0 - 1e-9 {
        return path.pts.clone();
    }
    let mid = if path.sa.horizontal() { (env.a.cx() + env.b.cx()) / 2.0 } else { (env.a.cy() + env.b.cy()) / 2.0 };
    let v = mid.max(lo).min(hi);
    let (p0, p1) = (path.pts[0], path.pts[m - 1]);
    if path.sa.horizontal() {
        vec![(v, p0.1), (v, p1.1)]
    } else {
        vec![(p0.0, v), (p1.0, v)]
    }
}

// Slots a side would hold with `new` added.
fn slots_with(occ: &Occupancy, node: usize, side: Side, new: &[i64]) -> usize {
    let mut v: Vec<i64> = occ.sides.get(&(node, side.idx())).cloned().unwrap_or_default();
    for k in new {
        if !v.contains(k) {
            v.push(*k);
        }
    }
    v.len()
}

fn route_bundle(env: &Env, n: usize, b: &Bundle, keys: &(Vec<i64>, Vec<i64>), occ: &Occupancy, force: Option<(usize, Side)>) -> Option<(f64, Path)> {
    let mut ap = b.anchor_p;
    let mut aq = b.anchor_q;
    if let Some((node, side)) = force {
        if node == b.p {
            if ap.map_or(false, |s| s != side) {
                return None;
            }
            ap = Some(side);
        } else {
            if aq.map_or(false, |s| s != side) {
                return None;
            }
            aq = Some(side);
        }
    }
    let sas: Vec<Side> = match ap {
        Some(s) => vec![s],
        None => ORDER.to_vec(),
    };
    let sbs: Vec<Side> = match aq {
        Some(s) => vec![s],
        None => ORDER_B.to_vec(),
    };
    let k = env.k;
    let mut best: Option<(f64, Path)> = None;
    let mut cands: Vec<(f64, Path)> = Vec::new();
    for &sa in &sas {
        for &sb in &sbs {
            let need = if n <= 1 { 0.0 } else { (n as f64 - 1.0) * k / 2.0 };
            let pr = PortReq { sides_a: &[sa], sides_b: &[sb], need, taken: &occ.taken };
            let Some(mut p) = search(env, &pr) else {
                if std::env::var("LINI_DBG_ROUTE").is_ok() {
                    eprintln!("NOPATH {:?}->{:?}", sa, sb);
                }
                continue;
            };
            // sides: a straight bundle needs the shared range, others each
            // side (counting the wires already there)
            let straight_ok = p.pts.len() <= 4
                && facing_overlap(&env.a, sa, &env.b, sb, k).map_or(false, |(lo, hi)| n <= 1 || hi - lo >= (n as f64 - 1.0) * k / 2.0 - 1e-9);
            let na = slots_with(occ, b.p, sa, &keys.0);
            let nb = slots_with(occ, b.q, sb, &keys.1);
            if !straight_ok && !(side_fits(&env.a, sa, na, k) && side_fits(&env.b, sb, nb, k)) {
                if std::env::var("LINI_DBG_ROUTE").is_ok() {
                    eprintln!("NOFIT {:?}->{:?} {} {}", sa, sb, na, nb);
                }
                continue;
            }
            // channels: U-turns stack in a channel of limited depth
            let mut chan_ok = true;
            for (j, u) in u_segments(&p.pts) {
                let (horiz, pos, lo, hi) = seg_span(p.pts[j], p.pts[j + 1]);
                let depth = channel_depth(env, p.pts[j], p.pts[j + 1], u);
                let m: usize = occ
                    .chans
                    .iter()
                    .filter(|c| c.horiz == horiz && (c.pos - pos).abs() < 1e-6 && c.u == u && c.lo < hi - EPS && c.hi > lo + EPS)
                    .map(|c| c.count)
                    .sum();
                let tot = m + n;
                if tot >= 2 && depth / (tot as f64 - 1.0) < k / 2.0 - 1e-9 {
                    chan_ok = false;
                }
            }
            if !chan_ok {
                if std::env::var("LINI_DBG_ROUTE").is_ok() {
                    eprintln!("NOCHAN {:?}->{:?}", sa, sb);
                }
                continue;
            }
            let c = p.cost + detour_penalty(env, &p.pts);
            if std::env::var("LINI_DBG_ROUTE").is_ok() {
                eprintln!("CAND {:?}->{:?} cost {} + {} = {} pts {:?}", sa, sb, p.cost, c - p.cost, c, p.pts);
                crate::route::dbg_touches(env, &occ.taken, &p.pts);
            }
            cands.push((c, p.clone()));
            if best.as_ref().map_or(true, |(bc, _)| c < *bc - 1e-9) {
                centre_staircases(env, &mut p.pts);
                best = Some((c, p));
            }
        }
    }
    // a mirror-image twin of equal cost can win the tie
    if let Some((bc, _)) = &best {
        if mirror_on() {
            let bc = *bc;
            let tied: Vec<&(f64, Path)> = cands.iter().filter(|(c, _)| (c - bc).abs() < 1e-9).collect();
            if tied.len() >= 2 {
                let first = tied[0];
                for other in tied.iter().skip(1) {
                    if is_mirror(&first.1.pts, &other.1.pts) {
                        if std::env::var("LINI_DBG_ROUTE").is_ok() {
                            eprintln!("TWIN {:?} vs {:?}: {:?}", first.1.pts, other.1.pts, twin_wins(env, &first.1, &other.1));
                        }
                        if let Some(true) = twin_wins(env, &first.1, &other.1) {
                            let mut p = other.1.clone();
                            centre_staircases(env, &mut p.pts);
                            best = Some((other.0, p));
                        }
                        break;
                    }
                }
            }
        }
    }
    best
}

fn mirror_on() -> bool {
    std::env::var("LINI_NOMIRROR").is_err()
}

// Two polylines that are reflections of each other across a vertical or a
// horizontal line.
fn is_mirror(p: &[(f64, f64)], q: &[(f64, f64)]) -> bool {
    if p.len() != q.len() || p.len() < 3 {
        return false;
    }
    let mx = p[0].0 + q[0].0;
    let my = p[0].1 + q[0].1;
    let xm = p.iter().zip(q.iter()).all(|(a, b)| (a.1 - b.1).abs() < 1e-6 && (a.0 + b.0 - mx).abs() < 1e-6);
    let ym = p.iter().zip(q.iter()).all(|(a, b)| (a.0 - b.0).abs() < 1e-6 && (a.1 + b.1 - my).abs() < 1e-6);
    (xm || ym) && p != q
}

// Extent of an axis line through `at` (fixed coordinate `c`) until it
// meets a box lying across it: (lo, hi) along the line.
fn line_extent(solids: &[Rect], c: f64, at: f64, vertical: bool) -> (f64, f64) {
    let mut lo = f64::NEG_INFINITY;
    let mut hi = f64::INFINITY;
    for r in solids {
        let (p0, p1, a0, a1) = if vertical { (r.x0, r.x1, r.y0, r.y1) } else { (r.y0, r.y1, r.x0, r.x1) };
        if p0 + EPS < c && c < p1 - EPS {
            if a1 <= at + EPS {
                lo = lo.max(a1);
            } else if a0 >= at - EPS {
                hi = hi.min(a0);
            }
        }
    }
    (lo, hi)
}

// Does a line of the obstacle grid cross the open stretch (p, q) of an
// axis-aligned leg?
fn leg_crossed(env: &Env, p: (f64, f64), q: (f64, f64)) -> bool {
    let solids = env.solids();
    let horiz = (p.1 - q.1).abs() < 1e-9;
    let (lo, hi) = if horiz { (p.0.min(q.0), p.0.max(q.0)) } else { (p.1.min(q.1), p.1.max(q.1)) };
    let at = if horiz { p.1 } else { p.0 };
    let mut lines: Vec<(f64, f64, f64)> = Vec::new(); // (coordinate, extent lo, extent hi) of perpendicular lines
    for r in &solids {
        let (c0, c1, e0, e1) = if horiz { (r.x0, r.x1, r.y0, r.y1) } else { (r.y0, r.y1, r.x0, r.x1) };
        for c in [c0, c1] {
            let (l0, _) = line_extent(&solids, c, e0, horiz);
            let (_, h1) = line_extent(&solids, c, e1, horiz);
            lines.push((c, l0.min(e0), h1.max(e1)));
        }
    }
    for node in [env.a, env.b] {
        for sd in [Side::Right, Side::Bottom, Side::Left, Side::Top] {
            let sp = side_point(&node, sd, 0.0);
            let dv = sd.dir();
            let e = (sp.0 + dv.0 * env.k, sp.1 + dv.1 * env.k);
            let (c, along) = if horiz { (e.0, e.1) } else { (e.1, e.0) };
            let (l0, h1) = line_extent(&solids, c, along, horiz);
            lines.push((c, l0, h1));
        }
    }
    lines.iter().any(|&(c, l0, h1)| c > lo + EPS && c < hi - EPS && at >= l0 - EPS && at <= h1 + EPS)
}

// Of two mirror-image routes of equal cost, does the second win? The search
// settles ties by the step into the end: a leg crossed by a grid line on its
// way in is reached heading east or south first; otherwise the turn point
// lying lower (then further right) comes first.
fn twin_wins(env: &Env, first: &Path, other: &Path) -> Option<bool> {
    let m = first.pts.len();
    if m < 3 {
        return None;
    }
    let k = env.k;
    let seg = |pts: &[(f64, f64)]| -> ((f64, f64), (f64, f64)) { (pts[m - 2], pts[m - 1]) };
    let (b1, e1) = seg(&first.pts);
    let (b2, _) = seg(&other.pts);
    // the final straight run must reach past the stub
    let flen = (e1.0 - b1.0).abs() + (e1.1 - b1.1).abs();
    if flen <= k + 1e-9 {
        return None;
    }
    // the stub end on the final run
    let d1 = seg_dir(b1, e1);
    let d2 = seg_dir(b2, other.pts[m - 1]);
    let sgn = |v: f64| if v > 1e-9 { 1.0 } else if v < -1e-9 { -1.0 } else { 0.0 };
    let stub_end = |b: (f64, f64), e: (f64, f64)| -> (f64, f64) {
        let dx = sgn(e.0 - b.0);
        let dy = sgn(e.1 - b.1);
        (e.0 - dx * k, e.1 - dy * k)
    };
    let crossed1 = leg_crossed(env, b1, stub_end(b1, e1));
    if crossed1 {
        // seg_dir: 0 east, 1 south, 2 west, 3 north
        return Some(d2 < d1);
    }
    let key = |p: (f64, f64)| (p.1, p.0);
    let (k1, k2) = (key(b1), key(b2));
    Some(k2.0 > k1.0 + 1e-9 || ((k2.0 - k1.0).abs() < 1e-9 && k2.1 > k1.1 + 1e-9))
}

// A link between a container and something inside it runs straight from
// the container's border to the inner node's nearest side.
fn parent_child(world: &World, p: usize, q: usize, p_outer: bool) -> Path {
    let (outer, inner) = if p_outer { (world.rects[p], world.rects[q]) } else { (world.rects[q], world.rects[p]) };
    let gaps = [
        (Side::Right, outer.x1 - inner.x1),
        (Side::Left, inner.x0 - outer.x0),
        (Side::Bottom, outer.y1 - inner.y1),
        (Side::Top, inner.y0 - outer.y0),
    ];
    let mut best = gaps[0];
    for g in gaps.iter().skip(1) {
        if g.1 < best.1 - 1e-9 {
            best = *g;
        }
    }
    let sd = best.0;
    let ip = side_point(&inner, sd, 0.0);
    let op = match sd {
        Side::Right => (outer.x1, ip.1),
        Side::Left => (outer.x0, ip.1),
        Side::Bottom => (ip.0, outer.y1),
        Side::Top => (ip.0, outer.y0),
    };
    let pts = if p_outer { vec![op, ip] } else { vec![ip, op] };
    Path { pts, sa: sd, sb: sd, cost: 0.0 }
}

// Corner radii: terminal segments can be used whole (after the marker
// pull-back), interior ones are shared by their two corners in proportion
// to what they want.
fn cap_radii(pts: &[(f64, f64)], want: &[f64], pull_s: f64, pull_e: f64) -> Vec<f64> {
    let n = pts.len();
    if n < 3 {
        return vec![];
    }
    let seg = |i: usize| ((pts[i + 1].0 - pts[i].0).abs() + (pts[i + 1].1 - pts[i].1).abs());
    let share = |len: f64, mine: f64, other: f64| {
        if mine + other > len && mine + other > 0.0 {
            len * mine / (mine + other)
        } else {
            mine
        }
    };
    let mut out = Vec::new();
    for c in 1..n - 1 {
        let r = want[c - 1];
        let before = if c == 1 { seg(0) - pull_s } else { share(seg(c - 1), r, want[c - 2]) };
        let after = if c == n - 2 { seg(c) - pull_e } else { share(seg(c), r, want[c]) };
        out.push(r.min(before).min(after).max(0.0));
    }
    out
}

fn stray() -> Routed {
    Routed { stray: true, pts: vec![], radii: vec![], curve: None, sa: None, sb: None }
}

// One wire being planned.
#[derive(Clone, Debug)]
struct W {
    req: usize,
    bundle: usize,
    slot: usize,
    // polyline from the (promoted) start node to the end node
    pts: Vec<(f64, f64)>,
    sa: Side,
    sb: Side,
    from: usize,
    to: usize,
    k: f64,
    // logical offsets per segment (ports and tracks), for nested radii
    offs: Vec<f64>,
    straight: bool,
    // fan groups sharing a trunk port at the start / end node
    fan_s: Option<usize>,
    fan_e: Option<usize>,
    // a container-to-inner link takes its line from the inner node's side
    inner_end: Option<usize>,
    // a straight wire's preferred line: halfway between the two centres,
    // kept inside the range both sides can take
    ideal: Option<f64>,
}

pub fn route_links(ctx: &Ctx, world: &World, reqs: &[LinkReq]) -> Vec<Routed> {
    // an end promoted from a cell keeps the container's box but lines its
    // ports up with the cell: it routes as a node of its own (a key past the
    // real nodes) with that box
    let nn = world.rects.len();
    let mut ext = world.rects.clone();
    let mut real: Vec<usize> = (0..nn).collect();
    let mut keyed: Vec<((usize, usize, u64), usize)> = Vec::new();
    let mut key_of = |node: usize, cell: Option<usize>, k: f64, ext: &mut Vec<Rect>, real: &mut Vec<usize>| -> usize {
        let Some(c) = cell else { return node };
        if let Some(&(_, key)) = keyed.iter().find(|(nc, _)| *nc == (node, c, k.to_bits())) {
            return key;
        }
        let r = world.rects[node];
        let cr = world.rects[c];
        // the port sits mid-way along the stretch of the cell's row (or
        // column) that the side's port range keeps
        let mid_in = |c0: f64, c1: f64, lo: f64, hi: f64, at: f64| -> f64 {
            let (a, b) = (c0.max(lo), c1.min(hi));
            if a <= b {
                (a + b) / 2.0
            } else if lo <= hi {
                at.max(lo).min(hi)
            } else {
                (lo + hi) / 2.0
            }
        };
        let ccx = mid_in(cr.x0, cr.x1, r.x0 + k, r.x1 - k, cr.cx());
        let ccy = mid_in(cr.y0, cr.y1, r.y0 + k, r.y1 - k, cr.cy());
        let v = Rect { x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1, ccx, ccy, cw: r.w(), ch: r.h() };
        ext.push(v);
        real.push(node);
        keyed.push(((node, c, k.to_bits()), ext.len() - 1));
        ext.len() - 1
    };
    let reqs: Vec<LinkReq> = reqs
        .iter()
        .map(|r| {
            let mut r2 = r.clone();
            r2.from = key_of(r.from, r.cell_a, r.k, &mut ext, &mut real);
            r2.to = key_of(r.to, r.cell_b, r.k, &mut ext, &mut real);
            r2
        })
        .collect();
    let reqs = &reqs[..];
    let xworld = World { rects: ext };
    let world = &xworld;
    let real_of = |k: usize| real[k];
    let mut out: Vec<Option<Routed>> = (0..reqs.len()).map(|_| None).collect();
    // natural and straight routing need no planning
    for (i, req) in reqs.iter().enumerate() {
        let a = world.rects[req.from];
        let b = world.rects[req.to];
        if req.routing == "straight" {
            let (p, q) = crate::links::stray_line(&a, &b);
            out[i] = Some(Routed { stray: false, pts: vec![p, q], radii: vec![], curve: None, sa: None, sb: None });
        } else if req.routing == "natural" {
            let (pts, curve, sa, sb) = natural(&a, &b, req);
            out[i] = Some(Routed { stray: false, pts, radii: vec![], curve: Some(curve), sa: Some(sa), sb: Some(sb) });
        } else if req.from == req.to {
            let k = req.k;
            let pts = vec![(a.x1, a.cy()), (a.x1 + k, a.cy()), (a.x1 + k, a.y0 - k), (a.cx(), a.y0 - k), (a.cx(), a.y0)];
            let want = vec![req.radius; 3];
            let radii = cap_radii(&pts, &want, req.pull_s, req.pull_e);
            out[i] = Some(Routed { stray: false, pts, radii, curve: None, sa: Some(Side::Right), sb: Some(Side::Top) });
        }
    }
    let (bundles, of) = bundles_of(reqs);
    // fans: links of one statement sharing a start (or an end) node
    let mut fan_groups: Vec<(usize, Vec<usize>)> = Vec::new(); // (shared node, reqs)
    let mut fan_of_start: Vec<Option<usize>> = vec![None; reqs.len()];
    let mut fan_of_end: Vec<Option<usize>> = vec![None; reqs.len()];
    {
        let mut outs: std::collections::BTreeMap<(usize, usize), Vec<usize>> = std::collections::BTreeMap::new();
        let mut ins: std::collections::BTreeMap<(usize, usize), Vec<usize>> = std::collections::BTreeMap::new();
        for (i, r) in reqs.iter().enumerate() {
            if of[i] == usize::MAX {
                continue;
            }
            outs.entry((r.stmt, r.from)).or_default().push(i);
            ins.entry((r.stmt, r.to)).or_default().push(i);
        }
        let mut groups: Vec<(usize, usize, Vec<usize>, bool)> = Vec::new();
        for ((_, node), v) in outs {
            if v.len() >= 2 {
                groups.push((v[0], node, v, true));
            }
        }
        for ((_, node), v) in ins {
            if v.len() >= 2 {
                groups.push((v[0], node, v, false));
            }
        }
        groups.sort_by_key(|g| g.0);
        for (_, node, v, is_out) in groups {
            let gi = fan_groups.len();
            for &ri in &v {
                if is_out {
                    if fan_of_start[ri].is_none() {
                        fan_of_start[ri] = Some(gi);
                    }
                } else if fan_of_end[ri].is_none() {
                    fan_of_end[ri] = Some(gi);
                }
            }
            fan_groups.push((node, v));
        }
    }
    let mut occ = Occupancy { sides: std::collections::HashMap::new(), chans: Vec::new(), taken: Vec::new() };
    // each bundle's port slot keys at its two nodes
    let slot_key = |ri: usize, node: usize| -> i64 {
        let g = if reqs[ri].from == node { fan_of_start[ri] } else { fan_of_end[ri] };
        match g {
            Some(gi) if fan_groups[gi].0 == node => gi as i64,
            _ => -(ri as i64) - 1,
        }
    };
    let keys: Vec<(Vec<i64>, Vec<i64>)> = bundles.iter().map(|b| (b.reqs.iter().map(|&ri| slot_key(ri, b.p)).collect(), b.reqs.iter().map(|&ri| slot_key(ri, b.q)).collect())).collect();
    let mut wires: Vec<W> = Vec::new();
    let envs: Vec<Env> = bundles
        .iter()
        .map(|b| {
            let mut e = env_for(ctx, world, real_of(b.p), real_of(b.q), reqs[b.reqs[0]].k);
            e.a = world.rects[b.p];
            e.b = world.rects[b.q];
            e
        })
        .collect();
    let mut done = vec![false; bundles.len()];
    for bi in 0..bundles.len() {
        if done[bi] {
            continue;
        }
        // a fresh fan routes jointly: every member leaves the shared node
        // through the same side, the cheapest such side overall
        let first = bundles[bi].reqs[0];
        // the first fan (out, then in) whose member bundles are all fresh
        let fresh = |gi: usize, done: &Vec<bool>| -> bool {
            let (_, members) = &fan_groups[gi];
            let mut mbs: Vec<usize> = Vec::new();
            for &ri in members {
                if !mbs.contains(&of[ri]) {
                    mbs.push(of[ri]);
                }
            }
            mbs.len() >= 2 && mbs.iter().all(|&mb| !done[mb])
        };
        let fan = [fan_of_start[first], fan_of_end[first]].into_iter().flatten().find(|&gi| fresh(gi, &done));
        let mut joint: Option<Vec<(usize, Path)>> = None;
        if let Some(gi) = fan {
            let (node, members) = &fan_groups[gi];
            let mut mbs: Vec<usize> = Vec::new();
            for &ri in members {
                if !mbs.contains(&of[ri]) {
                    mbs.push(of[ri]);
                }
            }
            {
                let mut best: Option<(f64, Vec<(usize, Path)>)> = None;
                for &sd in ORDER.iter() {
                    let mut total = 0.0;
                    let mut got: Vec<(usize, Path)> = Vec::new();
                    let mut ok = true;
                    // members are laid one after another: later ones see the
                    // runs of the earlier ones
                    let mut trial = occ.clone();
                    for &mb in &mbs {
                        match route_bundle(&envs[mb], bundles[mb].reqs.len(), &bundles[mb], &keys[mb], &trial, Some((*node, sd))) {
                            Some((c, p)) => {
                                total += c;
                                if seq_fan() {
                                    record(&mut trial, &envs[mb], &bundles[mb], &keys[mb], &p, true);
                                }
                                got.push((mb, p));
                            }
                            None => {
                                ok = false;
                                break;
                            }
                        }
                    }
                    if ok && best.as_ref().map_or(true, |(bc, _)| total < *bc - 1e-9) {
                        best = Some((total, got));
                    }
                }
                joint = best.map(|b| b.1);
            }
        }
        let plan: Vec<(usize, Option<Path>)> = match joint {
            Some(v) => v.into_iter().map(|(mb, p)| (mb, Some(p))).collect(),
            None => {
                let b = &bundles[bi];
                let (rp, rq) = (real_of(b.p), real_of(b.q));
                let nested = crate::links::is_ancestor(ctx, rp, rq) || crate::links::is_ancestor(ctx, rq, rp);
                if nested {
                    vec![(bi, Some(parent_child(world, b.p, b.q, crate::links::is_ancestor(ctx, rp, rq))))]
                } else {
                    vec![(bi, route_bundle(&envs[bi], bundles[bi].reqs.len(), &bundles[bi], &keys[bi], &occ, None).map(|x| x.1))]
                }
            }
        };
        for (mb, path) in plan {
            done[mb] = true;
            let b = &bundles[mb];
            let env = &envs[mb];
            let k = env.k;
            let n = b.reqs.len();
            let Some(path) = path else {
                for &ri in &b.reqs {
                    out[ri] = Some(stray());
                }
                continue;
            };
            for (node, side, ks) in [(b.p, path.sa, &keys[mb].0), (b.q, path.sb, &keys[mb].1)] {
                let v = occ.sides.entry((node, side.idx())).or_default();
                for k in ks.iter() {
                    if !v.contains(k) {
                        v.push(*k);
                    }
                }
            }
            for (j, u) in u_segments(&path.pts) {
                let (horiz, pos, lo, hi) = seg_span(path.pts[j], path.pts[j + 1]);
                let depth = channel_depth(env, path.pts[j], path.pts[j + 1], u);
                occ.chans.push(ChanUse { horiz, pos, u, lo, hi, depth, count: n });
            }
            if !no_taken() {
                let laid = laid_line(env, &path, n);
                let ns = laid.len().saturating_sub(1);
                for j in 0..ns {
                    let (horiz, pos, lo, hi) = seg_span(laid[j], laid[j + 1]);
                    if hi - lo > 1e-9 {
                        occ.taken.push(Taken { horiz, pos, lo, hi, count: n, term: j == 0 || j + 1 == ns, sibling: false });
                    }
                }
            }
            let facing = facing_overlap(&env.a, path.sa, &env.b, path.sb, k);
            let z_straight = path.pts.len() <= 4 && facing.map_or(false, |(lo, hi)| n <= 1 || hi - lo >= (n as f64 - 1.0) * k / 2.0 - 1e-9);
            let straight = (path.pts.len() == 2 && path.sa == path.sb) || z_straight;
            let ideal = if z_straight && !(path.pts.len() == 2 && path.sa == path.sb) {
                let (lo, hi) = facing.unwrap();
                let mid = if path.sa.horizontal() { (env.a.cx() + env.b.cx()) / 2.0 } else { (env.a.cy() + env.b.cy()) / 2.0 };
                Some(mid.max(lo).min(hi))
            } else {
                None
            };
            // bundle order: forward links in order, then backward ones reversed
            let mut order: Vec<usize> = b.reqs.iter().cloned().filter(|&ri| reqs[ri].from == b.p).collect();
            let mut back: Vec<usize> = b.reqs.iter().cloned().filter(|&ri| reqs[ri].from != b.p).collect();
            back.reverse();
            order.extend(back);
            for (slot, &ri) in order.iter().enumerate() {
                let pts = path.pts.clone();
                let m = pts.len();
                // fan groups seen from the bundle's orientation
                let (fs, fe) = if reqs[ri].from == b.p { (fan_of_start[ri], fan_of_end[ri]) } else { (fan_of_end[ri], fan_of_start[ri]) };
                let inner_end = if crate::links::is_ancestor(ctx, real_of(b.p), real_of(b.q)) {
                    Some(1)
                } else if crate::links::is_ancestor(ctx, real_of(b.q), real_of(b.p)) {
                    Some(0)
                } else {
                    None
                };
                wires.push(W { req: ri, bundle: mb, slot, pts, sa: path.sa, sb: path.sb, from: b.p, to: b.q, k, offs: vec![0.0; m - 1], straight, fan_s: fs, fan_e: fe, inner_end, ideal });
            }
        }
    }
    plan_ports(ctx, world, &bundles, &mut wires);
    plan_tracks(&envs, &mut wires);
    if facing_on() {
        part_facing_legs(&mut wires);
    }
    // nested corners: a corner wrapped round a parallel inner corner takes
    // the inner radius plus half the offsets between them
    let base_r: Vec<f64> = wires.iter().map(|wr| reqs[wr.req].radius).collect();
    let nests = nest_corners(&wires, &base_r);
    let cross_caps = crossing_caps(&wires);
    // a nested corner grows from what the corner just inside it wants,
    // once that is held to its end legs and to crossing wires (sharing an
    // inner leg with a neighbour corner does not carry over)
    let mut eff: Vec<Vec<f64>> = wires.iter().map(|wr| vec![reqs[wr.req].radius; wr.pts.len().saturating_sub(2)]).collect();
    let wants_of = |w: usize, eff: &Vec<Vec<f64>>| -> Vec<f64> {
        let req = &reqs[wires[w].req];
        nests[w]
            .iter()
            .map(|&(extra, inner)| match inner {
                Some((xw, xc)) => eff[xw][xc] + extra,
                None => req.radius,
            })
            .collect()
    };
    for _ in 0..8 {
        let mut changed = false;
        for w in 0..wires.len() {
            let pts = &wires[w].pts;
            let m = pts.len();
            if m < 3 {
                continue;
            }
            let seg = |i: usize| ((pts[i + 1].0 - pts[i].0).abs() + (pts[i + 1].1 - pts[i].1).abs());
            let want = wants_of(w, &eff);
            for c in 0..m - 2 {
                let mut v = want[c].min(cross_caps[w][c]);
                if c == 0 {
                    v = v.min(seg(0));
                }
                if c == m - 3 {
                    v = v.min(seg(m - 2));
                }
                if (v - eff[w][c]).abs() > 1e-12 {
                    eff[w][c] = v;
                    changed = true;
                }
            }
        }
        if !changed {
            break;
        }
    }
    let radii_of = |w: usize| -> Vec<f64> {
        let wr = &wires[w];
        let req = &reqs[wr.req];
        let pts = &wr.pts;
        let want = wants_of(w, &eff);
        // pull-backs in this wire's own orientation
        let (ps, pe) = if req.from == wr.from { (req.pull_s, req.pull_e) } else { (req.pull_e, req.pull_s) };
        let m = pts.len();
        let seg = |i: usize| ((pts[i + 1].0 - pts[i].0).abs() + (pts[i + 1].1 - pts[i].1).abs());
        let pull_e = if m >= 2 && pe > seg(m - 2) + 1e-9 { 0.0 } else { pe };
        let pull_s = if m >= 2 && ps > seg(0) + 1e-9 { 0.0 } else { ps };
        let mut radii = cap_radii(pts, &want, pull_s, pull_e);
        // an arc never sweeps over a crossing wire
        for (r, c) in radii.iter_mut().zip(cross_caps[w].iter()) {
            if *r > *c {
                *r = *c;
            }
        }
        radii
    };
    for (w, wr) in wires.iter().enumerate() {
        let req = &reqs[wr.req];
        let mut pts = wr.pts.clone();
        let mut radii = if wr.straight { vec![] } else { radii_of(w) };
        let (mut sa, mut sb) = (wr.sa, wr.sb);
        if req.from != wr.from {
            pts.reverse();
            radii.reverse();
            std::mem::swap(&mut sa, &mut sb);
        }
        out[wr.req] = Some(Routed { stray: false, pts, radii, curve: None, sa: Some(sa), sb: Some(sb) });
    }
    out.into_iter().map(|o| o.unwrap_or_else(stray)).collect()
}

// Per corner, the distance to the nearest point where another wire
// crosses one of its two legs (infinite when none).
fn crossing_caps(wires: &[W]) -> Vec<Vec<f64>> {
    let mut segs: Vec<(usize, (f64, f64), (f64, f64))> = Vec::new();
    for (wi, w) in wires.iter().enumerate() {
        for k in 0..w.pts.len().saturating_sub(1) {
            segs.push((wi, w.pts[k], w.pts[k + 1]));
        }
    }
    // the crossing point of two perpendicular segments, strictly inside both
    let cross = |p: (f64, f64), q: (f64, f64), a: (f64, f64), b: (f64, f64)| -> Option<(f64, f64)> {
        let ph = (p.1 - q.1).abs() < 1e-9;
        let ah = (a.1 - b.1).abs() < 1e-9;
        if ph == ah {
            return None;
        }
        let (h0, h1, v0, v1) = if ph { (p, q, a, b) } else { (a, b, p, q) };
        let x = v0.0;
        let y = h0.1;
        let inside_h = x > h0.0.min(h1.0) + 1e-9 && x < h0.0.max(h1.0) - 1e-9;
        let inside_v = y > v0.1.min(v1.1) + 1e-9 && y < v0.1.max(v1.1) - 1e-9;
        if inside_h && inside_v {
            Some((x, y))
        } else {
            None
        }
    };
    wires
        .iter()
        .enumerate()
        .map(|(wi, w)| {
            let n = w.pts.len();
            let mut caps = vec![f64::INFINITY; n.saturating_sub(2)];
            if n < 3 || w.straight {
                return caps;
            }
            for c in 1..n - 1 {
                let corner = w.pts[c];
                for (p, q) in [(w.pts[c - 1], w.pts[c]), (w.pts[c], w.pts[c + 1])] {
                    for &(oi, a, b) in &segs {
                        if oi == wi {
                            continue;
                        }
                        if let Some(x) = cross(p, q, a, b) {
                            let d = (x.0 - corner.0).abs() + (x.1 - corner.1).abs();
                            if d < caps[c - 1] {
                                caps[c - 1] = d;
                            }
                        }
                    }
                }
            }
            caps
        })
        .collect()
}

// Extra radius per corner (added to the base radius). Corners turning the
// same way whose wires run side by side nest: the inner one keeps the base
// radius, outer ones grow by half their offsets so the arcs stay parallel.
fn nest_corners(wires: &[W], base_r: &[f64]) -> Vec<Vec<(f64, Option<(usize, usize)>)>> {
    struct C {
        w: usize,
        c: usize,
        u: usize,
        v: usize,
        p: (f64, f64),
        a: (f64, f64),
        b: (f64, f64),
    }
    let mut cs: Vec<C> = Vec::new();
    for (wi, w) in wires.iter().enumerate() {
        if w.straight || w.pts.len() < 3 {
            continue;
        }
        for c in 1..w.pts.len() - 1 {
            let u = seg_dir(w.pts[c - 1], w.pts[c]);
            let v = seg_dir(w.pts[c], w.pts[c + 1]);
            cs.push(C { w: wi, c, u, v, p: w.pts[c], a: w.pts[c - 1], b: w.pts[c + 1] });
        }
    }
    let span_overlap = |a0: f64, a1: f64, b0: f64, b1: f64| a0.min(a1) < b0.max(b1) - 1e-9 && b0.min(b1) < a0.max(a1) - 1e-9;
    // is corner y wrapped round corner x (the same bend whichever way the
    // wires run, outside it, side by side)?
    let outside = |x: &C, y: &C| -> bool {
        // y's legs matched to x's: same incoming / outgoing turn, or the
        // same bend walked the other way
        let (ya, yb) = if x.u == y.u && x.v == y.v {
            (y.a, y.b)
        } else if x.u == (y.v + 2) % 4 && x.v == (y.u + 2) % 4 {
            (y.b, y.a)
        } else {
            return false;
        };
        let uv = dvec(x.u);
        let vv = dvec(x.v);
        let d = (y.p.0 - x.p.0, y.p.1 - x.p.1);
        let du = d.0 * uv.0 + d.1 * uv.1;
        let dv = d.0 * vv.0 + d.1 * vv.1;
        // strictly outside on both axes (a trunk sibling sharing the leg is not)
        if du < 1e-9 || dv > -1e-9 {
            return false;
        }
        // the inner corner sits inside the outer arc: the two offsets may
        // differ by less than the inner arc's diameter
        if (du + dv).abs() >= 2.0 * base_r[x.w] - 1e-9 {
            return false;
        }
        // and not far apart (three clearances at most on either axis)
        let lim = 3.0 * wires[x.w].k;
        if du > lim + 1e-9 || -dv > lim + 1e-9 {
            return false;
        }
        // the legs run side by side
        let horiz_in = uv.1.abs() < 0.5;
        let (in_ok, out_ok) = if horiz_in {
            (span_overlap(x.a.0, x.p.0, ya.0, y.p.0), span_overlap(x.p.1, x.b.1, y.p.1, yb.1))
        } else {
            (span_overlap(x.a.1, x.p.1, ya.1, y.p.1), span_overlap(x.p.0, x.b.0, y.p.0, yb.0))
        };
        in_ok && out_ok
    };
    let mut wants: Vec<Vec<(f64, Option<(usize, usize)>)>> = wires.iter().map(|w| vec![(0.0, None); w.pts.len().saturating_sub(2)]).collect();
    for y in 0..cs.len() {
        // innermost corner of y's nest: wrapped by y, wrapping nothing
        let mut inner: Option<usize> = None;
        for x in 0..cs.len() {
            if x == y || !outside(&cs[x], &cs[y]) {
                continue;
            }
            inner = Some(match inner {
                None => x,
                Some(prev) => {
                    // the nearest such corner
                    let dp = (cs[prev].p.0 - cs[y].p.0).abs() + (cs[prev].p.1 - cs[y].p.1).abs();
                    let dx = (cs[x].p.0 - cs[y].p.0).abs() + (cs[x].p.1 - cs[y].p.1).abs();
                    if dx < dp {
                        x
                    } else {
                        prev
                    }
                }
            });
        }
        let Some(x) = inner else { continue };
        let (cy, cx) = (&cs[y], &cs[x]);
        let extra = if wires[cy.w].bundle == wires[cx.w].bundle && cy.u == cx.u {
            // within a bundle the offsets are exact multiples of the pitches
            let (wy, wx) = (&wires[cy.w], &wires[cx.w]);
            ((wy.offs[cy.c - 1] - wx.offs[cx.c - 1]).abs() + (wy.offs[cy.c] - wx.offs[cx.c]).abs()) / 2.0
        } else {
            ((cy.p.0 - cx.p.0).abs() + (cy.p.1 - cx.p.1).abs()) / 2.0
        };
        wants[cy.w][cy.c - 1] = (extra, Some((cx.w, cx.c - 1)));
    }
    wants
}

// Where the wire end at `end` (0 start, 1 finish) leaves its side: the
// turn class relative to the side's clockwise tangent and the distance to
// the first turn.
fn end_shape(w: &W, end: usize) -> (i32, f64) {
    let pts: Vec<(f64, f64)> = if end == 0 { w.pts.clone() } else { w.pts.iter().rev().cloned().collect() };
    let side = if end == 0 { w.sa } else { w.sb };
    if pts.len() <= 2 || w.straight {
        return (0, 0.0);
    }
    let t = tangent(side);
    let nd = dvec(seg_dir(pts[1], pts[2]));
    let dot = nd.0 * t.0 + nd.1 * t.1;
    let cls = if dot > 0.5 {
        1
    } else if dot < -0.5 {
        -1
    } else {
        0
    };
    let dist = (pts[1].0 - pts[0].0).abs() + (pts[1].1 - pts[0].1).abs();
    (cls, dist)
}

// The span key (far end, then near end reversed) of the U-turn track a
// wire end turns into, if any: smaller is further inside.
fn u_key(w: &W, end: usize) -> Option<(f64, f64)> {
    let m = w.pts.len();
    if w.straight || m < 4 {
        return None;
    }
    let j = if end == 0 { 1 } else { m - 3 };
    if !is_u(&w.pts, j) {
        return None;
    }
    let (_, _, lo, hi) = seg_span(w.pts[j], w.pts[j + 1]);
    Some((hi, lo))
}

// Spread every side's wire ends: ordered so wires do not cross, centred,
// pitch the clearance (squeezed down to fit the side).
fn plan_ports(ctx: &Ctx, world: &World, bundles: &[Bundle], wires: &mut [W]) {
    use std::collections::BTreeMap;
    // a straight wire leaving a container takes its port among the ends on
    // the side of the child it lines up with
    let port_node = |node: usize, side: Side, w: &W| -> usize {
        let Some(id) = w.ideal else { return node };
        if node >= ctx.nodes.len() {
            return node;
        }
        for &c in &ctx.nodes[node].children {
            if !crate::links::is_obstacle_kind(ctx, c) || ctx.nodes[c].is("caption") {
                continue;
            }
            let (c0, c1) = side_span(&world.rects[c], side);
            if id >= c0 + w.k - 1e-9 && id <= c1 - w.k + 1e-9 {
                return c;
            }
        }
        node
    };
    let mut sides: BTreeMap<(usize, usize), Vec<(usize, usize)>> = BTreeMap::new();
    for (wi, w) in wires.iter().enumerate() {
        sides.entry((w.from, w.sa.idx())).or_default().push((wi, 0));
        sides.entry((w.to, w.sb.idx())).or_default().push((wi, 1));
    }
    // (only when that child's side has ends of its own)
    let mut moves: Vec<((usize, usize), (usize, usize), (usize, usize))> = Vec::new();
    for (wi, w) in wires.iter().enumerate() {
        for (e, node, side) in [(0, w.from, w.sa), (1, w.to, w.sb)] {
            let c = port_node(node, side, w);
            if c != node && sides.get(&(c, side.idx())).map_or(false, |v| !v.is_empty()) {
                moves.push(((node, side.idx()), (c, side.idx()), (wi, e)));
            }
        }
    }
    for (from_key, to_key, end) in moves {
        if let Some(v) = sides.get_mut(&from_key) {
            v.retain(|x| *x != end);
        }
        sides.entry(to_key).or_default().push(end);
    }
    sides.retain(|_, v| !v.is_empty());
    // straight wires keep one position on both sides: the busier side decides
    let mut straight_pos: std::collections::HashMap<usize, f64> = std::collections::HashMap::new();
    // each side's own slot count and pitch (trunks collapse to one slot)
    let own_pitch: std::collections::HashMap<(usize, usize), (usize, f64)> = sides
        .iter()
        .map(|(&(node, sidx), ends)| {
            let side = [Side::Top, Side::Right, Side::Bottom, Side::Left][sidx];
            let r = world.rects[node];
            let k = wires[ends[0].0].k;
            let mut keys: Vec<Option<usize>> = Vec::new();
            let mut n = 0;
            for &(wi, e) in ends {
                let g = if e == 0 { wires[wi].fan_s } else { wires[wi].fan_e };
                match g {
                    Some(g) if keys.contains(&Some(g)) => {}
                    _ => {
                        keys.push(g);
                        n += 1;
                    }
                }
            }
            let len = if side.horizontal() { r.w() } else { r.h() };
            let pitch = if n <= 1 { 0.0 } else { k.min((len - 2.0 * k) / (n as f64 - 1.0)) };
            ((node, sidx), (n, pitch))
        })
        .collect();
    let end_sides: Vec<[(usize, usize); 2]> = wires.iter().map(|w| [(w.from, w.sa.idx()), (w.to, w.sb.idx())]).collect();
    let mut entries: Vec<((usize, usize), Vec<(usize, usize)>)> = sides.into_iter().collect();
    // busier sides first so straight wires take their positions there; an
    // inner node's side goes before its container's
    let inner_side = |ends: &Vec<(usize, usize)>| ends.iter().any(|&(wi, e)| wires[wi].inner_end == Some(e));
    entries.sort_by(|a, b| inner_side(&b.1).cmp(&inner_side(&a.1)).then(b.1.len().cmp(&a.1.len())).then(a.0.cmp(&b.0)));
    for ((node, sidx), mut ends) in entries {
        let side = [Side::Top, Side::Right, Side::Bottom, Side::Left][sidx];
        let r = world.rects[node];
        let k = wires[ends[0].0].k;
        // fan members sharing this node and side travel as one trunk port
        let fan_key = |w: &W, e: usize| if e == 0 { w.fan_s } else { w.fan_e };
        // ends wanting a line of their own come in its order along the side
        let tg = tangent(side);
        let tsg = if side.horizontal() { tg.0 } else { tg.1 };
        let mid = if side.horizontal() { r.cx() } else { r.cy() };
        let line_of = |wi: usize| -> f64 { straight_pos.get(&wi).copied().or(if wires[wi].straight { wires[wi].ideal } else { None }).unwrap_or(mid) * tsg };
        ends.sort_by(|&(wa, ea), &(wb, eb)| {
            let la = line_of(wa);
            let lb = line_of(wb);
            if (la - lb).abs() > 1e-9 {
                return la.partial_cmp(&lb).unwrap_or(std::cmp::Ordering::Equal);
            }
            let (ca, da) = end_shape(&wires[wa], ea);
            let (cb, db) = end_shape(&wires[wb], eb);
            let ka = if ca == -1 { da } else if ca == 1 { -da } else { 0.0 };
            let kb = if cb == -1 { db } else if cb == 1 { -db } else { 0.0 };
            // a wire turning into an inner track turns first
            let ua = u_key(&wires[wa], ea);
            let ub = u_key(&wires[wb], eb);
            let inner = match (ua, ub) {
                (Some(x), Some(y)) if ca == cb && ca != 0 => {
                    let o = x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal).then(y.1.partial_cmp(&x.1).unwrap_or(std::cmp::Ordering::Equal));
                    if ca == 1 {
                        o.reverse()
                    } else {
                        o
                    }
                }
                _ => std::cmp::Ordering::Equal,
            };
            let ba = wires[wa].bundle;
            let bb = wires[wb].bundle;
            // within a bundle: slot order on the start side, reversed on the far side
            let sa = if ea == 0 { wires[wa].slot as i64 } else { -(wires[wa].slot as i64) };
            let sb = if eb == 0 { wires[wb].slot as i64 } else { -(wires[wb].slot as i64) };
            ca.cmp(&cb)
                .then(ka.partial_cmp(&kb).unwrap_or(std::cmp::Ordering::Equal))
                .then(if ba == bb { std::cmp::Ordering::Equal } else { inner })
                .then(ba.cmp(&bb))
                .then(sa.cmp(&sb))
        });
        // slots: trunk members collapse onto their group's first slot
        let mut slot_of: Vec<usize> = Vec::new();
        let mut groups_seen: Vec<(usize, usize)> = Vec::new();
        let mut nslots = 0;
        for &(wi, e) in &ends {
            match fan_key(&wires[wi], e) {
                Some(g) => {
                    if let Some(&(_, sl)) = groups_seen.iter().find(|(gg, _)| *gg == g) {
                        slot_of.push(sl);
                    } else {
                        groups_seen.push((g, nslots));
                        slot_of.push(nslots);
                        nslots += 1;
                    }
                }
                None => {
                    slot_of.push(nslots);
                    nslots += 1;
                }
            }
        }
        let n = nslots;
        let len = if side.horizontal() { r.w() } else { r.h() };
        let mut pitch = if n <= 1 { 0.0 } else { k.min((len - 2.0 * k) / (n as f64 - 1.0)) };
        // a straight bundle keeps one pitch on both sides: the tighter one
        if n > 1 && ends.iter().all(|&(wi, _)| wires[wi].straight) {
            for &(wi, e) in &ends {
                if let Some(&(on, op)) = own_pitch.get(&end_sides[wi][1 - e]) {
                    if on == n && op < pitch {
                        pitch = op;
                    }
                }
            }
        }
        let t = tangent(side);
        let centre = if side.horizontal() { r.cx() } else { r.cy() };
        let sgn = if side.horizontal() { t.0 } else { t.1 };
        // each slot wants a line: the side's centre, or a straight wire's
        // own line (fixed once its other side placed it)
        let mut want: Vec<Option<(f64, bool)>> = vec![None; n];
        for (ii, &(wi, _)) in ends.iter().enumerate() {
            let i = slot_of[ii];
            let w = &wires[wi];
            if let Some(&sp) = straight_pos.get(&wi) {
                want[i] = Some((sp, true));
            } else if let (true, Some(id)) = (w.straight, w.ideal) {
                if want[i].is_none() {
                    want[i] = Some((id, false));
                }
            }
        }
        let standard = want.iter().all(|x| x.is_none());
        // slots in axis order, at least a pitch apart, as near their lines
        // as possible (pooled where they would crowd), inside the side
        let (s0, s1) = side_span(&r, side);
        let pos_of: Vec<f64> = {
            let axis = |i: usize| if sgn > 0.0 { i } else { n - 1 - i };
            let mut tgt = vec![0.0; n];
            let mut wt = vec![1.0; n];
            for i in 0..n {
                let (t0, fixed) = want[i].unwrap_or((centre, false));
                tgt[axis(i)] = t0;
                wt[axis(i)] = if fixed { 1e9 } else { 1.0 };
            }
            // blocks: (first, last, weight sum, weighted target sum, weighted index sum)
            let mut blocks: Vec<(usize, usize, f64, f64, f64)> = Vec::new();
            let val = |b: &(usize, usize, f64, f64, f64)| b.3 / b.2 - pitch * (b.4 / b.2);
            for j in 0..n {
                blocks.push((j, j, wt[j], wt[j] * tgt[j], wt[j] * j as f64));
                while blocks.len() >= 2 && val(&blocks[blocks.len() - 2]) > val(&blocks[blocks.len() - 1]) + 1e-12 {
                    let b2 = blocks.pop().unwrap();
                    let b1 = blocks.pop().unwrap();
                    blocks.push((b1.0, b2.1, b1.2 + b2.2, b1.3 + b2.3, b1.4 + b2.4));
                }
            }
            let mut ys = vec![0.0; n];
            for b in &blocks {
                let mut y = if standard { centre - (n as f64 - 1.0) / 2.0 * pitch } else { val(b) };
                let ylo = s0 + k;
                let yhi = s1 - k - (n as f64 - 1.0) * pitch;
                if !standard && ylo <= yhi + 1e-9 {
                    y = y.max(ylo).min(yhi);
                }
                for j in b.0..=b.1 {
                    ys[j] = y;
                }
            }
            if standard && n > 1 {
                // evenly spread round the centre: a crowded side measures
                // each slot's offset from the centre, a roomy one steps a
                // pitch at a time from its first slot
                let crowded = pitch < k - 1e-12;
                let h = (n as f64 - 1.0) / 2.0;
                (0..n)
                    .map(|i| {
                        let a = axis(i) as f64;
                        if crowded {
                            centre + (a * pitch - h * pitch)
                        } else {
                            (centre - h * pitch) + a * pitch
                        }
                    })
                    .collect()
            } else {
                (0..n).map(|i| ys[axis(i)] + axis(i) as f64 * pitch).collect()
            }
        };
        for (ii, &(wi, e)) in ends.iter().enumerate() {
            let i = slot_of[ii];
            let c = i as f64 - (n as f64 - 1.0) / 2.0;
            let mut off = if standard { c * pitch } else { (pos_of[i] - centre) * sgn };
            let mut pos = pos_of[i];
            let w = &wires[wi];
            if w.straight {
                if let Some(&sp) = straight_pos.get(&wi) {
                    // already fixed by the other side
                    off = (sp - centre) * sgn;
                    pos = sp;
                }
            }
            apply_port(&mut wires[wi], e, t, off, pos);
            let w = &wires[wi];
            if w.straight && !straight_pos.contains_key(&wi) {
                let p = if e == 0 { w.pts[0] } else { *w.pts.last().unwrap() };
                straight_pos.insert(wi, if side.horizontal() { p.0 } else { p.1 });
            }
        }
    }
    let _ = bundles;
}

// Put a wire end at `pos` along its side (`off` is its logical offset
// from the side's centre, kept for nesting).
fn apply_port(w: &mut W, end: usize, t: (f64, f64), off: f64, pos: f64) {
    let m = w.pts.len();
    let along_x = t.0.abs() > 0.5;
    if w.straight {
        // the whole line moves; it stays straight (a 2-point line between
        // facing sides)
        let s = w.pts[0];
        let e = w.pts[m - 1];
        let _ = end;
        let (sp, ep) = if along_x { ((pos, s.1), (pos, e.1)) } else { ((s.0, pos), (e.0, pos)) };
        w.pts = vec![sp, ep];
        w.offs = vec![off];
        return;
    }
    let (a, b) = if end == 0 { (0, 1) } else { (m - 1, m - 2) };
    for q in [a, b] {
        if along_x {
            w.pts[q].0 = pos;
        } else {
            w.pts[q].1 = pos;
        }
    }
    if end == 0 {
        w.offs[0] = off;
    } else {
        w.offs[m - 2] = -off;
    }
}

// Stack parallel interior segments: U-turns hug what they go around and
// stack outwards, staircases centre in their channel.
fn plan_tracks(envs: &[Env], wires: &mut [W]) {
    // collect interior segments
    struct Seg {
        w: usize,
        j: usize,
        u: usize,
        horiz: bool,
        pos: f64,
        lo: f64,
        hi: f64,
        is_u: bool,
        chan: (f64, f64),
    }
    let mut segs: Vec<Seg> = Vec::new();
    for (wi, w) in wires.iter().enumerate() {
        if w.straight {
            continue;
        }
        let m = w.pts.len();
        if m < 4 {
            continue;
        }
        for j in 1..m - 2 {
            let d0 = seg_dir(w.pts[j - 1], w.pts[j]);
            let d2 = seg_dir(w.pts[j + 1], w.pts[j + 2]);
            let (horiz, pos, lo, hi) = seg_span(w.pts[j], w.pts[j + 1]);
            let is_u = d0 == (d2 + 2) % 4;
            let chan = if is_u { (0.0, 0.0) } else { staircase_channel(&envs[w.bundle], &w.pts, j) };
            segs.push(Seg { w: wi, j, u: d0, horiz, pos, lo, hi, is_u, chan });
        }
    }
    // group by channel (union of overlapping spans)
    let n = segs.len();
    let mut group: Vec<usize> = (0..n).collect();
    fn find(g: &mut Vec<usize>, x: usize) -> usize {
        let mut r = x;
        while g[r] != r {
            r = g[r];
        }
        let mut c = x;
        while g[c] != r {
            let nx = g[c];
            g[c] = r;
            c = nx;
        }
        r
    }
    for a in 0..n {
        for b in a + 1..n {
            let (sa, sb) = (&segs[a], &segs[b]);
            if sa.is_u != sb.is_u || sa.horiz != sb.horiz || sa.u != sb.u {
                continue;
            }
            let same = if sa.is_u { (sa.pos - sb.pos).abs() < 1e-6 } else { (sa.chan.0 - sb.chan.0).abs() < 1e-6 && (sa.chan.1 - sb.chan.1).abs() < 1e-6 };
            if same && sa.lo < sb.hi - EPS && sb.lo < sa.hi - EPS {
                let ra = find(&mut group, a);
                let rb = find(&mut group, b);
                if ra != rb {
                    group[rb] = ra;
                }
            }
        }
    }
    let mut groups: std::collections::BTreeMap<usize, Vec<usize>> = std::collections::BTreeMap::new();
    for i in 0..n {
        let r = find(&mut group, i);
        groups.entry(r).or_default().push(i);
    }
    for (_, members) in groups {
        let first = &segs[members[0]];
        let k = wires[first.w].k;
        let cnt = members.len();
        let uv = dvec(first.u);
        // current spans (after ports)
        let span = |s: &Seg, ws: &[W]| {
            let w = &ws[s.w];
            let (_, _, lo, hi) = seg_span(w.pts[s.j], w.pts[s.j + 1]);
            (lo, hi)
        };
        // nesting order, inner first
        let mut left: Vec<usize> = members.clone();
        let mut ordered: Vec<usize> = Vec::new();
        if first.is_u {
            // U-turns: the one that ends first is inside
            left.sort_by(|&a, &b| {
                let (wa, wb) = (&wires[segs[a].w], &wires[segs[b].w]);
                // within a bundle the start ports decide: the wire starting
                // furthest towards where the U runs is inside
                if wa.bundle == wb.bundle {
                    let along = |s: &Seg, w: &W| {
                        let v = dvec(seg_dir(w.pts[s.j], w.pts[s.j + 1]));
                        let p = w.pts[s.j];
                        -(p.0 * v.0 + p.1 * v.1)
                    };
                    return along(&segs[a], wa).partial_cmp(&along(&segs[b], wb)).unwrap_or(std::cmp::Ordering::Equal);
                }
                let (al, ah) = span(&segs[a], wires);
                let (bl, bh) = span(&segs[b], wires);
                ah.partial_cmp(&bh)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then(bl.partial_cmp(&al).unwrap_or(std::cmp::Ordering::Equal))
                    .then(wa.bundle.cmp(&wb.bundle))
            });
            ordered = left.clone();
            left.clear();
        }
        while !left.is_empty() {
            let mut cands: Vec<usize> = Vec::new();
            for &x in &left {
                let (xl, xh) = span(&segs[x], wires);
                let contains_other = left.iter().any(|&y| {
                    if y == x {
                        return false;
                    }
                    let (yl, yh) = span(&segs[y], wires);
                    yl > xl + 1e-6 && yh < xh - 1e-6
                });
                if !contains_other {
                    cands.push(x);
                }
            }
            if cands.is_empty() {
                cands = left.clone();
            }
            // ties: the wire most offset towards where it turns goes first
            let key = |x: usize| {
                let s = &segs[x];
                let w = &wires[s.w];
                let v = dvec(seg_dir(w.pts[s.j], w.pts[s.j + 1]));
                let p = w.pts[s.j];
                (w.bundle, -(p.0 * v.0 + p.1 * v.1))
            };
            cands.sort_by(|&a, &b| {
                let (ba, oa) = key(a);
                let (bb, ob) = key(b);
                ba.cmp(&bb).then(oa.partial_cmp(&ob).unwrap_or(std::cmp::Ordering::Equal))
            });
            let pick = cands[0];
            ordered.push(pick);
            left.retain(|&x| x != pick);
        }
        if first.is_u {
            let depth = {
                let w = &wires[first.w];
                channel_depth(&envs[w.bundle], w.pts[first.j], w.pts[first.j + 1], first.u)
            };
            let pitch = if cnt <= 1 { 0.0 } else { k.min(depth / (cnt as f64 - 1.0)) };
            let base = first.pos * (if first.horiz { uv.1 } else { uv.0 });
            // too many to keep half a clearance apart: they share the band
            // from half a clearance off the obstacle to the channel's end
            // evenly, the outermost at the end (the innermost still hugs)
            let crowded = cnt >= 2 && pitch < k / 2.0 - 1e-9;
            let q = (k / 2.0 + depth) / cnt as f64;
            for (rank, &x) in ordered.iter().enumerate() {
                let s = &segs[x];
                // (the original settles crowded tracks to 2^-40)
                let o = if crowded { snap40((depth - (cnt - 1 - rank) as f64 * q).max(0.0)) } else { rank as f64 * pitch };
                set_pos(&mut wires[s.w].pts, s.j, uv, base + o);
                wires[s.w].offs[s.j] = o;
            }
        } else {
            let (lo, hi) = first.chan;
            let width = hi - lo;
            let pitch = if cnt <= 1 { 0.0 } else { k.min(width / (cnt as f64 - 1.0)) };
            let mid = (lo + hi) / 2.0;
            for (rank, &x) in ordered.iter().enumerate() {
                let s = &segs[x];
                let o = (rank as f64 - (cnt as f64 - 1.0) / 2.0) * pitch;
                set_pos(&mut wires[s.w].pts, s.j, uv, mid + o);
                wires[s.w].offs[s.j] = o;
            }
        }
    }
}

fn set_pos(line: &mut [(f64, f64)], j: usize, uv: (f64, f64), pos: f64) {
    // segment j runs between line[j] and line[j+1]; move it along u
    if uv.0.abs() > 0.5 {
        line[j].0 = pos * uv.0;
        line[j + 1].0 = pos * uv.0;
    } else {
        line[j].1 = pos * uv.1;
        line[j + 1].1 = pos * uv.1;
    }
}

// The channel a staircase segment can slide in (along the incoming
// direction's axis), as signed positions along u.
fn staircase_channel(env: &Env, pts: &[(f64, f64)], j: usize) -> (f64, f64) {
    let solids = env.solids();
    let p = pts[j];
    let q = pts[j + 1];
    let u = seg_dir(pts[j - 1], pts[j]);
    let uv = dvec(u);
    let vertical = (p.0 - q.0).abs() < 1e-9;
    let (lo0, hi0) = if vertical {
        let a = pts[j - 1].0;
        let b = pts[j + 2].0;
        (a.min(b), a.max(b))
    } else {
        let a = pts[j - 1].1;
        let b = pts[j + 2].1;
        (a.min(b), a.max(b))
    };
    let mut lo = lo0;
    let mut hi = hi0;
    if vertical {
        let (y0, y1) = (p.1.min(q.1), p.1.max(q.1));
        let x = p.0;
        for r in &solids {
            if r.y0 < y1 - EPS && r.y1 > y0 + EPS {
                if r.x1 <= x + EPS && r.x1 > lo {
                    lo = r.x1;
                }
                if r.x0 >= x - EPS && r.x0 < hi {
                    hi = r.x0;
                }
            }
        }
    } else {
        let (x0, x1) = (p.0.min(q.0), p.0.max(q.0));
        let y = p.1;
        for r in &solids {
            if r.x0 < x1 - EPS && r.x1 > x0 + EPS {
                if r.y1 <= y + EPS && r.y1 > lo {
                    lo = r.y1;
                }
                if r.y0 >= y - EPS && r.y0 < hi {
                    hi = r.y0;
                }
            }
        }
    }
    // signed along u
    let s = if vertical { uv.0 } else { uv.1 };
    if s >= 0.0 {
        (lo, hi)
    } else {
        (-hi, -lo)
    }
}

// Round to the nearest multiple of 2^-40.
fn snap40(x: f64) -> f64 {
    let s = 1099511627776.0;
    (x * s).round() / s
}
