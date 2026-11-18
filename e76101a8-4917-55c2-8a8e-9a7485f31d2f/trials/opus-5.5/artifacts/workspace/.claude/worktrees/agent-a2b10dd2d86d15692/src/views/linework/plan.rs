//! What a plan draws of the model, in plan mm, as the lines Linework picks its edges from: a cut
//! wall's outline where no other cut wall lies against it (each run carried a pixel on round the
//! corner into the wall it meets), a seen wall's whole outline, a door's jambs, leaf and swing, a
//! window's jambs and lines, a column's or a footing's outline, a floor's and an overhead roof's
//! edges. A wall's outline is its faces and its caps: free, mitred where walls meet end to end (at
//! any angle, any number of them), or stopped at the face of the wall it ends on.

use super::super::common::*;
use super::super::model::{centre_offset, location_line, wall_thickness, WallLine};
use crate::json::Value;
use crate::project::Project;

/// A pixel of the drawing Linework picks in, mm (1 : 100 at 0.2 mm a pixel, 0.05 px a mm).
pub const PIXEL: f64 = 20.0;

/// How near two wall ends meet to join, mm.
pub const JOIN_REACH: f64 = 1.0;

/// A plan: the view it is (a level's own plan, or a plan view) and the heights it cuts and sees.
#[derive(Clone, Copy, Debug)]
pub struct Plan {
    pub key: u64,
    pub level: u64,
    pub elevation: f64,
    pub cut: f64,
    pub bottom: f64,
    /// The point the drawing is centred on, where it is drawn to pick an edge (annotation is
    /// laid out in its pixels).
    pub frame: Option<[f64; 2]>,
}

/// The picking drawing's pixels a mm, and its middle.
pub const PX_SCALE: f64 = 1.0 / PIXEL;
pub const PX_MIDDLE: f64 = 500.0;

/// A point in the picking drawing's pixels (single precision), round `at`.
pub fn to_px(p: [f64; 2], at: [f64; 2]) -> [f64; 2] {
    [((p[0] - at[0]) * PX_SCALE + PX_MIDDLE) as f32 as f64, ((at[1] - p[1]) * PX_SCALE + PX_MIDDLE) as f32 as f64]
}

/// A point of the picking drawing back in plan mm.
pub fn from_px(q: [f64; 2], at: [f64; 2]) -> [f64; 2] {
    [(q[0] - PX_MIDDLE) / PX_SCALE + at[0], at[1] - (q[1] - PX_MIDDLE) / PX_SCALE]
}

/// The plan a view key draws: its level, and the heights of its view range (a dependent view's
/// its parent's).
pub fn plan_of(pr: &Project, key: u64) -> Option<Plan> {
    let level = crate::model::level_of_view(pr, key)?;
    let elevation = f_of(pr.el(level)?, "elevation").unwrap_or(0.0);
    let mut source = key;
    if let Some(parent) = pr.el(key).and_then(|e| ref_id(pr, e, "parent")) {
        source = parent;
    }
    let vr = pr.el(source).and_then(|e| e.get("view_range")).cloned().unwrap_or(Value::Null);
    let cut = vr.get("cut").and_then(|c| c.as_f64()).unwrap_or(1200.0);
    let bottom = vr.get("bottom").and_then(|c| c.as_f64()).unwrap_or(0.0);
    Some(Plan { key, level, elevation, cut: elevation + cut, bottom: elevation + bottom, frame: None })
}

/// A line the plan draws: its points in order, and whether it closes back to its first.
#[derive(Clone, Debug)]
pub struct Line {
    pub pts: Vec<[f64; 2]>,
    pub closed: bool,
    /// Whether its edges are given back as the element holds them (a detail line's, a region's),
    /// not as the picking drawing has them.
    pub exact: bool,
}

impl Line {
    pub fn open(pts: Vec<[f64; 2]>) -> Line {
        Line { pts, closed: false, exact: false }
    }
    pub fn ring(pts: Vec<[f64; 2]>) -> Line {
        Line { pts, closed: true, exact: false }
    }
    pub fn exact(mut self) -> Line {
        self.exact = true;
        self
    }
    /// Its segments in order (a closed one's last back to its first).
    pub fn segments(&self) -> Vec<([f64; 2], [f64; 2])> {
        let n = self.pts.len();
        let mut out = Vec::new();
        if n < 2 {
            return out;
        }
        for i in 0..n - 1 {
            out.push((self.pts[i], self.pts[i + 1]));
        }
        if self.closed && n > 2 {
            out.push((self.pts[n - 1], self.pts[0]));
        }
        out
    }
}

// ---------------------------------------------------------------- vectors, as glam does them

