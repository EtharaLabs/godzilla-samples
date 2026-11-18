//! A column's bars (a column or a structural column): `bars` along each face of a rectangular
//! section (`x` across its width, `y` across its depth, corners counted) or `count` round a
//! round one, legs turned into the section at the foot and the top (`hook`), a step toward the
//! axis near the top (`jog`); `stirrup`s (a round column's a polygon of 24 sides), `ties`
//! across a rectangular section, `anchor`s past the ends. Laid out in the column's frame: up
//! along its axis from its base, across along its width (its angle), and along its depth.

use super::beam::legs;
use super::de::{any, f, sub, u};
use super::geom::{add as vadd, spread, sub as vsub, unit, Frame, V3, TOL};
use super::shapes::{COLUMN_ANCHOR, COLUMN_BARS, STIRRUP, TIES};
use super::{check_keys, diameter, norm, not_negative, positive, read_struct, stir, Armed, Bar, Ctx, MAX_COUNT};
use crate::json::Value;
use crate::structure::common::R;
use crate::structure::members::geom::column_geom;
use crate::structure::rebar::MAX_BARS;

/// The sides of a round column's stirrups.
pub const ROUND_SIDES: usize = 24;

/// A bar of a column: where it is and which way its legs and its jog go.
#[derive(Clone, Copy)]
struct Place {
    a: f64,
    b: f64,
    /// A round column's bar: the radius it is on.
    r: f64,
    /// The way into the section along across and along the depth (a corner bar's legs go
    /// along the depth; its jog both ways; a round column's bar's toward the axis).
    leg: (f64, f64),
    jog: (f64, f64),
}

