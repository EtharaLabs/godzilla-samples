//! Floors, ceilings and shafts: an outline (given, sketched, or the walls'), its openings, and
//! the model's rules for them.

use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub const FLOOR_ORDER: &[&str] = &[
    "type",
    "level",
    "boundary",
    "openings",
    "offset",
    "slope",
    "arrow",
    "structural",
    "pattern_origin",
    "pattern_angle",
    "sketch",
    "shape",
    "params",
];
pub const CEILING_ORDER: &[&str] = &["type", "level", "boundary", "openings", "offset", "sketch", "params"];
pub const SHAFT_ORDER: &[&str] = &["level", "boundary", "top_level", "height", "base_offset", "sketch"];

pub const SKETCH_HELP: &str = "is a list of lines, each [[x,y],[x,y]], an arc [[x,y],[x,y],[x,y]] (its ends, then a point it passes through) or an object: `id?` and a curve's fields, `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

/// A boundary as points: each a point in mm, else the original's errors.
pub fn opt_boundary(p: &Value, c: &str, key: &str) -> R<Option<Vec<P2>>> {
    match params::get(p, key) {
        None => Ok(None),
        Some(Value::Arr(a)) => {
            let mut out = Vec::with_capacity(a.len());
            for x in a {
                match params::point_of(x) {
                    Some(q) => out.push(q),
                    None => return Err(format!("{}: `{}`: {} is not a point [x, y] in mm", c, key, x.to_compact())),
                }
            }
            Ok(Some(out))
        }
        Some(_) => Err(format!("{}: `{}` [[x, y], …] is required", c, key)),
    }
}

/// A list of outlines as serde reads `Vec<Vec<P2>>`, with its errors.
pub fn de_rings(v: &Value) -> Result<Vec<Vec<P2>>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::with_capacity(a.len());
    for r in a {
        out.push(de_points(r)?);
    }
    Ok(out)
}

/// A list of points as serde reads `Vec<P2>`.
pub fn de_points(v: &Value) -> Result<Vec<P2>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::with_capacity(a.len());
    for q in a {
        out.push(de_p2(q)?);
    }
    Ok(out)
}

/// A point as serde reads the tuple struct `P2(f64, f64)`.
pub fn de_p2(q: &Value) -> Result<P2, String> {
    let Value::Arr(x) = q else {
        return Err(format!("invalid type: {}, expected tuple struct P2", q.kind_name()));
    };
    let mut p = [0.0; 2];
    for i in 0..2 {
        match x.get(i) {
            None => return Err(format!("invalid length {}, expected tuple struct P2 with 2 elements", x.len())),
            Some(Value::Num(n)) => p[i] = n.as_f64(),
            Some(o) => return Err(format!("invalid type: {}, expected f64", o.kind_name())),
        }
    }
    if x.len() > 2 {
        return Err(format!("invalid length {}, expected fewer elements in array", x.len()));
    }
    Ok(p)
}

pub fn opt_openings(p: &Value, c: &str, key: &str) -> R<Option<Vec<Vec<P2>>>> {
    match params::get(p, key) {
        None => Ok(None),
        Some(v) => de_rings(v)
            .map(Some)
            .map_err(|e| format!("{}: `{}` is a list of outlines [[[x,y],…],…]: {}", c, key, e)),
    }
}

/// A boundary as the model keeps one: a point repeated, or within a millimetre of the one before
/// it (the last of the first), dropped.
pub fn clean(ring: &[P2]) -> Vec<P2> {
    let mut out: Vec<P2> = Vec::with_capacity(ring.len());
    for p in ring {
        if let Some(l) = out.last() {
            if geom::dist(*l, *p) <= 1.0 {
                continue;
            }
        }
        out.push(*p);
    }
    while out.len() > 1 && geom::dist(out[0], *out.last().unwrap()) <= 1.0 {
        out.pop();
    }
    out
}

/// Area in mm² of an outline less its openings.
pub fn net_area(boundary: &[P2], openings: &[Vec<P2>]) -> f64 {
    let mut a = geom::area(boundary).abs();
    for o in openings {
        a -= geom::area(o).abs();
    }
    a
}

/// The `sketch` parameter read into lines, or the original's error.
pub fn sketch_lines(p: &Value, c: &str) -> R<Option<Vec<crate::geom::sketch::Line>>> {
    match params::get(p, "sketch") {
        None => Ok(None),
        Some(v) => crate::geom::sketch::parse(v).map(Some).map_err(|e| crate::geom::sketch::parse_message(c, "sketch", &e)),
    }
}

// ---------------------------------------------------------------- floor

