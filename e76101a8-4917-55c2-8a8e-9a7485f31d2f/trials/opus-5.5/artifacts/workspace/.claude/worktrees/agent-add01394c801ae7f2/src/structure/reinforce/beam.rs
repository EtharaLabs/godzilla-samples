//! A beam's bars: `bottom` and `top` rows (hooks; some bottom bars bent up), `stirrup`s (closer
//! at the ends, hooked), `skin` bars up each side, `anchor`s past the ends. Laid out in the
//! beam's frame: along its centre line from its start, across it (level, to the left), up
//! square to both; its section's centre at the origin.

use super::de::{self, any, f, sub, u};
use super::geom::{gaps, spread, unit, Frame, TOL};
use super::shapes::{BEAM_ANCHOR, PITCH, ROW, STIRRUP};
use super::{check_keys, count, diameter, norm, not_negative, positive, read_struct, spacing, stir, Armed, Bar, Ctx};
use crate::json::{Map, Value};
use crate::structure::common::R;
use crate::structure::members::geom::run_geom;
use crate::structure::rebar::MAX_BARS;

/// A row's hooks at the start and at the end, read from `hook`: a length for both, or
/// {start, end}.
pub fn legs(what: &str, ends: (&str, &str), v: Option<&Value>) -> R<(f64, f64)> {
    let bad = || format!("`{}` must be a length in mm, or {{{}, {}}}", what, ends.0, ends.1);
    match v {
        None | Some(Value::Null) => Ok((0.0, 0.0)),
        Some(Value::Num(n)) => {
            let x = not_negative(what, n.as_f64())?;
            Ok((x, x))
        }
        Some(Value::Obj(m)) => {
            let mut a = 0.0;
            let mut b = 0.0;
            for (k, x) in m.iter() {
                let val = match x {
                    Value::Null => 0.0,
                    Value::Num(n) => n.as_f64(),
                    _ => return Err(bad()),
                };
                if k == ends.0 {
                    a = val;
                } else if k == ends.1 {
                    b = val;
                } else {
                    return Err(bad());
                }
            }
            let a = not_negative(what, a)?;
            let b = not_negative(what, b)?;
            Ok((a, b))
        }
        Some(_) => Err(bad()),
    }
}

/// The bars a row's `bent` takes: `k` of the `m` inner ones, evenly (indices into the inner).
pub fn picks(m: usize, k: usize) -> Vec<usize> {
    if k == 0 || m == 0 {
        return Vec::new();
    }
    if k == 1 {
        return vec![(m - 1) / 2];
    }
    (0..k).map(|i| ((i as f64) * ((m - 1) as f64) / ((k - 1) as f64)).round() as usize).collect()
}

/// The beam's centre line as the original lays bars along it (a stand-in for MEMBERS' axis,
/// whose last digits differ on a sloped beam): its ends, heights absolute, the centre half the
/// depth plumb under (or over) the justify line: on a sloped beam half the depth times its
/// length along the slope over its length in plan (both as `hypot` gives them).
fn centre_line(g: &crate::structure::members::geom::RunGeom) -> [[f64; 3]; 2] {
    use crate::structure::members::geom::Justify;
    let l = &g.line;
    let dx = l.end[0] - l.start[0];
    let dy = l.end[1] - l.start[1];
    let rise = l.end_offset - l.offset;
    let plan = dx.hypot(dy);
    let half = if g.stands {
        0.0
    } else if rise == 0.0 {
        g.section.depth / 2.0
    } else {
        g.section.depth / 2.0 * plan.hypot(rise) / plan
    };
    let centre = |z: f64| match l.justify {
        Justify::Top => z - half,
        Justify::Centre => z,
        Justify::Bottom => z + half,
    };
    let z0 = centre(g.elevation + l.offset);
    let z1 = centre(g.elevation + l.end_offset);
    [[l.start[0], l.start[1], z0], [l.end[0], l.end[1], z1]]
}

/// A row of bars as read.
struct Row {
    n: usize,
    d: f64,
    hooks: (f64, f64),
    /// count, angle, top
    bent: Option<(usize, f64, f64)>,
    /// Across, where each bar is.
    at: Vec<f64>,
    /// Up, where the row is.
    u: f64,
}

