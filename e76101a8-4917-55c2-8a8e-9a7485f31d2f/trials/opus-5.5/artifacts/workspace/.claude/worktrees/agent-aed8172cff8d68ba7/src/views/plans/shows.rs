//! What the views show, as far as their frames go: the walls' outlines in plan with their corners
//! mitred, the solids the model builds (an outline in plan between two heights), the box round the
//! walls and floors the building elevations look at, what a plan shows (`crop` without a region and
//! a plan's viewport), a section's or an elevation's frame along its line and up, and how big the
//! 3D view's picture of the model is.

use super::super::common::*;
use super::super::model::{self as m, WallLine};
use crate::project::Project;

/// A box in plan: its south-west and north-east corners.
pub type BBox = ([f64; 2], [f64; 2]);

/// Takes a point into a box.
pub fn grow(b: &mut Option<BBox>, p: [f64; 2]) {
    match b {
        None => *b = Some((p, p)),
        Some((lo, hi)) => {
            lo[0] = lo[0].min(p[0]);
            lo[1] = lo[1].min(p[1]);
            hi[0] = hi[0].max(p[0]);
            hi[1] = hi[1].max(p[1]);
        }
    }
}

/// Takes points into a box.
pub fn grow_all(b: &mut Option<BBox>, pts: &[[f64; 2]]) {
    for p in pts {
        grow(b, *p);
    }
}

// ---------------------------------------------------------------- walls joined

#[derive(Clone)]
struct WallShape {
    id: u64,
    level: String,
    /// The location line (where its points are, where walls meet).
    loc: WallLine,
    centre: WallLine,
    thick: f64,
    /// Left and right faces from its start to its end.
    left: Vec<[f64; 2]>,
    right: Vec<[f64; 2]>,
}

/// The number of chords an arc of radius `r` turning `sweep` radians is drawn with: none further
/// than a millimetre from it.
pub fn arc_segments(r: f64, sweep: f64) -> usize {
    let r = r.abs();
    if r <= 0.5 {
        return 1;
    }
    let step = 2.0 * (1.0 - 1.0 / r).acos();
    if !(step > 0.0) {
        return 1;
    }
    let n = (sweep.abs() / step).ceil();
    if n < 1.0 {
        1
    } else if n > 100_000.0 {
        100_000
    } else {
        n as usize
    }
}

/// An arc wall's face `d` to the left of its centre line: the centre line's chords (from its
/// very start to its very end) moved out from the arc's centre.
fn arc_face(centre: &WallLine, segments: usize, d: f64) -> Vec<[f64; 2]> {
    let Some((c, r)) = centre.circle() else { return vec![centre.start, centre.end] };
    let n = segments.max(1);
    let a0 = (centre.start[1] - c[1]).atan2(centre.start[0] - c[0]);
    let sweep = centre.arc.to_radians();
    let s = if centre.arc > 0.0 { -d } else { d };
    (0..=n)
        .map(|i| {
            let p = if i == 0 {
                centre.start
            } else if i == n {
                centre.end
            } else {
                let a = a0 + sweep * i as f64 / n as f64;
                [c[0] + r * a.cos(), c[1] + r * a.sin()]
            };
            let v = m::sub(p, c);
            let l = m::norm(v);
            m::add(c, m::mul(v, (l + s) / l))
        })
        .collect()
}

fn wall_shapes(pr: &Project) -> Vec<WallShape> {
    let mut out = Vec::new();
    for (id, e) in &pr.elements {
        if cat(e) != "wall" {
            continue;
        }
        let loc = m::location_line(e);
        let centre = m::centre_line(pr, e);
        let t = m::wall_thickness(pr, e);
        let n = match centre.circle() {
            Some((_, r)) => arc_segments(r, centre.arc.to_radians()),
            None => 1,
        };
        let l = centre.offset(t / 2.0);
        let r = centre.offset(-t / 2.0);
        let (left, right) = if centre.is_arc() {
            (arc_face(&centre, n, t / 2.0), arc_face(&centre, n, -t / 2.0))
        } else {
            (vec![l.start, l.end], vec![r.start, r.end])
        };
        out.push(WallShape {
            id: *id,
            level: s_of(e, "level").unwrap_or("").to_string(),
            loc,
            centre,
            thick: t,
            left,
            right,
        });
    }
    out
}

/// A straight face's free end, square across the wall there, as the original works it out: the
/// face's other end carried the length of the wall along it.
fn capped(centre: &WallLine, other_end: [f64; 2], at_start: bool) -> [f64; 2] {
    let d = m::sub(centre.end, centre.start);
    if at_start {
        m::sub(other_end, d)
    } else {
        m::add(other_end, d)
    }
}

fn same_point(a: [f64; 2], b: [f64; 2]) -> bool {
    (a[0] - b[0]).abs() < 1e-6 && (a[1] - b[1]).abs() < 1e-6
}

/// Where the lines through a, a + da and through b, b + db cross.
fn cross_lines(a: [f64; 2], da: [f64; 2], b: [f64; 2], db: [f64; 2]) -> Option<[f64; 2]> {
    let (da, db) = (m::unit(da), m::unit(db));
    let den = m::cross(da, db);
    if den.abs() < 1e-12 {
        return None;
    }
    let t = m::cross(m::sub(b, a), db) / den;
    Some(m::add(a, m::mul(da, t)))
}

