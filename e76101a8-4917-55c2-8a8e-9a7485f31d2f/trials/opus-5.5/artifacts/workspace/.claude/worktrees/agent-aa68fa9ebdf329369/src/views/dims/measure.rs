//! What a dimension measures: its references laid along the way it runs (an aligned or linear
//! one's stations), the angle between two lines, a radius, a diameter or an arc's length; and the
//! model's rules for it, in the order the original checks them.

use super::geom::{self, *};
use super::refs::{self, End, Face, Ref, Target};
use super::super::common::*;
use crate::json::Value;
use crate::project::Project;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Aligned,
    Linear,
    Angular,
    Radial,
    Diameter,
    ArcLength,
}

impl Kind {
    pub fn parse(s: &str) -> Option<Kind> {
        Some(match s {
            "aligned" => Kind::Aligned,
            "linear" => Kind::Linear,
            "angular" => Kind::Angular,
            "radial" => Kind::Radial,
            "diameter" => Kind::Diameter,
            "arc_length" => Kind::ArcLength,
            _ => return None,
        })
    }
    pub fn word(self) -> &'static str {
        match self {
            Kind::Aligned => "aligned",
            Kind::Linear => "linear",
            Kind::Angular => "angular",
            Kind::Radial => "radial",
            Kind::Diameter => "diameter",
            Kind::ArcLength => "arc_length",
        }
    }
    /// As the original's messages name it (its Debug).
    pub fn name(self) -> &'static str {
        match self {
            Kind::Aligned => "Aligned",
            Kind::Linear => "Linear",
            Kind::Angular => "Angular",
            Kind::Radial => "Radial",
            Kind::Diameter => "Diameter",
            Kind::ArcLength => "ArcLength",
        }
    }
    /// Whether it lays its references along a line (aligned or linear).
    pub fn along(self) -> bool {
        matches!(self, Kind::Aligned | Kind::Linear)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Orient {
    Horizontal,
    Vertical,
}

impl Orient {
    pub fn parse(s: &str) -> Option<Orient> {
        match s {
            "horizontal" => Some(Orient::Horizontal),
            "vertical" => Some(Orient::Vertical),
            _ => None,
        }
    }
    pub fn word(self) -> &'static str {
        match self {
            Orient::Horizontal => "horizontal",
            Orient::Vertical => "vertical",
        }
    }
    /// The way a dimension of it measures.
    pub fn axis(self) -> P {
        match self {
            Orient::Horizontal => [1.0, 0.0],
            Orient::Vertical => [0.0, 1.0],
        }
    }
}

/// A dimension as the checks and the measuring read it.
#[derive(Clone, Debug)]
pub struct Dim {
    pub id: u64,
    pub kind: Kind,
    pub orient: Option<Orient>,
    pub refs: Vec<Ref>,
    pub at: P,
}

impl Dim {
    pub fn from_element(id: u64, e: &Value) -> Dim {
        Dim {
            id,
            kind: s_of(e, "kind").and_then(Kind::parse).unwrap_or(Kind::Aligned),
            orient: s_of(e, "orient").and_then(Orient::parse),
            refs: refs::refs_of(e),
            at: pt_of(e, "at").unwrap_or([0.0, 0.0]),
        }
    }
}

/// The walls joined, worked out once for all the dimensions a check or a command measures.
pub struct Ctx<'a> {
    pub pr: &'a Project,
    walls: std::cell::OnceCell<Vec<Wall>>,
}

