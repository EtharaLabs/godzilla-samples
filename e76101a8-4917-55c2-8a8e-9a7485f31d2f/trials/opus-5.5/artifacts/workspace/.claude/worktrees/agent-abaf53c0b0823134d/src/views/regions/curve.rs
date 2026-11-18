//! A curve as a detail line, a group member or a region's boundary line holds it: a line, an
//! arc, a polyline (with arcs, closed or not), a circle, an ellipse (part of one with `span`), a
//! spline by its control points or through fit points. The points it is drawn with (its chords),
//! its bounds, and how its fields move, turn and mirror.
//!
//! The LINES part keeps its own model of these in `curves.rs`; this is the one the regions, the
//! groups and the patterns made of lines read.

use crate::json::{Map, Value};

pub type P = [f64; 2];

/// How far a chord may lie from its curve, in mm.
pub const TOL: f64 = 0.25;
/// The most points one curve is drawn with.
pub const MAX_POINTS: usize = 8192;
/// How far from the origin a point may lie, in mm.
pub const REACH: f64 = 1e9;

#[derive(Clone, Debug, PartialEq)]
pub enum Shape {
    Line(P, P),
    /// From, to, turning so many degrees counter-clockwise.
    Arc(P, P, f64),
    /// Points, each segment's turn (missing ones straight), closed.
    Poly(Vec<P>, Vec<f64>, bool),
    Circle(P, f64),
    /// Centre, radii, angle in degrees, span in degrees of its parameter.
    Ellipse(P, [f64; 2], f64, Option<[f64; 2]>),
    /// Control points, knots.
    Spline(Vec<P>, Option<Vec<f64>>),
    /// Fit points, start and end tangents.
    Fit(Vec<P>, Option<P>, Option<P>),
}

// ---------------------------------------------------------------- reading fields

fn num(v: Option<&Value>) -> Option<f64> {
    v.and_then(|x| x.as_f64())
}

