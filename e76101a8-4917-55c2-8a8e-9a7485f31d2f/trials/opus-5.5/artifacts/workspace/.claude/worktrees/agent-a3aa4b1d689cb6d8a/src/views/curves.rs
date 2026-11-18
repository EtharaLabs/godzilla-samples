//! A detail line's curve: a polyline of straight segments and arcs (a line or an arc is one of two
//! points), a circle, an ellipse whole or partial, a spline by its control points (a clamped
//! B-spline, uniform knots unless it holds its own) or a spline through points (a cubic by the
//! distance along them, each end free or leaving along a tangent).
//!
//! In a file and in a command a curve is flat, the fields of its shape: `start`, `end` (and `arc`);
//! `points`, `arcs`, `closed`; `centre`, `radius`; `centre`, `radii`, `angle`, `span`; `control`,
//! `knots`; `fit`, `start_tangent`, `end_tangent`. [`parse`] reads them (with the original's
//! errors), [`Curve::put_fields`] writes them back in the file's order.
//!
//! A curve is drawn with chords no further than [`FLAT`] from it ([`Curve::pieces`],
//! [`Curve::points`]); [`Curve::nearest`] finds where it passes nearest a point (on those chords,
//! polished on the curve itself where that comes nearer), [`Curve::split_at`] cuts it there,
//! [`Curve::map`] moves, turns or mirrors it, and the rest measure it ([`Curve::length`],
//! [`Curve::bounds`], [`Curve::ends`]) or change it (vertices, offsets, trimming).

use crate::json::{Map, Value};
use std::f64::consts::PI;

pub type P2 = [f64; 2];
pub type R<T> = Result<T, String>;

/// How far a chord drawn for a curve strays from it at most, mm.
pub const FLAT: f64 = 0.25;
/// How near a spline through points fitted to another curve keeps to it, mm.
pub const FIT_TOL: f64 = 0.05;
/// The most points a polyline's arcs add to draw it, and an ellipse is drawn with.
pub const MAX_DRAWN: usize = 8192;
/// How far from the origin a curve reaches, mm.
pub const REACH: f64 = 1e9;
/// The largest angle (an ellipse's `angle` and `span`), degrees.
pub const MAX_DEGREES: f64 = 1e6;
/// An arc is drawn in steps of at most this many degrees.
pub const ARC_STEP: f64 = 5.0;
/// A curve is longer than this, mm.
pub const MIN_LENGTH: f64 = 1.0;
/// The sharpest corner of a polyline an offset mitres (radians): sharper, it folds over itself.
pub const FOLD_ANGLE: f64 = 0.03998667683719012;

/// The curve's fields, in the order a command lists them.
pub const KEYS: &[&str] = &[
    "start", "end", "through", "arc", "points", "arcs", "closed", "centre", "radius", "radii", "angle", "span", "control",
    "knots", "fit", "start_tangent", "end_tangent",
];

/// What a curve is, as the errors about one say.
pub const GENERIC: &str = "a line is `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

// ---------------------------------------------------------------- vectors

pub fn add(a: P2, b: P2) -> P2 {
    [a[0] + b[0], a[1] + b[1]]
}
pub fn sub(a: P2, b: P2) -> P2 {
    [a[0] - b[0], a[1] - b[1]]
}
pub fn mul(a: P2, k: f64) -> P2 {
    [a[0] * k, a[1] * k]
}
pub fn dot(a: P2, b: P2) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
pub fn cross(a: P2, b: P2) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
pub fn norm(a: P2) -> f64 {
    (a[0] * a[0] + a[1] * a[1]).sqrt()
}
pub fn dist(a: P2, b: P2) -> f64 {
    norm(sub(b, a))
}
pub fn mid(a: P2, b: P2) -> P2 {
    [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]
}
pub fn lerp(a: P2, b: P2, t: f64) -> P2 {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}
pub fn unit(a: P2) -> P2 {
    let l = norm(a);
    if l == 0.0 {
        [0.0, 0.0]
    } else {
        let k = 1.0 / l;
        [a[0] * k, a[1] * k]
    }
}
/// The unit normal to the left of the way from `a` to `b`.
pub fn left_normal(a: P2, b: P2) -> P2 {
    let d = unit(sub(b, a));
    [-d[1], d[0]]
}
/// A point turned `t` radians counter-clockwise about `c`.
pub fn turn_about(p: P2, c: P2, t: f64) -> P2 {
    let (s, co) = t.sin_cos();
    let d = sub(p, c);
    [c[0] + d[0] * co - d[1] * s, c[1] + d[0] * s + d[1] * co]
}
/// A point mirrored across the line through `a` and `b`.
pub fn mirror_point(p: P2, a: P2, b: P2) -> P2 {
    let d = unit(sub(b, a));
    let v = sub(p, a);
    let along = dot(v, d);
    let foot = add(a, mul(d, along));
    sub(mul(foot, 2.0), p)
}
/// The distance from `p` to the segment from `a` to `b`.
pub fn dist_to_segment(p: P2, a: P2, b: P2) -> f64 {
    let d = sub(b, a);
    let l2 = dot(d, d);
    if l2 == 0.0 {
        return dist(p, a);
    }
    let s = (dot(sub(p, a), d) / l2).clamp(0.0, 1.0);
    dist(p, lerp(a, b, s))
}

/// A length rounded to the micron, as the original keeps the points it works out.
pub fn r3(x: f64) -> f64 {
    let y = (x * 1000.0).round() / 1000.0;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}
pub fn r3p(p: P2) -> P2 {
    [r3(p[0]), r3(p[1])]
}
/// An arc's turn rounded as the original keeps one it works out (to 1e-9 degrees).
pub fn r9(x: f64) -> f64 {
    let y = (x * 1e9).round() / 1e9;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}
/// A float as Rust's Display shows it in messages.
pub fn disp(x: f64) -> String {
    format!("{}", x)
}
/// A point as the messages show it: "[500, 100.001]".
pub fn disp_point(p: P2) -> String {
    format!("[{}, {}]", p[0], p[1])
}

fn within(p: P2) -> bool {
    p[0].is_finite() && p[1].is_finite() && p[0].abs() <= REACH && p[1].abs() <= REACH
}

// ---------------------------------------------------------------- arcs

/// An arc of a polyline: its circle, where it starts on it and how far it turns (radians,
/// counter-clockwise).
#[derive(Clone, Copy, Debug)]
pub struct ArcGeo {
    pub centre: P2,
    pub radius: f64,
    /// The angle of its start about the centre, radians.
    pub start: f64,
    /// Its turn, radians, counter-clockwise.
    pub turn: f64,
}

impl ArcGeo {
    pub fn at(&self, f: f64) -> P2 {
        let a = self.start + self.turn * f;
        [self.centre[0] + self.radius * a.cos(), self.centre[1] + self.radius * a.sin()]
    }
    pub fn length(&self) -> f64 {
        self.radius * self.turn.abs()
    }
    /// How many chords draw it: no further than FLAT from it, in steps of at most ARC_STEP degrees.
    pub fn chords(&self) -> usize {
        let step = 2.0 * (1.0 - FLAT / self.radius).acos();
        let by_flat = (self.turn.abs() / step).ceil();
        let by_step = (self.turn.abs().to_degrees() / ARC_STEP).ceil();
        let n = by_flat.max(by_step).max(1.0);
        if n.is_finite() {
            n as usize
        } else {
            1
        }
    }
}

/// Whether a turn of this many degrees is straight (under a nanoradian).
pub fn is_straight(deg: f64) -> bool {
    deg.abs() <= 1e-9f64.to_degrees()
}

/// The arc from `a` to `b` turning `deg` degrees counter-clockwise (None: straight).
pub fn arc_geo(a: P2, b: P2, deg: f64) -> Option<ArcGeo> {
    if is_straight(deg) {
        return None;
    }
    let t = deg.to_radians();
    let c = dist(a, b);
    if c == 0.0 {
        return None;
    }
    let r = c / (2.0 * (t / 2.0).sin().abs());
    let m = mid(a, b);
    // how far the centre is from the chord's middle, to its left for a counter-clockwise turn
    let s = if t > 0.0 { 1.0 } else { -1.0 };
    let h = (c / 2.0) / (t.abs() / 2.0).tan() * s;
    let n = left_normal(a, b);
    let centre = [m[0] + n[0] * h, m[1] + n[1] * h];
    let start = (a[1] - centre[1]).atan2(a[0] - centre[0]);
    Some(ArcGeo { centre, radius: r, start, turn: t })
}

/// The turn of the arc from `s` to `e` through `t`, degrees (0: as good as straight).
pub fn arc_through(s: P2, e: P2, t: P2) -> f64 {
    if dist_to_segment(t, s, e) <= 1.0 {
        return 0.0;
    }
    let u = sub(s, t);
    let v = sub(e, t);
    let cr = cross(u, v);
    if cr.abs() <= 1e-9 * norm(u) * norm(v) {
        return 0.0;
    }
    let inscribed = cr.abs().atan2(dot(u, v));
    let deg = (2.0 * (PI - inscribed)).to_degrees();
    if cross(sub(e, s), sub(t, s)) > 0.0 {
        -deg
    } else {
        deg
    }
}

// ---------------------------------------------------------------- the curve

#[derive(Clone, Debug, PartialEq)]
pub enum Curve {
    /// Straight segments and arcs: `arcs`, when not empty, holds the turn (degrees
    /// counter-clockwise) of each segment, the closing one last.
    Polyline { points: Vec<P2>, arcs: Vec<f64>, closed: bool },
    Circle { centre: P2, radius: f64 },
    /// `radii` along the ellipse's own axes, turned `angle` degrees; `span` the part of it from one
    /// angle to another (degrees of its parameter), counter-clockwise.
    Ellipse { centre: P2, radii: [f64; 2], angle: f64, span: Option<[f64; 2]> },
    Spline { control: Vec<P2>, knots: Option<Vec<f64>> },
    Fitted { fit: Vec<P2>, start_tangent: Option<P2>, end_tangent: Option<P2> },
}

/// A segment of a polyline.
#[derive(Clone, Copy, Debug)]
pub struct Seg {
    pub a: P2,
    pub b: P2,
    /// Its turn, degrees counter-clockwise (0: straight).
    pub arc: f64,
}

impl Seg {
    pub fn geo(&self) -> Option<ArcGeo> {
        arc_geo(self.a, self.b, self.arc)
    }
    pub fn at(&self, f: f64) -> P2 {
        match self.geo() {
            Some(g) => g.at(f),
            None => lerp(self.a, self.b, f),
        }
    }
    pub fn length(&self) -> f64 {
        match self.geo() {
            Some(g) => g.length(),
            None => dist(self.a, self.b),
        }
    }
    /// The fractions of it it is drawn at, and the points.
    pub fn drawn(&self) -> Vec<(f64, P2)> {
        match self.geo() {
            None => vec![(0.0, self.a), (1.0, self.b)],
            Some(g) => {
                let n = g.chords();
                (0..=n)
                    .map(|k| {
                        let f = k as f64 / n as f64;
                        let a = g.start + g.turn * k as f64 / n as f64;
                        (f, [g.centre[0] + g.radius * a.cos(), g.centre[1] + g.radius * a.sin()])
                    })
                    .collect()
            }
        }
    }
    /// The part from fraction `f0` to `f1` (an arc keeps its circle).
    pub fn part(&self, f0: f64, f1: f64) -> Seg {
        Seg { a: self.at(f0), b: self.at(f1), arc: self.arc * (f1 - f0) }
    }
}

/// A run of points a curve is drawn with, each with its parameter: the fraction along a polyline's
/// segment `seg`, the fraction of an ellipse's span (or of a circle), a spline's knot parameter.
#[derive(Clone, Debug)]
pub struct Piece {
    pub seg: usize,
    pub pts: Vec<(f64, P2)>,
}

/// Where a curve passes nearest a point.
#[derive(Clone, Copy, Debug)]
pub struct Near {
    /// The polyline's segment (0 for the other shapes).
    pub seg: usize,
    /// The parameter: the fraction along the segment, of the span, or the spline's knot parameter.
    pub f: f64,
    /// The parameter as the search for it runs: a polyline's segment and fraction as one number
    /// (the segment's index plus the fraction), a circle's or an ellipse's angle in degrees, a
    /// spline's knot parameter.
    pub param: f64,
    pub point: P2,
    /// How far the point given is from the curve as drawn.
    pub dist: f64,
}