pub fn cmd_floor(s: &mut Session, p: &Value) -> R<Value> {
    let c = "floor";
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let ty = params::opt_text(p, c, "type")?;
    let mut sketch = sketch_lines(p, c)?;
    let boundary = opt_boundary(p, c, "boundary")?;
    // with neither, the outline of the level's walls, found before the rest is read
    let walls_outline = if sketch.is_none() && boundary.is_none() {
        match super::outline::level_outline(pr, level) {
            Some(o) => Some(o),
            None => return Err(format!("floor: no walls enclose an area on {}; give `boundary`", level_name(pr, level))),
        }
    } else {
        None
    };
    let openings = opt_openings(p, c, "openings")?;
    let arrow = match params::get(p, "arrow") {
        None => None,
        Some(Value::Arr(a)) => {
            let mut pts = Vec::new();
            for x in a {
                match params::point_of(x) {
                    Some(q) => pts.push(q),
                    None => return Err(format!("floor: `arrow`: {} is not a point [x, y] in mm", x.to_compact())),
                }
            }
            if pts.len() != 2 {
                return Err("floor: `arrow` is [[x, y], [x, y]]: its tail, then its head".into());
            }
            Some(pts)
        }
        Some(_) => return Err("floor: `arrow` [[x, y], …] is required".into()),
    };
    let offset = params::opt_num(p, c, "offset")?;
    let slope = params::opt_num(p, c, "slope")?;
    let structural = params::opt_bool(p, c, "structural")?;
    if sketch.is_some() && (boundary.is_some() || openings.is_some()) {
        return Err("floor: give the outline as `sketch` or `boundary` (with `openings`), not both".into());
    }
    let ty = ty.or_else(|| default_type(pr, c)).ok_or_else(|| "floor: the model has no types for this".to_string())?;
    let mut from_walls = false;
    let mut sketch_v: Option<()> = None;
    let (outline, holes) = if let Some(lines) = sketch.as_mut() {
        let (o, h) = crate::geom::sketch::solve_one(lines).map_err(|e| format!("{}: {}", c, e))?;
        sketch_v = Some(());
        (o, h)
    } else if let Some(b) = boundary {
        let b = clean(&b);
        let b = geom::ccw(&b);
        let h: Vec<Vec<P2>> = openings.clone().unwrap_or_default().iter().map(|o| clean(o)).collect();
        (b, h)
    } else {
        let o = walls_outline.unwrap();
        from_walls = true;
        let h = match &openings {
            Some(given) => given.iter().map(|o| clean(o)).collect(),
            None => o.holes.clone(),
        };
        (o.boundary, h)
    };
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "type" => type_ref(pr, c, &ty),
        "level" => level_guid(pr, level),
        "boundary" => ring_v(&outline),
    };
    if !holes.is_empty() {
        e.set("openings", rings_v(&holes));
    }
    if let Some(o) = offset {
        if o != 0.0 {
            e.set("offset", Value::f(o));
        }
    }
    if let Some(sl) = slope {
        if sl != 0.0 {
            e.set("slope", Value::f(sl));
        }
    }
    if let Some(a) = &arrow {
        e.set("arrow", Value::Arr(vec![pv(a[0]), pv(a[1])]));
    }
    if structural == Some(true) {
        e.set("structural", Value::Bool(true));
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    if sketch_v.is_some() {
        let v = crate::geom::sketch::to_value(&mut s.project, sketch.as_ref().unwrap(), &[]);
        e.set("sketch", v);
    }
    let area = net_area(&outline, &holes);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    super::edits::note_walls(id, from_walls);
    Ok(jobj! {"area_m2" => m2(area), "id" => id})
}

// ---------------------------------------------------------------- ceiling