pub fn pt(v: Option<&Value>) -> Option<P> {
    let a = v?.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn pts(v: Option<&Value>) -> Option<Vec<P>> {
    let a = v?.as_arr()?;
    a.iter().map(|p| pt(Some(p))).collect()
}

fn nums(v: Option<&Value>) -> Option<Vec<f64>> {
    let a = v?.as_arr()?;
    a.iter().map(|x| x.as_f64()).collect()
}

fn has(e: &Value, k: &str) -> bool {
    matches!(e.get(k), Some(x) if !x.is_null())
}

impl Shape {
    /// The curve the fields of an element, a member or a boundary line give.
    pub fn from_fields(e: &Value) -> Option<Shape> {
        if has(e, "points") {
            let p = pts(e.get("points"))?;
            let arcs = nums(e.get("arcs")).unwrap_or_default();
            let closed = e.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
            return Some(Shape::Poly(p, arcs, closed));
        }
        if has(e, "centre") {
            let c = pt(e.get("centre"))?;
            if has(e, "radii") {
                let r = pt(e.get("radii"))?;
                let span = pt(e.get("span"));
                return Some(Shape::Ellipse(c, r, num(e.get("angle")).unwrap_or(0.0), span));
            }
            return Some(Shape::Circle(c, num(e.get("radius"))?));
        }
        if has(e, "control") {
            return Some(Shape::Spline(pts(e.get("control"))?, nums(e.get("knots"))));
        }
        if has(e, "fit") {
            return Some(Shape::Fit(pts(e.get("fit"))?, pt(e.get("start_tangent")), pt(e.get("end_tangent"))));
        }
        let a = pt(e.get("start"))?;
        let b = pt(e.get("end"))?;
        match num(e.get("arc")) {
            Some(t) if t != 0.0 => Some(Shape::Arc(a, b, t)),
            _ => Some(Shape::Line(a, b)),
        }
    }

    /// Whether it closes on itself (a circle, a whole ellipse, a closed polyline).
    pub fn is_closed(&self) -> bool {
        match self {
            Shape::Circle(..) => true,
            Shape::Ellipse(_, _, _, span) => span.is_none(),
            Shape::Poly(_, _, closed) => *closed,
            _ => false,
        }
    }

    /// Its ends, where it is open.
    pub fn ends(&self) -> Option<(P, P)> {
        if self.is_closed() {
            return None;
        }
        let d = self.drawn();
        Some((*d.first()?, *d.last()?))
    }

    /// The points it is drawn with, in order; a closed one's first point again at its end.
    pub fn drawn(&self) -> Vec<P> {
        match self {
            Shape::Line(a, b) => vec![*a, *b],
            Shape::Arc(a, b, t) => arc_points(*a, *b, *t),
            Shape::Poly(p, arcs, closed) => {
                let mut out: Vec<P> = Vec::new();
                if p.is_empty() {
                    return out;
                }
                out.push(p[0]);
                let n = p.len();
                let segs = if *closed { n } else { n.saturating_sub(1) };
                for i in 0..segs {
                    let a = p[i];
                    let b = p[(i + 1) % n];
                    let t = arcs.get(i).copied().unwrap_or(0.0);
                    if t != 0.0 {
                        let ap = arc_points(a, b, t);
                        out.extend_from_slice(&ap[1..]);
                    } else {
                        out.push(b);
                    }
                }
                out
            }
            Shape::Circle(c, r) => {
                let n = circle_segments(r.abs());
                (0..=n)
                    .map(|k| {
                        let t = (k as f64 * 360.0 / n as f64).to_radians();
                        [c[0] + r * t.cos(), c[1] + r * t.sin()]
                    })
                    .collect()
            }
            Shape::Ellipse(c, radii, angle, span) => ellipse_points(*c, *radii, *angle, *span),
            Shape::Spline(ctrl, knots) => spline_points(ctrl, knots.as_deref()),
            Shape::Fit(fit, t0, t1) => fit_points(fit, *t0, *t1),
        }
    }
}

// ---------------------------------------------------------------- arcs and circles

/// The step in radians a chord of a circle of radius `r` may turn within the tolerance.
fn sag_step(r: f64) -> f64 {
    let x = 1.0 - TOL / r;
    if x <= -1.0 {
        std::f64::consts::PI
    } else {
        2.0 * x.acos()
    }
}

/// How many chords a curve turning `sweep` radians on a circle of radius `r` is drawn with:
/// each within the tolerance of it and turning at most 5°.
fn segments(r: f64, sweep: f64) -> usize {
    let s = sweep.abs();
    let n = (s / sag_step(r)).ceil().max((s / 5f64.to_radians()).ceil()).max(1.0);
    if !n.is_finite() || n > MAX_POINTS as f64 {
        MAX_POINTS
    } else {
        n as usize
    }
}

/// How many chords a whole circle of radius `r` is drawn with.
pub fn circle_segments(r: f64) -> usize {
    segments(r, std::f64::consts::TAU).max(3)
}

/// How many chords an arc of radius `r` turning `turn` radians is drawn with: the angle it
/// sweeps worked out as its length over its radius.
pub fn arc_segments(r: f64, turn: f64) -> usize {
    segments(r, (r * turn.abs()) / r)
}

/// The centre and radius of the arc from `a` to `b` turning `deg` degrees counter-clockwise.
pub fn arc_centre(a: P, b: P, deg: f64) -> Option<(P, f64)> {
    let t = deg.to_radians();
    let dx = b[0] - a[0];
    let dy = b[1] - a[1];
    let c = (dx * dx + dy * dy).sqrt();
    if c == 0.0 || t == 0.0 {
        return None;
    }
    let r = c / (2.0 * (t / 2.0).sin().abs());
    let k = 0.5 / (t / 2.0).tan();
    let m = [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0];
    Some(([m[0] - dy * k, m[1] + dx * k], r))
}

/// The points an arc is drawn with, from `a` to `b`.
pub fn arc_points(a: P, b: P, deg: f64) -> Vec<P> {
    let Some((c, r)) = arc_centre(a, b, deg) else { return vec![a, b] };
    if !r.is_finite() {
        return vec![a, b];
    }
    let a0 = (a[1] - c[1]).atan2(a[0] - c[0]);
    let turn = deg.to_radians();
    let n = arc_segments(r, turn);
    let sweep = ((r * turn.abs()) / r) * turn.signum();
    let mut out = Vec::with_capacity(n + 1);
    out.push(a);
    for k in 1..n {
        let t = a0 + sweep * k as f64 / n as f64;
        out.push([c[0] + r * t.cos(), c[1] + r * t.sin()]);
    }
    out.push(b);
    out
}

/// The turn in degrees (counter-clockwise) of the arc from `a` to `b` through `m`; None where
/// the three lie on a line.
pub fn turn_through(a: P, b: P, m: P) -> Option<f64> {
    // the centre of the circle through the three
    let d = 2.0 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]));
    if d == 0.0 {
        return None;
    }
    let a2 = a[0] * a[0] + a[1] * a[1];
    let m2 = m[0] * m[0] + m[1] * m[1];
    let b2 = b[0] * b[0] + b[1] * b[1];
    let cx = (a2 * (m[1] - b[1]) + m2 * (b[1] - a[1]) + b2 * (a[1] - m[1])) / d;
    let cy = (a2 * (b[0] - m[0]) + m2 * (a[0] - b[0]) + b2 * (m[0] - a[0])) / d;
    let ang = |p: P| (p[1] - cy).atan2(p[0] - cx);
    let ta = ang(a);
    let tm = ang(m);
    let tb = ang(b);
    let tau = std::f64::consts::TAU;
    let norm = |x: f64| {
        let mut y = x % tau;
        if y < 0.0 {
            y += tau;
        }
        y
    };
    // counter-clockwise from a: does it pass m before b?
    let to_b = norm(tb - ta);
    let to_m = norm(tm - ta);
    let sweep = if to_m < to_b { to_b } else { to_b - tau };
    let deg = sweep.to_degrees();
    if !deg.is_finite() || deg == 0.0 {
        None
    } else {
        Some(deg)
    }
}