/// Mitres two straight walls meeting end to end at one point, where the mitre stays within a
/// wall's thickness of the end of each.
fn mitre(ws: &mut [WallShape], (i, at_start_i): (usize, bool), (j, at_start_j): (usize, bool)) {
    let dir = |w: &WallShape| m::unit(m::sub(w.centre.end, w.centre.start));
    let (a, b) = (&ws[i], &ws[j]);
    let da = if at_start_i { dir(a) } else { m::mul(dir(a), -1.0) };
    let db = if at_start_j { dir(b) } else { m::mul(dir(b), -1.0) };
    if m::cross(da, db).abs() < 1e-9 {
        return;
    }
    // the faces of each to the left and to the right of the way it leaves the corner
    let face = |w: &WallShape, at_start: bool, left_of_away: bool| -> ([f64; 2], [f64; 2]) {
        // leaving from its start the way runs start to end, so its own left face is left of it
        let own_left = left_of_away == at_start;
        let f = if own_left { &w.left } else { &w.right };
        (f[0], m::sub(f[f.len() - 1], f[0]))
    };
    let (al, ald) = face(a, at_start_i, true);
    let (ar, ard) = face(a, at_start_i, false);
    let (bl, bld) = face(b, at_start_j, true);
    let (br, brd) = face(b, at_start_j, false);
    let (Some(m1), Some(m2)) = (cross_lines(al, ald, br, brd), cross_lines(ar, ard, bl, bld)) else { return };
    let end_of = |w: &WallShape, at_start: bool| if at_start { w.centre.start } else { w.centre.end };
    let beyond = |w: &WallShape, at_start: bool, d: [f64; 2], p: [f64; 2]| -m::dot(m::sub(p, end_of(w, at_start)), d);
    let ok = |w: &WallShape, at_start: bool, d: [f64; 2]| {
        beyond(w, at_start, d, m1) < w.thick && beyond(w, at_start, d, m2) < w.thick
    };
    if !ok(a, at_start_i, da) || !ok(b, at_start_j, db) {
        return;
    }
    let set = |w: &mut WallShape, at_start: bool, left_of_away: bool, p: [f64; 2]| {
        let own_left = left_of_away == at_start;
        let f = if own_left { &mut w.left } else { &mut w.right };
        let k = if at_start { 0 } else { f.len() - 1 };
        f[k] = p;
    };
    set(&mut ws[i], at_start_i, true, m1);
    set(&mut ws[i], at_start_i, false, m2);
    set(&mut ws[j], at_start_j, false, m1);
    set(&mut ws[j], at_start_j, true, m2);
}

/// Each wall's outline in plan (its faces, mitred where two straight walls of a level meet end
/// to end), by id.
pub fn wall_outlines(pr: &Project) -> Vec<(u64, Vec<[f64; 2]>)> {
    let mut ws = wall_shapes(pr);
    // the ends that meet
    let mut ends: Vec<(usize, bool, [f64; 2])> = Vec::new();
    for (i, w) in ws.iter().enumerate() {
        if w.centre.is_arc() {
            continue;
        }
        ends.push((i, true, w.loc.start));
        ends.push((i, false, w.loc.end));
    }
    let mut done = vec![false; ends.len()];
    let mut joined = vec![false; ends.len()];
    let mut pairs = Vec::new();
    for k in 0..ends.len() {
        if done[k] {
            continue;
        }
        let group: Vec<usize> = (k..ends.len())
            .filter(|&q| !done[q] && same_point(ends[q].2, ends[k].2) && ws[ends[q].0].level == ws[ends[k].0].level)
            .collect();
        for &q in &group {
            done[q] = true;
        }
        if group.len() >= 2 {
            for &q in &group {
                joined[q] = true;
            }
        }
        if group.len() == 2 && ends[group[0]].0 != ends[group[1]].0 {
            pairs.push((group[0], group[1]));
        }
    }
    // a free end is cut square by its cap; a joined one keeps its face's own end until mitred
    let direct: Vec<(Vec<[f64; 2]>, Vec<[f64; 2]>)> = ws.iter().map(|w| (w.left.clone(), w.right.clone())).collect();
    for (k, (i, at_start, _)) in ends.iter().enumerate() {
        if joined[k] {
            continue;
        }
        let w = &mut ws[*i];
        let (dl, dr) = &direct[*i];
        let (idx, other) = if *at_start { (0, 1) } else { (1, 0) };
        w.left[idx] = capped(&w.centre, dl[other], *at_start);
        w.right[idx] = capped(&w.centre, dr[other], *at_start);
    }
    for (a, b) in pairs {
        let (i, si, _) = ends[a];
        let (j, sj, _) = ends[b];
        mitre(&mut ws, (i, si), (j, sj));
    }
    ws.into_iter()
        .map(|w| {
            let mut pts = w.left.clone();
            let mut back = w.right.clone();
            back.reverse();
            pts.extend(back);
            (w.id, pts)
        })
        .collect()
}

// ---------------------------------------------------------------- solids

