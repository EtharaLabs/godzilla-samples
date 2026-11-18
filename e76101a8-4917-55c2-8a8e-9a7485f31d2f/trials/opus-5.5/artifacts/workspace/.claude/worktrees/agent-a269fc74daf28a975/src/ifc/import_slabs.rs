//! Floors (level or sloped, shaped, structural), ceilings, and the shafts through floors,
//! ceilings and roofs.

use super::import::Ctx;
use super::import_build::{num_name, r3, r3z, r6};
use super::import_geom::{self as geom, Solid, V2, V3};
use super::import_types;
use super::import_walls::face_normal;
use crate::json::{Map, Value};
use std::collections::BTreeMap;

/// What this module keeps for later passes.
#[derive(Default)]
pub struct State {
    /// The slabs, ceilings and roofs that came in: entity → element id.
    pub hosts: BTreeMap<u64, u64>,
}

// ---------------------------------------------------------------- loops in plan

/// The signed area of a plan loop.
pub fn area(v: &[V2]) -> f64 {
    geom::area2(v)
}

/// A loop without its repeated points and the points that lie on the line between their
/// neighbours.
pub fn simplify(v: &[V2]) -> Vec<V2> {
    let mut p: Vec<V2> = Vec::new();
    for q in v {
        if let Some(l) = p.last() {
            if (l[0] - q[0]).abs() < 1e-6 && (l[1] - q[1]).abs() < 1e-6 {
                continue;
            }
        }
        p.push(*q);
    }
    while p.len() > 1 {
        let (a, b) = (p[0], p[p.len() - 1]);
        if (a[0] - b[0]).abs() < 1e-6 && (a[1] - b[1]).abs() < 1e-6 {
            p.pop();
        } else {
            break;
        }
    }
    let mut changed = true;
    while changed && p.len() > 3 {
        changed = false;
        let n = p.len();
        for i in 0..n {
            let (a, b, c) = (p[(i + n - 1) % n], p[i], p[(i + 1) % n]);
            let cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
            let l = ((c[0] - a[0]).powi(2) + (c[1] - a[1]).powi(2)).sqrt();
            if l == 0.0 || (cr / l).abs() < 1e-3 {
                // b is on the line from a to c (and between them, or a spike)
                p.remove(i);
                changed = true;
                break;
            }
        }
    }
    p
}

/// A loop the way the project keeps it: counter-clockwise (clockwise for a hole), from its
/// lowest point (the leftmost of the lowest), without points on straight runs.
pub fn canonical(v: &[V2], hole: bool) -> Vec<V2> {
    let mut p = simplify(v);
    if p.len() < 3 {
        return p;
    }
    let ccw = area(&p) > 0.0;
    if ccw == hole {
        p.reverse();
    }
    let mut k = 0;
    for i in 1..p.len() {
        if p[i][1] < p[k][1] || (p[i][1] == p[k][1] && p[i][0] < p[k][0]) {
            k = i;
        }
    }
    p.rotate_left(k);
    p
}

pub fn pts_value(v: &[V2]) -> Value {
    Value::Arr(v.iter().map(|p| Value::Arr(vec![Value::f(r3z(p[0])), Value::f(r3z(p[1]))])).collect())
}

/// Rounds a loop's points to a thousandth of a millimetre (what the project keeps).
pub fn round_loop(v: &[V2]) -> Vec<V2> {
    v.iter().map(|p| [r3(p[0]), r3(p[1])]).collect()
}

// ---------------------------------------------------------------- a slab's top

/// What a slab's body says of it.
#[derive(Clone, Debug)]
pub struct Top {
    pub outer: Vec<V2>,
    pub holes: Vec<Vec<V2>>,
    /// The top's plane (a point and its upward normal) when it is one plane.
    pub plane: Option<(V3, V3)>,
    /// The top's vertices (for a shaped top: its points), and its fold lines.
    pub verts: Vec<V3>,
    pub folds: Vec<(V3, V3)>,
    pub z_top: f64,
    pub z_bottom: f64,
    /// The thickness square to the top.
    pub thickness: f64,
}