// ---------------------------------------------------------------- ellipses

/// Half the chords an ellipse of major radius `a` is drawn with over `sweep_deg` of its
/// parameter.
fn ellipse_half_steps(a: f64, sweep_deg: f64) -> usize {
    segments(a, sweep_deg.abs().to_radians()).min(MAX_POINTS / 2)
}

pub fn ellipse_points(c: P, radii: [f64; 2], angle: f64, span: Option<[f64; 2]>) -> Vec<P> {
    let a = radii[0];
    let b = radii[1];
    let big = a.abs().max(b.abs());
    let (ca, sa) = (angle.to_radians().cos(), angle.to_radians().sin());
    let at = |t: f64| {
        let x = a * t.cos();
        let y = b * t.sin();
        [c[0] + (x * ca - y * sa), c[1] + (x * sa + y * ca)]
    };
    match span {
        None => {
            let n = ellipse_half_steps(big, 360.0) * 2;
            let n = n.min(MAX_POINTS).max(4);
            (0..=n).map(|k| at((k as f64 * 360.0 / n as f64).to_radians())).collect()
        }
        Some([s0, s1]) => {
            // a span runs counter-clockwise: one that ends below its start goes on past 360°
            let mut s1 = s1;
            while s1 < s0 {
                s1 += 360.0;
            }
            let n = (ellipse_half_steps(big, s1 - s0) * 2).min(MAX_POINTS).max(1);
            (0..=n).map(|k| at((s0 + (s1 - s0) * k as f64 / n as f64).to_radians())).collect()
        }
    }
}

// ---------------------------------------------------------------- splines

/// The degree a spline of `n` control points has with these knots (or clamped uniform ones).
pub fn spline_degree(n: usize, knots: Option<&[f64]>) -> usize {
    match knots {
        Some(k) if k.len() > n + 1 && k.len() - n - 1 < n => k.len() - n - 1,
        _ => (n.saturating_sub(1)).min(3).max(1),
    }
}

/// Clamped uniform knots for `n` control points of degree `p`, from 0 to 1.
pub fn clamped_knots(n: usize, p: usize) -> Vec<f64> {
    let mut k = Vec::with_capacity(n + p + 1);
    let inner = n.saturating_sub(p);
    for _ in 0..=p {
        k.push(0.0);
    }
    for i in 1..inner {
        k.push(i as f64 / inner as f64);
    }
    for _ in 0..=p {
        k.push(1.0);
    }
    k
}

fn de_boor(ctrl: &[P], knots: &[f64], p: usize, span: usize, x: f64) -> P {
    let mut d: Vec<P> = (0..=p).map(|j| ctrl[j + span - p]).collect();
    for r in 1..=p {
        for j in (r..=p).rev() {
            let lo = knots[j + span - p];
            let hi = knots[j + 1 + span - r];
            let alpha = if hi - lo == 0.0 { 0.0 } else { (x - lo) / (hi - lo) };
            d[j] = [(1.0 - alpha) * d[j - 1][0] + alpha * d[j][0], (1.0 - alpha) * d[j - 1][1] + alpha * d[j][1]];
        }
    }
    d[p]
}

fn hypot2(v: P) -> f64 {
    (v[0] * v[0] + v[1] * v[1]).sqrt()
}

