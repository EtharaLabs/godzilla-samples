//! Roofs: flat, sloping all round over a footprint with gable ends, with courtyards and
//! openings, or one profile swept across; walls cut to a roof over them, attached to it.

use super::import::Ctx;
use super::import_build::{num_name, r2, r3};
use super::import_geom::{self as geom, Solid, V2, V3};
use super::import_slabs::{canonical, pts_value, top};
use super::import_types;
use super::import_walls::face_normal;
use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// What this module keeps for later passes.
#[derive(Default)]
pub struct State {
    /// The roofs that came in: entity → (element id, guid), and their bodies.
    pub roofs: Vec<(u64, u64, String)>,
    pub bodies: BTreeMap<u64, Vec<Solid>>,
}

/// The solids of a roof: its own body, else the bodies of the slabs it aggregates.
fn roof_solids(ctx: &Ctx, id: u64) -> Vec<Solid> {
    let own = geom::body(&ctx.m, id);
    if !own.is_empty() {
        return own;
    }
    let mut out = Vec::new();
    if let Some(ch) = ctx.m.children.get(&id) {
        for c in ch {
            out.extend(geom::body(&ctx.m, *c));
        }
    }
    out
}

pub fn roofs(ctx: &mut Ctx) -> Result<(), String> {
    let mut ids: Vec<u64> = ctx.m.of("IFCROOF").to_vec();
    // roof slabs on their own
    for c in ["IFCSLAB", "IFCSLABSTANDARDCASE", "IFCSLABELEMENTEDCASE"] {
        for id in ctx.m.of(c).to_vec() {
            let e = ctx.m.get(id).unwrap();
            let roofslab = e.p(8).enm() == Some("ROOF");
            let parent_roof = ctx.m.parent.get(&id).map(|p| ctx.m.class(*p) == "IFCROOF").unwrap_or(false);
            if roofslab && !parent_roof {
                ids.push(id);
            }
        }
    }
    ids.sort();
    for id in ids {
        roof(ctx, id)?;
    }
    Ok(())
}

/// A face's plane: its unit normal and n·p.
fn plane(pts: &[V3]) -> (V3, f64) {
    let n = face_normal(pts);
    let mut c = [0.0; 3];
    for p in pts {
        c = geom::add(c, *p);
    }
    let c = geom::mul(c, 1.0 / pts.len() as f64);
    (n, geom::dot(n, c))
}

