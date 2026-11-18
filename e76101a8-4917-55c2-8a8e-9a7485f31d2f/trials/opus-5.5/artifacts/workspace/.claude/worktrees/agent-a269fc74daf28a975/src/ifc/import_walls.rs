//! Walls, straight and curved, measured from their bodies (and their axes where the file
//! writes one), with their types' layers; the doors and windows in them.

use super::import::Ctx;
use super::import_build::{self as build, r3};
use super::import_geom::{self as geom, cross, dot, sub, unit, Solid, Tf, V2, V3};
use super::import_types;
use crate::json::Value;

/// A wall as it came in: its centre line and what openings in it are measured against.
#[derive(Clone, Debug)]
pub struct WallLine {
    pub id: u64,
    pub guid: String,
    pub start: V2,
    pub end: V2,
    /// Degrees, counter-clockwise positive; 0 for a straight wall.
    pub arc: f64,
    /// The centre and radius of a curved wall's centre line.
    pub centre: V2,
    pub radius: f64,
    pub thickness: f64,
    pub z0: f64,
    pub z1: f64,
    pub level: usize,
    /// Whether its top is not one level plane (a wall cut to a roof).
    pub sloped_top: bool,
}

impl WallLine {
    /// How far along the wall a point lies, from its start: its projection on the line from
    /// the start to the end (a curved wall's chord too).
    pub fn along(&self, p: V2) -> f64 {
        let d = [self.end[0] - self.start[0], self.end[1] - self.start[1]];
        let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
        if l == 0.0 {
            return 0.0;
        }
        ((p[0] - self.start[0]) * d[0] + (p[1] - self.start[1]) * d[1]) / l
    }
}

pub const WALL_CLASSES: &[&str] = &["IFCWALL", "IFCWALLSTANDARDCASE", "IFCWALLELEMENTEDCASE"];

fn plan(p: V3) -> V2 {
    [p[0], p[1]]
}

/// Whether the points of a polyline lie on one straight line (within a tenth of a millimetre).
fn collinear(pts: &[V3]) -> bool {
    if pts.len() <= 2 {
        return true;
    }
    let a = plan(pts[0]);
    let b = plan(pts[pts.len() - 1]);
    let d = [b[0] - a[0], b[1] - a[1]];
    let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
    if l == 0.0 {
        return true;
    }
    pts.iter().all(|p| ((p[0] - a[0]) * d[1] - (p[1] - a[1]) * d[0]).abs() / l < 0.1)
}

/// Whether a body's top is one level plane at its highest point.
fn top_is_level(solids: &[Solid], z1: f64) -> bool {
    for s in solids {
        for f in &s.faces {
            let n = face_normal(&f.outer);
            if n[2] > 1e-6 && n[2] < 1.0 - 1e-9 {
                // a face that looks up but is not level
                let zs: Vec<f64> = f.outer.iter().map(|p| p[2]).collect();
                let hi = zs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
                let lo = zs.iter().cloned().fold(f64::INFINITY, f64::min);
                if hi - lo > 1e-3 {
                    return false;
                }
            }
        }
    }
    let _ = z1;
    true
}

/// A face's normal (Newell's method), unit length.
pub fn face_normal(pts: &[V3]) -> V3 {
    let mut n = [0.0; 3];
    let k = pts.len();
    // about its first corner, so that a face far from the origin keeps its precision
    let o = match pts.first() {
        Some(o) => *o,
        None => return n,
    };
    for i in 0..k {
        let (a, b) = (sub(pts[i], o), sub(pts[(i + 1) % k], o));
        n[0] += (a[1] - b[1]) * (a[2] + b[2]);
        n[1] += (a[2] - b[2]) * (a[0] + b[0]);
        n[2] += (a[0] - b[0]) * (a[1] + b[1]);
    }
    unit(n)
}

