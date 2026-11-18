//! Shapes of floors and flat roofs: points raised or lowered from the top and split lines it folds
//! along, between which it is flat triangles merged where neighbours lie in one plane; the
//! commands that give and change them, and the model's rules for them.

use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::tri::{self, Triangulation};
use crate::geom::{self, P2};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

#[derive(Clone, Debug)]
pub struct SPoint {
    pub id: Option<u64>,
    pub guid: Option<String>,
    pub at: P2,
    pub z: f64,
}

#[derive(Clone, Debug)]
pub struct SLine {
    pub id: Option<u64>,
    pub guid: Option<String>,
    pub a: P2,
    pub b: P2,
}

#[derive(Clone, Debug, Default)]
pub struct Shape {
    pub points: Vec<SPoint>,
    pub lines: Vec<SLine>,
}

impl Shape {
    pub fn read(e: &Value) -> Shape {
        let mut s = Shape::default();
        let Some(sh) = e.get("shape") else { return s };
        if let Some(a) = sh.get("points").and_then(|x| x.as_arr()) {
            for p in a {
                s.points.push(SPoint {
                    id: p.get("id").and_then(|x| x.as_u64()),
                    guid: text(p, "guid").map(|x| x.to_string()),
                    at: pt(p, "at").unwrap_or([0.0, 0.0]),
                    z: numd(p, "z", 0.0),
                });
            }
        }
        if let Some(a) = sh.get("lines").and_then(|x| x.as_arr()) {
            for l in a {
                s.lines.push(SLine {
                    id: l.get("id").and_then(|x| x.as_u64()),
                    guid: text(l, "guid").map(|x| x.to_string()),
                    a: pt(l, "a").unwrap_or([0.0, 0.0]),
                    b: pt(l, "b").unwrap_or([0.0, 0.0]),
                });
            }
        }
        s
    }

    pub fn is_empty(&self) -> bool {
        self.points.is_empty() && self.lines.is_empty()
    }

    /// The shape as an element keeps it, ids and GUIDs given to what has none.
    pub fn to_value(&mut self, pr: &mut Project) -> Value {
        let mut m = Map::new();
        if !self.points.is_empty() {
            let mut a = Vec::new();
            for p in &mut self.points {
                if p.id.is_none() {
                    p.id = Some(alloc_item_id(pr));
                    p.guid = Some(crate::rand::guid());
                }
                a.push(jobj! {"id" => p.id.unwrap(), "guid" => p.guid.clone().unwrap_or_default(), "at" => pv(p.at), "z" => p.z});
            }
            m.insert("points", Value::Arr(a));
        }
        if !self.lines.is_empty() {
            let mut a = Vec::new();
            for l in &mut self.lines {
                if l.id.is_none() {
                    l.id = Some(alloc_item_id(pr));
                    l.guid = Some(crate::rand::guid());
                }
                a.push(jobj! {"id" => l.id.unwrap(), "guid" => l.guid.clone().unwrap_or_default(), "a" => pv(l.a), "b" => pv(l.b)});
            }
            m.insert("lines", Value::Arr(a));
        }
        Value::Obj(m)
    }
}

/// An id for a shape's point or line: below every id the project has given out, those the
/// elements keep inside them (other shapes' points and lines) too, as a project opened from a
/// file has them.
fn alloc_item_id(pr: &mut Project) -> u64 {
    fn scan(v: &Value, low: &mut u64) {
        match v {
            Value::Obj(m) => {
                if let Some(Value::Num(n)) = m.get("id") {
                    let x = n.as_f64();
                    if (900000.0..1_000_000.0).contains(&x) {
                        *low = (*low).min(x as u64);
                    }
                }
                for (_, x) in &m.items {
                    scan(x, low);
                }
            }
            Value::Arr(a) => a.iter().for_each(|x| scan(x, low)),
            _ => {}
        }
    }
    let mut low = pr.lib_low;
    for e in pr.elements.values() {
        scan(e, &mut low);
    }
    pr.lib_low = low;
    pr.alloc_lib_id()
}

