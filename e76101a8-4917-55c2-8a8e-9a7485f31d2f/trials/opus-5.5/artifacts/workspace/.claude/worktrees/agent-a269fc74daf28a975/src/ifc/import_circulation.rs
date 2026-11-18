//! Masses, stairs and ramps (straight flights with the landings between them), railings, and
//! room separators.

use super::import::Ctx;
use super::import_build::{num_name, r3, r3z, r6};
use super::import_geom::{self as geom, Solid, V2, V3};
use super::import_types;
use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// What this module keeps for later passes.
#[derive(Default)]
pub struct State {
    /// The stairs and ramps that came in: entity → (start, direction of the first flight,
    /// width, base z).
    pub hosts: BTreeMap<u64, (V2, V2, f64, f64)>,
}

fn pv(p: V2) -> Value {
    Value::Arr(vec![Value::f(r3z(p[0])), Value::f(r3z(p[1]))])
}

fn deg(d: V2) -> f64 {
    let mut a = d[1].atan2(d[0]).to_degrees();
    if a < -1e-9 {
        a += 360.0;
    }
    if a >= 360.0 - 1e-9 {
        a -= 360.0;
    }
    a
}

// ---------------------------------------------------------------- masses

/// Proxies of object type `Mass`: masses.
pub fn masses(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCBUILDINGELEMENTPROXY").to_vec();
    for id in ids {
        if ctx.m.object_type(id).as_deref().map(|s| s.trim()) != Some("Mass") {
            continue;
        }
        mass(ctx, id);
    }
}

fn loft_points(v: &Value, k: &str) -> Option<Vec<V2>> {
    let a = v.get(k)?.as_arr()?;
    let mut out = Vec::new();
    for p in a {
        let q = p.as_arr()?;
        out.push([q.first()?.as_f64()?, q.get(1)?.as_f64()?]);
    }
    Some(out)
}

fn mass(ctx: &mut Ctx, id: u64) {
    let solids = geom::body(&ctx.m, id);
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    if pts.is_empty() {
        ctx.skip(id, "it has no body BIMCraft can read");
        return;
    }
    let (z0, z1) = pts.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(a, b), p| (a.min(p[2]), b.max(p[2])));
    let loft = ctx
        .m
        .prop(id, "BIMCraft_Mass", "Loft")
        .and_then(|p| p.str().map(|s| s.to_string()))
        .and_then(|s| crate::json::parse(&s).ok());
    // a loft is its two outlines, corner for corner
    let loft = loft.and_then(|l| match (loft_points(&l, "bottom"), loft_points(&l, "top")) {
        (Some(b), Some(t)) if b.len() == t.len() && b.len() >= 3 => Some((b, t)),
        _ => None,
    });
    let (boundary, top) = match loft {
        Some((b, t)) => (b, Some(t)),
        None => {
            // an extrusion straight up, or a body whose outline doesn't change from base to top
            let t = match super::import_slabs::top(&solids) {
                Some(t) => t,
                None => {
                    ctx.skip(id, "it has no body BIMCraft can read");
                    return;
                }
            };
            if !t.holes.is_empty() {
                ctx.skip(id, "a mass with a courtyard in it is more than BIMCraft draws");
                return;
            }
            let straight = solids.len() == 1 && solids[0].ext.as_ref().map(|x| x.tf.dir(x.dir)[2].abs() > 1.0 - 1e-9).unwrap_or(false);
            if !straight && !(t.plane.map(|p| p.1[2] > 1.0 - 1e-9).unwrap_or(false) && t.z_bottom == z0) {
                ctx.skip(id, "its outline changes from its base to its top, and no BIMCraft_Mass property set says how its corners pair up");
                return;
            }
            (super::import_slabs::canonical(&t.outer, false), None)
        }
    };
    let level = ctx.level_of(id, z0);
    let lev = ctx.levels[level].elevation;
    let top_level = ctx.level_at_top(level, z1);
    let name = ctx.m.name(id).map(|n| n.trim().to_string()).unwrap_or_default();
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("mass"));
    m.insert("name", Value::s(&name));
    m.insert("level", ctx.level_guid(level));
    m.insert("boundary", Value::Arr(boundary.iter().map(|p| pv(*p)).collect()));
    m.insert("top_level", match top_level {
        Some(t) => ctx.level_guid(t),
        None => Value::Null,
    });
    m.insert("height", Value::f(r3(z1 - z0)));
    m.insert("base_offset", Value::f(r3(z0 - lev)));
    let lofted = top.is_some();
    if let Some(t) = top {
        m.insert("top", Value::Arr(t.iter().map(|p| pv(*p)).collect()));
    }
    let pid = ctx.add(id, Value::Obj(m));
    // a loft's outlines are the set's, as it gives them
    if lofted {
        ctx.fixed.insert((pid, "boundary"));
        ctx.fixed.insert((pid, "top"));
    }
}