/// What the model builds, as far as a frame goes: an outline in plan between two heights.
#[derive(Clone, Debug)]
pub struct Solid {
    pub id: u64,
    pub cat: String,
    pub pts: Vec<[f64; 2]>,
    pub z0: f64,
    pub z1: f64,
    /// Its corners in space where it is no prism (a roof: its eaves and its ridge).
    pub corners: Option<Vec<[f64; 3]>>,
}

fn type_thickness(pr: &Project, cat: &str, e: &crate::json::Value, dflt: f64) -> f64 {
    m::type_entry(pr, cat, e).and_then(|t| f_of(t, "thickness")).unwrap_or(dflt)
}

/// The largest distance from an outline's edges to a point inside it, near enough for a hipped
/// roof's ridge: half the shorter side of its box.
fn ridge_run(pts: &[[f64; 2]]) -> f64 {
    match m::bounds(pts) {
        Some((lo, hi)) => ((hi[0] - lo[0]).min(hi[1] - lo[1]) / 2.0).max(0.0),
        None => 0.0,
    }
}

/// Every solid the model builds: walls (joined), floors, ceilings, roofs, columns, footings.
pub fn solids(pr: &Project) -> Vec<Solid> {
    let mut out = Vec::new();
    for (id, pts) in wall_outlines(pr) {
        let e = pr.el(id).unwrap();
        let (z0, z1) = m::base_top(pr, e);
        out.push(Solid { id, cat: "wall".into(), pts, z0, z1, corners: None });
    }
    for (id, e) in &pr.elements {
        let c = cat(e);
        let lv = m::level_elevation(pr, e, "level").unwrap_or(0.0);
        match c {
            "floor" => {
                let Some(pts) = pts_of(e, "boundary") else { continue };
                let t = type_thickness(pr, "floor", e, 200.0);
                let top = lv + f_of(e, "offset").unwrap_or(0.0);
                let mut rise = 0.0;
                if let (Some(s), Some(a)) = (f_of(e, "slope"), pts_of(e, "arrow")) {
                    if a.len() == 2 {
                        let d = m::unit(m::sub(a[1], a[0]));
                        let far = pts.iter().map(|p| m::dot(m::sub(*p, a[0]), d)).fold(f64::MIN, f64::max);
                        let near = pts.iter().map(|p| m::dot(m::sub(*p, a[0]), d)).fold(f64::MAX, f64::min);
                        let k = s.to_radians().tan();
                        rise = (far * k).max(near * k).max(0.0);
                        let fall = (far * k).min(near * k).min(0.0);
                        out.push(Solid { id: *id, cat: c.into(), pts: pts.clone(), z0: top + fall - t, z1: top + rise, corners: None });
                        continue;
                    }
                }
                out.push(Solid { id: *id, cat: c.into(), pts, z0: top - t, z1: top + rise, corners: None });
            }
            "ceiling" => {
                let Some(pts) = pts_of(e, "boundary") else { continue };
                let t = type_thickness(pr, "ceiling", e, 20.0);
                let under = lv + f_of(e, "offset").unwrap_or(2600.0);
                out.push(Solid { id: *id, cat: c.into(), pts, z0: under, z1: under + t, corners: None });
            }
            "roof" => {
                let Some(b) = pts_of(e, "boundary") else { continue };
                let t = type_thickness(pr, "roof", e, 300.0);
                let base = lv + f_of(e, "offset").unwrap_or(0.0);
                let over = f_of(e, "overhang").unwrap_or(0.0);
                let pts = b;
                let slope = f_of(e, "slope").unwrap_or(30.0);
                let (top, corners) = if slope.abs() < 1e-9 {
                    (base + t, None)
                } else {
                    let a = slope.to_radians();
                    let eave = base + t / a.cos();
                    let top = eave + (ridge_run(&pts) - over) * a.tan();
                    let mut cs: Vec<[f64; 3]> = Vec::new();
                    // the overhang falls past the wall line to the roof's edge
                    let drop = over * a.tan();
                    for p in &pts {
                        cs.push([p[0], p[1], base - drop]);
                        cs.push([p[0], p[1], eave - drop]);
                    }
                    if let Some((lo, hi)) = m::bounds(&pts) {
                        let (w, d) = (hi[0] - lo[0], hi[1] - lo[1]);
                        if w >= d {
                            let y = (lo[1] + hi[1]) / 2.0;
                            cs.push([lo[0] + d / 2.0, y, top]);
                            cs.push([hi[0] - d / 2.0, y, top]);
                        } else {
                            let x = (lo[0] + hi[0]) / 2.0;
                            cs.push([x, lo[1] + w / 2.0, top]);
                            cs.push([x, hi[1] - w / 2.0, top]);
                        }
                    }
                    (top, Some(cs))
                };
                out.push(Solid { id: *id, cat: c.into(), pts, z0: base, z1: top, corners });
            }
            "column" | "structuralcolumn" | "structural_column" | "footing" => {
                let Some(pts) = m::outline(pr, *id) else { continue };
                let (z0, z1) = if c == "footing" {
                    let t = m::type_entry(pr, "footing", e).and_then(|t| f_of(t, "thickness")).unwrap_or(500.0);
                    let top = lv + f_of(e, "offset").unwrap_or(0.0);
                    (top - t, top)
                } else {
                    m::base_top(pr, e)
                };
                out.push(Solid { id: *id, cat: c.into(), pts, z0, z1, corners: None });
            }
            "mass" => {
                let Some(pts) = pts_of(e, "boundary") else { continue };
                let (z0, z1) = m::base_top(pr, e);
                out.push(Solid { id: *id, cat: c.into(), pts, z0, z1, corners: None });
            }
            "stair" | "ramp" => {
                if let Some(s) = stair_solid(pr, *id, e, lv) {
                    out.push(s);
                }
            }
            "railing" => {
                // along its own path (one a stair or a ramp hosts goes with it)
                let Some(pts) = pts_of(e, "path") else { continue };
                let h = type_entry_any(pr, "railing", e).and_then(|t| f_of(t, "height")).unwrap_or(1000.0);
                let z0 = lv + f_of(e, "base_offset").unwrap_or(0.0);
                out.push(Solid { id: *id, cat: c.into(), pts, z0, z1: z0 + h, corners: None });
            }
            "component" => {
                if let Some(s) = component_solid(pr, *id, e, lv) {
                    out.push(s);
                }
            }
            _ => {
                if let Some(s) = run_solid(pr, *id, e, lv) {
                    out.push(s);
                }
            }
        }
    }
    out
}