/// The region a shape lies on: the element's outline and its holes (a roof's courtyards and
/// openings).
pub fn region(e: &Value) -> (Vec<P2>, Vec<Vec<P2>>) {
    let b = pts(e, "boundary").unwrap_or_default();
    let mut holes = Vec::new();
    if cat(e) == "roof" {
        holes.extend(rings(e, "courtyards"));
    }
    holes.extend(rings(e, "openings"));
    (b, holes)
}

/// Where the top is without the shape, mm above zero: a floor's level plus its offset, a roof's
/// base plus its thickness.
pub fn base_top(pr: &Project, e: &Value) -> f64 {
    let lev = level_of(pr, e).map(|l| elev(pr, l)).unwrap_or(0.0);
    let off = numd(e, "offset", 0.0);
    match cat(e) {
        "roof" => {
            let t = type_name(pr, e).map(|n| thickness(pr, "roof", &n)).unwrap_or(0.0);
            lev + off + t
        }
        _ => lev + off,
    }
}

/// Why a roof can't take a shape.
pub fn unshapeable(e: &Value) -> Option<&'static str> {
    if cat(e) != "roof" {
        return None;
    }
    if e.get("extrusion").map(|x| !x.is_null()).unwrap_or(false) {
        return Some("an extruded roof takes its shape from its profile: only a flat roof by footprint takes points and split lines");
    }
    if e.get("join").map(|x| !x.is_null()).unwrap_or(false) {
        return Some("a roof that joins another ends where it meets that one's top: only a flat roof by footprint that joins none takes points and split lines");
    }
    if numd(e, "slope", 30.0) != 0.0 {
        return Some("a pitched roof's slopes come from its `slope`: only a flat roof takes points and split lines: `modify` its `slope` to 0, or `reset_shape`");
    }
    None
}

/// The shape triangulated over its region: the triangulation and each corner's height above the
/// unshaped top.
pub fn lift(e: &Value, sh: &Shape) -> Option<(Triangulation, Vec<f64>)> {
    let (b, holes) = region(e);
    let pts: Vec<P2> = sh.points.iter().map(|p| p.at).collect();
    let lines: Vec<(P2, P2)> = sh.lines.iter().map(|l| (l.a, l.b)).collect();
    let t = tri::constrained(&b, &holes, &pts, &lines).ok()?;
    let z: Vec<f64> = t
        .pts
        .iter()
        .map(|q| sh.points.iter().find(|p| geom::dist(p.at, *q) <= tri::TOL).map(|p| p.z).unwrap_or(0.0))
        .collect();
    Some((t, z))
}

/// The planes a shaped top folds into (1 for none).
pub fn faces(e: &Value, sh: &Shape) -> usize {
    if sh.is_empty() {
        return 1;
    }
    match lift(e, sh) {
        Some((t, z)) => tri::planes(&t, &z),
        None => 1,
    }
}

/// The top's lowest and highest, mm above zero.
pub fn top_range(pr: &Project, e: &Value, sh: &Shape) -> (f64, f64) {
    let base = base_top(pr, e);
    let (b, holes) = region(e);
    let mut zs: Vec<f64> = Vec::new();
    for q in b.iter().chain(holes.iter().flatten()) {
        zs.push(sh.points.iter().find(|p| geom::dist(p.at, *q) <= tri::TOL).map(|p| p.z).unwrap_or(0.0));
    }
    for p in &sh.points {
        zs.push(p.z);
    }
    let lo = zs.iter().cloned().fold(f64::INFINITY, f64::min);
    let hi = zs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    (base + lo, base + hi)
}

