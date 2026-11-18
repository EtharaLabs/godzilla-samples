//! The height of the top of what a spot elevation stands on, at its point: a floor's top (sloped
//! or not), a roof's top along its slopes, a wall's or a column's top, a run's top along it, a
//! component's top.

use super::geo::{self, P};
use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, Ctx};

fn level_elev(pr: &Project, e: &Value) -> f64 {
    common::text(e, "level").and_then(|g| common::level_elev(pr, g)).unwrap_or(0.0)
}

/// How far `p` lies inside the edge from `a` to `b` of an outline (square to it).
fn edge_dist(p: P, a: P, b: P) -> f64 {
    let d = geo::unit(geo::sub(b, a));
    geo::cross(d, geo::sub(p, a)).abs()
}

fn type_def<'p>(pr: &'p Project, e: &Value) -> Option<&'p Value> {
    common::element_type(pr, e).map(|(_, d)| d)
}

/// A family's parameter for a component: its own value, its type's, its family's.
pub fn family_param(pr: &Project, e: &Value, name: &str) -> Option<f64> {
    if let Some(v) = e.get("params").and_then(|p| p.get(name)).and_then(|v| v.as_f64()) {
        return Some(v);
    }
    let fg = common::text(e, "family")?;
    let (fname, fam) = common::family(pr, fg)?;
    if let Some(tn) = common::text(e, "type").and_then(|g| common::family_type(pr, &fname, g)) {
        if let Some(v) = fam.get("types").and_then(|t| t.get(&tn)).and_then(|t| t.get(name)).and_then(|v| v.as_f64()) {
            return Some(v);
        }
    }
    for p in fam.get("parameters")?.as_arr()? {
        if common::text(p, "name") == Some(name) {
            return common::num(p, "value");
        }
    }
    None
}

/// The top of a roof at `p`: its planes rising from its edges (less the overhang) at their slopes,
/// the lowest of them there, and its thickness over that.
fn roof_top(pr: &Project, e: &Value, p: P) -> Option<f64> {
    let base = level_elev(pr, e) + common::num(e, "offset").unwrap_or(0.0);
    let t = type_def(pr, e).and_then(|d| common::num(d, "thickness")).unwrap_or(0.0);
    let slope = common::num(e, "slope").unwrap_or(0.0);
    let pts = common::points(e.get("boundary").unwrap_or(&Value::Null));
    let over = common::num(e, "overhang").unwrap_or(0.0);
    let gables: Vec<usize> = e
        .get("gables")
        .and_then(|g| g.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect())
        .unwrap_or_default();
    let slopes: Vec<f64> = e
        .get("slopes")
        .and_then(|g| g.as_arr())
        .map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect())
        .unwrap_or_default();
    let n = pts.len();
    let mut best: Option<(f64, f64)> = None;
    for i in 0..n {
        if gables.contains(&i) {
            continue;
        }
        let s = match slopes.get(i) {
            Some(x) if *x != 0.0 => *x,
            _ => slope,
        };
        if s <= 0.0 {
            continue;
        }
        let (a, b) = (pts[i], pts[(i + 1) % n]);
        let h = (edge_dist(p, a, b) - over) * s.to_radians().tan();
        if best.map(|(bh, _)| h < bh).unwrap_or(true) {
            best = Some((h, s));
        }
    }
    match best {
        Some((h, s)) => Some(base + h + t / s.to_radians().cos()),
        None => Some(base + t),
    }
}

/// The top of a floor at `p`: its level and offset, risen along its arrow at its slope.
fn floor_top(pr: &Project, e: &Value, p: P) -> f64 {
    let mut z = level_elev(pr, e) + common::num(e, "offset").unwrap_or(0.0);
    if let (Some(s), Some(arrow)) = (common::num(e, "slope"), e.get("arrow")) {
        let pts = common::points(arrow);
        if pts.len() == 2 && s != 0.0 {
            let d = geo::unit(geo::sub(pts[1], pts[0]));
            z += geo::dot(geo::sub(p, pts[0]), d) * s.to_radians().tan();
        }
    }
    z
}

/// The top of a run (pipe, duct, beam…) at `p`: its line's height there and its size over it.
fn run_top(pr: &Project, e: &Value, p: P) -> Option<f64> {
    let a = geo::pt(e.get("start"))?;
    let b = geo::pt(e.get("end"))?;
    let o1 = common::num(e, "offset").unwrap_or(0.0);
    let o2 = common::num(e, "end_offset").unwrap_or(o1);
    let l = geo::dist(a, b);
    let f = if l > 0.0 { (geo::dot(geo::sub(p, a), geo::sub(b, a)) / (l * l)).clamp(0.0, 1.0) } else { 0.0 };
    let z = level_elev(pr, e) + o1 + (o2 - o1) * f;
    let depth = type_def(pr, e).and_then(|d| common::num(d, "depth")).unwrap_or(0.0);
    let just = common::text(e, "justify").unwrap_or(if common::category(e) == "beam" { "top" } else { "centre" });
    Some(match just {
        "top" => z,
        "bottom" => z + depth,
        _ => z + depth / 2.0,
    })
}

/// The height of the top of `h` (the spot's host) at `p`.
pub fn top_at(cx: &Ctx, _hid: u64, h: &Value, p: P) -> Option<f64> {
    let pr = cx.pr;
    match common::category(h) {
        "floor" => Some(floor_top(pr, h, p)),
        "roof" => roof_top(pr, h, p),
        "wall" | "column" | "structuralcolumn" => {
            Some(level_elev(pr, h) + common::num(h, "base_offset").unwrap_or(0.0) + common::num(h, "height").unwrap_or(0.0))
        }
        "footing" => Some(level_elev(pr, h) + common::num(h, "offset").unwrap_or(0.0)),
        "component" => Some(level_elev(pr, h) + common::num(h, "offset").unwrap_or(0.0) + family_param(pr, h, "Height").unwrap_or(0.0)),
        "beam" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor" | "groundconductor" | "cable" | "stripfooting" => run_top(pr, h, p),
        "ceiling" => Some(level_elev(pr, h) + common::num(h, "offset").unwrap_or(2600.0)),
        "stair" | "ramp" => {
            let top = common::text(h, "top_level").and_then(|g| common::level_elev(pr, g));
            Some(top.unwrap_or_else(|| level_elev(pr, h) + common::num(h, "height").unwrap_or(0.0)))
        }
        _ => None,
    }
}
