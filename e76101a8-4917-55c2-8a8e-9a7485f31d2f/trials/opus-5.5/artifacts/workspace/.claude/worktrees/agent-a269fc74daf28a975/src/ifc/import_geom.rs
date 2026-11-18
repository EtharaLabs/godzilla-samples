//! Geometry of an IFC file: placements, curves, profiles and the solids a body is made of, all
//! turned into faces in the project's coordinates (millimetres).

use super::import_model::Model;
use super::step::{Entity, P};

pub type V2 = [f64; 2];
pub type V3 = [f64; 3];

pub fn add(a: V3, b: V3) -> V3 {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}
pub fn sub(a: V3, b: V3) -> V3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
pub fn mul(a: V3, k: f64) -> V3 {
    [a[0] * k, a[1] * k, a[2] * k]
}
pub fn dot(a: V3, b: V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
pub fn cross(a: V3, b: V3) -> V3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
pub fn norm(a: V3) -> f64 {
    dot(a, a).sqrt()
}
pub fn unit(a: V3) -> V3 {
    let n = norm(a);
    if n > 0.0 {
        mul(a, 1.0 / n)
    } else {
        a
    }
}

/// An affine map: `p' = x*p0 + y*p1 + z*p2 + t` (the axes may be scaled).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Tf {
    pub x: V3,
    pub y: V3,
    pub z: V3,
    pub t: V3,
}

impl Tf {
    pub const ID: Tf = Tf { x: [1.0, 0.0, 0.0], y: [0.0, 1.0, 0.0], z: [0.0, 0.0, 1.0], t: [0.0, 0.0, 0.0] };
    pub fn apply(&self, p: V3) -> V3 {
        [
            self.x[0] * p[0] + self.y[0] * p[1] + self.z[0] * p[2] + self.t[0],
            self.x[1] * p[0] + self.y[1] * p[1] + self.z[1] * p[2] + self.t[1],
            self.x[2] * p[0] + self.y[2] * p[1] + self.z[2] * p[2] + self.t[2],
        ]
    }
    /// A direction (no translation).
    pub fn dir(&self, d: V3) -> V3 {
        [
            self.x[0] * d[0] + self.y[0] * d[1] + self.z[0] * d[2],
            self.x[1] * d[0] + self.y[1] * d[1] + self.z[1] * d[2],
            self.x[2] * d[0] + self.y[2] * d[1] + self.z[2] * d[2],
        ]
    }
    /// `self ∘ o`: o first, then self.
    pub fn then(&self, o: &Tf) -> Tf {
        Tf { x: self.dir(o.x), y: self.dir(o.y), z: self.dir(o.z), t: self.apply(o.t) }
    }
    /// The inverse of a rigid map (orthonormal axes).
    pub fn inverse_rigid(&self) -> Tf {
        let tx = [self.x[0], self.y[0], self.z[0]];
        let ty = [self.x[1], self.y[1], self.z[1]];
        let tz = [self.x[2], self.y[2], self.z[2]];
        let r = Tf { x: tx, y: ty, z: tz, t: [0.0; 3] };
        let t = r.dir(self.t);
        Tf { t: mul(t, -1.0), ..r }
    }
    pub fn det(&self) -> f64 {
        dot(self.x, cross(self.y, self.z))
    }
}

/// A planar face: its outer loop and its holes, as points in space.
#[derive(Clone, Debug, Default)]
pub struct Face {
    pub outer: Vec<V3>,
    pub holes: Vec<Vec<V3>>,
}