pub fn cmd_ceiling(s: &mut Session, p: &Value) -> R<Value> {
    let c = "ceiling";
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let ty = params::opt_text(p, c, "type")?;
    let mut sketch = sketch_lines(p, c)?;
    let point = params::opt_point(p, c, "point")?;
    let boundary = opt_boundary(p, c, "boundary")?;
    if sketch.is_none() && boundary.is_none() && point.is_none() {
        return Err("ceiling: `point` [x, y] in a room, `boundary` [[x, y], …] or `sketch` is required".into());
    }
    // round a point, the room's region at the walls' faces, found before the rest is read
    let at_point = match (sketch.is_none() && boundary.is_none(), point) {
        (true, Some(q)) => match super::rooms::region_at_faces(pr, level, q) {
            Some(r) => Some(r),
            None => return Err(format!("ceiling: no walls on {} close around {}; give `boundary`", level_name(pr, level), dp(q))),
        },
        _ => None,
    };
    let openings = opt_openings(p, c, "openings")?;
    let offset = params::opt_num(p, c, "offset")?;
    if sketch.is_some() && (boundary.is_some() || openings.is_some()) {
        return Err("ceiling: give the outline as `sketch` or `boundary` (with `openings`), not both".into());
    }
    let ty = ty.or_else(|| default_type(pr, c)).ok_or_else(|| "ceiling: the model has no types for this".to_string())?;
    let mut sketch_v: Option<()> = None;
    let (outline, holes) = if let Some(lines) = sketch.as_mut() {
        let (o, h) = crate::geom::sketch::solve_one(lines).map_err(|e| format!("{}: {}", c, e))?;
        sketch_v = Some(());
        (o, h)
    } else if let Some(b) = boundary {
        let b = geom::ccw(&clean(&b));
        let h: Vec<Vec<P2>> = openings.clone().unwrap_or_default().iter().map(|o| clean(o)).collect();
        (b, h)
    } else if let Some((o, mut h)) = at_point {
        if let Some(given) = &openings {
            h = given.iter().map(|o| clean(o)).collect();
        }
        (o, h)
    } else {
        return Err("ceiling: `point` [x, y] in a room, `boundary` [[x, y], …] or `sketch` is required".into());
    };
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "type" => type_ref(pr, c, &ty),
        "level" => level_guid(pr, level),
        "boundary" => ring_v(&outline),
    };
    if !holes.is_empty() {
        e.set("openings", rings_v(&holes));
    }
    e.set("offset", Value::f(offset.unwrap_or(2600.0)));
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    if sketch_v.is_some() {
        let v = crate::geom::sketch::to_value(&mut s.project, sketch.as_ref().unwrap(), &[]);
        e.set("sketch", v);
    }
    let area = net_area(&outline, &holes);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    Ok(jobj! {"area_m2" => m2(area), "id" => id})
}

// ---------------------------------------------------------------- shaft

pub fn cmd_shaft(s: &mut Session, p: &Value) -> R<Value> {
    let c = "shaft";
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let mut sketch = sketch_lines(p, c)?;
    let boundary = opt_boundary(p, c, "boundary")?;
    if sketch.is_none() && boundary.is_none() {
        return Err("shaft: `boundary` [[x, y], …] is required".into());
    }
    let height = params::opt_num(p, c, "height")?;
    let top_level = match params::get(p, "top_level") {
        Some(v) => Some(crate::model::resolve_level(pr, c, "top_level", v)?),
        None => None,
    };
    let base_offset = params::opt_num(p, c, "base_offset")?;
    if sketch.is_some() && boundary.is_some() {
        return Err("shaft: give the outline as `sketch` or `boundary` (with ``), not both".into());
    }
    let mut sketch_v: Option<()> = None;
    let outline = if let Some(lines) = sketch.as_mut() {
        let (o, h) = crate::geom::sketch::solve_one(lines).map_err(|e| format!("{}: {}", c, e))?;
        if !h.is_empty() {
            return Err("shaft: a shaft is one outline with no holes in it: sketch each hole as a shaft of its own".into());
        }
        sketch_v = Some(());
        o
    } else if let Some(b) = boundary {
        geom::ccw(&clean(&b))
    } else {
        return Err("shaft: `boundary` [[x, y], …] is required".into());
    };
    let top = match top_level {
        Some(t) => Some(t),
        None if height.is_some() => None,
        None => crate::model::level_above(pr, level),
    };
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "level" => level_guid(pr, level),
        "boundary" => ring_v(&outline),
        "top_level" => match top { Some(t) => Value::Str(level_guid(pr, t)), None => Value::Null },
        "height" => height.unwrap_or(3000.0),
        "base_offset" => base_offset.unwrap_or(0.0),
    };
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    if sketch_v.is_some() {
        let v = crate::geom::sketch::to_value(&mut s.project, sketch.as_ref().unwrap(), &[]);
        e.set("sketch", v);
    }
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    Ok(jobj! {"id" => id})
}

// ---------------------------------------------------------------- the rules

/// A boundary's and its openings' counts, and the openings inside it and apart.
pub fn check_rings(c: &str, id: u64, boundary: &[P2], openings: &[Vec<P2>]) -> R<()> {
    if boundary.len() < 3 || boundary.len() > 10000 {
        return Err(format!("{} {}: a boundary needs 3 to 10000 points", c, id));
    }
    for (i, o) in openings.iter().enumerate() {
        if o.len() < 3 || o.len() > 10000 {
            return Err(format!("{} {} opening {}: a boundary needs 3 to 10000 points", c, id, i));
        }
    }
    for (i, o) in openings.iter().enumerate() {
        if !ring_inside(o, boundary) {
            return Err(format!("{} {}: opening {} isn't inside its outline", c, id, i));
        }
    }
    for i in 0..openings.len() {
        for j in i + 1..openings.len() {
            if rings_overlap(&openings[i], &openings[j]) {
                return Err(format!("{} {}: openings {} and {} overlap", c, id, i, j));
            }
        }
    }
    Ok(())
}