/// A type's entry in `types.<cat>` by the element's `type` GUID.
fn type_entry_any<'a>(pr: &'a Project, c: &str, e: &crate::json::Value) -> Option<&'a crate::json::Value> {
    m::type_entry(pr, c, e)
}

/// A run's (a beam's, a pipe's, a duct's…) section in its type: width across, depth deep.
fn run_type<'a>(pr: &'a Project, e: &crate::json::Value) -> Option<&'a crate::json::Value> {
    let name = lib_ref_name(pr, e, "type")?;
    pr.section("types")?.get("runs")?.get(cat(e))?.get(&name)
}

/// A run's solid: along its line, its type's width across, between the heights its justify line
/// and offsets put it at.
fn run_solid(pr: &Project, id: u64, e: &crate::json::Value, lv: f64) -> Option<Solid> {
    let (a, b) = (pt_of(e, "start")?, pt_of(e, "end")?);
    let t = run_type(pr, e)?;
    let w = f_of(t, "width").unwrap_or(0.0);
    let d = if t.get("round").and_then(|r| r.as_bool()) == Some(true) { w } else { f_of(t, "depth").unwrap_or(w) };
    let o0 = f_of(e, "offset").unwrap_or(0.0);
    let o1 = f_of(e, "end_offset").unwrap_or(o0);
    let span = |o: f64| -> (f64, f64) {
        let z = lv + o;
        match s_of(e, "justify").unwrap_or("centre") {
            "top" => (z - d, z),
            "bottom" => (z, z + d),
            _ => (z - d / 2.0, z + d / 2.0),
        }
    };
    let (s0, s1) = span(o0);
    let (t0, t1) = span(o1);
    let n = m::left_normal(a, b);
    let h = w / 2.0;
    let pts = vec![m::add(a, m::mul(n, h)), m::add(b, m::mul(n, h)), m::sub(b, m::mul(n, h)), m::sub(a, m::mul(n, h))];
    let corners = if t.get("round").and_then(|r| r.as_bool()) == Some(true) {
        // a round run's section is a circle about its axis
        let mut cs = Vec::new();
        for (p, (z0, z1)) in [(a, (s0, s1)), (b, (t0, t1))] {
            let zc = (z0 + z1) / 2.0;
            for k in 0..32 {
                let t = k as f64 / 32.0 * std::f64::consts::TAU;
                let q = m::add(p, m::mul(n, h * t.cos()));
                cs.push([q[0], q[1], zc + h * t.sin()]);
            }
        }
        Some(cs)
    } else {
        None
    };
    Some(Solid { id, cat: cat(e).to_string(), pts, z0: s0.min(t0), z1: s1.max(t1), corners })
}

/// A straight stair's or ramp's footprint: from its start along its way as long as its treads
/// (or its slope) make it, its width across.
fn stair_solid(pr: &Project, id: u64, e: &crate::json::Value, lv: f64) -> Option<Solid> {
    let start = pt_of(e, "start")?;
    let height = match m::level_elevation(pr, e, "top_level") {
        Some(t) => t + f_of(e, "top_offset").unwrap_or(0.0) - lv,
        None => f_of(e, "height").unwrap_or(3000.0),
    };
    let dir = match pt_of(e, "end") {
        Some(t) if m::dist(t, start) > 0.0 => m::unit(m::sub(t, start)),
        _ => {
            let a = f_of(e, "angle").unwrap_or(0.0).to_radians();
            [a.cos(), a.sin()]
        }
    };
    let run = if cat(e) == "ramp" {
        let slope = f_of(e, "slope").unwrap_or(8.33);
        if slope > 0.0 {
            height / (slope / 100.0)
        } else {
            0.0
        }
    } else {
        let riser = f_of(e, "riser").unwrap_or(180.0);
        let tread = f_of(e, "tread").unwrap_or(280.0);
        let risers = if riser > 0.0 { (height / riser - 1e-9).ceil().max(1.0) } else { 1.0 };
        (risers - 1.0) * tread
    };
    let w = f_of(e, "width").unwrap_or(if cat(e) == "ramp" { 1200.0 } else { 1000.0 });
    let n = [-dir[1], dir[0]];
    let end = m::add(start, m::mul(dir, run));
    let h = w / 2.0;
    let pts = vec![m::add(start, m::mul(n, h)), m::add(end, m::mul(n, h)), m::sub(end, m::mul(n, h)), m::sub(start, m::mul(n, h))];
    // solid from the floor up to its treads, which rise from its foot to its head
    let mut corners = Vec::new();
    for (k, p) in pts.iter().enumerate() {
        let top = if k == 1 || k == 2 { lv + height } else { lv };
        corners.push([p[0], p[1], lv]);
        corners.push([p[0], p[1], top]);
    }
    Some(Solid { id, cat: cat(e).to_string(), pts, z0: lv, z1: lv + height, corners: Some(corners) })
}

