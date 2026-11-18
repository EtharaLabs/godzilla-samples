//! Masses: a footprint extruded (or lofted to a top outline) from a level; the floors made at each
//! level it crosses, the walls, floor and roof made on its faces and rebuilt from it, and Show Mass.

use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub const ORDER: &[&str] = &["name", "level", "boundary", "top_level", "height", "base_offset", "top", "params"];
pub const MASS_FLOOR: &str = "Mass Floor";
pub const MASS_FACE: &str = "Mass Face";

/// A mass as the geometry reads it.
#[derive(Clone, Debug)]
pub struct Mass {
    pub id: u64,
    pub guid: String,
    pub level: Option<u64>,
    pub boundary: Vec<P2>,
    pub top: Option<Vec<P2>>,
    pub base: f64,
    pub height: f64,
}

impl Mass {
    pub fn read(pr: &Project, id: u64) -> Option<Mass> {
        let e = pr.el(id)?;
        if cat(e) != "mass" {
            return None;
        }
        let level = level_of(pr, e);
        let base = level.map(|l| elev(pr, l)).unwrap_or(0.0) + numd(e, "base_offset", 0.0);
        let top_level = e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level"));
        let height = match top_level {
            Some(t) => elev(pr, t) - base,
            None => numd(e, "height", 3000.0),
        };
        Some(Mass {
            id,
            guid: pr.guid_of(id).unwrap_or_default(),
            level,
            boundary: pts(e, "boundary").unwrap_or_default(),
            top: pts(e, "top"),
            base,
            height,
        })
    }

    /// The cross section `t` of the way up (0 the footprint, 1 the top).
    pub fn ring_at(&self, t: f64) -> Vec<P2> {
        match &self.top {
            Some(top) if top.len() == self.boundary.len() => {
                self.boundary.iter().zip(top).map(|(a, b)| geom::lerp(*a, *b, t)).collect()
            }
            _ => self.boundary.clone(),
        }
    }

    /// The cross section at a height (mm above zero).
    pub fn outline_at(&self, z: f64) -> Vec<P2> {
        let t = if self.height != 0.0 { (z - self.base) / self.height } else { 0.0 };
        self.ring_at(t)
    }

    pub fn area(&self) -> f64 {
        geom::area(&self.boundary).abs()
    }

    /// Its volume, mm³: Simpson's rule on three cross sections, exact for a straight loft.
    pub fn volume(&self) -> f64 {
        let a0 = geom::area(&self.ring_at(0.0)).abs();
        let am = geom::area(&self.ring_at(0.5)).abs();
        let a1 = geom::area(&self.ring_at(1.0)).abs();
        self.height / 6.0 * (a0 + 4.0 * am + a1)
    }

    /// The top of the mass, mm above zero.
    pub fn top_z(&self) -> f64 {
        self.base + self.height
    }
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

fn mass_name(lang: &str) -> &'static str {
    match lang {
        "pt" => "Massa",
        "es" => "Masa",
        "de" => "Volumenkörper",
        "sv" => "Massa",
        "cs" => "Objem",
        "fr" => "Volume",
        "nl" => "Massa",
        "it" => "Massa",
        _ => "Mass",
    }
}

