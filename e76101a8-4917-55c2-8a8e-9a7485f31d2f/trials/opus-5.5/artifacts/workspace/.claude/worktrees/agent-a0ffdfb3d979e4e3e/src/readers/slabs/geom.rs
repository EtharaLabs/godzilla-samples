//! Plane geometry the slabs share: polygon areas, points in polygons, the area a polygon keeps
//! once holes (overlapping one another or its edges, as shafts may) are taken out of it, and the
//! rounding the original reports areas and volumes with.

pub type P = [f64; 2];

pub fn sub(a: P, b: P) -> P {
    [a[0] - b[0], a[1] - b[1]]
}
pub fn add(a: P, b: P) -> P {
    [a[0] + b[0], a[1] + b[1]]
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
    (a[0] * a[0] + a[1] * a[1]).sqrt()
}
pub fn dist(a: P, b: P) -> f64 {
    len(sub(a, b))
}
pub fn lerp(a: P, b: P, t: f64) -> P {
    [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}
/// The unit vector along `a`, or zero.
pub fn unit(a: P) -> P {
    let l = len(a);
    if l > 0.0 {
        [a[0] / l, a[1] / l]
    } else {
        [0.0, 0.0]
    }
}
/// `a` turned a quarter counter-clockwise (to the left).
pub fn left(a: P) -> P {
    [-a[1], a[0]]
}

/// Twice the signed area (counter-clockwise positive), by the shoelace sum.
pub fn shoelace2(poly: &[P]) -> f64 {
    let n = poly.len();
    let mut s = 0.0;
    for i in 0..n {
        let a = poly[i];
        let b = poly[(i + 1) % n];
        s += a[0] * b[1] - b[0] * a[1];
    }
    s
}

pub fn signed_area(poly: &[P]) -> f64 {
    shoelace2(poly) / 2.0
}

pub fn area(poly: &[P]) -> f64 {
    signed_area(poly).abs()
}

/// Whether `p` is inside the polygon (even-odd; a point on an edge may go either way).
pub fn inside(poly: &[P], p: P) -> bool {
    let n = poly.len();
    let mut c = false;
    let mut j = n.wrapping_sub(1);
    for i in 0..n {
        let a = poly[i];
        let b = poly[j];
        if (a[1] > p[1]) != (b[1] > p[1]) {
            let x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
            if p[0] < x {
                c = !c;
            }
        }
        j = i;
    }
    c
}

/// The distance from `p` to the segment `a`–`b`.
pub fn dist_to_segment(p: P, a: P, b: P) -> f64 {
    let d = sub(b, a);
    let l2 = dot(d, d);
    if l2 == 0.0 {
        return dist(p, a);
    }
    let t = (dot(sub(p, a), d) / l2).clamp(0.0, 1.0);
    dist(p, lerp(a, b, t))
}

/// The distance from `p` to the polygon's outline.
pub fn dist_to_outline(poly: &[P], p: P) -> f64 {
    let n = poly.len();
    let mut d = f64::INFINITY;
    for i in 0..n {
        d = d.min(dist_to_segment(p, poly[i], poly[(i + 1) % n]));
    }
    d
}

/// Whether `p` is inside the polygon or within `tol` of its outline.
pub fn inside_or_on(poly: &[P], p: P, tol: f64) -> bool {
    inside(poly, p) || dist_to_outline(poly, p) <= tol
}

/// Where segments `a`–`b` and `c`–`d` cross (proper or touching), as the parameter along the first.
fn seg_cross(a: P, b: P, c: P, d: P) -> Option<P> {
    let r = sub(b, a);
    let s = sub(d, c);
    let den = cross(r, s);
    if den == 0.0 {
        return None;
    }
    let ca = sub(c, a);
    let t = cross(ca, s) / den;
    let u = cross(ca, r) / den;
    if (0.0..=1.0).contains(&t) && (0.0..=1.0).contains(&u) {
        Some(lerp(a, b, t))
    } else {
        None
    }
}

fn edges_cross(p: &[P], q: &[P]) -> bool {
    let (n, m) = (p.len(), q.len());
    for i in 0..n {
        let (a, b) = (p[i], p[(i + 1) % n]);
        for j in 0..m {
            let (c, d) = (q[j], q[(j + 1) % m]);
            if seg_cross(a, b, c, d).is_some() {
                return true;
            }
            // collinear overlaps
            if cross(sub(b, a), sub(d, c)) == 0.0 && cross(sub(b, a), sub(c, a)) == 0.0 {
                let r = sub(b, a);
                let l2 = dot(r, r);
                if l2 > 0.0 {
                    let t0 = dot(sub(c, a), r) / l2;
                    let t1 = dot(sub(d, a), r) / l2;
                    if t0.max(t1) >= 0.0 && t0.min(t1) <= 1.0 {
                        return true;
                    }
                }
            }
        }
    }
    false
}

/// The area of `outer` once `holes` are taken out of it: holes may overlap one another, run past
/// its edges or lie outside it altogether (only what they cover of it counts, once).
pub fn area_minus(outer: &[P], holes: &[Vec<P>]) -> f64 {
    let holes: Vec<&Vec<P>> = holes.iter().filter(|h| h.len() >= 3).collect();
    if holes.is_empty() {
        return area(outer);
    }
    // the plain case: each hole well inside, none touching another (exact sums, as the original's)
    let mut simple = true;
    'check: for (i, h) in holes.iter().enumerate() {
        if edges_cross(outer, h) || !inside(outer, h[0]) {
            simple = false;
            break;
        }
        for g in holes.iter().skip(i + 1) {
            if edges_cross(h, g) || inside(h, g[0]) || inside(g, h[0]) {
                simple = false;
                break 'check;
            }
        }
    }
    if simple {
        let mut a = area(outer);
        for h in &holes {
            a -= area(h);
        }
        return a;
    }
    let mut polys: Vec<&[P]> = vec![outer];
    for h in &holes {
        polys.push(h);
    }
    strip_area(&polys)
}