pub fn arm(ctx: &Ctx) -> R<Armed> {
    let pr = ctx.pr;
    let g = column_geom(pr, ctx.e).ok_or_else(|| "the column has no section".to_string())?;
    let params = ctx.params;
    let bars = read_struct(params, "bars", &COLUMN_BARS)?;
    let stirrup = read_struct(params, "stirrup", &STIRRUP)?;
    let ties = read_struct(params, "ties", &TIES)?;
    let anchor = read_struct(params, "anchor", &COLUMN_ANCHOR)?;
    check_keys(params, "column")?;
    if bars.is_none() && stirrup.is_none() {
        return Err("nothing to reinforce with: give `bars` or a `stirrup`".into());
    }
    let cv = ctx.cover;
    let ds = match &stirrup {
        Some(m) => diameter("stirrup", f(m, "diameter").unwrap_or(0.0))?,
        None => 0.0,
    };
    let round = g.section.round;
    let w = g.section.width;
    let dp = if round { w } else { g.section.depth };
    let hw = w / 2.0;
    let hd = dp / 2.0;
    if round {
        if hw - cv.sides - ds <= 0.0 {
            return Err("the section is too narrow for that cover and stirrup".into());
        }
    } else if w - 2.0 * cv.sides - 2.0 * ds <= 0.0 || dp - 2.0 * cv.sides - 2.0 * ds <= 0.0 {
        return Err("the section is too narrow for that cover and stirrup".into());
    }
    let height = g.top - g.base;
    let (t0, t1) = {
        let below = anchor.as_ref().and_then(|m| f(m, "below"));
        let above = anchor.as_ref().and_then(|m| f(m, "above"));
        let t0 = match below {
            Some(x) => -not_negative("anchor below", x)?,
            None => cv.bottom,
        };
        let t1 = match above {
            Some(x) => height + not_negative("anchor above", x)?,
            None => height - cv.top,
        };
        (t0, t1)
    };
    if height - cv.bottom - cv.top <= 0.0 {
        return Err("the column is too short for that cover".into());
    }
    let (s, c) = g.angle.to_radians().sin_cos();
    let across = [c, s, 0.0];
    let up = [-s, c, 0.0];
    let fr = Frame { o: [g.at[0], g.at[1], g.base - ctx.host.elevation], along: [0.0, 0.0, 1.0], across, up };
    let gb = ctx.common.grade.clone();
    let gs = ctx.common.grade_stirrup.clone();
    let mut out: Vec<Bar> = Vec::new();
    // the bars, where they are and their paths
    let mut bar_paths: Vec<Vec<V3>> = Vec::new();
    let mut bar_d = 0.0;
    // the interior bars of the faces, for the ties: across of the x faces', along the depth of the y faces'
    let mut x_inner: Vec<f64> = Vec::new();
    let mut y_inner: Vec<f64> = Vec::new();
    // what the check reads of the bars: how many, how thick, the most between two along a face
    let mut bar_info: Option<(usize, f64, Option<f64>)> = None;
    if let Some(m) = &bars {
        let d = diameter("bars", f(m, "diameter").unwrap_or(0.0))?;
        bar_d = d;
        let hooks = legs("bars hook", ("below", "above"), any(m, "hook"))?;
        let jog = match sub(m, "jog") {
            Some(j) => {
                let by = positive("jog by", f(j, "by").unwrap_or(0.0))?;
                let ft = positive("jog from_top", f(j, "from_top").unwrap_or(0.0))?;
                let slope = f(j, "slope").unwrap_or(6.0);
                if !(1.0..=50.0).contains(&slope) {
                    return Err(format!(
                        "`jog` slope {} isn't between 1 and 50 mm along the column for each mm across",
                        slope
                    ));
                }
                let start = height - ft;
                let run = by * slope;
                if start <= t0 + TOL || start + run >= t1 - TOL {
                    return Err(format!(
                        "the jog doesn't fit the bars: it starts {} mm below the top and runs {:.0} mm up, and the bars run from {:.0} to {:.0} mm",
                        ft, run, t0, t1
                    ));
                }
                Some((by, start, start + run))
            }
            None => None,
        };
        let clear = ctx.common.clearance_for(&[d]);
        // (where, leg direction, jog direction) of each bar in local coordinates
        let mut places: Vec<Place> = Vec::new();
        let mut face: Option<f64> = None;
        let span;
        if round {
            if u(m, "x").is_some() || u(m, "y").is_some() {
                return Err("a round column takes `count` bars round its circle, not `x` and `y`".into());
            }
            let n = match u(m, "count") {
                Some(n) => n,
                None => return Err("a round column needs `bars` count: how many round its circle".into()),
            };
            if !(3..=MAX_COUNT).contains(&n) {
                return Err(format!("`bars` count {} isn't 3 to 1000", n));
            }
            let n = n as usize;
            let r = hw - cv.sides - ds - d / 2.0;
            if r < 0.0 {
                return Err(format!("the section is too narrow for the bars of {} mm with that cover and stirrup", d));
            }
            let chord = 2.0 * r * (std::f64::consts::PI / n as f64).sin();
            let gap = chord - d;
            if gap < clear - TOL {
                return Err(format!(
                    "{} bars of {} mm leave {:.1} mm between them round the circle, less than the {} mm clearance: use fewer or thinner bars",
                    n, d, gap, clear
                ));
            }
            span = 2.0 * r;
            for i in 0..n {
                let phi = 2.0 * std::f64::consts::PI * i as f64 / n as f64;
                let (ps, pc) = phi.sin_cos();
                let (a, b) = (r * pc, r * ps);
                // toward the axis: the bar's place reversed, over the radius
                let toward = (-a / r, -b / r);
                places.push(Place { a, b, r, leg: toward, jog: toward });
            }
        } else {
            if u(m, "count").is_some() {
                return Err("a rectangular column takes `x` and `y` bars along its faces, not `count`".into());
            }
            let nx = u(m, "x").unwrap_or(2);
            if !(2..=MAX_COUNT).contains(&nx) {
                return Err(format!("`bars x` is {} bars along a face; it is 2 (the corners) to 1000", nx));
            }
            let ny = u(m, "y").unwrap_or(2);
            if !(2..=MAX_COUNT).contains(&ny) {
                return Err(format!("`bars y` is {} bars along a face; it is 2 (the corners) to 1000", ny));
            }
            let (nx, ny) = (nx as usize, ny as usize);
            let a = hw - cv.sides - ds - d / 2.0;
            let b = hd - cv.sides - ds - d / 2.0;
            for (n, half, name) in [(nx, a, "x"), (ny, b, "y")] {
                if half < 0.0 {
                    return Err(format!(
                        "the section is too narrow for the {} face bars of {} mm with that cover and stirrup",
                        name, d
                    ));
                }
                let gap = 2.0 * half / (n - 1) as f64 - d;
                if gap < clear - TOL {
                    return Err(format!(
                        "{} {} face bars of {} mm leave {:.1} mm between them, less than the {} mm clearance: use fewer or thinner bars",
                        n, name, d, gap, clear
                    ));
                }
            }
            span = (2.0 * a).min(2.0 * b);
            face = Some((2.0 * a / (nx - 1) as f64).max(2.0 * b / (ny - 1) as f64));
            let xs = spread(-a, a, nx);
            let ys = spread(-b, b, ny);
            for (sb, bb) in [(-1.0, -b), (1.0, b)] {
                for (i, xa) in xs.iter().enumerate() {
                    let corner = i == 0 || i == nx - 1;
                    let sa = if *xa < 0.0 { 1.0 } else { -1.0 };
                    let jog = if corner { (sa, -sb) } else { (0.0, -sb) };
                    places.push(Place { a: *xa, b: bb, r: 0.0, leg: (0.0, -sb), jog });
                }
            }
            for (sa, aa) in [(1.0, -a), (-1.0, a)] {
                for yb in &ys[1..ny - 1] {
                    places.push(Place { a: aa, b: *yb, r: 0.0, leg: (sa, 0.0), jog: (sa, 0.0) });
                }
            }
            x_inner = xs[1..nx - 1].to_vec();
            y_inner = ys[1..ny - 1].to_vec();
        }
        bar_info = Some((places.len(), d, face));
        for hk in [hooks.0, hooks.1] {
            if hk > span + TOL {
                return Err(format!(
                    "a bars hook of {} mm doesn't fit in a section {:.1} mm across between the bars",
                    hk, span
                ));
            }
        }
        // after the jog the bars keep the clearance from one another
        if let Some((by, _, _)) = jog {
            let moved: Vec<(f64, f64)> =
                places.iter().map(|p| (p.a + p.jog.0 * by, p.b + p.jog.1 * by)).collect();
            let mut least = f64::INFINITY;
            for i in 0..moved.len() {
                for j in i + 1..moved.len() {
                    let da = moved[i].0 - moved[j].0;
                    let db = moved[i].1 - moved[j].1;
                    least = least.min((da * da + db * db).sqrt());
                }
            }
            let gap = least - d;
            if gap < clear - TOL {
                return Err(format!(
                    "after the jog two bars are {:.1} mm apart, less than the {} mm clearance: give a smaller `by`, or fewer bars",
                    gap, clear
                ));
            }
        }
        for p in &places {
            // the leg's end: across the face into the section, a round bar's toward the axis
            // (a round column's: its place scaled to the circle `h` nearer the axis)
            let leg = |t: f64, h: f64| -> V3 {
                if round {
                    fr.at(t, p.a * (p.r - h) / p.r, p.b * (p.r - h) / p.r)
                } else {
                    fr.at(t, p.a + p.leg.0 * h, p.b + p.leg.1 * h)
                }
            };
            let mut path: Vec<V3> = Vec::with_capacity(6);
            if hooks.0 > TOL {
                path.push(leg(t0, hooks.0));
            }
            let foot = fr.at(t0, p.a, p.b);
            let head = fr.at(t1, p.a, p.b);
            path.push(foot);
            // the step's points are on the bar, at their share of its length
            let on_bar = |t: f64| -> V3 {
                let k = (t - t0) / (t1 - t0);
                [
                    foot[0] + (head[0] - foot[0]) * k,
                    foot[1] + (head[1] - foot[1]) * k,
                    foot[2] + (head[2] - foot[2]) * k,
                ]
            };
            // the points over the step move with it, a hook's leg too
            // (by the step across the section, turned into the world)
            let shift = match jog {
                Some((by, j0, _)) => {
                    path.push(on_bar(j0));
                    let (da, db) = (p.jog.0 * by, p.jog.1 * by);
                    Some([
                        across[0] * da + up[0] * db,
                        across[1] * da + up[1] * db,
                        across[2] * da + up[2] * db,
                    ])
                }
                None => None,
            };
            let moved = |q: V3| -> V3 {
                match shift {
                    Some(s) => [q[0] + s[0], q[1] + s[1], q[2] + s[2]],
                    None => q,
                }
            };
            if let Some((_, _, j1)) = jog {
                path.push(moved(on_bar(j1)));
            }
            path.push(moved(head));
            if hooks.1 > TOL {
                path.push(moved(leg(t1, hooks.1)));
            }
            bar_paths.push(path);
        }
    }
    let _ = bar_d;
    for path in bar_paths {
        out.push(Bar { path, diameter: bar_d, grade: gb.clone(), layer: "bars".into() });
    }
    // the stirrups and the ties
    let mut stirrup_info: Option<(f64, f64)> = None;
    if let Some(m) = &stirrup {
        let st = stir::read_rest(m, ds)?;
        let mut tie: Option<(f64, f64)> = None;
        if let Some(tm) = &ties {
            if round {
                return Err("a round column has no ties: they go across a rectangular section".into());
            }
            let dt = diameter("ties", f(tm, "diameter").unwrap_or(0.0))?;
            let th = match f(tm, "hook") {
                Some(h) => not_negative("ties hook", h)?,
                None => 0.0,
            };
            if x_inner.is_empty() && y_inner.is_empty() {
                return Err(
                    "no tie to make: ties go across the section between bars that are not at a corner, so `bars` needs x or y over 2"
                        .into(),
                );
            }
            tie = Some((dt, th));
        }
        let s0 = cv.bottom + ds / 2.0;
        let s1 = height - cv.top - ds / 2.0;
        let zs = stir::zones(s0, s1, &st);
        let per = 1 + if tie.is_some() { x_inner.len() + y_inner.len() } else { 0 };
        if stir::count(&zs) * per as f64 + out.len() as f64 > MAX_BARS as f64 {
            return Err(format!(
                "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
                MAX_BARS
            ));
        }
        let sa = hw - cv.sides - ds / 2.0;
        let sb = hd - cv.sides - ds / 2.0;
        let ia = hw - cv.sides - ds;
        let ib = hd - cv.sides - ds;
        let stations = stir::places(&zs);
        stirrup_info = Some((ds, norm::largest_gap(&stations)));
        for t in stations {
            let shape: Vec<V3> = if round {
                let rs = hw - cv.sides - ds / 2.0;
                let mut v: Vec<V3> = (0..ROUND_SIDES)
                    .map(|k| {
                        let phi = 2.0 * std::f64::consts::PI * k as f64 / ROUND_SIDES as f64;
                        let (ps, pc) = phi.sin_cos();
                        fr.at(t, rs * pc, rs * ps)
                    })
                    .collect();
                v.push(v[0]);
                v
            } else {
                let c0 = fr.at(t, -sa, sb);
                vec![c0, fr.at(t, sa, sb), fr.at(t, sa, -sb), fr.at(t, -sa, -sb), c0]
            };
            out.push(Bar { path: stir::hooked(shape, st.hook), diameter: ds, grade: gs.clone(), layer: "stirrup".into() });
            if let Some((dt, th)) = tie {
                // a tie's tails turn into the section, toward the other axis
                let tie_path = |p0: V3, p1: V3, other: V3| -> Vec<V3> {
                    if !(th > TOL) {
                        return vec![p0, p1];
                    }
                    let al = unit(vsub(p1, p0));
                    let dir = unit(vadd(al, other));
                    vec![
                        [p0[0] + dir[0] * th, p0[1] + dir[1] * th, p0[2] + dir[2] * th],
                        p0,
                        p1,
                        [p1[0] - dir[0] * th, p1[1] - dir[1] * th, p1[2] - dir[2] * th],
                    ]
                };
                for xa in &x_inner {
                    let path = tie_path(fr.at(t, *xa, -ib), fr.at(t, *xa, ib), across);
                    out.push(Bar { path, diameter: dt, grade: gs.clone(), layer: "tie".into() });
                }
                for yb in &y_inner {
                    let path = tie_path(fr.at(t, -ia, *yb), fr.at(t, ia, *yb), up);
                    out.push(Bar { path, diameter: dt, grade: gs.clone(), layer: "tie".into() });
                }
            }
        }
    } else if ties.is_some() {
        return Err("ties go with the stirrups: give a `stirrup` too".into());
    }
    if out.len() > MAX_BARS {
        return Err(format!(
            "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
            MAX_BARS
        ));
    }
    let _ = Value::Null;
    let nc = norm::Column { round, width: w, depth: dp, bars: bar_info, stirrup: stirrup_info };
    Ok(Armed { bars: out, info: norm::Info { cover: Some(cv), kind: norm::Kind::Column(nc) } })
}
