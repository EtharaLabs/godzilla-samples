//! The curves a sketch line may be: a line, an arc (by its turn or a point it passes through), a
//! polyline of lines and arcs, a circle, an ellipse (or part of one), a spline by control points
//! or through points; each drawn as chords none further than `FLAT` from it.

use super::*;

/// How far a chord may stray from its curve, mm.
pub const FLAT: f64 = 0.25;
/// The farthest a curve reaches from the origin, mm.
pub const MAX_COORD: f64 = 1e9;

#[derive(Clone, Debug)]
pub enum Curve {
    Line(P2, P2),
    /// From a to b turning `deg` degrees (counter-clockwise positive).
    Arc(P2, P2, f64),
    Poly { pts: Vec<P2>, arcs: Vec<f64>, closed: bool },
    Circle { c: P2, r: f64 },
    Ellipse { c: P2, rx: f64, ry: f64, angle: f64, span: Option<(f64, f64)> },
    Spline { control: Vec<P2>, knots: Option<Vec<f64>> },
    Fit { pts: Vec<P2>, t0: Option<P2>, t1: Option<P2> },
}

/// The turn (degrees) of the arc from a to b through t; None when the three are in a line.
pub fn turn_through(a: P2, b: P2, t: P2) -> Option<f64> {
    let ta = sub(a, t);
    let tb = sub(b, t);
    let cr = cross(ta, tb);
    if cr == 0.0 {
        return None;
    }
    let ang = cr.atan2(dot(ta, tb));
    let mag = (2.0 * (std::f64::consts::PI - ang.abs())).to_degrees();
    Some(if ang > 0.0 { -mag } else { mag })
}

/// How many chords an arc of this radius turning `sweep` radians takes.
pub fn chords(radius: f64, sweep: f64) -> usize {
    if !(radius > FLAT) {
        return ((sweep.abs() / (std::f64::consts::PI / 2.0)).ceil() as usize).max(1);
    }
    let step = 2.0 * (1.0 - FLAT / radius).acos();
    let n = (sweep.abs() / step).ceil();
    if n.is_finite() && n >= 1.0 {
        (n as usize).min(1_000_000)
    } else {
        1
    }
}

/// An arc's chord points from a to b turning `deg` degrees, its ends exactly a and b.
pub fn arc_points(a: P2, b: P2, deg: f64) -> Vec<P2> {
    if straight(deg) || a == b {
        return vec![a, b];
    }
    let arc = Arc::new(a, b, deg);
    let n = chords(arc.radius, arc.sweep);
    let mut out = Vec::with_capacity(n + 1);
    out.push(a);
    for i in 1..n {
        let ang = arc.a0 + arc.sweep * i as f64 / n as f64;
        out.push([arc.centre[0] + arc.radius * ang.cos(), arc.centre[1] + arc.radius * ang.sin()]);
    }
    out.push(b);
    out
}

impl Curve {
    /// Why it can't be drawn, as the problem says it ("a line needs two points or more, not 1").
    pub fn undrawable(&self) -> Option<String> {
        let far = |p: &P2| !(p[0].is_finite() && p[1].is_finite() && p[0].abs() <= MAX_COORD && p[1].abs() <= MAX_COORD);
        match self {
            Curve::Line(a, b) => {
                if far(a) || far(b) {
                    return Some(String::new());
                }
            }
            Curve::Arc(a, b, deg) => {
                if far(a) || far(b) {
                    return Some(String::new());
                }
                if !(deg.abs() < 360.0) {
                    return Some(format!("an arc turns {}°; it turns less than a whole circle, either way", deg));
                }
            }
            Curve::Poly { pts, arcs, .. } => {
                if pts.len() < 2 {
                    return Some(format!("a line needs two points or more, not {}", pts.len()));
                }
                if pts.iter().any(far) {
                    return Some(String::new());
                }
                for a in arcs {
                    if !(a.abs() < 360.0) {
                        return Some(format!("an arc turns {}°; it turns less than a whole circle, either way", a));
                    }
                }
            }
            Curve::Circle { c, r } => {
                if far(c) {
                    return Some(String::new());
                }
                if !(*r > 1.0 && *r <= MAX_COORD) {
                    return Some(format!("its radius is {} mm; it's more than 1 mm and at most 1000000000", r));
                }
            }
            Curve::Ellipse { c, rx, ry, .. } => {
                if far(c) {
                    return Some(String::new());
                }
                for r in [rx, ry] {
                    if !(*r > 1.0 && *r <= MAX_COORD) {
                        return Some(format!("its radius is {} mm; it's more than 1 mm and at most 1000000000", r));
                    }
                }
            }
            Curve::Spline { control, .. } => {
                if control.len() < 2 {
                    return Some(format!("a line needs two points or more, not {}", control.len()));
                }
                if control.iter().any(far) {
                    return Some(String::new());
                }
            }
            Curve::Fit { pts, .. } => {
                if pts.len() < 2 {
                    return Some(format!("a line needs two points or more, not {}", pts.len()));
                }
                if pts.iter().any(far) {
                    return Some(String::new());
                }
            }
        }
        None
    }

    /// Whether it closes on itself (a circle, a closed polyline, a whole ellipse).
    pub fn closed(&self) -> bool {
        match self {
            Curve::Circle { .. } => true,
            Curve::Ellipse { span, .. } => span.is_none(),
            Curve::Poly { closed, .. } => *closed,
            _ => false,
        }
    }