/// What the search for the nearest point narrows its bracket by each time (the golden section).
pub const GOLDEN: f64 = 0.618033988749895;
/// How many times it narrows.
pub const NARROWINGS: usize = 40;

impl Curve {
    /// A line from `a` to `b`.
    pub fn line(a: P2, b: P2) -> Curve {
        Curve::Polyline { points: vec![a, b], arcs: Vec::new(), closed: false }
    }
    /// An arc from `a` to `b` turning `deg` degrees counter-clockwise (a line if straight).
    pub fn arc(a: P2, b: P2, deg: f64) -> Curve {
        let arcs = if deg == 0.0 { Vec::new() } else { vec![deg] };
        Curve::Polyline { points: vec![a, b], arcs, closed: false }
    }
    pub fn polyline(points: Vec<P2>, arcs: Vec<f64>, closed: bool) -> Curve {
        let arcs = if arcs.iter().all(|a| *a == 0.0) { Vec::new() } else { arcs };
        Curve::Polyline { points, arcs, closed }
    }

    /// What `elements` calls its shape: line, arc, polyline, circle, ellipse, partial ellipse,
    /// spline, fitted spline.
    pub fn shape(&self) -> &'static str {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                if points.len() == 2 && !*closed {
                    if arcs.first().map(|a| *a != 0.0).unwrap_or(false) {
                        "arc"
                    } else {
                        "line"
                    }
                } else {
                    "polyline"
                }
            }
            Curve::Circle { .. } => "circle",
            Curve::Ellipse { span: None, .. } => "ellipse",
            Curve::Ellipse { .. } => "partial ellipse",
            Curve::Spline { .. } => "spline",
            Curve::Fitted { .. } => "fitted spline",
        }
    }

    /// Whether it comes round to where it starts by itself (a closed polyline, a circle, a whole
    /// ellipse).
    pub fn is_closed(&self) -> bool {
        match self {
            Curve::Polyline { closed, .. } => *closed,
            Curve::Circle { .. } => true,
            Curve::Ellipse { span, .. } => span.is_none(),
            _ => false,
        }
    }

    /// A polyline's segments (none for the other shapes).
    pub fn segments(&self) -> Vec<Seg> {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                let n = points.len();
                let m = if *closed { n } else { n.saturating_sub(1) };
                (0..m)
                    .map(|i| Seg { a: points[i], b: points[(i + 1) % n], arc: arcs.get(i).copied().unwrap_or(0.0) })
                    .collect()
            }
            _ => Vec::new(),
        }
    }

    // ------------------------------------------------------------ rounding, checking

    /// The curve as a command keeps it: points to the micron.
    pub fn rounded(&self) -> Curve {
        match self {
            Curve::Polyline { points, arcs, closed } => Curve::Polyline {
                points: points.iter().map(|p| r3p(*p)).collect(),
                arcs: arcs.clone(),
                closed: *closed,
            },
            Curve::Circle { centre, radius } => Curve::Circle { centre: r3p(*centre), radius: *radius },
            Curve::Ellipse { centre, radii, angle, span } => {
                Curve::Ellipse { centre: r3p(*centre), radii: *radii, angle: *angle, span: *span }
            }
            Curve::Spline { control, knots } => {
                Curve::Spline { control: control.iter().map(|p| r3p(*p)).collect(), knots: knots.clone() }
            }
            Curve::Fitted { fit, start_tangent, end_tangent } => Curve::Fitted {
                fit: fit.iter().map(|p| r3p(*p)).collect(),
                start_tangent: *start_tangent,
                end_tangent: *end_tangent,
            },
        }
    }

    /// Its arcs' turns as a command keeps them, to 1e-9 degrees (a turn of none dropped).
    pub fn arcs_rounded(&self) -> Curve {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                Curve::polyline(points.clone(), arcs.iter().map(|a| r9(*a)).collect(), *closed)
            }
            c => c.clone(),
        }
    }

    /// The rules a curve keeps: what the original says of one that breaks them ("it is 1 mm long
    /// or less"…), the first broken in the original's order.
    pub fn check(&self) -> R<()> {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                let n = points.len();
                if n < 2 {
                    return Err(format!("a line needs two points or more, not {}", n));
                }
                if *closed && n == 2 && arcs.is_empty() {
                    return Err("a closed line needs three points or more, or arcs".into());
                }
                if !points.iter().all(|p| within(*p)) {
                    return Err("a point isn't a number within 1000000000 mm".into());
                }
                let segs = self.segments();
                if segs.iter().any(|s| s.a == s.b) {
                    return Err("two points one after another are the same; a line runs between points apart".into());
                }
                if !arcs.is_empty() && arcs.len() != segs.len() {
                    return Err(format!("`arcs` gives one turn for each of its {} segments, not {}", segs.len(), arcs.len()));
                }
                for a in arcs {
                    if !(a.abs() < 360.0) {
                        return Err(format!("an arc turns {}°; it turns less than a whole circle, either way", disp(*a)));
                    }
                }
                let mut extra = 0usize;
                for s in &segs {
                    if let Some(g) = s.geo() {
                        if !(norm(g.centre) + g.radius <= REACH) {
                            return Err("an arc of it is part of a circle that reaches further than 1000000000 mm from the origin: it turns almost nothing, or almost a whole circle, so its circle is huge".into());
                        }
                    }
                }
                for s in &segs {
                    if let Some(g) = s.geo() {
                        extra += g.chords() - 1;
                    }
                }
                if extra > MAX_DRAWN {
                    return Err(format!(
                        "its arcs take more than {} points to draw within {} mm; use fewer, or smaller ones",
                        MAX_DRAWN, FLAT
                    ));
                }
            }
            Curve::Circle { centre, radius } => {
                if !within(*centre) {
                    return Err("its centre isn't a point within 1000000000 mm".into());
                }
                if !(*radius > 1.0 && *radius <= REACH) {
                    return Err(format!("its radius is {} mm; it's more than 1 mm and at most 1000000000", disp(*radius)));
                }
                if !(norm(*centre) + radius <= REACH) {
                    return Err("the circle reaches further than 1000000000 mm from the origin; move it in or make it smaller".into());
                }
            }
            Curve::Ellipse { centre, radii, angle, span } => {
                if !within(*centre) {
                    return Err("its centre isn't a point within 1000000000 mm".into());
                }
                // a radius below none runs that axis the other way (a mirrored ellipse)
                for (i, r) in radii.iter().enumerate() {
                    let r = r.abs();
                    if !(r > 1.0 && r <= REACH) {
                        return Err(format!(
                            "its {} radius is {} mm; it's more than 1 mm and at most 1000000000",
                            if i == 0 { "first" } else { "second" },
                            disp(r)
                        ));
                    }
                }
                let max = MAX_DEGREES.to_radians();
                if !(angle.to_radians().abs() <= max) {
                    return Err(format!("its angle {}° isn't a number of degrees", disp(*angle)));
                }
                if let Some([a, b]) = span {
                    if !(a.to_radians().abs() <= max && b.to_radians().abs() <= max) {
                        return Err("its span isn't two angles in degrees".into());
                    }
                    if a == b {
                        return Err(format!("its span from {}° to {}° is nothing; give two angles apart", disp(*a), disp(*b)));
                    }
                }
                if !(norm(*centre) + radii[0].abs().max(radii[1].abs()) <= REACH) {
                    return Err("the ellipse reaches further than 1000000000 mm from the origin; move it in or make it smaller".into());
                }
            }
            Curve::Spline { control, knots } => {
                let n = control.len();
                if n < 2 {
                    return Err(format!("a spline needs two control points or more, not {}", n));
                }
                if !control.iter().all(|p| within(*p)) {
                    return Err("a control point isn't a number within 1000000000 mm".into());
                }
                if let Some(k) = knots {
                    check_knots(n, k)?;
                }
            }
            Curve::Fitted { fit, start_tangent, end_tangent } => {
                let n = fit.len();
                if n < 2 {
                    return Err(format!("a spline needs two points or more to pass through, not {}", n));
                }
                if !fit.iter().all(|p| within(*p)) {
                    return Err("a point isn't a number within 1000000000 mm".into());
                }
                if fit.windows(2).any(|w| w[0] == w[1]) {
                    return Err("two points one after another are the same; a spline passes through points apart".into());
                }
                for t in [start_tangent, end_tangent].into_iter().flatten() {
                    let l = norm(*t);
                    if !(l >= 1e-9 && l <= REACH) {
                        return Err("a tangent is a direction [x, y], not nothing".into());
                    }
                }
            }
        }
        if !(self.length() > MIN_LENGTH) {
            return Err("it is 1 mm long or less".into());
        }
        Ok(())
    }

    // ------------------------------------------------------------ fields

    /// Writes its fields, in the file's order, at the end of an object.
    pub fn put_fields(&self, m: &mut Map) {
        let pt = |p: &P2| Value::from(*p);
        let pts = |v: &[P2]| Value::Arr(v.iter().map(pt).collect());
        let nums = |v: &[f64]| Value::Arr(v.iter().map(|x| Value::f(*x)).collect());
        match self {
            Curve::Polyline { points, arcs, closed } => {
                if points.len() == 2 && !*closed {
                    m.insert("start", pt(&points[0]));
                    m.insert("end", pt(&points[1]));
                    if let Some(a) = arcs.first() {
                        if *a != 0.0 {
                            m.insert("arc", Value::f(*a));
                        }
                    }
                } else {
                    m.insert("points", pts(points));
                    if arcs.iter().any(|a| *a != 0.0) {
                        m.insert("arcs", nums(arcs));
                    }
                    if *closed {
                        m.insert("closed", Value::Bool(true));
                    }
                }
            }
            Curve::Circle { centre, radius } => {
                m.insert("centre", pt(centre));
                m.insert("radius", Value::f(*radius));
            }
            Curve::Ellipse { centre, radii, angle, span } => {
                m.insert("centre", pt(centre));
                m.insert("radii", nums(radii));
                if *angle != 0.0 {
                    m.insert("angle", Value::f(*angle));
                }
                if let Some(s) = span {
                    m.insert("span", nums(s));
                }
            }
            Curve::Spline { control, knots } => {
                m.insert("control", pts(control));
                if let Some(k) = knots {
                    m.insert("knots", nums(k));
                }
            }
            Curve::Fitted { fit, start_tangent, end_tangent } => {
                m.insert("fit", pts(fit));
                if let Some(t) = start_tangent {
                    m.insert("start_tangent", pt(t));
                }
                if let Some(t) = end_tangent {
                    m.insert("end_tangent", pt(t));
                }
            }
        }
    }

    /// Takes the curve's fields out of an object.
    pub fn clear_fields(m: &mut Map) {
        for k in KEYS {
            m.remove(k);
        }
    }

    /// Puts this curve in an element in place of the one it has (its other fields as they were).
    pub fn set_in(&self, e: &mut Value) {
        if let Value::Obj(m) = e {
            Curve::clear_fields(m);
            self.put_fields(m);
        }
    }

    /// The curve an element (or anything with a curve's fields) holds, if it holds one.
    pub fn of(e: &Value) -> Option<Curve> {
        parse(e).ok()
    }

    // ------------------------------------------------------------ drawing

    /// The runs of points it is drawn with, each point with its parameter.
    pub fn pieces(&self) -> Vec<Piece> {
        match self {
            Curve::Polyline { .. } => {
                self.segments().iter().enumerate().map(|(i, s)| Piece { seg: i, pts: s.drawn() }).collect()
            }
            Curve::Circle { centre, radius } => {
                let step = 2.0 * (1.0 - FLAT / radius).acos();
                let n = (2.0 * PI / step).ceil().max(360.0 / ARC_STEP).max(1.0);
                let n = if n.is_finite() { (n as usize).min(MAX_DRAWN) } else { 72 };
                let pts = (0..=n)
                    .map(|k| {
                        let a = 2.0 * PI * k as f64 / n as f64;
                        (k as f64 / n as f64, [centre[0] + radius * a.cos(), centre[1] + radius * a.sin()])
                    })
                    .collect();
                vec![Piece { seg: 0, pts }]
            }
            Curve::Ellipse { .. } => {
                // its parameter in degrees, as it is kept
                let (a0, swd) = self.ellipse_span_deg();
                let n = self.ellipse_chords();
                let pts = (0..=n)
                    .map(|k| {
                        let t = a0 + k as f64 * (swd / n as f64);
                        (k as f64 / n as f64, self.ellipse_at_t(t.to_radians()))
                    })
                    .collect();
                vec![Piece { seg: 0, pts }]
            }
            Curve::Spline { control, knots } => {
                let b = Bspline::new(control, knots.as_deref());
                vec![Piece { seg: 0, pts: b.drawn() }]
            }
            Curve::Fitted { .. } => {
                let b = self.fitted_bspline();
                vec![Piece { seg: 0, pts: b.drawn() }]
            }
        }
    }

    /// The points it is drawn with, in order (a closed curve's first point again at its end).
    pub fn points(&self) -> Vec<P2> {
        let mut out: Vec<P2> = Vec::new();
        for pc in self.pieces() {
            for (i, (_, p)) in pc.pts.iter().enumerate() {
                if i == 0 && !out.is_empty() {
                    continue;
                }
                out.push(*p);
            }
        }
        out
    }

    /// How long it is: a polyline's and a circle's exactly, the others along the points drawn.
    pub fn length(&self) -> f64 {
        match self {
            Curve::Polyline { .. } => self.segments().iter().map(|s| s.length()).sum(),
            Curve::Circle { radius, .. } => 2.0 * PI * radius,
            _ => {
                let p = self.points();
                p.windows(2).map(|w| dist(w[0], w[1])).sum()
            }
        }
    }

    /// The south-west and north-east corners round it as drawn.
    pub fn bounds(&self) -> Option<(P2, P2)> {
        let pts = self.points();
        let mut it = pts.iter();
        let f = *it.next()?;
        let (mut lo, mut hi) = (f, f);
        for p in it {
            lo = [lo[0].min(p[0]), lo[1].min(p[1])];
            hi = [hi[0].max(p[0]), hi[1].max(p[1])];
        }
        Some((lo, hi))
    }

    /// Where it starts and ends (None for a closed curve).
    pub fn ends(&self) -> Option<(P2, P2)> {
        if self.is_closed() {
            return None;
        }
        Some((self.start_point(), self.end_point()))
    }

    pub fn start_point(&self) -> P2 {
        match self {
            Curve::Polyline { points, .. } => points[0],
            Curve::Circle { centre, radius } => [centre[0] + radius, centre[1]],
            Curve::Ellipse { .. } => {
                let (t0, _) = self.ellipse_range();
                self.ellipse_at_t(t0)
            }
            Curve::Spline { control, .. } => control[0],
            Curve::Fitted { fit, .. } => fit[0],
        }
    }

    pub fn end_point(&self) -> P2 {
        match self {
            Curve::Polyline { points, closed, .. } => {
                if *closed {
                    points[0]
                } else {
                    *points.last().unwrap()
                }
            }
            Curve::Circle { .. } => self.start_point(),
            Curve::Ellipse { .. } => {
                let (t0, sw) = self.ellipse_range();
                self.ellipse_at_t(t0 + sw)
            }
            Curve::Spline { control, .. } => *control.last().unwrap(),
            Curve::Fitted { fit, .. } => *fit.last().unwrap(),
        }
    }

    /// The centres of its arcs, its circle's or its ellipse's (what a centre mark marks).
    pub fn centres(&self) -> Vec<P2> {
        match self {
            Curve::Polyline { .. } => self.segments().iter().filter_map(|s| s.geo()).map(|g| g.centre).collect(),
            Curve::Circle { centre, .. } | Curve::Ellipse { centre, .. } => vec![*centre],
            _ => Vec::new(),
        }
    }

    /// The point at a parameter (a segment and the fraction along it, for a polyline).
    pub fn at(&self, seg: usize, f: f64) -> P2 {
        match self {
            Curve::Polyline { .. } => {
                let segs = self.segments();
                segs[seg.min(segs.len() - 1)].at(f)
            }
            Curve::Circle { centre, radius } => {
                let a = 2.0 * PI * f;
                [centre[0] + radius * a.cos(), centre[1] + radius * a.sin()]
            }
            Curve::Ellipse { .. } => {
                let (a0, swd) = self.ellipse_span_deg();
                self.ellipse_at_t((a0 + swd * f).to_radians())
            }
            Curve::Spline { control, knots } => Bspline::new(control, knots.as_deref()).at(f),
            Curve::Fitted { .. } => self.fitted_bspline().at(f),
        }
    }

    // ------------------------------------------------------------ ellipses

    /// An ellipse's parameter range: where it starts and how far it runs, radians.
    pub fn ellipse_range(&self) -> (f64, f64) {
        match self {
            Curve::Ellipse { span: Some([a, b]), .. } => {
                let mut d = (b - a).rem_euclid(360.0);
                if d == 0.0 {
                    d = 360.0;
                }
                (a.to_radians(), d.to_radians())
            }
            _ => (0.0, 2.0 * PI),
        }
    }

    /// An ellipse's span in degrees: where it starts and how far it runs.
    fn ellipse_span_deg(&self) -> (f64, f64) {
        match self {
            Curve::Ellipse { span: Some([a, b]), .. } => {
                let mut d = (b - a).rem_euclid(360.0);
                if d == 0.0 {
                    d = 360.0;
                }
                (*a, d)
            }
            _ => (0.0, 360.0),
        }
    }

    pub fn ellipse_at_t(&self, t: f64) -> P2 {
        match self {
            Curve::Ellipse { centre, radii, angle, .. } => {
                let (sa, ca) = angle.to_radians().sin_cos();
                let x = radii[0] * t.cos();
                let y = radii[1] * t.sin();
                [centre[0] + x * ca - y * sa, centre[1] + x * sa + y * ca]
            }
            _ => [0.0, 0.0],
        }
    }

    fn ellipse_d1(&self, t: f64) -> P2 {
        match self {
            Curve::Ellipse { radii, angle, .. } => {
                let (sa, ca) = angle.to_radians().sin_cos();
                let x = -radii[0] * t.sin();
                let y = radii[1] * t.cos();
                [x * ca - y * sa, x * sa + y * ca]
            }
            _ => [0.0, 0.0],
        }
    }

    /// How many chords draw an ellipse.
    fn ellipse_chords(&self) -> usize {
        let (_, sw) = self.ellipse_range();
        let r = match self {
            Curve::Ellipse { radii, .. } => radii[0].abs().max(radii[1].abs()),
            _ => 1.0,
        };
        let step = 2.0 * (1.0 - FLAT / r).acos();
        let by_flat = (sw / step).ceil();
        let by_step = (sw.to_degrees() / ARC_STEP).ceil();
        let n = by_flat.max(by_step).max(8.0) * 2.0;
        if n.is_finite() {
            (n as usize).min(MAX_DRAWN)
        } else {
            16
        }
    }

    pub fn fitted_bspline(&self) -> Bspline {
        match self {
            Curve::Fitted { fit, start_tangent, end_tangent } => {
                let (control, knots) = fit_to_control(fit, *start_tangent, *end_tangent);
                Bspline { control, knots, degree: 3 }
            }
            _ => Bspline { control: vec![[0.0, 0.0], [1.0, 0.0]], knots: vec![0.0, 0.0, 1.0, 1.0], degree: 1 },
        }
    }

    // ------------------------------------------------------------ nearest

    /// Where it passes nearest `p`. On the chords it is drawn with first: the nearest, the
    /// parameter there as the chord's ends' parameters run. Then on the curve itself, by golden
    /// section (NARROWINGS times) from a bracket that far either side, the parameter's range over
    /// the number of points drawn (kept within the range); taken where that comes nearer than the
    /// chord does (from the outside of a bend).
    pub fn nearest(&self, p: P2) -> Near {
        let track = Track::of(self);
        if track.pts.len() < 2 {
            // nothing drawn to run along (no segments): where it starts
            let q = match (track.pts.first(), self) {
                (Some(x), _) => x.1,
                (None, Curve::Polyline { points, .. }) => points.first().copied().unwrap_or([0.0, 0.0]),
                (None, _) => self.start_point(),
            };
            let d = (p[0] - q[0]).hypot(p[1] - q[1]);
            return Near { seg: 0, f: 0.0, param: track.u0, point: q, dist: d };
        }
        let mut best: Option<(f64, f64)> = None;
        for w in track.pts.windows(2) {
            let (ua, a) = w[0];
            let (ub, b) = w[1];
            let d = sub(b, a);
            let l2 = d[0] * d[0] + d[1] * d[1];
            let s = if l2 > 0.0 { ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2 } else { 0.0 };
            let s = s.clamp(0.0, 1.0);
            let q = [a[0] + s * d[0], a[1] + s * d[1]];
            let dd = (p[0] - q[0]).hypot(p[1] - q[1]);
            if best.map(|b| dd < b.0).unwrap_or(true) {
                best = Some((dd, ua + s * (ub - ua)));
            }
        }
        let (dc, uc) = best.unwrap_or((f64::INFINITY, track.u0));
        let h = (track.u1 - track.u0) / track.pts.len().max(1) as f64;
        let (mut a, mut b) = ((uc - h).max(track.u0), (uc + h).min(track.u1));
        let far = |u: f64| {
            let e = sub(track.at(u), p);
            e[0].hypot(e[1])
        };
        for _ in 0..NARROWINGS {
            let w = b - a;
            let c = b - GOLDEN * w;
            let d = a + GOLDEN * w;
            if far(c) < far(d) {
                b = d;
            } else {
                a = c;
            }
        }
        let u = (a + b) / 2.0;
        let q = track.at(u);
        let dq = (p[0] - q[0]).hypot(p[1] - q[1]);
        if dq < dc {
            track.near(u, q, dq)
        } else {
            track.near(uc, track.at(uc), dc)
        }
    }

    /// The vertex nearest `p`: its index and how far it is (a polyline's corners, a spline's
    /// control points or points passed through).
    pub fn nearest_vertex(&self, p: P2) -> Option<(usize, f64)> {
        let v: &[P2] = match self {
            Curve::Polyline { points, .. } => points,
            Curve::Spline { control, .. } => control,
            Curve::Fitted { fit, .. } => fit,
            _ => return None,
        };
        let mut best: Option<(usize, f64)> = None;
        for (i, q) in v.iter().enumerate() {
            let d = dist(p, *q);
            if best.map(|b| d < b.1).unwrap_or(true) {
                best = Some((i, d));
            }
        }
        best
    }

    // ------------------------------------------------------------ moves

    /// The curve with each point moved by `f` (a move, a turn, a mirror or any affine map), as the
    /// original keeps it: points to the micron; a mirror (a map that turns it inside out) turns arcs
    /// the other way and an ellipse's second axis round (its second radius below none); an
    /// ellipse's direction and a spline's tangents mapped and kept to 1e-9.
    pub fn map(&self, f: &dyn Fn(P2) -> P2) -> Curve {
        let o = f([0.0, 0.0]);
        let lin = |v: P2| sub(f(v), o);
        let ex = lin([1.0, 0.0]);
        let ey = lin([0.0, 1.0]);
        let mirrored = cross(ex, ey) < 0.0;
        let pt = |p: &P2| r3p(f(*p));
        let dir9 = |v: P2| [r9(v[0]), r9(v[1])];
        match self {
            Curve::Polyline { points, arcs, closed } => Curve::Polyline {
                points: points.iter().map(pt).collect(),
                arcs: arcs.iter().map(|a| if mirrored { -a } else { *a }).collect(),
                closed: *closed,
            },
            Curve::Circle { centre, radius } => Curve::Circle { centre: pt(centre), radius: *radius },
            Curve::Ellipse { centre, radii, angle, span } => {
                let (s0, c0) = angle.to_radians().sin_cos();
                let u = dir9(lin([c0, s0]));
                let l = norm(u);
                let a = (u[1] / l).asin();
                let a = if u[0] >= 0.0 {
                    a
                } else if a >= 0.0 {
                    PI - a
                } else {
                    -PI - a
                };
                let r = if mirrored { [radii[0], -radii[1]] } else { *radii };
                Curve::Ellipse { centre: pt(centre), radii: r, angle: a.to_degrees(), span: *span }
            }
            Curve::Spline { control, knots } => Curve::Spline { control: control.iter().map(pt).collect(), knots: knots.clone() },
            Curve::Fitted { fit, start_tangent, end_tangent } => Curve::Fitted {
                fit: fit.iter().map(pt).collect(),
                start_tangent: start_tangent.map(|t| dir9(lin(t))),
                end_tangent: end_tangent.map(|t| dir9(lin(t))),
            },
        }
    }

    /// Moved by `d`.
    pub fn moved(&self, d: P2) -> Curve {
        self.map(&|p| add(p, d))
    }

    /// Turned `deg` degrees counter-clockwise about `c`.
    pub fn turned(&self, c: P2, deg: f64) -> Curve {
        let t = deg.to_radians();
        self.map(&|p| turn_about(p, c, t))
    }

    /// Mirrored across the line through `a` and `b`.
    pub fn mirrored(&self, a: P2, b: P2) -> Curve {
        self.map(&|p| mirror_point(p, a, b))
    }

    /// The same curve run the other way.
    pub fn reversed(&self) -> Curve {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                if *closed {
                    // a closed polyline from the same start, round the other way
                    let n = points.len();
                    let mut pts = vec![points[0]];
                    for i in (1..n).rev() {
                        pts.push(points[i]);
                    }
                    let ar = if arcs.is_empty() { Vec::new() } else { (0..n).rev().map(|i| -arcs[i]).collect() };
                    Curve::Polyline { points: pts, arcs: ar, closed: true }
                } else {
                    let mut pts = points.clone();
                    pts.reverse();
                    let mut ar: Vec<f64> = arcs.iter().map(|a| -a).collect();
                    ar.reverse();
                    Curve::Polyline { points: pts, arcs: ar, closed: false }
                }
            }
            Curve::Spline { control, knots } => {
                let mut c = control.clone();
                c.reverse();
                let k = knots.as_ref().map(|k| {
                    let (a, b) = (k[0], *k.last().unwrap());
                    let mut v: Vec<f64> = k.iter().map(|x| a + b - x).collect();
                    v.reverse();
                    v
                });
                Curve::Spline { control: c, knots: k }
            }
            Curve::Fitted { fit, start_tangent, end_tangent } => {
                let mut f = fit.clone();
                f.reverse();
                Curve::Fitted {
                    fit: f,
                    start_tangent: end_tangent.map(|t| [-t[0], -t[1]]),
                    end_tangent: start_tangent.map(|t| [-t[0], -t[1]]),
                }
            }
            Curve::Ellipse { centre, radii, angle, span: Some([a, b]) } => {
                // the same ellipse mirrored in its own first axis runs the other way
                Curve::Ellipse { centre: *centre, radii: *radii, angle: *angle, span: Some([*a, *b]) }
            }
            c => c.clone(),
        }
    }
}

