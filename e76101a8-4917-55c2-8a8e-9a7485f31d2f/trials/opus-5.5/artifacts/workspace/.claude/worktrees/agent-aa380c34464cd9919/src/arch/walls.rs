//! Walls: the `wall` and `flip` commands, a wall's geometry (its location line and centre line,
//! faces, arcs, heights) and the model's rules for walls.

use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::{self, Arc, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// The fields of a wall, in its struct's order.
pub const ORDER: &[&str] = &[
    "type",
    "level",
    "start",
    "end",
    "top_level",
    "height",
    "base_offset",
    "top_offset",
    "arc",
    "location",
    "attach_top",
    "attach_base",
    "room_bounding",
    "params",
];

pub const LOCATIONS: &[&str] = &["centre", "core-centre", "exterior-finish", "interior-finish", "exterior-core", "interior-core"];

/// A wall as the geometry reads it.
#[derive(Clone, Debug)]
pub struct Wall {
    pub id: u64,
    pub type_name: String,
    pub level: Option<u64>,
    /// On the location line.
    pub start: P2,
    pub end: P2,
    pub top_level: Option<u64>,
    pub height: f64,
    pub base_offset: f64,
    pub top_offset: f64,
    pub arc: f64,
    pub location: String,
    pub room_bounding: bool,
    pub thickness: f64,
    /// How far right of the location line the centre line is.
    pub shift: f64,
}

impl Wall {
    pub fn read(pr: &Project, id: u64) -> Option<Wall> {
        let e = pr.el(id)?;
        if cat(e) != "wall" {
            return None;
        }
        let type_name = type_name(pr, e).unwrap_or_default();
        let thickness = thickness(pr, "wall", &type_name);
        let location = text(e, "location").unwrap_or("centre").to_string();
        let shift = location_shift(pr, &type_name, &location, thickness);
        let top_level = e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level"));
        Some(Wall {
            id,
            type_name,
            level: level_of(pr, e),
            start: pt(e, "start").unwrap_or([0.0, 0.0]),
            end: pt(e, "end").unwrap_or([0.0, 0.0]),
            top_level,
            height: numd(e, "height", 3000.0),
            base_offset: numd(e, "base_offset", 0.0),
            top_offset: numd(e, "top_offset", 0.0),
            arc: numd(e, "arc", 0.0),
            location,
            room_bounding: flag(e, "room_bounding").unwrap_or(true),
            thickness,
            shift,
        })
    }

    pub fn all(pr: &Project) -> Vec<Wall> {
        pr.elements.keys().filter_map(|id| Wall::read(pr, *id)).collect()
    }

    pub fn is_arc(&self) -> bool {
        !geom::straight(self.arc)
    }

    pub fn arc(&self) -> Arc {
        Arc::new(self.start, self.end, self.arc)
    }

    /// The location line's length (an arc's along it).
    pub fn length(&self) -> f64 {
        if self.is_arc() {
            self.arc().length()
        } else {
            geom::dist(self.start, self.end)
        }
    }

    /// The centre line's ends (the location line moved `shift` to its right).
    pub fn centre(&self) -> (P2, P2) {
        if self.shift == 0.0 {
            return (self.start, self.end);
        }
        if self.is_arc() {
            let a = self.arc();
            // to the right of a counter-clockwise arc is away from its centre
            let r = if a.sweep > 0.0 { a.radius + self.shift } else { a.radius - self.shift };
            let a1 = a.a0 + a.sweep;
            let s = [a.centre[0] + r * a.a0.cos(), a.centre[1] + r * a.a0.sin()];
            let e = [a.centre[0] + r * a1.cos(), a.centre[1] + r * a1.sin()];
            return (s, e);
        }
        let n = geom::unit(geom::sub(self.end, self.start));
        let right = [n[1], -n[0]];
        (geom::add(self.start, geom::scale(right, self.shift)), geom::add(self.end, geom::scale(right, self.shift)))
    }

    /// The centre line as straight pieces (an arc in chords within a millimetre).
    pub fn centre_pieces(&self) -> Vec<(P2, P2)> {
        let (s, e) = self.centre();
        if self.is_arc() {
            let pts = crate::geom::graph::arc_points(s, e, self.arc, 1.0);
            pts.windows(2).map(|w| (w[0], w[1])).collect()
        } else {
            vec![(s, e)]
        }
    }

    /// The level's elevation plus the base offset.
    pub fn base(&self, pr: &Project) -> f64 {
        self.level.map(|l| elev(pr, l)).unwrap_or(0.0) + self.base_offset
    }

    /// Its top, unattached: the top level's elevation plus the top offset, or the base plus the
    /// height when it has no top level.
    pub fn top(&self, pr: &Project) -> f64 {
        match self.top_level {
            Some(t) => elev(pr, t) + self.top_offset,
            None => self.base(pr) + self.height,
        }
    }

    /// Its base and top as built: attached, the lowest of what its base stands on and the
    /// highest of what its top runs up to, over its footprint.
    pub fn heights(&self, pr: &Project) -> (f64, f64) {
        match pr.el(self.id) {
            Some(e) => super::hosts::wall_heights(pr, self, e),
            None => (self.base(pr), self.top(pr)),
        }
    }

    /// Whether the wall spans the height z (its base at or under it, its top over it).
    pub fn spans(&self, pr: &Project, z: f64) -> bool {
        let (b, t) = self.heights(pr);
        b <= z && z < t
    }
}

/// The centre lines of a set of walls, each run on or back to meet the centre line of the wall it
/// joins at each end (a wall whose location line its end touches, at an end or part way along):
/// for each wall, its straight pieces (an arc's chords).
pub fn joined_centres(walls: &[Wall]) -> Vec<Vec<(P2, P2)>> {
    let tol = crate::geom::graph::WELD;
    let mut out = Vec::with_capacity(walls.len());
    for (i, w) in walls.iter().enumerate() {
        if w.is_arc() {
            out.push(arc_joined(walls, i, tol));
            continue;
        }
        let (mut cs, mut ce) = w.centre();
        let (cs0, ce0) = (cs, ce);
        let dir = geom::sub(w.end, w.start);
        for (k, p) in [w.start, w.end].iter().enumerate() {
            // of the other walls the end touches (a straight one not in line with it), the one
            // whose centre line it meets nearest
            let here = if k == 0 { cs0 } else { ce0 };
            let mut best: Option<(P2, f64)> = None;
            for (j, o) in walls.iter().enumerate() {
                if j == i {
                    continue;
                }
                let q = if o.is_arc() {
                    if !on_arc(o, *p, tol) {
                        continue;
                    }
                    // an arc meets others along its tangent where it ends (or where the end touches it)
                    let (t0, t1) = arc_tangent_at(o, *p);
                    line_meet(cs, ce, t0, t1)
                } else {
                    let od = geom::sub(o.end, o.start);
                    let par = geom::cross(geom::unit(dir), geom::unit(od)).abs() < 1e-9;
                    if par || geom::seg_dist(o.start, o.end, *p) > tol {
                        continue;
                    }
                    let (os, oe) = o.centre();
                    line_meet(cs, ce, os, oe)
                };
                let Some(q) = q else { continue };
                let dq = geom::dist(q, here);
                if best.map(|(_, b)| dq < b).unwrap_or(true) {
                    best = Some((q, dq));
                }
            }
            if let Some((q, _)) = best {
                if k == 0 {
                    cs = q;
                } else {
                    ce = q;
                }
            }
        }
        out.push(vec![(cs, ce)]);
    }
    out
}

/// The wall a straight wall's end joins (as `joined_centres` picks it), by index.
fn join_target(walls: &[Wall], i: usize, k: usize, tol: f64) -> Option<usize> {
    let w = &walls[i];
    let (cs, ce) = w.centre();
    let dir = geom::sub(w.end, w.start);
    let p = if k == 0 { w.start } else { w.end };
    let here = if k == 0 { cs } else { ce };
    let mut best: Option<(usize, f64)> = None;
    for (j, o) in walls.iter().enumerate() {
        if j == i {
            continue;
        }
        let q = if o.is_arc() {
            if !on_arc(o, p, tol) {
                continue;
            }
            let (t0, t1) = arc_tangent_at(o, p);
            line_meet(cs, ce, t0, t1)
        } else {
            let od = geom::sub(o.end, o.start);
            if geom::cross(geom::unit(dir), geom::unit(od)).abs() < 1e-9 || geom::seg_dist(o.start, o.end, p) > tol {
                continue;
            }
            let (os, oe) = o.centre();
            line_meet(cs, ce, os, oe)
        };
        let Some(q) = q else { continue };
        let dq = geom::dist(q, here);
        if best.map(|(_, b)| dq < b).unwrap_or(true) {
            best = Some((j, dq));
        }
    }
    best.map(|b| b.0)
}

/// A straight wall's footprint between its faces as the faces' outline gives it: its faces cut
/// where they meet the walls its ends join (mitred at a corner, at the other's face where it
/// ends against one), square at a free end; from its start's left corner round, or from its
/// end's right one when its end meets an earlier wall than its start does.
pub fn footprint(walls: &[Wall], i: usize) -> Option<Vec<P2>> {
    let tol = crate::geom::graph::WELD;
    let w = &walls[i];
    if w.is_arc() {
        return None;
    }
    let (cs, ce) = w.centre();
    let u = geom::unit(geom::sub(ce, cs));
    let l = geom::left(u);
    let h = w.thickness / 2.0;
    let lf = (geom::add(cs, geom::scale(l, h)), geom::add(ce, geom::scale(l, h)));
    let rf = (geom::sub(cs, geom::scale(l, h)), geom::sub(ce, geom::scale(l, h)));
    let mut caps: [(P2, P2); 2] = [
        (lf.0, rf.0),
        (lf.1, rf.1),
    ];
    let mut partner = [i, i];
    for k in 0..2 {
        let Some(j) = join_target(walls, i, k, tol) else { continue };
        let o = &walls[j];
        if o.is_arc() {
            continue;
        }
        partner[k] = j;
        let (os, oe) = o.centre();
        let uo = geom::unit(geom::sub(oe, os));
        let lo = geom::left(uo);
        let ho = o.thickness / 2.0;
        let ol = (geom::add(os, geom::scale(lo, ho)), geom::add(oe, geom::scale(lo, ho)));
        let or = (geom::sub(os, geom::scale(lo, ho)), geom::sub(oe, geom::scale(lo, ho)));
        let p = if k == 0 { w.start } else { w.end };
        let at_start = geom::dist(p, o.start) <= tol;
        let at_end = geom::dist(p, o.end) <= tol;
        let (for_left, for_right) = if at_start || at_end {
            // a corner: in turn round it, left meets left; head to head, left meets right
            if (k == 1 && at_start) || (k == 0 && at_end) {
                (ol, or)
            } else {
                (or, ol)
            }
        } else {
            // against its side: both stop at the face toward this wall
            let far = if k == 0 { w.end } else { w.start };
            let side = geom::cross(uo, geom::sub(far, os));
            if side >= 0.0 {
                (ol, ol)
            } else {
                (or, or)
            }
        };
        let a = line_meet(lf.0, lf.1, for_left.0, for_left.1);
        let b = line_meet(rf.0, rf.1, for_right.0, for_right.1);
        if let (Some(a), Some(b)) = (a, b) {
            caps[k] = (a, b);
        }
    }
    let ring = vec![caps[0].0, caps[0].1, caps[1].1, caps[1].0];
    if partner[1] < partner[0] {
        Some(vec![ring[2], ring[3], ring[0], ring[1]])
    } else {
        Some(ring)
    }
}

/// The circle of an arc wall's centre line: centre, radius, start angle and sweep.
fn centre_circle(w: &Wall) -> (P2, f64, f64, f64) {
    let a = w.arc();
    let r = if a.sweep > 0.0 { a.radius + w.shift } else { a.radius - w.shift };
    (a.centre, r, a.a0, a.sweep)
}

/// Whether a point lies on an arc wall's location line (within tol).
fn on_arc(w: &Wall, p: P2, tol: f64) -> bool {
    let a = w.arc();
    if (geom::dist(p, a.centre) - a.radius).abs() > tol {
        return false;
    }
    if geom::dist(p, w.start) <= tol || geom::dist(p, w.end) <= tol {
        return true;
    }
    let ang = (p[1] - a.centre[1]).atan2(p[0] - a.centre[0]);
    let mut da = ang - a.a0;
    if a.sweep < 0.0 {
        da = -da;
    }
    da = da.rem_euclid(std::f64::consts::TAU);
    da <= a.sweep.abs()
}

/// The tangent line of an arc wall's centre line where a point touches it: at the nearer end
/// when the point is at an end, else where the point's radius crosses it.
fn arc_tangent_at(w: &Wall, p: P2) -> (P2, P2) {
    let (c, r, a0, sweep) = centre_circle(w);
    let ang = if geom::dist(p, w.start) <= geom::dist(p, w.end) && geom::dist(p, w.start) <= crate::geom::graph::WELD {
        a0
    } else if geom::dist(p, w.end) <= crate::geom::graph::WELD {
        a0 + sweep
    } else {
        (p[1] - c[1]).atan2(p[0] - c[0])
    };
    let q = [c[0] + r * ang.cos(), c[1] + r * ang.sin()];
    let t = [-ang.sin(), ang.cos()];
    (q, geom::add(q, t))
}

/// An arc wall's centre line in chords, each end run on or back along its tangent to meet the
/// centre line of the wall its location line's end touches.
fn arc_joined(walls: &[Wall], i: usize, tol: f64) -> Vec<(P2, P2)> {
    let w = &walls[i];
    let mut pieces = w.centre_pieces();
    if pieces.is_empty() {
        return pieces;
    }
    for (k, p) in [w.start, w.end].iter().enumerate() {
        // of the walls the end touches, the one its tangent meets nearest
        let (t0, t1) = arc_tangent_at(w, *p);
        let tu = geom::unit(geom::sub(t1, t0));
        let mut best: Option<(P2, f64)> = None;
        for (j, o) in walls.iter().enumerate() {
            if j == i {
                continue;
            }
            let touches = if o.is_arc() { on_arc(o, *p, tol) } else { geom::seg_dist(o.start, o.end, *p) <= tol };
            if !touches {
                continue;
            }
            let (u0, u1) = if o.is_arc() { arc_tangent_at(o, *p) } else { o.centre() };
            let od = geom::unit(geom::sub(u1, u0));
            if geom::cross(tu, od).abs() < 1e-9 {
                continue;
            }
            let Some(q) = line_meet(t0, t1, u0, u1) else { continue };
            let dq = geom::dist(q, t0);
            if best.map(|(_, b)| dq < b).unwrap_or(true) {
                best = Some((q, dq));
            }
        }
        if let Some((q, _)) = best {
            if k == 0 {
                pieces[0].0 = q;
            } else {
                let m = pieces.len();
                pieces[m - 1].1 = q;
            }
        }
    }
    pieces
}

/// Where two lines (through a0, a1 and through b0, b1) meet.
pub fn line_meet(a0: P2, a1: P2, b0: P2, b1: P2) -> Option<P2> {
    let d = geom::sub(a1, a0);
    let e = geom::sub(b1, b0);
    let den = geom::cross(d, e);
    if den == 0.0 {
        return None;
    }
    let t = geom::cross(geom::sub(b0, a0), e) / den;
    Some([a0[0] + d[0] * t, a0[1] + d[1] * t])
}

/// How far right of a wall's location line its centre line lies, for its type and location.
pub fn location_shift(pr: &Project, type_name: &str, location: &str, t: f64) -> f64 {
    let ls = layers(pr, "wall", type_name);
    // the core: from the first structure layer to the last, else the whole wall
    let mut acc = 0.0;
    let mut core: Option<(f64, f64)> = None;
    for (f, th) in &ls {
        if f == "structure" {
            core = Some(match core {
                None => (acc, acc + th),
                Some((a, _)) => (a, acc + th),
            });
        }
        acc += th;
    }
    let (c0, c1) = core.unwrap_or((0.0, t));
    let s = match location {
        "exterior-finish" => 0.0,
        "interior-finish" => t,
        "exterior-core" => c0,
        "interior-core" => c1,
        "core-centre" => (c0 + c1) / 2.0,
        _ => t / 2.0,
    };
    t / 2.0 - s
}

/// A location as the command reads it (any case, `center` for `centre`); None if it's none.
pub fn parse_location(s: &str) -> Option<&'static str> {
    let l = s.trim().to_lowercase();
    match l.as_str() {
        "centre" | "center" => Some("centre"),
        "core-centre" | "core-center" => Some("core-centre"),
        "exterior-finish" => Some("exterior-finish"),
        "interior-finish" => Some("interior-finish"),
        "exterior-core" => Some("exterior-core"),
        "interior-core" => Some("interior-core"),
        _ => None,
    }
}