pub fn cmd_mass(s: &mut Session, p: &Value) -> R<Value> {
    let c = "mass";
    let pr = &s.project;
    let level = crate::model::level_param(pr, c, p, "level")?;
    let boundary = super::slabs::opt_boundary(p, c, "boundary")?.ok_or_else(|| "mass: `boundary` [[x, y], …] is required".to_string())?;
    if params::get(p, "top").is_some() && params::get(p, "lean").is_some() {
        return Err("mass: give `top`, an outline, or `lean`, how far the top moves sideways, not both".into());
    }
    let lean = params::opt_point(p, c, "lean")?;
    let top = super::slabs::opt_boundary(p, c, "top")?;
    let height = params::opt_num(p, c, "height")?;
    let top_level = match params::get(p, "top_level") {
        Some(v) => Some(crate::model::resolve_level(pr, c, "top_level", v)?),
        None => None,
    };
    let name = params::opt_text(p, c, "name")?;
    let base_offset = params::opt_num(p, c, "base_offset")?;
    let boundary = geom::ccw(&boundary);
    let mut top = top;
    if let Some(l) = lean {
        if l != [0.0, 0.0] {
            top = Some(boundary.iter().map(|q| geom::add(*q, l)).collect());
        }
    }
    let top = top.and_then(|t| {
        let t = if geom::area(&t) < 0.0 && t.len() == boundary.len() && false { t } else { t };
        if t == boundary {
            None
        } else {
            Some(t)
        }
    });
    let top_l = match top_level {
        Some(t) => Some(t),
        None if height.is_some() => None,
        None => crate::model::level_above(pr, level),
    };
    let name = match name {
        Some(n) => n,
        None => mass_name(&pr.language()).to_string(),
    };
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
        "name" => name,
        "level" => level_guid(pr, level),
        "boundary" => ring_v(&boundary),
        "top_level" => match top_l { Some(t) => Value::Str(level_guid(pr, t)), None => Value::Null },
        "height" => height.unwrap_or(3000.0),
        "base_offset" => base_offset.unwrap_or(0.0),
    };
    if let Some(t) = &top {
        e.set("top", ring_v(t));
    }
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    let m = Mass::read(&s.project, id).unwrap();
    Ok(jobj! {
        "area_m2" => m2(m.area()),
        "height" => m.height,
        "id" => id,
        "volume_m3" => round2(m.volume() / 1e9),
    })
}

/// A mass named by a parameter (`mass`), or the error the face commands give.
fn mass_param(pr: &Project, p: &Value, c: &str, required: bool) -> R<Option<u64>> {
    let v = match opt_ref(p, c, "mass")? {
        Some(v) => v,
        None => {
            if required {
                return Err(format!("{}: `mass`, the id of a mass, is required", c));
            }
            return Ok(None);
        }
    };
    match by_ref(pr, &v) {
        Some(id) if pr.category(id) == Some("mass") => Ok(Some(id)),
        _ => Err(format!("{}: {} isn't a mass", c, ref_word(pr, &v))),
    }
}

/// The mark a made element holds: `params[key]`.
fn mark<'a>(e: &'a Value, key: &str) -> Option<&'a Value> {
    e.get("params").and_then(|p| p.get(key))
}

fn set_mark(e: &mut Value, key: &str, v: Value) {
    crate::styles::phasing::set_param(e, key, v);
}

// ---------------------------------------------------------------- mass floors

/// The levels a mass crosses, from its base up to, not including, its top, lowest first.
pub fn slices(pr: &Project, m: &Mass) -> Vec<u64> {
    let top = m.top_z();
    crate::model::levels(pr)
        .into_iter()
        .filter(|l| {
            let z = elev(pr, *l);
            z >= m.base && z < top
        })
        .collect()
}