// ---------------------------------------------------------------- knots

/// The checks of a spline's own knots.
fn check_knots(n: usize, k: &[f64]) -> R<()> {
    let m = k.len();
    let ok_count = m > n + 1 && {
        let p = m - n - 1;
        (1..=5).contains(&p) && p < n
    };
    if !ok_count {
        return Err(format!(
            "a spline of {} control points has {} plus its degree plus one knots (degree 1 to 5, below {}), not {}",
            n, n, n, m
        ));
    }
    let p = m - n - 1;
    if !k.iter().all(|x| x.is_finite() && x.abs() <= REACH) || k.windows(2).any(|w| w[1] < w[0]) {
        return Err("its knots are numbers, each no less than the one before".into());
    }
    // runs of equal knots
    let mut runs: Vec<(f64, usize)> = Vec::new();
    for x in k {
        match runs.last_mut() {
            Some((v, c)) if *v == *x => *c += 1,
            _ => runs.push((*x, 1)),
        }
    }
    let clamped = runs.len() >= 2 && runs[0].1 >= p + 1 && runs.last().unwrap().1 >= p + 1;
    if !clamped {
        return Err(format!(
            "its first {} knots are the same, and its last {}, so it runs from its first control point to its last",
            p + 1,
            p + 1
        ));
    }
    let inner_ok = runs[0].1 == p + 1
        && runs.last().unwrap().1 == p + 1
        && runs[1..runs.len() - 1].iter().all(|(_, c)| *c <= p);
    if !inner_ok {
        return Err(format!("no knot inside it comes more than {} times", p));
    }
    Ok(())
}