// ---------------------------------------------------------------- stairs and ramps

/// A flight's direction, start, width and going: from its steps (the first to the last), or,
/// with one step, along the first of its longest sides.
struct Flight {
    dir: V2,
    start: V2,
    width: f64,
    /// How far all its steps run along it.
    run: f64,
    z0: f64,
    z1: f64,
}

fn plan_loops(solids: &[Solid]) -> Vec<Vec<V2>> {
    let mut out = Vec::new();
    for s in solids {
        let up = s.ext.as_ref().map(|x| geom::unit(x.tf.dir(x.dir))[2].abs() > 1.0 - 1e-9).unwrap_or(false);
        if let (Some(x), true) = (&s.ext, up) {
            out.push(
                x.outer
                    .iter()
                    .map(|p| {
                        let q = x.tf.apply([p[0], p[1], 0.0]);
                        [q[0], q[1]]
                    })
                    .collect(),
            );
        } else if let Some(t) = super::import_slabs::top(std::slice::from_ref(s)) {
            out.push(super::import_slabs::canonical(&t.outer, false));
        }
    }
    out
}

fn centre(l: &[V2]) -> V2 {
    let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    for p in l {
        x0 = x0.min(p[0]);
        x1 = x1.max(p[0]);
        y0 = y0.min(p[1]);
        y1 = y1.max(p[1]);
    }
    [(x0 + x1) / 2.0, (y0 + y1) / 2.0]
}

fn first_longest(l: &[V2]) -> Option<V2> {
    let p = super::import_slabs::simplify(l);
    let n = p.len();
    if n < 2 {
        return None;
    }
    let mut best = 0;
    let mut bl = -1.0;
    for i in 0..n {
        let (a, b) = (p[i], p[(i + 1) % n]);
        let len = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
        if len > bl + 1e-6 {
            bl = len;
            best = i;
        }
    }
    let (a, b) = (p[best], p[(best + 1) % n]);
    Some([(b[0] - a[0]) / bl, (b[1] - a[1]) / bl])
}

fn extent(l: &[V2], d: V2) -> (f64, f64) {
    let mut lo = f64::INFINITY;
    let mut hi = f64::NEG_INFINITY;
    for p in l {
        let s = p[0] * d[0] + p[1] * d[1];
        lo = lo.min(s);
        hi = hi.max(s);
    }
    (lo, hi)
}

fn stair_flight(solids: &[Solid]) -> Option<Flight> {
    let loops = plan_loops(solids);
    if loops.is_empty() {
        return None;
    }
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    let (z0, z1) = pts.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(a, b), p| (a.min(p[2]), b.max(p[2])));
    let dir = if loops.len() >= 2 {
        let (a, b) = (centre(&loops[0]), centre(&loops[loops.len() - 1]));
        let d = [b[0] - a[0], b[1] - a[1]];
        let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
        if l < 1e-9 {
            first_longest(&loops[0])?
        } else {
            [d[0] / l, d[1] / l]
        }
    } else {
        first_longest(&loops[0])?
    };
    let across = [-dir[1], dir[0]];
    let (s0, _) = extent(&loops[0], dir);
    let (t0, t1) = extent(&loops[0], across);
    let tm = (t0 + t1) / 2.0;
    let start = [dir[0] * s0 + across[0] * tm, dir[1] * s0 + across[1] * tm];
    let (mut r0, mut r1) = (f64::INFINITY, f64::NEG_INFINITY);
    for l in &loops {
        let (a, b) = extent(l, dir);
        r0 = r0.min(a);
        r1 = r1.max(b);
    }
    Some(Flight { dir, start, width: t1 - t0, run: r1 - r0, z0, z1 })
}

/// A ramp's flight: its top's slope, the foot it rises from and its width across.
struct RampFlight {
    dir: V2,
    start: V2,
    width: f64,
    rise: f64,
    run: f64,
    z0: f64,
    z1: f64,
}