pub fn cmd_mass_floors(s: &mut Session, p: &Value) -> R<Value> {
    let c = "mass_floors";
    let pr = &s.project;
    let one = mass_param(pr, p, c, false)?;
    let prune = params::opt_bool(p, c, "prune")?.unwrap_or(false);
    let ty = params::opt_text(p, c, "type")?;
    let masses: Vec<u64> = match one {
        Some(id) => vec![id],
        None => pr.ids_of("mass"),
    };
    if masses.is_empty() {
        return Err("mass_floors: no mass; make one with `mass`".into());
    }
    let mut ids = Vec::new();
    let mut made = Vec::new();
    let mut updated = Vec::new();
    let mut stale = Vec::new();
    let mut removed = Vec::new();
    for mid in masses {
        let m = Mass::read(&s.project, mid).unwrap();
        let levels = slices(&s.project, &m);
        // the floors this mass made, by level
        let mine: Vec<(u64, String)> = s
            .project
            .elements
            .iter()
            .filter(|(_, e)| cat(e) == "floor")
            .filter_map(|(id, e)| {
                let mk = mark(e, MASS_FLOOR)?;
                if text(mk, "mass") != Some(m.guid.as_str()) {
                    return None;
                }
                Some((*id, text(mk, "level").unwrap_or("").to_string()))
            })
            .collect();
        for l in &levels {
            let lg = level_guid(&s.project, *l);
            let ring = m.outline_at(elev(&s.project, *l));
            if let Some((fid, _)) = mine.iter().find(|(_, g)| *g == lg) {
                let pr = &s.project;
                let mut e = pr.el(*fid).unwrap().clone();
                let before = e.clone();
                e.set("boundary", ring_v(&ring));
                if let Some(t) = &ty {
                    e.set("type", type_ref(pr, "floor", t));
                }
                if e != before {
                    s.project.elements.insert(*fid, e);
                    updated.push(*fid);
                }
                ids.push(*fid);
            } else {
                let pr = &s.project;
                let tname = ty.clone().or_else(|| default_type(pr, "floor")).unwrap_or_default();
                let mut e = jobj! {
                    "guid" => crate::rand::guid(),
                    "category" => "floor",
                    "type" => type_ref(pr, "floor", &tname),
                    "level" => lg.clone(),
                    "boundary" => ring_v(&ring),
                };
                set_mark(&mut e, MASS_FLOOR, jobj! {"level" => lg.clone(), "mass" => m.guid.clone()});
                crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
                let id = s.project.alloc_id();
                s.project.elements.insert(id, e);
                super::edits::note_made_by(id, "mass");
                made.push(id);
                ids.push(id);
            }
        }
        for (fid, lg) in &mine {
            let on = levels.iter().any(|l| level_guid(&s.project, *l) == *lg);
            if !on {
                if prune {
                    s.project.elements.remove(fid);
                    removed.push(*fid);
                } else {
                    stale.push(*fid);
                }
            }
        }
    }
    Ok(jobj! {"ids" => ids, "made" => made, "removed" => removed, "stale" => stale, "updated" => updated})
}

// ---------------------------------------------------------------- by face

/// Whether the face on edge i stands plumb (its top edge right over its bottom edge).
pub fn plumb(m: &Mass, i: usize) -> bool {
    let n = m.boundary.len();
    let Some(top) = &m.top else { return true };
    if top.len() != n {
        return true;
    }
    let (a, b) = (m.boundary[i], m.boundary[(i + 1) % n]);
    let (c, dd) = (top[i], top[(i + 1) % n]);
    let u = geom::sub(b, a);
    let l = geom::len(u);
    if l <= 0.0 {
        return false;
    }
    let off = |q: P2| geom::cross(u, geom::sub(q, a)) / l;
    off(c).abs() < 1e-6 && off(dd).abs() < 1e-6
}

/// The wall parameters for a mass's face (edge i): along the edge reversed, its exterior finish on
/// the face, as tall as the mass.
fn wall_params(pr: &Project, m: &Mass, i: usize) -> (P2, P2, u64, f64, f64) {
    let n = m.boundary.len();
    let a = m.boundary[i];
    let b = m.boundary[(i + 1) % n];
    let e = pr.el(m.id).unwrap();
    let level = level_of(pr, e).unwrap_or(0);
    (b, a, level, m.height, numd(e, "base_offset", 0.0))
}