fn sub(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] - b[0], a[1] - b[1]]
}
fn add(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] + b[0], a[1] + b[1]]
}
fn mul(a: [f64; 2], k: f64) -> [f64; 2] {
    [a[0] * k, a[1] * k]
}
fn dot(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
fn cross(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
fn len(a: [f64; 2]) -> f64 {
    dot(a, a).sqrt()
}
fn dist(a: [f64; 2], b: [f64; 2]) -> f64 {
    len(sub(a, b))
}
pub fn normalize(a: [f64; 2]) -> [f64; 2] {
    let l = len(a);
    if l == 0.0 {
        return [0.0, 0.0];
    }
    mul(a, 1.0 / l)
}
/// A quarter turn counter-clockwise.
fn perp(a: [f64; 2]) -> [f64; 2] {
    [-a[1], a[0]]
}

/// Where the line through `a` along `u` meets the line through `b` along `w`; None if parallel.
fn meet(a: [f64; 2], u: [f64; 2], b: [f64; 2], w: [f64; 2]) -> Option<[f64; 2]> {
    let d = cross(u, w);
    if d.abs() < 1e-12 {
        return None;
    }
    let s = cross(sub(b, a), w) / d;
    Some(add(a, mul(u, s)))
}

// ---------------------------------------------------------------- walls

/// A wall as the plan reads it.
#[derive(Clone, Debug)]
pub struct Wall {
    pub id: u64,
    pub loc: WallLine,
    pub centre: WallLine,
    pub t: f64,
    pub base: f64,
    pub top: f64,
}

pub fn walls(pr: &Project) -> Vec<Wall> {
    let mut out = Vec::new();
    for (id, e) in &pr.elements {
        if cat(e) != "wall" {
            continue;
        }
        let loc = location_line(e);
        if dist(loc.start, loc.end) < 1e-9 {
            continue;
        }
        let (base, top) = super::super::model::base_top(pr, e);
        out.push(Wall {
            id: *id,
            loc,
            centre: loc.offset(centre_offset(pr, e)),
            t: wall_thickness(pr, e),
            base,
            top,
        });
    }
    out
}

/// The unit direction a wall's line leaves an end by, into the wall.
fn leaving(w: &Wall, at_start: bool) -> [f64; 2] {
    let l = &w.centre;
    if !l.is_arc() {
        let u = normalize(sub(l.end, l.start));
        return if at_start { u } else { mul(u, -1.0) };
    }
    let (c, _) = l.circle().unwrap();
    let p = if at_start { l.start } else { l.end };
    let r = normalize(sub(p, c));
    // a counter-clockwise arc runs a quarter turn on from its radius
    let fwd = if l.arc > 0.0 { perp(r) } else { mul(perp(r), -1.0) };
    if at_start {
        fwd
    } else {
        mul(fwd, -1.0)
    }
}

fn end_point(l: &WallLine, at_start: bool) -> [f64; 2] {
    if at_start {
        l.start
    } else {
        l.end
    }
}

/// How a wall's end meets the others: free, mitred with the walls ending there, or stopped at
/// the face of a wall it ends on.
#[derive(Clone, Debug)]
enum End {
    Free,
    Mitre(Vec<(usize, bool)>),
    Butt(usize),
}

fn spans_meet(a: &Wall, b: &Wall) -> bool {
    a.base < b.top && b.base < a.top
}

fn end_of(ws: &[Wall], i: usize, at_start: bool) -> End {
    let w = &ws[i];
    let p = end_point(&w.loc, at_start);
    let mut group = vec![(i, at_start)];
    for (j, o) in ws.iter().enumerate() {
        if j == i || !spans_meet(w, o) {
            continue;
        }
        for s in [true, false] {
            if dist(end_point(&o.loc, s), p) <= JOIN_REACH {
                group.push((j, s));
                break;
            }
        }
    }
    if group.len() > 1 {
        return End::Mitre(group);
    }
    for (j, o) in ws.iter().enumerate() {
        if j == i || !spans_meet(w, o) || o.centre.is_arc() {
            continue;
        }
        let u = normalize(sub(o.centre.end, o.centre.start));
        let l = dist(o.centre.end, o.centre.start);
        let rel = sub(p, o.centre.start);
        let s = dot(rel, u);
        let off = cross(u, rel);
        if off.abs() <= o.t / 2.0 + 1e-9 && s > JOIN_REACH && s < l - JOIN_REACH {
            return End::Butt(j);
        }
    }
    End::Free
}

/// A wall end's corners, left and right of the wall (as it runs from its start to its end), and
/// the point between them its cap turns at, if it turns.
fn corners(ws: &[Wall], i: usize, at_start: bool) -> ([f64; 2], [f64; 2], Option<[f64; 2]>) {
    let w = &ws[i];
    let c = end_point(&w.centre, at_start);
    let v = leaving(w, at_start);
    let n = perp(v);
    // the wall's own left and right of start → end
    let own_left = if at_start { n } else { mul(n, -1.0) };
    let free = (add(c, mul(own_left, w.t / 2.0)), sub(c, mul(own_left, w.t / 2.0)), None);
    match end_of(ws, i, at_start) {
        End::Free => free,
        End::Butt(j) => {
            let h = &ws[j];
            let hu = normalize(sub(h.centre.end, h.centre.start));
            let hn = perp(hu);
            let side = if dot(v, hn) >= 0.0 { 1.0 } else { -1.0 };
            let face = add(h.centre.start, mul(hn, side * h.t / 2.0));
            let l = meet(add(c, mul(own_left, w.t / 2.0)), v, face, hu);
            let r = meet(sub(c, mul(own_left, w.t / 2.0)), v, face, hu);
            match (l, r) {
                (Some(l), Some(r)) => (l, r, None),
                _ => free,
            }
        }
        End::Mitre(group) => {
            let middle = Some(end_point(&w.loc, at_start));
            match mitre(ws, &group, i, at_start) {
                Some((ccw, cw)) => {
                    // the way out turned a quarter counter-clockwise is the wall's left at its
                    // start, its right at its end
                    if at_start {
                        (ccw, cw, middle)
                    } else {
                        (cw, ccw, middle)
                    }
                }
                // too sharp a corner for this wall to mitre: its end square, through the joint
                None => (free.0, free.1, middle),
            }
        }
    }
}

/// A wall's corners where walls meet end to end, counter-clockwise and clockwise of the way it
/// leaves the joint: where its faces meet the faces of the walls next round. None where either
/// lies further along its face from its end than the thickest of them is thick (too sharp a corner
/// for it to mitre).
fn mitre(ws: &[Wall], group: &[(usize, bool)], i: usize, at_start: bool) -> Option<([f64; 2], [f64; 2])> {
    let mut members: Vec<(usize, bool, [f64; 2], [f64; 2], f64)> = group
        .iter()
        .map(|(k, s)| {
            let wk = &ws[*k];
            let vk = leaving(wk, *s);
            (*k, *s, end_point(&wk.centre, *s), vk, vk[1].atan2(vk[0]))
        })
        .collect();
    members.sort_by(|a, b| a.4.partial_cmp(&b.4).unwrap_or(std::cmp::Ordering::Equal));
    let m = members.len();
    let thickest = group.iter().map(|(k, _)| ws[*k].t).fold(0.0, f64::max);
    let me = members.iter().position(|x| x.0 == i && x.1 == at_start)?;
    let (k, _, pk, vk, _) = members[me];
    let nk = perp(vk);
    let tk = ws[k].t;
    let next = members[(me + 1) % m];
    let prev = members[(me + m - 1) % m];
    let ccw_face = add(pk, mul(nk, tk / 2.0));
    let ccw = {
        let (_, _, pn, vn, _) = next;
        let tn = ws[next.0].t;
        meet(ccw_face, vk, sub(pn, mul(perp(vn), tn / 2.0)), vn).unwrap_or(ccw_face)
    };
    let cw_face = sub(pk, mul(nk, tk / 2.0));
    let cw = {
        let (_, _, pp, vp, _) = prev;
        let tp = ws[prev.0].t;
        meet(cw_face, vk, add(pp, mul(perp(vp), tp / 2.0)), vp).unwrap_or(cw_face)
    };
    for (c, f) in [(ccw, ccw_face), (cw, cw_face)] {
        if dot(sub(c, f), vk).abs() > thickest + 1e-9 {
            return None;
        }
    }
    Some((ccw, cw))
}

/// How many chords draw an arc of `sweep` degrees at radius `r`: none further than a millimetre
/// from it, and none of more than 5°.
pub fn arc_chords(sweep: f64, r: f64) -> usize {
    let t = sweep.abs().to_radians();
    let by_flat = if r > 1.0 { (t / (2.0 * (1.0 - 1.0 / r).acos())).ceil() } else { 1.0 };
    let by_angle = (sweep.abs() / 5.0).ceil();
    by_flat.max(by_angle).max(1.0) as usize
}

/// The points between an arc wall's ends along one of its faces (`d` left of its centre line).
fn face_between(w: &Wall, d: f64) -> Vec<[f64; 2]> {
    let l = &w.centre;
    let Some((c, r)) = l.circle() else { return Vec::new() };
    let n = arc_chords(l.arc, r);
    let a0 = (l.start[1] - c[1]).atan2(l.start[0] - c[0]);
    let sweep = l.arc.to_radians();
    // left of a counter-clockwise arc is toward its centre
    let rf = if l.arc > 0.0 { r - d } else { r + d };
    (1..n)
        .map(|i| {
            let a = a0 + sweep * i as f64 / n as f64;
            [c[0] + rf * a.cos(), c[1] + rf * a.sin()]
        })
        .collect()
}

/// A wall's outline in plan as the drawing goes round it: its start's right corner, its start
/// cap, its left face, its end cap, its right face back.
pub fn outline(ws: &[Wall], i: usize) -> Vec<[f64; 2]> {
    let w = &ws[i];
    let (sl, sr, sm) = corners(ws, i, true);
    let (el, er, em) = corners(ws, i, false);
    let mut ring = vec![sr];
    if let Some(m) = sm {
        ring.push(m);
    }
    ring.push(sl);
    ring.extend(face_between(w, w.t / 2.0));
    ring.push(el);
    if let Some(m) = em {
        ring.push(m);
    }
    ring.push(er);
    let mut right = face_between(w, -w.t / 2.0);
    right.reverse();
    ring.extend(right);
    ring
}

/// Whether a wall is cut by the plan, or seen below its cut.
fn cut_by(w: &Wall, p: &Plan) -> bool {
    w.base <= p.cut && p.cut < w.top
}
fn seen_by(w: &Wall, p: &Plan) -> bool {
    w.top <= p.cut && w.top > p.bottom
}

pub fn seg_dist(p: [f64; 2], a: [f64; 2], b: [f64; 2]) -> f64 {
    let ab = sub(b, a);
    let l2 = dot(ab, ab);
    if l2 == 0.0 {
        return dist(p, a);
    }
    let t = (dot(sub(p, a), ab) / l2).clamp(0.0, 1.0);
    dist(p, add(a, mul(ab, t)))
}

/// The parameters along a→b where it crosses or touches a polygon's edges.
fn crossings(a: [f64; 2], b: [f64; 2], poly: &[[f64; 2]]) -> Vec<f64> {
    let mut ts = Vec::new();
    let d = sub(b, a);
    let l2 = dot(d, d);
    let n = poly.len();
    for k in 0..n {
        let p = poly[k];
        let q = poly[(k + 1) % n];
        let e = sub(q, p);
        let den = cross(d, e);
        if den.abs() > 1e-12 {
            let t = cross(sub(p, a), e) / den;
            let s = cross(sub(p, a), d) / den;
            if (-1e-9..=1.0 + 1e-9).contains(&s) && (0.0..=1.0).contains(&t) {
                ts.push(t);
            }
        } else if l2 > 0.0 {
            // along the same line: its ends where they lie on a→b
            for v in [p, q] {
                if cross(sub(v, a), d).abs() / l2.sqrt() < 1e-6 {
                    let t = dot(sub(v, a), d) / l2;
                    if (0.0..=1.0).contains(&t) {
                        ts.push(t);
                    }
                }
            }
        }
    }
    ts
}

/// The pieces of a ring's edges no other polygon covers: for each edge, its visible spans as
/// (edge, from t, to t).
fn visible_spans(ring: &[[f64; 2]], others: &[Vec<[f64; 2]>]) -> Vec<(usize, f64, f64)> {
    let n = ring.len();
    // which way round the ring goes says which side of each edge is outside it
    let cw = signed_area(ring) < 0.0;
    let mut out = Vec::new();
    for k in 0..n {
        let a = ring[k];
        let b = ring[(k + 1) % n];
        if dist(a, b) < 1e-9 {
            continue;
        }
        let d = normalize(sub(b, a));
        let outward = if cw { perp(d) } else { [d[1], -d[0]] };
        let mut ts = vec![0.0, 1.0];
        for o in others {
            ts.extend(crossings(a, b, o));
        }
        ts.sort_by(|x, y| x.partial_cmp(y).unwrap());
        ts.dedup_by(|x, y| (*x - *y).abs() < 1e-12);
        for w in ts.windows(2) {
            let (t0, t1) = (w[0], w[1]);
            if t1 - t0 < 1e-12 {
                continue;
            }
            // against another where what lies just outside it is the other's
            let m = add(a, mul(sub(b, a), (t0 + t1) / 2.0));
            let probe = add(m, mul(outward, JOIN_REACH));
            if !others.iter().any(|o| inside(probe, o)) {
                out.push((k, t0, t1));
            }
        }
    }
    out
}

/// A ring's area, positive counter-clockwise.
fn signed_area(ring: &[[f64; 2]]) -> f64 {
    let n = ring.len();
    let mut s = 0.0;
    for i in 0..n {
        s += cross(ring[i], ring[(i + 1) % n]);
    }
    s / 2.0
}

/// Whether a point lies inside a polygon (even-odd).
fn inside(p: [f64; 2], poly: &[[f64; 2]]) -> bool {
    let n = poly.len();
    let mut c = false;
    let mut j = n - 1;
    for k in 0..n {
        let (a, b) = (poly[k], poly[j]);
        if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0] {
            c = !c;
        }
        j = k;
    }
    c
}

fn at_t(ring: &[[f64; 2]], k: usize, t: f64) -> [f64; 2] {
    let a = ring[k];
    let b = ring[(k + 1) % ring.len()];
    if t <= 0.0 {
        return a;
    }
    if t >= 1.0 {
        return b;
    }
    add(a, mul(sub(b, a), t))
}

/// A cut wall's runs: its outline's visible spans, joined where they follow on round the ring,
/// the last joined to the first where the ring's start is visible. None where all of it is (the
/// whole ring is then one closed line).
fn runs(ring: &[[f64; 2]], spans: &[(usize, f64, f64)]) -> Option<Vec<Vec<[f64; 2]>>> {
    let n = ring.len();
    // all of it to be seen: the ring whole
    let edges: Vec<usize> = (0..n).filter(|k| dist(ring[*k], ring[(k + 1) % n]) >= 1e-9).collect();
    let covered = |k: usize| -> f64 { spans.iter().filter(|s| s.0 == k).map(|s| s.2 - s.1).sum() };
    if edges.iter().all(|k| (covered(*k) - 1.0).abs() < 1e-9) {
        return None;
    }
    let mut out: Vec<Vec<[f64; 2]>> = Vec::new();
    let mut prev: Option<(usize, f64)> = None;
    for &(k, t0, t1) in spans {
        let a = at_t(ring, k, t0);
        let b = at_t(ring, k, t1);
        let follows = match prev {
            Some((pk, pt1)) => (pk == k && (pt1 - t0).abs() < 1e-12) || (pt1 >= 1.0 && t0 <= 0.0 && next_edge(ring, pk) == k),
            None => false,
        };
        if follows {
            out.last_mut().unwrap().push(b);
        } else {
            out.push(vec![a, b]);
        }
        prev = Some((k, t1));
    }
    // the last run ends where the ring starts and the first starts there: one run
    if out.len() > 1 {
        let first = spans[0];
        let last = spans[spans.len() - 1];
        if first.1 <= 0.0 && last.2 >= 1.0 && next_edge(ring, last.0) == first.0 {
            let tail = out.pop().unwrap();
            let head = std::mem::take(&mut out[0]);
            let mut merged = tail;
            merged.extend(head.into_iter().skip(1));
            out[0] = merged;
        }
    }
    Some(out)
}

/// The next edge round a ring that has length.
fn next_edge(ring: &[[f64; 2]], k: usize) -> usize {
    let n = ring.len();
    let mut j = (k + 1) % n;
    for _ in 0..n {
        if dist(ring[j], ring[(j + 1) % n]) >= 1e-9 {
            return j;
        }
        j = (j + 1) % n;
    }
    j
}

/// What the plan cuts or sees as solids: walls and columns, their outlines, and for those it cuts
/// their runs (where nothing else it cuts lies against them).
pub struct Solids {
    pub ws: Vec<Wall>,
    pub ids: Vec<u64>,
    pub rings: Vec<Vec<[f64; 2]>>,
    pub cut: Vec<bool>,
    pub seen: Vec<bool>,
    /// Each cut solid's runs (None: drawn whole, a closed ring).
    pub runs: Vec<Option<Vec<Vec<[f64; 2]>>>>,
}

/// How many sides draw a round column.
pub const ROUND_SIDES: usize = 24;

/// A column's (or a structural column's, or a footing's) outline in plan: its type's width along
/// its angle by its depth, or round.
pub fn column_ring(pr: &Project, e: &Value) -> Option<Vec<[f64; 2]>> {
    let c = pt_of(e, "at")?;
    let t = super::super::tags::fields::type_def(pr, e);
    let w = t.and_then(|t| f_of(t, "width")).unwrap_or(400.0);
    let d = t.and_then(|t| f_of(t, "depth")).unwrap_or(w);
    let round = t.and_then(|t| t.get("round")).and_then(|r| r.as_bool()).unwrap_or(false);
    let a = f_of(e, "angle").unwrap_or(0.0).to_radians();
    if round {
        let r = w / 2.0;
        return Some(
            (0..ROUND_SIDES)
                .map(|i| {
                    let t = a + std::f64::consts::TAU * i as f64 / ROUND_SIDES as f64;
                    [c[0] + r * t.cos(), c[1] + r * t.sin()]
                })
                .collect(),
        );
    }
    let (ca, sa) = (a.cos(), a.sin());
    Some(
        [[-w / 2.0, -d / 2.0], [w / 2.0, -d / 2.0], [w / 2.0, d / 2.0], [-w / 2.0, d / 2.0]]
            .iter()
            .map(|p| [c[0] + (p[0] * ca - p[1] * sa), c[1] + (p[0] * sa + p[1] * ca)])
            .collect(),
    )
}

pub fn plan_solids(pr: &Project, plan: &Plan) -> Solids {
    // walls join as the model has them; what the plan hides is not drawn
    let ws = walls(pr);
    let mut ids: Vec<u64> = ws.iter().map(|w| w.id).collect();
    let mut rings: Vec<Vec<[f64; 2]>> = (0..ws.len()).map(|i| outline(&ws, i)).collect();
    let mut cut: Vec<bool> = ws.iter().map(|w| !hidden(pr, plan, w.id) && cut_by(w, plan)).collect();
    let mut seen: Vec<bool> =
        ws.iter().enumerate().map(|(i, w)| !hidden(pr, plan, w.id) && !cut[i] && seen_by(w, plan)).collect();
    for (id, e) in &pr.elements {
        let c = cat(e);
        if !matches!(c, "column" | "structuralcolumn" | "footing") {
            continue;
        }
        let Some(ring) = column_ring(pr, e) else { continue };
        let shown = !hidden(pr, plan, *id);
        let (is_cut, is_seen) = if c == "footing" {
            // a footing is seen in its level's plan
            (false, shown && ref_id(pr, e, "level") == Some(plan.level))
        } else {
            let (base, top) = super::super::model::base_top(pr, e);
            let k = shown && base <= plan.cut && plan.cut < top;
            (k, shown && !k && top <= plan.cut && top > plan.bottom)
        };
        ids.push(*id);
        rings.push(ring);
        cut.push(is_cut);
        seen.push(is_seen);
    }
    let mut rs = Vec::new();
    for i in 0..ids.len() {
        if !cut[i] {
            rs.push(None);
            continue;
        }
        let others: Vec<Vec<[f64; 2]>> =
            (0..ids.len()).filter(|j| *j != i && cut[*j]).map(|j| rings[j].clone()).collect();
        let spans = visible_spans(&rings[i], &others);
        rs.push(runs(&rings[i], &spans));
    }
    Solids { ws, ids, rings, cut, seen, runs: rs }
}

/// A solid's lines: a seen one's whole outline; a cut one's runs, each carried a pixel round the
/// corner into what it meets (its whole outline, closed, where nothing meets it).
fn solid_lines(sd: &Solids, i: usize) -> Vec<Line> {
    if sd.seen[i] {
        return vec![Line::ring(sd.rings[i].clone())];
    }
    if !sd.cut[i] {
        return Vec::new();
    }
    let Some(runs) = &sd.runs[i] else { return vec![Line::ring(sd.rings[i].clone())] };
    // the other cut solids' runs, to turn the corner along
    let mut others: Vec<&Vec<[f64; 2]>> = Vec::new();
    for j in 0..sd.ids.len() {
        if j == i || !sd.cut[j] {
            continue;
        }
        if let Some(rj) = &sd.runs[j] {
            others.extend(rj.iter());
        }
    }
    // where another's run ends at a run's end, round the corner along it
    let turn = |p: [f64; 2]| -> Option<[f64; 2]> {
        for r in &others {
            let n = r.len();
            if n < 2 {
                continue;
            }
            if dist(r[0], p) < 1e-6 {
                return Some(add(p, mul(normalize(sub(r[1], p)), PIXEL)));
            }
            if dist(r[n - 1], p) < 1e-6 {
                return Some(add(p, mul(normalize(sub(r[n - 2], p)), PIXEL)));
            }
        }
        None
    };
    let mut out = Vec::new();
    for r in runs {
        let mut pts = r.clone();
        if let Some(s) = turn(pts[0]) {
            pts.insert(0, s);
        }
        if let Some(e) = turn(*pts.last().unwrap()) {
            pts.push(e);
        }
        out.push(Line::open(pts));
    }
    out
}

// ---------------------------------------------------------------- what the plan hides

/// Whether a plan hides an element: its category, or it, in the plan's graphics (a dependent
/// view's its parent's).
pub fn hidden(pr: &Project, plan: &Plan, id: u64) -> bool {
    let mut src = plan.key;
    if let Some(parent) = pr.el(plan.key).and_then(|e| ref_id(pr, e, "parent")) {
        src = parent;
    }
    let Some(g) = pr.el(src).and_then(|v| v.get("graphics")) else { return false };
    let c = cat_of(pr, id);
    if g.get("categories").and_then(|m| m.get(&c)).and_then(|o| o.get("hidden")).and_then(|h| h.as_bool()) == Some(true) {
        return true;
    }
    let gid = guid(pr, id);
    g.get("elements").and_then(|m| m.get(&gid)).and_then(|o| o.get("hidden")).and_then(|h| h.as_bool()) == Some(true)
}

// ---------------------------------------------------------------- doors and windows

/// How many chords draw a door's swing (a quarter turn).
pub const SWING_CHORDS: usize = 24;

fn opening_lines(pr: &Project, plan: &Plan, pw: &Solids, id: u64) -> Vec<Line> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let is_door = cat(e) == "door";
    let Some(wid) = ref_id(pr, e, "host") else { return Vec::new() };
    let Some(wi) = pw.ws.iter().position(|w| w.id == wid) else { return Vec::new() };
    if !pw.cut[wi] {
        return Vec::new();
    }
    let w = &pw.ws[wi];
    if e.get("family").map(|f| !f.is_null()).unwrap_or(false) {
        return family_door_lines(pr, plan, e, w);
    }
    let ty = super::super::tags::fields::type_def(pr, e);
    let width = ty.and_then(|t| f_of(t, "width")).unwrap_or(900.0);
    let height = ty.and_then(|t| f_of(t, "height")).unwrap_or(2100.0);
    let sill = f_of(e, "sill").unwrap_or(0.0);
    let lo = w.base + sill;
    if !(lo <= plan.cut && plan.cut < lo + height) {
        return Vec::new();
    }
    if w.loc.is_arc() {
        return arc_opening_lines(e, w, is_door, width);
    }
    let offset = f_of(e, "offset").unwrap_or(0.0);
    let u = normalize(sub(w.loc.end, w.loc.start));
    let n = perp(u);
    let co = dot(sub(w.centre.start, w.loc.start), n);
    let at = |s: f64, d: f64| -> [f64; 2] { add(add(w.loc.start, mul(u, s)), mul(n, co + d)) };
    let (s0, s1) = (offset - width / 2.0, offset + width / 2.0);
    let half = w.t / 2.0;
    let mut out = vec![Line::open(vec![at(s0, -half), at(s0, half)]), Line::open(vec![at(s1, -half), at(s1, half)])];
    if is_door {
        let flip_facing = e.get("flip_facing").and_then(|f| f.as_bool()).unwrap_or(false);
        let flip_hand = e.get("flip_hand").and_then(|f| f.as_bool()).unwrap_or(false);
        let side = if flip_facing { -1.0 } else { 1.0 };
        let (sh, so) = if flip_hand { (s1, s0) } else { (s0, s1) };
        let hinge = at(sh, side * half);
        let open_dir = mul(n, side);
        let tip = add(hinge, mul(open_dir, width));
        out.push(Line::open(vec![hinge, tip]));
        // the swing, from the leaf's tip round to the other jamb
        let to = at(so, side * half);
        let a0 = open_dir[1].atan2(open_dir[0]);
        let d1 = normalize(sub(to, hinge));
        let mut a1 = d1[1].atan2(d1[0]);
        let mut da = a1 - a0;
        while da > std::f64::consts::PI {
            a1 -= std::f64::consts::TAU;
            da = a1 - a0;
        }
        while da < -std::f64::consts::PI {
            a1 += std::f64::consts::TAU;
            da = a1 - a0;
        }
        let mut arc = Vec::with_capacity(SWING_CHORDS + 1);
        for k in 0..=SWING_CHORDS {
            let a = a0 + da * k as f64 / SWING_CHORDS as f64;
            arc.push([hinge[0] + width * a.cos(), hinge[1] + width * a.sin()]);
        }
        out.push(Line::open(arc));
    } else {
        for d in [-half, 0.0, half] {
            out.push(Line::open(vec![at(s0, d), at(s1, d)]));
        }
    }
    out
}

