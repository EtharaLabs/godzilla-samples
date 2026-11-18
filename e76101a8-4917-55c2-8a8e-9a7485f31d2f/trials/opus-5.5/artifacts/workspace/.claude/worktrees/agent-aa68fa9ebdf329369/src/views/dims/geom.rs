//! What a dimension measures to, in plan: a wall's centre line, faces and ends (its faces meeting
//! the walls joined to it in mitred caps, or stopping at the face of the wall it ends on), a
//! door's or window's centre and jambs, a grid's line, a detail line and its ends, a round
//! column's edge.

use super::super::common::*;
use super::super::model as vm;
use crate::json::Value;
use crate::project::Project;

pub type P = [f64; 2];

/// Ends of walls this close are joined.
pub const JOIN_GAP: f64 = 1.0;
/// An end this far past the face of the wall it ends on still ends on it.
pub const T_SLACK: f64 = 1.0;
/// Lines whose directions' cross product is this small are parallel.
pub const PARALLEL: f64 = 1e-3;
/// A point this near a line (or an end) picks it.
pub const PICK: f64 = 100.0;

// ---------------------------------------------------------------- vectors

pub fn add(a: P, b: P) -> P {
    [a[0] + b[0], a[1] + b[1]]
}
pub fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
pub fn mul(a: P, k: f64) -> P {
    [a[0] * k, a[1] * k]
}
pub fn dot(a: P, b: P) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
pub fn cross(a: P, b: P) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
pub fn norm(a: P) -> f64 {
    (a[0] * a[0] + a[1] * a[1]).sqrt()
}
pub fn dist(a: P, b: P) -> f64 {
    norm(sub(a, b))
}
/// `a` made a unit long, as the original normalizes: times the reciprocal of its length.
pub fn unit(a: P) -> P {
    let l = norm(a);
    if l == 0.0 {
        [0.0, 0.0]
    } else {
        let k = 1.0 / l;
        [a[0] * k, a[1] * k]
    }
}
/// The direction a quarter turn counter-clockwise from `d`.
pub fn left_of(d: P) -> P {
    [-d[1], d[0]]
}
pub fn mid(a: P, b: P) -> P {
    [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]
}

/// The distance from `p` to the segment `a`–`b`.
pub fn seg_dist(p: P, a: P, b: P) -> f64 {
    let d = sub(b, a);
    let l2 = dot(d, d);
    if l2 == 0.0 {
        return dist(p, a);
    }
    let t = (dot(sub(p, a), d) / l2).clamp(0.0, 1.0);
    dist(p, add(a, mul(d, t)))
}

/// Where the lines through `a` along `da` and through `b` along `db` cross (None: parallel).
pub fn line_meet(a: P, da: P, b: P, db: P) -> Option<P> {
    let den = cross(da, db);
    if den.abs() < 1e-12 * norm(da) * norm(db) || den == 0.0 {
        return None;
    }
    let t = cross(sub(b, a), db) / den;
    Some(add(a, mul(da, t)))
}

/// An angle in radians wrapped into [0, 2π).
pub fn wrap(a: f64) -> f64 {
    let t = std::f64::consts::TAU;
    let mut x = a % t;
    if x < 0.0 {
        x += t;
    }
    if x >= t {
        x -= t;
    }
    x
}

// ---------------------------------------------------------------- curves

/// A line in plan as a face or a centre line is: straight through a point along a direction, or a
/// circle (an arc's).
#[derive(Clone, Copy, Debug)]
pub enum Carrier {
    Line { p: P, d: P },
    Circle { c: P, r: f64 },
}

