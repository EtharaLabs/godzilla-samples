//! Roofs: by footprint (given, sketched, or over the walls of the level below, past their faces by
//! the overhang, round their courtyards), sloped edge by edge with gables, or by extrusion; and the
//! model's rules for roofs.

use super::slabs::{clean, de_rings, opt_boundary, opt_openings};
use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub const ORDER: &[&str] = &[
    "type",
    "level",
    "boundary",
    "courtyards",
    "slope",
    "slopes",
    "overhang",
    "gable",
    "gables",
    "offset",
    "openings",
    "join",
    "extrusion",
    "sketch",
    "shape",
    "params",
];

/// The two ends of a line as serde reads `[P2; 2]`.
fn de_p2_pair(v: &Value) -> Result<Vec<P2>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected an array of length 2", v.kind_name()));
    };
    let mut out = Vec::with_capacity(2);
    for i in 0..2 {
        match a.get(i) {
            Some(q) => out.push(super::slabs::de_p2(q)?),
            None => return Err(format!("invalid length {}, expected an array of length 2", i)),
        }
    }
    if a.len() > 2 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

fn de_f64(x: &Value) -> Result<f64, String> {
    match x {
        Value::Num(n) => Ok(n.as_f64()),
        o => Err(format!("invalid type: {}, expected f64", o.kind_name())),
    }
}

/// An extrusion as serde reads `Extrusion {line: [P2; 2], profile: Vec<P2>, from (default 0),
/// to}`, from a map or a sequence of its fields in order.
pub fn de_extrusion(v: &Value) -> Result<Value, String> {
    let mut line = None;
    let mut profile = None;
    let mut from = None;
    let mut to = None;
    match v {
        Value::Obj(m) => {
            for (k, x) in &m.items {
                match k.as_str() {
                    "line" => line = Some(de_p2_pair(x)?),
                    "profile" => profile = Some(super::slabs::de_points(x)?),
                    "from" => from = Some(de_f64(x)?),
                    "to" => to = Some(de_f64(x)?),
                    other => return Err(format!("unknown field `{}`, expected one of `line`, `profile`, `from`, `to`", other)),
                }
            }
        }
        Value::Arr(a) => {
            let short = |i: usize| format!("invalid length {}, expected struct Extrusion with 4 elements", i);
            line = Some(de_p2_pair(a.first().ok_or_else(|| short(0))?)?);
            profile = Some(super::slabs::de_points(a.get(1).ok_or_else(|| short(1))?)?);
            if let Some(x) = a.get(2) {
                from = Some(de_f64(x)?);
            }
            to = Some(de_f64(a.get(3).ok_or_else(|| short(3))?)?);
            if a.len() > 4 {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
        }
        _ => return Err(format!("invalid type: {}, expected struct Extrusion", v.kind_name())),
    }
    let line = line.ok_or_else(|| "missing field `line`".to_string())?;
    let profile = profile.ok_or_else(|| "missing field `profile`".to_string())?;
    let to = to.ok_or_else(|| "missing field `to`".to_string())?;
    Ok(jobj! {
        "line" => ring_v(&line),
        "profile" => ring_v(&profile),
        "from" => from.unwrap_or(0.0),
        "to" => to,
    })
}

fn de_usizes(v: &Value) -> Result<Vec<u64>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::new();
    for x in a {
        match x {
            Value::Num(crate::json::Num::U(u)) => out.push(*u),
            Value::Num(crate::json::Num::I(i)) => return Err(format!("invalid value: integer `{}`, expected usize", i)),
            o => return Err(format!("invalid type: {}, expected usize", o.kind_name())),
        }
    }
    Ok(out)
}

fn de_f64s(v: &Value) -> Result<Vec<f64>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::new();
    for x in a {
        match x {
            Value::Num(n) => out.push(n.as_f64()),
            o => return Err(format!("invalid type: {}, expected f64", o.kind_name())),
        }
    }
    Ok(out)
}