/// A door's or a window's lines in a curved wall: its jambs along the radius, a window's lines
/// along its faces and its middle, a door's leaf square to the wall from its hinge, as long as
/// the opening is across, and its swing round to the other jamb.
fn arc_opening_lines(e: &Value, w: &Wall, is_door: bool, width: f64) -> Vec<Line> {
    let Some((c, r)) = w.loc.circle() else { return Vec::new() };
    let Some((_, rc)) = w.centre.circle() else { return Vec::new() };
    let offset = f_of(e, "offset").unwrap_or(0.0);
    let sign = if w.loc.arc > 0.0 { 1.0 } else { -1.0 };
    let a_start = (w.loc.start[1] - c[1]).atan2(w.loc.start[0] - c[0]);
    let angle = |s: f64| a_start + sign * s / r;
    // left of a counter-clockwise arc is toward its centre
    let radius = |d: f64| if sign > 0.0 { rc - d } else { rc + d };
    let at = |s: f64, d: f64| -> [f64; 2] {
        let a = angle(s);
        let rr = radius(d);
        [c[0] + rr * a.cos(), c[1] + rr * a.sin()]
    };
    let (s0, s1) = (offset - width / 2.0, offset + width / 2.0);
    let half = w.t / 2.0;
    let mut out = vec![Line::open(vec![at(s0, -half), at(s0, half)]), Line::open(vec![at(s1, -half), at(s1, half)])];
    if is_door {
        let flip_facing = e.get("flip_facing").and_then(|f| f.as_bool()).unwrap_or(false);
        let flip_hand = e.get("flip_hand").and_then(|f| f.as_bool()).unwrap_or(false);
        let side = if flip_facing { -1.0 } else { 1.0 };
        let (sh, so) = if flip_hand { (s1, s0) } else { (s0, s1) };
        let hinge = at(sh, side * half);
        let to = at(so, side * half);
        let reach = dist(to, hinge);
        // square to the wall at the hinge, toward the side it opens to
        let open_dir = normalize(sub(at(sh, side * (half + 1.0)), hinge));
        let tip = add(hinge, mul(open_dir, reach));
        out.push(Line::open(vec![hinge, tip]));
        let a0 = open_dir[1].atan2(open_dir[0]);
        let d1 = normalize(sub(to, hinge));
        let mut da = d1[1].atan2(d1[0]) - a0;
        while da > std::f64::consts::PI {
            da -= std::f64::consts::TAU;
        }
        while da < -std::f64::consts::PI {
            da += std::f64::consts::TAU;
        }
        let mut arc = Vec::with_capacity(SWING_CHORDS + 1);
        for k in 0..=SWING_CHORDS {
            let a = a0 + da * k as f64 / SWING_CHORDS as f64;
            arc.push([hinge[0] + reach * a.cos(), hinge[1] + reach * a.sin()]);
        }
        out.push(Line::open(arc));
    } else {
        let sweep = ((s1 - s0) / r).to_degrees();
        let n = arc_chords(sweep, rc);
        for d in [-half, 0.0, half] {
            let pts: Vec<[f64; 2]> = (0..=n).map(|k| at(s0 + (s1 - s0) * k as f64 / n as f64, d)).collect();
            out.push(Line::open(pts));
        }
    }
    out
}