/// The point where two carriers meet nearest `near`; None where they don't.
pub fn meet(a: Carrier, b: Carrier, near: P) -> Option<P> {
    match (a, b) {
        (Carrier::Line { p, d }, Carrier::Line { p: q, d: e }) => line_meet(p, d, q, e),
        (Carrier::Line { p, d }, Carrier::Circle { c, r }) | (Carrier::Circle { c, r }, Carrier::Line { p, d }) => {
            let u = unit(d);
            let f = sub(p, c);
            let b2 = dot(f, u);
            let cc = dot(f, f) - r * r;
            let disc = b2 * b2 - cc;
            if disc < 0.0 {
                return None;
            }
            let s = disc.sqrt();
            let p1 = add(p, mul(u, -b2 + s));
            let p2 = add(p, mul(u, -b2 - s));
            Some(if dist(p1, near) <= dist(p2, near) { p1 } else { p2 })
        }
        (Carrier::Circle { c: c1, r: r1 }, Carrier::Circle { c: c2, r: r2 }) => {
            let d = dist(c1, c2);
            if d == 0.0 || d > r1 + r2 || d < (r1 - r2).abs() {
                return None;
            }
            let a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
            let h = (r1 * r1 - a * a).max(0.0).sqrt();
            let u = unit(sub(c2, c1));
            let m = add(c1, mul(u, a));
            let n = left_of(u);
            let p1 = add(m, mul(n, h));
            let p2 = add(m, mul(n, -h));
            Some(if dist(p1, near) <= dist(p2, near) { p1 } else { p2 })
        }
    }
}

/// The foot of `p` on a carrier.
pub fn foot(c: Carrier, p: P) -> P {
    match c {
        Carrier::Line { p: q, d } => {
            let u = unit(d);
            add(q, mul(u, dot(sub(p, q), u)))
        }
        Carrier::Circle { c, r } => {
            let v = sub(p, c);
            let l = norm(v);
            if l == 0.0 {
                add(c, [r, 0.0])
            } else {
                add(c, mul(v, r / l))
            }
        }
    }
}

// ---------------------------------------------------------------- walls

/// What a wall is in plan before it is joined.
#[derive(Clone, Debug)]
pub struct WallBase {
    pub id: u64,
    pub guid: String,
    /// Its location line (`start`, `end`, `arc`).
    pub loc: vm::WallLine,
    /// Its centre line, ending where the location line does.
    pub cl: vm::WallLine,
    pub t: f64,
    pub base: f64,
    pub top: f64,
}

impl WallBase {
    pub fn straight(&self) -> bool {
        !self.cl.is_arc()
    }
    /// The unit direction from its start to its end (a straight wall's).
    pub fn dir(&self) -> P {
        unit(sub(self.cl.end, self.cl.start))
    }
    /// The circle of a curved wall's centre line, with its start angle and sweep in radians.
    pub fn circle(&self) -> Option<(P, f64, f64, f64)> {
        let (c, r) = self.cl.circle()?;
        let a0 = (self.cl.start[1] - c[1]).atan2(self.cl.start[0] - c[0]);
        Some((c, r, a0, self.cl.arc.to_radians()))
    }
    /// The way it runs at an end, start to end.
    pub fn tangent(&self, at_end: bool) -> P {
        match self.circle() {
            None => self.dir(),
            Some((c, _, _, sweep)) => {
                let p = if at_end { self.cl.end } else { self.cl.start };
                let v = unit(sub(p, c));
                if sweep > 0.0 {
                    left_of(v)
                } else {
                    mul(left_of(v), -1.0)
                }
            }
        }
    }
    /// The line `off` to the left of its centre line (+t/2: its left face).
    pub fn carrier(&self, off: f64) -> Carrier {
        match self.circle() {
            None => {
                let d = self.dir();
                Carrier::Line { p: add(self.cl.start, mul(left_of(d), off)), d }
            }
            Some((c, r, _, sweep)) => {
                // left of a counter-clockwise arc is toward its centre
                let rr = if sweep > 0.0 { r - off } else { r + off };
                Carrier::Circle { c, r: rr }
            }
        }
    }
    pub fn left(&self) -> Carrier {
        self.carrier(self.t / 2.0)
    }
    pub fn right(&self) -> Carrier {
        self.carrier(-self.t / 2.0)
    }
    /// How far `p` lies to the left of its centre line, and how far along it (a straight wall's from
    /// its start; a curved one's, the angle swept from its start, as a fraction of its sweep).
    pub fn offset_along(&self, p: P) -> (f64, f64) {
        match self.circle() {
            None => {
                let d = self.dir();
                let v = sub(p, self.cl.start);
                let len = dist(self.cl.start, self.cl.end);
                (dot(v, left_of(d)), if len > 0.0 { dot(v, d) / len } else { 0.0 })
            }
            Some((c, r, a0, sweep)) => {
                let v = sub(p, c);
                let l = norm(v);
                let off = if sweep > 0.0 { r - l } else { l - r };
                let a = v[1].atan2(v[0]);
                let f = if sweep > 0.0 { wrap(a - a0) / sweep } else { wrap(a0 - a) / -sweep };
                (off, f)
            }
        }
    }
    fn overlaps(&self, o: &WallBase) -> bool {
        self.base < o.top && o.base < self.top
    }
}