pub fn cmd_wall_by_face(s: &mut Session, p: &Value) -> R<Value> {
    let c = "wall_by_face";
    let pr = &s.project;
    let mid = mass_param(pr, p, c, true)?.unwrap();
    let m = Mass::read(pr, mid).unwrap();
    let n = m.boundary.len();
    let faces: Vec<usize> = match params::get(p, "faces") {
        None => (0..n).collect(),
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for x in a {
                let k = match x {
                    Value::Num(crate::json::Num::U(u)) if (*u as usize) < n => *u as usize,
                    _ => {
                        return Err(format!(
                            "wall_by_face: face {} isn't an edge of the footprint: 0 to {}, from its first point",
                            x.to_compact(),
                            n.saturating_sub(1)
                        ))
                    }
                };
                if !out.contains(&k) {
                    out.push(k);
                }
            }
            out
        }
        Some(v) => return Err(format!("wall_by_face: `faces` must be a list of edge numbers, got {}", v.to_compact())),
    };
    let ty = params::opt_text(p, "wall", "type")?;
    let location = match params::opt_text(p, "wall", "location")? {
        None => "exterior-finish",
        Some(l) => match super::walls::parse_location(&l) {
            Some(x) => x,
            None => {
                return Err(format!(
                    "wall: `location` is one of centre, core-centre, exterior-finish, interior-finish, exterior-core, interior-core, not `{}`",
                    l
                ))
            }
        },
    };
    for &k in &faces {
        if !plumb(&m, k) {
            return Err(format!("wall_by_face: face {} leans, and a wall stands plumb", k));
        }
    }
    let ty = ty.or_else(|| default_type(&s.project, "wall")).unwrap_or_default();
    let mut ids = Vec::new();
    for k in faces {
        let (a, b, level, h, bo) = wall_params(&s.project, &m, k);
        let mut e = super::walls::make_wall(s, &ty, level, a, b, None, Some(h), Some(bo), None, None, Some(location), &None, &None, None);
        set_mark(&mut e, MASS_FACE, jobj! {"face" => k, "mass" => m.guid.clone()});
        let id = s.project.alloc_id();
        s.project.elements.insert(id, e);
        ids.push(id);
    }
    Ok(jobj! {"ids" => ids})
}

/// Where a face element of the top goes: its level and offset (the top level, or the mass's level
/// and its top's height over it).
fn top_place(pr: &Project, m: &Mass) -> (u64, f64) {
    let e = pr.el(m.id).unwrap();
    let level = level_of(pr, e).unwrap_or(0);
    match e.get("top_level").and_then(|v| by_ref(pr, v)).filter(|l| pr.category(*l) == Some("level")) {
        Some(t) => (t, 0.0),
        None => (level, numd(e, "base_offset", 0.0) + m.height),
    }
}

pub fn cmd_floor_by_face(s: &mut Session, p: &Value) -> R<Value> {
    let c = "floor_by_face";
    let pr = &s.project;
    let mid = mass_param(pr, p, c, true)?.unwrap();
    let ty = params::opt_text(p, "floor", "type")?;
    let m = Mass::read(pr, mid).unwrap();
    let ty = ty.or_else(|| default_type(pr, "floor")).unwrap_or_default();
    let (level, offset) = top_place(pr, &m);
    let ring = m.ring_at(1.0);
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "floor",
        "type" => type_ref(pr, "floor", &ty),
        "level" => level_guid(pr, level),
        "boundary" => ring_v(&ring),
    };
    if offset != 0.0 {
        e.set("offset", Value::f(offset));
    }
    set_mark(&mut e, MASS_FACE, jobj! {"face" => "top", "mass" => m.guid.clone()});
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let area = geom::area(&ring).abs();
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    super::edits::note_made_by(id, "mass");
    Ok(jobj! {"area_m2" => m2(area), "id" => id})
}

pub fn cmd_roof_by_face(s: &mut Session, p: &Value) -> R<Value> {
    let c = "roof_by_face";
    let pr = &s.project;
    let mid = mass_param(pr, p, c, true)?.unwrap();
    let ty = params::opt_text(p, "roof", "type")?;
    let overhang = params::opt_num(p, "roof", "overhang")?;
    let slope = params::opt_num(p, "roof", "slope")?;
    let m = Mass::read(pr, mid).unwrap();
    let ty = ty.or_else(|| default_type(pr, "roof")).unwrap_or_default();
    let (level, offset) = top_place(pr, &m);
    let ring = m.ring_at(1.0);
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "roof",
        "type" => type_ref(pr, "roof", &ty),
        "level" => level_guid(pr, level),
        "boundary" => ring_v(&ring),
        "slope" => slope.unwrap_or(0.0),
        "overhang" => overhang.unwrap_or(0.0),
        "offset" => offset,
    };
    set_mark(&mut e, MASS_FACE, jobj! {"face" => "top", "mass" => m.guid.clone()});
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    super::edits::note_made_by(id, "mass");
    Ok(jobj! {"id" => id})
}

