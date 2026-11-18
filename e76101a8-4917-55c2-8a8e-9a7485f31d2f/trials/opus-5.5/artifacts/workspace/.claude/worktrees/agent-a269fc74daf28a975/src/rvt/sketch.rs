//! A sketched element's boundary: its sketch lines (a curve each) closed into loops, the loops
//! inside others as their voids, arcs drawn as chords.

use super::build::r3;
use super::cats;
use super::curves::{self, Arc};
use super::import::Ctx;
use super::plan::{self, P};
use super::records::Record;

/// Joined ends may be this far apart (mm).
const JOIN: f64 = 1.0;

#[derive(Clone, Debug)]
pub struct SLine {
    pub id: u64,
    pub a: P,
    pub b: P,
    /// The arc (feet), when the line is one: traversed from `a0` to `a1`.
    pub arc: Option<Arc>,
    /// Up to 2023, a line read from a box across its diagonal is one of two.
    pub diagonal: Option<(P, P, P, P)>,
    /// Neither reading gives this line a curve.
    pub none: bool,
}

/// The tessellation of an arc: points from `a` to `b` (inclusive), every chord within the
/// tolerance of the arc.
fn arc_pts(a: &Arc, reverse: bool) -> Vec<P> {
    let sweep = a.a1 - a.a0;
    let r_ft = a.radius;
    let tol_ft = 0.0005;
    let step = if r_ft > tol_ft { 2.0 * (1.0 - tol_ft / r_ft).acos() } else { sweep.abs() };
    let n = ((sweep.abs() / step).ceil() as usize).clamp(1, 4096);
    let mut v: Vec<P> = (0..=n)
        .map(|k| {
            let t = a.a0 + sweep * k as f64 / n as f64;
            let p = a.point(t);
            [r3(p[0] * 304.8), r3(p[1] * 304.8)]
        })
        .collect();
    if reverse {
        v.reverse();
    }
    v
}

fn dist(p: P, q: P) -> f64 {
    ((p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2)).sqrt()
}