/// The footprint of the walls of a level, `extra` past their faces, and its courtyards: the outline
/// counter-clockwise from its lowest corner, each courtyard clockwise from its lowest.
pub fn wall_footprint(pr: &Project, level: u64, extra: f64) -> Option<(Vec<P2>, Vec<Vec<P2>>)> {
    let o = super::outline::level_outline(pr, level)?;
    let walls = super::outline::level_walls(pr, level);
    let mut half = Vec::new();
    for (w, pieces) in walls.iter().zip(super::walls::joined_centres(&walls)) {
        for _ in pieces {
            half.push(w.thickness / 2.0);
        }
    }
    let g = &o.graph;
    // the original grows the whole outline by the thickest wall's half, whichever wall an edge is
    let widest = half.iter().cloned().fold(0.0, f64::max);
    let dist_of = |_a: usize, _b: usize| -> f64 { widest + extra };
    // the outline: the outer face (clockwise) moved outward is the left of the reversed ring
    let ring_ids: Vec<usize> = o.faces[o.outer].ring.iter().rev().copied().collect();
    let ring = g.pts(&ring_ids);
    let n = ring_ids.len();
    let ds: Vec<f64> = (0..n).map(|i| -dist_of(ring_ids[i], ring_ids[(i + 1) % n])).collect();
    let moved = geom::offset::offset_ring_ends(&ring, &ds, false);
    let boundary = round3(&geom::start_lowest(&super::outline::drop_collinear(&moved)));
    // courtyards: the loops the floor is open over, moved in by their faces and the overhang
    let mut courtyards = Vec::new();
    let parts = g.parts();
    let main_part = parts[o.faces[o.outer].ring[0]];
    let rooms = super::outline::room_points(pr, level);
    let outline_pts: Vec<P2> = ring.clone();
    let mut taken: Vec<Vec<P2>> = Vec::new();
    for (i, f) in o.faces.iter().enumerate() {
        if i == o.outer || f.area >= 0.0 || parts[f.ring[0]] == main_part {
            continue;
        }
        let pts = g.pts(&f.ring);
        if !pts.iter().all(|p| geom::inside(&outline_pts, *p)) {
            continue;
        }
        if taken.iter().any(|t| geom::inside_raw(t, pts[0])) {
            continue;
        }
        let region: Vec<P2> = pts.iter().rev().copied().collect();
        if rooms.iter().any(|r| geom::inside(&region, *r)) {
            continue;
        }
        taken.push(pts.clone());
        let m = f.ring.len();
        let ds: Vec<f64> = (0..m).map(|k| -dist_of(f.ring[k], f.ring[(k + 1) % m])).collect();
        let moved = geom::offset::offset_ring_ends(&pts, &ds, false);
        courtyards.push(round3(&geom::start_lowest(&super::outline::drop_collinear(&moved))));
    }
    Some((boundary, courtyards))
}

/// Points rounded to a thousandth of a millimetre, as a roof's footprint over walls is kept.
pub fn round3(r: &[P2]) -> Vec<P2> {
    r.iter().map(|p| [(p[0] * 1000.0).round() / 1000.0, (p[1] * 1000.0).round() / 1000.0]).collect()
}