fn ramp_flight(solids: &[Solid]) -> Option<RampFlight> {
    let mut best: Option<(Vec<V3>, V3)> = None;
    for s in solids {
        for f in &s.faces {
            if f.outer.len() < 3 {
                continue;
            }
            let n = super::import_walls::face_normal(&f.outer);
            if n[2] > 1e-6 && n[2] < 1.0 - 1e-9 && best.is_none() {
                best = Some((f.outer.clone(), n));
            }
        }
    }
    let (face, n) = best?;
    let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
    let dir = [-n[0] / h, -n[1] / h];
    let across = [-dir[1], dir[0]];
    let plan: Vec<V2> = face.iter().map(|p| [p[0], p[1]]).collect();
    let (s0, s1) = extent(&plan, dir);
    let (t0, t1) = extent(&plan, across);
    let tm = (t0 + t1) / 2.0;
    let start = [dir[0] * s0 + across[0] * tm, dir[1] * s0 + across[1] * tm];
    let zs: Vec<f64> = face.iter().map(|p| p[2]).collect();
    let z0 = zs.iter().cloned().fold(f64::INFINITY, f64::min);
    let z1 = zs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    Some(RampFlight { dir, start, width: t1 - t0, rise: z1 - z0, run: s1 - s0, z0, z1 })
}

fn turn(a: V2, b: V2) -> f64 {
    let c = a[0] * b[0] + a[1] * b[1];
    let s = a[0] * b[1] - a[1] * b[0];
    let mut t = s.atan2(c).to_degrees();
    if t <= -180.0 + 1e-6 {
        t = 180.0;
    }
    r6(t)
}

/// IfcStair (its flights, or its own body as one), a flight that is no stair's, IfcRamp: stairs
/// and ramps.
pub fn stairs(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCSTAIR").to_vec();
    for id in ids {
        stair(ctx, id, false);
    }
    let ids: Vec<u64> = ctx.m.of("IFCSTAIRFLIGHT").to_vec();
    for id in ids {
        let in_stair = ctx.m.parent.get(&id).map(|p| ctx.m.class(*p) == "IFCSTAIR").unwrap_or(false);
        if !in_stair {
            stair(ctx, id, true);
        }
    }
    let ids: Vec<u64> = ctx.m.of("IFCRAMP").to_vec();
    for id in ids {
        ramp(ctx, id);
    }
}

/// A flight measured: its plan, its risers, their height and the going of a tread.
struct Measured {
    geo: Flight,
    risers: i64,
    riser: f64,
    tread: f64,
}

/// A flight's steps from its body: each step one outline in plan (the file's riser and tread
/// counts and sizes where it gives them); one solid with no steps is cut into the treads the
/// file counts.
fn measure(ctx: &Ctx, solids: &[Solid], ent: Option<u64>) -> Result<Measured, &'static str> {
    let s = ctx.m.scale;
    let e = ent.and_then(|f| ctx.m.get(f)).filter(|e| e.name == "IFCSTAIRFLIGHT");
    let n_risers = e.and_then(|e| e.p(8).int()).filter(|n| *n > 0);
    let n_treads = e.and_then(|e| e.p(9).int()).filter(|n| *n > 0);
    let rh = e.and_then(|e| e.p(10).num()).map(|x| x * s).filter(|x| *x > 0.0);
    let tl = e.and_then(|e| e.p(11).num()).map(|x| x * s).filter(|x| *x > 0.0);
    let _ = (n_treads, tl);
    let steps = plan_loops(solids).len() as i64;
    let geo = stair_flight(solids).ok_or("it has no body BIMCraft can read")?;
    // the steps it shows, or one solid cut into the risers the file counts; a tread the run
    // over the risers but the last
    let (risers, riser) = if steps >= 2 {
        let risers = n_risers.unwrap_or(steps + 1);
        (risers, rh.unwrap_or((geo.z1 - geo.z0) / steps as f64))
    } else {
        let risers = n_risers.ok_or("BIMCraft can't find its treads")?;
        (risers, rh.unwrap_or((geo.z1 - geo.z0) / risers as f64))
    };
    let tread = if risers > 1 { geo.run / (risers - 1) as f64 } else { geo.run };
    Ok(Measured { geo, risers, riser, tread })
}