/// Whether a face looking down is parallel to one looking up (within a few degrees).
fn parallel(up: V3, down: V3) -> bool {
    let d = [up[0] + down[0], up[1] + down[1], up[2] + down[2]];
    (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt() < 0.05
}

/// A slope's thickness: from its plane square down to the lowest corner of the face looking
/// down most nearly parallel to it (if one is).
fn slope_thickness(up: &(V3, f64), downs: &[(Vec<V3>, (V3, f64))]) -> Option<f64> {
    let (n, d) = up;
    let mut best: Option<(f64, &Vec<V3>)> = None;
    for (pts, (m, _)) in downs {
        if !parallel(*n, *m) {
            continue;
        }
        let e = ((n[0] + m[0]).powi(2) + (n[1] + m[1]).powi(2) + (n[2] + m[2]).powi(2)).sqrt();
        if best.map(|b| e < b.0).unwrap_or(true) {
            best = Some((e, pts));
        }
    }
    let (_, pts) = best?;
    let mut low: Option<V3> = None;
    for p in pts {
        if low.map(|l| p[2] < l[2]).unwrap_or(true) {
            low = Some(*p);
        }
    }
    let p = low?;
    Some(d - geom::dot(*n, p))
}

/// The roof's thickness: the first slope's with an underside parallel to it.
fn thickness_of(sloped: &[&(Vec<V3>, (V3, f64))], downs: &[(Vec<V3>, (V3, f64))]) -> Option<f64> {
    sloped.iter().find_map(|u| slope_thickness(&u.1, downs))
}

/// The slope of a plane in degrees.
fn slope_of(n: V3) -> f64 {
    let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
    (h / n[2].abs()).atan().to_degrees()
}

/// The vertical extent of the roof at its points: the most, over the points of its top, of
/// the highest top and the lowest underside at that point in plan.
fn vertical_extent(solids: &[Solid]) -> f64 {
    extent_at(solids, true)
}

/// The vertical extent at the top's highest points, down to the corners of the underside under
/// them.
fn corner_extent(solids: &[Solid]) -> f64 {
    extent_at(solids, false)
}

fn extent_at(solids: &[Solid], under: bool) -> f64 {
    let mut tops: BTreeMap<(i64, i64), f64> = BTreeMap::new();
    let mut bottoms: BTreeMap<(i64, i64), f64> = BTreeMap::new();
    for s in solids {
        for f in &s.faces {
            if f.outer.len() < 3 {
                continue;
            }
            let n = face_normal(&f.outer);
            for p in f.outer.iter().chain(f.holes.iter().flatten()) {
                let k = ((p[0] * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64);
                if n[2] > 1e-6 {
                    let e = tops.entry(k).or_insert(f64::NEG_INFINITY);
                    *e = e.max(p[2]);
                } else if n[2] < -1e-6 {
                    let e = bottoms.entry(k).or_insert(f64::INFINITY);
                    *e = e.min(p[2]);
                }
            }
        }
    }
    // a point of the top with no corner under it: the underside under it
    let mut downs: Vec<(Vec<V3>, (V3, f64))> = Vec::new();
    for s in solids {
        for f in &s.faces {
            if f.outer.len() >= 3 {
                let pl = plane(&f.outer);
                if pl.0[2] < -1e-6 {
                    downs.push((f.outer.clone(), pl));
                }
            }
        }
    }
    let mut best = 0.0f64;
    let zmax = tops.values().cloned().fold(f64::NEG_INFINITY, f64::max);
    for (k, t) in &tops {
        if !under && *t < zmax - 1e-6 {
            continue;
        }
        let b = bottoms.get(k).copied().or_else(|| if under { under_z(&downs, [k.0 as f64 / 1000.0, k.1 as f64 / 1000.0]) } else { None });
        if let Some(b) = b {
            best = best.max(t - b);
        }
    }
    best
}

/// Whether a face looking up is level enough to be a flat roof's (a fall of 2% at most).
fn is_level(n: V3) -> bool {
    let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
    h / n[2].abs() <= 0.02 + 1e-9
}

fn roof(ctx: &mut Ctx, id: u64) -> Result<(), String> {
    let solids = roof_solids(ctx, id);
    let t = match top(&solids) {
        Some(t) => t,
        None => {
            ctx.skip(id, "it has no body BIMCraft can read");
            return Ok(());
        }
    };
    let level = ctx.level_of(id, t.z_bottom);
    let lev = ctx.levels[level].elevation;
    // the faces that look up, and the slopes they have
    let mut ups: Vec<(Vec<V3>, (V3, f64))> = Vec::new();
    let mut downs: Vec<(Vec<V3>, (V3, f64))> = Vec::new();
    for s in &solids {
        for f in &s.faces {
            if f.outer.len() < 3 {
                continue;
            }
            let pl = plane(&f.outer);
            if pl.0[2] > 1e-6 {
                ups.push((f.outer.clone(), pl));
            } else if pl.0[2] < -1e-6 {
                downs.push((f.outer.clone(), pl));
            }
        }
    }
    let vext = vertical_extent(&solids);
    let name = import_types::file_type_name(ctx, id);
    let outer = canonical(&t.outer, false);
    // the lowest point of a loop of the top's outline
    let top_z = |l: &Vec<V2>| -> f64 {
        let mut z = f64::INFINITY;
        for p in l {
            let k = ((p[0] * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64);
            for v in &t.verts {
                if ((v[0] * 1000.0).round() as i64, (v[1] * 1000.0).round() as i64) == k {
                    z = z.min(v[2]);
                }
            }
        }
        z
    };
    let holes: Vec<Vec<V2>> = t.holes.iter().map(|h| canonical(h, true)).collect();
    let all_flat = ups.iter().all(|u| u.1 .0[2] > 1.0 - 1e-9);
    let sloped: Vec<&(Vec<V3>, (V3, f64))> = ups.iter().filter(|u| u.1 .0[2] <= 1.0 - 1e-9).collect();
    let slopes: Vec<f64> = sloped.iter().map(|u| slope_of(u.1 .0)).collect();
    let equal = !slopes.is_empty() && slopes.iter().all(|s| (s - slopes[0]).abs() < 1e-3);
    let ring = |l: &Vec<V2>| -> Vec<(V2, V2)> { (0..l.len()).map(|i| (l[i], l[(i + 1) % l.len()])).collect() };
    // each slope's underside: the sloped face looking down that falls the same way and is the
    // nearest to parallel to it; one that isn't parallel makes the roof as uneven as a shaped one
    let underside_off = |up: V3| -> Option<bool> {
        let mut best: Option<f64> = None;
        for d in &downs {
            let n = d.1 .0;
            if n[2] <= -1.0 + 1e-9 || n[0] * up[0] + n[1] * up[1] >= 0.0 {
                continue;
            }
            let e = ((up[0] + n[0]).powi(2) + (up[1] + n[1]).powi(2) + (up[2] + n[2]).powi(2)).sqrt();
            if best.map(|b| e < b).unwrap_or(true) {
                best = Some(e);
            }
        }
        best.map(|b| b >= 0.05)
    };
    // one slope all round: each sloped face in the plane that rises from an eave of the outline
    // (or of a courtyard), from the top's height there
    let mut eaves: Vec<(V2, V2, f64)> = Vec::new();
    for r in std::iter::once(&outer).chain(holes.iter()) {
        for e in ring(r) {
            if is_eave(&ups, e) {
                let h = top_z(&vec![e.0, e.1]);
                if h.is_finite() {
                    eaves.push((e.0, e.1, h));
                }
            }
        }
    }
    let would_hip = equal
        && !is_level(sloped[0].1 .0)
        && ring(&outer).iter().any(|e| is_eave(&ups, *e))
        && sloped.iter().all(|u| on_eave_plane(u, &eaves));
    let uneven = would_hip && sloped.iter().any(|u| underside_off(u.1 .0) == Some(true));
    let hip = would_hip && !uneven;
    if !all_flat && !hip {
        // a flat roof shaped to falls (as thick all over), or one too uneven to be flat
        let uniform = uniform_thickness(&ups, &downs);
        let level_all = ups.iter().all(|u| is_level(u.1 .0));
        // its top falls from its outline to drains inside it: shaped however thick
        let zmin = t.verts.iter().map(|v| v[2]).fold(f64::INFINITY, f64::min);
        let on_ring = |v: &V3| std::iter::once(&outer).chain(holes.iter()).any(|r| (0..r.len()).any(|i| seg_has(r[i], r[(i + 1) % r.len()], [v[0], v[1]])));
        let drains = t.verts.iter().any(|v| (v[2] - zmin).abs() < 1e-6 && !on_ring(v));
        let shaped = uniform.is_some() || drains || uneven;
        if shaped {
            return shaped_roof(ctx, id, &t, &downs, &outer, &holes, level, &name, solids);
        }
        if level_all {
            let thickness = r2(vext);
            let tname = name.clone().unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
            let tname = roof_type(ctx, id, &tname, thickness)?;
            let mut m = head(ctx, id, &tname, level);
            m.insert("boundary", pts_value(&outer));
            m.insert("slope", Value::f(0.0));
            m.insert("overhang", Value::f(0.0));
            m.insert("offset", Value::f(r3(t.z_bottom - lev)));
            if !holes.is_empty() {
                m.insert("openings", Value::Arr(holes.iter().map(|h| pts_value(h)).collect()));
            }
            add_roof(ctx, id, m, solids);
            return Ok(());
        }
    }
    if all_flat {
        let thickness = r2(t.z_top - t.z_bottom);
        let tname = name.clone().unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
        let tname = roof_type(ctx, id, &tname, thickness)?;
        let mut m = head(ctx, id, &tname, level);
        m.insert("boundary", pts_value(&outer));
        m.insert("slope", Value::f(0.0));
        m.insert("overhang", Value::f(0.0));
        m.insert("offset", Value::f(r3(t.z_bottom - lev)));
        if !holes.is_empty() {
            m.insert("openings", Value::Arr(holes.iter().map(|h| pts_value(h)).collect()));
        }
        add_roof(ctx, id, m, solids);
        return Ok(());
    }
    let one_slope = hip;
    if one_slope {
        // the sloped faces: each with an underside parallel to it
        for (_, (n, _)) in &sloped {
            let par = downs.iter().any(|(_, (n2, _))| parallel(*n, *n2));
            if !par {
                ctx.skip(id, "its underside isn't parallel to its top");
                return Ok(());
            }
        }
        let s = slopes[0];
        // its thickness square to the slope, down to its underside's lowest corner
        let thickness = r2(thickness_of(&sloped, &downs).unwrap_or_else(|| perpendicular(&sloped[0].1, &downs)));
        let vertical = thickness / s.to_radians().cos();
        let tname = name.clone().unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
        let cext = corner_extent(&solids);
        if cext > 2.0 * vertical {
            // the file's roof meets itself where a gable stands on another slope
            import_types::register(ctx, "roof", &tname, crate::jobj! {"thickness" => r2(cext)});
        }
        let tname = roof_type(ctx, id, &tname, thickness)?;
        // which of the outline's edges are eaves: the roof rises from them
        let ring_edges = |l: &Vec<V2>| -> Vec<(V2, V2)> { (0..l.len()).map(|i| (l[i], l[(i + 1) % l.len()])).collect() };
        let mut edges: Vec<(V2, V2)> = ring_edges(&outer);
        let mut courts: Vec<Vec<V2>> = Vec::new();
        let mut openings: Vec<Vec<V2>> = Vec::new();
        let eave_top = top_z(&outer);
        for h in &holes {
            // a courtyard: the roof falls to it, to eaves as low as the outline's; an opening
            // is cut through the slopes
            let es = ring_edges(h);
            if es.iter().any(|e| is_eave(&ups, *e)) && (top_z(h) - eave_top).abs() < 1.0 {
                courts.push(h.clone());
            } else {
                openings.push(h.clone());
            }
        }
        for c in &courts {
            edges.extend(ring_edges(c));
        }
        let mut gables = Vec::new();
        for (i, e) in edges.iter().enumerate() {
            if !is_eave(&ups, *e) {
                gables.push(Value::u(i as u64));
            }
        }
        // the eaves' underside (their top less the roof's depth): at the level and offset, or
        // under it by the overhang
        let eave = top_z(&outer) - vertical - lev;
        let (offset, overhang) = if eave >= -1e-6 { (r2(eave), 0.0) } else { (0.0, r3(-eave / r2(s).to_radians().tan())) };
        let mut m = head(ctx, id, &tname, level);
        m.insert("boundary", pts_value(&outer));
        if !courts.is_empty() {
            m.insert("courtyards", Value::Arr(courts.iter().map(|h| pts_value(h)).collect()));
        }
        m.insert("slope", Value::f(r2(s)));
        m.insert("overhang", Value::f(overhang));
        if !gables.is_empty() {
            m.insert("gables", Value::Arr(gables));
        }
        m.insert("offset", Value::f(offset));
        if !openings.is_empty() {
            m.insert("openings", Value::Arr(openings.iter().map(|h| pts_value(h)).collect()));
        }
        add_roof(ctx, id, m, solids);
        return Ok(());
    }
    // slopes of more than one pitch: one profile swept across, or nothing BIMCraft draws
    let tname = name.clone().unwrap_or_else(|| format!("Imported - {}mm", num_name(r2(vext))));
    // its thickness: the least of the slopes' square to the underside parallel under them
    let least = sloped.iter().map(|u| perpendicular(&u.1, &downs)).filter(|t| *t > 0.0).fold(f64::INFINITY, f64::min);
    let thickness = r2(if least.is_finite() { least } else { thickness_of(&sloped, &downs).unwrap_or(0.0) });
    match extrusion(&t, &ups, &downs, thickness) {
        Some(Ok(x)) => {
            let tname = name.clone().unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
            let tname = roof_type(ctx, id, &tname, thickness)?;
            let mut m = head(ctx, id, &tname, level);
            m.insert("slope", Value::f(0.0));
            m.insert("overhang", Value::f(0.0));
            m.insert("offset", Value::f(r2(x.z0 - lev)));
            m.insert(
                "extrusion",
                crate::jobj! {
                    "line" => pts_value(&[x.a, x.b]),
                    "profile" => Value::Arr(x.profile.iter().map(|p| Value::Arr(vec![Value::f(r2(p[0])), Value::f(r2(p[1]))])).collect()),
                    "from" => 0.0,
                    "to" => r2(x.width),
                },
            );
            add_roof(ctx, id, m, solids);
        }
        Some(Err(STEPS)) => {
            // a top that steps over its underside: shaped, where the roof is nowhere thinner
            // than under its highest point
            if thinnest_at_top(&t, &downs) {
                return shaped_roof(ctx, id, &t, &downs, &outer, &holes, level, &name, solids);
            }
            ctx.skip(id, STEPS);
        }
        Some(Err(why)) => {
            import_types::register(ctx, "roof", &tname, crate::jobj! {"thickness" => r2(vext)});
            ctx.skip(id, why);
        }
        None => {
            import_types::register(ctx, "roof", &tname, crate::jobj! {"thickness" => r2(vext)});
            ctx.skip(id, "its slopes don't make a roof BIMCraft draws: one slope all round, or one profile swept across");
        }
    }
    Ok(())
}

const STEPS: &str = "its underside steps up or down";

/// A flat roof shaped to its top: as thick as it is under its top's highest point.
#[allow(clippy::too_many_arguments)]
fn shaped_roof(
    ctx: &mut Ctx,
    id: u64,
    t: &super::import_slabs::Top,
    downs: &[(Vec<V3>, (V3, f64))],
    outer: &[V2],
    holes: &[Vec<V2>],
    level: usize,
    name: &Option<String>,
    solids: Vec<Solid>,
) -> Result<(), String> {
    let lev = ctx.levels[level].elevation;
    let hi = highest(t);
    let below = under_z(downs, [hi[0], hi[1]]).unwrap_or(t.z_bottom);
    let thickness = r2(hi[2] - below);
    let offset = r3(hi[2] - thickness - lev);
    let mut tt = t.clone();
    tt.z_top = hi[2];
    let shape = super::import_slabs::shape_value(&tt, outer, holes);
    let tname = name.clone().unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
    let tname = roof_type(ctx, id, &tname, thickness)?;
    let mut m = head(ctx, id, &tname, level);
    m.insert("boundary", pts_value(outer));
    m.insert("slope", Value::f(0.0));
    m.insert("overhang", Value::f(0.0));
    m.insert("offset", Value::f(offset));
    if !holes.is_empty() {
        m.insert("openings", Value::Arr(holes.iter().map(|h| pts_value(h)).collect()));
    }
    m.insert("shape", shape);
    add_roof(ctx, id, m, solids);
    Ok(())
}

/// The top's highest point (the first of them).
fn highest(t: &super::import_slabs::Top) -> V3 {
    t.verts.iter().cloned().fold([0.0, 0.0, f64::NEG_INFINITY], |a, p| if p[2] > a[2] { p } else { a })
}

/// Whether the roof is nowhere thinner (from its top down to its underside) than under its
/// top's highest point.
fn thinnest_at_top(t: &super::import_slabs::Top, downs: &[(Vec<V3>, (V3, f64))]) -> bool {
    let hi = highest(t);
    let th = match under_z(downs, [hi[0], hi[1]]) {
        Some(z) => hi[2] - z,
        None => return false,
    };
    t.verts.iter().all(|v| under_z(downs, [v[0], v[1]]).map(|z| v[2] - z >= th - 0.01).unwrap_or(true))
}

/// The height of the underside under a point in plan: on the face looking down whose outline
/// holds it.
fn under_z(downs: &[(Vec<V3>, (V3, f64))], p: V2) -> Option<f64> {
    let mut best: Option<f64> = None;
    for (pts, (n, d)) in downs {
        if n[2].abs() < 1e-9 {
            continue;
        }
        let poly: Vec<V2> = pts.iter().map(|q| [q[0], q[1]]).collect();
        if !in_polygon(&poly, p) {
            continue;
        }
        let z = (d - n[0] * p[0] - n[1] * p[1]) / n[2];
        if best.map(|b| z < b).unwrap_or(true) {
            best = Some(z);
        }
    }
    best
}

/// Whether a point lies in a polygon (or on its edge, to a hundredth of a millimetre).
fn in_polygon(poly: &[V2], p: V2) -> bool {
    let n = poly.len();
    for i in 0..n {
        if seg_has(poly[i], poly[(i + 1) % n], p) {
            return true;
        }
    }
    let mut inside = false;
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (poly[i], poly[j]);
        if (a[1] > p[1]) != (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0] {
            inside = !inside;
        }
        j = i;
    }
    inside
}

/// The vertical thickness, where it is one all over: the top's height over the underside at
/// each of the top's points.
fn uniform_thickness(ups: &[(Vec<V3>, (V3, f64))], downs: &[(Vec<V3>, (V3, f64))]) -> Option<f64> {
    let mut th: Option<f64> = None;
    for v in ups.iter().flat_map(|u| u.0.iter()) {
        let z = under_z(downs, [v[0], v[1]])?;
        let d = v[2] - z;
        match th {
            None => th = Some(d),
            Some(x) => {
                if (x - d).abs() > 0.01 {
                    return None;
                }
            }
        }
    }
    th
}

/// The thickness square to a sloped face: to the face looking down parallel to it.
fn perpendicular(up: &(V3, f64), downs: &[(Vec<V3>, (V3, f64))]) -> f64 {
    let (n, d) = up;
    let mut best: Option<f64> = None;
    for (_, (n2, d2)) in downs {
        if (n2[0] + n[0]).abs() < 1e-6 && (n2[1] + n[1]).abs() < 1e-6 && (n2[2] + n[2]).abs() < 1e-6 {
            let t = d + d2;
            if t > 0.0 && best.map(|b| t < b).unwrap_or(true) {
                best = Some(t);
            }
        }
    }
    best.unwrap_or(0.0)
}

fn head(ctx: &mut Ctx, id: u64, tname: &str, level: usize) -> Map {
    let tguid = ctx.type_guid("roof", tname);
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("roof"));
    m.insert("type", Value::s(&tguid));
    m.insert("level", ctx.level_guid(level));
    m
}

fn add_roof(ctx: &mut Ctx, id: u64, m: Map, solids: Vec<Solid>) {
    let g = m.get("guid").and_then(|g| g.as_str()).unwrap_or("").to_string();
    let pid = ctx.add(id, Value::Obj(m));
    ctx.roofs.roofs.push((id, pid, g));
    ctx.roofs.bodies.insert(id, solids);
    ctx.slabs.hosts.insert(id, pid);
}

/// A roof's type: the file's type name, its thickness, its layers where they make it up.
fn roof_type(ctx: &mut Ctx, id: u64, name: &str, thickness: f64) -> Result<String, String> {
    // the project refuses a type of no thickness
    if thickness <= 0.0 {
        return Err(format!("{}: roof type `{}` thickness must be above zero, got {}", ctx.path, name, num_name(thickness)));
    }
    let mut tv = crate::jobj! {"thickness" => thickness};
    let pick = |ctx: &Ctx, x: u64| -> Option<u64> {
        let mid = *ctx.m.material_of.get(&x)?;
        let e = ctx.m.get(mid)?;
        match e.name.as_str() {
            "IFCMATERIALLAYERSET" => Some(mid),
            "IFCMATERIALLAYERSETUSAGE" => e.p(0).r(),
            _ => None,
        }
    };
    let set = pick(ctx, id).or_else(|| ctx.m.type_of.get(&id).copied().and_then(|t| pick(ctx, t)));
    if let Some(set) = set {
        if let Some(ls) = import_types::layers(ctx, set, r3(thickness)) {
            tv.set("layers", Value::Arr(ls.into_iter().map(import_types::with_part_id).collect()));
        }
    }
    Ok(import_types::register(ctx, "roof", name, tv))
}

/// How the roof along an edge of its outline climbs from it: the cosine between the uphill of
/// the face along the edge and the edge's inward normal (1: it rises from the edge, an eave;
/// -1: it rises to it), if a sloped face lies along it.
fn edge_gradient(ups: &[(Vec<V3>, (V3, f64))], e: (V2, V2)) -> Option<f64> {
    let d = [e.1[0] - e.0[0], e.1[1] - e.0[1]];
    let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
    if l == 0.0 {
        return None;
    }
    let inward = [-d[1] / l, d[0] / l];
    let mid = [(e.0[0] + e.1[0]) / 2.0, (e.0[1] + e.1[1]) / 2.0];
    for (pts, (n, _)) in ups {
        // the face has an edge on this one
        let k = pts.len();
        let mut on = false;
        for i in 0..k {
            let (a, b) = (pts[i], pts[(i + 1) % k]);
            if seg_has([a[0], a[1]], [b[0], b[1]], mid) {
                on = true;
                break;
            }
        }
        if !on {
            continue;
        }
        let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
        if h < 1e-9 {
            return None;
        }
        let g = [-n[0] / h, -n[1] / h];
        return Some(g[0] * inward[0] + g[1] * inward[1]);
    }
    None
}

/// Whether a sloped face lies in the plane its slope makes rising from one of the eaves (from
/// the top's height there), as each face of a roof of one slope all round does.
fn on_eave_plane(f: &(Vec<V3>, (V3, f64)), eaves: &[(V2, V2, f64)]) -> bool {
    let (n, _) = f.1;
    let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
    if h < 1e-9 || f.0.is_empty() {
        return false;
    }
    let ts = h / n[2];
    let down = [n[0] / h, n[1] / h];
    let mut c = [0.0; 3];
    for p in &f.0 {
        c = geom::add(c, *p);
    }
    let c = geom::mul(c, 1.0 / f.0.len() as f64);
    eaves.iter().any(|(a, b, z)| {
        let d = [b[0] - a[0], b[1] - a[1]];
        let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
        if l == 0.0 {
            return false;
        }
        let inward = [-d[1] / l, d[0] / l];
        // it rises inward from the eave (its downhill straight out across it), through the eave
        // at its height
        let along = down[0] * inward[0] + down[1] * inward[1];
        let at = z + ts * ((c[0] - a[0]) * inward[0] + (c[1] - a[1]) * inward[1]);
        along < -0.999 && (c[2] - at).abs() < 1.0
    })
}

/// Whether the roof rises from an edge of its outline, square to it: an eave, not a gable.
fn is_eave(ups: &[(Vec<V3>, (V3, f64))], e: (V2, V2)) -> bool {
    edge_gradient(ups, e).map(|x| x > 0.999).unwrap_or(false)
}

fn seg_has(a: V2, b: V2, p: V2) -> bool {
    let d = [b[0] - a[0], b[1] - a[1]];
    let l2 = d[0] * d[0] + d[1] * d[1];
    if l2 == 0.0 {
        return false;
    }
    let t = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2;
    if t < -1e-9 || t > 1.0 + 1e-9 {
        return false;
    }
    let q = [a[0] + d[0] * t, a[1] + d[1] * t];
    ((p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2)).sqrt() < 0.01
}

struct Ext {
    a: V2,
    b: V2,
    profile: Vec<V2>,
    width: f64,
    z0: f64,
}

/// A roof that is one profile swept across: every face looking down shares one level
/// direction; its profile the top's section along the line square to it, each face lowered by
/// the roof's depth under it (its thickness over the face's cosine), the lowered faces meeting
/// end to end; its outline the rectangle the profile sweeps.
fn extrusion(t: &super::import_slabs::Top, ups: &[(Vec<V3>, (V3, f64))], downs: &[(Vec<V3>, (V3, f64))], thickness: f64) -> Option<Result<Ext, &'static str>> {
    let ns: Vec<V3> = downs.iter().map(|d| d.1 .0).filter(|n| n[2] < -1e-6).collect();
    if ns.is_empty() {
        return None;
    }
    // the sweep: level, square to every normal
    let mut sweep: Option<V2> = None;
    for n in &ns {
        let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
        if h > 1e-6 {
            sweep = Some([-n[1] / h, n[0] / h]);
            break;
        }
    }
    let sw = sweep?;
    for n in &ns {
        let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
        if (n[0] * sw[0] + n[1] * sw[1]).abs() > 1e-6 * h.max(1e-9) * 1e3 {
            return None;
        }
    }
    // the profile's axis: square to the sweep, pointing east (or north)
    let mut u = [sw[1], -sw[0]];
    if u[0] < -1e-12 || (u[0].abs() <= 1e-12 && u[1] < 0.0) {
        u = [-u[0], -u[1]];
    }
    let left = [-u[1], u[0]];
    // the top's faces in (along u, height), lowered, and how far they spread across
    let mut segs: Vec<(f64, f64, f64, f64)> = Vec::new();
    let (mut c0, mut c1) = (f64::INFINITY, f64::NEG_INFINITY);
    let (mut u0, mut u1) = (f64::INFINITY, f64::NEG_INFINITY);
    for (pts, (n, _)) in ups {
        if n[2] <= 1e-6 {
            continue;
        }
        let drop = thickness / n[2];
        let (mut a, mut b) = ((f64::INFINITY, 0.0), (f64::NEG_INFINITY, 0.0));
        for p in pts {
            let pu = p[0] * u[0] + p[1] * u[1];
            let pc = p[0] * left[0] + p[1] * left[1];
            c0 = c0.min(pc);
            c1 = c1.max(pc);
            u0 = u0.min(pu);
            u1 = u1.max(pu);
            if pu < a.0 {
                a = (pu, p[2]);
            }
            if pu > b.0 {
                b = (pu, p[2]);
            }
        }
        segs.push((a.0, a.1 - drop, b.0, b.1 - drop));
    }
    if segs.is_empty() {
        return None;
    }
    // the lowered faces in order along u (as they come where they start together), each going
    // on from where those before it end: one that lies within them adds nothing, one that
    // starts elsewhere, or at another height, is a step
    segs.sort_by_key(|x| (x.0 * 1000.0).round() as i64);
    let mut line: Vec<V2> = vec![[segs[0].0, segs[0].1]];
    for s in &segs {
        let end = line[line.len() - 1];
        if s.2 <= end[0] + STEP {
            continue;
        }
        if (s.0 - end[0]).abs() > STEP || (s.1 - end[1]).abs() > STEP {
            return Some(Err(STEPS));
        }
        line.push([s.2, s.3]);
    }
    let z0 = line.iter().map(|p| p[1]).fold(f64::INFINITY, f64::min);
    let profile: Vec<V2> = line.iter().map(|p| [p[0] - u0, p[1] - z0]).collect();
    let a = [u[0] * u0 + left[0] * c0, u[1] * u0 + left[1] * c0];
    let b = [u[0] * u1 + left[0] * c0, u[1] * u1 + left[1] * c0];
    // the outline must be the rectangle the profile sweeps
    let rect = [a, b, [b[0] + left[0] * (c1 - c0), b[1] + left[1] * (c1 - c0)], [a[0] + left[0] * (c1 - c0), a[1] + left[1] * (c1 - c0)]];
    let outline = super::import_slabs::simplify(&t.outer);
    let ok = t.holes.is_empty()
        && outline.len() == 4
        && outline.iter().all(|p| rect.iter().any(|q| (p[0] - q[0]).abs() < 0.5 && (p[1] - q[1]).abs() < 0.5));
    if !ok {
        return Some(Err("its outline isn't the rectangle its profile sweeps"));
    }
    Some(Ok(Ext { a, b, profile, width: c1 - c0, z0 }))
}