/// The height (above the unshaped top) the shaped top has at a point.
pub fn height_at(e: &Value, sh: &Shape, q: P2) -> f64 {
    if sh.points.is_empty() {
        return 0.0;
    }
    match lift(e, sh) {
        Some((t, z)) => tri::height_at(&t, &z, q).unwrap_or(0.0),
        None => 0.0,
    }
}

fn pc(p: P2) -> String {
    format!("({:.0}, {:.0})", p[0], p[1])
}

/// The element a shape command works on, or its error.
fn target(s: &Session, p: &Value, c: &str) -> R<u64> {
    let idv = match opt_ref(p, c, "id")? {
        Some(v) => v,
        None => return Err(format!("{}: `id`, the floor or flat roof to shape, is required", c)),
    };
    let pr = &s.project;
    let Some(id) = by_ref(pr, &idv) else {
        return Err(format!("{}: no element {}", c, ref_word(pr, &idv)));
    };
    let e = pr.el(id).unwrap();
    match cat(e) {
        "floor" => Ok(id),
        "roof" => match unshapeable(e) {
            Some(why) => Err(format!("{}: {}: {}", c, id, why)),
            None => Ok(id),
        },
        _ => Err(format!("{}: {}: only floors and flat roofs have shapes", c, id)),
    }
}

/// To a hundredth of a millimetre, as the replies give heights.
fn r2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

fn reply(pr: &Project, id: u64) -> Value {
    let e = pr.el(id).unwrap();
    let sh = Shape::read(e);
    let (lo, hi) = top_range(pr, e, &sh);
    jobj! {"faces" => faces(e, &sh), "id" => id, "top" => Value::Arr(vec![Value::f(r2(lo)), Value::f(r2(hi))])}
}

/// The listing `edit_shape` gives with neither points nor lines.
fn listing(pr: &Project, id: u64) -> Value {
    let e = pr.el(id).unwrap();
    let sh = Shape::read(e);
    let (b, holes) = region(e);
    let corners: Vec<Value> = b
        .iter()
        .chain(holes.iter().flatten())
        .map(|q| {
            let z = sh.points.iter().find(|p| geom::dist(p.at, *q) <= tri::TOL).map(|p| p.z).unwrap_or(0.0);
            jobj! {"at" => pv(*q), "z" => z}
        })
        .collect();
    let points: Vec<Value> = sh.points.iter().map(|p| jobj! {"at" => pv(p.at), "id" => p.id.unwrap_or(0), "z" => p.z}).collect();
    let lines: Vec<Value> = sh.lines.iter().map(|l| jobj! {"a" => pv(l.a), "b" => pv(l.b), "id" => l.id.unwrap_or(0)}).collect();
    let (lo, hi) = top_range(pr, e, &sh);
    jobj! {
        "corners" => Value::Arr(corners),
        "faces" => faces(e, &sh),
        "id" => id,
        "lines" => Value::Arr(lines),
        "points" => Value::Arr(points),
        "top" => Value::Arr(vec![Value::f(r2(lo)), Value::f(r2(hi))]),
    }
}

/// Whether a point is a corner of the region or a point of the shape.
fn is_vertex(e: &Value, sh: &Shape, q: P2) -> bool {
    let (b, holes) = region(e);
    b.iter().chain(holes.iter().flatten()).any(|c| geom::dist(*c, q) <= tri::TOL) || sh.points.iter().any(|p| geom::dist(p.at, q) <= tri::TOL)
}

/// Writes a shape into its element (none: the field goes).
fn store(s: &mut Session, id: u64, mut sh: Shape) {
    let v = if sh.is_empty() { None } else { Some(sh.to_value(&mut s.project)) };
    let e = s.project.el_mut(id).unwrap();
    let order: &[&str] = if cat(e) == "roof" { super::roofs::ORDER } else { super::slabs::FLOOR_ORDER };
    match v {
        Some(v) => put(e, order, "shape", v),
        None => {
            e.remove("shape");
        }
    }
}

