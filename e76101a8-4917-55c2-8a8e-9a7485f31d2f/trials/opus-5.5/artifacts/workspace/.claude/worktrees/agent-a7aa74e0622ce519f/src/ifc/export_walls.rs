//! Walls in plan: their location lines, faces, and the outline their joins give them
//! (mitred where walls share an end, stopped at the face of a wall one ends on, squared
//! where a corner is too sharp), arcs in short chords.

use super::geom::*;
use crate::json::Value;
use crate::project::Project;

/// Ends closer than this are one node, and a wall ends on another this far past its face.
pub const TOL: f64 = 1.0;

#[derive(Clone, Debug)]
pub struct Wall {
    pub id: u64,
    pub guid: String,
    pub level: String,
    pub start: V2,
    pub end: V2,
    /// Degrees it turns from start to end, counter-clockwise positive; 0 straight.
    pub arc: f64,
    pub thickness: f64,
    /// How far its left (exterior) and right faces stand from its location line.
    pub left: f64,
    pub right: f64,
    pub type_name: String,
    pub type_guid: String,
    pub location: String,
    /// The heights it spans (from the building's datum): walls join only where they share
    /// some of them.
    pub z0: f64,
    pub z1: f64,
}

/// The circle a curved wall's location line runs on.
#[derive(Clone, Copy, Debug)]
pub struct Arc {
    pub centre: V2,
    pub radius: f64,
    /// Angle of the start from the centre, and the sweep (radians, counter-clockwise positive).
    pub a0: f64,
    pub sweep: f64,
}

impl Wall {
    pub fn is_arc(&self) -> bool {
        self.arc.abs() > 1e-9
    }

    pub fn arc_geom(&self) -> Option<Arc> {
        if !self.is_arc() {
            return None;
        }
        let sweep = self.arc.to_radians();
        let chord = self.end - self.start;
        let c = chord.length();
        if c < 1e-9 {
            return None;
        }
        let radius = c / (2.0 * (sweep.abs() / 2.0).sin());
        // the centre stands off the chord's midpoint, to its left for a counter-clockwise
        // sweep under a half turn (and to its right past one)
        let d = chord.normalize();
        let h = (c / 2.0) / (sweep / 2.0).tan();
        let centre = (self.start + self.end) * 0.5 + d.perp() * h;
        let a0 = (self.start - centre).angle();
        Some(Arc { centre, radius, a0, sweep })
    }

    /// The tangent of an arc at an angle from its centre, the way it runs.
    fn tangent_at(sweep: f64, ang: f64) -> V2 {
        if sweep > 0.0 {
            v2(-ang.sin(), ang.cos())
        } else {
            v2(ang.sin(), -ang.cos())
        }
    }

    /// The direction of the location line at the start.
    pub fn start_dir(&self) -> V2 {
        match self.arc_geom() {
            Some(a) => Self::tangent_at(a.sweep, a.a0),
            None => (self.end - self.start).normalize(),
        }
    }

    /// The direction of the location line at the end.
    pub fn end_dir(&self) -> V2 {
        match self.arc_geom() {
            Some(a) => Self::tangent_at(a.sweep, a.a0 + a.sweep),
            None => (self.end - self.start).normalize(),
        }
    }

    /// The length of its location line.
    pub fn length(&self) -> f64 {
        match self.arc_geom() {
            Some(a) => a.radius * a.sweep.abs(),
            None => (self.end - self.start).length(),
        }
    }

    /// Chords a curve of this radius is drawn in over this sweep: none farther than 1 from
    /// the curve, and none turning more than 5 degrees (the turn taken as its length over its
    /// radius).
    pub fn segments(radius: f64, sweep: f64) -> usize {
        let r = radius.abs();
        let turn = (r * sweep.abs()) / r;
        let by_turn = (turn / 5f64.to_radians()).ceil();
        let by_sag = if r <= 0.5 { 1.0 } else { (sweep.abs() / (2.0 * (1.0 - 1.0 / r).acos())).ceil() };
        let n = by_sag.max(by_turn);
        if n.is_finite() && n >= 1.0 {
            n as usize
        } else {
            1
        }
    }

    /// Points along a line offset `off` to the left of the location line, start to end
    /// (both ends included).
    pub fn offset_points(&self, off: f64) -> Vec<V2> {
        match self.arc_geom() {
            None => {
                // along the line from its start: start + d * t, offset to the left
                let d = (self.end - self.start).normalize();
                let len = (self.end - self.start).length();
                let n = d.perp();
                if off == 0.0 {
                    vec![self.start + d * 0.0, self.start + d * len]
                } else {
                    vec![self.start + n * off, self.start + d * len + n * off]
                }
            }
            Some(a) => {
                let k = Self::segments(a.radius, a.sweep);
                // to the left of a counter-clockwise arc is toward its centre
                let r = if a.sweep > 0.0 { a.radius - off } else { a.radius + off };
                let mut pts = Vec::with_capacity(k + 1);
                for i in 0..=k {
                    let ang = a.a0 + a.sweep * (i as f64) / (k as f64);
                    pts.push(a.centre + v2(ang.cos(), ang.sin()) * r);
                }
                pts
            }
        }
    }
}