pub fn cmd_roof(s: &mut Session, p: &Value) -> R<Value> {
    let c = "roof";
    let pr = &s.project;
    let level_given = params::get(p, "level").is_some();
    let level = match params::get(p, "level") {
        Some(v) => crate::model::resolve_level(pr, c, "level", v)?,
        None => {
            let ls = crate::model::levels(pr);
            match ls.get(1).or(ls.first()) {
                Some(l) => *l,
                None => return Err("roof: the project has no level".into()),
            }
        }
    };
    let ty = params::opt_text(p, c, "type")?;
    let extrusion = match params::get(p, "extrusion") {
        None => None,
        Some(v) => Some(de_extrusion(v).map_err(|e| {
            format!("roof: `extrusion` is {{line: [[x,y],[x,y]], profile: [[along, up],…], from?, to}}: {}", e)
        })?),
    };
    let mut sketch = super::slabs::sketch_lines(p, c)?;
    let overhang = params::opt_num(p, c, "overhang")?;
    let boundary = opt_boundary(p, c, "boundary")?;
    // with no outline given, the walls of the level below, found before the rest is read
    let over_walls = if extrusion.is_none() && sketch.is_none() && boundary.is_none() {
        let ls = crate::model::levels(pr);
        let i = ls.iter().position(|l| *l == level).unwrap_or(0);
        if i == 0 {
            return Err(format!("roof: {} has no level below to roof over; give `boundary`", level_name(pr, level)));
        }
        let below = ls[i - 1];
        let hang = overhang.unwrap_or(500.0);
        let Some(fp) = wall_footprint(pr, below, hang) else {
            return Err(format!("roof: no walls enclose an area on {}; give `boundary`", level_name(pr, below)));
        };
        Some((fp, hang))
    } else {
        None
    };
    let courtyards = opt_openings(p, c, "courtyards")?;
    let slope = params::opt_num(p, c, "slope")?;
    let gable = params::opt_bool(p, c, "gable")?;
    let gables = match params::get(p, "gables") {
        None => None,
        Some(v) => Some(de_usizes(v).map_err(|e| format!("roof: `gables` is a list of edge numbers: {}", e))?),
    };
    let slopes = match params::get(p, "slopes") {
        None => None,
        Some(v) => Some(de_f64s(v).map_err(|e| format!("roof: `slopes` is a list of degrees, one for each edge: {}", e))?),
    };
    let offset = params::opt_num(p, c, "offset")?;
    let openings = match params::get(p, "openings") {
        None => None,
        Some(v) => Some(de_rings(v).map_err(|e| format!("roof: `openings` is a list of outlines [[[x,y],…],…]: {}", e))?),
    };
    let join = opt_ref(p, c, "join")?;
    let ty = ty.or_else(|| default_type(pr, c)).ok_or_else(|| "roof: the model has no types for this".to_string())?;
    if sketch.is_some() && (boundary.is_some() || courtyards.is_some()) {
        return Err("roof: give the outline as `sketch` or `boundary` (with `courtyards`), not both".into());
    }
    let mut sketch_v: Option<()> = None;
    let mut from_walls = false;
    let mut line_slopes: Option<Vec<f64>> = None;
    let (outline, yards, hang): (Option<Vec<P2>>, Vec<Vec<P2>>, f64) = if extrusion.is_some() {
        (None, Vec::new(), overhang.unwrap_or(0.0))
    } else if let Some(lines) = sketch.as_mut() {
        let r = crate::geom::sketch::solve_region(lines).map_err(|e| format!("{}: {}", c, e))?;
        sketch_v = Some(());
        line_slopes = sketch_slopes(lines, &r);
        (Some(r.outline), r.holes, overhang.unwrap_or(0.0))
    } else if let Some(b) = boundary {
        let y: Vec<Vec<P2>> = courtyards.clone().unwrap_or_default().iter().map(|r| clean(r)).collect();
        (Some(clean(&b)), y, overhang.unwrap_or(0.0))
    } else {
        // over the walls of the level below
        let ((b, y), hang) = over_walls.unwrap();
        from_walls = true;
        let y = match &courtyards {
            Some(given) => given.iter().map(|r| clean(r)).collect(),
            None => y,
        };
        (Some(b), y, hang)
    };
    let _ = level_given;
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "type" => type_ref(pr, c, &ty),
        "level" => level_guid(pr, level),
    };
    if let Some(o) = &outline {
        e.set("boundary", ring_v(o));
    }
    if !yards.is_empty() {
        e.set("courtyards", rings_v(&yards));
    }
    let slope_v = slope.unwrap_or(if extrusion.is_some() { 0.0 } else { 30.0 });
    e.set("slope", Value::f(slope_v));
    let slopes = slopes.or(line_slopes);
    if let Some(sl) = &slopes {
        if !sl.is_empty() {
            e.set("slopes", Value::Arr(sl.iter().map(|x| Value::f(*x)).collect()));
        }
    }
    e.set("overhang", Value::f(hang));
    if gable == Some(true) {
        e.set("gable", Value::Bool(true));
    }
    if let Some(gs) = &gables {
        if !gs.is_empty() {
            e.set("gables", Value::Arr(gs.iter().map(|x| Value::u(*x)).collect()));
        }
    }
    e.set("offset", Value::f(offset.unwrap_or(0.0)));
    if let Some(op) = &openings {
        if !op.is_empty() {
            let cl: Vec<Vec<P2>> = op.iter().map(|r| clean(r)).collect();
            e.set("openings", rings_v(&cl));
        }
    }
    if let Some(j) = &join {
        e.set("join", ref_value(pr, j));
    }
    if let Some(x) = extrusion {
        e.set("extrusion", x);
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    if sketch_v.is_some() {
        let v = crate::geom::sketch::to_value(&mut s.project, sketch.as_ref().unwrap(), &[]);
        e.set("sketch", strip_slopes(v));
    }
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    super::edits::note_walls(id, from_walls);
    Ok(jobj! {"id" => id})
}