// ---------------------------------------------------------------- the commands

pub fn cmd_wall(s: &mut Session, p: &Value) -> R<Value> {
    let c = "wall";
    let points: Vec<P2> = match params::get(p, "points") {
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                match params::point_of(x) {
                    Some(q) => out.push(q),
                    None => return Err(format!("wall: `points`: {} is not a point [x, y] in mm", x.to_compact())),
                }
            }
            out
        }
        _ => return Err("wall: `points` [[x, y], …] is required".into()),
    };
    if points.len() < 2 {
        return Err("wall: `points` needs at least 2 points".into());
    }
    let closed = params::opt_bool(p, c, "closed")?.unwrap_or(false);
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let ty = params::opt_text(p, c, "type")?;
    let height = params::opt_num(p, c, "height")?;
    let top_level = match params::get(p, "top_level") {
        Some(v) => Some(crate::model::resolve_level(pr, c, "top_level", v)?),
        None => None,
    };
    let base_offset = params::opt_num(p, c, "base_offset")?;
    let top_offset = params::opt_num(p, c, "top_offset")?;
    let arc = params::opt_num(p, c, "arc")?;
    let location = match params::opt_text(p, c, "location")? {
        None => None,
        Some(l) => match parse_location(&l) {
            Some(x) => Some(x),
            None => {
                return Err(format!(
                    "wall: `location` is one of centre, core-centre, exterior-finish, interior-finish, exterior-core, interior-core, not `{}`",
                    l
                ))
            }
        },
    };
    let attach_top = opt_ref(p, c, "attach_top")?;
    let attach_base = opt_ref(p, c, "attach_base")?;
    let room_bounding = match params::get(p, "room_bounding") {
        None => None,
        Some(Value::Bool(b)) => Some(*b),
        Some(_) => return Err("wall: `room_bounding` is true or false".into()),
    };
    let ty = ty.or_else(|| default_type(pr, "wall")).ok_or_else(|| "wall: the model has no types for this".to_string())?;
    // up to the next level, unless it is given a height (unconnected) or a top level
    let top = match top_level {
        Some(t) => Some(t),
        None if height.is_some() => None,
        None => crate::model::level_above(pr, level),
    };
    let mut segs: Vec<(P2, P2)> = points.windows(2).map(|w| (w[0], w[1])).collect();
    if closed {
        segs.push((points[points.len() - 1], points[0]));
    }
    let mut ids = Vec::new();
    for (a, b) in segs {
        let e = make_wall(s, &ty, level, a, b, top, height, base_offset, top_offset, arc, location, &attach_top, &attach_base, room_bounding);
        let id = s.project.alloc_id();
        s.project.elements.insert(id, e);
        ids.push(id);
    }
    Ok(jobj! {"ids" => ids})
}