/// The elements made by face of a mass (or of any), in id order.
fn by_face(pr: &Project, mass: Option<&str>) -> Vec<u64> {
    pr.elements
        .iter()
        .filter(|(_, e)| matches!(cat(e), "wall" | "floor" | "roof"))
        .filter(|(_, e)| match mark(e, MASS_FACE) {
            Some(mk) => mass.map(|g| text(mk, "mass") == Some(g)).unwrap_or(true),
            None => false,
        })
        .map(|(id, _)| *id)
        .collect()
}

pub fn cmd_update_by_face(s: &mut Session, p: &Value) -> R<Value> {
    let c = "update_by_face";
    let pr = &s.project;
    let mass_v = opt_ref(p, c, "mass")?;
    if mass_v.is_some() && params::get(p, "ids").is_some() {
        return Err("update_by_face: give `ids` or `mass`, not both".into());
    }
    let ids: Vec<u64> = match params::get(p, "ids") {
        None => {
            let one = mass_param(pr, p, c, false)?;
            let g = one.map(|m| pr.guid_of(m).unwrap_or_default());
            by_face(pr, g.as_deref())
        }
        Some(Value::Arr(a)) => {
            let mut out = Vec::new();
            for v in a {
                let parsed = match v {
                    Value::Num(_) => params::id_of(v).map(Value::u),
                    Value::Str(t) => {
                        let t2 = t.trim();
                        if let Ok(n) = t2.parse::<u64>() {
                            Some(Value::u(n))
                        } else {
                            crate::model::normalize_guid(t2).map(Value::Str)
                        }
                    }
                    _ => None,
                };
                let Some(pv0) = parsed else {
                    return Err(format!("update_by_face: {} is not an element id or GUID", v.to_compact()));
                };
                let Some(id) = by_ref(pr, &pv0) else {
                    return Err(format!("update_by_face: no element {}", ref_word(pr, v)));
                };
                if pr.el(id).and_then(|e| mark(e, MASS_FACE)).is_none() {
                    return Err(format!(
                        "update_by_face: {} isn't made by face; `wall_by_face`, `floor_by_face` and `roof_by_face` make them",
                        id
                    ));
                }
                out.push(id);
            }
            out
        }
        Some(_) => return Err("update_by_face: `ids` [id, …] is required".into()),
    };
    if ids.is_empty() {
        return Err("update_by_face: nothing is made by face: `wall_by_face`, `floor_by_face` and `roof_by_face` make walls, floors and roofs that follow a mass".into());
    }
    // every face first: one gone refuses the lot
    for &id in &ids {
        let pr = &s.project;
        let e = pr.el(id).unwrap();
        let mk = mark(e, MASS_FACE).unwrap();
        let Some(mid) = mk.get("mass").and_then(|g| by_ref(pr, g)).filter(|m| pr.category(*m) == Some("mass")) else {
            continue;
        };
        let m = Mass::read(pr, mid).unwrap();
        if let Some(k) = mk.get("face").and_then(|f| f.as_u64()) {
            let n = m.boundary.len();
            if k as usize >= n {
                return Err(format!(
                    "update_by_face: {} {} was made on face {} of mass {}, which has {} faces now (0 to {})",
                    cat(e),
                    id,
                    k,
                    mid,
                    n,
                    n.saturating_sub(1)
                ));
            }
        }
    }
    let mut updated = Vec::new();
    let mut unchanged = Vec::new();
    for id in ids {
        let pr = &s.project;
        let e = pr.el(id).unwrap().clone();
        let mk = mark(&e, MASS_FACE).unwrap().clone();
        let Some(mid) = mk.get("mass").and_then(|g| by_ref(pr, g)).filter(|m| pr.category(*m) == Some("mass")) else {
            unchanged.push(id);
            continue;
        };
        let m = Mass::read(pr, mid).unwrap();
        let mut ne = e.clone();
        match cat(&e) {
            "wall" => {
                let k = mk.get("face").and_then(|f| f.as_u64()).unwrap_or(0) as usize;
                let (a, b, level, h, bo) = wall_params(pr, &m, k);
                ne.set("start", pv(a));
                ne.set("end", pv(b));
                ne.set("level", Value::Str(level_guid(pr, level)));
                ne.set("height", Value::f(h));
                ne.set("base_offset", Value::f(bo));
            }
            _ => {
                let (level, offset) = top_place(pr, &m);
                ne.set("level", Value::Str(level_guid(pr, level)));
                ne.set("boundary", ring_v(&m.ring_at(1.0)));
                if cat(&e) == "floor" {
                    if offset != 0.0 {
                        put(&mut ne, super::slabs::FLOOR_ORDER, "offset", Value::f(offset));
                    } else {
                        ne.remove("offset");
                    }
                } else {
                    ne.set("offset", Value::f(offset));
                }
            }
        }
        if ne != e {
            s.project.elements.insert(id, ne);
            updated.push(id);
        } else {
            unchanged.push(id);
        }
    }
    Ok(jobj! {"unchanged" => unchanged, "updated" => updated})
}

