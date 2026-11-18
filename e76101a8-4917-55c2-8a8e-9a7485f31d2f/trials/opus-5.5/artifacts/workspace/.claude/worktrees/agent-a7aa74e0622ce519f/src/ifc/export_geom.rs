//! Plane and space vectors for the export's geometry, computed as glam computes them
//! (a normal is the vector times one over its length), so the last bits come out as the
//! original's do.

#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct V2 {
    pub x: f64,
    pub y: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct V3 {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

pub fn v2(x: f64, y: f64) -> V2 {
    V2 { x, y }
}
pub fn v3(x: f64, y: f64, z: f64) -> V3 {
    V3 { x, y, z }
}

impl std::ops::Add for V2 {
    type Output = V2;
    fn add(self, o: V2) -> V2 {
        v2(self.x + o.x, self.y + o.y)
    }
}
impl std::ops::Sub for V2 {
    type Output = V2;
    fn sub(self, o: V2) -> V2 {
        v2(self.x - o.x, self.y - o.y)
    }
}
impl std::ops::Mul<f64> for V2 {
    type Output = V2;
    fn mul(self, k: f64) -> V2 {
        v2(self.x * k, self.y * k)
    }
}
impl std::ops::Neg for V2 {
    type Output = V2;
    fn neg(self) -> V2 {
        v2(-self.x, -self.y)
    }
}
impl std::ops::Add for V3 {
    type Output = V3;
    fn add(self, o: V3) -> V3 {
        v3(self.x + o.x, self.y + o.y, self.z + o.z)
    }
}
impl std::ops::Sub for V3 {
    type Output = V3;
    fn sub(self, o: V3) -> V3 {
        v3(self.x - o.x, self.y - o.y, self.z - o.z)
    }
}
impl std::ops::Mul<f64> for V3 {
    type Output = V3;
    fn mul(self, k: f64) -> V3 {
        v3(self.x * k, self.y * k, self.z * k)
    }
}
impl std::ops::Neg for V3 {
    type Output = V3;
    fn neg(self) -> V3 {
        v3(-self.x, -self.y, -self.z)
    }
}

impl V2 {
    pub fn dot(self, o: V2) -> f64 {
        self.x * o.x + self.y * o.y
    }
    /// `x * o.y - y * o.x`, glam's `perp_dot`.
    pub fn cross(self, o: V2) -> f64 {
        self.x * o.y - self.y * o.x
    }
    pub fn length(self) -> f64 {
        self.dot(self).sqrt()
    }
    pub fn length_squared(self) -> f64 {
        self.dot(self)
    }
    pub fn normalize(self) -> V2 {
        self * (1.0 / self.length())
    }
    /// The vector turned a quarter to the left.
    pub fn perp(self) -> V2 {
        v2(-self.y, self.x)
    }
    pub fn distance(self, o: V2) -> f64 {
        (self - o).length()
    }
    pub fn lerp(self, o: V2, t: f64) -> V2 {
        self + (o - self) * t
    }
    pub fn angle(self) -> f64 {
        self.y.atan2(self.x)
    }
}

impl V3 {
    pub fn dot(self, o: V3) -> f64 {
        self.x * o.x + self.y * o.y + self.z * o.z
    }
    pub fn cross(self, o: V3) -> V3 {
        v3(self.y * o.z - o.y * self.z, self.z * o.x - o.z * self.x, self.x * o.y - o.x * self.y)
    }
    pub fn length(self) -> f64 {
        self.dot(self).sqrt()
    }
    pub fn normalize(self) -> V3 {
        self * (1.0 / self.length())
    }
    pub fn xy(self) -> V2 {
        v2(self.x, self.y)
    }
}

/// Where two lines cross: `a + d * t` and `b + e * s`; none when they're parallel.
pub fn line_cross(a: V2, d: V2, b: V2, e: V2) -> Option<V2> {
    let den = d.cross(e);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = (b - a).cross(e) / den;
    Some(a + d * t)
}

/// The parameter along `a + d * t` where it crosses `b + e * s`.
pub fn line_cross_t(a: V2, d: V2, b: V2, e: V2) -> Option<f64> {
    let den = d.cross(e);
    if den.abs() < 1e-12 {
        return None;
    }
    Some((b - a).cross(e) / den)
}

/// Twice the signed area of a ring (positive counter-clockwise).
pub fn area2(ring: &[V2]) -> f64 {
    let n = ring.len();
    let mut s = 0.0;
    for i in 0..n {
        let a = ring[i];
        let b = ring[(i + 1) % n];
        s += a.x * b.y - b.x * a.y;
    }
    s
}

pub fn signed_area(ring: &[V2]) -> f64 {
    area2(ring) / 2.0
}

pub fn perimeter(ring: &[V2]) -> f64 {
    let n = ring.len();
    let mut s = 0.0;
    for i in 0..n {
        s += ring[i].distance(ring[(i + 1) % n]);
    }
    s
}
