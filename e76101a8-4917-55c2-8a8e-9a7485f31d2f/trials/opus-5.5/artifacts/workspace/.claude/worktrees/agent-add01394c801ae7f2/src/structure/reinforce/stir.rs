//! Stirrups (a beam's and a column's): closed loops at stations along the host, closer in the
//! first and last `ends.length` mm, a hook running on past the first corner to a tail turned
//! into the section along the corner's bisector.

use super::de::{f, sub};
use super::geom::{add, station_count, stations, sub as vsub, unit, V3, TOL};
use super::{not_negative, spacing};
use crate::json::Map;
use crate::structure::common::R;

/// A stirrup as read, its diameter checked.
pub struct Stir {
    pub d: f64,
    pub spacing: f64,
    pub hook: f64,
    /// length, spacing
    pub ends: Option<(f64, f64)>,
}

/// The rest of a stirrup after its diameter: its spacing, its hook and its ends, in that order.
pub fn read_rest(m: &Map, d: f64) -> R<Stir> {
    let sp = spacing("stirrup", f(m, "spacing").unwrap_or(0.0), d)?;
    let hook = match f(m, "hook") {
        Some(h) => not_negative("hook", h)?,
        None => 0.0,
    };
    let ends = match sub(m, "ends") {
        Some(e) => {
            let l = f(e, "length").unwrap_or(0.0);
            if !(l > 0.0) {
                return Err(format!("`ends` length {} mm must be over 0", l));
            }
            let esp = spacing("ends", f(e, "spacing").unwrap_or(0.0), d)?;
            Some((l, esp))
        }
        None => None,
    };
    Ok(Stir { d, spacing: sp, hook, ends })
}

/// The zones stirrups are spread over from `s0` to `s1`: (from, to, spacing). With `ends`, the
/// first and last `length` mm at their own spacing and the middle at the stirrup's; where the
/// ends meet, all of it at the closer spacing.
pub fn zones(s0: f64, s1: f64, st: &Stir) -> Vec<(f64, f64, f64)> {
    match st.ends {
        Some((l, esp)) => {
            let a = s0 + l;
            let b = s1 - l;
            if b - a > TOL {
                vec![(s0, a, esp), (a, b, st.spacing), (b, s1, esp)]
            } else {
                vec![(s0, s1, esp.min(st.spacing))]
            }
        }
        None => vec![(s0, s1, st.spacing)],
    }
}

/// How many stirrups the zones take.
pub fn count(zs: &[(f64, f64, f64)]) -> f64 {
    let mut n = 0.0;
    for (i, (a, b, s)) in zs.iter().enumerate() {
        n += station_count(*a, *b, *s) - if i == 1 { 2.0 } else { 0.0 };
    }
    n
}

/// Where the stirrups are: the middle zone's ends are the end zones' own.
pub fn places(zs: &[(f64, f64, f64)]) -> Vec<f64> {
    let mut out = Vec::new();
    for (i, (a, b, s)) in zs.iter().enumerate() {
        let pts = stations(*a, *b, *s);
        if i == 1 {
            let n = pts.len();
            out.extend(pts.into_iter().take(n - 1).skip(1));
        } else {
            out.extend(pts);
        }
    }
    out
}

/// A closed loop (its last point its first) with a hook: a tail turned into the section from
/// its first corner, along the bisector of the corner's two sides, at both ends of the path.
pub fn hooked(loop_: Vec<V3>, hook: f64) -> Vec<V3> {
    if !(hook > TOL) || loop_.len() < 3 {
        return loop_;
    }
    let c0 = loop_[0];
    let c1 = loop_[1];
    let cl = loop_[loop_.len() - 2];
    let e1 = unit(vsub(c1, c0));
    let e2 = unit(vsub(cl, c0));
    let dir = unit(add(e1, e2));
    let tail = [c0[0] + dir[0] * hook, c0[1] + dir[1] * hook, c0[2] + dir[2] * hook];
    let mut out = Vec::with_capacity(loop_.len() + 2);
    out.push(tail);
    out.extend(loop_);
    out.push(tail);
    out
}