fn s(v: Option<&Value>) -> String {
    v.and_then(|x| x.as_str()).unwrap_or("").to_string()
}
fn f(v: Option<&Value>, d: f64) -> f64 {
    v.and_then(|x| x.as_f64()).unwrap_or(d)
}
pub fn pt(v: Option<&Value>) -> V2 {
    match v.and_then(|x| x.as_arr()) {
        Some(a) if a.len() >= 2 => v2(a[0].as_f64().unwrap_or(0.0), a[1].as_f64().unwrap_or(0.0)),
        _ => v2(0.0, 0.0),
    }
}

/// A library entry's name by GUID.
pub fn lib_name(pr: &Project, g: &str) -> String {
    pr.lib_name(g).unwrap_or_default()
}

/// The `types` section's entry for a category and a type GUID.
pub fn type_data<'a>(pr: &'a Project, key: &str, g: &str) -> Option<&'a Value> {
    let name = pr.lib_name(g)?;
    pr.get("types")?.get(key)?.get(&name)
}

pub fn wall_of(pr: &Project, id: u64, e: &Value) -> Wall {
    let tg = s(e.get("type"));
    let type_name = lib_name(pr, &tg);
    let td = type_data(pr, "wall", &tg);
    let thickness = td.map(|t| f(t.get("thickness"), 200.0)).unwrap_or(200.0);
    let location = e.get("location").and_then(|x| x.as_str()).unwrap_or("centre").to_string();
    // the layers from the exterior in: its core runs from the first structure layer to the last
    let mut ext = 0.0;
    let mut core = thickness;
    if let Some(ls) = td.and_then(|t| t.get("layers")).and_then(|l| l.as_arr()) {
        let th: Vec<f64> = ls.iter().map(|l| f(l.get("thickness"), 0.0)).collect();
        let st: Vec<bool> = ls.iter().map(|l| l.get("function").and_then(|x| x.as_str()) == Some("structure")).collect();
        if let (Some(a), Some(b)) = (st.iter().position(|x| *x), st.iter().rposition(|x| *x)) {
            ext = th[..a].iter().sum();
            core = th[a..=b].iter().sum();
        }
    }
    let d = match location.as_str() {
        "exterior-finish" => 0.0,
        "interior-finish" => thickness,
        "exterior-core" => ext,
        "interior-core" => ext + core,
        "core-centre" => ext + core / 2.0,
        _ => thickness / 2.0,
    };
    Wall {
        id,
        guid: s(e.get("guid")),
        level: s(e.get("level")),
        start: pt(e.get("start")),
        end: pt(e.get("end")),
        arc: f(e.get("arc"), 0.0),
        thickness,
        left: d,
        right: thickness - d,
        type_name,
        type_guid: tg,
        location,
        z0: f64::NEG_INFINITY,
        z1: f64::INFINITY,
    }
}

/// One end of a wall seen from the node it is at: the direction into the wall and its faces
/// to the left and right of that direction.
#[derive(Clone, Copy, Debug)]
struct End {
    wall: usize,
    p: V2,
    u: V2,
    /// Where its left and right faces end (on a curved wall, its offset arcs' ends).
    lp: V2,
    rp: V2,
}

impl End {
    fn left_line(&self) -> (V2, V2) {
        (self.lp, self.u)
    }
    fn right_line(&self) -> (V2, V2) {
        (self.rp, self.u)
    }
}

fn end_of(w: &Wall, i: usize, at_end: bool) -> End {
    let (u, oleft, oright, p) = if !at_end { (w.start_dir(), w.left, w.right, w.start) } else { (-w.end_dir(), w.right, w.left, w.end) };
    let (lp, rp) = if w.is_arc() {
        let l = w.offset_points(w.left);
        let r = w.offset_points(-w.right);
        if !at_end {
            (l[0], r[0])
        } else {
            (*r.last().unwrap(), *l.last().unwrap())
        }
    } else {
        (p + u.perp() * oleft, p - u.perp() * oright)
    };
    End { wall: i, p, u, lp, rp }
}