fn extent_of(pts: &[[f64; 3]]) -> [f64; 6] {
    let mut e = [f64::INFINITY, f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    for p in pts {
        for k in 0..3 {
            e[k] = e[k].min(p[k]);
            e[k + 3] = e[k + 3].max(p[k]);
        }
    }
    e
}

/// An arc's extent (feet), from points along it.
fn arc_extent(a: &Arc) -> [f64; 6] {
    let n = 720;
    let pts: Vec<[f64; 3]> = (0..=n).map(|k| a.point(a.a0 + (a.a1 - a.a0) * k as f64 / n as f64)).collect();
    extent_of(&pts)
}

fn off(e: &[f64; 6], b: &[f64; 6]) -> f64 {
    (0..6).map(|k| (e[k] - b[k]).abs()).fold(0.0, f64::max)
}

/// A sketch line's curve: from its data (as a line and as an arc, the one closest to its box),
/// else from its box.
pub fn line_of(ctx: &Ctx, r: &Record) -> SLine {
    let b = r.bbox.unwrap_or([0.0; 6]);
    let pick = ctx.first_data(r.id, |d| curves::first_both(d));
    if let Some((line, arc, _flagged, _)) = pick {
        let le = line.map(|l| extent_of(&[l.start, l.end]));
        let ae = arc.map(|a| arc_extent(&a));
        let use_arc = match (le, ae) {
            (Some(l), Some(a)) => off(&a, &b) < off(&l, &b) - 1e-9,
            (None, Some(_)) => true,
            _ => false,
        };
        // a curve that does not span the record's box (within a ten-thousandth of a foot) gives
        // way to the box when the box is one line
        let flat_box = r.bbox.map(|b| (b[3] - b[0]).abs() < 1e-12 || (b[4] - b[1]).abs() < 1e-12).unwrap_or(false);
        let fits = !flat_box
            || match (use_arc, le, ae) {
                (true, _, Some(a)) => off(&a, &b) <= 1e-4,
                (false, Some(l), _) => off(&l, &b) <= 1e-4,
                _ => false,
            };
        if use_arc && fits {
            let a = arc.unwrap();
            let s = a.start();
            let e = a.end();
            return SLine {
                id: r.id,
                a: [r3(s[0] * 304.8), r3(s[1] * 304.8)],
                b: [r3(e[0] * 304.8), r3(e[1] * 304.8)],
                arc: Some(a),
                diagonal: None,
                none: false,
            };
        }
        if let (Some(l), true) = (line, fits) {
            return SLine {
                id: r.id,
                a: [r3(l.start[0] * 304.8), r3(l.start[1] * 304.8)],
                b: [r3(l.end[0] * 304.8), r3(l.end[1] * 304.8)],
                arc: None,
                diagonal: None,
                none: false,
            };
        }
    }
    // the box: a line along it, or across one of its diagonals
    let (x0, y0, x1, y1) = (r3(b[0] * 304.8), r3(b[1] * 304.8), r3(b[3] * 304.8), r3(b[4] * 304.8));
    let flat = (x1 - x0).abs() < 1e-9 || (y1 - y0).abs() < 1e-9;
    if r.bbox.is_none() {
        return SLine { id: r.id, a: [0.0, 0.0], b: [0.0, 0.0], arc: None, diagonal: None, none: true };
    }
    if flat {
        SLine { id: r.id, a: [x0, y0], b: [x1, y1], arc: None, diagonal: None, none: false }
    } else {
        SLine {
            id: r.id,
            a: [x0, y0],
            b: [x1, y1],
            arc: None,
            diagonal: Some(([x0, y0], [x1, y1], [x0, y1], [x1, y0])),
            none: false,
        }
    }
}

/// The sketch lines of each sketched element (floors, ceilings, roofs), by owner.
pub fn owners(ctx: &Ctx) -> std::collections::BTreeMap<u64, Vec<SLine>> {
    let mut out: std::collections::BTreeMap<u64, Vec<SLine>> = std::collections::BTreeMap::new();
    for r in ctx.instances(cats::OST_SKETCH_LINES) {
        let owners: Vec<u64> = r
            .refs2
            .iter()
            .copied()
            .filter(|id| {
                ctx.is_instance(cats::OST_FLOORS, *id) || ctx.is_instance(cats::OST_CEILINGS, *id) || ctx.is_instance(cats::OST_ROOFS, *id)
            })
            .collect();
        let mut uniq = owners.clone();
        uniq.dedup();
        if uniq.len() != 1 {
            continue;
        }
        out.entry(uniq[0]).or_default().push(line_of(ctx, r));
    }
    for v in out.values_mut() {
        v.sort_by_key(|l| l.id);
    }
    out
}

pub enum Trace {
    /// Closed loops: each an outer boundary (counter-clockwise) with its voids (clockwise).
    Loops { loops: Vec<(Vec<P>, Vec<Vec<P>>)>, leftover: Vec<u64> },
    /// One open chain, its ends joined by a straight line.
    Open(Vec<P>),
    /// Nothing the reader can follow.
    Fail,
}

/// The polygon of a chain of lines, each with its direction (`true` from a to b): each vertex
/// where the lines meet (its place the last line end found there), an arc's chords after its
/// start; an open chain ends at its last line's end.
fn chain_points(lines: &[SLine], ends: &[(usize, usize)], verts: &[P], chain: &[(usize, bool)], closed: bool) -> Vec<P> {
    let mut pts: Vec<P> = Vec::new();
    let n = chain.len();
    for &(i, fwd) in chain.iter() {
        let l = &lines[i];
        pts.push(verts[if fwd { ends[i].0 } else { ends[i].1 }]);
        if let Some(a) = &l.arc {
            let ap = arc_pts(a, !fwd);
            if ap.len() > 2 {
                pts.extend_from_slice(&ap[1..ap.len() - 1]);
            }
        }
    }
    if !closed {
        let (li, lf) = chain[n - 1];
        pts.push(verts[if lf { ends[li].1 } else { ends[li].0 }]);
    }
    pts
}

/// An open chain closed by the straight line between its ends, walked as a loop is: from its
/// lowest line's start in that line's direction; counter-clockwise.
fn joined_points(lines: &[SLine], ends: &[(usize, usize)], verts: &[P], chain: &[(usize, bool)]) -> Vec<P> {
    // the points along the chain, and where each line starts among them
    let mut pts: Vec<P> = Vec::new();
    let mut starts: Vec<usize> = Vec::new();
    for &(i, fwd) in chain.iter() {
        starts.push(pts.len());
        pts.push(verts[if fwd { ends[i].0 } else { ends[i].1 }]);
        if let Some(a) = &lines[i].arc {
            let ap = arc_pts(a, !fwd);
            if ap.len() > 2 {
                pts.extend_from_slice(&ap[1..ap.len() - 1]);
            }
        }
    }
    let (li, lf) = chain[chain.len() - 1];
    pts.push(verts[if lf { ends[li].1 } else { ends[li].0 }]);
    let n = pts.len();
    let (k, &(_, fwd)) = chain.iter().enumerate().min_by_key(|(_, (i, _))| lines[*i].id).unwrap();
    let mut out: Vec<P> = Vec::with_capacity(n);
    if fwd {
        let s0 = starts[k];
        for j in 0..n {
            out.push(pts[(s0 + j) % n]);
        }
    } else {
        // the line runs against the chain: the walk goes back along it from its own start
        let s0 = if k + 1 < starts.len() { starts[k + 1] } else { n - 1 };
        for j in 0..n {
            out.push(pts[(s0 + n - j) % n]);
        }
    }
    if plan::area(&out) < 0.0 {
        out.reverse();
    }
    out
}

fn seg_cross(a0: P, a1: P, b0: P, b1: P) -> bool {
    let d = |p: P, q: P, r: P| (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
    let (d1, d2, d3, d4) = (d(b0, b1, a0), d(b0, b1, a1), d(a0, a1, b0), d(a0, a1, b1));
    ((d1 > 1e-9 && d2 < -1e-9) || (d1 < -1e-9 && d2 > 1e-9)) && ((d3 > 1e-9 && d4 < -1e-9) || (d3 < -1e-9 && d4 > 1e-9))
}

fn polys_cross(p: &[P], q: &[P]) -> bool {
    for i in 0..p.len() {
        let (a0, a1) = (p[i], p[(i + 1) % p.len()]);
        for j in 0..q.len() {
            let (b0, b1) = (q[j], q[(j + 1) % q.len()]);
            if seg_cross(a0, a1, b0, b1) {
                return true;
            }
        }
    }
    false
}

/// Traces the lines into loops.
pub fn trace(input: &[SLine]) -> Trace {
    if input.iter().any(|l| l.none) {
        return Trace::Fail;
    }
    let mut lines: Vec<SLine> = input.to_vec();
    // up to 2023: settle each diagonal by the open ends the others leave
    let diag: Vec<usize> = (0..lines.len()).filter(|i| lines[*i].diagonal.is_some()).collect();
    if !diag.is_empty() {
        let fixed: Vec<usize> = (0..lines.len()).filter(|i| lines[*i].diagonal.is_none()).collect();
        let free = |pt: P, lines: &[SLine], idx: &[usize]| -> bool {
            idx.iter().filter(|i| dist(lines[**i].a, pt) < JOIN || dist(lines[**i].b, pt) < JOIN).count() == 1
        };
        for &i in &diag {
            let (m0, m1, n0, n1) = lines[i].diagonal.unwrap();
            let fits_main = free(m0, &lines, &fixed) && free(m1, &lines, &fixed);
            let fits_anti = free(n0, &lines, &fixed) && free(n1, &lines, &fixed);
            if fits_main == fits_anti {
                return Trace::Fail;
            }
            if fits_main {
                lines[i].a = m0;
                lines[i].b = m1;
            } else {
                lines[i].a = n0;
                lines[i].b = n1;
            }
            lines[i].diagonal = None;
        }
    }
    // the vertices the lines' ends make
    let mut verts: Vec<P> = Vec::new();
    let vid = |p: P, verts: &mut Vec<P>| -> usize {
        if let Some(i) = verts.iter().position(|v| dist(*v, p) < JOIN) {
            verts[i] = p;
            i
        } else {
            verts.push(p);
            verts.len() - 1
        }
    };
    let ends: Vec<(usize, usize)> = lines
        .iter()
        .map(|l| {
            let a = vid(l.a, &mut verts);
            let b = vid(l.b, &mut verts);
            (a, b)
        })
        .collect();
    let mut deg = vec![0usize; verts.len()];
    for &(a, b) in &ends {
        deg[a] += 1;
        deg[b] += 1;
        if a == b {
            return Trace::Fail;
        }
    }
    if deg.iter().any(|d| *d > 2) {
        return Trace::Fail;
    }
    // components: a walk from each unused line, by id
    let mut used = vec![false; lines.len()];
    let mut closed: Vec<Vec<(usize, bool)>> = Vec::new();
    let mut open: Vec<Vec<(usize, bool)>> = Vec::new();
    for s in 0..lines.len() {
        if used[s] {
            continue;
        }
        used[s] = true;
        // forward from the line's end
        let mut chain = vec![(s, true)];
        let mut cur = ends[s].1;
        let mut is_closed = false;
        loop {
            if cur == ends[s].0 {
                is_closed = true;
                break;
            }
            let next = (0..lines.len()).find(|i| !used[*i] && (ends[*i].0 == cur || ends[*i].1 == cur));
            match next {
                Some(i) => {
                    used[i] = true;
                    let fwd = ends[i].0 == cur;
                    chain.push((i, fwd));
                    cur = if fwd { ends[i].1 } else { ends[i].0 };
                }
                None => break,
            }
        }
        if !is_closed {
            // and backward from the line's start
            let mut back: Vec<(usize, bool)> = Vec::new();
            let mut cur = ends[s].0;
            loop {
                let next = (0..lines.len()).find(|i| !used[*i] && (ends[*i].0 == cur || ends[*i].1 == cur));
                match next {
                    Some(i) => {
                        used[i] = true;
                        let fwd = ends[i].1 == cur;
                        back.push((i, fwd));
                        cur = if fwd { ends[i].0 } else { ends[i].1 };
                    }
                    None => break,
                }
            }
            back.reverse();
            back.extend(chain);
            open.push(back);
        } else {
            closed.push(chain);
        }
    }
    if closed.is_empty() {
        if open.len() == 1 {
            return Trace::Open(joined_points(&lines, &ends, &verts, &open[0]));
        }
        return Trace::Fail;
    }
    let leftover: Vec<u64> = open.iter().flat_map(|c| c.iter().map(|(i, _)| lines[*i].id)).collect();
    let mut polys: Vec<Vec<P>> = closed.iter().map(|c| chain_points(&lines, &ends, &verts, c, true)).collect();
    for i in 0..polys.len() {
        for j in i + 1..polys.len() {
            if polys_cross(&polys[i], &polys[j]) {
                return Trace::Fail;
            }
        }
    }
    // nesting: a loop inside another is its void (one level)
    let n = polys.len();
    let mut parent: Vec<Option<usize>> = vec![None; n];
    for i in 0..n {
        let probe = polys[i][0];
        let mut best: Option<(usize, f64)> = None;
        for j in 0..n {
            if i != j && plan::inside(&polys[j], probe) {
                let a = plan::area(&polys[j]).abs();
                if best.map(|(_, ba)| a < ba).unwrap_or(true) {
                    best = Some((j, a));
                }
            }
        }
        parent[i] = best.map(|(j, _)| j);
    }
    let mut out: Vec<(Vec<P>, Vec<Vec<P>>)> = Vec::new();
    let mut slot: Vec<Option<usize>> = vec![None; n];
    for i in 0..n {
        let depth_even = {
            let mut d = 0;
            let mut c = parent[i];
            while let Some(p) = c {
                d += 1;
                c = parent[p];
                if d > n {
                    break;
                }
            }
            d % 2 == 0
        };
        if depth_even {
            let mut p = std::mem::take(&mut polys[i]);
            if plan::area(&p) < 0.0 {
                p.reverse();
            }
            slot[i] = Some(out.len());
            out.push((p, Vec::new()));
        }
    }
    for i in 0..n {
        if slot[i].is_none() {
            if let Some(par) = parent[i] {
                if let Some(s) = slot[par] {
                    let mut p = std::mem::take(&mut polys[i]);
                    if plan::area(&p) > 0.0 {
                        p.reverse();
                    }
                    out[s].1.push(p);
                }
            }
        }
    }
    Trace::Loops { loops: out, leftover }
}

/// The footprint of a box (mm), counter-clockwise from its south-west corner.
pub fn footprint(b: &[f64; 6]) -> Vec<P> {
    let (x0, y0, x1, y1) = (r3(b[0] * 304.8), r3(b[1] * 304.8), r3(b[3] * 304.8), r3(b[4] * 304.8));
    vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
}