// ---------------------------------------------------------------- show mass

/// The view a name or id names: a level's plan, a plan view, a section, an elevation, a 3D view.
fn view_of(pr: &Project, v: &Value) -> R<Option<u64>> {
    const VIEWS: &[&str] = &["level", "planview", "section", "elevation", "view3d", "camera"];
    match v {
        Value::Num(_) => match by_ref(pr, v) {
            Some(id) if pr.category(id).map(|c| VIEWS.contains(&c)).unwrap_or(false) => Ok(Some(id)),
            _ => Err(format!("show_mass: `view`: {} is not a view", v.to_compact())),
        },
        Value::Str(s) => {
            if s.eq_ignore_ascii_case("{3D}") {
                return Ok(pr.elements.iter().find(|(_, e)| cat(e) == "view3d" && text(e, "name") == Some("{3D}")).map(|(k, _)| *k).or(None));
            }
            if let Some(id) = by_ref(pr, v) {
                if pr.category(id).map(|c| VIEWS.contains(&c)).unwrap_or(false) {
                    return Ok(Some(id));
                }
            }
            for c in VIEWS {
                if let Some((id, _)) = pr.elements.iter().find(|(_, e)| cat(e) == *c && text(e, "name") == Some(s.as_str())) {
                    return Ok(Some(*id));
                }
            }
            Err(format!("show_mass: no view named `{}`", s))
        }
        _ => Err(format!("show_mass: `view`: {} is not a view", v.to_compact())),
    }
}

fn hidden_cats(e: &Value) -> Vec<String> {
    e.get("graphics")
        .and_then(|g| g.get("categories"))
        .and_then(|c| c.as_obj())
        .map(|m| m.iter().filter(|(_, o)| flag(o, "hidden") == Some(true)).map(|(k, _)| k.clone()).collect())
        .unwrap_or_default()
}