/// A family parameter's value for a component: its own, its type's, else the family's.
pub fn family_param(pr: &Project, e: &crate::json::Value, name: &str) -> Option<f64> {
    if let Some(v) = e.get("params").and_then(|p| f_of(p, name)) {
        return Some(v);
    }
    let fam = lib_ref_name(pr, e, "family")?;
    let f = pr.section("families")?.get(&fam)?;
    if let Some(t) = lib_ref_name(pr, e, "type") {
        // the library names a family's type "Family: Type"
        let t = t.strip_prefix(&format!("{}: ", fam)).map(|x| x.to_string()).unwrap_or(t);
        if let Some(v) = f.get("types").and_then(|ts| ts.get(&t)).and_then(|t| f_of(t, name)) {
            return Some(v);
        }
    }
    f.get("parameters")?
        .as_arr()?
        .iter()
        .find(|p| s_of(p, "name") == Some(name))
        .and_then(|p| f_of(p, "value"))
}

/// A component's footprint: its family's width by its depth about its point, turned with it.
fn component_solid(pr: &Project, id: u64, e: &crate::json::Value, lv: f64) -> Option<Solid> {
    let at = pt_of(e, "at")?;
    let w = family_param(pr, e, "Width").or_else(|| family_param(pr, e, "Length")).or_else(|| family_param(pr, e, "Diameter"))?;
    let d = family_param(pr, e, "Depth").or_else(|| family_param(pr, e, "Width").filter(|_| family_param(pr, e, "Length").is_some())).unwrap_or(w);
    let h = family_param(pr, e, "Height").unwrap_or(0.0);
    let a = f_of(e, "angle").unwrap_or(0.0).to_radians();
    let (ca, sa) = (a.cos(), a.sin());
    let pts = [[-w / 2.0, -d / 2.0], [w / 2.0, -d / 2.0], [w / 2.0, d / 2.0], [-w / 2.0, d / 2.0]]
        .iter()
        .map(|p| [at[0] + p[0] * ca - p[1] * sa, at[1] + p[0] * sa + p[1] * ca])
        .collect();
    let z0 = lv + f_of(e, "offset").unwrap_or(0.0);
    Some(Solid { id, cat: "component".into(), pts, z0, z1: z0 + h, corners: None })
}

/// The categories a view's graphics hide.
fn hidden_categories(pr: &Project, view: u64) -> Vec<String> {
    let mut out = Vec::new();
    let Some(e) = pr.el(view) else { return out };
    if let Some(g) = e.get("graphics").and_then(|g| g.get("categories")).and_then(|c| c.as_obj()) {
        for (k, v) in g.iter() {
            if v.get("hidden").and_then(|h| h.as_bool()) == Some(true) {
                out.push(k.clone());
            }
        }
    }
    out
}

fn shown(hidden: &[String], cat: &str) -> bool {
    let c = match cat {
        "structuralcolumn" => "structural_column",
        x => x,
    };
    !hidden.iter().any(|h| h == c || h == cat)
}

// ---------------------------------------------------------------- the box the elevations look at

/// The box round the walls and floors in plan, which the building elevations stand round.
pub fn walls_and_floors_box(pr: &Project) -> Option<BBox> {
    let mut b = None;
    for (_, pts) in wall_outlines(pr) {
        grow_all(&mut b, &pts);
    }
    for e in pr.elements.values() {
        if cat(e) == "floor" {
            if let Some(pts) = pts_of(e, "boundary") {
                grow_all(&mut b, &pts);
            }
        }
    }
    b
}

/// The box round everything the model builds, in plan.
pub fn model_box(pr: &Project) -> Option<BBox> {
    let mut b = None;
    for s in solids(pr) {
        grow_all(&mut b, &s.pts);
    }
    b
}

/// The box the levels' rectangles take a metre past: what the model builds, and its grids.
pub fn levels_model_box(pr: &Project, all: &[Solid]) -> Option<BBox> {
    let mut b = None;
    for x in all {
        grow_all(&mut b, &x.pts);
    }
    for e in pr.elements.values() {
        if cat(e) == "grid" {
            for k in ["start", "end"] {
                if let Some(p) = pt_of(e, k) {
                    grow(&mut b, p);
                }
            }
        }
    }
    b
}