/// A spline's degree: its knots say it, else cubic (lower with fewer control points).
pub fn degree_of(n: usize, knots: Option<&[f64]>) -> usize {
    match knots {
        Some(k) if k.len() > n + 1 => k.len() - n - 1,
        _ => 3.min(n.saturating_sub(1)).max(1),
    }
}

/// The clamped uniform knots of `n` control points of degree `p`, from 0 to 1.
pub fn uniform_knots(n: usize, p: usize) -> Vec<f64> {
    let mut k = vec![0.0; p + 1];
    let inner = n - p - 1;
    for i in 1..=inner {
        k.push(i as f64 / (inner + 1) as f64);
    }
    k.extend(std::iter::repeat(1.0).take(p + 1));
    k
}

// ---------------------------------------------------------------- B-splines

/// A B-spline: its control points, its knots (clamped) and degree.
#[derive(Clone, Debug)]
pub struct Bspline {
    pub control: Vec<P2>,
    pub knots: Vec<f64>,
    pub degree: usize,
}

impl Bspline {
    pub fn new(control: &[P2], knots: Option<&[f64]>) -> Bspline {
        let n = control.len();
        let p = degree_of(n, knots);
        let k = match knots {
            Some(k) if k.len() == n + p + 1 => k.to_vec(),
            _ => uniform_knots(n, p),
        };
        Bspline { control: control.to_vec(), knots: k, degree: p }
    }

    pub fn u0(&self) -> f64 {
        self.knots[self.degree]
    }
    pub fn u1(&self) -> f64 {
        self.knots[self.control.len()]
    }

    /// The knot span holding `u`.
    pub fn span(&self, u: f64) -> usize {
        let n = self.control.len();
        let p = self.degree;
        if u >= self.knots[n] {
            // the last span of non-zero length
            let mut k = n - 1;
            while k > p && self.knots[k] == self.knots[k + 1] {
                k -= 1;
            }
            return k;
        }
        if u <= self.knots[p] {
            let mut k = p;
            while k < n - 1 && self.knots[k] == self.knots[k + 1] {
                k += 1;
            }
            return k;
        }
        let (mut lo, mut hi) = (p, n);
        let mut mid = (lo + hi) / 2;
        while u < self.knots[mid] || u >= self.knots[mid + 1] {
            if u < self.knots[mid] {
                hi = mid;
            } else {
                lo = mid;
            }
            mid = (lo + hi) / 2;
        }
        mid
    }

    /// The point at parameter `u` (de Boor).
    pub fn at(&self, u: f64) -> P2 {
        let p = self.degree;
        let k = self.span(u);
        let t = &self.knots;
        let mut d: Vec<P2> = (0..=p).map(|j| self.control[j + k - p]).collect();
        for r in 1..=p {
            for j in (r..=p).rev() {
                let den = t[j + 1 + k - r] - t[j + k - p];
                let a = if den == 0.0 { 0.0 } else { (u - t[j + k - p]) / den };
                d[j] = [(1.0 - a) * d[j - 1][0] + a * d[j][0], (1.0 - a) * d[j - 1][1] + a * d[j][1]];
            }
        }
        d[p]
    }

    /// The control points of its derivative (a B-spline of one degree less on the inner knots).
    pub fn derivative(&self) -> Bspline {
        let p = self.degree;
        let n = self.control.len();
        if p == 0 || n < 2 {
            return Bspline { control: vec![[0.0, 0.0]], knots: vec![0.0, 1.0], degree: 0 };
        }
        let t = &self.knots;
        let q: Vec<P2> = (0..n - 1)
            .map(|i| {
                let den = t[i + p + 1] - t[i + 1];
                if den == 0.0 {
                    [0.0, 0.0]
                } else {
                    mul(sub(self.control[i + 1], self.control[i]), p as f64 / den)
                }
            })
            .collect();
        Bspline { control: q, knots: t[1..t.len() - 1].to_vec(), degree: p - 1 }
    }

    /// The parameters it is drawn at and the points: each knot span in equal steps, as many as
    /// keep each chord within FLAT of it (by the most its second derivative comes to there).
    pub fn drawn(&self) -> Vec<(f64, P2)> {
        let p = self.degree;
        let n = self.control.len();
        let mut out: Vec<(f64, P2)> = Vec::new();
        if p == 1 {
            for k in p..n {
                let (a, b) = (self.knots[k], self.knots[k + 1]);
                if b <= a {
                    continue;
                }
                if out.is_empty() {
                    out.push((a, self.control[k - 1]));
                }
                out.push((b, self.control[k]));
            }
            return out;
        }
        let second = self.derivative().derivative();
        for k in p..n {
            let (a, b) = (self.knots[k], self.knots[k + 1]);
            if b <= a {
                continue;
            }
            let mut m = 0.0f64;
            for i in (k - p)..=(k - 2) {
                if let Some(c) = second.control.get(i) {
                    m = m.max(norm(*c));
                }
            }
            let steps = if m > 0.0 {
                let du = (8.0 * FLAT / m).sqrt();
                let s = ((b - a) / du).ceil();
                if s.is_finite() {
                    (s as usize).clamp(1, MAX_DRAWN)
                } else {
                    1
                }
            } else {
                1
            };
            let first = out.is_empty();
            for i in 0..=steps {
                if i == 0 && !first {
                    continue;
                }
                let u = a + (b - a) * i as f64 / steps as f64;
                out.push((u, self.at(u)));
            }
        }
        out
    }

    /// The same curve with knot `u` inserted `times` times (Boehm): one control point more each.
    pub fn insert_knot(&self, u: f64, times: usize) -> Bspline {
        let mut b = self.clone();
        for _ in 0..times {
            let p = b.degree;
            let k = b.span(u);
            let t = &b.knots;
            let mut q: Vec<P2> = Vec::with_capacity(b.control.len() + 1);
            for i in 0..=b.control.len() {
                if i + p <= k {
                    q.push(b.control[i]);
                } else if i > k {
                    q.push(b.control[i - 1]);
                } else {
                    let den = t[i + p] - t[i];
                    let a = if den == 0.0 { 0.0 } else { (u - t[i]) / den };
                    q.push([
                        (1.0 - a) * b.control[i - 1][0] + a * b.control[i][0],
                        (1.0 - a) * b.control[i - 1][1] + a * b.control[i][1],
                    ]);
                }
            }
            let mut nk = b.knots.clone();
            nk.insert(k + 1, u);
            b = Bspline { control: q, knots: nk, degree: p };
        }
        b
    }

    /// How many times `u` is a knot.
    pub fn multiplicity(&self, u: f64) -> usize {
        self.knots.iter().filter(|x| **x == u).count()
    }
}

// ---------------------------------------------------------------- splines through points

/// The cumulative distances along points.
pub fn chord_params(pts: &[P2]) -> Vec<f64> {
    let mut s = vec![0.0];
    for w in pts.windows(2) {
        let l = *s.last().unwrap() + dist(w[0], w[1]);
        s.push(l);
    }
    s
}

/// The non-zero basis functions of degree `p` at `u` in knot span `k`, and their first `nd`
/// derivatives (The NURBS Book, A2.3): `ders[d][j]` is the d-th derivative of N_{k-p+j}.
pub fn basis_ders(knots: &[f64], p: usize, k: usize, u: f64, nd: usize) -> Vec<Vec<f64>> {
    let mut ndu = vec![vec![0.0; p + 1]; p + 1];
    let mut left = vec![0.0; p + 1];
    let mut right = vec![0.0; p + 1];
    ndu[0][0] = 1.0;
    for j in 1..=p {
        left[j] = u - knots[k + 1 - j];
        right[j] = knots[k + j] - u;
        let mut saved = 0.0;
        for r in 0..j {
            ndu[j][r] = right[r + 1] + left[j - r];
            let temp = if ndu[j][r] == 0.0 { 0.0 } else { ndu[r][j - 1] / ndu[j][r] };
            ndu[r][j] = saved + right[r + 1] * temp;
            saved = left[j - r] * temp;
        }
        ndu[j][j] = saved;
    }
    let mut ders = vec![vec![0.0; p + 1]; nd + 1];
    for j in 0..=p {
        ders[0][j] = ndu[j][p];
    }
    let mut a = vec![vec![0.0; p + 1]; 2];
    for r in 0..=p {
        let (mut s1, mut s2) = (0usize, 1usize);
        a[0][0] = 1.0;
        for kk in 1..=nd.min(p) {
            let mut d = 0.0;
            let rk = r as isize - kk as isize;
            let pk = p - kk;
            if r >= kk {
                let den = ndu[pk + 1][rk as usize];
                a[s2][0] = if den == 0.0 { 0.0 } else { a[s1][0] / den };
                d = a[s2][0] * ndu[rk as usize][pk];
            }
            let j1 = if rk >= -1 { 1 } else { (-rk) as usize };
            let j2 = if (r as isize - 1) <= pk as isize { kk - 1 } else { p - r };
            for j in j1..=j2 {
                let idx = (rk + j as isize) as usize;
                let den = ndu[pk + 1][idx];
                a[s2][j] = if den == 0.0 { 0.0 } else { (a[s1][j] - a[s1][j - 1]) / den };
                d += a[s2][j] * ndu[idx][pk];
            }
            if r <= pk {
                let den = ndu[pk + 1][r];
                a[s2][kk] = if den == 0.0 { 0.0 } else { -a[s1][kk - 1] / den };
                d += a[s2][kk] * ndu[r][pk];
            }
            ders[kk][r] = d;
            std::mem::swap(&mut s1, &mut s2);
        }
    }
    let mut f = p as f64;
    for kk in 1..=nd.min(p) {
        for j in 0..=p {
            ders[kk][j] *= f;
        }
        f *= (p - kk) as f64;
    }
    ders
}