/// A wall's plan geometry, joined: its faces' ends as the joins make them, and its ends' lines.
#[derive(Clone, Debug)]
pub struct Wall {
    pub b: WallBase,
    /// Its left face's ends, at its start and its end.
    pub left: (P, P),
    pub right: (P, P),
    /// Its start's and its end's lines, each from its right face to its left.
    pub sface: (P, P),
    pub eface: (P, P),
    /// How far along its centre line (a straight one's, from its start) its start's and its end's
    /// lines stand: its faces and centre line, as lines, run between them.
    pub span: (f64, f64),
}

impl Wall {
    pub fn id(&self) -> u64 {
        self.b.id
    }
    /// A straight wall's line `off` left of its centre line, from its start's line to its end's.
    pub fn full(&self, off: f64) -> (P, P) {
        let d = self.b.dir();
        let n = left_of(d);
        let c0 = self.b.cl.start;
        let at = |s: f64| add(add(c0, mul(d, s)), mul(n, off));
        (at(self.span.0), at(self.span.1))
    }
    /// The corners of its outline in plan.
    pub fn outline(&self) -> Vec<P> {
        let mut v = vec![self.right.0, self.right.1, self.eface.0, self.eface.1, self.left.1, self.left.0, self.sface.1, self.sface.0];
        if !self.b.straight() {
            // the faces' arcs bulge past their ends
            let (c, _, a0, sweep) = self.b.circle().unwrap();
            for off in [self.b.t / 2.0, -self.b.t / 2.0] {
                if let Carrier::Circle { r, .. } = self.b.carrier(off) {
                    for i in 0..=32 {
                        let a = a0 + sweep * i as f64 / 32.0;
                        v.push([c[0] + r * a.cos(), c[1] + r * a.sin()]);
                    }
                }
            }
        }
        v
    }
}

pub fn wall_base(pr: &Project, id: u64) -> Option<WallBase> {
    let e = pr.el(id)?;
    if cat(e) != "wall" {
        return None;
    }
    let loc = vm::location_line(e);
    let mut cl = vm::centre_line(pr, e);
    if !cl.is_arc() {
        // a straight wall's centre line runs its length from its start, as the original lays it
        let v = sub(loc.end, loc.start);
        let d = unit(v);
        let off = vm::centre_offset(pr, e);
        cl.start = add(loc.start, mul(left_of(d), off));
        cl.end = add(cl.start, mul(d, norm(v)));
    }
    let (base, top) = vm::base_top(pr, e);
    Some(WallBase {
        id,
        guid: s_of(e, "guid").unwrap_or("").to_string(),
        loc,
        cl,
        t: vm::wall_thickness(pr, e),
        base,
        top,
    })
}

/// Every wall's plan geometry before joins, by id.
pub fn wall_bases(pr: &Project) -> Vec<WallBase> {
    pr.ids_of("wall").into_iter().filter_map(|id| wall_base(pr, id)).collect()
}