/// A level's rectangle in plan: its own extent, else the model's a metre past it (a 20 m square
/// round the origin when there is no model).
pub fn level_rect(_pr: &Project, level: &crate::json::Value, model: Option<BBox>) -> BBox {
    if let Some(a) = level.get("extent").and_then(|x| x.as_arr()) {
        if a.len() == 2 {
            if let (Some(p), Some(q)) = (crate::commands::params::point_of(&a[0]), crate::commands::params::point_of(&a[1])) {
                return (p, q);
            }
        }
    }
    match model {
        Some((lo, hi)) => ([lo[0] - 1000.0, lo[1] - 1000.0], [hi[0] + 1000.0, hi[1] + 1000.0]),
        None => ([-10000.0, -10000.0], [10000.0, 10000.0]),
    }
}

// ---------------------------------------------------------------- sections and elevations

/// A section's or an elevation's line: start, unit direction along it, length, and the way it
/// looks (left of the line).
pub fn view_line(e: &crate::json::Value) -> ([f64; 2], [f64; 2], f64, [f64; 2]) {
    let s = pt_of(e, "start").unwrap_or([0.0, 0.0]);
    let t = pt_of(e, "end").unwrap_or([0.0, 0.0]);
    let len = m::dist(s, t);
    let v = m::sub(t, s);
    let inv = 1.0 / len;
    let d = if len > 0.0 { [v[0] * inv, v[1] * inv] } else { [0.0, 0.0] };
    (s, d, len, [-d[1], d[0]])
}

/// The heights a section frames before its margins: its levels and what the model builds.
fn heights(pr: &Project, sol: &[Solid]) -> Option<(f64, f64)> {
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    for id in crate::model::levels(pr) {
        let z = crate::model::elev(pr, id);
        lo = lo.min(z);
        hi = hi.max(z);
    }
    for s in sol {
        lo = lo.min(s.z0);
        hi = hi.max(s.z1);
    }
    if lo.is_finite() {
        Some((lo, hi))
    } else {
        None
    }
}

/// A section's or an elevation's frame: along its line from its start (`u`) and up (`v`), the
/// model (and its levels where it sees them) and the line itself, 600 mm over and under; a
/// cropped one its line and its crop, 600 mm over and under.
pub fn section_frame(pr: &Project, id: u64) -> (f64, f64, f64, f64) {
    frame_of(pr, id, true)
}

/// A section's or an elevation's frame as it would be uncropped.
pub fn section_frame_uncropped(pr: &Project, id: u64) -> (f64, f64, f64, f64) {
    frame_of(pr, id, false)
}

fn frame_of(pr: &Project, id: u64, cropped: bool) -> (f64, f64, f64, f64) {
    let e = pr.el(id).unwrap();
    let (s, d, len, look) = view_line(e);
    if let Some(c) = e.get("crop").and_then(|c| c.as_arr()).filter(|_| cropped) {
        if c.len() == 2 {
            let b = c[0].as_f64().unwrap_or(0.0);
            let t = c[1].as_f64().unwrap_or(0.0);
            return (0.0, len, b - 600.0, t + 600.0);
        }
    }
    let hidden = hidden_categories(pr, id);
    let all = solids(pr);
    let sol: Vec<Solid> = all.iter().filter(|x| shown(&hidden, &x.cat)).cloned().collect();
    let mut u0 = 0.0f64;
    let mut u1 = len;
    for x in &sol {
        for p in &x.pts {
            let u = m::dot(m::sub(*p, s), d);
            u0 = u0.min(u);
            u1 = u1.max(u);
        }
    }
    let depth = f_of(e, "depth");
    let mb = levels_model_box(pr, &all);
    if shown(&hidden, "level") {
        for lid in crate::model::levels(pr) {
            let le = pr.el(lid).unwrap();
            let (lo, hi) = level_rect(pr, le, mb);
            let corners = [lo, [hi[0], lo[1]], hi, [lo[0], hi[1]]];
            let ss: Vec<f64> = corners.iter().map(|p| m::dot(m::sub(*p, s), look)).collect();
            let smax = ss.iter().cloned().fold(f64::MIN, f64::max);
            let smin = ss.iter().cloned().fold(f64::MAX, f64::min);
            let seen = smax >= -1.0 && depth.map_or(true, |dp| smin <= dp);
            if !seen {
                continue;
            }
            for p in corners {
                let u = m::dot(m::sub(p, s), d);
                u0 = u0.min(u);
                u1 = u1.max(u);
            }
        }
    }
    let (z0, z1) = heights(pr, &sol).unwrap_or((0.0, 0.0));
    (u0, u1, z0 - 600.0, z1 + 600.0)
}

// ---------------------------------------------------------------- plans

/// The view range of a plan (its own, or its parent's for a dependent one): cut, bottom, depth.
fn view_range(pr: &Project, view: u64) -> (f64, f64, f64, Option<f64>) {
    let mut e = pr.el(view);
    if let Some(x) = e {
        if let Some(p) = ref_id(pr, x, "parent") {
            e = pr.el(p);
        }
    }
    let vr = e.and_then(|x| x.get("view_range"));
    let g = |k: &str, d: f64| vr.and_then(|v| f_of(v, k)).unwrap_or(d);
    (g("cut", 1200.0), g("bottom", 0.0), g("depth", 0.0), vr.and_then(|v| f_of(v, "top")))
}