/// The loose ends of lines made points at the height the top has there.
fn close_ends(e: &Value, sh: &mut Shape) {
    let lines = sh.lines.clone();
    // the top as its points make it
    let bare = Shape { points: sh.points.clone(), lines: Vec::new() };
    for l in &lines {
        for q in [l.a, l.b] {
            if !is_vertex(e, sh, q) {
                let z = height_at(e, &bare, q);
                sh.points.push(SPoint { id: None, guid: None, at: q, z: round_mm(z) });
            }
        }
    }
}

fn round_mm(z: f64) -> f64 {
    z
}

/// An `id` as serde reads `Option<u64>`.
fn de_id(y: &Value) -> Result<Option<u64>, String> {
    match y {
        Value::Null => Ok(None),
        Value::Num(crate::json::Num::U(u)) => Ok(Some(*u)),
        Value::Num(crate::json::Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u64", i)),
        o => Err(format!("invalid type: {}, expected u64", o.kind_name())),
    }
}

/// A `guid` as the model reads a reference: a GUID (in braces or not, any case) or an id, as a
/// number or a string of digits; only checked, a point or line is known by its `id`.
fn de_ref(y: &Value) -> Result<(), String> {
    match y {
        Value::Null => Ok(()),
        Value::Str(s) => {
            let t = s.trim();
            let g = t.strip_prefix('{').and_then(|u| u.strip_suffix('}')).unwrap_or(t);
            let b = g.as_bytes();
            let guid = b.len() == 36
                && b.iter().enumerate().all(|(i, c)| {
                    let dash = matches!(i, 8 | 13 | 18 | 23);
                    dash == (*c == b'-') && (dash || c.is_ascii_hexdigit())
                });
            let id = !t.is_empty() && t.bytes().all(|c| c.is_ascii_digit()) && t.parse::<u64>().is_ok();
            if guid || id {
                Ok(())
            } else {
                Err(format!("`{}` is not a GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or an id", s))
            }
        }
        Value::Num(crate::json::Num::U(_)) => Ok(()),
        Value::Num(crate::json::Num::I(i)) => Err(format!("{} is not an element id", i)),
        Value::Num(crate::json::Num::F(f)) => {
            if *f >= 0.0 && f.fract() == 0.0 && *f < 18446744073709551616.0 {
                Ok(())
            } else {
                Err(format!("{} is not an element id", f))
            }
        }
        o => Err(format!("invalid type: {}, expected an element's GUID, or its id", o.kind_name())),
    }
}

fn de_z(y: &Value) -> Result<Option<f64>, String> {
    match y {
        Value::Num(n) => Ok(Some(n.as_f64())),
        Value::Null => Ok(None),
        o => Err(format!("invalid type: {}, expected f64", o.kind_name())),
    }
}

/// The fields of a struct of 4 (`id`, `guid`, then two of its own) given as a sequence: the id,
/// the third and the fourth.
fn seq4<'a>(f: &'a [Value], name: &str) -> Result<(Option<u64>, &'a Value, Option<&'a Value>), String> {
    let id = match f.first() {
        Some(y) => de_id(y)?,
        None => None,
    };
    if let Some(y) = f.get(1) {
        de_ref(y)?;
    }
    let third = f.get(2).ok_or_else(|| format!("invalid length 2, expected struct {} with 4 elements", name))?;
    Ok((id, third, f.get(3)))
}

fn too_long(f: &[Value]) -> Result<(), String> {
    if f.len() > 4 {
        return Err(format!("invalid length {}, expected fewer elements in array", f.len()));
    }
    Ok(())
}