/// A wall's end at a joint: which wall, whether its end (else its start), the way out of the joint
/// along it.
struct AtJoint {
    i: usize,
    at_end: bool,
    u: P,
    /// Whether it runs through the node (a wall the node lies within), rather than ending there.
    through: bool,
    /// Where the node is, for a curved wall running through it (its faces as their tangents there).
    near: Option<P>,
}

impl AtJoint {
    /// Its face on the left of the way out (its left face at its start, its right one at its end);
    /// a curved wall's as the line it runs along there.
    fn ccw_face(&self, ws: &[WallBase]) -> Carrier {
        let off = if self.at_end { -ws[self.i].t / 2.0 } else { ws[self.i].t / 2.0 };
        self.face(ws, off)
    }
    fn cw_face(&self, ws: &[WallBase]) -> Carrier {
        let off = if self.at_end { ws[self.i].t / 2.0 } else { -ws[self.i].t / 2.0 };
        self.face(ws, off)
    }
    fn face(&self, ws: &[WallBase], off: f64) -> Carrier {
        let w = &ws[self.i];
        match (self.near, w.circle()) {
            (Some(q), Some((c, _, _, _))) => match w.carrier(off) {
                Carrier::Circle { r, .. } => {
                    let v = unit(sub(q, c));
                    Carrier::Line { p: add(c, mul(v, r)), d: left_of(v) }
                }
                x => x,
            },
            _ => face_line_at(w, self.at_end, off),
        }
    }
}

/// A wall's face `off` left of its centre line as a line where it ends: a straight wall's face, a
/// curved one's tangent at that end.
fn face_line_at(w: &WallBase, at_end: bool, off: f64) -> Carrier {
    if w.straight() {
        return w.carrier(off);
    }
    Carrier::Line { p: foot_at_end(w, at_end, off), d: w.tangent(at_end) }
}