// ---------------------------------------------------------------- the rest

fn slab_lines(pr: &Project, plan: &Plan, id: u64) -> Vec<Line> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let Some(b) = pts_of(e, "boundary") else { return Vec::new() };
    let lv = super::super::model::level_elevation(pr, e, "level");
    match cat(e) {
        "floor" => {
            // its top seen between the plan's bottom and its cut
            let top = lv.unwrap_or(0.0) + f_of(e, "offset").unwrap_or(0.0);
            if !(plan.bottom <= top && top <= plan.cut) {
                return Vec::new();
            }
        }
        "roof" => {
            if lv.map(|l| l < plan.elevation).unwrap_or(true) {
                return Vec::new();
            }
            // in its own level's plan, a hipped roof over a rectangle shows its slopes
            if ref_id(pr, e, "level") == Some(plan.level) && f_of(e, "slope").unwrap_or(30.0) != 0.0 {
                let gable = e.get("gable").and_then(|g| g.as_bool()).unwrap_or(false);
                let gables = e.get("gables").and_then(|g| g.as_arr()).map(|a| !a.is_empty()).unwrap_or(false);
                if !gables && e.get("extrusion").map(|x| x.is_null()).unwrap_or(true) {
                    if let Some(faces) = hip_faces(&b, gable) {
                        return faces.into_iter().map(Line::ring).collect();
                    }
                }
            }
        }
        _ => return Vec::new(),
    }
    let mut out = vec![Line::ring(b)];
    if let Some(a) = e.get("openings").and_then(|o| o.as_arr()) {
        for o in a {
            let pts: Option<Vec<[f64; 2]>> = o
                .as_arr()
                .map(|q| q.iter().filter_map(|p| { let a = p.as_arr()?; Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?]) }).collect());
            if let Some(pts) = pts {
                if pts.len() >= 3 {
                    out.push(Line::ring(pts));
                }
            }
        }
    }
    out
}