/// Points as serde reads `Vec<PointIn {id?, guid?, at, z?}>` (each a map or its fields in order).
fn de_points(v: &Value, keep: &Shape) -> Result<Vec<(SPoint, bool)>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::new();
    for x in a {
        let mut at = None;
        let mut z = None;
        let mut id = None;
        match x {
            Value::Obj(m) => {
                for (k, y) in &m.items {
                    match k.as_str() {
                        "id" => id = de_id(y)?,
                        "guid" => de_ref(y)?,
                        "at" => at = Some(super::slabs::de_p2(y)?),
                        "z" => z = de_z(y)?,
                        other => return Err(format!("unknown field `{}`, expected one of `id`, `guid`, `at`, `z`", other)),
                    }
                }
            }
            Value::Arr(f) => {
                let (i, third, fourth) = seq4(f, "PointIn")?;
                id = i;
                at = Some(super::slabs::de_p2(third)?);
                if let Some(y) = fourth {
                    z = de_z(y)?;
                }
                too_long(f)?;
            }
            _ => return Err(format!("invalid type: {}, expected struct PointIn", x.kind_name())),
        }
        let at = at.ok_or_else(|| "missing field `at`".to_string())?;
        let kept = id.and_then(|i| keep.points.iter().find(|p| p.id == Some(i)));
        let (id, guid) = match kept {
            Some(k) => (k.id, k.guid.clone()),
            None => (None, None),
        };
        out.push((SPoint { id, guid, at, z: z.unwrap_or(f64::NAN) }, z.is_some()));
    }
    Ok(out)
}

/// Split lines as serde reads `Vec<LineIn {id?, guid?, a, b}>` (each a map or its fields in order).
fn de_lines(v: &Value, keep: &Shape) -> Result<Vec<SLine>, String> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected a sequence", v.kind_name()));
    };
    let mut out = Vec::new();
    for x in a {
        let mut pa = None;
        let mut pb = None;
        let mut id = None;
        match x {
            Value::Obj(m) => {
                for (k, y) in &m.items {
                    match k.as_str() {
                        "id" => id = de_id(y)?,
                        "guid" => de_ref(y)?,
                        "a" => pa = Some(super::slabs::de_p2(y)?),
                        "b" => pb = Some(super::slabs::de_p2(y)?),
                        other => return Err(format!("unknown field `{}`, expected one of `id`, `guid`, `a`, `b`", other)),
                    }
                }
            }
            Value::Arr(f) => {
                let (i, third, fourth) = seq4(f, "LineIn")?;
                id = i;
                pa = Some(super::slabs::de_p2(third)?);
                let fourth = fourth.ok_or_else(|| "invalid length 3, expected struct LineIn with 4 elements".to_string())?;
                pb = Some(super::slabs::de_p2(fourth)?);
                too_long(f)?;
            }
            _ => return Err(format!("invalid type: {}, expected struct LineIn", x.kind_name())),
        }
        let a = pa.ok_or_else(|| "missing field `a`".to_string())?;
        let b = pb.ok_or_else(|| "missing field `b`".to_string())?;
        let kept = id.and_then(|i| keep.lines.iter().find(|l| l.id == Some(i)));
        let (id, guid) = match kept {
            Some(k) => (k.id, k.guid.clone()),
            None => (None, None),
        };
        out.push(SLine { id, guid, a, b });
    }
    Ok(out)
}