/// The slopes a roof's edges take from its sketch's lines (each edge its line's, 0 for none);
/// None when no line has one.
pub fn sketch_slopes(lines: &[crate::geom::sketch::Line], r: &crate::geom::sketch::Region) -> Option<Vec<f64>> {
    let of = |i: usize| lines[i].fields.get("slope").and_then(|x| x.as_f64());
    if !lines.iter().enumerate().any(|(i, _)| of(i).is_some()) {
        return None;
    }
    let mut out = Vec::new();
    for ring in &r.lines {
        for &li in ring {
            out.push(of(li).unwrap_or(0.0));
        }
    }
    Some(out)
}

/// A roof's sketch as it keeps it: its lines' slopes are the roof's `slopes`, not the sketch's.
pub fn strip_slopes(mut v: Value) -> Value {
    if let Value::Arr(a) = &mut v {
        for l in a.iter_mut() {
            l.remove("slope");
        }
    }
    v
}

/// The roof's edges in all: its boundary's, then its courtyards'.
pub fn edge_count(e: &Value) -> usize {
    let mut n = pts(e, "boundary").map(|b| b.len()).unwrap_or(0);
    for r in rings(e, "courtyards") {
        n += r.len();
    }
    n
}

pub fn check_roof(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_roof_own(pr, id, e)?;
    super::shape::check_shape(pr, id, e)
}

