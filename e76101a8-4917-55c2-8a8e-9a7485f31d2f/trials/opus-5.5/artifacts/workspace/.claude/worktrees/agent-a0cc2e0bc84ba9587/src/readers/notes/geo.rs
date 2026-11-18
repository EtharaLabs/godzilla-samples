//! Plan geometry the notes read: points and directions, walls' faces (by their location line, their
//! type's layers and the joins at their ends), the openings in them, grids and detail lines as the
//! lines and arcs a dimension measures to.

use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, Ctx};
use std::collections::HashMap;
use std::rc::Rc;

pub type P = [f64; 2];

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
pub fn len(a: P) -> f64 {
    a[0].hypot(a[1])
}
pub fn dist(a: P, b: P) -> f64 {
    len(sub(b, a))
}
pub fn unit(a: P) -> P {
    let l = len(a);
    if l == 0.0 {
        [0.0, 0.0]
    } else {
        [a[0] / l, a[1] / l]
    }
}
/// The direction a quarter turn counter-clockwise from `a` (to its left).
pub fn left(a: P) -> P {
    [-a[1], a[0]]
}
pub fn lerp(a: P, b: P, t: f64) -> P {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}
/// Where the lines through `p` along `d` and through `q` along `e` cross.
pub fn meet(p: P, d: P, q: P, e: P) -> Option<P> {
    let den = cross(d, e);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = cross(sub(q, p), e) / den;
    Some(add(p, mul(d, t)))
}