pub fn cmd_edit_shape(s: &mut Session, p: &Value) -> R<Value> {
    let c = "edit_shape";
    known_only(p, c, &["id", "points", "lines", "absolute"])?;
    let id = target(s, p, c)?;
    let pr = &s.project;
    let e = pr.el(id).unwrap().clone();
    let old = Shape::read(&e);
    // with neither points nor lines it gives the shape, `absolute` unread
    if params::get(p, "points").is_none() && params::get(p, "lines").is_none() {
        return Ok(listing(pr, id));
    }
    let absolute = params::opt_bool(p, c, "absolute")?.unwrap_or(false);
    let points = match params::get(p, "points") {
        None => None,
        Some(v) => Some(de_points(v, &old).map_err(|er| format!("edit_shape: `points` is a list of {{at: [x, y], z, id?}}: {}", er))?),
    };
    let lines = match params::get(p, "lines") {
        None => None,
        Some(v) => Some(de_lines(v, &old).map_err(|er| format!("edit_shape: `lines` is a list of {{a: [x, y], b: [x, y], id?}}: {}", er))?),
    };
    let base = base_top(pr, &e);
    let mut sh = Shape::default();
    for (pt, has_z) in points.unwrap_or_default() {
        if !has_z {
            return Err(format!("edit_shape: the point at P2({:?}, {:?}) needs its height `z`", pt.at[0], pt.at[1]));
        }
        if !(pt.z.abs() <= params::MAX_MM) {
            return Err(format!("edit_shape: `z` must be a number in mm, got {}", d(pt.z)));
        }
        let z = if absolute { pt.z - base } else { pt.z };
        sh.points.push(SPoint { z, ..pt });
    }
    sh.lines = lines.unwrap_or_default();
    close_ends(&e, &mut sh);
    store(s, id, sh);
    Ok(reply(&s.project, id))
}

pub fn cmd_add_point(s: &mut Session, p: &Value) -> R<Value> {
    let c = "add_point";
    known_only(p, c, &["id", "at", "z", "absolute", "offset"])?;
    let id = target(s, p, c)?;
    let at = params::req_point(p, c, "at")?;
    let z = params::opt_num(p, c, "z")?;
    let offset = params::opt_num(p, c, "offset")?;
    if z.is_some() && offset.is_some() {
        return Err("add_point: give `z` or `offset`, not both".into());
    }
    // `absolute` only says how to read `z`
    let absolute = if z.is_some() { params::opt_bool(p, c, "absolute")?.unwrap_or(false) } else { false };
    let pr = &s.project;
    let e = pr.el(id).unwrap().clone();
    let mut sh = Shape::read(&e);
    let base = base_top(pr, &e);
    let now = height_at(&e, &sh, at);
    let zz = match (z, offset) {
        (Some(z), _) => {
            if absolute {
                z - base
            } else {
                z
            }
        }
        (None, Some(o)) => now + o,
        (None, None) => now,
    };
    match sh.points.iter_mut().find(|q| geom::dist(q.at, at) <= 1.0) {
        Some(q) => q.z = zz,
        None => sh.points.push(SPoint { id: None, guid: None, at, z: zz }),
    }
    store(s, id, sh);
    Ok(reply(&s.project, id))
}

pub fn cmd_add_split_line(s: &mut Session, p: &Value) -> R<Value> {
    let c = "add_split_line";
    known_only(p, c, &["id", "a", "b"])?;
    let id = target(s, p, c)?;
    let a = params::req_point(p, c, "a")?;
    let b = params::req_point(p, c, "b")?;
    let e = s.project.el(id).unwrap().clone();
    let mut sh = Shape::read(&e);
    let mut add = Shape { points: Vec::new(), lines: vec![SLine { id: None, guid: None, a, b }] };
    // loose ends at the height the top has there now
    for q in [a, b] {
        if !is_vertex(&e, &sh, q) && !add.points.iter().any(|x| geom::dist(x.at, q) <= tri::TOL) {
            let z = height_at(&e, &sh, q);
            let _ = &add;
            add.points.push(SPoint { id: None, guid: None, at: q, z });
        }
    }
    sh.points.extend(add.points);
    sh.lines.extend(add.lines);
    store(s, id, sh);
    Ok(reply(&s.project, id))
}

pub fn cmd_reset_shape(s: &mut Session, p: &Value) -> R<Value> {
    let c = "reset_shape";
    known_only(p, c, &["id"])?;
    let idv = match opt_ref(p, c, "id")? {
        Some(v) => v,
        None => return Err(format!("{}: `id`, the floor or flat roof to shape, is required", c)),
    };
    let pr = &s.project;
    let Some(id) = by_ref(pr, &idv) else {
        return Err(format!("{}: no element {}", c, ref_word(pr, &idv)));
    };
    if !matches!(pr.category(id), Some("floor") | Some("roof")) {
        return Err(format!("{}: {}: only floors and flat roofs have shapes", c, id));
    }
    store(s, id, Shape::default());
    Ok(jobj! {"id" => id})
}