/// The cubic through points by the distance along them, as control points and knots (the knots
/// at the points' distances along, clamped): each end free (no bend) or leaving along a tangent.
pub fn fit_to_control(fit: &[P2], st: Option<P2>, et: Option<P2>) -> (Vec<P2>, Vec<f64>) {
    let m = fit.len() - 1;
    let s = chord_params(fit);
    let mut knots = vec![s[0]; 4];
    knots.extend_from_slice(&s[1..m]);
    knots.extend(std::iter::repeat(s[m]).take(4));
    let n = m + 3;
    if m == 0 {
        return (vec![fit[0]; 4], knots);
    }
    let basis = Bspline { control: vec![[0.0, 0.0]; n], knots: knots.clone(), degree: 3 };
    let row = |u: f64, d: usize| -> Vec<f64> {
        let k = basis.span(u);
        let ders = basis_ders(&knots, 3, k, u, d);
        let mut r = vec![0.0; n];
        for j in 0..=3 {
            r[k - 3 + j] = ders[d][j];
        }
        r
    };
    // the system: the two end conditions and interpolation at each point
    let mut a = vec![vec![0.0; n]; n];
    let mut rhs = vec![[0.0, 0.0]; n];
    for i in 0..=m {
        a[i] = row(s[i], 0);
        rhs[i] = fit[i];
    }
    let (d0, b0) = match st {
        None => (2, [0.0, 0.0]),
        Some(t) => (1, unit(t)),
    };
    a[m + 1] = row(s[0], d0);
    rhs[m + 1] = b0;
    let (d1, b1) = match et {
        None => (2, [0.0, 0.0]),
        Some(t) => (1, unit(t)),
    };
    a[m + 2] = row(s[m], d1);
    rhs[m + 2] = b1;
    let ctrl = solve(a, rhs);
    (ctrl, knots)
}

/// Solves a small linear system for points (Gauss-Jordan with pivoting).
fn solve(mut a: Vec<Vec<f64>>, mut b: Vec<P2>) -> Vec<P2> {
    let n = a.len();
    for c in 0..n {
        let mut piv = c;
        for r in c + 1..n {
            if a[r][c].abs() > a[piv][c].abs() {
                piv = r;
            }
        }
        a.swap(c, piv);
        b.swap(c, piv);
        let d = a[c][c];
        if d == 0.0 {
            continue;
        }
        for r in 0..n {
            if r != c && a[r][c] != 0.0 {
                let f = a[r][c] / d;
                for k in c..n {
                    a[r][k] -= f * a[c][k];
                }
                b[r] = [b[r][0] - f * b[c][0], b[r][1] - f * b[c][1]];
            }
        }
    }
    (0..n).map(|i| [b[i][0] / a[i][i], b[i][1] / a[i][i]]).collect()
}

/// How far a sample may stray from the chords of a refitted spline, mm.
pub const REFIT_TOL: f64 = 2.0 * FIT_TOL;
/// How many steps a curve is sampled in to refit it.
pub const REFIT_SAMPLES: usize = 256;

/// The unit tangents where a curve given by a function of its parameter leaves `u0` and comes
/// into `u1`, by a step of a millionth of the way.
pub fn end_tangents(at: &dyn Fn(f64) -> P2, u0: f64, u1: f64) -> (P2, P2) {
    let h = 1e-6 * (u1 - u0);
    let st = unit(sub(at(u0 + h), at(u0)));
    let et = unit(sub(at(u1), at(u1 - h)));
    (st, et)
}

/// The distance from a point to a run of drawn points.
fn chord_distance(pts: &[(f64, P2)], p: P2) -> f64 {
    let mut best = f64::INFINITY;
    for w in pts.windows(2) {
        let (a, b) = (w[0].1, w[1].1);
        let d = sub(b, a);
        let l2 = d[0] * d[0] + d[1] * d[1];
        let s = if l2 > 0.0 { ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2 } else { 0.0 };
        let s = s.clamp(0.0, 1.0);
        let e = [p[0] - a[0] - s * d[0], p[1] - a[1] - s * d[1]];
        let dd = (e[0] * e[0] + e[1] * e[1]).sqrt();
        if dd < best {
            best = dd;
        }
    }
    best
}

/// How many points a refit adds at most.
pub const REFIT_PICKS: usize = 64;

/// A spline through points that keeps near a curve given by a function of its parameter over
/// [u0, u1]: sampled in REFIT_SAMPLES equal steps (and at `start`), it passes through its ends and
/// the points at `start`, leaving and arriving along the tangents given, with the sample where it
/// strays most from the chords it is drawn with added (at most REFIT_PICKS of them) until none
/// strays more than FIT_TOL, to the micron.
pub fn refit(at: &dyn Fn(f64) -> P2, u0: f64, u1: f64, st: Option<P2>, et: Option<P2>, start: &[f64]) -> Curve {
    refit_with(at, u0, u1, st, et, start, true)
}

/// `refit`, the points passed through kept to a micrometre (`round`) or as they come.
pub fn refit_with(
    at: &dyn Fn(f64) -> P2,
    u0: f64,
    u1: f64,
    st: Option<P2>,
    et: Option<P2>,
    start: &[f64],
    round: bool,
) -> Curve {
    let keep = |p: P2| if round { r3p(p) } else { p };
    let mut us: Vec<f64> = (0..=REFIT_SAMPLES).map(|i| u0 + (u1 - u0) * i as f64 / REFIT_SAMPLES as f64).collect();
    for b in start {
        if *b > u0 && *b < u1 && !us.contains(b) {
            us.push(*b);
        }
    }
    us.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let pts: Vec<P2> = us.iter().map(|u| at(*u)).collect();
    let last = us.len() - 1;
    let mut chosen: Vec<usize> = vec![0, last];
    for k in start {
        if let Some(i) = us.iter().position(|u| u == k) {
            if !chosen.contains(&i) {
                chosen.push(i);
            }
        }
    }
    chosen.sort();
    let mut picks = 0;
    loop {
        let fit: Vec<P2> = chosen.iter().map(|i| keep(pts[*i])).collect();
        let fc = Curve::Fitted { fit: fit.clone(), start_tangent: st, end_tangent: et };
        if picks >= REFIT_PICKS {
            return fc;
        }
        // through points all in one place, the spline is that point
        let drawn = if chord_params(&fit).last().copied().unwrap_or(0.0) > 0.0 {
            fc.fitted_bspline().drawn()
        } else {
            vec![(0.0, fit[0]), (0.0, fit[0])]
        };
        let mut worst: Option<(f64, usize)> = None;
        for i in 0..=last {
            if chosen.contains(&i) {
                continue;
            }
            let d = chord_distance(&drawn, pts[i]);
            if worst.map(|x| d > x.0).unwrap_or(true) {
                worst = Some((d, i));
            }
        }
        match worst {
            Some((d, i)) if r3(d) > FIT_TOL => {
                chosen.push(i);
                chosen.sort();
                picks += 1;
            }
            _ => return fc,
        }
    }
}

// ---------------------------------------------------------------- reading the fields

/// The fields of a curve as given.
#[derive(Clone, Debug, Default)]
pub struct Fields {
    pub start: Option<P2>,
    pub end: Option<P2>,
    pub through: Option<P2>,
    pub arc: Option<f64>,
    pub points: Option<Vec<P2>>,
    pub arcs: Option<Vec<f64>>,
    pub closed: bool,
    pub centre: Option<P2>,
    pub radius: Option<f64>,
    pub radii: Option<[f64; 2]>,
    pub angle: Option<f64>,
    pub span: Option<[f64; 2]>,
    pub control: Option<Vec<P2>>,
    pub knots: Option<Vec<f64>>,
    pub fit: Option<Vec<P2>>,
    pub start_tangent: Option<P2>,
    pub end_tangent: Option<P2>,
}

fn kind(v: &Value) -> String {
    v.kind_name()
}

fn de_f64(v: &Value) -> R<f64> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(format!("invalid type: {}, expected f64", kind(v))),
    }
}

/// Two numbers, as serde reads a tuple struct `P2` or an array `[f64; 2]` (`what` is how serde
/// calls it: "tuple struct P2", "an array of length 2").
fn de_pair(v: &Value, what: &str, len_what: &str) -> R<P2> {
    match v {
        Value::Arr(a) => {
            let mut out = [0.0; 2];
            for i in 0..2 {
                match a.get(i) {
                    Some(x) => out[i] = de_f64(x)?,
                    None => return Err(format!("invalid length {}, expected {}", i, len_what)),
                }
            }
            if a.len() > 2 {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(out)
        }
        _ => Err(format!("invalid type: {}, expected {}", kind(v), what)),
    }
}

fn de_p2(v: &Value) -> R<P2> {
    de_pair(v, "tuple struct P2", "tuple struct P2 with 2 elements")
}

fn de_arr2(v: &Value) -> R<[f64; 2]> {
    de_pair(v, "an array of length 2", "an array of length 2")
}

fn de_vec<T>(v: &Value, el: &dyn Fn(&Value) -> R<T>) -> R<Vec<T>> {
    match v {
        Value::Arr(a) => a.iter().map(el).collect(),
        _ => Err(format!("invalid type: {}, expected a sequence", kind(v))),
    }
}

impl Fields {
    /// Reads the fields of an object as serde reads them: each key of the curve's in sorted order,
    /// the first that isn't of its type refused (serde's own words); null is no value (but for
    /// `closed`, which is true or false).
    pub fn read(v: &Value) -> R<Fields> {
        let mut f = Fields::default();
        let m = match v {
            Value::Obj(m) => m,
            _ => return Ok(f),
        };
        let mut keys: Vec<&(String, Value)> = m.items.iter().filter(|(k, _)| KEYS.contains(&k.as_str())).collect();
        keys.sort_by(|a, b| a.0.cmp(&b.0));
        for (k, x) in keys {
            if x.is_null() && k != "closed" {
                continue;
            }
            match k.as_str() {
                "start" => f.start = Some(de_p2(x)?),
                "end" => f.end = Some(de_p2(x)?),
                "through" => f.through = Some(de_p2(x)?),
                "arc" => f.arc = Some(de_f64(x)?),
                "points" => f.points = Some(de_vec(x, &de_p2)?),
                "arcs" => f.arcs = Some(de_vec(x, &de_f64)?),
                "closed" => {
                    f.closed = match x {
                        Value::Bool(b) => *b,
                        _ => return Err(format!("invalid type: {}, expected a boolean", kind(x))),
                    }
                }
                "centre" => f.centre = Some(de_p2(x)?),
                "radius" => f.radius = Some(de_f64(x)?),
                "radii" => f.radii = Some(de_arr2(x)?),
                "angle" => f.angle = Some(de_f64(x)?),
                "span" => f.span = Some(de_arr2(x)?),
                "control" => f.control = Some(de_vec(x, &de_p2)?),
                "knots" => f.knots = Some(de_vec(x, &de_f64)?),
                "fit" => f.fit = Some(de_vec(x, &de_p2)?),
                "start_tangent" => f.start_tangent = Some(de_p2(x)?),
                "end_tangent" => f.end_tangent = Some(de_p2(x)?),
                _ => {}
            }
        }
        Ok(f)
    }

    /// The fields given, in the order of KEYS (`closed` only when true).
    pub fn given(&self) -> Vec<&'static str> {
        let mut g = Vec::new();
        let flags = [
            self.start.is_some(),
            self.end.is_some(),
            self.through.is_some(),
            self.arc.is_some(),
            self.points.is_some(),
            self.arcs.is_some(),
            self.closed,
            self.centre.is_some(),
            self.radius.is_some(),
            self.radii.is_some(),
            self.angle.is_some(),
            self.span.is_some(),
            self.control.is_some(),
            self.knots.is_some(),
            self.fit.is_some(),
            self.start_tangent.is_some(),
            self.end_tangent.is_some(),
        ];
        for (i, k) in KEYS.iter().enumerate() {
            if flags[i] {
                g.push(*k);
            }
        }
        g
    }

    /// The curve the fields make: the first shape whose fields are there (a line by `start` and
    /// `end`, a polyline by `points`, a circle, an ellipse, a spline by `control`, one through
    /// `fit`), none of another shape's fields with it.
    pub fn curve(&self) -> R<Curve> {
        let (own, curve): (&[&str], Option<Curve>) = if self.start.is_some() && self.end.is_some() {
            (&["start", "end", "through", "arc"], None)
        } else if self.points.is_some() {
            (&["points", "arcs", "closed"], None)
        } else if self.centre.is_some() && self.radius.is_some() {
            (&["centre", "radius"], None)
        } else if self.centre.is_some() && self.radii.is_some() {
            (&["centre", "radii", "angle", "span"], None)
        } else if self.control.is_some() {
            (&["control", "knots"], None)
        } else if self.fit.is_some() {
            (&["fit", "start_tangent", "end_tangent"], None)
        } else {
            return Err(GENERIC.to_string());
        };
        let _ = curve;
        for g in self.given() {
            if !own.contains(&g) {
                return Err(format!("`{}` doesn't go with the {} given: {}", g, own.join(", "), GENERIC));
            }
        }
        match own[0] {
            "start" => {
                let (a, b) = (self.start.unwrap(), self.end.unwrap());
                if self.through.is_some() && self.arc.is_some() {
                    return Err("give an arc's `through` point or its `arc` turn, not both".into());
                }
                let deg = match (self.arc, self.through) {
                    (Some(d), _) => d,
                    (None, Some(t)) => arc_through(a, b, t),
                    _ => 0.0,
                };
                Ok(Curve::arc(a, b, deg))
            }
            "points" => Ok(Curve::polyline(self.points.clone().unwrap(), self.arcs.clone().unwrap_or_default(), self.closed)),
            "centre" if self.radius.is_some() => Ok(Curve::Circle { centre: self.centre.unwrap(), radius: self.radius.unwrap() }),
            "centre" => Ok(Curve::Ellipse {
                centre: self.centre.unwrap(),
                radii: self.radii.unwrap(),
                angle: self.angle.unwrap_or(0.0),
                span: self.span,
            }),
            "control" => Ok(Curve::Spline { control: self.control.clone().unwrap(), knots: self.knots.clone() }),
            _ => Ok(Curve::Fitted { fit: self.fit.clone().unwrap(), start_tangent: self.start_tangent, end_tangent: self.end_tangent }),
        }
    }
}