fn stair(ctx: &mut Ctx, id: u64, loose: bool) {
    let flights: Vec<u64> = if loose {
        vec![id]
    } else {
        let parts: Vec<u64> = ctx.m.children.get(&id).cloned().unwrap_or_default();
        parts.iter().copied().filter(|p| ctx.m.class(*p) == "IFCSTAIRFLIGHT").collect()
    };
    let mut fl: Vec<Measured> = Vec::new();
    if flights.is_empty() {
        let solids = geom::body(&ctx.m, id);
        if solids.is_empty() {
            ctx.skip(id, "it has no body BIMCraft can read");
            return;
        }
        match measure(ctx, &solids, None) {
            Ok(x) => fl.push(x),
            Err(why) => {
                ctx.skip(id, why);
                return;
            }
        }
    } else {
        for f in &flights {
            let solids = geom::body(&ctx.m, *f);
            if solids.is_empty() {
                ctx.skip(id, "it has no body BIMCraft can read");
                return;
            }
            match measure(ctx, &solids, Some(*f)) {
                Ok(x) => fl.push(x),
                Err(why) => {
                    ctx.skip(id, why);
                    return;
                }
            }
        }
    }
    let base = fl.iter().map(|f| f.geo.z0).fold(f64::INFINITY, f64::min);
    let total: i64 = fl.iter().map(|f| f.risers).sum();
    let height = r3(fl.iter().map(|f| f.risers as f64 * f.riser).sum::<f64>());
    let first = &fl[0];
    let level = ctx.level_of(id, base);
    let top_level = ctx.level_at_top(level, base + height);
    // a stair up to a level rises the levels' height in its risers
    let span = match top_level {
        Some(t) => ctx.levels[t].elevation - ctx.levels[level].elevation,
        None => height,
    };
    let riser = if total > 0 { span / total as f64 } else { 0.0 };
    let mut landings = Vec::new();
    let mut at = 0i64;
    for i in 0..fl.len() - 1 {
        at += fl[i].risers;
        landings.push(crate::jobj! {"at" => Value::f(at as f64), "turn" => Value::f(turn(fl[i].geo.dir, fl[i + 1].geo.dir))});
    }
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("stair"));
    m.insert("level", ctx.level_guid(level));
    m.insert("top_level", match top_level {
        Some(t) => ctx.level_guid(t),
        None => Value::Null,
    });
    m.insert("height", Value::f(height));
    m.insert("start", pv(first.geo.start));
    m.insert("angle", Value::f(r6(deg(first.geo.dir))));
    m.insert("width", Value::f(r3(first.geo.width)));
    m.insert("riser", Value::f(riser));
    m.insert("tread", Value::f(r3(first.tread)));
    if !landings.is_empty() {
        m.insert("landings", Value::Arr(landings));
    }
    let (start, dir, width) = (first.geo.start, first.geo.dir, first.geo.width);
    ctx.add(id, Value::Obj(m));
    for f in &flights {
        ctx.handled.insert(*f);
    }
    ctx.circulation.hosts.insert(id, (start, dir, width, base));
}

fn ramp(ctx: &mut Ctx, id: u64) {
    let parts: Vec<u64> = ctx.m.children.get(&id).cloned().unwrap_or_default();
    let flights: Vec<u64> = parts.iter().copied().filter(|p| ctx.m.class(*p) == "IFCRAMPFLIGHT").collect();
    let mut fl: Vec<RampFlight> = Vec::new();
    for f in &flights {
        let solids = geom::body(&ctx.m, *f);
        match ramp_flight(&solids) {
            Some(x) => fl.push(x),
            None => {
                ctx.skip(id, "its top isn't one flat face BIMCraft can read");
                return;
            }
        }
    }
    if fl.is_empty() {
        let own = geom::body(&ctx.m, id);
        match ramp_flight(&own) {
            Some(x) => fl.push(x),
            None => {
                ctx.skip(id, "its top isn't one flat face BIMCraft can read");
                return;
            }
        }
    }
    let base = fl.iter().map(|f| f.z0).fold(f64::INFINITY, f64::min);
    let top = fl.iter().map(|f| f.z1).fold(f64::NEG_INFINITY, f64::max);
    let height = top - base;
    let first = &fl[0];
    let slope = if first.run > 0.0 { first.rise / first.run * 100.0 } else { 0.0 };
    let level = ctx.level_of(id, base);
    let top_level = ctx.level_at_top(level, top);
    let mut landings = Vec::new();
    for i in 0..fl.len() - 1 {
        landings.push(crate::jobj! {"at" => Value::f(r3(fl[i].z1 - base)), "turn" => Value::f(turn(fl[i].dir, fl[i + 1].dir))});
    }
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("ramp"));
    m.insert("level", ctx.level_guid(level));
    m.insert("top_level", match top_level {
        Some(t) => ctx.level_guid(t),
        None => Value::Null,
    });
    m.insert("height", Value::f(r3(height)));
    m.insert("start", pv(first.start));
    m.insert("angle", Value::f(r6(deg(first.dir))));
    m.insert("width", Value::f(r3(first.width)));
    m.insert("slope", Value::f(r6(slope)));
    if !landings.is_empty() {
        m.insert("landings", Value::Arr(landings));
    }
    ctx.add(id, Value::Obj(m));
    ctx.circulation.hosts.insert(id, (first.start, first.dir, first.width, base));
}

// ---------------------------------------------------------------- railings