#[allow(clippy::too_many_arguments)]
pub fn make_wall(
    s: &Session,
    ty: &str,
    level: u64,
    a: P2,
    b: P2,
    top: Option<u64>,
    height: Option<f64>,
    base_offset: Option<f64>,
    top_offset: Option<f64>,
    arc: Option<f64>,
    location: Option<&str>,
    attach_top: &Option<Value>,
    attach_base: &Option<Value>,
    room_bounding: Option<bool>,
) -> Value {
    let pr = &s.project;
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "wall",
        "type" => type_ref(pr, "wall", ty),
        "level" => level_guid(pr, level),
        "start" => pv(a),
        "end" => pv(b),
        "top_level" => match top { Some(t) => Value::Str(level_guid(pr, t)), None => Value::Null },
        "height" => height.unwrap_or(3000.0),
        "base_offset" => base_offset.unwrap_or(0.0),
    };
    if let Some(t) = top_offset {
        if t != 0.0 {
            e.set("top_offset", Value::f(t));
        }
    }
    if let Some(x) = arc {
        if x != 0.0 {
            e.set("arc", Value::f(x));
        }
    }
    if let Some(l) = location {
        if l != "centre" {
            e.set("location", Value::s(l));
        }
    }
    if let Some(v) = attach_top {
        e.set("attach_top", ref_value(pr, v));
    }
    if let Some(v) = attach_base {
        e.set("attach_base", ref_value(pr, v));
    }
    if room_bounding == Some(false) {
        e.set("room_bounding", Value::Bool(false));
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    e
}