/// The curve an object's fields give, with the original's words for what's wrong: serde's for a
/// field of the wrong type (with what a curve is after it), "`x` doesn't go with …", or what a
/// curve is.
pub fn parse(v: &Value) -> R<Curve> {
    let f = Fields::read(v).map_err(|e| format!("{}: {}", e, GENERIC))?;
    f.curve()
}

// ---------------------------------------------------------------- along a curve

/// A curve as `nearest` runs along it: the points it is drawn with, each with its parameter
/// there (see `Near::param`), the parameter's range, and the point at any parameter.
struct Track {
    pts: Vec<(f64, P2)>,
    u0: f64,
    u1: f64,
    kind: TrackKind,
}

enum TrackKind {
    Segs(Vec<Seg>, Vec<Option<ArcGeo>>),
    Circle(P2, f64),
    /// Its centre, radii and turn, and where its span starts and how far it runs (degrees).
    Ellipse(Curve, f64, f64),
    Spline(Bspline),
}

impl Track {
    fn of(c: &Curve) -> Track {
        match c {
            Curve::Polyline { .. } => {
                let segs = c.segments();
                let geos: Vec<Option<ArcGeo>> = segs.iter().map(|s| s.geo()).collect();
                let mut pts: Vec<(f64, P2)> = Vec::new();
                for (i, s) in segs.iter().enumerate() {
                    for (k, (f, q)) in s.drawn().into_iter().enumerate() {
                        if k == 0 && !pts.is_empty() {
                            continue;
                        }
                        pts.push((i as f64 + f, q));
                    }
                }
                let u1 = segs.len() as f64;
                Track { pts, u0: 0.0, u1, kind: TrackKind::Segs(segs, geos) }
            }
            Curve::Circle { centre, radius } => {
                let drawn = c.points();
                let n = drawn.len().max(2) - 1;
                let pts = drawn.into_iter().enumerate().map(|(k, q)| (k as f64 * (360.0 / n as f64), q)).collect();
                Track { pts, u0: 0.0, u1: 360.0, kind: TrackKind::Circle(*centre, *radius) }
            }
            Curve::Ellipse { .. } => {
                let (a0, swd) = c.ellipse_span_deg();
                let drawn = c.points();
                let n = drawn.len().max(2) - 1;
                let pts = drawn.into_iter().enumerate().map(|(k, q)| (a0 + k as f64 * (swd / n as f64), q)).collect();
                Track { pts, u0: a0, u1: a0 + swd, kind: TrackKind::Ellipse(c.clone(), a0, swd) }
            }
            Curve::Spline { control, knots } => {
                let b = Bspline::new(control, knots.as_deref());
                Track { pts: b.drawn(), u0: b.u0(), u1: b.u1(), kind: TrackKind::Spline(b) }
            }
            Curve::Fitted { .. } => {
                let b = c.fitted_bspline();
                Track { pts: b.drawn(), u0: b.u0(), u1: b.u1(), kind: TrackKind::Spline(b) }
            }
        }
    }

    /// A polyline's segment at a parameter, and the fraction along it.
    fn seg_of(u: f64, ns: usize) -> (usize, f64) {
        let i = if u > 0.0 { (u.floor() as usize).min(ns.max(1) - 1) } else { 0 };
        (i, u - i as f64)
    }

    fn at(&self, u: f64) -> P2 {
        match &self.kind {
            TrackKind::Segs(segs, geos) => {
                let (i, f) = Track::seg_of(u, segs.len());
                match geos[i] {
                    Some(g) => g.at(f),
                    None => lerp(segs[i].a, segs[i].b, f),
                }
            }
            TrackKind::Circle(c, r) => {
                let a = u.to_radians();
                [c[0] + r * a.cos(), c[1] + r * a.sin()]
            }
            TrackKind::Ellipse(e, _, _) => e.ellipse_at_t(u.to_radians()),
            TrackKind::Spline(b) => b.at(u),
        }
    }

    fn near(&self, u: f64, point: P2, dist: f64) -> Near {
        match &self.kind {
            TrackKind::Segs(segs, _) => {
                let (seg, f) = Track::seg_of(u, segs.len());
                Near { seg, f, param: u, point, dist }
            }
            TrackKind::Circle(..) => Near { seg: 0, f: u / 360.0, param: u, point, dist },
            TrackKind::Ellipse(_, a0, swd) => Near { seg: 0, f: (u - a0) / swd, param: u, point, dist },
            TrackKind::Spline(_) => Near { seg: 0, f: u, param: u, point, dist },
        }
    }
}

// ---------------------------------------------------------------- vertices

/// What adding or taking a vertex does.
#[derive(Debug)]
pub enum VertexError {
    /// Not a shape that takes one there ("only polylines and splines take a vertex, between their ends").
    NotBetweenEnds,
    /// Too far from the line: the distance.
    TooFar(f64),
    /// Too far from any vertex: the distance.
    NoVertexNear(f64),
    /// No vertex can go ("it has no vertex to spare").
    NoneToSpare,
}

/// How near a vertex must be to the point given, mm.
pub const VERTEX_REACH: f64 = 100.0;

impl Curve {
    /// The curve with a vertex more where it passes nearest `p`: a polyline's segment cut there
    /// (within a millimetre of a corner, the corner: a closed polyline then starts there), a knot
    /// inserted in a control-point spline (the curve as it was), a point in a spline through points.
    pub fn with_vertex(&self, p: P2) -> Result<Curve, VertexError> {
        match self {
            Curve::Circle { .. } | Curve::Ellipse { .. } => {
                let near = self.nearest(p);
                if near.dist > VERTEX_REACH {
                    return Err(VertexError::TooFar(r2(near.dist)));
                }
                Err(VertexError::NotBetweenEnds)
            }
            Curve::Polyline { points, arcs, closed } => {
                let near = self.nearest(p);
                if near.dist > VERTEX_REACH {
                    return Err(VertexError::TooFar(r2(near.dist)));
                }
                let segs = self.segments();
                let ns = segs.len();
                if (near.seg == 0 && near.f <= 0.0) || (near.seg == ns - 1 && near.f >= 1.0) {
                    return Err(VertexError::NotBetweenEnds);
                }
                let q = r3p(near.point);
                let s = segs[near.seg];
                // within a millimetre of a corner: that corner
                let corner = if dist(near.point, s.a) <= 1.0 {
                    Some(near.seg)
                } else if dist(near.point, s.b) <= 1.0 {
                    Some((near.seg + 1) % points.len())
                } else {
                    None
                };
                match corner {
                    Some(c) => {
                        if !*closed {
                            if c == 0 || c == points.len() - 1 {
                                return Err(VertexError::NotBetweenEnds);
                            }
                            return Ok(self.clone());
                        }
                        Ok(self.rotated_to(c))
                    }
                    None => {
                        let i = near.seg;
                        let f = near.f;
                        let mut pts = points.clone();
                        let mut ar: Vec<f64> = if arcs.is_empty() { vec![0.0; ns] } else { arcs.clone() };
                        let a1 = r9(s.arc * f);
                        let a2 = r9(s.arc - a1);
                        pts.insert(i + 1, q);
                        ar[i] = a1;
                        ar.insert(i + 1, a2);
                        let c = Curve::polyline(pts, ar, *closed);
                        if *closed {
                            Ok(c.rotated_to(i + 1))
                        } else {
                            Ok(c)
                        }
                    }
                }
            }
            Curve::Spline { control, knots } => {
                let near = self.nearest(p);
                if near.dist > VERTEX_REACH {
                    return Err(VertexError::TooFar(r2(near.dist)));
                }
                let b = Bspline::new(control, knots.as_deref());
                if near.f <= b.u0() || near.f >= b.u1() {
                    return Err(VertexError::NotBetweenEnds);
                }
                let nb = b.insert_knot(near.f, 1);
                Ok(Curve::Spline { control: nb.control.iter().map(|c| r3p(*c)).collect(), knots: Some(nb.knots) })
            }
            Curve::Fitted { fit, start_tangent, end_tangent } => {
                let near = self.nearest(p);
                if near.dist > VERTEX_REACH {
                    return Err(VertexError::TooFar(r2(near.dist)));
                }
                let b = self.fitted_bspline();
                if near.f <= b.u0() || near.f >= b.u1() {
                    return Err(VertexError::NotBetweenEnds);
                }
                let s = chord_params(fit);
                let q = r3p(near.point);
                let mut i = 1;
                while i < s.len() - 1 && s[i] <= near.f {
                    i += 1;
                }
                let mut f = fit.clone();
                // a point within a millimetre of one it passes through: none to add
                if dist(q, f[i - 1]) <= 1.0 || dist(q, f[i]) <= 1.0 {
                    return Err(VertexError::NotBetweenEnds);
                }
                f.insert(i, q);
                Ok(Curve::Fitted { fit: f, start_tangent: *start_tangent, end_tangent: *end_tangent })
            }
        }
    }

