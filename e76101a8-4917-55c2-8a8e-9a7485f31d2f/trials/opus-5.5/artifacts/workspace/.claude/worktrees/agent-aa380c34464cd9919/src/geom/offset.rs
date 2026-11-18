//! Offsets of rings: each edge moved to its left by its own distance, the corners where the moved
//! edges meet (mitred), a step where two edges in line move by different distances, and a square
//! end where an edge runs back along the one before it (a wall's free end).

use super::*;

/// The ring with edge i (from point i to the next) moved `d[i]` to its left.
pub fn offset_ring(ring: &[P2], d: &[f64]) -> Vec<P2> {
    offset_ring_ends(ring, d, true)
}

/// As `offset_ring`, an edge running back along the one before it ending square (`square`) or
/// at the first one's end alone (a roof grown over a wall standing out of the rest).
pub fn offset_ring_ends(ring: &[P2], d: &[f64], square: bool) -> Vec<P2> {
    let n = ring.len();
    if n < 2 {
        return ring.to_vec();
    }
    let mut out = Vec::with_capacity(n + 4);
    for i in 0..n {
        let prev = (i + n - 1) % n;
        let a = ring[prev];
        let b = ring[i];
        let c = ring[(i + 1) % n];
        let u = unit(sub(b, a));
        let v = unit(sub(c, b));
        let nu = left(u);
        let nv = left(v);
        let du = d[prev];
        let dv = d[i];
        let cr = cross(u, v);
        let dt = dot(u, v);
        if cr.abs() < 1e-12 {
            if dt > 0.0 {
                // in line: the same point moved, or a step between two distances
                if (du - dv).abs() < 1e-9 {
                    out.push(add(b, scale(nu, du)));
                } else {
                    out.push(add(b, scale(nu, du)));
                    out.push(add(b, scale(nv, dv)));
                }
            } else {
                // running back: a square end, or the first edge's end
                out.push(add(b, scale(nu, du)));
                if square {
                    out.push(add(b, scale(nv, dv)));
                }
            }
            continue;
        }
        // where the moved lines meet: b + nu*du + u*t = b + nv*dv + v*s
        let p0 = add(b, scale(nu, du));
        let q0 = add(b, scale(nv, dv));
        let t = cross(sub(q0, p0), v) / cr;
        out.push(add(p0, scale(u, t)));
    }
    out
}