fn check_roof_own(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_type(pr, id, e, "roof")?;
    let has_ext = e.get("extrusion").map(|x| !x.is_null()).unwrap_or(false);
    if !has_ext {
        let boundary = pts(e, "boundary").unwrap_or_default();
        let mut holes = rings(e, "courtyards");
        let ops = rings(e, "openings");
        let _ = &mut holes;
        super::slabs::check_rings("roof", id, &boundary, &[])?;
        for (i, o) in holes.iter().enumerate() {
            if o.len() < 3 || o.len() > 10000 {
                return Err(format!("roof {} courtyard {}: a boundary needs 3 to 10000 points", id, i));
            }
        }
        for (i, o) in ops.iter().enumerate() {
            if o.len() < 3 || o.len() > 10000 {
                return Err(format!("roof {} opening {}: a boundary needs 3 to 10000 points", id, i));
            }
        }
    }
    let slope = numd(e, "slope", 30.0);
    if !(0.0..=75.0).contains(&slope) {
        return Err(format!("roof {}: slope {}° isn't from 0° (flat) to 75°", id, d(slope)));
    }
    let n = edge_count(e);
    if let Some(sl) = e.get("slopes").and_then(|g| g.as_arr()) {
        if !sl.is_empty() && sl.len() != n {
            return Err(format!(
                "roof {}: `slopes` has {} numbers for its {} edges (one for each, the courtyards' after the boundary's; 0 for the roof's slope), or leave it empty",
                id,
                sl.len(),
                n
            ));
        }
        for (i, x) in sl.iter().enumerate() {
            let v = x.as_f64().unwrap_or(0.0);
            if !(0.0..=75.0).contains(&v) {
                return Err(format!("roof {}: edge {}'s slope {}° isn't from 0° (the roof's slope) to 75°", id, i, d(v)));
            }
        }
    }
    let gs: Vec<usize> = e.get("gables").and_then(|g| g.as_arr()).map(|a| a.iter().map(|g| g.as_u64().unwrap_or(0) as usize).collect()).unwrap_or_default();
    for k in &gs {
        if *k >= n {
            return Err(format!("roof {}: gable edge {} isn't one of its {} edges (0 to {})", id, k, n, n.saturating_sub(1)));
        }
    }
    if flag(e, "gable") == Some(true) && !has_ext && rectangle(&pts(e, "boundary").unwrap_or_default()).is_none() {
        return Err(format!(
            "roof {}: `gable` leaves a rectangle's ends upright; over any other footprint, name the edges in `gables`",
            id
        ));
    }
    if !gs.is_empty() && !has_ext && slope > 0.0 && n > 0 {
        let mut set = gs.clone();
        set.sort();
        set.dedup();
        if set.len() >= n {
            return Err(format!("roof {}: none of its edges slopes", id));
        }
    }
    if let Some(j) = e.get("join") {
        if !j.is_null() {
            let ok = by_ref(pr, j)
                .filter(|t| *t != id && pr.category(*t) == Some("roof"))
                .and_then(|t| pr.el(t))
                .map(|r| r.get("join").map(|x| x.is_null()).unwrap_or(true))
                .unwrap_or(false);
            if !ok {
                return Err(format!(
                    "roof {}: it joins element {}, which isn't a roof that joins none",
                    id,
                    ref_word_guid(pr, j)
                ));
            }
        }
    }
    Ok(())
}

/// How a join names its element: by GUID if it names one, else as given.
fn ref_word_guid(pr: &Project, v: &Value) -> String {
    match by_ref(pr, v) {
        Some(id) => pr.guid_of(id).unwrap_or_default(),
        None => match v {
            Value::Str(s) => s.clone(),
            _ => v.to_compact(),
        },
    }
}

// ---------------------------------------------------------------- the roof's faces

/// A slope of a roof by footprint: its ring in plan, the edge it rises from (its number), and the
/// plane of its underside: through the edge's start at the eaves' height `z0`, rising `tan` per mm
/// toward `up` (the edge's inward normal), `slope` degrees.
#[derive(Clone, Debug)]
pub struct Face {
    pub ring: Vec<P2>,
    pub edge: usize,
    pub origin: P2,
    pub z0: f64,
    pub up: P2,
    pub tan: f64,
    pub slope: f64,
}

impl Face {
    pub fn z_at(&self, q: P2) -> f64 {
        crate::arch::hosts::Piece::new(Vec::new(), self.origin, self.z0, self.up, self.tan, 0.0).z_at(q)
    }
}

/// The slope (degrees) edge k rises at: its own, else the roof's.
pub fn edge_slope_deg(e: &Value, k: usize) -> f64 {
    let own = e
        .get("slopes")
        .and_then(|s| s.as_arr())
        .and_then(|a| a.get(k))
        .and_then(|x| x.as_f64())
        .unwrap_or(0.0);
    if own != 0.0 {
        own
    } else {
        numd(e, "slope", 30.0)
    }
}