    /// Its points along it as chords, ends included (a closed curve ends where it starts).
    pub fn points(&self) -> Vec<P2> {
        match self {
            Curve::Line(a, b) => vec![*a, *b],
            Curve::Arc(a, b, deg) => arc_points(*a, *b, *deg),
            Curve::Poly { pts, arcs, closed } => {
                let n = pts.len();
                let segs = if *closed { n } else { n - 1 };
                let mut out = vec![pts[0]];
                for i in 0..segs {
                    let a = pts[i];
                    let b = pts[(i + 1) % n];
                    let deg = arcs.get(i).copied().unwrap_or(0.0);
                    let p = arc_points(a, b, deg);
                    out.extend_from_slice(&p[1..]);
                }
                out
            }
            Curve::Circle { c, r } => {
                let n = chords(*r, std::f64::consts::TAU);
                let mut out = Vec::with_capacity(n + 1);
                for i in 0..n {
                    let ang = (360.0 * i as f64 / n as f64).to_radians();
                    out.push([c[0] + r * ang.cos(), c[1] + r * ang.sin()]);
                }
                out.push(out[0]);
                out
            }
            Curve::Ellipse { c, rx, ry, angle, span } => {
                let (t0, t1) = match span {
                    Some((a, b)) => (a.to_radians(), b.to_radians()),
                    None => (0.0, std::f64::consts::TAU),
                };
                let rmax = rx.max(*ry);
                let n = 2 * chords(rmax, t1 - t0);
                let (ca, sa) = (angle.to_radians().cos(), angle.to_radians().sin());
                let at = |t: f64| -> P2 {
                    let x = rx * t.cos();
                    let y = ry * t.sin();
                    [c[0] + x * ca - y * sa, c[1] + x * sa + y * ca]
                };
                let mut out = Vec::with_capacity(n + 1);
                for i in 0..n {
                    out.push(at(t0 + (t1 - t0) * i as f64 / n as f64));
                }
                if span.is_none() {
                    out.push(out[0]);
                } else {
                    out.push(at(t1));
                }
                out
            }
            Curve::Spline { control, knots } => bspline(control, knots.as_deref()),
            Curve::Fit { pts, t0, t1 } => fit_spline(pts, *t0, *t1),
        }
    }
}

/// A cubic (or lower, with few points) B-spline by its control points, clamped at its ends.
fn bspline(ctrl: &[P2], knots: Option<&[f64]>) -> Vec<P2> {
    let n = ctrl.len();
    let p = 3.min(n - 1);
    let m = n + p + 1;
    let kn: Vec<f64> = match knots {
        Some(k) if k.len() == m => k.to_vec(),
        _ => {
            let mut k = Vec::with_capacity(m);
            for i in 0..m {
                if i <= p {
                    k.push(0.0);
                } else if i >= n {
                    k.push(1.0);
                } else {
                    k.push((i - p) as f64 / (n - p) as f64);
                }
            }
            k
        }
    };
    let eval = |t: f64| -> P2 {
        // de Boor
        let mut k = p;
        while k + 1 < n && t >= kn[k + 1] {
            k += 1;
        }
        let mut d: Vec<P2> = (0..=p).map(|j| ctrl[(j + k - p).min(n - 1)]).collect();
        for r in 1..=p {
            for j in (r..=p).rev() {
                let i = j + k - p;
                let den = kn[i + p + 1 - r] - kn[i];
                let a = if den != 0.0 { (t - kn[i]) / den } else { 0.0 };
                d[j] = lerp(d[j - 1], d[j], a);
            }
        }
        d[p]
    };
    let segs = (n * 16).max(16);
    let (lo, hi) = (kn[p], kn[n]);
    let mut out = Vec::with_capacity(segs + 1);
    for i in 0..segs {
        out.push(eval(lo + (hi - lo) * i as f64 / segs as f64));
    }
    out.push(ctrl[n - 1]);
    out
}

/// A curve through points (a Catmull-Rom spline), with the tangents given at its ends.
fn fit_spline(pts: &[P2], t0: Option<P2>, t1: Option<P2>) -> Vec<P2> {
    let n = pts.len();
    if n == 2 {
        return pts.to_vec();
    }
    let tan = |i: usize| -> P2 {
        if i == 0 {
            if let Some(t) = t0 {
                return t;
            }
            return sub(pts[1], pts[0]);
        }
        if i == n - 1 {
            if let Some(t) = t1 {
                return t;
            }
            return sub(pts[n - 1], pts[n - 2]);
        }
        scale(sub(pts[i + 1], pts[i - 1]), 0.5)
    };
    let mut out = vec![pts[0]];
    for i in 0..n - 1 {
        let (p0, p1) = (pts[i], pts[i + 1]);
        let (m0, m1) = (tan(i), tan(i + 1));
        let steps = 16;
        for s in 1..=steps {
            let t = s as f64 / steps as f64;
            let t2 = t * t;
            let t3 = t2 * t;
            let h00 = 2.0 * t3 - 3.0 * t2 + 1.0;
            let h10 = t3 - 2.0 * t2 + t;
            let h01 = -2.0 * t3 + 3.0 * t2;
            let h11 = t3 - t2;
            out.push([
                h00 * p0[0] + h10 * m0[0] + h01 * p1[0] + h11 * m1[0],
                h00 * p0[1] + h10 * m0[1] + h01 * p1[1] + h11 * m1[1],
            ]);
        }
    }
    out
}