/// A wall's face corners at one of its ends, (left, right), as the joins there make them.
fn end_corners(ws: &[WallBase], i: usize, at_end: bool) -> (P, P) {
    let w = &ws[i];
    let p = if at_end { w.loc.end } else { w.loc.start };
    let cp = if at_end { w.cl.end } else { w.cl.start };
    let free = || (foot_at_end(w, at_end, w.t / 2.0), foot_at_end(w, at_end, -w.t / 2.0));
    // a curved wall's faces end square across it, whatever it is joined to
    if !w.straight() {
        return free();
    }
    let tan = w.tangent(at_end);
    let u_self = if at_end { mul(tan, -1.0) } else { tan };
    // walls ending here
    let mut at: Vec<AtJoint> = vec![AtJoint { i, at_end, u: u_self, through: false, near: None }];
    for (j, o) in ws.iter().enumerate() {
        if j == i || !w.overlaps(o) {
            continue;
        }
        for oe in [false, true] {
            let q = if oe { o.loc.end } else { o.loc.start };
            if dist(p, q) <= JOIN_GAP {
                let t = o.tangent(oe);
                at.push(AtJoint { i: j, at_end: oe, u: if oe { mul(t, -1.0) } else { t }, through: false, near: None });
            }
        }
    }
    // where walls meet within another, that one runs through the node both ways
    if at.len() > 1 {
        let members: Vec<usize> = at.iter().map(|a| a.i).collect();
        for (j, o) in ws.iter().enumerate() {
            if members.contains(&j) || !w.overlaps(o) {
                continue;
            }
            let (off, along) = o.offset_along(p);
            let at_mm = along * o.cl.length();
            if !(at_mm > JOIN_GAP && at_mm < o.cl.length() - JOIN_GAP) || off.abs() > o.t / 2.0 + 1e-9 {
                continue;
            }
            // the way it runs there
            let (d, near) = match o.circle() {
                None => (o.dir(), None),
                Some((c, _, _, sweep)) => {
                    let v = unit(sub(p, c));
                    (if sweep > 0.0 { left_of(v) } else { mul(left_of(v), -1.0) }, Some(p))
                }
            };
            at.push(AtJoint { i: j, at_end: false, u: d, through: true, near });
            at.push(AtJoint { i: j, at_end: true, u: mul(d, -1.0), through: true, near });
        }
    }
    let mut base = [foot_at_end(w, at_end, w.t / 2.0), foot_at_end(w, at_end, -w.t / 2.0)];
    let mut mitred = [false, false];
    if at.len() > 1 {
        let ang = |u: P| u[1].atan2(u[0]);
        let me = ang(u_self);
        // the next way out counter-clockwise, and clockwise
        let mut ccw: Option<(f64, usize)> = None;
        let mut cw: Option<(f64, usize)> = None;
        for (k, a) in at.iter().enumerate().skip(1) {
            let d = wrap(ang(a.u) - me);
            let dc = wrap(me - ang(a.u));
            if d > 1e-12 && ccw.map_or(true, |(x, _)| d < x) {
                ccw = Some((d, k));
            }
            if dc > 1e-12 && cw.map_or(true, |(x, _)| dc < x) {
                cw = Some((dc, k));
            }
        }
        let mine = &at[0];
        // my face on the left of my way out meets the next one's face on the right of its way
        let left_of_u = mine.ccw_face(ws);
        let right_of_u = mine.cw_face(ws);
        // a corner so sharp the mitre would reach further along the wall than the thicker of
        // the two is thick is squared off
        let thickest = at.iter().map(|a| ws[a.i].t).fold(0.0, f64::max);
        let near = |x: P, _k: usize| dot(sub(x, cp), u_self).abs() <= thickest + 1e-9;
        // a face that is the wall's location line keeps its end at the joint rather than
        // stopping short of it
        let keeps = |face: Carrier, x: P, k: usize| at[k].through || dist(foot(face, cp), p) > 1e-6 || dot(sub(x, p), u_self) <= 1e-9;
        let m1 = ccw.and_then(|(_, k)| meet(left_of_u, at[k].cw_face(ws), cp).filter(|x| near(*x, k) && keeps(left_of_u, *x, k)));
        let m2 = cw.and_then(|(_, k)| meet(right_of_u, at[k].ccw_face(ws), cp).filter(|x| near(*x, k) && keeps(right_of_u, *x, k)));
        let c1 = m1.unwrap_or_else(|| foot(left_of_u, cp));
        let c2 = m2.unwrap_or_else(|| foot(right_of_u, cp));
        // at the start, the left of the way out is the left face; at the end, the right
        base = if at_end { [c2, c1] } else { [c1, c2] };
        mitred = if at_end { [m2.is_some(), m1.is_some()] } else { [m1.is_some(), m2.is_some()] };
    }
    let joined: Vec<usize> = at.iter().map(|a| a.i).collect();
    // an end joined to others is done: a wall it lies within ran through the node
    if at.len() > 1 {
        return (base[0], base[1]);
    }
    // ending on another wall (its end within it, or just past the face it ends on): each face
    // stops at that face, but one whose end is past the far face, or that a join mitred where
    // it isn't within the other wall, which stays; none does where one would reach further
    // along it than the thicker of the two is thick
    for (j, o) in ws.iter().enumerate() {
        if joined.contains(&j) || !w.overlaps(o) {
            continue;
        }
        let (po, along) = o.offset_along(p);
        // more than the joining gap from either of its ends
        let olen = o.cl.length();
        let at_mm = along * olen;
        if !(at_mm > JOIN_GAP && at_mm < olen - JOIN_GAP) {
            continue;
        }
        let otan = match o.circle() {
            None => o.dir(),
            Some((c, _, _, sweep)) => {
                let v = unit(sub(p, c));
                if sweep > 0.0 {
                    left_of(v)
                } else {
                    mul(left_of(v), -1.0)
                }
            }
        };
        if cross(unit(u_self), otan).abs() < PARALLEL {
            continue;
        }
        // which side of it this wall runs to
        let side = if dot(u_self, left_of(otan)) > 0.0 { 1.0 } else { -1.0 };
        let near = o.t / 2.0 + T_SLACK;
        let sp = po * side;
        if sp < -o.t / 2.0 || sp > near {
            continue;
        }
        // the face it ends on (a curved wall's as its tangent where this one meets it)
        let face = match o.carrier(side * o.t / 2.0) {
            Carrier::Circle { c, r } => {
                let v = unit(sub(p, c));
                Carrier::Line { p: add(c, mul(v, r)), d: left_of(v) }
            }
            x => x,
        };
        let reach = w.t.max(o.t);
        let free = [foot_at_end(w, at_end, w.t / 2.0), foot_at_end(w, at_end, -w.t / 2.0)];
        let inside = |x: P| {
            let sx = o.offset_along(x).0 * side;
            sx >= -o.t / 2.0 && sx <= near
        };
        let mut corners = base;
        let mut ok = true;
        for (k, off) in [w.t / 2.0, -w.t / 2.0].iter().enumerate() {
            let sf = o.offset_along(free[k]).0 * side;
            if mitred[k] && sf < -o.t / 2.0 {
                // its end square across it is past the far face: a mitre within the other
                // wall is undone
                if inside(base[k]) {
                    corners[k] = free[k];
                }
                continue;
            }
            if mitred[k] && !inside(base[k]) {
                continue;
            }
            match meet(w.carrier(*off), face, cp) {
                Some(x) if dot(sub(x, cp), u_self).abs() <= reach => corners[k] = x,
                // a face past the face it ends on must stop at it; one within the other wall
                // may stay as it is
                _ => {
                    if sf > near {
                        ok = false;
                    }
                }
            }
        }
        if !ok {
            continue;
        }
        return (corners[0], corners[1]);
    }
    (base[0], base[1])
}