/// The edges left upright: `gables`, or a rectangle's short ends with `gable` (every edge of the
/// boundary along them).
pub fn gable_edges(e: &Value) -> Vec<usize> {
    if let Some(a) = e.get("gables").and_then(|g| g.as_arr()) {
        if !a.is_empty() {
            return a.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect();
        }
    }
    if flag(e, "gable") == Some(true) {
        let b = pts(e, "boundary").unwrap_or_default();
        if let Some(c) = rectangle(&b) {
            let l0 = geom::dist(c[0], c[1]);
            let l1 = geom::dist(c[1], c[2]);
            let ends: [(P2, P2); 2] = if l0 <= l1 { [(c[0], c[1]), (c[2], c[3])] } else { [(c[1], c[2]), (c[3], c[0])] };
            let n = b.len();
            return (0..n)
                .filter(|&i| {
                    let (p, q) = (b[i], b[(i + 1) % n]);
                    ends.iter().any(|(a, z)| geom::seg_dist(*a, *z, p) < 1e-6 && geom::seg_dist(*a, *z, q) < 1e-6)
                })
                .collect();
        }
    }
    Vec::new()
}

/// The four corners of a boundary that is a rectangle (corners in line dropped), if it is one.
pub fn rectangle(b: &[P2]) -> Option<[P2; 4]> {
    let r = super::outline::drop_collinear(b);
    if r.len() != 4 {
        return None;
    }
    for i in 0..4 {
        let u = geom::unit(geom::sub(r[(i + 1) % 4], r[i]));
        let v = geom::unit(geom::sub(r[(i + 2) % 4], r[(i + 1) % 4]));
        if geom::dot(u, v).abs() > 1e-9 {
            return None;
        }
    }
    Some([r[0], r[1], r[2], r[3]])
}

/// The roof's base: its level's elevation plus its offset.
pub fn roof_base(pr: &Project, e: &Value) -> f64 {
    level_of(pr, e).map(|l| elev(pr, l)).unwrap_or(0.0) + numd(e, "offset", 0.0)
}

/// The height of the roof's eaves: its base, `overhang` out from where the slope reaches it.
pub fn eave_height(pr: &Project, e: &Value) -> f64 {
    let slope = numd(e, "slope", 30.0);
    roof_base(pr, e) - numd(e, "overhang", 0.0) * slope.to_radians().tan()
}

/// The slopes of a roof by footprint (none for one by extrusion), meeting in hips, valleys and
/// ridges; and how far its underside rises above its eaves.
pub fn roof_faces(pr: &Project, e: &Value) -> (Vec<Face>, f64) {
    if e.get("extrusion").map(|x| !x.is_null()).unwrap_or(false) {
        return (Vec::new(), 0.0);
    }
    let b = pts(e, "boundary").unwrap_or_default();
    if b.len() < 3 {
        return (Vec::new(), 0.0);
    }
    let yards = rings(e, "courtyards");
    let gables = gable_edges(e);
    let eave = eave_height(pr, e);
    let flat = numd(e, "slope", 30.0) == 0.0;
    // the rings the skeleton's way round, each edge keeping its number
    let mut rs: Vec<Vec<P2>> = Vec::new();
    let mut nums: Vec<usize> = Vec::new();
    let mut k0 = 0;
    for (ri, r) in std::iter::once(&b).chain(yards.iter()).enumerate() {
        let n = r.len();
        let want_ccw = ri == 0;
        let is_ccw = geom::area(r) > 0.0;
        if want_ccw == is_ccw {
            rs.push(r.clone());
            nums.extend((0..n).map(|i| k0 + i));
        } else {
            // reversed: point i is old point n-1-i, so edge i (i to i+1) is old edge n-2-i
            rs.push(r.iter().rev().copied().collect());
            nums.extend((0..n).map(|i| k0 + (2 * n - 2 - i) % n));
        }
        k0 += n;
    }
    let total = k0;
    let slopes: Vec<f64> = (0..total).map(|k| edge_slope_deg(e, k)).collect();
    let min_tan = slopes
        .iter()
        .enumerate()
        .filter(|(k, _)| !gables.contains(k))
        .map(|(_, s)| s.to_radians().tan())
        .fold(f64::INFINITY, f64::min);
    let even = flat || !min_tan.is_finite() || min_tan <= 0.0;
    let speeds: Vec<f64> = nums
        .iter()
        .map(|&k| {
            if gables.contains(&k) {
                0.0
            } else if even {
                1.0
            } else {
                let t = slopes[k].to_radians().tan();
                if (t - min_tan).abs() <= 0.0 {
                    1.0
                } else {
                    min_tan / t
                }
            }
        })
        .collect();
    let sk = crate::geom::skeleton::Skeleton::new(&rs, &speeds);
    let mut out = Vec::new();
    for (i, ring) in sk.faces().into_iter().enumerate() {
        let k = nums[i];
        let (a, _, n, _) = sk.edges[i];
        let level = flat || gables.contains(&k);
        let tan = if level { 0.0 } else { slopes[k].to_radians().tan() };
        let slope = if level { 0.0 } else { slopes[k] };
        out.push(Face { ring, edge: k, origin: a, z0: eave, up: n, tan, slope });
    }
    let rise = if even && flat { 0.0 } else if min_tan.is_finite() { sk.t_max * min_tan } else { 0.0 };
    (out, rise)
}