/// How far apart two lowered faces may end and start and still meet.
const STEP: f64 = 0.5;

/// Walls cut to a roof over them: attached to it (`attach_top`).
pub fn attach(ctx: &mut Ctx) {
    let walls: Vec<(u64, super::import_walls::WallLine)> = ctx.walls.iter().map(|(k, v)| (*k, v.clone())).collect();
    for (_, w) in walls {
        if !w.sloped_top {
            continue;
        }
        // the roof over the wall's middle: the lowest underside above its base there
        let mid = [(w.start[0] + w.end[0]) / 2.0, (w.start[1] + w.end[1]) / 2.0];
        let mut found: Option<(f64, String)> = None;
        let mut any: Option<String> = None;
        for (ent, _, g) in &ctx.roofs.roofs {
            let solids = match ctx.roofs.bodies.get(ent) {
                Some(s) => s,
                None => continue,
            };
            let mut downs: Vec<(Vec<V3>, (V3, f64))> = Vec::new();
            for s in solids {
                for f in &s.faces {
                    if f.outer.len() >= 3 {
                        let pl = plane(&f.outer);
                        if pl.0[2] < -1e-6 {
                            downs.push((f.outer.clone(), pl));
                        }
                    }
                }
            }
            if let Some(z) = under_z(&downs, mid) {
                if any.is_none() {
                    any = Some(g.clone());
                }
                // the one whose underside there is nearest the wall's top
                let d = (z - w.z1).abs();
                if z >= w.z0 - 1.0 && found.as_ref().map(|(b, _)| d < *b).unwrap_or(true) {
                    found = Some((d, g.clone()));
                }
            }
        }
        let found = found.map(|(_, g)| g).or(any);
        if let Some(g) = found {
            if let Some(e) = ctx.pr.el_mut(w.id) {
                set_wall_key(e, "attach_top", Value::s(&g));
            }
        }
    }
}

/// Sets a wall's key in the order the model writes a wall's fields.
pub fn set_wall_key(e: &mut Value, key: &str, v: Value) {
    const ORDER: &[&str] = &[
        "guid", "category", "type", "level", "start", "end", "top_level", "height", "base_offset", "top_offset", "arc", "location", "attach_top",
        "attach_base", "room_bounding", "params",
    ];
    if let Value::Obj(m) = e {
        if m.contains(key) {
            m.insert(key, v);
            return;
        }
        let rank = |k: &str| ORDER.iter().position(|o| *o == k).unwrap_or(usize::MAX);
        let r = rank(key);
        let pos = m.items.iter().position(|(k, _)| rank(k) > r).unwrap_or(m.items.len());
        m.items.insert(pos, (key.to_string(), v));
    }
}