// ---------------------------------------------------------------- the rules

pub fn check_shape(pr: &Project, id: u64, e: &Value) -> R<()> {
    let sh = Shape::read(e);
    if sh.is_empty() {
        return Ok(());
    }
    let c = cat(e);
    if c == "floor" && e.get("arrow").map(|x| !x.is_null()).unwrap_or(false) && numd(e, "slope", 0.0) != 0.0 {
        return Err(format!(
            "floor {}: a shaped floor takes its falls from its points, not a slope arrow too: `modify` its `slope` to 0, or `reset_shape`",
            id
        ));
    }
    if let Some(why) = unshapeable(e) {
        return Err(format!("roof {}: {}", id, why));
    }
    let (b, holes) = region(e);
    let inside_region = |q: P2| -> Result<(), String> {
        let on_edge = |r: &[P2]| (0..r.len()).any(|i| geom::seg_dist(r[i], r[(i + 1) % r.len()], q) <= tri::TOL);
        if !(geom::inside(&b, q) || on_edge(&b)) {
            return Err(format!("{} {}: the shape point at {} is outside its outline", c, id, pc(q)));
        }
        for h in &holes {
            if geom::inside(h, q) {
                return Err(format!("{} {}: the shape point at {} is in an opening", c, id, pc(q)));
            }
        }
        Ok(())
    };
    // the variable layer of its type takes up the fall: a point may not lower the top through it
    let var = type_name(pr, e).and_then(|n| variable_layer(pr, c, &n));
    for p in &sh.points {
        inside_region(p.at)?;
        if let Some(tv) = var {
            let v = ((tv + p.z) * 10.0).round() / 10.0;
            if v < 0.0 {
                return Err(format!(
                    "{} {}: at the shape point at {} the variable layer would be {} mm: raise the point by {} mm, or thicken the variable layer",
                    c,
                    id,
                    pc(p.at),
                    d(v),
                    d(-v)
                ));
            }
        }
    }
    for i in 0..sh.points.len() {
        for j in i + 1..sh.points.len() {
            if geom::dist(sh.points[i].at, sh.points[j].at) <= 1.0 {
                return Err(format!(
                    "{} {}: the shape points at {} and {} are within a millimetre of each other: one is enough",
                    c,
                    id,
                    pc(sh.points[i].at),
                    pc(sh.points[j].at)
                ));
            }
        }
    }
    let corners: Vec<P2> = b.iter().chain(holes.iter().flatten()).copied().collect();
    for l in &sh.lines {
        let len = geom::dist(l.a, l.b);
        if !(len > 1.0) {
            return Err(format!("{} {} split line: too short ({} mm)", c, id, d(len)));
        }
        for q in [l.a, l.b] {
            let known = sh.points.iter().any(|p| geom::dist(p.at, q) <= 1.0) || corners.iter().any(|k| geom::dist(*k, q) <= 1.0);
            if !known {
                return Err(format!(
                    "{} {}: the split line from {} to {} ends at {}, which is no point of its shape and no corner: add a point there",
                    c,
                    id,
                    pc(l.a),
                    pc(l.b),
                    pc(q)
                ));
            }
        }
    }
    // the lines bend through the points (and the corners) within a millimetre of them: no piece
    // may cross an edge or run in an opening, and no two pieces may cross
    let pieces = line_pieces(&sh, &corners);
    let rings_all: Vec<&Vec<P2>> = std::iter::once(&b).chain(holes.iter()).collect();
    for &(a0, a1) in &pieces {
        let mut hit: Option<(f64, P2)> = None;
        for r in &rings_all {
            let n = r.len();
            for i in 0..n {
                let (e0, e1) = (r[i], r[(i + 1) % n]);
                let o1 = geom::orient(a0, a1, e0);
                let o2 = geom::orient(a0, a1, e1);
                let o3 = geom::orient(e0, e1, a0);
                let o4 = geom::orient(e0, e1, a1);
                let eps = 1e-9 * geom::dist(a0, a1).max(1.0) * geom::dist(e0, e1).max(1.0);
                let proper = ((o1 > eps && o2 < -eps) || (o1 < -eps && o2 > eps)) && ((o3 > eps && o4 < -eps) || (o3 < -eps && o4 > eps));
                if proper {
                    if let Some((t, _)) = geom::seg_cross(a0, a1, e0, e1) {
                        if hit.map(|h| t < h.0).unwrap_or(true) {
                            hit = Some((t, geom::lerp(a0, a1, t)));
                        }
                    }
                }
            }
        }
        if let Some((_, q)) = hit {
            return Err(format!(
                "{} {}: the split line from {} to {} crosses an edge of the outline or of an opening at {}",
                c,
                id,
                pc(a0),
                pc(a1),
                pc(q)
            ));
        }
        let m = geom::lerp(a0, a1, 0.5);
        if holes.iter().any(|h| geom::inside(h, m)) {
            return Err(format!("{} {}: the split line from {} to {} runs in an opening", c, id, pc(a0), pc(a1)));
        }
        let on_outline = (0..b.len()).any(|i| geom::seg_dist(b[i], b[(i + 1) % b.len()], m) <= 1e-6);
        if !geom::inside(&b, m) && !on_outline {
            return Err(format!("{} {}: the split line from {} to {} runs outside the outline", c, id, pc(a0), pc(a1)));
        }
    }
    for j in 0..pieces.len() {
        for i in 0..j {
            let ((a0, a1), (b0, b1)) = (pieces[i], pieces[j]);
            if let Some((t, _)) = geom::seg_cross(a0, a1, b0, b1) {
                let q = geom::lerp(a0, a1, t);
                let at_end = |p: P2, r: P2| geom::dist(q, p) <= 1.0 || geom::dist(q, r) <= 1.0;
                if !(at_end(a0, a1) || at_end(b0, b1)) {
                    return Err(format!("{} {}: the split line from {} to {} crosses another at {}", c, id, pc(b0), pc(b1), pc(q)));
                }
            }
        }
    }
    Ok(())
}

