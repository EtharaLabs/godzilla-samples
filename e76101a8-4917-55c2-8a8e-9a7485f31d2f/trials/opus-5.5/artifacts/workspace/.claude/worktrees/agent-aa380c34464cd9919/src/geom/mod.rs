//! Plan geometry: points and vectors, polygons (area, orientation, containment), segments and
//! their crossings, arcs as chords, the planar graph of lines and its faces, offsets, sketches,
//! triangulation and straight skeletons. Everything in millimetres, in the plan's x and y.

pub mod curves;
pub mod graph;
pub mod sketch;
pub mod skeleton;
pub mod offset;
pub mod tri;

pub type P2 = [f64; 2];

#[inline]
pub fn add(a: P2, b: P2) -> P2 {
    [a[0] + b[0], a[1] + b[1]]
}
#[inline]
pub fn sub(a: P2, b: P2) -> P2 {
    [a[0] - b[0], a[1] - b[1]]
}
#[inline]
pub fn scale(a: P2, k: f64) -> P2 {
    [a[0] * k, a[1] * k]
}
#[inline]
pub fn dot(a: P2, b: P2) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
#[inline]
pub fn cross(a: P2, b: P2) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
#[inline]
pub fn len(a: P2) -> f64 {
    (a[0] * a[0] + a[1] * a[1]).sqrt()
}
#[inline]
pub fn dist(a: P2, b: P2) -> f64 {
    let dx = b[0] - a[0];
    let dy = b[1] - a[1];
    (dx * dx + dy * dy).sqrt()
}
#[inline]
pub fn lerp(a: P2, b: P2, t: f64) -> P2 {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}
/// The unit vector along a, or zero.
pub fn unit(a: P2) -> P2 {
    let l = len(a);
    if l > 0.0 {
        [a[0] / l, a[1] / l]
    } else {
        [0.0, 0.0]
    }
}
/// The vector turned a quarter turn counter-clockwise (to the left).
#[inline]
pub fn left(a: P2) -> P2 {
    [-a[1], a[0]]
}
/// (b - a) x (c - a): positive when c is left of a→b.
#[inline]
pub fn orient(a: P2, b: P2, c: P2) -> f64 {
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
}