/// The lines a plan draws of an element, in the order it draws them.
pub fn element_lines(pr: &Project, plan: &Plan, id: u64) -> Vec<Line> {
    if hidden(pr, plan, id) {
        return Vec::new();
    }
    let c = cat_of(pr, id);
    match c.as_str() {
        "wall" | "column" | "structuralcolumn" | "footing" => {
            let sd = plan_solids(pr, plan);
            match sd.ids.iter().position(|x| *x == id) {
                Some(i) => solid_lines(&sd, i),
                None => Vec::new(),
            }
        }
        "door" | "window" => {
            let sd = plan_solids(pr, plan);
            opening_lines(pr, plan, &sd, id)
        }
        "floor" | "roof" => slab_lines(pr, plan, id),
        "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "cable" | "downconductor" | "groundconductor" | "beam"
        | "stripfooting" => run_lines(pr, plan, id),
        "railing" | "roomseparator" | "mass" | "shaft" | "ramp" | "grid" | "section" => other_lines(pr, plan, id),
        "stair" => stair_lines(pr, plan, id),
        "line" | "region" => detail_lines(pr, plan, id),
        _ => Vec::new(),
    }
}

/// Whether an element stands on the plan's level.
fn on_level(pr: &Project, plan: &Plan, e: &Value) -> bool {
    ref_id(pr, e, "level") == Some(plan.level)
}