/// The points a spline by its control points is drawn with: each knot span cut so that its
/// chords lie within the tolerance of it.
pub fn spline_points(ctrl: &[P], knots: Option<&[f64]>) -> Vec<P> {
    if ctrl.len() < 2 {
        return ctrl.to_vec();
    }
    let n = ctrl.len();
    let p = spline_degree(n, knots);
    let kn: Vec<f64> = match knots {
        Some(k) if k.len() == n + p + 1 => k.to_vec(),
        _ => clamped_knots(n, p),
    };
    let mut out: Vec<P> = vec![de_boor(ctrl, &kn, p, p, kn[p])];
    for span in p..n {
        let lo = kn[span];
        let hi = kn[span + 1];
        if hi <= lo {
            continue;
        }
        // the second derivative at the span's ends, by differences
        let h = (hi - lo) * 1e-4;
        let second = |x: f64| {
            let a = de_boor(ctrl, &kn, p, span, x - h);
            let b = de_boor(ctrl, &kn, p, span, x);
            let c = de_boor(ctrl, &kn, p, span, x + h);
            hypot2([(a[0] - 2.0 * b[0] + c[0]) / (h * h), (a[1] - 2.0 * b[1] + c[1]) / (h * h)])
        };
        let m = second(lo + h).max(second(hi - h));
        let segs = if m > 0.0 { ((hi - lo) / (8.0 * TOL / m).sqrt()).ceil().max(1.0) } else { 1.0 };
        let segs = (segs as usize).min(MAX_POINTS);
        for k in 1..=segs {
            let x = lo + (hi - lo) * k as f64 / segs as f64;
            let x = if k == segs { hi - (hi - lo) * 1e-12 } else { x };
            let q = if k == segs && span + 1 == n { *ctrl.last().unwrap() } else { de_boor(ctrl, &kn, p, span, x) };
            out.push(q);
        }
        if out.len() > MAX_POINTS {
            out.truncate(MAX_POINTS);
            break;
        }
    }
    out
}

/// A cubic spline through the points by their chords' lengths: natural at its ends, or leaving
/// and reaching them along the tangents given. Each piece: its ends, their second derivatives,
/// its parameter's length.
fn fit_pieces(fit: &[P], t0: Option<P>, t1: Option<P>) -> Vec<(P, P, P, P, f64)> {
    let n = fit.len();
    let mut out = Vec::new();
    if n < 2 {
        return out;
    }
    let h: Vec<f64> = (0..n - 1).map(|i| hypot2([fit[i + 1][0] - fit[i][0], fit[i + 1][1] - fit[i][1]])).collect();
    if h.iter().any(|x| *x == 0.0) {
        return out;
    }
    let unit = |t: Option<P>| -> Option<P> {
        let t = t?;
        let l = hypot2(t);
        if l == 0.0 {
            None
        } else {
            Some([t[0] / l, t[1] / l])
        }
    };
    let u0 = unit(t0);
    let u1 = unit(t1);
    let mut second: Vec<P> = vec![[0.0, 0.0]; n];
    for dim in 0..2 {
        let y: Vec<f64> = fit.iter().map(|p| p[dim]).collect();
        let mut a = vec![0.0; n];
        let mut b = vec![0.0; n];
        let mut c = vec![0.0; n];
        let mut d = vec![0.0; n];
        match u0 {
            Some(u) => {
                b[0] = 2.0 * h[0];
                c[0] = h[0];
                d[0] = 6.0 * ((y[1] - y[0]) / h[0] - u[dim]);
            }
            None => b[0] = 1.0,
        }
        for i in 1..n - 1 {
            a[i] = h[i - 1];
            b[i] = 2.0 * (h[i - 1] + h[i]);
            c[i] = h[i];
            d[i] = 6.0 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1]);
        }
        match u1 {
            Some(u) => {
                a[n - 1] = h[n - 2];
                b[n - 1] = 2.0 * h[n - 2];
                d[n - 1] = 6.0 * (u[dim] - (y[n - 1] - y[n - 2]) / h[n - 2]);
            }
            None => b[n - 1] = 1.0,
        }
        // the Thomas algorithm
        let mut cp = vec![0.0; n];
        let mut dp = vec![0.0; n];
        cp[0] = c[0] / b[0];
        dp[0] = d[0] / b[0];
        for i in 1..n {
            let m = b[i] - a[i] * cp[i - 1];
            cp[i] = if i < n - 1 { c[i] / m } else { 0.0 };
            dp[i] = (d[i] - a[i] * dp[i - 1]) / m;
        }
        let mut m = vec![0.0; n];
        m[n - 1] = dp[n - 1];
        for i in (0..n - 1).rev() {
            m[i] = dp[i] - cp[i] * m[i + 1];
        }
        for i in 0..n {
            second[i][dim] = m[i];
        }
    }
    for i in 0..n - 1 {
        out.push((fit[i], fit[i + 1], second[i], second[i + 1], h[i]));
    }
    out
}