/// Where an end stands in another wall (clear of its ends): this one's faces cut at that
/// wall's face on its side.
fn stop_on(walls: &[Wall], i: usize, me: &End, strict: bool) -> Option<Vec<V2>> {
    let me = *me;
    let tol_in = TOL;
    // a wall this end stops on
    for (j, w) in walls.iter().enumerate() {
        if j == i {
            continue;
        }
        // its face on the side this wall runs to, as a line: a curved wall's the tangent where
        // this end stands, seen from its centre
        let (face, d) = if let Some(a) = w.arc_geom() {
            let v = me.p - a.centre;
            let rp = v.length();
            if rp < 1e-9 {
                continue;
            }
            let ang = v.y.atan2(v.x);
            // how far round from its start, the way it turns
            let tau = std::f64::consts::TAU;
            let mut turned = (ang - a.a0) * a.sweep.signum();
            turned = turned.rem_euclid(tau);
            let arc_len = turned * a.radius;
            if arc_len <= TOL || arc_len >= a.radius * a.sweep.abs() - TOL {
                continue;
            }
            // to the left of a counter-clockwise arc is toward its centre
            let off = if a.sweep > 0.0 { a.radius - rp } else { rp - a.radius };
            if off > w.left + tol_in || off < -w.right - tol_in {
                continue;
            }
            let radial = v * (1.0 / rp);
            let tg = if a.sweep > 0.0 { v2(-radial.y, radial.x) } else { v2(radial.y, -radial.x) };
            let n = tg.perp();
            // before any node join: not where it stands on the face on its own side already
            let own_side = if me.u.dot(n) > 0.0 { w.left } else { -w.right };
            if strict && (off - own_side).abs() <= TOL {
                continue;
            }
            let r_face = if me.u.dot(n) > 0.0 {
                if a.sweep > 0.0 { a.radius - w.left } else { a.radius + w.left }
            } else if a.sweep > 0.0 {
                a.radius + w.right
            } else {
                a.radius - w.right
            };
            (a.centre + radial * r_face, tg)
        } else {
            let d = (w.end - w.start).normalize();
            let n = d.perp();
            let v = me.p - w.start;
            let t = v.dot(d);
            let len = (w.end - w.start).length();
            // along it, clear of its ends (an end within the tolerance of one is a node)
            if t <= TOL || t >= len - TOL {
                continue;
            }
            let off = v.dot(n);
            // between its faces, or within the tolerance of one
            if off > w.left + tol_in || off < -w.right - tol_in {
                continue;
            }
            // before any node join: not where it stands on the face on its own side already
            let own_side = if me.u.dot(n) > 0.0 { w.left } else { -w.right };
            if strict && (off - own_side).abs() <= TOL {
                continue;
            }
            (if me.u.dot(n) > 0.0 { w.start + n * w.left } else { w.start - n * w.right }, d)
        };
        let (la, ld) = me.left_line();
        let (ra, rd) = me.right_line();
        let lt = line_cross_t(la, ld, face, d);
        let rt = line_cross_t(ra, rd, face, d);
        if let (Some(lt), Some(rt)) = (lt, rt) {
            // each face cut at that face, or squared where the cut runs farther from its end
            // than the thicker of the two walls is thick
            let lim = walls[i].thickness.max(w.thickness);
            let l = if lt.abs() <= lim { la + ld * lt } else { me.lp };
            let r = if rt.abs() <= lim { ra + rd * rt } else { me.rp };
            return Some(vec![r, l]);
        }
    }
    None
}

/// What caps one end: points in the outline's order (from the outgoing right face to the
/// outgoing left), and whether it joins another wall there.
fn cap(walls: &[Wall], i: usize, at_end: bool) -> Vec<V2> {
    let me = end_of(&walls[i], i, at_end);
    // an end standing in another wall stops at its face, before it joins any at a node
    if let Some(c) = stop_on(walls, i, &me, true) {
        return c;
    }
    // the other walls with an end at this one's
    let mut ends = vec![me];
    for (j, w) in walls.iter().enumerate() {
        if j == i {
            continue;
        }
        if w.start.distance(me.p) <= TOL {
            ends.push(end_of(w, j, false));
        }
        if w.end.distance(me.p) <= TOL {
            ends.push(end_of(w, j, true));
        }
    }
    if ends.len() > 1 {
        let ang = |e: &End| e.u.y.atan2(e.u.x);
        let mut order: Vec<usize> = (0..ends.len()).collect();
        order.sort_by(|a, b| ang(&ends[*a]).partial_cmp(&ang(&ends[*b])).unwrap_or(std::cmp::Ordering::Equal));
        let k = order.iter().position(|x| *x == 0).unwrap();
        let ccw = ends[order[(k + 1) % order.len()]];
        let cw = ends[order[(k + order.len() - 1) % order.len()]];
        let (la, ld) = me.left_line();
        let (ra, rd) = me.right_line();
        let (cra, crd) = ccw.right_line();
        let (cwa, cwd) = cw.left_line();
        let lt = line_cross_t(la, ld, cra, crd);
        let rt = line_cross_t(ra, rd, cwa, cwd);
        // each face mitred to its neighbour's, or squared at the node where the mitre runs
        // farther from it than the thickest wall there is thick
        let thickest = ends.iter().map(|e| walls[e.wall].thickness).fold(0.0, f64::max);
        let (lim_l, lim_r) = (thickest, thickest);
        let l = match lt {
            Some(t) if t.abs() <= lim_l => la + ld * t,
            _ => me.lp,
        };
        let r = match rt {
            Some(t) if t.abs() <= lim_r => ra + rd * t,
            _ => me.rp,
        };
        return vec![r, me.p, l];
    }
    if let Some(c) = stop_on(walls, i, &me, false) {
        return c;
    }
    // a free end: the faces' own ends
    let w = &walls[i];
    let lp = w.offset_points(w.left);
    let rp = w.offset_points(-w.right);
    if at_end {
        vec![*lp.last().unwrap(), *rp.last().unwrap()]
    } else {
        vec![rp[0], lp[0]]
    }
}

