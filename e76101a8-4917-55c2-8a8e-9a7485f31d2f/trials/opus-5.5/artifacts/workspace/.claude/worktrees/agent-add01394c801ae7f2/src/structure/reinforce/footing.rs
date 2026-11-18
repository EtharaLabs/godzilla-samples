//! An isolated footing's bars: a `mesh` of two layers at its bottom, `x` along its width (its
//! angle) and `y` across it on top of the first, at most a spacing apart, their ends a cover
//! short of its sides (a round footing's at its circle), turned up by `hook`.

use super::de::{f, sub};
use super::geom::{gaps, station_count, Frame, V3, TOL};
use super::shapes::MESH;
use super::{check_keys, diameter, norm, not_negative, read_struct, spacing, Armed, Bar, Ctx};
use crate::structure::common::R;
use crate::structure::members::geom::column_geom;
use crate::structure::rebar::MAX_BARS;

/// A layer of a mesh as read and checked.
pub struct Layer {
    pub name: &'static str,
    pub d: f64,
    pub spacing: f64,
}

pub fn arm(ctx: &Ctx) -> R<Armed> {
    let pr = ctx.pr;
    let g = column_geom(pr, ctx.e).ok_or_else(|| "the footing has no section".to_string())?;
    let params = ctx.params;
    let mesh = read_struct(params, "mesh", &MESH)?;
    check_keys(params, "footing")?;
    let mesh = match mesh {
        Some(m) if m.contains("x") || m.contains("y") => m,
        _ => return Err("nothing to reinforce with: give a `mesh` with `x` or `y` bars".into()),
    };
    let cv = ctx.cover;
    let hook = match f(&mesh, "hook") {
        Some(h) => not_negative("hook", h)?,
        None => 0.0,
    };
    let round = g.section.round;
    let w = g.section.width;
    let dp = if round { w } else { g.section.depth };
    let hw = w / 2.0;
    let hd = dp / 2.0;
    let thick = g.top - g.base;
    let (s, c) = g.angle.to_radians().sin_cos();
    let across = [c, s, 0.0];
    let up = [-s, c, 0.0];
    let fr = Frame { o: [g.at[0], g.at[1], g.base - ctx.host.elevation], along: [0.0, 0.0, 1.0], across, up };
    let clear_of = |d: f64| ctx.common.clearance_for(&[d]);
    let mut layers: Vec<(Layer, f64, f64, f64)> = Vec::new(); // layer, z, row half, run half
    let mut z_next = cv.bottom;
    let mut total = 0.0;
    for (key, name) in [("x", "mesh x"), ("y", "mesh y")] {
        let m = match sub(&mesh, key) {
            Some(m) => m,
            None => continue,
        };
        if key == "y" {
            // the second layer lies on the first: both inside the covers
            let dx = layers.first().map(|l| l.0.d).unwrap_or(0.0);
            let dy = f(m, "diameter").unwrap_or(0.0);
            if dx + dy > thick - cv.top - cv.bottom {
                return Err(format!(
                    "the mesh doesn't fit the footing's {} mm thickness between the covers",
                    thick
                ));
            }
        }
        let d = diameter(name, f(m, "diameter").unwrap_or(0.0))?;
        let sp = spacing(name, f(m, "spacing").unwrap_or(0.0), d)?;
        // the rows spread across the other way, the bars run this way
        let (row_half, run_half) = if key == "x" { (hd, hw) } else { (hw, hd) };
        let a = row_half - cv.sides - d / 2.0;
        if a < 0.0 {
            return Err(format!("the {} bars don't fit inside that cover", name));
        }
        let run = run_half - cv.sides;
        if run <= TOL {
            return Err("the footing is too small for that cover".into());
        }
        if key == "x" && d > thick - cv.top - cv.bottom {
            return Err(format!("the mesh doesn't fit the footing's {} mm thickness between the covers", thick));
        }
        let span = 2.0 * a;
        let n = gaps(span, sp);
        if span > 0.0 {
            let step = span / n as f64;
            let gap = step - d;
            let cl = clear_of(d);
            if gap < cl - TOL {
                return Err(format!(
                    "{} bars of {} mm each {:.1} mm leave {:.1} mm between them, less than the {} mm clearance: widen the spacing",
                    name, d, step, gap, cl
                ));
            }
        }
        let z = z_next + d / 2.0;
        if hook > 0.0 && hook + d / 2.0 > (thick - cv.top) - z {
            return Err(format!(
                "a hook of {} mm turned up from the {} bars reaches past the top cover of a footing {} mm thick",
                hook, name, thick
            ));
        }
        z_next += d;
        total += d;
        if station_count(-a, a, sp) > (MAX_BARS + 1) as f64 {
            return Err(format!(
                "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
                MAX_BARS
            ));
        }
        layers.push((Layer { name, d, spacing: sp }, z, a, run));
    }
    let _ = total;
    let gb = ctx.common.grade.clone();
    let mut out: Vec<Bar> = Vec::new();
    for (l, z, a, run) in &layers {
        let rows = rows(-*a, *a, l.spacing);
        for r in rows {
            let ext = if round {
                let rr = hw - ctx.cover.sides;
                let q = rr * rr - r * r;
                if q <= 0.0 {
                    continue;
                }
                q.sqrt()
            } else {
                *run
            };
            let at = |x: f64| -> V3 {
                if l.name == "mesh x" {
                    fr.at(*z, x, r)
                } else {
                    fr.at(*z, r, x)
                }
            };
            let lift = |x: f64| -> V3 {
                if l.name == "mesh x" {
                    fr.at(*z + hook, x, r)
                } else {
                    fr.at(*z + hook, r, x)
                }
            };
            let mut path = Vec::with_capacity(4);
            if hook > 0.0 {
                path.push(lift(-ext));
            }
            path.push(at(-ext));
            path.push(at(ext));
            if hook > 0.0 {
                path.push(lift(ext));
            }
            out.push(Bar { path, diameter: l.d, grade: gb.clone(), layer: l.name.into() });
        }
    }
    if out.len() > MAX_BARS {
        return Err(format!(
            "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
            MAX_BARS
        ));
    }
    Ok(Armed { bars: out, info: norm::Info { cover: Some(ctx.cover), kind: norm::Kind::Footing } })
}

/// The rows of a mesh layer from `a` to `b`, at most `spacing` apart; one where there's no room.
pub fn rows(a: f64, b: f64, spacing: f64) -> Vec<f64> {
    if b - a <= 0.0 {
        return vec![a];
    }
    super::geom::stations(a, b, spacing)
}
