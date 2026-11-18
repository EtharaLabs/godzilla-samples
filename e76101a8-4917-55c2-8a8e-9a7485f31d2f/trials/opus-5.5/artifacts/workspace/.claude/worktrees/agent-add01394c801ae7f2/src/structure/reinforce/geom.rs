//! Geometry `reinforce` lays bars out with: a host's frame (along, across, up), bars spread
//! evenly across a width, stations at most a spacing apart along a length.

pub type V3 = [f64; 3];

/// Within this (mm) two things are one: a hook that just fits, a gap just at the clearance, a
/// bar that can just rise.
pub const TOL: f64 = 1.0;

pub fn add(a: V3, b: V3) -> V3 {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

pub fn sub(a: V3, b: V3) -> V3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

pub fn scale(a: V3, k: f64) -> V3 {
    [a[0] * k, a[1] * k, a[2] * k]
}

pub fn dot(a: V3, b: V3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

pub fn cross(a: V3, b: V3) -> V3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

pub fn len(a: V3) -> f64 {
    (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]).sqrt()
}

/// A vector made a unit long as the original's vector library does it: times the reciprocal of
/// its length.
pub fn unit(a: V3) -> V3 {
    let r = 1.0 / len(a);
    [a[0] * r, a[1] * r, a[2] * r]
}

/// A host's own frame: an origin and three directions; a point is `t` along, `a` across and
/// `u` up from the origin.
#[derive(Clone, Copy, Debug)]
pub struct Frame {
    pub o: V3,
    pub along: V3,
    pub across: V3,
    pub up: V3,
}

impl Frame {
    pub fn at(&self, t: f64, a: f64, u: f64) -> V3 {
        let o = self.o;
        let (l, c, p) = (self.along, self.across, self.up);
        [
            o[0] + l[0] * t + c[0] * a + p[0] * u,
            o[1] + l[1] * t + c[1] * a + p[1] * u,
            o[2] + l[2] * t + c[2] * a + p[2] * u,
        ]
    }
}

/// `n` places evenly from `a` to `b`, the first at `a` and the last at `b`; one is in the middle.
pub fn spread(a: f64, b: f64, n: usize) -> Vec<f64> {
    if n == 0 {
        return Vec::new();
    }
    if n == 1 {
        return vec![(a + b) / 2.0];
    }
    let m = (n - 1) as f64;
    (0..n).map(|i| a + (b - a) * i as f64 / m).collect()
}

/// How many gaps at most `spacing` apart a length takes.
pub fn gaps(length: f64, spacing: f64) -> usize {
    let n = (length / spacing).ceil();
    if n < 1.0 {
        1
    } else {
        n as usize
    }
}

/// Stations from `a` to `b` at most `spacing` apart, evenly: the first at `a`, the last at `b`.
pub fn stations(a: f64, b: f64, spacing: f64) -> Vec<f64> {
    let n = gaps(b - a, spacing);
    (0..=n).map(|i| a + (b - a) * i as f64 / n as f64).collect()
}

/// How many stations `stations` gives, without making them (a guard against huge counts).
pub fn station_count(a: f64, b: f64, spacing: f64) -> f64 {
    ((b - a) / spacing).ceil().max(1.0) + 1.0
}