/// The signed area of a ring (counter-clockwise positive), by the shoelace sum.
pub fn area(ring: &[P2]) -> f64 {
    let n = ring.len();
    if n < 3 {
        return 0.0;
    }
    let mut s = 0.0;
    for i in 0..n {
        let a = ring[i];
        let b = ring[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    s / 2.0
}

pub fn perimeter(ring: &[P2]) -> f64 {
    let n = ring.len();
    let mut s = 0.0;
    for i in 0..n {
        s += dist(ring[i], ring[(i + 1) % n]);
    }
    s
}

/// The ring counter-clockwise: reversed (whole) if it runs clockwise.
pub fn ccw(ring: &[P2]) -> Vec<P2> {
    if area(ring) < 0.0 {
        ring.iter().rev().copied().collect()
    } else {
        ring.to_vec()
    }
}

/// The ring clockwise: reversed (whole) if it runs counter-clockwise.
pub fn cw(ring: &[P2]) -> Vec<P2> {
    if area(ring) > 0.0 {
        ring.iter().rev().copied().collect()
    } else {
        ring.to_vec()
    }
}

/// The parameter along a→b of the point nearest p, clamped to the segment.
pub fn project_t(a: P2, b: P2, p: P2) -> f64 {
    let d = sub(b, a);
    let l2 = dot(d, d);
    if l2 <= 0.0 {
        return 0.0;
    }
    (dot(sub(p, a), d) / l2).clamp(0.0, 1.0)
}

/// How far p is from the segment a–b.
pub fn seg_dist(a: P2, b: P2, p: P2) -> f64 {
    let t = project_t(a, b, p);
    dist(p, lerp(a, b, t))
}

/// Whether p lies inside the ring (even-odd; a point on an edge counts as outside).
pub fn inside(ring: &[P2], p: P2) -> bool {
    let n = ring.len();
    if n < 3 {
        return false;
    }
    for i in 0..n {
        let a = ring[i];
        let b = ring[(i + 1) % n];
        if seg_dist(a, b, p) < 1e-9 {
            return false;
        }
    }
    inside_raw(ring, p)
}

/// Even-odd containment without the edge test.
pub fn inside_raw(ring: &[P2], p: P2) -> bool {
    let n = ring.len();
    let mut c = false;
    let mut j = n - 1;
    for i in 0..n {
        let a = ring[i];
        let b = ring[j];
        if (a[1] > p[1]) != (b[1] > p[1]) {
            let x = (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0];
            if p[0] < x {
                c = !c;
            }
        }
        j = i;
    }
    c
}

/// Where two segments cross, as parameters (t along a0→a1, u along b0→b1), when they cross at a
/// single point (ends included).
pub fn seg_cross(a0: P2, a1: P2, b0: P2, b1: P2) -> Option<(f64, f64)> {
    let d = sub(a1, a0);
    let e = sub(b1, b0);
    let den = cross(d, e);
    if den == 0.0 {
        return None;
    }
    let w = sub(b0, a0);
    let t = cross(w, e) / den;
    let u = cross(w, d) / den;
    if (0.0..=1.0).contains(&t) && (0.0..=1.0).contains(&u) {
        Some((t, u))
    } else {
        None
    }
}

/// The bounding box of points: (min, max).
pub fn bbox(pts: &[P2]) -> (P2, P2) {
    let mut lo = [f64::INFINITY, f64::INFINITY];
    let mut hi = [f64::NEG_INFINITY, f64::NEG_INFINITY];
    for p in pts {
        lo[0] = lo[0].min(p[0]);
        lo[1] = lo[1].min(p[1]);
        hi[0] = hi[0].max(p[0]);
        hi[1] = hi[1].max(p[1]);
    }
    (lo, hi)
}

/// The ring turned to start at its lowest point (least y, then least x).
pub fn start_lowest(ring: &[P2]) -> Vec<P2> {
    if ring.is_empty() {
        return Vec::new();
    }
    let mut k = 0;
    for (i, p) in ring.iter().enumerate() {
        let q = ring[k];
        if p[1] < q[1] || (p[1] == q[1] && p[0] < q[0]) {
            k = i;
        }
    }
    let mut out = Vec::with_capacity(ring.len());
    out.extend_from_slice(&ring[k..]);
    out.extend_from_slice(&ring[..k]);
    out
}

// ---------------------------------------------------------------- arcs

/// A circular arc through `a` and `b`, turning `sweep` radians about its centre (counter-clockwise
/// positive): its centre, radius and the angle of `a` from the centre.
#[derive(Clone, Copy, Debug)]
pub struct Arc {
    pub centre: P2,
    pub radius: f64,
    pub a0: f64,
    pub sweep: f64,
}

impl Arc {
    /// The arc from a to b turning `deg` degrees (counter-clockwise positive).
    pub fn new(a: P2, b: P2, deg: f64) -> Arc {
        let sweep = deg.to_radians();
        let chord = sub(b, a);
        let c = len(chord);
        let half = sweep / 2.0;
        let radius = c / 2.0 / half.sin().abs();
        let mid = lerp(a, b, 0.5);
        // the centre is to the left of a→b for a counter-clockwise arc under a half turn
        let d = c / 2.0 / half.tan();
        let n = left(unit(chord));
        let centre = add(mid, scale(n, d));
        let a0 = (a[1] - centre[1]).atan2(a[0] - centre[0]);
        Arc { centre, radius, a0, sweep }
    }
    pub fn at(&self, t: f64) -> P2 {
        let ang = self.a0 + self.sweep * t;
        [self.centre[0] + self.radius * ang.cos(), self.centre[1] + self.radius * ang.sin()]
    }
    pub fn length(&self) -> f64 {
        self.radius * self.sweep.abs()
    }
}

/// Whether an arc of `deg` degrees counts as straight.
pub fn straight(deg: f64) -> bool {
    deg.to_radians().abs() < 1e-9
}