pub fn cmd_flip(s: &mut Session, p: &Value) -> R<Value> {
    let list: Vec<Value> = match params::get(p, "ids") {
        Some(Value::Arr(a)) => a.clone(),
        Some(_) => return Err("flip: `ids` [id, …] is required".into()),
        None => match params::get(p, "id") {
            Some(v) => vec![v.clone()],
            None => return Err("flip: `ids` [id, …] is required".into()),
        },
    };
    let pr = &s.project;
    let mut ids: Vec<u64> = Vec::new();
    for v in &list {
        let id = match by_ref(pr, v) {
            Some(id) => id,
            None => return Err(format!("flip: no element {}", ref_word(pr, v))),
        };
        let c = pr.category(id).unwrap_or("");
        if c != "wall" {
            return Err(format!("flip: {} {} isn't a wall", c, id));
        }
        if !ids.contains(&id) {
            ids.push(id);
        }
    }
    for &id in &ids {
        flip_wall(&mut s.project, id);
    }
    Ok(jobj! {"flipped" => ids})
}

/// Turns a wall round about its location line: its ends swapped (an arc turning back the other
/// way), its doors and windows kept where they stand, facing and hand flipped.
pub fn flip_wall(pr: &mut Project, id: u64) {
    let Some(w) = Wall::read(pr, id) else { return };
    let len = w.length();
    let g = pr.guid_of(id).unwrap_or_default();
    if let Some(e) = pr.el_mut(id) {
        e.set("start", pv(w.end));
        e.set("end", pv(w.start));
        if let Some(a) = num(e, "arc") {
            e.set("arc", Value::f(-a));
        }
    }
    let hosted: Vec<u64> = pr
        .elements
        .iter()
        .filter(|(_, e)| matches!(cat(e), "door" | "window") && text(e, "host") == Some(g.as_str()))
        .map(|(k, _)| *k)
        .collect();
    for h in hosted {
        if let Some(e) = pr.el_mut(h) {
            let off = numd(e, "offset", 0.0);
            e.set("offset", Value::f(len - off));
            let ff = flag(e, "flip_facing").unwrap_or(false);
            let fh = flag(e, "flip_hand").unwrap_or(false);
            e.set("flip_facing", Value::Bool(!ff));
            e.set("flip_hand", Value::Bool(!fh));
        }
    }
}