impl<'a> Ctx<'a> {
    pub fn new(pr: &'a Project) -> Ctx<'a> {
        Ctx { pr, walls: std::cell::OnceCell::new() }
    }
    pub fn walls(&self) -> &Vec<Wall> {
        self.walls.get_or_init(|| geom::walls(self.pr))
    }
    pub fn wall(&self, id: u64) -> Option<&Wall> {
        self.walls().iter().find(|w| w.id() == id)
    }
}

/// What a reference is, in plan, for a dimension laying its references along a line.
#[derive(Clone, Copy, Debug)]
pub enum Geo {
    /// A line (its two ends, the way it runs from the first).
    Line(P, P),
    Point(P),
}

/// The line or point a reference of an aligned, linear or angular dimension is to, else why not.
pub fn ref_geo(cx: &Ctx, r: &Ref) -> Result<Geo, String> {
    let pr = cx.pr;
    let Some(id) = r.id(pr) else {
        return Err(format!("element {} doesn't exist", r.guid()));
    };
    let e = pr.el(id).unwrap();
    let c = cat(e);
    let g = || refs::named_guid(pr, r);
    let pick = |l: (P, P)| -> Geo {
        match r.point {
            None => Geo::Line(l.0, l.1),
            Some(End::Start) => Geo::Point(l.0),
            Some(End::End) => Geo::Point(l.1),
        }
    };
    match c {
        "wall" => {
            let w = cx.wall(id).ok_or_else(|| format!("element {} doesn't exist", r.guid()))?;
            let curved = !w.b.straight();
            match r.face {
                Face::Centre | Face::Left | Face::Right => {
                    if curved && r.point.is_none() {
                        return Err(format!("{}'s faces are arcs; measure to its start or its end, or its radius", g()));
                    }
                    let l = match r.face {
                        Face::Centre => (w.b.cl.start, w.b.cl.end),
                        Face::Left => w.left,
                        _ => w.right,
                    };
                    Ok(pick(l))
                }
                Face::Start => Ok(pick(w.sface)),
                Face::End => Ok(pick(w.eface)),
            }
        }
        "door" | "window" => {
            if matches!(r.face, Face::Left | Face::Right) {
                return Err(format!("{} has a centre and two jambs, start and end; measure to one of those", g()));
            }
            let (_, ls) = geom::opening_lines(pr, id).ok_or_else(|| format!("{} has a centre and two jambs, start and end; measure to one of those", g()))?;
            let l = match r.face {
                Face::Start => ls[1],
                Face::End => ls[2],
                _ => ls[0],
            };
            Ok(pick(l))
        }
        "grid" => {
            if r.face != Face::Centre {
                return Err(format!("{} has no faces; measure to its line", g()));
            }
            let a = pt_of(e, "start").unwrap_or([0.0, 0.0]);
            let b = pt_of(e, "end").unwrap_or([0.0, 0.0]);
            Ok(pick((a, b)))
        }
        "line" => {
            let Some(shape) = geom::line_shape(e) else {
                return Err(format!("{} has a line and two ends; measure to one of those", g()));
            };
            if r.face == Face::Centre && r.point.is_some() {
                let (a, b) = shape.ends();
                return Ok(Geo::Point(if r.point == Some(End::Start) { a } else { b }));
            }
            let LineShape::Line(a, b) = shape else {
                return Err(format!("{} is a {}; dimensions measure to straight ones (and radial ones to circles and arcs)", g(), shape.word()));
            };
            match r.face {
                Face::Left | Face::Right => Err(format!("{} has a line and two ends; measure to one of those", g())),
                Face::Centre => Ok(pick((a, b))),
                _ => {
                    // the line square to it at that end, 100 mm each way, from its right to its left
                    let d = unit(sub(b, a));
                    let n = mul(left_of(d), 100.0);
                    let p = if r.face == Face::Start { a } else { b };
                    Ok(pick((sub(p, n), add(p, n))))
                }
            }
        }
        _ => Err(format!("{} isn't a wall, a door, a window, a grid or a detail line", g())),
    }
}

/// How messages name the element of a reference: "wall 100002".
fn nm(pr: &Project, r: &Ref) -> String {
    refs::named(pr, r)
}

/// A dimension laid along a line: the way it runs, and each reference's station along it.
#[derive(Clone, Debug)]
pub struct Laid {
    /// The way it measures (east or north), a unit vector.
    pub dir: P,
    /// (station, the reference's index), in order along `dir`.
    pub stations: Vec<(f64, usize)>,
}

impl Laid {
    pub fn values(&self) -> Vec<f64> {
        self.stations.windows(2).map(|w| w[1].0 - w[0].0).collect()
    }
}

/// A unit vector made to point east (or north, where it points neither east nor west).
pub fn eastward(d: P) -> P {
    if d[0] > 1e-9 || (d[0].abs() <= 1e-9 && d[1] >= 0.0) {
        d
    } else {
        [-d[0], -d[1]]
    }
}

/// The count of references each kind takes, and what it says otherwise.
fn count_rule(d: &Dim) -> Result<(), String> {
    let n = d.refs.len();
    let ok = match d.kind {
        Kind::Aligned | Kind::Linear => (2..=10000).contains(&n),
        Kind::Angular => n == 2,
        Kind::Radial | Kind::Diameter => n == 1,
        Kind::ArcLength => n == 1 || n == 3,
    };
    if ok {
        return Ok(());
    }
    Err(match d.kind {
        Kind::Aligned | Kind::Linear => "a dimension measures between 2 to 10000 references".into(),
        Kind::Angular => "an angular dimension measures between two lines".into(),
        Kind::Radial => "a radial dimension measures one round element".into(),
        Kind::Diameter => "a diameter dimension measures one round element".into(),
        Kind::ArcLength => "an arc length dimension measures along one arc, all of it or between two points on it".into(),
    })
}

/// The rules a dimension holds to, after its type's, and what it measures: its values (the
/// segments, an angle in degrees, a radius, a diameter or a length), unrounded. The error is the
/// reason only (the caller says which dimension).
pub fn measure(cx: &Ctx, d: &Dim) -> Result<Vec<f64>, String> {
    count_rule(d)?;
    if d.orient.is_some() && d.kind != Kind::Linear {
        return Err(format!("only a linear dimension has an `orient`; this one is {}", d.kind.name()));
    }
    match d.kind {
        Kind::Aligned | Kind::Linear => Ok(lay(cx, d)?.values()),
        Kind::Angular => Ok(vec![angle(cx, d)?]),
        Kind::Radial | Kind::Diameter => {
            let r = radius(cx, d)?;
            Ok(vec![if d.kind == Kind::Diameter { 2.0 * r } else { r }])
        }
        Kind::ArcLength => Ok(vec![arc_length(cx, d)?]),
    }
}

/// An aligned or linear dimension's references laid along the way it measures.
pub fn lay(cx: &Ctx, d: &Dim) -> Result<Laid, String> {
    let pr = cx.pr;
    let mut geos: Vec<Geo> = Vec::new();
    let mut first: Option<(usize, P)> = None;
    for (i, r) in d.refs.iter().enumerate() {
        let g = ref_geo(cx, r)?;
        if d.refs[..i].iter().any(|o| o.same(r)) {
            return Err(format!("it measures to {}'s {} twice", nm(pr, r), refs::what(r)));
        }
        if let Geo::Line(a, b) = g {
            let u = unit(sub(b, a));
            if d.kind == Kind::Linear {
                let o = d.orient.unwrap_or(Orient::Horizontal);
                // its lines run square to the way it measures
                if cross(u, left_of(o.axis())).abs() > PARALLEL {
                    return Err(format!(
                        "{} isn't square to a {} dimension; measure to its ends, or make the dimension aligned",
                        nm(pr, r),
                        o.word()
                    ));
                }
            } else {
                match first {
                    None => first = Some((i, u)),
                    Some((k, f)) => {
                        if cross(u, f).abs() > PARALLEL {
                            return Err(format!(
                                "{} isn't parallel to {}; a dimension measures between parallel walls and grids",
                                nm(pr, r),
                                nm(pr, &d.refs[k])
                            ));
                        }
                    }
                }
            }
        }
        geos.push(g);
    }
    let dir = match (d.kind, first) {
        (Kind::Linear, _) => d.orient.unwrap_or(Orient::Horizontal).axis(),
        (_, Some((_, u))) => eastward(left_of(u)),
        (_, None) => {
            let pts: Vec<P> = geos.iter().map(|g| if let Geo::Point(p) = g { *p } else { [0.0, 0.0] }).collect();
            let Some(&p0) = pts.first() else { return Err("its points are all in one place, so it has no way to run".into()) };
            match pts.iter().skip(1).find(|p| dist(**p, p0) > 1e-9) {
                Some(p) => eastward(unit(sub(*p, p0))),
                None => return Err("its points are all in one place, so it has no way to run".into()),
            }
        }
    };
    let at = d.at;
    let mut st: Vec<(f64, usize)> = geos
        .iter()
        .enumerate()
        .map(|(i, g)| {
            // how far along the dimension's line, from `at`, a point is; a line, where the
            // dimension's line (through `at` along the way it measures) crosses it
            let s = match g {
                Geo::Point(p) => dot(sub(*p, at), dir),
                Geo::Line(a, b) => {
                    let u = sub(*b, *a);
                    let den = cross(dir, u);
                    if den.abs() < 1e-12 {
                        dot(sub(*a, at), dir)
                    } else {
                        let x = add(at, mul(dir, cross(sub(*a, at), u) / den));
                        dot(sub(x, at), dir)
                    }
                }
            };
            (s, i)
        })
        .collect();
    st.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    Ok(Laid { dir, stations: st })
}

/// An angular dimension's angle, degrees, on the side of `at`.
fn angle(cx: &Ctx, d: &Dim) -> Result<f64, String> {
    let pr = cx.pr;
    let mut lines: Vec<(P, P)> = Vec::new();
    for (i, r) in d.refs.iter().enumerate() {
        if r.point.is_some() {
            return Err(format!("it measures to an end of {}; an angle is between two lines", nm(pr, r)));
        }
        let g = ref_geo(cx, r)?;
        if d.refs[..i].iter().any(|o| o.same(r)) {
            return Err(format!("it measures to {}'s {} twice", nm(pr, r), refs::what(r)));
        }
        match g {
            Geo::Point(_) => return Err(format!("it measures to an end of {}; an angle is between two lines", nm(pr, r))),
            Geo::Line(a, b) => {
                if let Some((fa, fb)) = lines.first() {
                    let f = unit(sub(*fb, *fa));
                    let u = unit(sub(b, a));
                    if cross(f, u).abs() <= PARALLEL {
                        return Err(format!("{} is parallel to {}; an angle is between lines that meet", nm(pr, r), nm(pr, &d.refs[0])));
                    }
                }
                lines.push((a, b));
            }
        }
    }
    let (a1, b1) = lines[0];
    let (a2, b2) = lines[1];
    let d1 = unit(sub(b1, a1));
    let d2 = unit(sub(b2, a2));
    let x = line_meet(a1, d1, a2, d2).unwrap_or(a1);
    let v = sub(d.at, x);
    // `at` as a sum of the two lines' ways: its signs pick the sector
    let den = cross(d1, d2);
    let s1 = cross(v, d2) / den;
    let s2 = cross(d1, v) / den;
    let r1 = mul(d1, s1.signum());
    let r2 = mul(d2, s2.signum());
    let c = dot(r1, r2).clamp(-1.0, 1.0);
    Ok(c.acos().to_degrees())
}

/// What is round: (centre, radius) of a radial or diameter dimension's reference.
fn radius(cx: &Ctx, d: &Dim) -> Result<f64, String> {
    let pr = cx.pr;
    let r = &d.refs[0];
    let Some(id) = r.id(pr) else {
        return Err(format!("element {} doesn't exist", r.guid()));
    };
    let e = pr.el(id).unwrap();
    let what = if d.kind == Kind::Diameter { "a diameter dimension" } else { "a radial dimension" };
    let g = refs::named_guid(pr, r);
    match cat(e) {
        "wall" => {
            let w = cx.wall(id).ok_or_else(|| format!("element {} doesn't exist", r.guid()))?;
            if w.b.straight() {
                return Err(format!("{} is straight; {} measures round columns and curved walls", g, what));
            }
            let off = match r.face {
                Face::Left => w.b.t / 2.0,
                Face::Right => -w.b.t / 2.0,
                _ => 0.0,
            };
            match w.b.carrier(off) {
                Carrier::Circle { r, .. } => Ok(r),
                _ => Ok(0.0),
            }
        }
        "line" => {
            let shape = geom::line_shape(e);
            match shape {
                Some(LineShape::Circle { r, .. }) | Some(LineShape::Arc { r, .. }) => Ok(r),
                Some(s) => Err(format!("{} is a {}; {} measures round columns and curved walls, circles and arcs", g, s.word(), what)),
                None => Err(format!("{} is a line; {} measures round columns and curved walls, circles and arcs", g, what)),
            }
        }
        _ => match geom::round_column(pr, e) {
            Some((_, rad)) => Ok(rad),
            None => Err(format!("{} isn't round; {} measures round columns and curved walls", g, what)),
        },
    }
}

/// The arc an arc length dimension measures along: centre, radius, start angle, sweep (radians).
fn the_arc(cx: &Ctx, r: &Ref) -> Result<(P, f64, f64, f64), String> {
    let pr = cx.pr;
    let Some(id) = r.id(pr) else {
        return Err(format!("element {} doesn't exist", r.guid()));
    };
    let e = pr.el(id).unwrap();
    let g = refs::named_guid(pr, r);
    const TAIL: &str = "an arc length dimension measures along curved walls and arcs";
    match cat(e) {
        "wall" => {
            let w = cx.wall(id).ok_or_else(|| format!("element {} doesn't exist", r.guid()))?;
            let Some((c, _, a0, sweep)) = w.b.circle() else {
                return Err(format!("{} is straight; {}", g, TAIL));
            };
            let off = match r.face {
                Face::Centre => 0.0,
                Face::Left => w.b.t / 2.0,
                Face::Right => -w.b.t / 2.0,
                _ => return Err(format!("{}'s ends are straight; {}", g, TAIL)),
            };
            match w.b.carrier(off) {
                Carrier::Circle { r, .. } => Ok((c, r, a0, sweep)),
                _ => Ok((c, 0.0, a0, sweep)),
            }
        }
        "line" => match geom::line_shape(e) {
            Some(LineShape::Arc { c, r, a0, sweep, .. }) => Ok((c, r, a0, sweep)),
            Some(LineShape::Circle { .. }) => Err(format!("{} is a circle, which has no ends; {}", g, TAIL)),
            Some(s) => Err(format!("{} is a {}; {}", g, s.word(), TAIL)),
            None => Err(format!("{} is a line; {}", g, TAIL)),
        },
        _ => Err(format!("{} isn't curved; {}", g, TAIL)),
    }
}

/// The fraction of an arc's sweep a point on its circle lies at (None: not on the arc).
fn on_arc(arc: (P, f64, f64, f64), p: P) -> Option<f64> {
    let (c, r, a0, sweep) = arc;
    let l = dist(p, c);
    if (l - r).abs() > 1e-3_f64.max(r * 1e-9) {
        return None;
    }
    let a = (p[1] - c[1]).atan2(p[0] - c[0]);
    let f = if sweep > 0.0 { wrap(a - a0) / sweep } else { wrap(a0 - a) / -sweep };
    let tol = 1e-9;
    if f <= 1.0 + tol {
        return Some(f.min(1.0));
    }
    // just short of a whole turn back to the start
    if (f * sweep.abs() - std::f64::consts::TAU).abs() < 1e-6 {
        return Some(0.0);
    }
    None
}

fn arc_length(cx: &Ctx, d: &Dim) -> Result<f64, String> {
    let pr = cx.pr;
    let arc = the_arc(cx, &d.refs[0])?;
    let whole = arc.1 * arc.3.abs();
    if d.refs.len() == 1 {
        return Ok(whole);
    }
    let mut fs = Vec::new();
    for r in d.refs.iter().skip(1) {
        if r.point.is_none() {
            return Err(format!("{} is measured to as a line", nm(pr, r)));
        }
        let g = ref_geo(cx, r)?;
        match g {
            Geo::Line(..) => return Err(format!("{} is measured to as a line", nm(pr, r))),
            Geo::Point(p) => match on_arc(arc, p) {
                Some(f) => fs.push(f),
                None => {
                    let end = r.point.unwrap_or(End::Start).word();
                    return Err(format!("{}'s {} isn't on the arc it measures along", nm(pr, r), end));
                }
            },
        }
    }
    Ok(whole * (fs[1] - fs[0]).abs())
}

/// A value as `values` gives it: to the hundredth.
pub fn r2(x: f64) -> f64 {
    let y = (x * 100.0).round() / 100.0;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

/// Whether a reference is to the target (the element of that GUID).
pub fn refers_to(r: &Ref, g: &str) -> bool {
    matches!(&r.target, Target::Guid(x) if x == g)
}