/// The points a spline through fit points is drawn with: each piece cut so that its chords lie
/// within the tolerance of it.
pub fn fit_points(fit: &[P], t0: Option<P>, t1: Option<P>) -> Vec<P> {
    if fit.len() < 2 {
        return fit.to_vec();
    }
    let pieces = fit_pieces(fit, t0, t1);
    let mut out: Vec<P> = vec![fit[0]];
    for (i, pc) in pieces.iter().enumerate() {
        let (y0, y1, m0, m1, h) = *pc;
        let at = |s: f64| -> P {
            let mut q = [0.0; 2];
            for d in 0..2 {
                let a = (h - s) / h;
                let b = s / h;
                q[d] = a * y0[d] + b * y1[d] + ((a * a * a - a) * m0[d] + (b * b * b - b) * m1[d]) * h * h / 6.0;
            }
            q
        };
        let mmax = hypot2(m0).max(hypot2(m1));
        let segs = if mmax > 0.0 { (h / (8.0 * TOL / mmax).sqrt()).ceil().max(1.0) } else { 1.0 };
        let segs = (segs as usize).min(MAX_POINTS);
        for k in 1..=segs {
            if k == segs {
                out.push(fit[i + 1]);
            } else {
                out.push(at(h * k as f64 / segs as f64));
            }
        }
        if out.len() > MAX_POINTS {
            out.truncate(MAX_POINTS);
            break;
        }
    }
    out
}

// ---------------------------------------------------------------- bounds

/// The south-west and north-east corners round some points.
pub fn bounds(pts: &[P]) -> Option<(P, P)> {
    let mut it = pts.iter();
    let f = *it.next()?;
    let (mut lo, mut hi) = (f, f);
    for p in it {
        lo = [lo[0].min(p[0]), lo[1].min(p[1])];
        hi = [hi[0].max(p[0]), hi[1].max(p[1])];
    }
    Some((lo, hi))
}

// ---------------------------------------------------------------- moving the fields

/// A map of the plane: a turn (and a mirror across the x axis first) and a move, as a group
/// places its members; or a move alone.
#[derive(Clone, Copy, Debug)]
pub struct Place {
    pub at: P,
    pub angle: f64,
    pub mirrored: bool,
    /// A move alone, done as a subtraction-free addition (`p + at`).
    pub shift_only: bool,
}

impl Place {
    /// The frame a group of `at`, `angle` and `mirrored` draws its members in.
    pub fn group(at: P, angle: f64, mirrored: bool) -> Place {
        Place { at, angle, mirrored, shift_only: false }
    }
    /// A move by `-by` (members about their middle): a plain subtraction.
    pub fn minus(by: P) -> Place {
        Place { at: by, angle: 0.0, mirrored: false, shift_only: true }
    }
    fn axes(&self) -> (P, P) {
        let a = self.angle.to_radians();
        let b = (self.angle + 90.0).to_radians();
        let u = [a.cos(), a.sin()];
        let mut v = [b.cos(), b.sin()];
        if self.mirrored {
            v = [-v[0], -v[1]];
        }
        (u, v)
    }
    pub fn point(&self, p: P) -> P {
        if self.shift_only {
            return [p[0] - self.at[0], p[1] - self.at[1]];
        }
        let (u, v) = self.axes();
        [self.at[0] + p[0] * u[0] + p[1] * v[0], self.at[1] + p[0] * u[1] + p[1] * v[1]]
    }
    /// A direction (no move).
    pub fn vector(&self, p: P) -> P {
        if self.shift_only {
            return p;
        }
        let (u, v) = self.axes();
        [p[0] * u[0] + p[1] * v[0], p[0] * u[1] + p[1] * v[1]]
    }
    /// What the map turns an angle into (a mirror reflects it first), from -180° to 180°, to
    /// nine places (a region's pattern).
    pub fn turn(&self, deg: f64) -> f64 {
        let (d, rot) = if self.shift_only { (deg, 0.0) } else { (if self.mirrored { -deg } else { deg }, self.angle) };
        let x = (d + rot).to_radians();
        r9(x.sin().atan2(x.cos()).to_degrees())
    }
    /// What the map turns a note's angle into: it keeps reading the right way round under a
    /// mirror, turning with the group (to within a whole turn); else its direction turns.
    pub fn turn_note(&self, deg: f64) -> f64 {
        if self.flips() {
            return (deg + self.angle) % 360.0;
        }
        let t = deg.to_radians();
        let d = if self.shift_only {
            [t.cos(), t.sin()]
        } else {
            let (u, v) = Place::group(self.at, self.angle, false).axes();
            let c = [t.cos(), t.sin()];
            [c[0] * u[0] + c[1] * v[0], c[0] * u[1] + c[1] * v[1]]
        };
        r9(d[1].atan2(d[0]).to_degrees())
    }
    pub fn flips(&self) -> bool {
        self.mirrored && !self.shift_only
    }
}