/// The area of the first polygon less the union of the others, strip by strip: between each two
/// x's where a vertex is or two edges cross, every edge is a straight piece across, so the area
/// is the strip's width times the length of what is left at its middle.
fn strip_area(polys: &[&[P]]) -> f64 {
    let mut xs: Vec<f64> = Vec::new();
    for p in polys {
        for v in p.iter() {
            xs.push(v[0]);
        }
    }
    for (i, p) in polys.iter().enumerate() {
        for q in polys.iter().skip(i + 1) {
            let (n, m) = (p.len(), q.len());
            for a in 0..n {
                let (pa, pb) = (p[a], p[(a + 1) % n]);
                for b in 0..m {
                    if let Some(x) = seg_cross(pa, pb, q[b], q[(b + 1) % m]) {
                        xs.push(x[0]);
                    }
                }
            }
        }
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    xs.dedup();
    let mut total = 0.0;
    for w in xs.windows(2) {
        let (x0, x1) = (w[0], w[1]);
        if x1 - x0 <= 0.0 {
            continue;
        }
        let xm = (x0 + x1) / 2.0;
        let spans = |p: &[P]| -> Vec<(f64, f64)> {
            let n = p.len();
            let mut ys = Vec::new();
            for i in 0..n {
                let (a, b) = (p[i], p[(i + 1) % n]);
                if (a[0] < xm) != (b[0] < xm) {
                    ys.push(a[1] + (xm - a[0]) * (b[1] - a[1]) / (b[0] - a[0]));
                }
            }
            ys.sort_by(|a, b| a.partial_cmp(b).unwrap());
            ys.chunks(2).filter(|c| c.len() == 2).map(|c| (c[0], c[1])).collect()
        };
        let keep = spans(polys[0]);
        if keep.is_empty() {
            continue;
        }
        let mut cut: Vec<(f64, f64)> = Vec::new();
        for p in &polys[1..] {
            cut.extend(spans(p));
        }
        cut.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        let mut merged: Vec<(f64, f64)> = Vec::new();
        for c in cut {
            if let Some(last) = merged.last_mut() {
                if c.0 <= last.1 {
                    last.1 = last.1.max(c.1);
                    continue;
                }
            }
            merged.push(c);
        }
        let mut length = 0.0;
        for (a, b) in keep {
            let mut l = b - a;
            for &(c, d) in &merged {
                let lo = a.max(c);
                let hi = b.min(d);
                if hi > lo {
                    l -= hi - lo;
                }
            }
            length += l;
        }
        total += (x1 - x0) * length;
    }
    total
}

// ---------------------------------------------------------------- rounding as reported

/// Rounds to hundredths (lengths and heights in mm).
pub fn r2(x: f64) -> f64 {
    let v = (x * 100.0).round() / 100.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// Rounds to thousandths.
pub fn r3(x: f64) -> f64 {
    let v = (x * 1000.0).round() / 1000.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// An area in mm² as the original reports it: m² to hundredths (rounded off the mm² value, so
/// 1 005 000 mm² is 1.01 m²).
pub fn m2(a_mm2: f64) -> f64 {
    let v = (a_mm2 / 1e4).round() / 100.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// A volume in mm³ as m³ to thousandths (a floor's).
pub fn m3_3(v_mm3: f64) -> f64 {
    let v = (v_mm3 / 1e6).round() / 1000.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

/// A volume in mm³ as m³ to hundredths (a mass's).
pub fn m3_2(v_mm3: f64) -> f64 {
    let v = (v_mm3 / 1e7).round() / 100.0;
    if v == 0.0 {
        0.0
    } else {
        v
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn holes_overlapping() {
        let f = vec![[0.0, 0.0], [10000.0, 0.0], [10000.0, 6000.0], [0.0, 6000.0]];
        let holes = vec![
            vec![[4000.0, 4000.0], [6000.0, 4000.0], [6000.0, 5000.0], [4000.0, 5000.0]],
            vec![[-1000.0, 1000.0], [1000.0, 1000.0], [1000.0, 2000.0], [-1000.0, 2000.0]],
            vec![[5000.0, 4500.0], [7000.0, 4500.0], [7000.0, 5500.0], [5000.0, 5500.0]],
            vec![[2000.0, 1000.0], [3000.0, 1000.0], [3000.0, 3000.0], [2000.0, 3000.0]],
            vec![[2500.0, 2000.0], [3500.0, 2000.0], [3500.0, 3500.0], [2500.0, 3500.0]],
        ];
        assert!((area_minus(&f, &holes) - 52.5e6).abs() < 1e-3);
    }

    #[test]
    fn rounding() {
        assert_eq!(m2(1005000.0), 1.01);
        assert_eq!(m2(145000.0), 0.15);
        assert_eq!(m3_3(200500000.0), 0.201);
        assert_eq!(m3_2(1.005e9), 1.01);
    }
}