/// An extrusion as the file wrote it: a profile (outer loop and holes, in plan of its own
/// coordinates), the map of those coordinates, the direction and the depth.
#[derive(Clone, Debug)]
pub struct Extrusion {
    pub outer: Vec<V2>,
    pub holes: Vec<Vec<V2>>,
    /// The profile's coordinates to the project's (the solid's position and the placement).
    pub tf: Tf,
    /// The extrusion direction in the profile's coordinates (a unit vector), and the depth.
    pub dir: V3,
    pub depth: f64,
    /// The profile's kind and its sizes when it is a parametric one (rectangle `x` by `y`,
    /// circle of a radius), in the profile's own frame.
    pub param: Param,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Param {
    None,
    Rect { x: f64, y: f64, centre: V2, xdir: V2 },
    Circle { r: f64, centre: V2 },
    /// A hollow circle (a pipe's section): outer radius and wall thickness.
    CircleHollow { r: f64, t: f64, centre: V2 },
}

/// One solid (or surface model) of a body.
#[derive(Clone, Debug)]
pub struct Solid {
    pub faces: Vec<Face>,
    /// Set when the solid is one extrusion of a profile.
    pub ext: Option<Extrusion>,
    /// The representation item's entity (the extrusion, the Brep, the mesh…).
    pub item: u64,
    /// Whether it is a clipped solid (a boolean result: its first operand is kept).
    pub clipped: bool,
    /// The half spaces that clip it, in the project's coordinates: a point on the plane and the
    /// normal pointing out of the material that is kept (the file's AgreementFlag applied).
    pub clips: Vec<(V3, V3)>,
}

impl Solid {
    pub fn points(&self) -> impl Iterator<Item = &V3> {
        self.faces.iter().flat_map(|f| f.outer.iter().chain(f.holes.iter().flatten()))
    }
}

/// How finely arcs are cut into chords: the number of segments for a full circle.
pub const CIRCLE_SEGMENTS: usize = 72;

pub fn p2(m: &Model, id: u64) -> Option<V2> {
    let e = m.get(id)?;
    if e.name != "IFCCARTESIANPOINT" {
        return None;
    }
    let c = e.p(0).nums()?;
    Some([*c.first().unwrap_or(&0.0) * m.scale, *c.get(1).unwrap_or(&0.0) * m.scale])
}

pub fn p3(m: &Model, id: u64) -> Option<V3> {
    let e = m.get(id)?;
    if e.name != "IFCCARTESIANPOINT" {
        return None;
    }
    let c = e.p(0).nums()?;
    Some([
        *c.first().unwrap_or(&0.0) * m.scale,
        *c.get(1).unwrap_or(&0.0) * m.scale,
        *c.get(2).unwrap_or(&0.0) * m.scale,
    ])
}

pub fn dir3(m: &Model, p: &P) -> Option<V3> {
    let e = m.get(p.r()?)?;
    if e.name != "IFCDIRECTION" {
        return None;
    }
    let c = e.p(0).nums()?;
    Some([*c.first().unwrap_or(&0.0), *c.get(1).unwrap_or(&0.0), *c.get(2).unwrap_or(&0.0)])
}

/// IFC's first projected axis: `v` (or the default) made square to `z`.
fn first_proj(z: V3, v: Option<V3>) -> V3 {
    let v = match v {
        Some(v) => v,
        None => {
            if z != [1.0, 0.0, 0.0] {
                [1.0, 0.0, 0.0]
            } else {
                [0.0, 1.0, 0.0]
            }
        }
    };
    unit(sub(v, mul(z, dot(v, z))))
}

/// An IfcAxis2Placement3D (or 2D) as a map.
pub fn axis_placement(m: &Model, id: u64) -> Tf {
    let e = match m.get(id) {
        Some(e) => e,
        None => return Tf::ID,
    };
    match e.name.as_str() {
        "IFCAXIS2PLACEMENT3D" => {
            let t = e.p(0).r().and_then(|r| p3(m, r)).unwrap_or([0.0; 3]);
            let z = unit(dir3(m, e.p(1)).unwrap_or([0.0, 0.0, 1.0]));
            let x = first_proj(z, dir3(m, e.p(2)));
            let y = cross(z, x);
            Tf { x, y, z, t }
        }
        "IFCAXIS2PLACEMENT2D" => {
            let o = e.p(0).r().and_then(|r| p2(m, r)).unwrap_or([0.0; 2]);
            let d = dir3(m, e.p(1)).unwrap_or([1.0, 0.0, 0.0]);
            let x = unit([d[0], d[1], 0.0]);
            Tf { x, y: [-x[1], x[0], 0.0], z: [0.0, 0.0, 1.0], t: [o[0], o[1], 0.0] }
        }
        _ => Tf::ID,
    }
}

/// An IfcLocalPlacement (or a grid placement, as its origin) in the project's coordinates.
pub fn placement(m: &Model, id: u64) -> Tf {
    let mut chain: Vec<Tf> = Vec::new();
    let mut cur = Some(id);
    let mut guard = 0;
    while let Some(c) = cur {
        guard += 1;
        if guard > 1000 {
            break;
        }
        let e = match m.get(c) {
            Some(e) => e,
            None => break,
        };
        if e.name != "IFCLOCALPLACEMENT" {
            break;
        }
        chain.push(e.p(1).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID));
        cur = e.p(0).r();
    }
    let mut t = Tf::ID;
    for l in chain.iter().rev() {
        t = t.then(l);
    }
    t
}

/// An IfcCartesianTransformationOperator (2D or 3D, uniform or not).
pub fn operator(m: &Model, id: u64) -> Tf {
    let e = match m.get(id) {
        Some(e) => e,
        None => return Tf::ID,
    };
    let is2d = e.name.starts_with("IFCCARTESIANTRANSFORMATIONOPERATOR2D");
    let a1 = dir3(m, e.p(0));
    let a2 = dir3(m, e.p(1));
    let o = e.p(2).r().and_then(|r| p3(m, r)).unwrap_or([0.0; 3]);
    let s = e.p(3).num().unwrap_or(1.0);
    let (x, y, z);
    if is2d {
        let d1 = unit(a1.map(|d| [d[0], d[1], 0.0]).unwrap_or([1.0, 0.0, 0.0]));
        x = d1;
        y = a2.map(|d| unit([d[0], d[1], 0.0])).unwrap_or([-d1[1], d1[0], 0.0]);
        z = [0.0, 0.0, 1.0];
    } else {
        let a3 = dir3(m, e.p(4));
        let d1 = unit(a3.unwrap_or([0.0, 0.0, 1.0]));
        let d2 = first_proj(d1, a1);
        let v = a2.unwrap_or([0.0, 1.0, 0.0]);
        let d3 = unit(sub(sub(v, mul(d1, dot(v, d1))), mul(d2, dot(v, d2))));
        x = d2;
        y = d3;
        z = d1;
    }
    let (s2, s3) = if e.name.ends_with("NONUNIFORM") {
        if is2d {
            (e.p(4).num().unwrap_or(s), 1.0)
        } else {
            (e.p(5).num().unwrap_or(s), e.p(6).num().unwrap_or(s))
        }
    } else {
        (s, if is2d { 1.0 } else { s })
    };
    Tf { x: mul(x, s), y: mul(y, s2), z: mul(z, s3), t: o }
}