/// The split lines cut at the shape's points, and the outline's and openings' corners, within a
/// millimetre of them, in order along each.
pub fn line_pieces(sh: &Shape, corners: &[P2]) -> Vec<(P2, P2)> {
    let mut out = Vec::new();
    for l in &sh.lines {
        // each line from its lesser end (by x, then y)
        let (la, lb) = if (l.b[0], l.b[1]) < (l.a[0], l.a[1]) { (l.b, l.a) } else { (l.a, l.b) };
        let dd = geom::sub(lb, la);
        let l2 = geom::dot(dd, dd);
        let mut cuts: Vec<(f64, P2)> = Vec::new();
        if l2 > 0.0 {
            for q in sh.points.iter().map(|p| p.at).chain(corners.iter().copied()) {
                if geom::dist(q, la) <= 1.0 || geom::dist(q, lb) <= 1.0 {
                    continue;
                }
                let t = geom::dot(geom::sub(q, la), dd) / l2;
                if t > 0.0 && t < 1.0 && geom::seg_dist(la, lb, q) <= 1.0 && !cuts.iter().any(|c0| geom::dist(c0.1, q) <= 1.0) {
                    cuts.push((t, q));
                }
            }
        }
        cuts.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap_or(std::cmp::Ordering::Equal));
        let mut prev = la;
        for (_, q) in cuts {
            out.push((prev, q));
            prev = q;
        }
        out.push((prev, lb));
    }
    out
}