/// A face's end where the wall's end is square across it: `off` left of the centre line's end.
fn foot_at_end(w: &WallBase, at_end: bool, off: f64) -> P {
    let cp = if at_end { w.cl.end } else { w.cl.start };
    match w.circle() {
        None => add(cp, mul(left_of(w.dir()), off)),
        Some((c, _, _, _)) => {
            let car = w.carrier(off);
            let v = unit(sub(cp, c));
            match car {
                Carrier::Circle { r, .. } => add(c, mul(v, r)),
                _ => cp,
            }
        }
    }
}

/// A wall joined to the others: its faces' ends and its ends' lines.
pub fn join(ws: &[WallBase], i: usize) -> Wall {
    let b = ws[i].clone();
    let (ls, rs) = end_corners(ws, i, false);
    let (le, re) = end_corners(ws, i, true);
    let (sface, eface, span) = if b.straight() {
        let d = b.dir();
        let n = left_of(d);
        let c0 = b.cl.start;
        let pr = |x: P| dot(sub(x, c0), d);
        let s0 = pr(b.loc.start).min(pr(ls)).min(pr(rs));
        let s1 = pr(b.loc.end).max(pr(le)).max(pr(re));
        let at = |s: f64, off: f64| add(add(c0, mul(d, s)), mul(n, off));
        ((at(s0, -b.t / 2.0), at(s0, b.t / 2.0)), (at(s1, -b.t / 2.0), at(s1, b.t / 2.0)), (s0, s1))
    } else {
        (
            (foot_at_end(&b, false, -b.t / 2.0), foot_at_end(&b, false, b.t / 2.0)),
            (foot_at_end(&b, true, -b.t / 2.0), foot_at_end(&b, true, b.t / 2.0)),
            (0.0, 0.0),
        )
    };
    Wall { b, left: (ls, le), right: (rs, re), sface, eface, span }
}

/// Every wall of the project joined, by id.
pub fn walls(pr: &Project) -> Vec<Wall> {
    let ws = wall_bases(pr);
    (0..ws.len()).map(|i| join(&ws, i)).collect()
}

/// One wall joined to the others.
pub fn wall(pr: &Project, id: u64) -> Option<Wall> {
    let ws = wall_bases(pr);
    let i = ws.iter().position(|w| w.id == id)?;
    Some(join(&ws, i))
}

// ---------------------------------------------------------------- doors and windows