pub fn cmd_show_mass(s: &mut Session, p: &Value) -> R<Value> {
    let c = "show_mass";
    let show = params::opt_bool(p, c, "show")?;
    let pr = &s.project;
    let three_d = matches!(params::get(p, "view"), Some(Value::Str(x)) if x.eq_ignore_ascii_case("{3D}"));
    let vid = match params::get(p, "view") {
        None => crate::model::default_level(pr),
        Some(v) => view_of(pr, v)?,
    };
    let (vid, name, hidden_now) = match vid {
        Some(id) => {
            let e = pr.el(id).unwrap();
            (Some(id), text(e, "name").unwrap_or("").to_string(), hidden_cats(e).contains(&"mass".to_string()))
        }
        None => (None, "{3D}".to_string(), false),
    };
    let want_shown = show.unwrap_or(hidden_now);
    let mut vid = vid;
    if want_shown == hidden_now {
        // a change: hide or show the category in the view's graphics
        if vid.is_none() && three_d {
            let e = jobj! {"guid" => crate::rand::guid(), "category" => "view3d", "name" => "{3D}", "azimuth" => -45.0, "elevation" => 30.0};
            let id = s.project.alloc_id();
            s.project.elements.insert(id, e);
            vid = Some(id);
        }
        if let Some(id) = vid {
            let e = s.project.el_mut(id).unwrap();
            if want_shown {
                if let Some(g) = e.get_mut("graphics") {
                    if let Some(Value::Obj(cm)) = g.get_mut("categories") {
                        cm.remove("mass");
                        if cm.is_empty() {
                            g.remove("categories");
                        }
                    }
                    if g.as_obj().map(|m| m.is_empty()).unwrap_or(false) {
                        e.remove("graphics");
                    }
                }
            } else {
                if e.get("graphics").is_none() {
                    e.set("graphics", Value::obj());
                }
                let g = e.get_mut("graphics").unwrap();
                if g.get("categories").is_none() {
                    g.set("categories", Value::obj());
                }
                let cm = g.get_mut("categories").unwrap().as_obj_mut().unwrap();
                match cm.get_mut("mass") {
                    Some(o) => o.set("hidden", Value::Bool(true)),
                    None => cm.insert_sorted("mass", jobj! {"hidden" => true}),
                }
            }
        }
    }
    let hidden = vid.and_then(|id| s.project.el(id)).map(hidden_cats).unwrap_or_default();
    let shown = !hidden.contains(&"mass".to_string());
    Ok(jobj! {"hidden" => hidden, "name" => name, "shown" => shown, "view" => match vid { Some(i) => Value::u(i), None => Value::Null }})
}

// ---------------------------------------------------------------- the rules

pub fn check_mass(pr: &Project, id: u64, e: &Value) -> R<()> {
    let b = pts(e, "boundary").unwrap_or_default();
    if b.len() < 3 || b.len() > 10000 {
        return Err(format!("mass {}: a boundary needs 3 to 10000 points", id));
    }
    if !(geom::area(&b).abs() > 1.0) {
        return Err(format!("mass {}: its boundary encloses no area", id));
    }
    let m = Mass::read(pr, id).unwrap();
    let has_top_level = e.get("top_level").map(|v| !v.is_null()).unwrap_or(false);
    if !has_top_level {
        let h = numd(e, "height", 3000.0);
        if !(h > 0.0) {
            return Err(format!("mass {} height must be above zero, got {}", id, d(h)));
        }
    }
    if !(m.height > 0.0) {
        return Err(format!("mass {}: its top must be above its base", id));
    }
    if let Some(t) = &m.top {
        if t.len() != b.len() {
            return Err(format!(
                "mass {}: its top outline has {} points and its footprint {}; they pair up one for one",
                id,
                t.len(),
                b.len()
            ));
        }
        let at = geom::area(t);
        if !(at.abs() > 1.0) {
            return Err(format!("mass {} top: its boundary encloses no area", id));
        }
        if (at > 0.0) != (geom::area(&b) > 0.0) {
            return Err(format!("mass {}: its top outline runs the other way round from its footprint", id));
        }
        let ab = geom::area(&b);
        for k in 1..16 {
            let r = m.ring_at(k as f64 / 16.0);
            let a = geom::area(&r);
            if !(a * ab.signum() > 1.0) {
                return Err(format!("mass {}: lofted between its outlines it collapses {}/16 of the way up", id, k));
            }
        }
    }
    Ok(())
}