    /// The curve with the vertex nearest `p` taken out: a polyline's corner (the two segments
    /// either side one, an arc turning as both did if both were arcs), a control point, a point
    /// passed through.
    pub fn without_vertex(&self, p: P2) -> Result<Curve, VertexError> {
        match self {
            Curve::Circle { .. } | Curve::Ellipse { .. } => Err(VertexError::NoneToSpare),
            Curve::Polyline { points, arcs, closed } => {
                let n = points.len();
                let (i, d) = self.nearest_vertex(p).unwrap();
                if d > VERTEX_REACH {
                    return Err(VertexError::NoVertexNear(r2(d)));
                }
                if (!*closed && n <= 2) || (*closed && n <= 3) {
                    return Err(VertexError::NoneToSpare);
                }
                let ns = self.segments().len();
                let mut ar: Vec<f64> = if arcs.is_empty() { vec![0.0; ns] } else { arcs.clone() };
                let mut pts = points.clone();
                if !*closed && (i == 0 || i == n - 1) {
                    pts.remove(i);
                    if i == 0 {
                        ar.remove(0);
                    } else {
                        ar.pop();
                    }
                    return Ok(Curve::polyline(pts, ar, false));
                }
                // the segments before and after the corner become one
                let before = if i == 0 { ns - 1 } else { i - 1 };
                let after = i;
                let (x, y) = (ar[before], ar[after]);
                let merged = if x == 0.0 || y == 0.0 { 0.0 } else { x + y };
                if merged.abs() >= 360.0 {
                    return Err(VertexError::NoneToSpare);
                }
                pts.remove(i);
                if i == 0 {
                    ar.remove(0);
                    let last = ar.len() - 1;
                    ar[last] = merged;
                } else {
                    ar[before] = merged;
                    ar.remove(after);
                }
                Ok(Curve::polyline(pts, ar, *closed))
            }
            Curve::Spline { control, knots } => {
                let n = control.len();
                let (i, d) = self.nearest_vertex(p).unwrap();
                if d > VERTEX_REACH {
                    return Err(VertexError::NoVertexNear(r2(d)));
                }
                if n <= 2 {
                    return Err(VertexError::NoneToSpare);
                }
                let mut c = control.clone();
                c.remove(i);
                // its own knots lose one inside it (where the control point was); with none inside,
                // it is a Bézier of a degree less, by uniform knots
                let k = knots.as_ref().and_then(|k| {
                    let p = k.len() - n - 1;
                    if n - p - 1 == 0 {
                        return None;
                    }
                    let mut k = k.clone();
                    k.remove((i + 1).clamp(p + 1, n - 1));
                    Some(k)
                });
                Ok(Curve::Spline { control: c, knots: k })
            }
            Curve::Fitted { fit, start_tangent, end_tangent } => {
                let (i, d) = self.nearest_vertex(p).unwrap();
                if d > VERTEX_REACH {
                    return Err(VertexError::NoVertexNear(r2(d)));
                }
                if fit.len() <= 2 {
                    return Err(VertexError::NoneToSpare);
                }
                let mut f = fit.clone();
                f.remove(i);
                Ok(Curve::Fitted { fit: f, start_tangent: *start_tangent, end_tangent: *end_tangent })
            }
        }
    }

    /// A closed polyline starting at its corner `c` instead.
    pub fn rotated_to(&self, c: usize) -> Curve {
        match self {
            Curve::Polyline { points, arcs, closed: true } => {
                let n = points.len();
                let pts: Vec<P2> = (0..n).map(|k| points[(c + k) % n]).collect();
                let ar: Vec<f64> = if arcs.is_empty() { Vec::new() } else { (0..n).map(|k| arcs[(c + k) % n]).collect() };
                Curve::Polyline { points: pts, arcs: ar, closed: true }
            }
            x => x.clone(),
        }
    }
}

/// A distance rounded to the hundredth, as messages give it.
pub fn r2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

// ---------------------------------------------------------------- splitting

/// What cutting a curve gives.
#[derive(Clone, Debug)]
pub enum Cut {
    /// Two curves, the first from its start to the cut.
    Two(Curve, Curve),
    /// A closed curve opened at the cut: one that starts and ends there.
    Opened(Curve),
}

impl Curve {
    /// Cuts a polyline at its corner `v`: two polylines, or a closed one opened there.
    pub fn cut_at_vertex(&self, v: usize) -> Option<Cut> {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                let n = points.len();
                let segs = self.segments().len();
                let arc_of = |i: usize| if arcs.is_empty() { 0.0 } else { arcs[i] };
                if *closed {
                    let mut pts: Vec<P2> = (0..n).map(|k| points[(v + k) % n]).collect();
                    pts.push(points[v % n]);
                    let ar: Vec<f64> = (0..n).map(|k| arc_of((v + k) % n)).collect();
                    return Some(Cut::Opened(Curve::polyline(pts, ar, false)));
                }
                if v == 0 || v >= n - 1 {
                    return None;
                }
                let p1 = points[..=v].to_vec();
                let a1 = (0..v).map(arc_of).collect();
                let p2 = points[v..].to_vec();
                let a2 = (v..segs).map(arc_of).collect();
                Some(Cut::Two(Curve::polyline(p1, a1, false), Curve::polyline(p2, a2, false)))
            }
            _ => None,
        }
    }

    /// Cuts it at a parameter (a segment and a fraction along it for a polyline).
    pub fn cut(&self, seg: usize, f: f64) -> Option<Cut> {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                let segs = self.segments();
                if f <= 0.0 {
                    return self.cut_at_vertex(seg);
                }
                if f >= 1.0 {
                    return self.cut_at_vertex((seg + 1) % points.len());
                }
                let s = segs[seg];
                let q = s.at(f);
                let a_first = s.arc * f;
                let a_second = s.arc * (1.0 - f);
                let ns = segs.len();
                let arc_of = |i: usize| if arcs.is_empty() { 0.0 } else { arcs[i] };
                if *closed {
                    let n = points.len();
                    let mut pts = vec![q];
                    let mut ar = vec![a_second];
                    for k in 1..=n {
                        let i = (seg + k) % n;
                        pts.push(points[i]);
                        if k < n {
                            ar.push(arc_of(i));
                        }
                    }
                    ar.push(a_first);
                    pts.push(q);
                    return Some(Cut::Opened(Curve::polyline(pts, ar, false)));
                }
                let mut p1: Vec<P2> = points[..=seg].to_vec();
                let mut a1: Vec<f64> = (0..seg).map(arc_of).collect();
                p1.push(q);
                a1.push(a_first);
                let mut p2 = vec![q];
                let mut a2 = vec![a_second];
                p2.extend_from_slice(&points[seg + 1..]);
                a2.extend((seg + 1..ns).map(arc_of));
                Some(Cut::Two(Curve::polyline(p1, a1, false), Curve::polyline(p2, a2, false)))
            }
            Curve::Circle { centre, radius } => {
                let a = 2.0 * PI * f;
                let (s, c) = a.sin_cos();
                let q = [centre[0] + radius * c, centre[1] + radius * s];
                let o = [centre[0] - radius * c, centre[1] - radius * s];
                Some(Cut::Opened(Curve::Polyline { points: vec![q, o, q], arcs: vec![180.0, 180.0], closed: false }))
            }
            Curve::Ellipse { centre, radii, angle, span } => {
                let (a0, sw) = self.ellipse_span_deg();
                let t = a0 + sw * f;
                match span {
                    None => Some(Cut::Opened(Curve::Ellipse {
                        centre: *centre,
                        radii: *radii,
                        angle: *angle,
                        span: Some([t, t + 360.0]),
                    })),
                    Some([s0, s1]) => Some(Cut::Two(
                        Curve::Ellipse { centre: *centre, radii: *radii, angle: *angle, span: Some([*s0, t]) },
                        Curve::Ellipse { centre: *centre, radii: *radii, angle: *angle, span: Some([t, *s1]) },
                    )),
                }
            }
            Curve::Spline { control, knots } => {
                let b = Bspline::new(control, knots.as_deref());
                let p = b.degree;
                let have = b.multiplicity(f);
                let nb = if have < p { b.insert_knot(f, p - have) } else { b.clone() };
                // the knot at f now comes p times: the halves share the control point there
                let first = nb.knots.iter().position(|x| *x == f)?;
                let n1 = first; // control points of the first half
                let c1: Vec<P2> = nb.control[..n1].to_vec();
                let c2: Vec<P2> = nb.control[n1 - 1..].to_vec();
                let mut k1: Vec<f64> = nb.knots[..first + p].to_vec();
                k1.push(f);
                let mut k2: Vec<f64> = vec![f];
                k2.extend_from_slice(&nb.knots[first..]);
                Some(Cut::Two(Curve::Spline { control: c1, knots: Some(k1) }, Curve::Spline { control: c2, knots: Some(k2) }))
            }
            Curve::Fitted { start_tangent, end_tangent, .. } => {
                // each half refitted to the curve as it was, its direction kept where it is cut
                let b = self.fitted_bspline();
                let tan = unit(b.derivative().at(f));
                let (u0, u1) = (b.u0(), b.u1());
                let at = |u: f64| b.at(u);
                let left = refit_with(&at, u0, f, *start_tangent, Some(tan), &[], false);
                let right = refit_with(&at, f, u1, Some(tan), *end_tangent, &[], false);
                Some(Cut::Two(left, right))
            }
        }
    }

    /// Cuts it where it passes nearest `p`, as `split` does: within VERTEX_REACH of it; an open
    /// curve not within a millimetre of its ends; a polyline at its corner within a millimetre; a
    /// closed curve opened there.
    pub fn split_at(&self, p: P2) -> Result<(Near, Cut), VertexError> {
        let near = self.nearest(p);
        if near.dist > VERTEX_REACH {
            return Err(VertexError::TooFar(r2(near.dist)));
        }
        let q = near.point;
        if !self.is_closed() {
            let (a, b) = (self.start_point(), self.end_point());
            if dist(q, a) <= 1.0 || dist(q, b) <= 1.0 {
                return Err(VertexError::NotBetweenEnds);
            }
        }
        if let Curve::Polyline { points, .. } = self {
            let s = self.segments()[near.seg];
            let v = if dist(q, s.a) <= 1.0 {
                Some(near.seg)
            } else if dist(q, s.b) <= 1.0 {
                Some((near.seg + 1) % points.len())
            } else {
                None
            };
            if let Some(v) = v {
                return self.cut_at_vertex(v).map(|c| (near, c)).ok_or(VertexError::NotBetweenEnds);
            }
        }
        let cut = self.cut_near(&near).ok_or(VertexError::NotBetweenEnds)?;
        Ok((near, cut))
    }

    /// Cuts it where `nearest` found: a circle and an ellipse at the angle it found (degrees), the
    /// others as `cut` does.
    pub fn cut_near(&self, near: &Near) -> Option<Cut> {
        match self {
            Curve::Circle { centre, radius } => {
                let (s, c) = near.param.to_radians().sin_cos();
                let q = [centre[0] + radius * c, centre[1] + radius * s];
                let o = [centre[0] - radius * c, centre[1] - radius * s];
                Some(Cut::Opened(Curve::Polyline { points: vec![q, o, q], arcs: vec![180.0, 180.0], closed: false }))
            }
            Curve::Ellipse { centre, radii, angle, span } => {
                let t = near.param;
                let e = |sp: [f64; 2]| Curve::Ellipse { centre: *centre, radii: *radii, angle: *angle, span: Some(sp) };
                match span {
                    None => Some(Cut::Opened(e([t, t + 360.0]))),
                    Some([s0, s1]) => Some(Cut::Two(e([*s0, t]), e([t, *s1]))),
                }
            }
            _ => self.cut(near.seg, near.f),
        }
    }
}

// ---------------------------------------------------------------- joining

/// Joins curves (lines, arcs, open polylines) that meet end to end, within `tol`, into one
/// polyline in the order they chain from the first: each next one at the chain's end, else at its
/// start, turned round as it must be; closed when its ends come together.
pub fn join(curves: &[Curve], tol: f64) -> Option<Curve> {
    let mut pts: Vec<P2> = Vec::new();
    let mut arcs: Vec<f64> = Vec::new();
    // a piece's points and its arcs (none: all straight)
    let take = |c: &Curve| -> Option<(Vec<P2>, Vec<f64>)> {
        match c {
            Curve::Polyline { points, arcs, closed: false } => Some((points.clone(), arcs.clone())),
            _ => None,
        }
    };
    let fill = |p: &[P2], a: Vec<f64>| -> Vec<f64> { if a.is_empty() { vec![0.0; p.len() - 1] } else { a } };
    let (p0, a0) = take(curves.first()?)?;
    let a0 = fill(&p0, a0);
    pts.extend(p0);
    arcs.extend(a0);
    let mut left: Vec<(Vec<P2>, Vec<f64>)> = Vec::new();
    for c in &curves[1..] {
        left.push(take(c)?);
    }
    while !left.is_empty() {
        let mut found = None;
        for (k, (p, _)) in left.iter().enumerate() {
            let (s, e) = (pts[0], *pts.last().unwrap());
            let (ps, pe) = (p[0], *p.last().unwrap());
            if dist(e, ps) <= tol {
                found = Some((k, 0));
            } else if dist(e, pe) <= tol {
                found = Some((k, 1));
            } else if dist(s, pe) <= tol {
                found = Some((k, 2));
            } else if dist(s, ps) <= tol {
                found = Some((k, 3));
            }
            if found.is_some() {
                break;
            }
        }
        let (k, how) = found?;
        let (mut p, mut a) = left.remove(k);
        if how == 1 || how == 3 {
            p.reverse();
            a.reverse();
            for x in a.iter_mut() {
                *x = -*x;
            }
        }
        let a = fill(&p, a);
        if how <= 1 {
            pts.extend_from_slice(&p[1..]);
            arcs.extend(a);
        } else {
            pts.remove(0);
            let mut np = p;
            np.extend(pts);
            pts = np;
            let mut na = a;
            na.extend(arcs);
            arcs = na;
        }
    }
    // three segments or more that come round close; two coming back stay open
    let closed = pts.len() > 3 && dist(pts[0], *pts.last().unwrap()) <= tol;
    if closed {
        pts.pop();
    }
    Some(Curve::polyline(pts, arcs, closed))
}