pub fn walls(ctx: &mut Ctx) {
    let mut ids: Vec<u64> = Vec::new();
    for c in WALL_CLASSES {
        ids.extend_from_slice(ctx.m.of(c));
    }
    ids.sort();
    for id in ids {
        wall(ctx, id);
    }
    join(ctx);
}

/// Walls that nearly meet are joined: an end of a straight wall within the thicker wall's
/// thickness of where its centre line crosses another's (on the same level, near that one) is
/// moved there.
fn join(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.walls.keys().copied().collect();
    for &a in &ids {
        for which in 0..2 {
            let wa = ctx.walls[&a].clone();
            if wa.arc != 0.0 {
                continue;
            }
            let e = if which == 0 { wa.start } else { wa.end };
            // an end another wall's end meets (within a millimetre, on any level) is no loose end
            let met = ids.iter().any(|b| {
                if *b == a {
                    return false;
                }
                let wb = &ctx.walls[b];
                [wb.start, wb.end].iter().any(|q| ((q[0] - e[0]).powi(2) + (q[1] - e[1]).powi(2)).sqrt() <= 1.0 + 1e-9)
            });
            if met {
                continue;
            }
            let mut best: Option<(f64, V2)> = None;
            for &b in &ids {
                if b == a {
                    continue;
                }
                let wb = &ctx.walls[&b];
                if wb.arc != 0.0 || wb.level != wa.level {
                    continue;
                }
                let x = match cross_point(wa.start, wa.end, wb.start, wb.end) {
                    Some(x) => x,
                    None => continue,
                };
                let tol = wa.thickness.max(wb.thickness);
                let de = ((e[0] - x[0]).powi(2) + (e[1] - x[1]).powi(2)).sqrt();
                if de > tol + 1e-9 {
                    continue;
                }
                if seg_dist(x, wb.start, wb.end) > tol + 1e-9 {
                    continue;
                }
                if best.map(|(d, _)| de < d).unwrap_or(true) {
                    best = Some((de, x));
                }
            }
            if let Some((_, x)) = best {
                let x = [r3(x[0]), r3(x[1])];
                let w = ctx.walls.get_mut(&a).unwrap();
                if which == 0 {
                    w.start = x;
                } else {
                    w.end = x;
                }
                let pid = w.id;
                let key = if which == 0 { "start" } else { "end" };
                if let Some(el) = ctx.pr.el_mut(pid) {
                    el.set(key, Value::Arr(vec![Value::f(x[0]), Value::f(x[1])]));
                }
            }
        }
    }
}

/// Where two lines (through a–b and c–d) cross, if they are not parallel.
fn cross_point(a: V2, b: V2, c: V2, d: V2) -> Option<V2> {
    let r = [b[0] - a[0], b[1] - a[1]];
    let s = [d[0] - c[0], d[1] - c[1]];
    let den = r[0] * s[1] - r[1] * s[0];
    let lr = (r[0] * r[0] + r[1] * r[1]).sqrt();
    let ls = (s[0] * s[0] + s[1] * s[1]).sqrt();
    if lr == 0.0 || ls == 0.0 || (den / (lr * ls)).abs() < 1e-9 {
        return None;
    }
    let t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den;
    Some([a[0] + r[0] * t, a[1] + r[1] * t])
}