pub fn arm(ctx: &Ctx) -> R<Armed> {
    let pr = ctx.pr;
    let g = run_geom(pr, ctx.e).ok_or_else(|| "the beam has no section".to_string())?;
    if g.section.round {
        return Err("a round beam isn't reinforced yet; a rectangular one is".into());
    }
    let params = ctx.params;
    let bottom = read_struct(params, "bottom", &ROW)?;
    let top = read_struct(params, "top", &ROW)?;
    let stirrup = read_struct(params, "stirrup", &STIRRUP)?;
    let skin = read_struct(params, "skin", &PITCH)?;
    let anchor = read_struct(params, "anchor", &BEAM_ANCHOR)?;
    check_keys(params, "beam")?;
    if bottom.is_none() && top.is_none() && stirrup.is_none() {
        return Err("nothing to reinforce with: give `bottom` or `top` bars, or a `stirrup`".into());
    }
    let cv = ctx.cover;
    let ds = match &stirrup {
        Some(m) => diameter("stirrup", f(m, "diameter").unwrap_or(0.0))?,
        None => 0.0,
    };
    let w = g.section.width;
    let h = g.section.depth;
    let hw = w / 2.0;
    let hh = h / 2.0;
    let inner_w = w - 2.0 * cv.sides - 2.0 * ds;
    let inner_h = h - cv.top - cv.bottom - 2.0 * ds;
    if inner_w <= 0.0 || inner_h <= 0.0 {
        return Err("the section is too narrow or too shallow for that cover and stirrup".into());
    }
    // the box inside the stirrup: across its sides, up to its top and down to its bottom
    let a_in = hw - cv.sides - ds;
    let top_in = hh - cv.top - ds;
    let bot_in = -(hh - cv.bottom - ds);
    // the frame: along the centre line, across it level, up square to both
    let [a0, a1] = centre_line(&g);
    let dv = [a1[0] - a0[0], a1[1] - a0[1], a1[2] - a0[2]];
    let len = dv[0].hypot(dv[1]).hypot(dv[2]);
    let along = unit(dv);
    let across = unit([-along[1], along[0], 0.0]);
    let up = super::geom::cross(along, across);
    // the origin over the beam's level
    let fr = Frame { o: [a0[0], a0[1], a0[2] - ctx.host.elevation], along, across, up };
    // how far the bars run: past the ends by the anchors, else a cover short of them
    let (t0, t1) = {
        let st = anchor.as_ref().and_then(|m| f(m, "start"));
        let en = anchor.as_ref().and_then(|m| f(m, "end"));
        let t0 = match st {
            Some(x) => -not_negative("anchor start", x)?,
            None => cv.sides,
        };
        let t1 = match en {
            Some(x) => len + not_negative("anchor end", x)?,
            None => len - cv.sides,
        };
        (t0, t1)
    };
    let clear = |ds_: &[f64]| ctx.common.clearance_for(ds_);
    // the rows
    let read_row = |m: &Map, name: &str, is_top: bool| -> R<Row> {
        let d = diameter(name, f(m, "diameter").unwrap_or(0.0))?;
        let n = count(name, u(m, "count").unwrap_or(0))?;
        let a = a_in - d / 2.0;
        if a < 0.0 {
            return Err(format!(
                "the section is too narrow for the {} bars of {} mm with that cover and stirrup",
                name, d
            ));
        }
        if inner_h < d {
            return Err(format!("a {} mm {} bar doesn't fit inside the stirrup, {:.1} mm deep", d, name, inner_h));
        }
        let hooks = legs(&format!("{} hook", name), ("start", "end"), any(m, "hook"))?;
        for hk in [hooks.0, hooks.1] {
            if hk > inner_h - d / 2.0 + TOL {
                return Err(format!(
                    "a {} hook of {} mm doesn't fit inside the stirrup, which is {:.1} mm deep from the bars",
                    name, hk, inner_h
                ));
            }
        }
        let u_row = if is_top { top_in - d / 2.0 } else { bot_in + d / 2.0 };
        let mut bent = None;
        if let Some(b) = sub(m, "bent") {
            if is_top {
                return Err("only bottom bars are bent up: put `bent` in `bottom`".into());
            }
            let k = u(b, "count").unwrap_or(0);
            let most = n as i64 - 2;
            if k < 1 || k as i64 > most {
                return Err(format!(
                    "`bent` count {} must be 1 to {}: the two bars at the corners stay straight to hold the stirrups, and the bottom row has {}",
                    k, most, n
                ));
            }
            let angle = f(b, "angle").unwrap_or(45.0);
            if !(15.0..=75.0).contains(&angle) {
                return Err(format!("`bent` angle {} degrees isn't between 15 and 75", angle));
            }
            let tp = match f(b, "top") {
                Some(x) => positive("bent top", x)?,
                None => (t1 - t0) / 5.0,
            };
            let zt = top_in - d / 2.0;
            let rise = zt - u_row;
            if rise <= TOL {
                return Err(format!(
                    "there's no room to bend a bar of {} mm up: it can't rise from the bottom to the top inside the stirrup",
                    d
                ));
            }
            let run = rise / angle.to_radians().tan();
            let each = tp + run;
            if 2.0 * each > t1 - t0 {
                return Err(format!(
                    "the bent bars meet in the middle: each end takes {:.0} mm of the {:.0} mm: give a shorter `top` or a steeper `angle`",
                    each,
                    t1 - t0
                ));
            }
            bent = Some((k as usize, angle, tp));
        }
        let at = spread(-a, a, n);
        if n > 1 {
            let gap = 2.0 * a / (n - 1) as f64 - d;
            let c = clear(&[d]);
            if gap < c - TOL {
                return Err(format!(
                    "{} {} bars of {} mm leave {:.1} mm between them, less than the {} mm clearance: use fewer or thinner bars",
                    n, name, d, gap, c
                ));
            }
        }
        Ok(Row { n, d, hooks, bent, at, u: u_row })
    };
    let brow = match &bottom {
        Some(m) => Some(read_row(m, "bottom", false)?),
        None => None,
    };
    let trow = match &top {
        Some(m) => Some(read_row(m, "top", true)?),
        None => None,
    };
    // a bent-up bar running along the top must keep clear of the top bars
    if let (Some(b), Some(t)) = (&brow, &trow) {
        if let Some((k, _, _)) = b.bent {
            let zt = top_in - b.d / 2.0;
            let inner: Vec<usize> = (1..b.n - 1).collect();
            let c = clear(&[b.d, t.d]);
            for j in picks(inner.len(), k) {
                let ab = b.at[inner[j]];
                for at in &t.at {
                    let da = ab - at;
                    let du = zt - t.u;
                    let gap = (da * da + du * du).sqrt() - (b.d + t.d) / 2.0;
                    if gap < c - TOL {
                        return Err(format!(
                            "a bent-up bar meets a top bar: {:.1} mm between them, less than the {} mm clearance: bend up other bars or use fewer top bars",
                            gap, c
                        ));
                    }
                }
            }
        }
    }
    // skin bars up each side, between the rows
    let skin_rows = match &skin {
        Some(m) => {
            let dk = diameter("skin", f(m, "diameter").unwrap_or(0.0))?;
            let sp = spacing("skin", f(m, "spacing").unwrap_or(0.0), dk)?;
            let ub = match &brow {
                Some(r) => r.u,
                None => bot_in,
            };
            let ut = match &trow {
                Some(r) => r.u,
                None => top_in,
            };
            let n = gaps(ut - ub, sp);
            let ak = a_in - dk / 2.0;
            let us: Vec<f64> = (1..n).map(|i| ub + (ut - ub) * i as f64 / n as f64).collect();
            Some((dk, ak, us))
        }
        None => None,
    };
    // the stirrups
    let mut st_stations: Vec<f64> = Vec::new();
    let mut st_hook = 0.0;
    if let Some(m) = &stirrup {
        let st = stir::read_rest(m, ds)?;
        st_hook = st.hook;
        let s0 = cv.sides + ds / 2.0;
        let s1 = len - (cv.sides + ds / 2.0);
        let zs = stir::zones(s0, s1, &st);
        let others = brow.as_ref().map(|r| r.n).unwrap_or(0)
            + trow.as_ref().map(|r| r.n).unwrap_or(0)
            + skin_rows.as_ref().map(|s| 2 * s.2.len()).unwrap_or(0);
        if stir::count(&zs) + others as f64 > MAX_BARS as f64 {
            return Err(format!(
                "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
                MAX_BARS
            ));
        }
        st_stations = stir::places(&zs);
    }
    // the bars
    let gb = ctx.common.grade.clone();
    let gs = ctx.common.grade_stirrup.clone();
    let mut bars: Vec<Bar> = Vec::new();
    let straight = |r: &Row, a: f64, up_sign: f64| -> Vec<[f64; 3]> {
        let mut p = Vec::with_capacity(4);
        if r.hooks.0 > TOL {
            p.push(fr.at(t0, a, r.u + up_sign * r.hooks.0));
        }
        p.push(fr.at(t0, a, r.u));
        p.push(fr.at(t1, a, r.u));
        if r.hooks.1 > TOL {
            p.push(fr.at(t1, a, r.u + up_sign * r.hooks.1));
        }
        p
    };
    if let Some(r) = &brow {
        let chosen: Vec<usize> = match r.bent {
            Some((k, _, _)) => picks(r.n - 2, k).into_iter().map(|j| j + 1).collect(),
            None => Vec::new(),
        };
        for (i, a) in r.at.iter().enumerate() {
            if chosen.contains(&i) {
                let (_, angle, tp) = r.bent.unwrap();
                let zt = top_in - r.d / 2.0;
                let run = (zt - r.u) / angle.to_radians().tan();
                let path = vec![
                    fr.at(t0, *a, zt),
                    fr.at(t0 + tp, *a, zt),
                    fr.at(t0 + tp + run, *a, r.u),
                    fr.at(t1 - tp - run, *a, r.u),
                    fr.at(t1 - tp, *a, zt),
                    fr.at(t1, *a, zt),
                ];
                bars.push(Bar { path, diameter: r.d, grade: gb.clone(), layer: "bent".into() });
            } else {
                bars.push(Bar { path: straight(r, *a, 1.0), diameter: r.d, grade: gb.clone(), layer: "bottom".into() });
            }
        }
    }
    if let Some(r) = &trow {
        for a in &r.at {
            bars.push(Bar { path: straight(r, *a, -1.0), diameter: r.d, grade: gb.clone(), layer: "top".into() });
        }
    }
    if let Some((dk, ak, us)) = &skin_rows {
        for uu in us {
            for a in [-*ak, *ak] {
                let path = vec![fr.at(t0, a, *uu), fr.at(t1, a, *uu)];
                bars.push(Bar { path, diameter: *dk, grade: gb.clone(), layer: "skin".into() });
            }
        }
    }
    if stirrup.is_some() {
        let sa = hw - cv.sides - ds / 2.0;
        let su = top_in + ds / 2.0;
        let sb = bot_in - ds / 2.0;
        for t in &st_stations {
            let c0 = fr.at(*t, -sa, su);
            let c1 = fr.at(*t, sa, su);
            let c2 = fr.at(*t, sa, sb);
            let c3 = fr.at(*t, -sa, sb);
            let path = stir::hooked(vec![c0, c1, c2, c3, c0], st_hook);
            bars.push(Bar { path, diameter: ds, grade: gs.clone(), layer: "stirrup".into() });
        }
    }
    if bars.len() > MAX_BARS {
        return Err(format!(
            "that is more than the {} bars a command makes: widen a spacing or use fewer bars",
            MAX_BARS
        ));
    }
    let _ = de::s;
    // what the check reads: the section, the rows, the skin bars, the stirrups
    let mut nb = norm::Beam { width: w, depth: h, ..Default::default() };
    if let Some(r) = &brow {
        nb.bottom = vec![r.d; r.n];
    }
    if let Some(r) = &trow {
        nb.top = vec![r.d; r.n];
    }
    if let Some((dk, _, us)) = &skin_rows {
        nb.skin = vec![*dk; 2 * us.len()];
        nb.skin_face = vec![*dk; us.len()];
    }
    if stirrup.is_some() {
        nb.stirrup = Some((ds, norm::largest_gap(&st_stations)));
    }
    nb.d = match &brow {
        Some(r) => h - cv.bottom - ds - r.d / 2.0,
        None => h - cv.bottom - ds,
    };
    let info = norm::Info { cover: Some(cv), kind: norm::Kind::Beam(nb) };
    Ok(Armed { bars, info })
}