fn key(p: V3) -> (i64, i64) {
    ((p[0] * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64)
}

/// A point of the top in plan, to the micrometre (faces of a top meet in plan even where the
/// file's slabs are not quite at one height there).
fn key3(p: V3) -> (i64, i64, i64) {
    ((p[0] * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64, 0)
}

/// The plane of a face: its unit normal and its offset (n·p).
/// A face's plane: its normal, and its distance along it from `r` (a point near the body, so
/// that a body far from the origin keeps its precision).
fn plane_of(pts: &[V3], r: V3) -> (V3, f64) {
    let n = face_normal(pts);
    let mut c = [0.0; 3];
    for p in pts {
        c = geom::add(c, geom::sub(*p, r));
    }
    let c = geom::mul(c, 1.0 / pts.len() as f64);
    (n, geom::dot(n, c))
}

/// An edge split at the corners that lie on it (in space, within a hundredth of a millimetre).
fn split_edge(a: V3, b: V3, corners: &[V3]) -> Vec<(V3, V3)> {
    let d = [b[0] - a[0], b[1] - a[1], 0.0];
    let l2 = geom::dot(d, d);
    let mut on: Vec<(f64, V3)> = Vec::new();
    if l2 > 0.0 {
        for p in corners {
            let dp = [p[0] - a[0], p[1] - a[1], 0.0];
            let t = geom::dot(dp, d) / l2;
            if t <= 1e-9 || t >= 1.0 - 1e-9 {
                continue;
            }
            let q = [a[0] + d[0] * t, a[1] + d[1] * t];
            if ((p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2)).sqrt() < 0.01 {
                // the point on this edge, at the edge's own height there
                let z = a[2] + (b[2] - a[2]) * t;
                on.push((t, [p[0], p[1], z]));
            }
        }
    }
    if on.is_empty() {
        return vec![(a, b)];
    }
    on.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut out = Vec::new();
    let mut cur = a;
    for (_, p) in on {
        out.push((cur, p));
        cur = p;
    }
    out.push((cur, b));
    out
}

/// Chains directed edges into loops.
fn chain(edges: &[(V3, V3)]) -> Vec<Vec<V3>> {
    let mut left: Vec<(V3, V3)> = edges.to_vec();
    let mut loops = Vec::new();
    while let Some(first) = left.first().copied() {
        left.remove(0);
        let mut lp = vec![first.0];
        let mut cur = first.1;
        let start = key3(first.0);
        let mut guard = 0;
        while key3(cur) != start && guard < 100000 {
            guard += 1;
            lp.push(cur);
            match left.iter().position(|(a, _)| key3(*a) == key3(cur)) {
                Some(i) => {
                    let (_, b) = left.remove(i);
                    cur = b;
                }
                None => break,
            }
        }
        if lp.len() >= 3 {
            loops.push(lp);
        }
    }
    loops
}

/// Whether a face looking up lies under another: within it in plan, nowhere above it (and,
/// where the two are one, the later of them).
fn covered(i: usize, ups: &[(&Vec<V3>, Vec<Vec<V3>>, (V3, f64))], r: V3) -> bool {
    let f = ups[i].0;
    for (j, g) in ups.iter().enumerate() {
        if j == i {
            continue;
        }
        let (n, d) = g.2;
        if n[2] <= 1e-9 {
            continue;
        }
        let poly: Vec<V2> = g.0.iter().map(|p| [p[0], p[1]]).collect();
        let mut under = true;
        let mut below = false;
        for p in f.iter() {
            if !holds(&poly, [p[0], p[1]]) {
                under = false;
                break;
            }
            let z = r[2] + (d - n[0] * (p[0] - r[0]) - n[1] * (p[1] - r[1])) / n[2];
            if p[2] > z + 1e-3 {
                under = false;
                break;
            }
            if p[2] < z - 1e-3 {
                below = true;
            }
        }
        if under && (below || j < i) {
            return true;
        }
    }
    false
}

/// Whether a point lies in a polygon in plan, or on its edge (to a hundredth of a millimetre).
fn holds(poly: &[V2], p: V2) -> bool {
    let n = poly.len();
    for i in 0..n {
        let (a, b) = (poly[i], poly[(i + 1) % n]);
        let d = [b[0] - a[0], b[1] - a[1]];
        let l2 = d[0] * d[0] + d[1] * d[1];
        if l2 > 0.0 {
            let t = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2;
            if (-1e-9..=1.0 + 1e-9).contains(&t) {
                let q = [a[0] + d[0] * t, a[1] + d[1] * t];
                if ((p[0] - q[0]).powi(2) + (p[1] - q[1]).powi(2)).sqrt() < 0.01 {
                    return true;
                }
            }
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

/// A slab's top from its body: an extrusion straight up by its profile, else the faces that
/// look up, their outline and how they fold.
pub fn top(solids: &[Solid]) -> Option<Top> {
    let pts: Vec<V3> = solids.iter().flat_map(|s| s.points().copied().collect::<Vec<_>>()).collect();
    if pts.is_empty() {
        return None;
    }
    let z_top = pts.iter().map(|p| p[2]).fold(f64::NEG_INFINITY, f64::max);
    let z_bottom = pts.iter().map(|p| p[2]).fold(f64::INFINITY, f64::min);
    if solids.len() == 1 {
        if let Some(x) = &solids[0].ext {
            let d = x.tf.dir(x.dir);
            let up = x.tf.dir([0.0, 0.0, 1.0]);
            if d[2].abs() > 1.0 - 1e-9 && up[2].abs() > 1.0 - 1e-9 {
                let tr = |l: &Vec<V2>| -> Vec<V2> {
                    l.iter()
                        .map(|p| {
                            let q = x.tf.apply([p[0], p[1], 0.0]);
                            [q[0], q[1]]
                        })
                        .collect()
                };
                return Some(Top {
                    outer: tr(&x.outer),
                    holes: x.holes.iter().map(tr).collect(),
                    plane: Some(([0.0, 0.0, z_top], [0.0, 0.0, 1.0])),
                    verts: Vec::new(),
                    folds: Vec::new(),
                    z_top,
                    z_bottom,
                    thickness: z_top - z_bottom,
                });
            }
        }
    }
    // the faces that look up
    let mut ups: Vec<(&Vec<V3>, Vec<Vec<V3>>, (V3, f64))> = Vec::new();
    let mut downs: Vec<(V3, f64)> = Vec::new();
    let r = pts[0];
    for s in solids {
        for f in &s.faces {
            if f.outer.len() < 3 {
                continue;
            }
            let pl = plane_of(&f.outer, r);
            if pl.0[2] > 1e-6 {
                ups.push((&f.outer, f.holes.clone(), pl));
            } else if pl.0[2] < -1e-6 {
                downs.push(pl);
            }
        }
    }
    if ups.is_empty() {
        return None;
    }
    // the top's corners are every face's; its outline and folds the faces' not under another
    // (a layer under the top, or a face inside the body)
    let all_ups = ups.clone();
    let hidden: Vec<bool> = (0..ups.len()).map(|i| covered(i, &ups, r)).collect();
    let mut k = 0;
    ups.retain(|_| {
        k += 1;
        !hidden[k - 1]
    });
    // each face's edges, split where another face's corner lies on them
    let mut corners: Vec<V3> = Vec::new();
    {
        let mut seen: std::collections::BTreeSet<(i64, i64, i64)> = std::collections::BTreeSet::new();
        for (outer, holes, _) in &ups {
            for p in outer.iter().chain(holes.iter().flatten()) {
                if seen.insert(key3(*p)) {
                    corners.push(*p);
                }
            }
        }
    }
    let face_edges: Vec<Vec<(V3, V3)>> = ups
        .iter()
        .map(|(outer, holes, _)| {
            let mut out = Vec::new();
            let mut rings: Vec<&Vec<V3>> = vec![*outer];
            for h in holes {
                rings.push(h);
            }
            for r in rings {
                let n = r.len();
                for i in 0..n {
                    let (a, b) = (r[i], r[(i + 1) % n]);
                    if key3(a) == key3(b) {
                        continue;
                    }
                    out.extend(split_edge(a, b, &corners));
                }
            }
            out
        })
        .collect();
    // edges of the top: used once, the outline; twice, inside it
    let mut count: BTreeMap<((i64, i64, i64), (i64, i64, i64)), (V3, V3, usize, usize)> = BTreeMap::new();
    let mut order: Vec<((i64, i64, i64), (i64, i64, i64))> = Vec::new();
    for (fi, es) in face_edges.iter().enumerate() {
        for (a, b) in es {
            let (ka, kb) = (key3(*a), key3(*b));
            let k = if ka <= kb { (ka, kb) } else { (kb, ka) };
            match count.get_mut(&k) {
                Some(e) => {
                    e.2 += 1;
                    e.3 = fi;
                }
                None => {
                    count.insert(k, (*a, *b, 1, fi));
                    order.push(k);
                }
            }
        }
    }
    let mut outline: Vec<(V3, V3)> = Vec::new();
    let mut inner: Vec<(V3, V3, usize, usize)> = Vec::new();
    for k in &order {
        let e = count[k];
        if e.2 == 1 {
            outline.push((e.0, e.1));
        }
    }
    // inner edges, between faces that are not in one plane (a fold)
    let mut first_face: BTreeMap<((i64, i64, i64), (i64, i64, i64)), usize> = BTreeMap::new();
    for (fi, es) in face_edges.iter().enumerate() {
        for (a, b) in es {
            let (ka, kb) = (key3(*a), key3(*b));
            let k = if ka <= kb { (ka, kb) } else { (kb, ka) };
            first_face.entry(k).or_insert(fi);
        }
    }
    for k in &order {
        let e = count[k];
        if e.2 == 2 {
            let f0 = first_face[k];
            let f1 = e.3;
            inner.push((e.0, e.1, f0, f1));
        }
    }
    let loops = chain(&outline);
    if loops.is_empty() {
        return None;
    }
    let plans: Vec<Vec<V2>> = loops.iter().map(|l| l.iter().map(|p| [p[0], p[1]]).collect()).collect();
    let mut bi = 0;
    for i in 1..plans.len() {
        if area(&plans[i]).abs() > area(&plans[bi]).abs() {
            bi = i;
        }
    }
    let outer = plans[bi].clone();
    let holes: Vec<Vec<V2>> = plans.iter().enumerate().filter(|(i, _)| *i != bi).map(|(_, l)| l.clone()).collect();
    // one plane?
    let p0 = ups[0].2;
    let same = |a: &(V3, f64), b: &(V3, f64)| -> bool {
        (a.0[0] - b.0[0]).abs() < 1e-6 && (a.0[1] - b.0[1]).abs() < 1e-6 && (a.0[2] - b.0[2]).abs() < 1e-6 && (a.1 - b.1).abs() < 1e-3
    };
    let planar = ups.iter().all(|u| same(&u.2, &p0));
    let mut folds = Vec::new();
    for (a, b, f0, f1) in &inner {
        if !same(&ups[*f0].2, &ups[*f1].2) {
            folds.push((*a, *b));
        }
    }
    let mut verts: Vec<V3> = Vec::new();
    let mut seen: Vec<(i64, i64, i64)> = Vec::new();
    for (outer, holes, _) in &all_ups {
        for p in outer.iter().chain(holes.iter().flatten()) {
            if !seen.contains(&key3(*p)) {
                seen.push(key3(*p));
                verts.push(*p);
            }
        }
    }
    // the thickness square to the top: to the plane of the faces looking down
    let thickness = if planar {
        let n = p0.0;
        let mut best: Option<f64> = None;
        for d in &downs {
            if (d.0[0] + n[0]).abs() < 1e-6 && (d.0[1] + n[1]).abs() < 1e-6 && (d.0[2] + n[2]).abs() < 1e-6 {
                // d.0 = -n: distance between n·p = p0.1 and -n·p = d.1
                let t = p0.1 + d.1;
                if best.map(|b| t > b).unwrap_or(true) {
                    best = Some(t);
                }
            }
        }
        best.unwrap_or(z_top - z_bottom)
    } else {
        // a shaped top: straight down at its outline
        let mut t = z_top - z_bottom;
        if let Some(v) = loops.get(bi).and_then(|l| l.first()) {
            let below = pts.iter().filter(|p| key(**p) == key(*v)).map(|p| p[2]).fold(f64::INFINITY, f64::min);
            if below.is_finite() {
                t = v[2] - below;
            }
        }
        t
    };
    let plane = if planar {
        let n = p0.0;
        Some((loops[bi][0], n))
    } else {
        None
    };
    Some(Top { outer, holes, plane, verts, folds, z_top, z_bottom, thickness })
}

/// A floor's or roof's sloped top: its slope in degrees, and its arrow (from the boundary's
/// lowest point, the first of them, uphill across all of it) and the height at the arrow's
/// tail.
pub fn slope_arrow(outer: &[V2], plane: (V3, V3)) -> Option<(f64, [V2; 2], f64)> {
    let (p, n) = plane;
    let h = (n[0] * n[0] + n[1] * n[1]).sqrt();
    if h < 1e-9 {
        return None;
    }
    let g = [-n[0] / h, -n[1] / h];
    let slope = (h / n[2]).atan().to_degrees();
    let proj = |q: &V2| q[0] * g[0] + q[1] * g[1];
    let mut lo = 0;
    for i in 1..outer.len() {
        if proj(&outer[i]) < proj(&outer[lo]) - 1e-9 {
            lo = i;
        }
    }
    let hi = outer.iter().map(proj).fold(f64::NEG_INFINITY, f64::max);
    let tail = outer[lo];
    let len = hi - proj(&tail);
    let head = [tail[0] + g[0] * len, tail[1] + g[1] * len];
    // the top's height at the tail
    let z = p[2] - (n[0] * (tail[0] - p[0]) + n[1] * (tail[1] - p[1])) / n[2];
    Some((slope, [tail, head], z))
}

// ---------------------------------------------------------------- floors

fn is_roof_slab(ctx: &Ctx, id: u64) -> bool {
    let e = match ctx.m.get(id) {
        Some(e) => e,
        None => return false,
    };
    let pt = e.p(8).enm().unwrap_or("");
    if pt == "ROOF" {
        return true;
    }
    if let Some(p) = ctx.m.parent.get(&id) {
        let c = ctx.m.class(*p);
        if c == "IFCROOF" || c == "IFCSTAIR" || c == "IFCRAMP" {
            return true;
        }
    }
    if let Some(t) = ctx.m.type_of.get(&id).and_then(|t| ctx.m.get(*t)) {
        if t.name == "IFCSLABTYPE" && t.p(9).enm() == Some("ROOF") && pt != "FLOOR" && pt != "BASESLAB" {
            return true;
        }
    }
    false
}

pub fn floors(ctx: &mut Ctx) {
    let mut ids: Vec<u64> = Vec::new();
    for c in ["IFCSLAB", "IFCSLABSTANDARDCASE", "IFCSLABELEMENTEDCASE"] {
        ids.extend_from_slice(ctx.m.of(c));
    }
    ids.sort();
    for id in ids {
        if is_roof_slab(ctx, id) {
            continue;
        }
        floor(ctx, id);
    }
}

/// Roofs come in before the shafts; the shafts look at them through this.
pub fn is_host(ctx: &Ctx, id: u64) -> bool {
    ctx.slabs.hosts.contains_key(&id)
}

/// Whether a product's `Pset_*Common` says it carries load.
pub fn load_bearing(ctx: &Ctx, id: u64, set: &str) -> bool {
    ctx.m.prop(id, set, "LoadBearing").and_then(|p| p.boolean()).unwrap_or(false)
}

/// A slab type's layers (from its usage, its own set or its type's), where they make up its
/// thickness.
fn slab_layers(ctx: &mut Ctx, id: u64, thickness: f64) -> Option<Value> {
    let pick = |ctx: &Ctx, x: u64| -> Option<u64> {
        let mid = *ctx.m.material_of.get(&x)?;
        let e = ctx.m.get(mid)?;
        match e.name.as_str() {
            "IFCMATERIALLAYERSET" => Some(mid),
            "IFCMATERIALLAYERSETUSAGE" => e.p(0).r(),
            _ => None,
        }
    };
    let set = pick(ctx, id).or_else(|| ctx.m.type_of.get(&id).copied().and_then(|t| pick(ctx, t)))?;
    let ls = import_types::layers(ctx, set, r3(thickness))?;
    Some(Value::Arr(ls.into_iter().map(import_types::with_part_id).collect()))
}

fn floor(ctx: &mut Ctx, id: u64) {
    let solids = geom::body(&ctx.m, id);
    let t = match top(&solids) {
        Some(t) => t,
        None => {
            ctx.skip(id, "it has no body BIMCraft can read");
            return;
        }
    };
    // its level: the one its top is at, else its storey's, else the one under its top
    let level = match ctx.levels.iter().position(|l| (l.elevation - t.z_top).abs() < 1e-3) {
        Some(i) => i,
        None => ctx.level_of(id, t.z_top),
    };
    let lev = ctx.levels[level].elevation;
    let outer = canonical(&t.outer, false);
    let holes: Vec<Vec<V2>> = t.holes.iter().map(|h| canonical(h, true)).collect();
    let thickness = super::import_build::r2(t.thickness);
    let base_name = import_types::file_type_name(ctx, id).unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
    let mut tv = crate::jobj! {"thickness" => thickness};
    if let Some(ls) = slab_layers(ctx, id, thickness) {
        tv.set("layers", ls);
    }
    let tname = import_types::register(ctx, "floor", &base_name, tv);
    let tguid = ctx.type_guid("floor", &tname);
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("floor"));
    m.insert("type", Value::s(&tguid));
    m.insert("level", ctx.level_guid(level));
    m.insert("boundary", pts_value(&outer));
    if !holes.is_empty() {
        m.insert("openings", Value::Arr(holes.iter().map(|h| pts_value(h)).collect()));
    }
    let mut shape: Option<Value> = None;
    match t.plane {
        Some(pl) if pl.1[2] < 1.0 - 1e-9 => {
            if let Some((slope, arrow, z)) = slope_arrow(&outer, pl) {
                let off = r3(z - lev);
                if off != 0.0 {
                    m.insert("offset", Value::f(off));
                }
                m.insert("slope", Value::f(r6(slope)));
                m.insert("arrow", pts_value(&arrow));
            }
        }
        Some(_) => {
            let off = r3(t.z_top - lev);
            if off != 0.0 {
                m.insert("offset", Value::f(off));
            }
        }
        None => {
            let off = r3(t.z_top - lev);
            if off != 0.0 {
                m.insert("offset", Value::f(off));
            }
            shape = Some(shape_value(&t, &outer, &holes));
        }
    }
    if load_bearing(ctx, id, "Pset_SlabCommon") {
        m.insert("structural", Value::Bool(true));
    }
    if let Some(s) = shape {
        m.insert("shape", s);
    }
    let pid = ctx.add(id, Value::Obj(m));
    ctx.slabs.hosts.insert(id, pid);
    if let Some(mk) = import_types::mark_of(ctx, id, &base_name) {
        ctx.structure.marks.push((id, "floor".to_string(), mk));
    }
}

/// A shaped top as the project keeps it: its points that are not on the top's plane at the
/// highest, or that lie inside its outline, and its fold lines.
pub fn shape_value(t: &Top, outer: &[V2], holes: &[Vec<V2>]) -> Value {
    let on_loop = |p: V2| -> bool {
        let rk = (((p[0]) * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64);
        outer.iter().chain(holes.iter().flatten()).any(|q| ((q[0] * 1000.0).round() as i64, (q[1] * 1000.0).round() as i64) == rk)
    };
    let mut points = Vec::new();
    for v in &t.verts {
        let dz = r3z(v[2] - t.z_top);
        let corner = on_loop([v[0], v[1]]);
        if corner && dz == 0.0 {
            continue;
        }
        points.push(crate::jobj! {
            "id" => 0u64,
            "guid" => crate::rand::guid(),
            "at" => Value::Arr(vec![Value::f(r3(v[0])), Value::f(r3(v[1]))]),
            "z" => dz,
        });
    }
    // the fold lines, ordered by their ends
    let mut lines: Vec<((i64, i64), (i64, i64), V3, V3)> = Vec::new();
    for (a, b) in &t.folds {
        let (ka, kb) = (key(*a), key(*b));
        let (k0, k1) = if ka <= kb { (ka, kb) } else { (kb, ka) };
        lines.push((k0, k1, *a, *b));
    }
    lines.sort_by(|x, y| (x.0, x.1).cmp(&(y.0, y.1)));
    let lines: Vec<Value> = lines
        .into_iter()
        .map(|(_, _, a, b)| {
            crate::jobj! {
                "id" => 0u64,
                "guid" => crate::rand::guid(),
                "a" => Value::Arr(vec![Value::f(r3(a[0])), Value::f(r3(a[1]))]),
                "b" => Value::Arr(vec![Value::f(r3(b[0])), Value::f(r3(b[1]))]),
            }
        })
        .collect();
    let mut m = Map::new();
    m.insert("points", Value::Arr(points));
    if !lines.is_empty() {
        m.insert("lines", Value::Arr(lines));
    }
    Value::Obj(m)
}

// ---------------------------------------------------------------- ceilings

fn is_ceiling(ctx: &Ctx, id: u64) -> bool {
    let e = match ctx.m.get(id) {
        Some(e) => e,
        None => return false,
    };
    let pt = e.p(8).enm().unwrap_or("");
    if pt == "CEILING" {
        return true;
    }
    if pt == "NOTDEFINED" || pt == "USERDEFINED" || pt.is_empty() {
        if let Some(t) = ctx.m.type_of.get(&id).and_then(|t| ctx.m.get(*t)) {
            return t.p(9).enm() == Some("CEILING");
        }
    }
    false
}

pub fn ceilings(ctx: &mut Ctx) {
    let ids: Vec<u64> = ctx.m.of("IFCCOVERING").to_vec();
    for id in ids {
        if !is_ceiling(ctx, id) {
            continue;
        }
        ceiling(ctx, id);
    }
}

fn ceiling(ctx: &mut Ctx, id: u64) {
    let solids = geom::body(&ctx.m, id);
    let t = match top(&solids) {
        Some(t) => t,
        None => {
            ctx.skip(id, "it has no body BIMCraft can read");
            return;
        }
    };
    let level = ctx.level_of(id, t.z_bottom);
    let lev = ctx.levels[level].elevation;
    let outer = canonical(&t.outer, false);
    let holes: Vec<Vec<V2>> = t.holes.iter().map(|h| canonical(h, true)).collect();
    let thickness = super::import_build::r2(t.z_top - t.z_bottom);
    let tname = import_types::file_type_name(ctx, id).unwrap_or_else(|| format!("Imported - {}mm", num_name(thickness)));
    // the grid is the project's type's, where it has one of that name
    let grid = super::import_build::type_value(&ctx.pr, "ceiling", &tname).and_then(|t| t.get("grid")).and_then(|g| g.as_f64()).unwrap_or(0.0);
    let mut tv = crate::jobj! {"thickness" => thickness, "grid" => grid};
    if let Some(ls) = slab_layers(ctx, id, thickness) {
        tv.set("layers", ls);
    }
    let tname = import_types::register(ctx, "ceiling", &tname, tv);
    let tguid = ctx.type_guid("ceiling", &tname);
    let g = ctx.guid_for(id);
    let mut m = Map::new();
    m.insert("guid", Value::s(&g));
    m.insert("category", Value::s("ceiling"));
    m.insert("type", Value::s(&tguid));
    m.insert("level", ctx.level_guid(level));
    m.insert("boundary", pts_value(&outer));
    if !holes.is_empty() {
        m.insert("openings", Value::Arr(holes.iter().map(|h| pts_value(h)).collect()));
    }
    m.insert("offset", Value::f(r3(t.z_bottom - lev)));
    let pid = ctx.add(id, Value::Obj(m));
    ctx.slabs.hosts.insert(id, pid);
}

// ---------------------------------------------------------------- shafts

pub fn shafts(ctx: &mut Ctx) {
    // the openings that void floors, ceilings and roofs, one shaft for each that are the same
    let mut seen: Vec<(Vec<(i64, i64)>, i64, i64)> = Vec::new();
    let ids: Vec<u64> = ctx.m.of("IFCOPENINGELEMENT").to_vec();
    for id in ids {
        let host = match ctx.m.voided.get(&id) {
            Some(h) => *h,
            None => continue,
        };
        let hosted = ctx.slabs.hosts.contains_key(&host) || ctx.made.get(&host).map(|m| m.cat == "roof").unwrap_or(false);
        if !hosted {
            continue;
        }
        if ctx.m.filled_by.contains_key(&id) {
            continue;
        }
        ctx.handled.insert(id);
        let solids = geom::body(&ctx.m, id);
        let t = match top(&solids) {
            Some(t) => t,
            None => continue,
        };
        let outer = round_loop(&canonical(&t.outer, false));
        let k: Vec<(i64, i64)> = outer.iter().map(|p| ((p[0] * 1000.0).round() as i64, (p[1] * 1000.0).round() as i64)).collect();
        let (zb, zt) = ((r3(t.z_bottom) * 1000.0).round() as i64, (r3(t.z_top) * 1000.0).round() as i64);
        if seen.iter().any(|s| s.0 == k && s.1 == zb && s.2 == zt) {
            continue;
        }
        seen.push((k, zb, zt));
        let level = ctx.level_at(t.z_bottom);
        let lev = ctx.levels[level].elevation;
        let top_level = ctx.level_at_top(level, t.z_top);
        let g = ctx.guid_for(id);
        let v = crate::jobj! {
            "guid" => g.as_str(),
            "category" => "shaft",
            "level" => ctx.level_guid(level),
            "boundary" => pts_value(&outer),
            "top_level" => match top_level { Some(i) => ctx.level_guid(i), None => Value::Null },
            "height" => r3(t.z_top - t.z_bottom),
            "base_offset" => r3(t.z_bottom - lev),
        };
        ctx.add(id, v);
    }
}