/// The distance from a point to a segment.
fn seg_dist(p: V2, a: V2, b: V2) -> f64 {
    let d = [b[0] - a[0], b[1] - a[1]];
    let l2 = d[0] * d[0] + d[1] * d[1];
    let t = if l2 == 0.0 { 0.0 } else { (((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2).clamp(0.0, 1.0) };
    let q = [a[0] + d[0] * t, a[1] + d[1] * t];
    ((p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2)).sqrt()
}

fn wall(ctx: &mut Ctx, id: u64) {
    let solids = geom::body(&ctx.m, id);
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    if pts.is_empty() {
        ctx.skip(id, "it has no body BIMCraft can read");
        return;
    }
    let tf = geom::product_tf(&ctx.m, id);
    let axis = geom::axis_curve(&ctx.m, id);
    let (z0, z1) = pts.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(a, b), p| (a.min(p[2]), b.max(p[2])));
    // the side the layers are stacked from: a usage stacking to the wall's left (positive)
    // turns it round, so that its first layer is on its left
    let usage = layer_usage(ctx, id);
    let mut line = match axis {
        Some(ax) if !collinear(&ax) && ax.len() >= 3 => match arc_line(&ax, &pts) {
            Some(l) => l,
            None => straight_line(&tf, Some(&ax), &pts),
        },
        Some(ax) => straight_line(&tf, Some(&ax), &pts),
        None => straight_line(&tf, None, &pts),
    };
    if usage.as_ref().map(|u| u.positive).unwrap_or(false) {
        std::mem::swap(&mut line.0, &mut line.1);
        line.2 = -line.2;
    }
    let (start, end, arc, centre, radius, thickness) = line;
    let level = ctx.level_of(id, z0);
    let lev = ctx.levels[level].elevation;
    let height = r3(z1 - z0);
    let base_offset = r3(z0 - lev);
    let sloped = !top_is_level(&solids, z1);
    let top_level = if sloped { None } else { ctx.level_at_top(level, z1) };
    let tname = import_types::wall_type(ctx, id, thickness, usage.as_ref());
    let tguid = ctx.type_guid("wall", &tname);
    let g = ctx.guid_for(id);
    let mut v = crate::jobj! {
        "guid" => g.as_str(),
        "category" => "wall",
        "type" => tguid,
        "level" => ctx.level_guid(level),
        "start" => Value::Arr(vec![Value::f(r3(start[0])), Value::f(r3(start[1]))]),
        "end" => Value::Arr(vec![Value::f(r3(end[0])), Value::f(r3(end[1]))]),
        "top_level" => match top_level { Some(t) => ctx.level_guid(t), None => Value::Null },
        "height" => height,
        "base_offset" => base_offset,
    };
    if arc != 0.0 {
        v.set("arc", Value::f(build::r6(arc)));
    }
    let pid = ctx.add(id, v);
    ctx.walls.insert(
        id,
        WallLine {
            id: pid,
            guid: g,
            start: [r3(start[0]), r3(start[1])],
            end: [r3(end[0]), r3(end[1])],
            arc: if arc != 0.0 { build::r6(arc) } else { 0.0 },
            centre,
            radius,
            thickness,
            z0,
            z1,
            level,
            sloped_top: sloped,
        },
    );
}

type Line = (V2, V2, f64, V2, f64, f64);

/// A straight wall's centre line: along its axis (or its placement's x), across the middle of
/// its body; and its thickness.
fn straight_line(tf: &Tf, axis: Option<&Vec<V3>>, pts: &[V3]) -> Line {
    let (o, u) = match axis {
        Some(ax) => {
            let a = plan(ax[0]);
            let b = plan(ax[ax.len() - 1]);
            let d = [b[0] - a[0], b[1] - a[1]];
            let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
            if l > 0.0 {
                (a, [d[0] / l, d[1] / l])
            } else {
                (plan(tf.t), unit2([tf.x[0], tf.x[1]]))
            }
        }
        None => (plan(tf.t), unit2([tf.x[0], tf.x[1]])),
    };
    let v = [-u[1], u[0]];
    let (mut s0, mut s1, mut t0, mut t1) = (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY);
    for p in pts {
        let d = [p[0] - o[0], p[1] - o[1]];
        let s = d[0] * u[0] + d[1] * u[1];
        let t = d[0] * v[0] + d[1] * v[1];
        s0 = s0.min(s);
        s1 = s1.max(s);
        t0 = t0.min(t);
        t1 = t1.max(t);
    }
    if let Some(ax) = axis {
        let a = plan(ax[0]);
        let b = plan(ax[ax.len() - 1]);
        let sa = (a[0] - o[0]) * u[0] + (a[1] - o[1]) * u[1];
        let sb = (b[0] - o[0]) * u[0] + (b[1] - o[1]) * u[1];
        s0 = sa;
        s1 = sb;
    }
    let tm = (t0 + t1) / 2.0;
    let start = [o[0] + u[0] * s0 + v[0] * tm, o[1] + u[1] * s0 + v[1] * tm];
    let end = [o[0] + u[0] * s1 + v[0] * tm, o[1] + u[1] * s1 + v[1] * tm];
    (start, end, 0.0, [0.0, 0.0], 0.0, t1 - t0)
}

fn unit2(a: V2) -> V2 {
    let l = (a[0] * a[0] + a[1] * a[1]).sqrt();
    if l > 0.0 {
        [a[0] / l, a[1] / l]
    } else {
        [1.0, 0.0]
    }
}

/// A curved wall's centre line: the circle of its axis, at the middle of its body's radii.
fn arc_line(ax: &[V3], pts: &[V3]) -> Option<Line> {
    let a = plan(ax[0]);
    let b = plan(ax[ax.len() / 2]);
    let c = plan(ax[ax.len() - 1]);
    let (cc, _r) = geom::circle3(a, b, c)?;
    let (mut r0, mut r1) = (f64::INFINITY, f64::NEG_INFINITY);
    for p in pts {
        let r = ((p[0] - cc[0]).powi(2) + (p[1] - cc[1]).powi(2)).sqrt();
        r0 = r0.min(r);
        r1 = r1.max(r);
    }
    let rm = (r0 + r1) / 2.0;
    let a0 = (a[1] - cc[1]).atan2(a[0] - cc[0]);
    let am = (b[1] - cc[1]).atan2(b[0] - cc[0]);
    let a1 = (c[1] - cc[1]).atan2(c[0] - cc[0]);
    let tau = 2.0 * std::f64::consts::PI;
    let n = |x: f64| ((x % tau) + tau) % tau;
    let ccw_m = n(am - a0);
    let ccw_c = n(a1 - a0);
    let sweep = if ccw_m <= ccw_c { ccw_c } else { ccw_c - tau };
    let start = [cc[0] + rm * a0.cos(), cc[1] + rm * a0.sin()];
    let end = [cc[0] + rm * a1.cos(), cc[1] + rm * a1.sin()];
    Some((start, end, sweep.to_degrees(), cc, rm, r1 - r0))
}

/// A wall's material layer set usage: the set, and whether its layers stack to the positive
/// side of the wall's placement.
pub struct Usage {
    pub set: u64,
    pub positive: bool,
}

pub fn layer_usage(ctx: &Ctx, id: u64) -> Option<Usage> {
    let mid = *ctx.m.material_of.get(&id)?;
    let e = ctx.m.get(mid)?;
    if e.name == "IFCMATERIALLAYERSETUSAGE" {
        let set = e.p(0).r()?;
        let positive = e.p(2).enm() == Some("POSITIVE");
        return Some(Usage { set, positive });
    }
    None
}

// ---------------------------------------------------------------- doors and windows

pub fn openings(ctx: &mut Ctx) -> Result<(), String> {
    let mut ids: Vec<u64> = Vec::new();
    for c in ["IFCDOOR", "IFCWINDOW", "IFCDOORSTANDARDCASE", "IFCWINDOWSTANDARDCASE"] {
        ids.extend_from_slice(ctx.m.of(c));
    }
    ids.sort();
    for &id in &ids {
        opening(ctx, id)?;
    }
    // a door or window the file gives no tag (or one an earlier one has) numbered on in its
    // category's series
    for cat in ["door", "window"] {
        let mut used: Vec<String> = Vec::new();
        let mut pending: Vec<u64> = Vec::new();
        for id in &ids {
            let pid = match ctx.made.get(id) {
                Some(m) if m.cat == cat => m.id,
                _ => continue,
            };
            let tag = ctx.pr.elements.get(&pid).and_then(|e| e.get("mark")).and_then(|m| m.as_str()).unwrap_or("").to_string();
            if !tag.is_empty() && !used.contains(&tag) {
                used.push(tag);
            } else {
                pending.push(pid);
            }
        }
        for pid in pending {
            let m = next_mark(&used);
            if let Some(e) = ctx.pr.elements.get_mut(&pid) {
                e.set("mark", Value::s(&m));
            }
            used.push(m);
        }
    }
    Ok(())
}

/// The mark after a category's marks: on in the series most of them are in (two at least; the
/// first by name of those as many), else in plain numbers; as wide as the widest of its series.
pub fn next_mark(marks: &[String]) -> String {
    let mut groups: std::collections::BTreeMap<String, (usize, u64, usize)> = std::collections::BTreeMap::new();
    let mut seen: Vec<&String> = Vec::new();
    for m in marks {
        if seen.contains(&m) {
            continue;
        }
        seen.push(m);
        let digits = m.chars().rev().take_while(|c| c.is_ascii_digit()).count();
        if digits == 0 {
            continue;
        }
        let (prefix, num) = m.split_at(m.len() - digits);
        let n: u64 = match num.parse() {
            Ok(n) => n,
            Err(_) => continue,
        };
        let g = groups.entry(prefix.to_string()).or_insert((0, 0, 0));
        g.0 += 1;
        g.1 = g.1.max(n);
        g.2 = g.2.max(digits);
    }
    let mut best: Option<(&String, &(usize, u64, usize))> = None;
    for (p, g) in &groups {
        if g.0 >= 2 && best.map(|b| g.0 > b.1 .0).unwrap_or(true) {
            best = Some((p, g));
        }
    }
    // plain numbers are never padded
    let pick = best.or_else(|| groups.get_key_value(""));
    match pick {
        Some((p, g)) if p.is_empty() => format!("{}", g.1 + 1),
        Some((p, g)) => format!("{}{:0w$}", p, g.1 + 1, w = g.2),
        None => "1".to_string(),
    }
}

fn opening(ctx: &mut Ctx, id: u64) -> Result<(), String> {
    let class = ctx.m.class(id).to_string();
    let cat = if class.starts_with("IFCDOOR") { "door" } else { "window" };
    // its wall: the one whose opening it fills
    let host = ctx.m.fills.get(&id).and_then(|o| ctx.m.voided.get(o)).copied();
    let host = match host {
        Some(h) => h,
        None => {
            ctx.skip(id, "it fills no opening in a wall");
            return Ok(());
        }
    };
    let wl = match ctx.walls.get(&host) {
        Some(w) => w.clone(),
        None => {
            ctx.skip(id, "its wall was left out");
            return Ok(());
        }
    };
    let e = ctx.m.get(id).unwrap().clone();
    let solids = geom::body(&ctx.m, id);
    let opening_ent = ctx.m.fills.get(&id).copied();
    if let Some(o) = opening_ent {
        ctx.handled.insert(o);
    }
    let osolids = opening_ent.map(|o| geom::body(&ctx.m, o)).unwrap_or_default();
    let use_solids = if osolids.is_empty() { &solids } else { &osolids };
    let pts: Vec<V3> = use_solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    let s = ctx.m.scale;
    // the file's overall sizes where they are some, else what it measures
    let ow = e.p(9).num().map(|x| x * s).filter(|x| *x > 0.0);
    let oh = e.p(8).num().map(|x| x * s).filter(|x| *x > 0.0);
    let (centre, zlo, zhi, wmeas) = match geom::bbox(pts.iter()) {
        Some((lo, hi)) => {
            // the opening's extent along the wall
            let (mut a0, mut a1) = (f64::INFINITY, f64::NEG_INFINITY);
            for p in &pts {
                let a = wl.along(plan(*p));
                a0 = a0.min(a);
                a1 = a1.max(a);
            }
            ((a0 + a1) / 2.0, lo[2], hi[2], a1 - a0)
        }
        None => {
            ctx.skip(id, "it has no body BIMCraft can read");
            return Ok(());
        }
    };
    let width = r3(ow.unwrap_or(wmeas));
    let height = r3(oh.unwrap_or(zhi - zlo));
    let sill = super::import_build::r2(zlo - wl.z0);
    let operation = if cat == "door" { door_operation(ctx, id) } else { window_operation(ctx, id) };
    let flip_hand = cat == "door" && door_hand_right(ctx, id);
    let tname = import_types::opening_type(ctx, id, cat, width, height, sill, operation.as_deref()).map_err(|e| format!("{}: {}", ctx.path, e))?;
    let tguid = ctx.type_guid(cat, &tname);
    // its tag, unless the tag is the id its name ends with (Revit's `Family:Type:123456`)
    let mark = e.p(7).str().map(|s| s.to_string()).unwrap_or_default();
    let mark = match e.p(2).str() {
        Some(n) if !mark.is_empty() && n.ends_with(&format!(":{}", mark)) => String::new(),
        _ => mark,
    };
    let g = ctx.guid_for(id);
    let v = crate::jobj! {
        "guid" => g.as_str(),
        "category" => cat,
        "type" => tguid,
        "host" => wl.guid.as_str(),
        "offset" => r3(centre),
        "sill" => sill,
        "mark" => mark,
        "flip_facing" => false,
        "flip_hand" => flip_hand,
    };
    ctx.add(id, v);
    let _ = (cross([0.0; 3], [0.0; 3]), dot([0.0; 3], [0.0; 3]), sub([0.0; 3], [0.0; 3]));
    Ok(())
}

/// A door's OperationType: its own where it gives one (IFC4), else its type's (or its style's).
fn door_operation_type(ctx: &Ctx, id: u64) -> Option<String> {
    let e = ctx.m.get(id)?;
    if ctx.m.is_ifc4() && !e.p(11).is_null() {
        return e.p(11).enm().map(|s| s.to_string());
    }
    let t = ctx.m.type_of.get(&id).and_then(|t| ctx.m.get(*t))?;
    match t.name.as_str() {
        "IFCDOORTYPE" => t.p(10).enm().map(|s| s.to_string()),
        "IFCDOORSTYLE" => t.p(8).enm().map(|s| s.to_string()),
        _ => None,
    }
}

/// A door's operation as BIMCraft names it, from its OperationType (or its type's).
fn door_operation(ctx: &Ctx, id: u64) -> Option<String> {
    let op = door_operation_type(ctx, id)?;
    Some(
        match op.as_str() {
            "SINGLE_SWING_LEFT" | "SINGLE_SWING_RIGHT" | "DOUBLE_SWING_LEFT" | "DOUBLE_SWING_RIGHT" | "SWING_FIXED_LEFT" | "SWING_FIXED_RIGHT" => "swing",
            "DOUBLE_DOOR_SINGLE_SWING" | "DOUBLE_DOOR_SINGLE_SWING_OPPOSITE_LEFT" | "DOUBLE_DOOR_SINGLE_SWING_OPPOSITE_RIGHT" | "DOUBLE_DOOR_DOUBLE_SWING" => "double-swing",
            "SLIDING_TO_LEFT" | "SLIDING_TO_RIGHT" => "sliding",
            "DOUBLE_DOOR_SLIDING" => "double-sliding",
            "FOLDING_TO_LEFT" | "FOLDING_TO_RIGHT" | "DOUBLE_DOOR_FOLDING" => "folding",
            _ => return None,
        }
        .to_string(),
    )
}

/// Whether a door opens to the right (its operation says so).
fn door_hand_right(ctx: &Ctx, id: u64) -> bool {
    door_operation_type(ctx, id).map(|o| o.ends_with("RIGHT")).unwrap_or(false)
}

fn window_operation(_ctx: &Ctx, _id: u64) -> Option<String> {
    None
}