/// A run's outline, its width across (a round one's diameter), and its centre line.
fn run_lines(pr: &Project, plan: &Plan, id: u64) -> Vec<Line> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    if !on_level(pr, plan, e) {
        return Vec::new();
    }
    let (Some(a), Some(b)) = (pt_of(e, "start"), pt_of(e, "end")) else { return Vec::new() };
    if dist(a, b) < 1e-9 {
        return Vec::new();
    }
    let w = super::super::tags::fields::type_def(pr, e).and_then(|t| f_of(t, "width")).unwrap_or(100.0);
    let n = perp(normalize(sub(b, a)));
    let h = w / 2.0;
    vec![
        Line::ring(vec![sub(a, mul(n, h)), sub(b, mul(n, h)), add(b, mul(n, h)), add(a, mul(n, h))]),
        Line::open(vec![a, b]),
    ]
}

/// Railings' paths, room separators, masses', shafts' and ramps' outlines (a shaft's crossed),
/// grids' lines.
fn other_lines(pr: &Project, plan: &Plan, id: u64) -> Vec<Line> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    match cat(e) {
        "railing" => {
            if !on_level(pr, plan, e) {
                return Vec::new();
            }
            match pts_of(e, "path") {
                Some(p) if p.len() >= 2 => vec![Line::open(p)],
                _ => Vec::new(),
            }
        }
        "roomseparator" => {
            if !on_level(pr, plan, e) {
                return Vec::new();
            }
            match (pt_of(e, "start"), pt_of(e, "end")) {
                (Some(a), Some(b)) => vec![Line::open(vec![a, b])],
                _ => Vec::new(),
            }
        }
        "mass" => {
            if !on_level(pr, plan, e) {
                return Vec::new();
            }
            match pts_of(e, "boundary") {
                Some(b) if b.len() >= 3 => vec![Line::ring(b)],
                _ => Vec::new(),
            }
        }
        "shaft" => {
            let (base, top) = super::super::model::base_top(pr, e);
            if !(base <= plan.cut && top > plan.bottom) {
                return Vec::new();
            }
            match pts_of(e, "boundary") {
                Some(b) if b.len() == 4 => vec![
                    Line::ring(b.clone()),
                    Line::open(vec![b[0], b[2]]),
                    Line::open(vec![b[3], b[1]]),
                ],
                Some(b) if b.len() >= 3 => vec![Line::ring(b)],
                _ => Vec::new(),
            }
        }
        "ramp" => {
            if !on_level(pr, plan, e) {
                return Vec::new();
            }
            let Some(st) = pt_of(e, "start") else { return Vec::new() };
            let ang = f_of(e, "angle").unwrap_or(0.0).to_radians();
            let width = f_of(e, "width").unwrap_or(1200.0);
            let slope = f_of(e, "slope").unwrap_or(8.333333333333334);
            let height = f_of(e, "height").unwrap_or(3000.0);
            let length = if slope > 0.0 { height / slope * 100.0 } else { 0.0 };
            let u = [ang.cos(), ang.sin()];
            let n = perp(u);
            let h = width / 2.0;
            let end = add(st, mul(u, length));
            vec![Line::ring(vec![sub(st, mul(n, h)), sub(end, mul(n, h)), add(end, mul(n, h)), add(st, mul(n, h))]), Line::open(vec![st, end])]
        }
        "grid" => match (pt_of(e, "start"), pt_of(e, "end")) {
            (Some(a), Some(b)) if dist(a, b) > 1e-9 => {
                // its line, and a bubble at each end, 2.2 mm across on paper
                let sc = plan_scale(pr, plan);
                let u = normalize(sub(b, a));
                vec![Line::open(vec![a, b]), Line::ring(bubble(plan, a, mul(u, -1.0), sc)), Line::ring(bubble(plan, b, u, sc))]
            }
            _ => Vec::new(),
        },
        "section" => match (pt_of(e, "start"), pt_of(e, "end")) {
            (Some(a), Some(b)) if dist(a, b) > 1e-9 => {
                // its line, and at its end a tick the way it looks (to its left)
                let k = SECTION_TICK * plan_scale(pr, plan);
                let left = perp(normalize(sub(b, a)));
                let tip = match plan.frame {
                    // laid out in the picking drawing's pixels, y running down it
                    Some(at) => {
                        let t = to_px(b, at);
                        let kp = k * PX_SCALE;
                        from_px([(t[0] + left[0] * kp) as f32 as f64, (t[1] - left[1] * kp) as f32 as f64], at)
                    }
                    None => add(b, mul(left, k)),
                };
                vec![Line::open(vec![a, b]), Line::open(vec![b, tip])]
            }
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

/// A roof's slopes over a rectangle (its outline taken counter-clockwise), each from its eave up
/// to the ridge, in the outline's order: hipped, the long sides' trapezoids and the short sides'
/// triangles (a square's four meet at its middle); with `gable`, its short ends upright and its
/// long sides' slopes meeting along the whole ridge. None for any other outline.
fn hip_faces(b: &[[f64; 2]], gable: bool) -> Option<Vec<Vec<[f64; 2]>>> {
    if b.len() != 4 {
        return None;
    }
    for i in 0..4 {
        let e0 = sub(b[(i + 1) % 4], b[i]);
        let e1 = sub(b[(i + 2) % 4], b[(i + 1) % 4]);
        if dot(e0, e1).abs() > 1e-6 * len(e0) * len(e1) {
            return None;
        }
    }
    let mut b: Vec<[f64; 2]> = b.to_vec();
    if cross(sub(b[1], b[0]), sub(b[2], b[1])) < 0.0 {
        b.reverse();
    }
    let a = dist(b[0], b[1]);
    let c = dist(b[1], b[2]);
    let centre = mul(add(add(b[0], b[1]), add(b[2], b[3])), 0.25);
    // the ridge runs along the longer sides, its ends as far in from the short ones as they are long
    // halved (at them, between gables)
    let (u, long) = if a >= c { (normalize(sub(b[1], b[0])), a) } else { (normalize(sub(b[2], b[1])), c) };
    let short = if a >= c { c } else { a };
    let half = if gable { long / 2.0 } else { (long - short) / 2.0 };
    let r_a = sub(centre, mul(u, half));
    let r_b = add(centre, mul(u, half));
    let near = |p: [f64; 2]| if dot(sub(p, centre), u) < 0.0 { r_a } else { r_b };
    let mut faces = Vec::new();
    for i in 0..4 {
        let p = b[i];
        let q = b[(i + 1) % 4];
        let along = dot(normalize(sub(q, p)), u).abs() > 0.5;
        if gable && !along && dist(p, q) <= long {
            continue;
        }
        let (rp, rq) = (near(p), near(q));
        if dist(rp, rq) < 1e-9 {
            faces.push(vec![p, q, rq]);
        } else {
            faces.push(vec![p, q, rq, rp]);
        }
    }
    Some(faces)
}

/// A straight stair in its level's plan: a line across at each riser, its sides (cut where the
/// plan cuts it, midway up the tread over the last riser below its cut), the cut line slanting
/// across there, and its walking line up its middle.
fn stair_lines(pr: &Project, plan: &Plan, id: u64) -> Vec<Line> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    if !on_level(pr, plan, e) {
        return Vec::new();
    }
    if e.get("landings").and_then(|l| l.as_arr()).map(|a| !a.is_empty()).unwrap_or(false) {
        return Vec::new();
    }
    let Some(st) = pt_of(e, "start") else { return Vec::new() };
    let ang = f_of(e, "angle").unwrap_or(0.0).to_radians();
    let width = f_of(e, "width").unwrap_or(1000.0);
    let height = f_of(e, "height").unwrap_or(3000.0);
    let riser_max = f_of(e, "riser").unwrap_or(180.0);
    let tread = f_of(e, "tread").unwrap_or(280.0);
    if riser_max <= 0.0 || height <= 0.0 {
        return Vec::new();
    }
    let risers = (height / riser_max - 1e-9).ceil().max(1.0) as usize;
    let rh = height / risers as f64;
    let length = (risers - 1) as f64 * tread;
    let u = [ang.cos(), ang.sin()];
    let right = [u[1], -u[0]];
    let h = width / 2.0;
    let at = |d: f64, side: f64| -> [f64; 2] { add(add(st, mul(u, d)), mul(right, side * h)) };
    let mut out = Vec::new();
    for k in 0..risers {
        let d = k as f64 * tread;
        out.push(Line::open(vec![at(d, 1.0), at(d, -1.0)]));
    }
    let base = super::super::model::level_elevation(pr, e, "level").unwrap_or(plan.elevation);
    let below = ((plan.cut - base) / rh).floor();
    let cut = (below + 0.5) * tread;
    let is_cut = below >= 0.0 && cut < length;
    for side in [1.0, -1.0] {
        if is_cut {
            out.push(Line::open(vec![at(0.0, side), at(cut, side)]));
            out.push(Line::open(vec![at(cut, side), at(length, side)]));
        } else {
            out.push(Line::open(vec![at(0.0, side), at(length, side)]));
        }
    }
    if is_cut {
        out.push(Line::open(vec![at(cut - 0.4 * tread, 1.0), at(cut + 0.4 * tread, -1.0)]));
    }
    out.push(Line::open(vec![at(0.0, 0.0), at(length, 0.0)]));
    out
}

/// A grid bubble's radius and a section mark's tick, mm on paper.
pub const BUBBLE: f64 = 2.2;
pub const SECTION_TICK: f64 = 1.8;
/// How many chords draw a grid's bubble.
pub const BUBBLE_CHORDS: usize = 32;

/// A plan's scale, the n of 1 : n (its own, a dependent view's its parent's; 1 : 100, or 1 : 96 in
/// feet and inches, until set).
pub fn plan_scale(pr: &Project, plan: &Plan) -> f64 {
    let mut src = plan.key;
    if let Some(parent) = pr.el(plan.key).and_then(|e| ref_id(pr, e, "parent")) {
        src = parent;
    }
    if let Some(sc) = pr.el(src).and_then(|e| e.get("graphics")).and_then(|g| g.get("scale")).and_then(|x| x.as_f64()) {
        return sc;
    }
    let units = crate::styles::weights::project_units(pr);
    if crate::styles::weights::imperial(&units) {
        96.0
    } else {
        100.0
    }
}

/// A grid's bubble at an end, `out` the way away from the grid: a circle through the end, from
/// there the way the clock goes, laid out in the picking drawing's pixels where it has them.
fn bubble(plan: &Plan, touch: [f64; 2], out: [f64; 2], scale: f64) -> Vec<[f64; 2]> {
    let r = BUBBLE * scale;
    // round from its east the way the clock goes
    let a0 = 0.0;
    let angle = |k: usize| a0 - std::f64::consts::TAU * k as f64 / BUBBLE_CHORDS as f64;
    match plan.frame {
        Some(at) => {
            let rp = r * PX_SCALE;
            let t = to_px(touch, at);
            // y runs down the drawing
            let c = [(t[0] + out[0] * rp) as f32 as f64, (t[1] - out[1] * rp) as f32 as f64];
            (0..BUBBLE_CHORDS)
                .map(|k| {
                    let a = angle(k);
                    from_px([(c[0] + rp * a.cos()) as f32 as f64, (c[1] - rp * a.sin()) as f32 as f64], at)
                })
                .collect()
        }
        None => {
            let c = add(touch, mul(out, r));
            (0..BUBBLE_CHORDS)
                .map(|k| {
                    let a = angle(k);
                    [c[0] + r * a.cos(), c[1] + r * a.sin()]
                })
                .collect()
        }
    }
}

/// Whether an annotation element is drawn in a plan: in it, or (a dependent view) in its parent.
fn annotation_in(pr: &Project, plan: &Plan, e: &Value) -> bool {
    let Some(v) = ref_id(pr, e, "view") else { return false };
    if v == plan.key {
        return true;
    }
    pr.el(plan.key).and_then(|p| ref_id(pr, p, "parent")) == Some(v)
}

/// A detail line's straight segments (a polyline's, not its arcs), a filled region's sketch lines
/// where it has a line style.
fn detail_lines(pr: &Project, plan: &Plan, id: u64) -> Vec<Line> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    if !annotation_in(pr, plan, e) {
        return Vec::new();
    }
    match cat(e) {
        "line" => {
            if e.get("arcs").map(|a| !a.is_null()).unwrap_or(false) {
                return Vec::new();
            }
            if let (Some(a), Some(b)) = (pt_of(e, "start"), pt_of(e, "end")) {
                let arc = f_of(e, "arc").unwrap_or(0.0);
                if arc != 0.0 {
                    return vec![Line::open(arc_points(a, b, arc)).exact()];
                }
                return vec![Line::open(vec![a, b]).exact()];
            }
            match pts_of(e, "points") {
                Some(p) if p.len() >= 2 => {
                    let closed = e.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
                    vec![if closed { Line::ring(p) } else { Line::open(p) }.exact()]
                }
                _ => Vec::new(),
            }
        }
        _ => {
            if e.get("line_style").map(|l| l.is_null()).unwrap_or(false) {
                return Vec::new();
            }
            let Some(a) = e.get("sketch").and_then(|s| s.as_arr()) else { return Vec::new() };
            a.iter()
                .filter_map(|l| {
                    if l.get("arc").and_then(|a| a.as_f64()).map(|a| a != 0.0).unwrap_or(false) {
                        return None;
                    }
                    Some(Line::open(vec![pt_of(l, "start")?, pt_of(l, "end")?]).exact())
                })
                .collect()
        }
    }
}