/// The GUIDs annotation is in when it is drawn in this plan: the plan's own (and a dependent's
/// parent's), and the level's own plan where annotation names no view.
fn plan_annotation_views(pr: &Project, view: u64) -> Vec<String> {
    let mut out = vec![guid(pr, view)];
    if let Some(e) = pr.el(view) {
        if let Some(p) = s_of(e, "parent") {
            out.push(p.to_string());
        }
    }
    out
}

/// Whether an element of annotation is drawn in a plan.
pub fn annotation_in_plan(pr: &Project, view: u64, e: &crate::json::Value) -> bool {
    let views = plan_annotation_views(pr, view);
    if let Some(v) = s_of(e, "view") {
        return views.iter().any(|g| g == v);
    }
    // no view: a dimension on its level's own plan, a tag on its host's
    let Some(level) = plan_level(pr, view) else { return false };
    if cat_of(pr, view) != "level" {
        // a plan view shows its own annotation, and a dependent its parent's
        let lg = guid(pr, level);
        let parent_is_level = pr.el(view).and_then(|x| s_of(x, "parent")) == Some(lg.as_str());
        if !parent_is_level {
            return false;
        }
    }
    let lg = guid(pr, level);
    match cat(e) {
        "dimension" => s_of(e, "level") == Some(lg.as_str()),
        "tag" => host_level(pr, e).as_deref() == Some(lg.as_str()),
        _ => false,
    }
}

/// The level GUID a tag's host stands on (a door's or window's through its wall).
pub fn host_level(pr: &Project, e: &crate::json::Value) -> Option<String> {
    let h = ref_id(pr, e, "host")?;
    let he = pr.el(h)?;
    if let Some(l) = s_of(he, "level") {
        return Some(l.to_string());
    }
    let w = ref_id(pr, he, "host")?;
    s_of(pr.el(w)?, "level").map(|s| s.to_string())
}

/// The point in plan an element names, which a tag is offset from: a door's or a window's place
/// in its wall, a room's point, an element's `at`, a line's middle.
pub fn host_point(pr: &Project, id: u64) -> Option<[f64; 2]> {
    let e = pr.el(id)?;
    match cat(e) {
        "door" | "window" => {
            let w = ref_id(pr, e, "host")?;
            let we = pr.el(w)?;
            let l = m::location_line(we);
            let off = f_of(e, "offset").unwrap_or(0.0);
            if l.is_arc() {
                let (c, r) = l.circle()?;
                let a0 = (l.start[1] - c[1]).atan2(l.start[0] - c[0]);
                let a = a0 + off / r * l.arc.signum();
                return Some([c[0] + r * a.cos(), c[1] + r * a.sin()]);
            }
            let d = m::unit(m::sub(l.end, l.start));
            Some(m::add(l.start, m::mul(d, off)))
        }
        "room" => pt_of(e, "point"),
        _ => {
            if let Some(p) = pt_of(e, "at") {
                return Some(p);
            }
            if let (Some(a), Some(b)) = (pt_of(e, "start"), pt_of(e, "end")) {
                return Some(m::mid(a, b));
            }
            pts_of(e, "boundary").and_then(|b| m::bounds(&b)).map(|(lo, hi)| m::mid(lo, hi))
        }
    }
}

/// The points a piece of annotation stands at in its view.
fn annotation_points(pr: &Project, e: &crate::json::Value) -> Vec<[f64; 2]> {
    let mut out = Vec::new();
    match cat(e) {
        "tag" => {
            if let Some(h) = ref_id(pr, e, "host") {
                if let Some(p) = host_point(pr, h) {
                    let o = pt_of(e, "offset").unwrap_or([0.0, 0.0]);
                    out.push([p[0] + o[0], p[1] + o[1]]);
                }
            }
        }
        "text" | "spot" | "detailgroup" => {
            if let Some(p) = pt_of(e, "at") {
                out.push(p);
            }
            if let Some(p) = pt_of(e, "leader") {
                out.push(p);
            }
        }
        "dimension" => {
            if let Some(p) = pt_of(e, "at") {
                out.push(p);
            }
        }
        "line" => {
            for k in ["start", "end", "through", "centre"] {
                if let Some(p) = pt_of(e, k) {
                    out.push(p);
                }
            }
            for k in ["points", "control", "fit"] {
                if let Some(ps) = pts_of(e, k) {
                    out.extend(ps);
                }
            }
        }
        "region" => {
            if let Some(a) = e.get("sketch").and_then(|s| s.as_arr()) {
                for l in a {
                    for k in ["start", "end"] {
                        if let Some(p) = pt_of(l, k) {
                            out.push(p);
                        }
                    }
                }
            }
        }
        "repeatingdetail" => {
            for k in ["start", "end"] {
                if let Some(p) = pt_of(e, k) {
                    out.push(p);
                }
            }
        }
        _ => {}
    }
    out
}