pub fn pt(v: Option<&Value>) -> Option<P> {
    let a = v?.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn pval(p: P) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

// ---------------------------------------------------------------- arcs

/// A circular arc from `a` to `b` turning `turn` degrees counter-clockwise (negative: clockwise).
#[derive(Clone, Copy, Debug)]
pub struct Arc {
    pub c: P,
    pub r: f64,
    /// The angle of its start from its centre, and how far it turns (radians, signed).
    pub a0: f64,
    pub sweep: f64,
}

impl Arc {
    pub fn from_chord(a: P, b: P, turn_deg: f64) -> Option<Arc> {
        let t = turn_deg.to_radians();
        let chord = dist(a, b);
        if t.abs() < 1e-12 || chord == 0.0 {
            return None;
        }
        let r = chord / (2.0 * (t / 2.0).sin().abs());
        let m = lerp(a, b, 0.5);
        let d = unit(sub(b, a));
        // the centre lies to the left of a→b for a counter-clockwise turn under a half circle
        let h = (r * r - chord * chord / 4.0).max(0.0).sqrt();
        let side = if (t.abs() < std::f64::consts::PI) == (t > 0.0) { 1.0 } else { -1.0 };
        let c = add(m, mul(left(d), h * side));
        let a0 = (a[1] - c[1]).atan2(a[0] - c[0]);
        Some(Arc { c, r, a0, sweep: t })
    }
    pub fn at(&self, f: f64) -> P {
        let ang = self.a0 + self.sweep * f;
        [self.c[0] + self.r * ang.cos(), self.c[1] + self.r * ang.sin()]
    }
    pub fn length(&self) -> f64 {
        self.r * self.sweep.abs()
    }
    /// The same arc moved `off` toward its left (of its way along): smaller round a counter-clockwise arc.
    pub fn offset(&self, off: f64) -> Arc {
        let r = if self.sweep > 0.0 { self.r - off } else { self.r + off };
        Arc { r, ..*self }
    }
}

// ---------------------------------------------------------------- walls

/// A wall as the notes measure it: its location line, its faces and their ends after joins.
#[derive(Clone, Debug)]
pub struct Wall {
    pub id: u64,
    pub level: String,
    pub a: P,
    pub b: P,
    pub d: P,
    pub n: P,
    pub length: f64,
    pub t: f64,
    /// How far its left and right faces lie to the left of its location line.
    pub left: f64,
    pub right: f64,
    pub arc: Option<Arc>,
    /// Its faces' corners after the joins at its ends: [left start, left end, right start, right end].
    pub corners: [P; 4],
}

impl Wall {
    pub fn centre_off(&self) -> f64 {
        (self.left + self.right) / 2.0
    }
    /// The line of a face (`left`, `right`, `centre`): a point on it.
    pub fn face_point(&self, face: &str) -> P {
        let off = match face {
            "left" => self.left,
            "right" => self.right,
            _ => self.centre_off(),
        };
        add(self.a, mul(self.n, off))
    }
    pub fn face_arc(&self, face: &str) -> Option<Arc> {
        let off = match face {
            "left" => self.left,
            "right" => self.right,
            _ => self.centre_off(),
        };
        self.arc.map(|a| a.offset(off))
    }
    /// A face's end: a corner after joins (left, right), or the centre line's.
    pub fn face_end(&self, face: &str, end: bool) -> P {
        match face {
            "left" => self.corners[if end { 1 } else { 0 }],
            "right" => self.corners[if end { 3 } else { 2 }],
            _ => {
                if let Some(a) = self.face_arc("centre") {
                    return a.at(if end { 1.0 } else { 0.0 });
                }
                let off = mul(self.n, self.centre_off());
                add(if end { self.b } else { self.a }, off)
            }
        }
    }
    /// How far along it (from its start) its start or end face lies: the farthest its faces reach.
    pub fn end_along(&self, end: bool) -> f64 {
        if end {
            dot(sub(self.corners[1], self.a), self.d).max(dot(sub(self.corners[3], self.a), self.d))
        } else {
            dot(sub(self.corners[0], self.a), self.d).min(dot(sub(self.corners[2], self.a), self.d))
        }
    }
}

/// A wall type's thickness and where its core lies: the thickness of its layers outside the core
/// and of the core (the structure layers and what lies between them; the whole wall without layers).
pub fn wall_type_dims(def: &Value) -> (f64, f64, f64) {
    let t = common::num(def, "thickness").unwrap_or(0.0);
    let layers: Vec<(String, f64)> = def
        .get("layers")
        .and_then(|l| l.as_arr())
        .map(|a| {
            a.iter()
                .map(|l| (common::text(l, "function").unwrap_or("").to_string(), common::num(l, "thickness").unwrap_or(0.0)))
                .collect()
        })
        .unwrap_or_default();
    if layers.is_empty() {
        return (t, 0.0, t);
    }
    let first = layers.iter().position(|(f, _)| f == "structure");
    let last = layers.iter().rposition(|(f, _)| f == "structure");
    match (first, last) {
        (Some(i), Some(j)) => {
            let ext: f64 = layers[..i].iter().map(|l| l.1).sum();
            let core: f64 = layers[i..=j].iter().map(|l| l.1).sum();
            (t, ext, core)
        }
        _ => (t, 0.0, t),
    }
}

/// The wall without its joins: its line, faces and square ends.
fn bare_wall(pr: &Project, id: u64, e: &Value) -> Option<Wall> {
    let a = pt(e.get("start"))?;
    let b = pt(e.get("end"))?;
    let (t, ext, core) = common::element_type(pr, e).map(|(_, def)| wall_type_dims(def)).unwrap_or((0.0, 0.0, 0.0));
    // the exterior is the wall's left side
    let left = match common::text(e, "location").unwrap_or("centre") {
        "exterior-finish" => 0.0,
        "interior-finish" => t,
        "core-centre" => ext + core / 2.0,
        "exterior-core" => ext,
        "interior-core" => ext + core,
        _ => t / 2.0,
    };
    let right = left - t;
    let d = unit(sub(b, a));
    let n = left_of(d);
    let arc = common::num(e, "arc").filter(|x| *x != 0.0).and_then(|t| Arc::from_chord(a, b, t));
    let length = match &arc {
        Some(c) => c.length(),
        None => dist(a, b),
    };
    let mut w = Wall {
        id,
        level: common::text(e, "level").unwrap_or("").to_string(),
        a,
        b,
        d,
        n,
        length,
        t,
        left,
        right,
        arc,
        corners: [[0.0; 2]; 4],
    };
    if let Some(c) = arc {
        let l = c.offset(left);
        let r = c.offset(right);
        w.corners = [l.at(0.0), l.at(1.0), r.at(0.0), r.at(1.0)];
    } else {
        w.corners = [add(a, mul(n, left)), add(b, mul(n, left)), add(a, mul(n, right)), add(b, mul(n, right))];
    }
    Some(w)
}

fn left_of(d: P) -> P {
    left(d)
}

/// How near two walls' ends are to be joined.
const JOIN_TOL: f64 = 1.0;

/// Every wall of the project with its joins worked out, by id.
pub fn walls(cx: &Ctx) -> Rc<HashMap<u64, Wall>> {
    cx.cached("notes:walls", || Rc::new(make_walls(cx.pr)))
}

pub fn wall(cx: &Ctx, id: u64) -> Option<Wall> {
    walls(cx).get(&id).cloned()
}

fn make_walls(pr: &Project) -> HashMap<u64, Wall> {
    let mut bare: Vec<Wall> = Vec::new();
    for (id, e) in &pr.elements {
        if common::category(e) == "wall" {
            if let Some(w) = bare_wall(pr, *id, e) {
                bare.push(w);
            }
        }
    }
    let mut out = HashMap::new();
    for w in &bare {
        let mut j = w.clone();
        if w.arc.is_none() {
            for end in [false, true] {
                join_end(&bare, w, &mut j, end);
            }
        }
        out.insert(w.id, j);
    }
    out
}

/// The wall's end at `end`: (its point, its direction pointing away from the wall's body).
fn end_of(w: &Wall, end: bool) -> (P, P) {
    if end {
        (w.b, w.d)
    } else {
        (w.a, mul(w.d, -1.0))
    }
}

/// A face line of `w` as seen from one of its ends going away from its body: (point, direction) of
/// the face that is on the left when walking out of the wall through that end.
fn face_line(w: &Wall, end: bool, left_side: bool) -> (P, P) {
    // walking out through the end: along d at the end, against d at the start
    let (_, out) = end_of(w, end);
    let off = if end == left_side { w.left } else { w.right };
    (add(w.a, mul(w.n, off)), out)
}

fn set_corner(j: &mut Wall, end: bool, left_face: bool, p: P) {
    let k = match (left_face, end) {
        (true, false) => 0,
        (true, true) => 1,
        (false, false) => 2,
        (false, true) => 3,
    };
    j.corners[k] = p;
}

fn join_end(all: &[Wall], w: &Wall, j: &mut Wall, end: bool) {
    let (p, out) = end_of(w, end);
    if w.length == 0.0 {
        return;
    }
    // the other walls ending at this end
    let mut mates: Vec<(&Wall, bool)> = Vec::new();
    for o in all {
        if o.id == w.id || o.level != w.level || o.arc.is_some() || o.length == 0.0 {
            continue;
        }
        if dist(o.a, p) <= JOIN_TOL {
            mates.push((o, false));
        } else if dist(o.b, p) <= JOIN_TOL {
            mates.push((o, true));
        }
    }
    if mates.len() == 1 {
        let (m, mend) = mates[0];
        let (_, mout) = end_of(m, mend);
        // walking out of w through p and into m: w's left face goes on as m's right face seen
        // walking out of m through its end (it is walked the other way)
        let mut corners = Vec::new();
        for left_side in [true, false] {
            let (fp, fd) = face_line(w, end, left_side);
            let (mp, md) = face_line(m, mend, !left_side);
            let c = meet(fp, fd, mp, md);
            corners.push(c);
        }
        let ok = corners.iter().all(|c| c.is_some()) && {
            let ext: Vec<f64> = corners.iter().map(|c| dot(sub(c.unwrap(), p), out)).collect();
            ext.iter().all(|e| e.abs() <= w.t.max(m.t) + 1e-9)
        };
        let _ = mout;
        if ok {
            for (i, left_side) in [true, false].iter().enumerate() {
                let face_is_left = end == *left_side;
                set_corner(j, end, face_is_left, corners[i].unwrap());
            }
        }
        return;
    }
    if mates.len() == 2 {
        // two of the three running on as one wall: the third abuts them
        let dirs: Vec<P> = mates.iter().map(|(m, me)| end_of(m, *me).1).collect();
        let straight = |a: P, b: P| dot(a, b) < -0.999_999;
        if straight(out, dirs[0]) || straight(out, dirs[1]) {
            // w runs on through: the abutting wall is the other one
            let (other, oend) = if straight(out, dirs[0]) { mates[1] } else { mates[0] };
            let (_, oout) = end_of(other, oend);
            // the abutting wall comes in on w's side where its body lies
            let side_left = dot(mul(oout, -1.0), w.n) > 0.0;
            // that face of w ends at the abutting wall's face on its side
            let face_off = if side_left { w.left } else { w.right };
            let fp = add(w.a, mul(w.n, face_off));
            // the abutting wall's faces: the one nearer w's body
            let lp = add(other.a, mul(other.n, other.left));
            let rp = add(other.a, mul(other.n, other.right));
            let pick = |q: P| dot(sub(q, p), mul(out, -1.0));
            let face = if pick(lp) > pick(rp) { lp } else { rp };
            if let Some(c) = meet(fp, w.d, face, other.d) {
                set_corner(j, end, side_left, c);
            }
            return;
        }
        if straight(dirs[0], dirs[1]) {
            // w abuts the two running on: cut at their face on its side
            let (h, _) = mates[0];
            cut_at_host(w, j, end, h);
        }
        return;
    }
    if !mates.is_empty() {
        return;
    }
    // a wall it ends inside
    for o in all {
        if o.id == w.id || o.level != w.level || o.arc.is_some() || o.length == 0.0 {
            continue;
        }
        let along = dot(sub(p, o.a), o.d);
        let across = dot(sub(p, o.a), o.n);
        if along > 0.0 && along < o.length && across <= o.left + 1e-9 && across >= o.right - 1e-9 {
            cut_at_host(w, j, end, o);
            return;
        }
    }
}

/// The end of `w` cut at the face of `h` on the side its body comes from.
fn cut_at_host(w: &Wall, j: &mut Wall, end: bool, h: &Wall) {
    let (p, out) = end_of(w, end);
    let lp = add(h.a, mul(h.n, h.left));
    let rp = add(h.a, mul(h.n, h.right));
    // the face toward the rest of w
    let back = mul(out, -1.0);
    let face = if dot(sub(lp, p), back) > dot(sub(rp, p), back) { lp } else { rp };
    for face_left in [true, false] {
        let off = if face_left { w.left } else { w.right };
        let fp = add(w.a, mul(w.n, off));
        if let Some(c) = meet(fp, w.d, face, h.d) {
            set_corner(j, end, face_left, c);
        }
    }
}

// ---------------------------------------------------------------- openings

/// A door's or window's width: its type's, its family type's or its family's `Width`, or one of
/// its own.
pub fn opening_width(pr: &Project, e: &Value) -> Option<f64> {
    if let Some(w) = e.get("params").and_then(|p| p.get("Width")).and_then(|w| w.as_f64()) {
        return Some(w);
    }
    if let Some(fg) = common::text(e, "family") {
        let (fname, fam) = common::family(pr, fg)?;
        let tname = common::text(e, "type").and_then(|g| common::family_type(pr, &fname, g));
        if let Some(tn) = tname {
            if let Some(w) = fam.get("types").and_then(|t| t.get(&tn)).and_then(|t| t.get("Width")).and_then(|w| w.as_f64()) {
                return Some(w);
            }
        }
        let params = fam.get("parameters")?.as_arr()?;
        for p in params {
            if common::text(p, "name") == Some("Width") {
                return common::num(p, "value");
            }
        }
        return None;
    }
    let (_, def) = common::element_type(pr, e)?;
    common::num(def, "width")
}

/// Where a door or window stands on its wall's location line, and the wall's way there.
pub fn opening_place(cx: &Ctx, e: &Value) -> Option<(P, P, Wall)> {
    let (hid, _) = common::target(cx.pr, e, "host")?;
    let w = wall(cx, hid)?;
    let off = common::num(e, "offset").unwrap_or(0.0);
    if let Some(a) = w.arc {
        let f = if a.length() == 0.0 { 0.0 } else { off / a.length() };
        let p = a.at(f);
        let ang = a.a0 + a.sweep * f;
        let tan = if a.sweep > 0.0 { [-ang.sin(), ang.cos()] } else { [ang.sin(), -ang.cos()] };
        return Some((p, tan, w));
    }
    Some((add(w.a, mul(w.d, off)), w.d, w))
}
