//! The bounded line and the arc in an element's data (`04 00 08 01`, then the numbers, feet).

use super::bytes::*;

pub const MARK: [u8; 4] = [4, 0, 8, 1];
/// The largest length (feet) the reader takes, from zero: Revit's working limit is 20 miles.
pub const MAX_FEET: f64 = 3e5;

#[derive(Clone, Copy, Debug)]
pub struct Line {
    pub start: [f64; 3],
    pub end: [f64; 3],
    pub dir: [f64; 3],
}

#[derive(Clone, Copy, Debug)]
pub struct Arc {
    pub a0: f64,
    pub a1: f64,
    pub x: [f64; 3],
    pub y: [f64; 3],
    pub radius: f64,
    pub centre: [f64; 3],
}

impl Arc {
    pub fn point(&self, a: f64) -> [f64; 3] {
        let (s, c) = a.sin_cos();
        [
            self.centre[0] + self.radius * (c * self.x[0] + s * self.y[0]),
            self.centre[1] + self.radius * (c * self.x[1] + s * self.y[1]),
            self.centre[2] + self.radius * (c * self.x[2] + s * self.y[2]),
        ]
    }
    pub fn start(&self) -> [f64; 3] {
        self.point(self.a0)
    }
    pub fn end(&self) -> [f64; 3] {
        self.point(self.a1)
    }
    pub fn normal(&self) -> [f64; 3] {
        let (a, b) = (self.x, self.y);
        [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    }
}

#[derive(Clone, Copy, Debug)]
pub enum Curve {
    Line(Line),
    Arc(Arc),
}

fn ok(v: f64) -> bool {
    v.is_finite() && v.abs() <= MAX_FEET
}

pub fn line_at(d: &[u8], p: usize) -> Option<Line> {
    let mut v = [0f64; 8];
    for (k, x) in v.iter_mut().enumerate() {
        *x = rd_f64(d, p + 4 + 8 * k)?;
        if !ok(*x) {
            return None;
        }
    }
    let (t0, t1) = (v[0], v[1]);
    let o = [v[2], v[3], v[4]];
    let dir = [v[5], v[6], v[7]];
    let n = (dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]).sqrt();
    if (n - 1.0).abs() > 1e-6 {
        return None;
    }
    let start = [o[0] + t0 * dir[0], o[1] + t0 * dir[1], o[2] + t0 * dir[2]];
    let end = [o[0] + t1 * dir[0], o[1] + t1 * dir[1], o[2] + t1 * dir[2]];
    Some(Line { start, end, dir })
}

pub fn arc_at(d: &[u8], p: usize) -> Option<Arc> {
    let mut v = [0f64; 12];
    for (k, x) in v.iter_mut().enumerate() {
        *x = rd_f64(d, p + 4 + 8 * k)?;
        if !ok(*x) {
            return None;
        }
    }
    let a = Arc {
        a0: v[0],
        a1: v[1],
        x: [v[2], v[3], v[4]],
        y: [v[5], v[6], v[7]],
        radius: v[8],
        centre: [v[9], v[10], v[11]],
    };
    if !(a.radius > 0.0) {
        return None;
    }
    let nx = (a.x[0].powi(2) + a.x[1].powi(2) + a.x[2].powi(2)).sqrt();
    let ny = (a.y[0].powi(2) + a.y[1].powi(2) + a.y[2].powi(2)).sqrt();
    if (nx - 1.0).abs() > 1e-6 || (ny - 1.0).abs() > 1e-6 {
        return None;
    }
    Some(a)
}

/// The first curve record of the data: an arc when the eight bytes before its mark are a `u64` 1.
pub fn first(d: &[u8]) -> Option<(Curve, usize)> {
    let p = find(d, &MARK, 0, d.len())?;
    let is_arc = p >= 8 && rd_u64(d, p - 8) == Some(1);
    let end = p + 4 + if is_arc { 96 } else { 64 };
    if is_arc {
        arc_at(d, p).map(|a| (Curve::Arc(a), end))
    } else {
        line_at(d, p).map(|l| (Curve::Line(l), end))
    }
}

/// Both readings of the first curve record (for sketch lines).
pub fn first_both(d: &[u8]) -> Option<(Option<Line>, Option<Arc>, bool, usize)> {
    let p = find(d, &MARK, 0, d.len())?;
    let flagged = p >= 8 && rd_u64(d, p - 8) == Some(1);
    Some((line_at(d, p), arc_at(d, p), flagged, p))
}