/// How far along an ellipse's major axis the point lies that its direction moves as.
const AXIS: f64 = 1e6;

pub fn r3(x: f64) -> f64 {
    let y = (x * 1000.0).round() / 1000.0;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

pub fn r9(x: f64) -> f64 {
    let y = (x * 1e9).round() / 1e9;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

pub fn r6(x: f64) -> f64 {
    let y = (x * 1e6).round() / 1e6;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

fn pval(p: P) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

fn rounded(p: P, round: bool) -> P {
    if round {
        [r3(p[0]), r3(p[1])]
    } else {
        p
    }
}

/// Inserts a key after another (or at the end), keeping its place if it is there.
pub fn insert_after(m: &mut Map, after: &[&str], k: &str, v: Value) {
    if m.contains(k) {
        m.insert(k, v);
        return;
    }
    let mut pos = None;
    for a in after {
        if let Some(i) = m.items.iter().position(|(kk, _)| kk == a) {
            pos = Some(pos.map_or(i, |p: usize| p.max(i)));
        }
    }
    match pos {
        Some(i) => m.items.insert(i + 1, (k.to_string(), v)),
        None => m.items.push((k.to_string(), v)),
    }
}

/// Moves the curve fields of an object (a line, a member line, a boundary line) as `f` says,
/// rounding its points to the micron where `round`: points move, turns flip under a mirror, an
/// ellipse's angle is worked out again from where its major axis went.
pub fn place_curve(m: &mut Map, f: &Place, round: bool) {
    // an ellipse's angle, from its centre and a point a kilometre along its major axis, as they
    // were before they move
    let ellipse = if m.get("radii").map(|v| !v.is_null()).unwrap_or(false) {
        let ang = num(m.get("angle")).unwrap_or(0.0);
        pt(m.get("centre")).map(|c| {
            let t = ang.to_radians();
            (c, [c[0] + AXIS * t.cos(), c[1] + AXIS * t.sin()])
        })
    } else {
        None
    };
    for (k, v) in m.items.iter_mut() {
        match k.as_str() {
            "start" | "end" | "centre" | "through" => {
                if let Some(p) = pt(Some(v)) {
                    *v = pval(rounded(f.point(p), round));
                }
            }
            "points" | "control" | "fit" => {
                if let Some(ps) = pts(Some(v)) {
                    *v = Value::Arr(ps.iter().map(|p| pval(rounded(f.point(*p), round))).collect());
                }
            }
            "start_tangent" | "end_tangent" => {
                if let Some(p) = pt(Some(v)) {
                    *v = pval(rounded(f.vector(p), round));
                }
            }
            "arc" => {
                if f.flips() {
                    if let Some(x) = v.as_f64() {
                        *v = Value::f(-x);
                    }
                }
            }
            "arcs" => {
                if f.flips() {
                    if let Some(a) = nums(Some(v)) {
                        *v = Value::Arr(a.iter().map(|x| Value::f(if *x == 0.0 { *x } else { -*x })).collect());
                    }
                }
            }
            "radii" => {
                if f.flips() {
                    if let Some(r) = pt(Some(v)) {
                        *v = pval([r[0], -r[1]]);
                    }
                }
            }
            _ => {}
        }
    }
    if let Some((c, axis)) = ellipse {
        let c2 = f.point(c);
        let a2 = f.point(axis);
        let c6 = rounded(c2, round);
        let a6 = rounded(a2, round);
        let ang = (a6[1] - c6[1]).atan2(a6[0] - c6[0]).to_degrees();
        if ang == 0.0 {
            m.remove("angle");
        } else {
            insert_after(m, &["radii"], "angle", Value::f(ang));
        }
    }
}