// ---------------------------------------------------------------- curves

/// Points along an arc of a circle (centre, radius) from angle a0 to a1 (radians, a1 > a0 for
/// counter-clockwise), both ends included.
pub fn arc_points(c: V2, r: f64, a0: f64, a1: f64) -> Vec<V2> {
    arc_points_n(c, r, a0, a1, CIRCLE_SEGMENTS)
}

/// `arc_points` with `seg` segments to a full circle.
pub fn arc_points_n(c: V2, r: f64, a0: f64, a1: f64, seg: usize) -> Vec<V2> {
    let sweep = a1 - a0;
    let n = ((sweep.abs() / (2.0 * std::f64::consts::PI) * seg as f64).ceil() as usize).max(1);
    (0..=n)
        .map(|i| {
            let a = a0 + sweep * i as f64 / n as f64;
            [c[0] + r * a.cos(), c[1] + r * a.sin()]
        })
        .collect()
}

/// The circle through three points (centre, radius), if they are not in a line.
pub fn circle3(a: V2, b: V2, c: V2) -> Option<(V2, f64)> {
    // about the first point, so that an arc far from the origin keeps its precision
    let (bx, by) = (b[0] - a[0], b[1] - a[1]);
    let (cx, cy) = (c[0] - a[0], c[1] - a[1]);
    let d = 2.0 * (bx * cy - by * cx);
    if d.abs() < 1e-12 {
        return None;
    }
    let b2 = bx * bx + by * by;
    let c2 = cx * cx + cy * cy;
    let ux = (cy * b2 - by * c2) / d;
    let uy = (bx * c2 - cx * b2) / d;
    let r = (ux * ux + uy * uy).sqrt();
    Some(([a[0] + ux, a[1] + uy], r))
}

/// A curve's points in its own coordinates (3D; a 2D curve has z = 0), and whether it is closed
/// by its nature (a circle).
pub fn curve(m: &Model, id: u64) -> Option<Vec<V3>> {
    curve_seg(m, id, CIRCLE_SEGMENTS)
}

/// `curve` with arcs in `seg` segments to a full circle.
pub fn curve_seg(m: &Model, id: u64, seg: usize) -> Option<Vec<V3>> {
    let e = m.get(id)?;
    match e.name.as_str() {
        "IFCPOLYLINE" => {
            let mut v = Vec::new();
            for r in e.p(0).refs() {
                v.push(p3(m, r)?);
            }
            Some(v)
        }
        "IFCINDEXEDPOLYCURVE" => indexed_polycurve(m, e, seg),
        "IFCCOMPOSITECURVE" | "IFCCOMPOSITECURVEONSURFACE" => {
            let mut out: Vec<V3> = Vec::new();
            for sg in e.p(0).refs() {
                let s = m.get(sg)?;
                // IfcCompositeCurveSegment(Transition, SameSense, ParentCurve)
                let parent = s.p(2).r()?;
                let mut pts = curve_seg(m, parent, seg)?;
                if s.p(1).boolean() == Some(false) {
                    pts.reverse();
                }
                for p in pts {
                    if let Some(l) = out.last() {
                        if norm(sub(*l, p)) < 1e-9 {
                            continue;
                        }
                    }
                    out.push(p);
                }
            }
            Some(out)
        }
        "IFCTRIMMEDCURVE" => trimmed(m, e, seg),
        "IFCCIRCLE" => {
            let tf = e.p(0).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID);
            let r = e.p(1).num()? * m.scale;
            let pts = arc_points_n([0.0, 0.0], r, 0.0, 2.0 * std::f64::consts::PI, seg);
            let mut v: Vec<V3> = pts.iter().map(|p| tf.apply([p[0], p[1], 0.0])).collect();
            v.pop();
            v.push(v[0]);
            Some(v)
        }
        "IFCELLIPSE" => {
            let tf = e.p(0).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID);
            let a = e.p(1).num()? * m.scale;
            let b = e.p(2).num()? * m.scale;
            let n = seg;
            let mut v: Vec<V3> = (0..n)
                .map(|i| {
                    let t = 2.0 * std::f64::consts::PI * i as f64 / n as f64;
                    tf.apply([a * t.cos(), b * t.sin(), 0.0])
                })
                .collect();
            v.push(v[0]);
            Some(v)
        }
        "IFCLINE" => None,
        _ => None,
    }
}