fn on_ring(r: &[P2], q: P2, tol: f64) -> bool {
    let n = r.len();
    (0..n).any(|i| geom::seg_dist(r[i], r[(i + 1) % n], q) <= tol)
}

/// The underside of a roof at a point in plan: the plane of the slope over it (the lowest where
/// slopes meet); None off the roof. A roof by extrusion: its profile's lowest over the point.
pub fn underside_at(pr: &Project, e: &Value, q: P2) -> Option<f64> {
    let (faces, _) = roof_faces(pr, e);
    let mut best: Option<f64> = None;
    for f in &faces {
        if f.ring.len() >= 3 && (geom::inside(&f.ring, q) || on_ring(&f.ring, q, 1e-6)) {
            let z = f.z_at(q);
            best = Some(best.map_or(z, |b: f64| b.min(z)));
        }
    }
    best
}

/// The highest the underside of a roof by footprint reaches.
pub fn ridge(pr: &Project, e: &Value) -> f64 {
    if let Some(x) = e.get("extrusion").filter(|x| !x.is_null()) {
        let top = pts(x, "profile").unwrap_or_default().iter().map(|p| p[1]).fold(f64::NEG_INFINITY, f64::max);
        return roof_base(pr, e) + if top.is_finite() { top } else { 0.0 };
    }
    let (_, rise) = roof_faces(pr, e);
    eave_height(pr, e) + rise
}

/// A roof's outline in plan: its boundary, or what its extrusion sweeps (along its line, from
/// `from` to `to` to its left).
pub fn outline(e: &Value) -> Vec<P2> {
    if let Some(x) = e.get("extrusion").filter(|x| !x.is_null()) {
        let line = pts(x, "line").unwrap_or_default();
        if line.len() < 2 {
            return Vec::new();
        }
        let (a, b) = (line[0], line[1]);
        let n = geom::left(geom::unit(geom::sub(b, a)));
        let (from, to) = (numd(x, "from", 0.0), numd(x, "to", 0.0));
        let at = |p: P2, w: f64| geom::add(p, geom::scale(n, w));
        return vec![at(a, from), at(b, from), at(b, to), at(a, to)];
    }
    pts(e, "boundary").unwrap_or_default()
}

/// A roof's area in plan, mm²: its outline less its courtyards (its openings don't count).
pub fn plan_area(e: &Value) -> f64 {
    let mut a = geom::area(&outline(e)).abs();
    if e.get("extrusion").map(|x| x.is_null()).unwrap_or(true) {
        for r in rings(e, "courtyards") {
            a -= geom::area(&r).abs();
        }
    }
    a
}