/// A door's or window's width, as its type (or its family's type) gives it.
pub fn opening_width(pr: &Project, e: &Value) -> f64 {
    let c = cat(e);
    if let Some(fam) = lib_ref_name(pr, e, "family") {
        let tname = lib_ref_name(pr, e, "type").unwrap_or_default();
        let tname = tname.strip_prefix(&format!("{}: ", fam)).unwrap_or(&tname).to_string();
        if let Some(f) = pr.section("families").and_then(|m| m.get(&fam)) {
            if let Some(w) = f.get("types").and_then(|t| t.get(&tname)).and_then(|t| f_of(t, "Width")) {
                return w;
            }
            if let Some(ps) = f.get("parameters").and_then(|p| p.as_arr()) {
                for p in ps {
                    if s_of(p, "name") == Some("Width") {
                        if let Some(w) = f_of(p, "value") {
                            return w;
                        }
                    }
                }
            }
        }
        return 900.0;
    }
    vm::type_entry(pr, c, e).and_then(|t| f_of(t, "width")).unwrap_or(900.0)
}

/// A door's or window's lines across its wall: (centre, jamb toward the wall's start, jamb toward
/// its end), each from the wall's right face to its left; and its host's id.
pub fn opening_lines(pr: &Project, id: u64) -> Option<(u64, [(P, P); 3])> {
    let e = pr.el(id)?;
    let host = ref_id(pr, e, "host")?;
    let w = wall_base(pr, host)?;
    let off = f_of(e, "offset").unwrap_or(0.0);
    let width = opening_width(pr, e);
    let at = |o: f64| -> (P, P) {
        match w.circle() {
            None => {
                let d = w.dir();
                let n = left_of(d);
                let p = add(w.cl.start, mul(d, o));
                (add(p, mul(n, -w.t / 2.0)), add(p, mul(n, w.t / 2.0)))
            }
            Some((c, _, _, sweep)) => {
                let (_, rl) = w.loc.circle().unwrap_or((c, 1.0));
                let a0 = (w.loc.start[1] - c[1]).atan2(w.loc.start[0] - c[0]);
                let a = a0 + o / rl * sweep.signum();
                let v = [a.cos(), a.sin()];
                let r_of = |car: Carrier| match car {
                    Carrier::Circle { r, .. } => r,
                    _ => rl,
                };
                (add(c, mul(v, r_of(w.right()))), add(c, mul(v, r_of(w.left()))))
            }
        }
    };
    Some((host, [at(off), at(off - width / 2.0), at(off + width / 2.0)]))
}

// ---------------------------------------------------------------- detail lines

/// The shape of a detail line.
#[derive(Clone, Debug)]
pub enum LineShape {
    Line(P, P),
    /// An arc: its centre, radius, start angle and sweep (radians, counter-clockwise positive),
    /// its ends.
    Arc { c: P, r: f64, a0: f64, sweep: f64, start: P, end: P },
    Circle { c: P, r: f64 },
    Polyline(Vec<P>),
    Ellipse { start: P, end: P },
    Spline { start: P, end: P },
}

impl LineShape {
    /// What messages call it.
    pub fn word(&self) -> &'static str {
        match self {
            LineShape::Line(..) => "line",
            LineShape::Arc { .. } => "arc",
            LineShape::Circle { .. } => "circle",
            LineShape::Polyline(..) => "polyline",
            LineShape::Ellipse { .. } => "ellipse",
            LineShape::Spline { .. } => "spline",
        }
    }
    pub fn ends(&self) -> (P, P) {
        match self {
            LineShape::Line(a, b) => (*a, *b),
            LineShape::Arc { start, end, .. } => (*start, *end),
            LineShape::Circle { c, r } => {
                let p = [c[0] + r, c[1]];
                (p, p)
            }
            LineShape::Polyline(pts) => (pts[0], *pts.last().unwrap()),
            LineShape::Ellipse { start, end } => (*start, *end),
            LineShape::Spline { start, end } => (*start, *end),
        }
    }
    /// Points along it, for its extent.
    pub fn points(&self) -> Vec<P> {
        match self {
            LineShape::Line(a, b) => vec![*a, *b],
            LineShape::Arc { c, r, a0, sweep, .. } => (0..=32)
                .map(|i| {
                    let a = a0 + sweep * i as f64 / 32.0;
                    [c[0] + r * a.cos(), c[1] + r * a.sin()]
                })
                .collect(),
            LineShape::Circle { c, r } => (0..32)
                .map(|i| {
                    let a = std::f64::consts::TAU * i as f64 / 32.0;
                    [c[0] + r * a.cos(), c[1] + r * a.sin()]
                })
                .collect(),
            LineShape::Polyline(p) => p.clone(),
            LineShape::Ellipse { start, end } | LineShape::Spline { start, end } => vec![*start, *end],
        }
    }
}