fn indexed_polycurve(m: &Model, e: &Entity, seg: usize) -> Option<Vec<V3>> {
    let pl = m.get(e.p(0).r()?)?;
    let coords: Vec<V3> = pl
        .p(0)
        .list()?
        .iter()
        .filter_map(|c| {
            let v = c.nums()?;
            Some([
                *v.first().unwrap_or(&0.0) * m.scale,
                *v.get(1).unwrap_or(&0.0) * m.scale,
                *v.get(2).unwrap_or(&0.0) * m.scale,
            ])
        })
        .collect();
    let at = |i: i64| -> Option<V3> { coords.get((i - 1) as usize).copied() };
    let mut out: Vec<V3> = Vec::new();
    let push = |out: &mut Vec<V3>, p: V3| {
        if let Some(l) = out.last() {
            if norm(sub(*l, p)) < 1e-9 {
                return;
            }
        }
        out.push(p);
    };
    match e.p(1) {
        P::List(segs) if !segs.is_empty() => {
            for s in segs {
                match s {
                    P::Typed(n, v) => {
                        let idx: Vec<i64> = v.first().and_then(|l| l.list()).map(|l| l.iter().filter_map(|x| x.int()).collect()).unwrap_or_default();
                        if n == "IFCARCINDEX" && idx.len() == 3 {
                            let (a, b, c) = (at(idx[0])?, at(idx[1])?, at(idx[2])?);
                            for p in arc3_n(a, b, c, seg) {
                                push(&mut out, p);
                            }
                        } else {
                            for i in idx {
                                push(&mut out, at(i)?);
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
        _ => {
            for p in coords.iter() {
                push(&mut out, *p);
            }
        }
    }
    Some(out)
}

/// Points along the arc through three points (in a plane of constant z).
pub fn arc3(a: V3, b: V3, c: V3) -> Vec<V3> {
    arc3_n(a, b, c, CIRCLE_SEGMENTS)
}

/// `arc3` with `seg` segments to a full circle.
pub fn arc3_n(a: V3, b: V3, c: V3, seg: usize) -> Vec<V3> {
    let (cc, r) = match circle3([a[0], a[1]], [b[0], b[1]], [c[0], c[1]]) {
        Some(x) => x,
        None => return vec![a, b, c],
    };
    let ang = |p: V3| (p[1] - cc[1]).atan2(p[0] - cc[0]);
    let (a0, am, a1) = (ang(a), ang(b), ang(c));
    // counter-clockwise if the middle point lies on the ccw sweep from a to c
    let tau = 2.0 * std::f64::consts::PI;
    let norm_a = |x: f64| ((x % tau) + tau) % tau;
    let ccw_m = norm_a(am - a0);
    let ccw_c = norm_a(a1 - a0);
    let sweep = if ccw_m <= ccw_c { ccw_c } else { ccw_c - tau };
    arc_points_n(cc, r, a0, a0 + sweep, seg).into_iter().map(|p| [p[0], p[1], a[2]]).collect()
}

fn trimmed(m: &Model, e: &Entity, seg: usize) -> Option<Vec<V3>> {
    // IfcTrimmedCurve(BasisCurve, Trim1, Trim2, SenseAgreement, MasterRepresentation)
    let bid = e.p(0).r()?;
    let basis = m.get(bid)?;
    let sense = e.p(3).boolean().unwrap_or(true);
    let master_param = e.p(4).enm() == Some("PARAMETER");
    let trim = |p: &P| -> (Option<f64>, Option<V3>) {
        let mut par = None;
        let mut pt = None;
        if let Some(l) = p.list() {
            for x in l {
                match x {
                    P::Ref(r) => pt = p3(m, *r),
                    P::Typed(n, _) if n == "IFCPARAMETERVALUE" => par = x.num(),
                    _ => {}
                }
            }
        }
        (par, pt)
    };
    let (t1, q1) = trim(e.p(1));
    let (t2, q2) = trim(e.p(2));
    match basis.name.as_str() {
        "IFCCIRCLE" | "IFCELLIPSE" => {
            let tf = basis.p(0).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID);
            let inv = tf.inverse_rigid();
            let ra = basis.p(1).num()? * m.scale;
            let rb = if basis.name == "IFCELLIPSE" { basis.p(2).num()? * m.scale } else { ra };
            let angle_of = |t: Option<f64>, q: Option<V3>| -> Option<f64> {
                let use_param = t.is_some() && (master_param || q.is_none());
                if use_param {
                    Some(t? * m.angle)
                } else {
                    let l = inv.apply(q?);
                    Some((l[1] / rb).atan2(l[0] / ra))
                }
            };
            let a0 = angle_of(t1, q1)?;
            let mut a1 = angle_of(t2, q2)?;
            let tau = 2.0 * std::f64::consts::PI;
            if sense {
                while a1 <= a0 {
                    a1 += tau;
                }
            } else {
                while a1 >= a0 {
                    a1 -= tau;
                }
            }
            if a0.abs() > 1e6 || a1.abs() > 1e6 {
                return None;
            }
            let sweep = a1 - a0;
            let n = ((sweep.abs() / tau * seg as f64).ceil() as usize).max(1);
            let pts: Vec<V3> = (0..=n)
                .map(|i| {
                    let a = a0 + sweep * i as f64 / n as f64;
                    tf.apply([ra * a.cos(), rb * a.sin(), 0.0])
                })
                .collect();
            Some(pts)
        }
        "IFCLINE" => {
            // IfcLine(Pnt, Dir: IfcVector(Orientation, Magnitude))
            let o = p3(m, basis.p(0).r()?)?;
            let v = m.get(basis.p(1).r()?)?;
            let d = dir3(m, v.p(0))?;
            let mag = v.p(1).num().unwrap_or(1.0) * m.scale;
            let dv = mul(unit(d), mag);
            let at = |t: Option<f64>, q: Option<V3>| -> Option<V3> {
                if let Some(q) = q {
                    if !(master_param && t.is_some()) {
                        return Some(q);
                    }
                }
                Some(add(o, mul(dv, t?)))
            };
            let a = at(t1, q1)?;
            let b = at(t2, q2)?;
            Some(if sense { vec![a, b] } else { vec![b, a] })
        }
        _ => curve_seg(m, bid, seg),
    }
}

/// A closed loop of a curve, in plan (its z dropped), without the repeated last point.
pub fn loop2(m: &Model, id: u64) -> Option<Vec<V2>> {
    let pts = curve(m, id)?;
    let mut v: Vec<V2> = pts.iter().map(|p| [p[0], p[1]]).collect();
    while v.len() > 1 {
        let (a, b) = (v[0], v[v.len() - 1]);
        if (a[0] - b[0]).abs() < 1e-9 && (a[1] - b[1]).abs() < 1e-9 {
            v.pop();
        } else {
            break;
        }
    }
    if v.len() < 3 {
        return None;
    }
    Some(v)
}

// ---------------------------------------------------------------- profiles

/// A profile: its outer loop and holes in its own plan, and its parametric kind.
pub fn profile(m: &Model, id: u64) -> Option<(Vec<V2>, Vec<Vec<V2>>, Param)> {
    let e = m.get(id)?;
    let pos = |i: usize| -> Tf { e.p(i).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID) };
    let tr = |tf: &Tf, v: Vec<V2>| -> Vec<V2> {
        v.into_iter()
            .map(|p| {
                let q = tf.apply([p[0], p[1], 0.0]);
                [q[0], q[1]]
            })
            .collect()
    };
    let s = m.scale;
    match e.name.as_str() {
        "IFCRECTANGLEPROFILEDEF" | "IFCROUNDEDRECTANGLEPROFILEDEF" | "IFCRECTANGLEHOLLOWPROFILEDEF" => {
            let tf = pos(2);
            let x = e.p(3).num()? * s;
            let y = e.p(4).num()? * s;
            let (hx, hy) = (x / 2.0, y / 2.0);
            let outer = tr(&tf, vec![[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]]);
            let mut holes = Vec::new();
            if e.name == "IFCRECTANGLEHOLLOWPROFILEDEF" {
                if let Some(t) = e.p(5).num() {
                    let t = t * s;
                    let (ix, iy) = (hx - t, hy - t);
                    if ix > 0.0 && iy > 0.0 {
                        holes.push(tr(&tf, vec![[-ix, -iy], [-ix, iy], [ix, iy], [ix, -iy]]));
                    }
                }
            }
            let param = Param::Rect { x, y, centre: [tf.t[0], tf.t[1]], xdir: [tf.x[0], tf.x[1]] };
            Some((outer, holes, param))
        }
        "IFCCIRCLEPROFILEDEF" | "IFCCIRCLEHOLLOWPROFILEDEF" => {
            let tf = pos(2);
            let r = e.p(3).num()? * s;
            let mut pts = arc_points([0.0, 0.0], r, 0.0, 2.0 * std::f64::consts::PI);
            pts.pop();
            let outer = tr(&tf, pts);
            let mut holes = Vec::new();
            let mut param = Param::Circle { r, centre: [tf.t[0], tf.t[1]] };
            if e.name == "IFCCIRCLEHOLLOWPROFILEDEF" {
                if let Some(t) = e.p(4).num() {
                    let t = t * s;
                    if r - t > 0.0 {
                        let mut ip = arc_points([0.0, 0.0], r - t, 0.0, 2.0 * std::f64::consts::PI);
                        ip.pop();
                        ip.reverse();
                        holes.push(tr(&tf, ip));
                    }
                    param = Param::CircleHollow { r, t, centre: [tf.t[0], tf.t[1]] };
                }
            }
            Some((outer, holes, param))
        }
        "IFCELLIPSEPROFILEDEF" => {
            let tf = pos(2);
            let a = e.p(3).num()? * s;
            let b = e.p(4).num()? * s;
            let n = CIRCLE_SEGMENTS;
            let pts: Vec<V2> = (0..n)
                .map(|i| {
                    let t = 2.0 * std::f64::consts::PI * i as f64 / n as f64;
                    [a * t.cos(), b * t.sin()]
                })
                .collect();
            Some((tr(&tf, pts), Vec::new(), Param::None))
        }
        "IFCARBITRARYCLOSEDPROFILEDEF" | "IFCARBITRARYPROFILEDEFWITHVOIDS" => {
            let outer = loop2(m, e.p(2).r()?)?;
            let mut holes = Vec::new();
            if e.name == "IFCARBITRARYPROFILEDEFWITHVOIDS" {
                for h in e.p(3).refs() {
                    if let Some(l) = loop2(m, h) {
                        holes.push(l);
                    }
                }
            }
            Some((outer, holes, Param::None))
        }
        "IFCISHAPEPROFILEDEF" | "IFCLSHAPEPROFILEDEF" | "IFCTSHAPEPROFILEDEF" | "IFCUSHAPEPROFILEDEF" | "IFCCSHAPEPROFILEDEF"
        | "IFCZSHAPEPROFILEDEF" | "IFCASYMMETRICISHAPEPROFILEDEF" => {
            // the section's bounding rectangle: its overall width and depth
            let tf = pos(2);
            let (w, d) = match e.name.as_str() {
                "IFCISHAPEPROFILEDEF" | "IFCASYMMETRICISHAPEPROFILEDEF" => (e.p(3).num()? * s, e.p(4).num()? * s),
                "IFCLSHAPEPROFILEDEF" => (e.p(4).num().unwrap_or(e.p(3).num()?) * s, e.p(3).num()? * s),
                "IFCTSHAPEPROFILEDEF" => (e.p(4).num()? * s, e.p(3).num()? * s),
                "IFCUSHAPEPROFILEDEF" => (e.p(4).num()? * s, e.p(3).num()? * s),
                "IFCCSHAPEPROFILEDEF" => (e.p(4).num()? * s, e.p(3).num()? * s),
                _ => (e.p(4).num()? * s, e.p(3).num()? * s),
            };
            let (hx, hy) = (w / 2.0, d / 2.0);
            let outer = tr(&tf, vec![[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]]);
            Some((outer, Vec::new(), Param::Rect { x: w, y: d, centre: [tf.t[0], tf.t[1]], xdir: [tf.x[0], tf.x[1]] }))
        }
        "IFCDERIVEDPROFILEDEF" => {
            let (o, h, _) = profile(m, e.p(2).r()?)?;
            let op = e.p(3).r().map(|r| operator(m, r)).unwrap_or(Tf::ID);
            Some((tr(&op, o), h.into_iter().map(|l| tr(&op, l)).collect(), Param::None))
        }
        _ => None,
    }
}

/// The signed area of a plan loop (counter-clockwise positive).
pub fn area2(v: &[V2]) -> f64 {
    let n = v.len();
    let mut a = 0.0;
    for i in 0..n {
        let (p, q) = (v[i], v[(i + 1) % n]);
        a += p[0] * q[1] - q[0] * p[1];
    }
    a / 2.0
}

// ---------------------------------------------------------------- solids

fn extrusion(m: &Model, e: &Entity, tf: &Tf, item: u64) -> Option<Solid> {
    // IfcExtrudedAreaSolid(SweptArea, Position, ExtrudedDirection, Depth)
    let (outer, holes, param) = profile(m, e.p(0).r()?)?;
    let pos = e.p(1).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID);
    let d = unit(dir3(m, e.p(2)).unwrap_or([0.0, 0.0, 1.0]));
    let depth = e.p(3).num()? * m.scale;
    let ptf = tf.then(&pos);
    let ext = Extrusion { outer, holes, tf: ptf, dir: d, depth, param };
    let faces = extrusion_faces(&ext);
    Some(Solid { faces, ext: Some(ext), item, clipped: false, clips: Vec::new() })
}

/// The faces of an extrusion: its base, its top and its sides.
pub fn extrusion_faces(x: &Extrusion) -> Vec<Face> {
    let off = mul(x.dir, x.depth);
    let at = |p: &V2, top: bool| -> V3 {
        let q = [p[0], p[1], 0.0];
        x.tf.apply(if top { add(q, off) } else { q })
    };
    let mut faces = Vec::new();
    let ccw = area2(&x.outer) >= 0.0;
    let ring = |l: &Vec<V2>, top: bool, rev: bool| -> Vec<V3> {
        let mut v: Vec<V3> = l.iter().map(|p| at(p, top)).collect();
        if rev {
            v.reverse();
        }
        v
    };
    faces.push(Face { outer: ring(&x.outer, false, ccw), holes: x.holes.iter().map(|h| ring(h, false, !ccw)).collect() });
    faces.push(Face { outer: ring(&x.outer, true, !ccw), holes: x.holes.iter().map(|h| ring(h, true, ccw)).collect() });
    let mut side = |l: &Vec<V2>| {
        let n = l.len();
        for i in 0..n {
            let (a, b) = (&l[i], &l[(i + 1) % n]);
            faces.push(Face { outer: vec![at(a, false), at(b, false), at(b, true), at(a, true)], holes: Vec::new() });
        }
    };
    side(&x.outer);
    for h in &x.holes {
        side(h);
    }
    faces
}

fn loop_points(m: &Model, id: u64, tf: &Tf) -> Option<Vec<V3>> {
    let e = m.get(id)?;
    match e.name.as_str() {
        "IFCPOLYLOOP" => {
            let mut v = Vec::new();
            for r in e.p(0).refs() {
                v.push(tf.apply(p3(m, r)?));
            }
            Some(v)
        }
        _ => {
            let pts = curve(m, id)?;
            Some(pts.into_iter().map(|p| tf.apply(p)).collect())
        }
    }
}

fn face_of(m: &Model, id: u64, tf: &Tf) -> Option<Face> {
    let e = m.get(id)?;
    // IfcFace(Bounds) / IfcFaceSurface(Bounds, FaceSurface, SameSense)
    let mut outer: Option<Vec<V3>> = None;
    let mut holes = Vec::new();
    for b in e.p(0).refs() {
        let be = m.get(b)?;
        let mut pts = loop_points(m, be.p(0).r()?, tf)?;
        if be.p(1).boolean() == Some(false) {
            pts.reverse();
        }
        if be.name == "IFCFACEOUTERBOUND" && outer.is_none() {
            outer = Some(pts);
        } else {
            holes.push(pts);
        }
    }
    let outer = match outer {
        Some(o) => o,
        None => {
            if holes.is_empty() {
                return None;
            }
            holes.remove(0)
        }
    };
    Some(Face { outer, holes })
}

fn shell_faces(m: &Model, id: u64, tf: &Tf, out: &mut Vec<Face>) -> Option<()> {
    let e = m.get(id)?;
    for f in e.p(0).refs() {
        if let Some(face) = face_of(m, f, tf) {
            out.push(face);
        }
    }
    Some(())
}

fn index_list(p: &P) -> Vec<Vec<i64>> {
    p.list().map(|l| l.iter().map(|t| t.list().map(|x| x.iter().filter_map(|i| i.int()).collect()).unwrap_or_default()).collect()).unwrap_or_default()
}

fn point_list(m: &Model, id: u64, tf: &Tf) -> Option<Vec<V3>> {
    let e = m.get(id)?;
    let s = m.scale;
    Some(
        e.p(0)
            .list()?
            .iter()
            .map(|c| {
                let v = c.nums().unwrap_or_default();
                tf.apply([
                    *v.first().unwrap_or(&0.0) * s,
                    *v.get(1).unwrap_or(&0.0) * s,
                    *v.get(2).unwrap_or(&0.0) * s,
                ])
            })
            .collect(),
    )
}

/// The solids of a representation item, in the project's coordinates.
pub fn item_solids(m: &Model, id: u64, tf: &Tf, out: &mut Vec<Solid>, depth: usize) {
    if depth > 32 {
        return;
    }
    let e = match m.get(id) {
        Some(e) => e,
        None => return,
    };
    match e.name.as_str() {
        "IFCEXTRUDEDAREASOLID" | "IFCEXTRUDEDAREASOLIDTAPERED" => {
            if let Some(s) = extrusion(m, e, tf, id) {
                out.push(s);
            }
        }
        "IFCFACETEDBREP" | "IFCFACETEDBREPWITHVOIDS" | "IFCADVANCEDBREP" | "IFCADVANCEDBREPWITHVOIDS" => {
            let mut faces = Vec::new();
            if let Some(sh) = e.p(0).r() {
                shell_faces(m, sh, tf, &mut faces);
            }
            if !faces.is_empty() {
                out.push(Solid { faces, ext: None, item: id, clipped: false, clips: Vec::new() });
            }
        }
        "IFCSHELLBASEDSURFACEMODEL" | "IFCFACEBASEDSURFACEMODEL" => {
            let mut faces = Vec::new();
            for sh in e.p(0).refs() {
                shell_faces(m, sh, tf, &mut faces);
            }
            if !faces.is_empty() {
                out.push(Solid { faces, ext: None, item: id, clipped: false, clips: Vec::new() });
            }
        }
        "IFCCLOSEDSHELL" | "IFCOPENSHELL" | "IFCCONNECTEDFACESET" => {
            let mut faces = Vec::new();
            shell_faces(m, id, tf, &mut faces);
            if !faces.is_empty() {
                out.push(Solid { faces, ext: None, item: id, clipped: false, clips: Vec::new() });
            }
        }
        "IFCTRIANGULATEDFACESET" | "IFCTRIANGULATEDIRREGULARNETWORK" => {
            // (Coordinates, Normals, Closed, CoordIndex, PnIndex)
            let pts = match e.p(0).r().and_then(|r| point_list(m, r, tf)) {
                Some(p) => p,
                None => return,
            };
            let pn: Vec<i64> = e.p(4).list().map(|l| l.iter().filter_map(|x| x.int()).collect()).unwrap_or_default();
            let at = |i: i64| -> Option<V3> {
                let j = if pn.is_empty() { i } else { *pn.get((i - 1) as usize)? };
                pts.get((j - 1) as usize).copied()
            };
            let mut faces = Vec::new();
            for t in index_list(e.p(3)) {
                let v: Option<Vec<V3>> = t.iter().map(|i| at(*i)).collect();
                if let Some(v) = v {
                    if v.len() >= 3 {
                        faces.push(Face { outer: v, holes: Vec::new() });
                    }
                }
            }
            if !faces.is_empty() {
                out.push(Solid { faces, ext: None, item: id, clipped: false, clips: Vec::new() });
            }
        }
        "IFCPOLYGONALFACESET" => {
            // (Coordinates, Closed, Faces, PnIndex)
            let pts = match e.p(0).r().and_then(|r| point_list(m, r, tf)) {
                Some(p) => p,
                None => return,
            };
            let pn: Vec<i64> = e.p(3).list().map(|l| l.iter().filter_map(|x| x.int()).collect()).unwrap_or_default();
            let at = |i: i64| -> Option<V3> {
                let j = if pn.is_empty() { i } else { *pn.get((i - 1) as usize)? };
                pts.get((j - 1) as usize).copied()
            };
            let mut faces = Vec::new();
            for f in e.p(2).refs() {
                let fe = match m.get(f) {
                    Some(x) => x,
                    None => continue,
                };
                let idx: Vec<i64> = fe.p(0).list().map(|l| l.iter().filter_map(|x| x.int()).collect()).unwrap_or_default();
                let outer: Option<Vec<V3>> = idx.iter().map(|i| at(*i)).collect();
                let mut holes = Vec::new();
                if fe.name == "IFCINDEXEDPOLYGONALFACEWITHVOIDS" {
                    for h in index_list(fe.p(1)) {
                        if let Some(hv) = h.iter().map(|i| at(*i)).collect::<Option<Vec<V3>>>() {
                            holes.push(hv);
                        }
                    }
                }
                if let Some(o) = outer {
                    if o.len() >= 3 {
                        faces.push(Face { outer: o, holes });
                    }
                }
            }
            if !faces.is_empty() {
                out.push(Solid { faces, ext: None, item: id, clipped: false, clips: Vec::new() });
            }
        }
        "IFCBOOLEANCLIPPINGRESULT" | "IFCBOOLEANRESULT" => {
            // (Operator, FirstOperand, SecondOperand): the first operand, its clips noted
            let first = match e.p(1).r() {
                Some(r) => r,
                None => return,
            };
            let mut inner = Vec::new();
            item_solids(m, first, tf, &mut inner, depth + 1);
            let op = e.p(0).enm().unwrap_or("");
            let mut clips = Vec::new();
            if op == "DIFFERENCE" {
                if let Some(sec) = e.p(2).r() {
                    if let Some(h) = half_space(m, sec, tf) {
                        clips.push(h);
                    }
                }
            }
            for mut s in inner {
                s.clipped = true;
                s.clips.extend(clips.iter().copied());
                out.push(s);
            }
        }
        "IFCMAPPEDITEM" => {
            // (MappingSource: IfcRepresentationMap(MappingOrigin, MappedRepresentation), MappingTarget)
            let src = match e.p(0).r().and_then(|r| m.get(r)) {
                Some(s) => s,
                None => return,
            };
            let origin = src.p(0).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID);
            let target = e.p(1).r().map(|r| operator(m, r)).unwrap_or(Tf::ID);
            let t2 = tf.then(&target).then(&origin);
            if let Some(rep) = src.p(1).r().and_then(|r| m.get(r)) {
                for it in rep.p(3).refs() {
                    item_solids(m, it, &t2, out, depth + 1);
                }
            }
        }
        _ => {}
    }
}

/// A half space solid as a plane (a point, and the normal out of what is kept).
fn half_space(m: &Model, id: u64, tf: &Tf) -> Option<(V3, V3)> {
    let e = m.get(id)?;
    match e.name.as_str() {
        "IFCHALFSPACESOLID" | "IFCPOLYGONALBOUNDEDHALFSPACE" | "IFCBOXEDHALFSPACE" => {
            // (BaseSurface: IfcPlane(Position), AgreementFlag, …)
            let pl = m.get(e.p(0).r()?)?;
            if pl.name != "IFCPLANE" {
                return None;
            }
            let ptf = tf.then(&pl.p(0).r().map(|r| axis_placement(m, r)).unwrap_or(Tf::ID));
            let n = unit(ptf.z);
            // AgreementFlag true: the half space is on the side the normal points to; it is
            // taken away, so what is kept lies behind the plane
            let agree = e.p(1).boolean().unwrap_or(true);
            Some((ptf.t, if agree { n } else { mul(n, -1.0) }))
        }
        _ => None,
    }
}

/// The solids of a product's representation of an identifier (`Body`, `Axis`…), its local
/// placement applied.
pub fn rep_items(m: &Model, product: &Entity, ident: &str) -> Vec<u64> {
    let mut out = Vec::new();
    let pds = match product.p(6).r().and_then(|r| m.get(r)) {
        Some(p) => p,
        None => return out,
    };
    for rep in pds.p(2).refs() {
        let re = match m.get(rep) {
            Some(r) => r,
            None => continue,
        };
        let id_ok = re.p(1).str().map(|s| s.eq_ignore_ascii_case(ident)).unwrap_or(false);
        if id_ok {
            out.push(rep);
        }
    }
    out
}

/// A product's body: the solids of its `Body` representation (or, without one, of any
/// representation that has solids), in the project's coordinates.
pub fn body(m: &Model, pid: u64) -> Vec<Solid> {
    let e = match m.get(pid) {
        Some(e) => e,
        None => return Vec::new(),
    };
    let tf = e.p(5).r().map(|r| placement(m, r)).unwrap_or(Tf::ID);
    let mut out = Vec::new();
    for rep in rep_items(m, e, "Body") {
        if let Some(re) = m.get(rep) {
            for it in re.p(3).refs() {
                item_solids(m, it, &tf, &mut out, 0);
            }
        }
    }
    out
}

/// The world placement of a product.
pub fn product_tf(m: &Model, pid: u64) -> Tf {
    m.get(pid).and_then(|e| e.p(5).r()).map(|r| placement(m, r)).unwrap_or(Tf::ID)
}

/// A product's `Axis` curve in the project's coordinates.
pub fn axis_curve(m: &Model, pid: u64) -> Option<Vec<V3>> {
    let e = m.get(pid)?;
    let tf = product_tf(m, pid);
    for rep in rep_items(m, e, "Axis") {
        let re = m.get(rep)?;
        for it in re.p(3).refs() {
            if let Some(pts) = curve(m, it) {
                if pts.len() >= 2 {
                    return Some(pts.into_iter().map(|p| tf.apply(p)).collect());
                }
            }
        }
    }
    None
}

/// The bounding box of points: (min, max).
pub fn bbox<'a>(pts: impl Iterator<Item = &'a V3>) -> Option<(V3, V3)> {
    let mut lo = [f64::INFINITY; 3];
    let mut hi = [f64::NEG_INFINITY; 3];
    let mut any = false;
    for p in pts {
        any = true;
        for k in 0..3 {
            lo[k] = lo[k].min(p[k]);
            hi[k] = hi[k].max(p[k]);
        }
    }
    if any {
        Some((lo, hi))
    } else {
        None
    }
}