/// What a plan shows, in plan: the model it cuts or sees, roofs over it, the sections', the
/// elevations' and the grids' lines, and its annotation. None where it shows nothing.
pub fn plan_shows(pr: &Project, view: u64) -> Option<BBox> {
    let level = plan_level(pr, view)?;
    let z = crate::model::elev(pr, level);
    let (cut, bottom, depth, top) = view_range(pr, view);
    let low = z + bottom.min(depth).min(bottom);
    let cut_at = z + cut;
    // what is overhead is seen up to the top of the range: the level above unless it says
    let high = match top {
        Some(t) => z + t,
        None => crate::model::level_above(pr, level).map_or(f64::INFINITY, |l| crate::model::elev(pr, l)),
    };
    let hidden = hidden_categories(pr, view);
    let level_guid = guid(pr, level);
    let mut b = None;
    for s in solids(pr) {
        if !shown(&hidden, &s.cat) {
            continue;
        }
        let on_level = pr.el(s.id).and_then(|e| s_of(e, "level")) == Some(level_guid.as_str());
        let show = match s.cat.as_str() {
            "roof" => s.z1 > low && s.z0 <= high,
            "floor" => s.z1 >= low && s.z1 <= cut_at.max(low) || (s.z0 < cut_at && s.z1 > cut_at),
            "stair" | "ramp" | "railing" => s.z0 <= cut_at && s.z1 >= low,
            "wall" | "column" | "structuralcolumn" | "structural_column" => s.z0 < cut_at && s.z1 > low,
            _ => on_level || (s.z0 < cut_at && s.z1 > low),
        };
        if show {
            grow_all(&mut b, &s.pts);
        }
    }
    for e in pr.elements.values() {
        match cat(e) {
            "section" | "elevation" => {
                if !shown(&hidden, cat(e)) {
                    continue;
                }
                for k in ["start", "end"] {
                    if let Some(p) = pt_of(e, k) {
                        grow(&mut b, p);
                    }
                }
            }
            "shaft" => {
                if !shown(&hidden, "shaft") {
                    continue;
                }
                let (z0, z1) = m::base_top(pr, e);
                if z0 < cut_at && z1 > low {
                    if let Some(bd) = pts_of(e, "boundary") {
                        grow_all(&mut b, &bd);
                    }
                }
            }
            "room" | "roomseparator" => {
                if !shown(&hidden, cat(e)) || s_of(e, "level") != Some(level_guid.as_str()) {
                    continue;
                }
                if cat(e) == "roomseparator" {
                    for k in ["start", "end"] {
                        if let Some(p) = pt_of(e, k) {
                            grow(&mut b, p);
                        }
                    }
                } else if let Some(p) = pt_of(e, "point") {
                    // a room's label stands at its point
                    grow(&mut b, p);
                }
            }
            "grid" => {
                if !shown(&hidden, "grid") {
                    continue;
                }
                for k in ["start", "end"] {
                    if let Some(p) = pt_of(e, k) {
                        grow(&mut b, p);
                    }
                }
            }
            "text" | "spot" | "dimension" | "line" | "region" | "detailgroup" | "repeatingdetail" | "tag" => {
                if annotation_in_plan(pr, view, e) {
                    grow_all(&mut b, &annotation_points(pr, e));
                }
            }
            _ => {}
        }
    }
    b
}

/// A plan's crop (its own; a dependent's own too), if it has one.
pub fn plan_crop(e: &crate::json::Value) -> Option<BBox> {
    let a = e.get("crop")?.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    let p = pt_of_v(&a[0])?;
    let q = pt_of_v(&a[1])?;
    Some((p, q))
}

fn pt_of_v(v: &crate::json::Value) -> Option<[f64; 2]> {
    let a = v.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

// ---------------------------------------------------------------- the 3D view

/// How wide and tall (model mm) the 3D view's parallel picture of the model is, seen from
/// `azimuth` degrees round from east and `elevation` degrees up. None for an empty model.
pub fn view3d_extent(pr: &Project, view: Option<u64>, azimuth: f64, elevation: f64) -> Option<(f64, f64)> {
    let hidden = view.map(|v| hidden_categories(pr, v)).unwrap_or_default();
    let (a, e) = (azimuth.to_radians(), elevation.to_radians());
    let r = [-a.sin(), a.cos(), 0.0];
    let u = [-e.sin() * a.cos(), -e.sin() * a.sin(), e.cos()];
    let mut xs = (f64::INFINITY, f64::NEG_INFINITY);
    let mut ys = (f64::INFINITY, f64::NEG_INFINITY);
    let mut any = false;
    for s in solids(pr) {
        if !shown(&hidden, &s.cat) {
            continue;
        }
        let corners: Vec<[f64; 3]> = match &s.corners {
            Some(c) => c.clone(),
            None => s.pts.iter().flat_map(|p| [[p[0], p[1], s.z0], [p[0], p[1], s.z1]]).collect(),
        };
        for p in corners {
            let x = p[0] * r[0] + p[1] * r[1];
            let y = p[0] * u[0] + p[1] * u[1] + p[2] * u[2];
            xs = (xs.0.min(x), xs.1.max(x));
            ys = (ys.0.min(y), ys.1.max(y));
            any = true;
        }
    }
    if !any {
        return None;
    }
    Some((xs.1 - xs.0, ys.1 - ys.0))
}