/// A detail line's shape, from its fields.
pub fn line_shape(e: &Value) -> Option<LineShape> {
    if let (Some(a), Some(b)) = (pt_of(e, "start"), pt_of(e, "end")) {
        let arc = f_of(e, "arc").unwrap_or(0.0);
        if arc.abs() > 1e-12 {
            if let Some((c, r)) = vm::arc_circle(a, b, arc) {
                let a0 = (a[1] - c[1]).atan2(a[0] - c[0]);
                return Some(LineShape::Arc { c, r, a0, sweep: arc.to_radians(), start: a, end: b });
            }
        }
        return Some(LineShape::Line(a, b));
    }
    if let (Some(c), Some(r)) = (pt_of(e, "centre"), f_of(e, "radius")) {
        return Some(LineShape::Circle { c, r });
    }
    if let (Some(c), Some(rr)) = (pt_of(e, "centre"), pts_or_pair(e, "radii")) {
        let ang = f_of(e, "angle").unwrap_or(0.0).to_radians();
        let at = |t: f64| {
            let (x, y) = (rr[0] * t.cos(), rr[1] * t.sin());
            [c[0] + x * ang.cos() - y * ang.sin(), c[1] + x * ang.sin() + y * ang.cos()]
        };
        let (t0, t1) = match e.get("span").and_then(|s| s.as_arr()) {
            Some(s) if s.len() == 2 => (s[0].as_f64().unwrap_or(0.0).to_radians(), s[1].as_f64().unwrap_or(0.0).to_radians()),
            _ => (0.0, 0.0),
        };
        return Some(LineShape::Ellipse { start: at(t0), end: at(t1) });
    }
    if let Some(pts) = pts_of(e, "points") {
        if pts.is_empty() {
            return None;
        }
        let mut pts = pts;
        if e.get("closed").and_then(|c| c.as_bool()) == Some(true) {
            let f = pts[0];
            pts.push(f);
        }
        return Some(LineShape::Polyline(pts));
    }
    for k in ["control", "fit"] {
        if let Some(pts) = pts_of(e, k) {
            if !pts.is_empty() {
                return Some(LineShape::Spline { start: pts[0], end: *pts.last().unwrap() });
            }
        }
    }
    None
}

fn pts_or_pair(e: &Value, k: &str) -> Option<[f64; 2]> {
    let a = e.get(k)?.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

// ---------------------------------------------------------------- columns

/// A round column's (or structural column's, or footing's) centre and radius.
pub fn round_column(pr: &Project, e: &Value) -> Option<(P, f64)> {
    let key = match cat(e) {
        "column" => "column",
        "structuralcolumn" | "structural_column" => "structural_column",
        "footing" => "footing",
        _ => return None,
    };
    let t = vm::type_entry(pr, key, e)?;
    if t.get("round").and_then(|r| r.as_bool()) != Some(true) {
        return None;
    }
    let c = pt_of(e, "at")?;
    Some((c, f_of(t, "width").unwrap_or(400.0) / 2.0))
}

/// Whether the element is a column of any kind (for "isn't round").
pub fn is_column(c: &str) -> bool {
    matches!(c, "column" | "structuralcolumn" | "structural_column" | "footing")
}