/// The outline of each wall, in plan, clockwise from its start's right face corner: its start
/// cap, its left face, its end cap and its right face back.
pub fn outlines(walls: &[Wall]) -> Vec<Vec<V2>> {
    raw_outlines(walls)
        .into_iter()
        .map(|ring| {
            let mut clean: Vec<V2> = Vec::with_capacity(ring.len());
            for p in ring {
                if let Some(q) = clean.last() {
                    if q.distance(p) < 1e-6 {
                        continue;
                    }
                }
                clean.push(p);
            }
            while clean.len() > 1 && clean[0].distance(*clean.last().unwrap()) < 1e-6 {
                clean.pop();
            }
            clean
        })
        .collect()
}

/// Each wall's outline as its caps and faces give it, a corner twice where a cap's point
/// falls on a face's (what a wall attached to a roof or a floor is cut from).
pub fn raw_outlines(walls: &[Wall]) -> Vec<Vec<V2>> {
    let mut out = Vec::with_capacity(walls.len());
    for (i, w) in walls.iter().enumerate() {
        // the same level only
        let same: Vec<usize> = (0..walls.len()).filter(|j| *j == i || (walls[*j].z0 < w.z1 && w.z0 < walls[*j].z1)).collect();
        let sub: Vec<Wall> = same.iter().map(|j| walls[*j].clone()).collect();
        let k = same.iter().position(|j| *j == i).unwrap();
        let sc = cap(&sub, k, false);
        let ec = cap(&sub, k, true);
        let lp = w.offset_points(w.left);
        let rp = w.offset_points(-w.right);
        let mut ring = Vec::new();
        ring.extend(sc.iter().cloned());
        if lp.len() > 2 {
            ring.extend(lp[1..lp.len() - 1].iter().cloned());
        }
        ring.extend(ec.iter().cloned());
        if rp.len() > 2 {
            ring.extend(rp[1..rp.len() - 1].iter().rev().cloned());
        }
        out.push(ring);
    }
    out
}

/// Where a wall's centre line ends: run on or back to meet the centre line of the wall it joins
/// at that end (the other wall at a node, or the wall it stops on), else its own end `p`.
pub fn centre_end(walls: &[Wall], i: usize, at_end: bool, p: V2, d: V2) -> V2 {
    let w = &walls[i];
    let node = if at_end { w.end } else { w.start };
    let centre_of = |o: &Wall| -> (V2, V2) {
        let od = (o.end - o.start).normalize();
        let off = (o.left - o.right) / 2.0;
        (o.start + od.perp() * off, od)
    };
    let mut others = Vec::new();
    for (j, o) in walls.iter().enumerate() {
        if j == i {
            continue;
        }
        if o.start.distance(node) <= TOL || o.end.distance(node) <= TOL {
            others.push(j);
        }
    }
    if !others.is_empty() {
        let mut best: Option<V2> = None;
        for j in others {
            let o = &walls[j];
            if o.is_arc() {
                continue;
            }
            let (oa, od) = centre_of(o);
            if let Some(x) = line_cross(p, d, oa, od) {
                if best.map(|b| b.distance(p) > x.distance(p)).unwrap_or(true) {
                    best = Some(x);
                }
            }
        }
        return best.unwrap_or(p);
    }
    for (j, o) in walls.iter().enumerate() {
        if j == i || o.is_arc() {
            continue;
        }
        let od = (o.end - o.start).normalize();
        let n = od.perp();
        let v = node - o.start;
        let t = v.dot(od);
        let len = (o.end - o.start).length();
        if t <= TOL || t >= len - TOL {
            continue;
        }
        let off = v.dot(n);
        if off > o.left + TOL || off < -o.right - TOL {
            continue;
        }
        let (oa, odd) = centre_of(o);
        if let Some(x) = line_cross(p, d, oa, odd) {
            return x;
        }
    }
    p
}