/// Whether ring a lies inside ring b (its corners inside or on b's edges, its edges crossing none
/// of b's).
pub fn ring_inside(a: &[P2], b: &[P2]) -> bool {
    for p in a {
        if !geom::inside(b, *p) {
            return false;
        }
    }
    !edges_cross(a, b)
}

pub fn edges_cross(a: &[P2], b: &[P2]) -> bool {
    let n = a.len();
    let m = b.len();
    for i in 0..n {
        let (p0, p1) = (a[i], a[(i + 1) % n]);
        for j in 0..m {
            let (q0, q1) = (b[j], b[(j + 1) % m]);
            if proper_cross(p0, p1, q0, q1) {
                return true;
            }
        }
    }
    false
}

fn proper_cross(a0: P2, a1: P2, b0: P2, b1: P2) -> bool {
    let d1 = geom::orient(b0, b1, a0);
    let d2 = geom::orient(b0, b1, a1);
    let d3 = geom::orient(a0, a1, b0);
    let d4 = geom::orient(a0, a1, b1);
    ((d1 > 0.0 && d2 < 0.0) || (d1 < 0.0 && d2 > 0.0)) && ((d3 > 0.0 && d4 < 0.0) || (d3 < 0.0 && d4 > 0.0))
}

/// Whether two rings overlap: an edge of one crosses the other's, or one lies inside the other.
pub fn rings_overlap(a: &[P2], b: &[P2]) -> bool {
    if edges_cross(a, b) {
        return true;
    }
    a.iter().any(|p| geom::inside(b, *p)) || b.iter().any(|p| geom::inside(a, *p))
}

/// The rule that only a roof's sketch lines carry slopes (it keeps them as its `slopes`).
pub fn check_sketch_slopes(c: &str, id: u64, e: &Value) -> R<()> {
    if let Some(a) = e.get("sketch").and_then(|v| v.as_arr()) {
        for (i, l) in a.iter().enumerate() {
            if l.get("slope").map(|x| !x.is_null()).unwrap_or(false) {
                return Err(format!(
                    "{} {}: sketch line {} has a `slope`, which a roof keeps as its `slopes`, never in its sketch",
                    c, id, i
                ));
            }
        }
    }
    Ok(())
}

pub fn check_floor(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_type(pr, id, e, "floor")?;
    check_sketch_slopes("floor", id, e)?;
    let boundary = pts(e, "boundary").unwrap_or_default();
    let openings = rings(e, "openings");
    check_rings("floor", id, &boundary, &openings)?;
    let slope = numd(e, "slope", 0.0);
    let arrow = pts(e, "arrow");
    if slope != 0.0 && arrow.is_none() {
        return Err(format!(
            "floor {}: a sloped floor needs a slope arrow, from where its top is at its offset toward where it rises",
            id
        ));
    }
    if let Some(a) = &arrow {
        if a.len() == 2 {
            let l = geom::dist(a[0], a[1]);
            if !(l > 1.0) {
                return Err(format!("floor {} arrow: too short ({} mm)", id, d(l)));
            }
        }
    }
    if !(slope.abs() <= 75.0) {
        return Err(format!("floor {}: slope {}° isn't between -75° and 75°", id, d(slope)));
    }
    super::shape::check_shape(pr, id, e)
}

pub fn check_ceiling(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_type(pr, id, e, "ceiling")?;
    check_sketch_slopes("ceiling", id, e)?;
    let boundary = pts(e, "boundary").unwrap_or_default();
    let openings = rings(e, "openings");
    check_rings("ceiling", id, &boundary, &openings)
}

pub fn check_shaft(pr: &Project, id: u64, e: &Value) -> R<()> {
    check_sketch_slopes("shaft", id, e)?;
    let boundary = pts(e, "boundary").unwrap_or_default();
    check_rings("shaft", id, &boundary, &[])?;
    let level = level_of(pr, e);
    let top_level = e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level"));
    let base = level.map(|l| elev(pr, l)).unwrap_or(0.0) + numd(e, "base_offset", 0.0);
    let height = numd(e, "height", 3000.0);
    if top_level.is_none() && !(height > 0.0) {
        return Err(format!("shaft {} height must be above zero, got {}", id, d(height)));
    }
    let top = match top_level {
        Some(t) => elev(pr, t),
        None => base + height,
    };
    if !(top > base) {
        return Err(format!("shaft {}: its top must be above its base", id));
    }
    Ok(())
}