/// An arc of a detail line from `a` to `b` turning `deg` counter-clockwise, in chords no further
/// than a quarter of a millimetre from it and of no more than 5°.
fn arc_points(a: [f64; 2], b: [f64; 2], deg: f64) -> Vec<[f64; 2]> {
    let Some((c, r)) = super::super::model::arc_circle(a, b, deg) else { return vec![a, b] };
    let t = deg.abs().to_radians();
    let by_flat = if r > 0.25 { (t / (2.0 * (1.0 - 0.25 / r).acos())).ceil() } else { 1.0 };
    let n = by_flat.max((deg.abs() / 5.0).ceil()).max(1.0) as usize;
    let a0 = (a[1] - c[1]).atan2(a[0] - c[0]);
    let sweep = deg.to_radians();
    let mut out: Vec<[f64; 2]> = (0..=n)
        .map(|k| {
            let ang = a0 + (sweep / n as f64) * k as f64;
            [c[0] + r * ang.cos(), c[1] + r * ang.sin()]
        })
        .collect();
    out[0] = a;
    out[n] = b;
    out
}

/// A door or a window of a family in a straight wall, where the plan cuts its opening.
fn family_door_lines(pr: &Project, plan: &Plan, e: &Value, w: &Wall) -> Vec<Line> {
    if w.loc.is_arc() {
        return Vec::new();
    }
    let sill = f_of(e, "sill").unwrap_or(0.0);
    let lo = w.base + sill;
    let z = plan.cut - lo;
    let height = super::super::tags::fields::family_number(pr, e, "Height").unwrap_or(2100.0);
    if !(0.0 <= z && z < height) {
        return Vec::new();
    }
    let offset = f_of(e, "offset").unwrap_or(0.0);
    let u = normalize(sub(w.loc.end, w.loc.start));
    let n = perp(u);
    let co = dot(sub(w.centre.start, w.loc.start), n);
    let hand = if e.get("flip_hand").and_then(|f| f.as_bool()).unwrap_or(false) { -1.0 } else { 1.0 };
    let facing = if e.get("flip_facing").and_then(|f| f.as_bool()).unwrap_or(false) { -1.0 } else { 1.0 };
    let middle = add(add(w.loc.start, mul(u, offset)), mul(n, co));
    let place = |x: f64, y: f64| -> [f64; 2] { add(add(middle, mul(u, hand * x)), mul(n, facing * y)) };
    let half = w.t / 2.0;
    let at = |s: f64, d: f64| -> [f64; 2] { add(add(w.loc.start, mul(u, s)), mul(n, co + d)) };
    let jamb = |width: f64| -> Vec<Line> {
        let (s0, s1) = (offset - width / 2.0, offset + width / 2.0);
        vec![Line::open(vec![at(s0, -half), at(s0, half)]), Line::open(vec![at(s1, -half), at(s1, half)])]
    };
    super::family::family_opening_lines(pr, e, w.t, z, &place, &jamb, hand * facing < 0.0).unwrap_or_default()
}