// ---------------------------------------------------------------- the rules

/// Whether an arc of `deg` degrees from a to b is one the model takes: under a full turn either
/// way, its circle within 1000 km of the origin (a turn under 1e-9 rad is straight).
pub fn arc_ok(a: P2, b: P2, deg: f64) -> bool {
    if !deg.is_finite() || deg.abs() >= 360.0 {
        return false;
    }
    if geom::straight(deg) {
        return true;
    }
    let arc = Arc::new(a, b, deg);
    let reach = arc.centre[0].abs().max(arc.centre[1].abs()) + arc.radius;
    reach.is_finite() && reach <= params::MAX_MM
}

/// The model's rules for one wall, in the original's order.
pub fn check_wall(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_type(pr, id, e, "wall")?;
    let w = match Wall::read(pr, id) {
        Some(w) => w,
        None => return Ok(()),
    };
    let l = geom::dist(w.start, w.end);
    if !(l > 1.0) {
        return Err(format!("wall {}: too short ({} mm)", id, d(l)));
    }
    if !arc_ok(w.start, w.end, w.arc) {
        return Err(format!(
            "wall {}: arc {}° isn't between -360° and 360°, reaching no farther than 1000 km",
            id,
            d(w.arc)
        ));
    }
    for k in ["attach_top", "attach_base"] {
        if let Some(v) = e.get(k) {
            if v.is_null() {
                continue;
            }
            let ok = by_ref(pr, v).map(|t| matches!(pr.category(t), Some("roof") | Some("floor"))).unwrap_or(false);
            if !ok {
                return Err(format!("wall {}: {} {} isn't a roof or a floor", id, k, ref_word(pr, v)));
            }
        }
    }
    if w.top_level.is_none() && !(w.height > 0.0) {
        return Err(format!("wall {} height must be above zero, got {}", id, d(w.height)));
    }
    let (base, top) = w.heights(pr);
    if !(top - base > 1.0) {
        let tall = (top - base).round() as i64;
        return Err(format!(
            "wall {}: its top ({:.0} mm) must be above its base ({:.0} mm); it comes out {} mm tall, so raise its top constraint, top offset or height by more than {} mm",
            id,
            top,
            base,
            tall,
            -tall
        ));
    }
    Ok(())
}