// ---------------------------------------------------------------- lines and circles meeting

/// A line or an arc run on along its line or circle: what trimming meets.
#[derive(Clone, Copy, Debug)]
pub enum Carrier {
    /// The line through `a` and `b`.
    Line(P2, P2),
    /// The circle round `c` of radius `r`.
    Circle(P2, f64),
}

/// Where two carriers cross (none for parallel lines, circles apart or touching).
pub fn meet(x: Carrier, y: Carrier) -> Vec<P2> {
    match (x, y) {
        (Carrier::Line(a, b), Carrier::Line(c, d)) => {
            let r = sub(b, a);
            let s = sub(d, c);
            let den = cross(r, s);
            if den.abs() <= 1e-12 * norm(r) * norm(s) {
                return Vec::new();
            }
            let t = cross(sub(c, a), s) / den;
            vec![add(a, mul(r, t))]
        }
        (Carrier::Line(a, b), Carrier::Circle(c, r)) | (Carrier::Circle(c, r), Carrier::Line(a, b)) => {
            let d = unit(sub(b, a));
            let f = sub(a, c);
            let along = -dot(f, d);
            let foot = add(a, mul(d, along));
            let (fx, fy) = (foot[0] - c[0], foot[1] - c[1]);
            let h2 = r * r - (fx * fx + fy * fy);
            if h2 <= 0.0 {
                return Vec::new();
            }
            let h = h2.sqrt();
            vec![sub(foot, mul(d, h)), add(foot, mul(d, h))]
        }
        (Carrier::Circle(c1, r1), Carrier::Circle(c2, r2)) => {
            let d = dist(c1, c2);
            if d == 0.0 || d >= r1 + r2 || d <= (r1 - r2).abs() {
                return Vec::new();
            }
            let a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d);
            let h = (r1 * r1 - a * a).max(0.0).sqrt();
            let u = unit(sub(c2, c1));
            let m = add(c1, mul(u, a));
            let n = [-u[1], u[0]];
            vec![sub(m, mul(n, h)), add(m, mul(n, h))]
        }
    }
}

impl Curve {
    /// A line's or an arc's carrier (None for other shapes).
    pub fn carrier(&self) -> Option<Carrier> {
        match self {
            Curve::Polyline { points, arcs, closed: false } if points.len() == 2 => {
                match arc_geo(points[0], points[1], arcs.first().copied().unwrap_or(0.0)) {
                    Some(g) => Some(Carrier::Circle(g.centre, g.radius)),
                    None => Some(Carrier::Line(points[0], points[1])),
                }
            }
            _ => None,
        }
    }
}

// ---------------------------------------------------------------- offsets

impl Curve {
    /// The curve drawn again `d` mm to its left (negative: its right): lines and arcs beside
    /// themselves (arcs round the same centres), a polyline's sides moved and its corners where
    /// they meet, a circle grown or shrunk; ellipses and splines as a spline through points within
    /// FIT_TOL of the true offset. None where it would turn inside out or fold over itself.
    pub fn offset(&self, d: f64) -> Option<Curve> {
        match self {
            Curve::Polyline { points, arcs, closed } => {
                let segs = self.segments();
                let moved: Vec<Seg> = segs.iter().map(|s| offset_seg(s, d)).collect::<Option<Vec<_>>>()?;
                let n = moved.len();
                let mut pts: Vec<P2> = Vec::new();
                let mut ar: Vec<f64> = Vec::new();
                // corners: where each moved side meets the next
                let corner = |i: usize, j: usize| -> Option<(P2, usize)> {
                    let (s, t) = (&moved[i], &moved[j]);
                    let cs = seg_carrier(s);
                    let ct = seg_carrier(t);
                    let cands = meet(cs, ct);
                    if cands.is_empty() {
                        // parallel or tangent: where they touch
                        if dist(s.b, t.a) < 1e-6 {
                            return Some((s.b, 0));
                        }
                        return None;
                    }
                    // the crossing nearest the moved sides' common end
                    let target = mid(s.b, t.a);
                    let mut best = cands[0];
                    for c in &cands {
                        if dist(*c, target) < dist(best, target) {
                            best = *c;
                        }
                    }
                    Some((best, 0))
                };
                // a corner sharper than this folds the offset over itself
                let tan_in = |s: &Seg| -> P2 {
                    match s.geo() {
                        None => unit(sub(s.b, s.a)),
                        Some(g) => {
                            let r = unit(sub(s.b, g.centre));
                            if g.turn > 0.0 {
                                [-r[1], r[0]]
                            } else {
                                [r[1], -r[0]]
                            }
                        }
                    }
                };
                let tan_out = |s: &Seg| -> P2 {
                    match s.geo() {
                        None => unit(sub(s.b, s.a)),
                        Some(g) => {
                            let r = unit(sub(s.a, g.centre));
                            if g.turn > 0.0 {
                                [-r[1], r[0]]
                            } else {
                                [r[1], -r[0]]
                            }
                        }
                    }
                };
                let sharp = |i: usize, j: usize| -> bool {
                    let (u, v) = (tan_in(&segs[i]), tan_out(&segs[j]));
                    let deflect = cross(u, v).abs().atan2(dot(u, v));
                    PI - deflect < FOLD_ANGLE
                };
                for i in 0..n {
                    let j = i + 1;
                    if (j < n && sharp(i, j)) || (j == n && *closed && sharp(i, 0)) {
                        return None;
                    }
                }
                let mut starts: Vec<P2> = moved.iter().map(|s| s.a).collect();
                let mut ends: Vec<P2> = moved.iter().map(|s| s.b).collect();
                for i in 0..n {
                    let j = i + 1;
                    if j < n {
                        let (c, _) = corner(i, j)?;
                        ends[i] = c;
                        starts[j] = c;
                    } else if *closed {
                        let (c, _) = corner(i, 0)?;
                        ends[i] = c;
                        starts[0] = c;
                    }
                }
                for i in 0..n {
                    let s = &moved[i];
                    let a = starts[i];
                    let b = ends[i];
                    let turn = match s.geo() {
                        None => {
                            // the side must still run the way it did
                            if dot(sub(b, a), sub(segs[i].b, segs[i].a)) <= 0.0 {
                                return None;
                            }
                            0.0
                        }
                        Some(g) => {
                            let a0 = (a[1] - g.centre[1]).atan2(a[0] - g.centre[0]);
                            let a1 = (b[1] - g.centre[1]).atan2(b[0] - g.centre[0]);
                            let mut t = a1 - a0;
                            if g.turn > 0.0 {
                                t = t.rem_euclid(2.0 * PI);
                            } else {
                                t = -(-t).rem_euclid(2.0 * PI);
                            }
                            if (t - g.turn).abs() > PI {
                                return None;
                            }
                            t.to_degrees()
                        }
                    };
                    pts.push(r3p(a));
                    ar.push(turn);
                    if i == n - 1 && !*closed {
                        pts.push(r3p(b));
                    }
                }
                let _ = (points, arcs);
                let c = Curve::polyline(pts, ar, *closed);
                c.check().ok()?;
                Some(c)
            }
            Curve::Circle { centre, radius } => {
                // a circle runs counter-clockwise: its left is inside
                let r = radius - d;
                if r <= 1.0 {
                    return None;
                }
                Some(Curve::Circle { centre: *centre, radius: r })
            }
            _ => {
                let (u0, u1) = self.param_range();
                let me = self.clone();
                let at = move |u: f64| -> P2 {
                    let p = me.at(0, u);
                    let t = me.tangent(u);
                    [p[0] - t[1] * d, p[1] + t[0] * d]
                };
                let (st, et) = end_tangents(&at, u0, u1);
                // the tangents kept to 1e-9, as a curve's directions are
                let (st, et) = ([r9(st[0]), r9(st[1])], [r9(et[0]), r9(et[1])]);
                let eighths: Vec<f64> = (1..8).map(|k| u0 + (u1 - u0) * k as f64 / 8.0).collect();
                let fc = refit(&at, u0, u1, Some(st), Some(et), &eighths);
                fc.check().ok()?;
                Some(fc)
            }
        }
    }

    /// The range of its parameter (an ellipse's and a circle's fraction, a spline's knots).
    pub fn param_range(&self) -> (f64, f64) {
        match self {
            Curve::Spline { control, knots } => {
                let b = Bspline::new(control, knots.as_deref());
                (b.u0(), b.u1())
            }
            Curve::Fitted { .. } => {
                let b = self.fitted_bspline();
                (b.u0(), b.u1())
            }
            _ => (0.0, 1.0),
        }
    }

    /// The parameters where a spline's pieces meet (its knots inside it).
    pub fn breaks(&self) -> Vec<f64> {
        let b = match self {
            Curve::Spline { control, knots } => Bspline::new(control, knots.as_deref()),
            Curve::Fitted { .. } => self.fitted_bspline(),
            _ => return Vec::new(),
        };
        let n = b.control.len();
        let mut v: Vec<f64> = b.knots[b.degree + 1..n].to_vec();
        v.dedup();
        v
    }

    /// The unit tangent at a parameter of an ellipse or a spline.
    pub fn tangent(&self, u: f64) -> P2 {
        match self {
            Curve::Ellipse { .. } => {
                let (a0, swd) = self.ellipse_span_deg();
                unit(self.ellipse_d1((a0 + swd * u).to_radians()))
            }
            Curve::Spline { control, knots } => unit(Bspline::new(control, knots.as_deref()).derivative().at(u)),
            Curve::Fitted { .. } => unit(self.fitted_bspline().derivative().at(u)),
            Curve::Circle { .. } => {
                let a = 2.0 * PI * u;
                [-a.sin(), a.cos()]
            }
            Curve::Polyline { .. } => [1.0, 0.0],
        }
    }

    /// Which side of it a point is: positive on its left.
    pub fn side_of(&self, p: P2) -> f64 {
        let near = self.nearest(p);
        match self {
            Curve::Polyline { .. } => {
                let s = self.segments()[near.seg];
                match s.geo() {
                    None => cross(sub(s.b, s.a), sub(p, s.a)),
                    Some(g) => {
                        // left of a counter-clockwise arc is inside its circle
                        let inside = dist(p, g.centre) <= g.radius;
                        let l = if g.turn > 0.0 { inside } else { !inside };
                        if l {
                            1.0
                        } else {
                            -1.0
                        }
                    }
                }
            }
            Curve::Circle { centre, radius } => {
                if dist(p, *centre) <= *radius {
                    1.0
                } else {
                    -1.0
                }
            }
            _ => {
                let t = self.tangent(near.f);
                let v = sub(p, near.point);
                let c = cross(t, v);
                if c == 0.0 {
                    1.0
                } else {
                    c
                }
            }
        }
    }
}

/// A segment moved `d` to its left (an arc: concentric).
fn offset_seg(s: &Seg, d: f64) -> Option<Seg> {
    match s.geo() {
        None => {
            let n = left_normal(s.a, s.b);
            Some(Seg { a: add(s.a, mul(n, d)), b: add(s.b, mul(n, d)), arc: 0.0 })
        }
        Some(g) => {
            // left of a counter-clockwise arc is toward its centre
            let r = if g.turn > 0.0 { g.radius - d } else { g.radius + d };
            if r <= 0.0 {
                return None;
            }
            let k = r / g.radius;
            let a = add(g.centre, mul(sub(s.a, g.centre), k));
            let b = add(g.centre, mul(sub(s.b, g.centre), k));
            Some(Seg { a, b, arc: s.arc })
        }
    }
}

fn seg_carrier(s: &Seg) -> Carrier {
    match s.geo() {
        None => Carrier::Line(s.a, s.b),
        Some(g) => Carrier::Circle(g.centre, g.radius),
    }
}