/// IfcRailing: railings, on a stair or ramp or along a path.
pub fn railings(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCRAILING").to_vec();
    for id in ids {
        railing(ctx, id);
    }
}

fn railing(ctx: &mut Ctx, id: u64) {
    let solids = geom::body(&ctx.m, id);
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    let axis = geom::axis_curve(&ctx.m, id);
    let host = ctx.m.parent.get(&id).copied().filter(|p| ctx.circulation.hosts.contains_key(p));
    let zmin = pts.iter().map(|p| p[2]).fold(f64::INFINITY, f64::min);
    // by its axis (the rail's top line), else a straight one by its body
    let path: Vec<V3> = match &axis {
        Some(_) if pts.is_empty() => {
            ctx.skip(id, "its railing height cannot be measured from its body");
            return;
        }
        Some(a) => a.clone(),
        None => {
            // along the long side of its box in plan, through the middle, at its top: when the
            // box is no more than 300 mm across
            let straight = geom::bbox(pts.iter()).and_then(|(lo, hi)| {
                let (dx, dy) = (hi[0] - lo[0], hi[1] - lo[1]);
                let (xm, ym) = ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0);
                if dx > dy {
                    (dy <= 300.0 + 1e-9).then(|| vec![[lo[0], ym, hi[2]], [hi[0], ym, hi[2]]])
                } else {
                    (dx <= 300.0 + 1e-9).then(|| vec![[xm, lo[1], hi[2]], [xm, hi[1], hi[2]]])
                }
            });
            match straight {
                Some(p) => p,
                None => {
                    ctx.skip(id, "it has no axis for BIMCraft to follow, and it isn't straight");
                    return;
                }
            }
        }
    };
    let level = match host {
        Some(h) => ctx.made.get(&h).and_then(|m| ctx.pr.el(m.id)).and_then(|e| e.get("level")).and_then(|l| l.as_str()).and_then(|g| ctx.levels.iter().position(|l| l.guid == g)),
        None => None,
    }
    .unwrap_or_else(|| ctx.level_of(id, zmin));
    let lev = ctx.levels[level].elevation;
    let height = match host {
        Some(h) => path[0][2] - ctx.circulation.hosts[&h].3,
        None => path[0][2] - zmin,
    };
    let height = r3(height);
    let base_name = import_types::file_type_name(ctx, id).unwrap_or_else(|| format!("Imported - {}mm", num_name(height)));
    let spacing = super::import_build::type_value(&ctx.pr, "railing", &base_name).and_then(|t| t.get("spacing")).and_then(|s| s.as_f64()).unwrap_or(0.0);
    let tname = import_types::register(ctx, "railing", &base_name, crate::jobj! {"height" => height, "spacing" => spacing});
    let tguid = ctx.type_guid("railing", &tname);
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("railing"));
    m.insert("type", Value::s(&tguid));
    m.insert("level", ctx.level_guid(level));
    match host {
        Some(h) => {
            let (start, dir, _, _) = ctx.circulation.hosts[&h];
            let p = path[0];
            let left = [-dir[1], dir[0]];
            let side = if (p[0] - start[0]) * left[0] + (p[1] - start[1]) * left[1] >= 0.0 { "left" } else { "right" };
            let hg = ctx.made[&h].guid.clone();
            m.insert("host", Value::s(&hg));
            m.insert("side", Value::s(side));
        }
        None => {
            m.insert("path", Value::Arr(path.iter().map(|p| pv([p[0], p[1]])).collect()));
            let bo = r3(zmin - lev);
            if bo != 0.0 {
                m.insert("base_offset", Value::f(bo));
            }
        }
    }
    ctx.add(id, Value::Obj(m));
}

// ---------------------------------------------------------------- room separators

/// Room separation lines: virtual elements of object type `RoomSeparation`, one for each
/// segment of their axis.
pub fn separators(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCVIRTUALELEMENT").to_vec();
    for id in ids {
        let ot = ctx.m.object_type(id).unwrap_or_default();
        if ot != "RoomSeparation" {
            continue;
        }
        let pts = match super::import_geom::axis_curve(&ctx.m, id) {
            Some(p) => p,
            None => continue,
        };
        let z = pts.iter().map(|p| p[2]).fold(f64::INFINITY, f64::min);
        let level = ctx.level_of(id, z);
        let a = pts[0];
        let b = pts[pts.len() - 1];
        let g = ctx.guid_for(id);
        let v = crate::jobj! {
            "guid" => g.as_str(),
            "category" => "roomseparator",
            "level" => ctx.level_guid(level),
            "start" => pv([a[0], a[1]]),
            "end" => pv([b[0], b[1]]),
        };
        ctx.add(id, v);
    }
}
