//! Doors and windows: placed in a wall at a point or an offset, of one of the project's types or a
//! family's, their marks numbering on in the series they're in; the rules that they fit their
//! wall and don't overlap.

use super::util::*;
use super::walls::Wall;
use crate::commands::params::{self, R};
use crate::geom::{self, P2};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// A door's or window's size: width, height, and (for a window) its default sill.
#[derive(Clone, Copy, Debug)]
pub struct Size {
    pub width: f64,
    pub height: f64,
    pub sill: f64,
}

/// A family of a category (door or window) by name.
pub fn family<'a>(pr: &'a Project, c: &str, name: &str) -> Option<&'a Value> {
    let f = pr.section("families")?.get(name)?;
    if text(f, "category") == Some(c) {
        Some(f)
    } else {
        None
    }
}

pub fn family_names(pr: &Project, c: &str) -> Vec<String> {
    let mut v: Vec<String> = pr
        .section("families")
        .map(|m| m.iter().filter(|(_, f)| text(f, "category") == Some(c)).map(|(k, _)| k.clone()).collect())
        .unwrap_or_default();
    v.sort();
    v
}

pub fn family_types(f: &Value) -> Vec<String> {
    let mut v: Vec<String> = f.get("types").and_then(|t| t.as_obj()).map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// A family parameter's value for one of its types: the type's own, else the parameter's.
pub fn family_value(f: &Value, ty: &str, param: &str) -> Option<f64> {
    if let Some(x) = f.get("types").and_then(|t| t.get(ty)).and_then(|t| t.get(param)).and_then(|x| x.as_f64()) {
        return Some(x);
    }
    let ps = f.get("parameters")?.as_arr()?;
    let p = ps.iter().find(|p| text(p, "name") == Some(param))?;
    if let Some(x) = num(p, "value") {
        return Some(x);
    }
    // a formula of plain numbers only (the formula engine is the families' own)
    text(p, "formula").and_then(|s| s.trim().parse::<f64>().ok())
}

/// The size of an opening of a project type or a family's type.
pub fn size_of(pr: &Project, c: &str, family_name: Option<&str>, ty: &str) -> Size {
    match family_name {
        Some(fname) => {
            let f = pr.section("families").and_then(|m| m.get(fname));
            let get = |k: &str| f.and_then(|f| family_value(f, ty, k));
            Size {
                width: get("Width").unwrap_or(0.0),
                height: get("Height").unwrap_or(0.0),
                sill: if c == "window" { get("Sill Height").unwrap_or(0.0) } else { 0.0 },
            }
        }
        None => {
            let t = type_def(pr, c, ty);
            Size {
                width: t.and_then(|t| num(t, "width")).unwrap_or(0.0),
                height: t.and_then(|t| num(t, "height")).unwrap_or(0.0),
                sill: t.and_then(|t| num(t, "sill")).unwrap_or(0.0),
            }
        }
    }
}

/// The family name an opening's `family` field holds (a GUID in a file).
pub fn family_name_of(pr: &Project, e: &Value) -> Option<String> {
    let v = e.get("family")?.as_str()?;
    if let Some(n) = pr.library.values().find(|x| text(x, "guid") == Some(v) && text(x, "kind") == Some("family")).and_then(|x| text(x, "name")) {
        return Some(n.to_string());
    }
    Some(v.to_string())
}

/// The type name of an opening of a family (its `type` is the family type's GUID).
pub fn family_type_of(pr: &Project, e: &Value, fname: &str) -> Option<String> {
    let v = e.get("type")?.as_str()?;
    if let Some(n) = pr.library.values().find(|x| text(x, "guid") == Some(v) && text(x, "kind") == Some("family-type")).and_then(|x| text(x, "name")) {
        let prefix = format!("{}: ", fname);
        return Some(n.strip_prefix(&prefix).unwrap_or(n).to_string());
    }
    Some(v.to_string())
}

/// An opening's size as it stands in the model.
pub fn opening_size(pr: &Project, e: &Value) -> Size {
    let c = cat(e);
    match family_name_of(pr, e) {
        Some(f) => {
            let ty = family_type_of(pr, e, &f).unwrap_or_default();
            size_of(pr, c, Some(&f), &ty)
        }
        None => {
            let ty = type_name(pr, e).unwrap_or_default();
            size_of(pr, c, None, &ty)
        }
    }
}

// ---------------------------------------------------------------- marks

/// The next mark of a category: on in the series most of its marks are in (at least two of them,
/// and more than are plain numbers), else the next plain number.
pub fn next_mark(pr: &Project, c: &str) -> String {
    next_series(pr, c, "mark")
}

/// The next value of a numbering field (a door's mark, a room's number) for a category.
pub fn next_series(pr: &Project, c: &str, field: &str) -> String {
    use std::collections::BTreeMap;
    // prefix -> (count, max, width)
    let mut series: BTreeMap<String, (usize, u64, usize)> = BTreeMap::new();
    for e in pr.elements.values() {
        if cat(e) != c {
            continue;
        }
        let Some(m) = text(e, field) else { continue };
        let m = m.trim();
        let digits: String = m.chars().rev().take_while(|ch| ch.is_ascii_digit()).collect::<Vec<_>>().into_iter().rev().collect();
        if digits.is_empty() {
            continue;
        }
        let prefix = &m[..m.len() - digits.len()];
        let Ok(n) = digits.parse::<u64>() else { continue };
        let ent = series.entry(prefix.to_string()).or_insert((0, 0, 0));
        ent.0 += 1;
        ent.1 = ent.1.max(n);
        ent.2 = ent.2.max(digits.len());
    }
    let plain = series.get("").copied().unwrap_or((0, 0, 0));
    let mut best: Option<(&String, (usize, u64, usize))> = None;
    for (k, v) in &series {
        if k.is_empty() {
            continue;
        }
        match best {
            None => best = Some((k, *v)),
            Some((_, b)) => {
                if v.0 > b.0 || (v.0 == b.0 && v.1 > b.1) {
                    best = Some((k, *v));
                }
            }
        }
    }
    if let Some((k, v)) = best {
        if v.0 >= 2 && v.0 > plain.0 {
            let n = v.1.saturating_add(1);
            return format!("{}{:0width$}", k, n, width = v.2);
        }
    }
    plain.1.saturating_add(1).to_string()
}

// ---------------------------------------------------------------- placing

/// Where along a wall's location line a point falls (its offset from the start), and how far
/// from the line it is.
pub fn along(w: &Wall, p: P2) -> (f64, f64) {
    if w.is_arc() {
        let a = w.arc();
        let ang = (p[1] - a.centre[1]).atan2(p[0] - a.centre[0]);
        // the angle from the start, the way the arc turns, in [0, 2π)
        let mut da = ang - a.a0;
        let tau = std::f64::consts::TAU;
        if a.sweep < 0.0 {
            da = -da;
        }
        da = da.rem_euclid(tau);
        let sw = a.sweep.abs();
        let rad = geom::dist(p, a.centre);
        if da <= sw {
            return (da * a.radius, (rad - a.radius).abs());
        }
        // past an end: the nearer end
        let ds = geom::dist(p, w.start);
        let de = geom::dist(p, w.end);
        if ds <= de {
            (0.0, ds)
        } else {
            (w.length(), de)
        }
    } else {
        let t = geom::project_t(w.start, w.end, p);
        let q = geom::lerp(w.start, w.end, t);
        (t * geom::dist(w.start, w.end), geom::dist(p, q))
    }
}

/// The level's cut height (its elevation plus its view range's cut plane).
pub fn cut_height(pr: &Project, level: u64) -> f64 {
    let e = pr.el(level);
    let cut = e.and_then(|e| e.get("view_range")).and_then(|v| num(v, "cut")).unwrap_or(1200.0);
    elev(pr, level) + cut
}

/// The wall under a point on a level's plan: the nearest within its half thickness and 100 mm.
pub fn wall_at(pr: &Project, c: &str, level: u64, p: P2) -> R<(u64, f64)> {
    let z = cut_height(pr, level);
    let mut best: Option<(f64, u64, f64)> = None;
    let mut other: Option<(f64, Wall)> = None;
    for w in Wall::all(pr) {
        let (off, dd) = along(&w, p);
        if dd > w.thickness / 2.0 + 100.0 {
            continue;
        }
        if w.spans(pr, z) {
            if best.map(|b| dd < b.0).unwrap_or(true) {
                best = Some((dd, w.id, off));
            }
        } else if other.as_ref().map(|o| dd < o.0).unwrap_or(true) {
            other = Some((dd, w));
        }
    }
    if let Some((_, id, off)) = best {
        return Ok((id, off));
    }
    let lname = level_name(pr, level);
    match other {
        Some((_, w)) => Err(format!(
            "{}: no wall at {} on {}; wall {} stands there but spans {} to {} mm and {} cuts at {} mm: give the wall that level, or a view range that cuts it",
            c,
            dp(p),
            lname,
            w.id,
            d(w.base(pr)),
            d(w.top(pr)),
            lname,
            d(z)
        )),
        None => Err(format!("{}: no wall at {} on {}", c, dp(p), lname)),
    }
}

pub fn cmd_opening(s: &mut Session, c: &str, p: &Value) -> R<Value> {
    let pr = &s.project;
    // a family's type, or one of the project's
    let fam = params::opt_text(p, c, "family")?;
    let fv = match &fam {
        None => None,
        Some(f) => match family(pr, c, f) {
            Some(fv) => Some(fv),
            None => return Err(format!("{}: there's no {} family `{}` (there are: {})", c, c, f, family_names(pr, c).join(", "))),
        },
    };
    let ty = params::opt_text(p, c, "type")?;
    let (family_name, ty) = match (&fam, fv) {
        (Some(f), Some(fv)) => {
            let types = family_types(fv);
            let t = match ty {
                Some(t) => {
                    if !types.contains(&t) {
                        return Err(format!("{}: type `{}` doesn't exist (there are: {})", c, t, types.join(", ")));
                    }
                    t
                }
                None => types.first().cloned().unwrap_or_default(),
            };
            (Some(f.clone()), t)
        }
        _ => (
            None,
            ty.or_else(|| default_type(pr, c)).ok_or_else(|| format!("{}: the model has no types for this", c))?,
        ),
    };
    // the host: the wall given (where `at` falls along it, else its middle), or the wall at `at`
    let at = params::opt_point(p, c, "at")?;
    let wall_ref = opt_ref(p, c, "wall")?;
    let (host, at_off) = match (&wall_ref, at) {
        (Some(v), _) => {
            let id = match by_ref(pr, v) {
                Some(id) if pr.category(id) == Some("wall") => id,
                _ => return Err(format!("{}: {} is not a wall", c, ref_word(pr, v))),
            };
            let w = Wall::read(pr, id);
            let o = match (at, &w) {
                (Some(q), Some(w)) => along(w, q).0,
                _ => w.map(|w| w.length()).unwrap_or(0.0) / 2.0,
            };
            (id, o)
        }
        (None, Some(q)) => {
            let level = crate::model::level_param(pr, c, p, "level")?;
            wall_at(pr, c, level, q)?
        }
        (None, None) => return Err(format!("{}: give `at` [x, y] on a wall, or `wall` with `offset`", c)),
    };
    let offset = params::opt_num(p, c, "offset")?;
    let sill = if c == "window" { params::opt_num(p, c, "sill")? } else { None };
    let mark = params::opt_text(p, c, "mark")?;
    let flip_facing = params::opt_bool(p, c, "flip_facing")?;
    let flip_hand = params::opt_bool(p, c, "flip_hand")?;
    let off = offset.unwrap_or(at_off);
    let size = size_of(pr, c, family_name.as_deref(), &ty);
    let sill = if c == "window" { sill.unwrap_or(size.sill) } else { 0.0 };
    let mark = mark.unwrap_or_else(|| next_mark(pr, c));
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => c,
    };
    match &family_name {
        Some(f) => {
            let tg = pr.lib_guid("family-type", &format!("{}: {}", f, ty)).map(Value::Str).unwrap_or_else(|| Value::s(&ty));
            let fg = pr.lib_guid("family", f).map(Value::Str).unwrap_or_else(|| Value::s(f));
            e.set("type", tg);
            e.set("family", fg);
        }
        None => e.set("type", type_ref(pr, c, &ty)),
    }
    e.set("host", Value::Str(pr.guid_of(host).unwrap_or_default()));
    e.set("offset", Value::f(off));
    e.set("sill", Value::f(sill));
    e.set("mark", Value::s(&mark));
    e.set("flip_facing", Value::Bool(flip_facing.unwrap_or(false)));
    e.set("flip_hand", Value::Bool(flip_hand.unwrap_or(false)));
    crate::styles::phasing::stamp_new(pr, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    Ok(jobj! {"host" => host, "id" => id, "mark" => mark, "offset" => off})
}

// ---------------------------------------------------------------- the rules

/// The rules for one door or window: its type, its host, that it fits along the wall and up it.
pub fn check_opening(pr: &Project, id: u64, e: &Value) -> R<()> {
    let c = cat(e);
    match family_name_of(pr, e) {
        Some(f) => {
            let fv = family(pr, c, &f);
            let ty = family_type_of(pr, e, &f).unwrap_or_default();
            match fv {
                None => {
                    return Err(format!(
                        "{} {}: family `{}` doesn't exist (there are: {})",
                        c,
                        id,
                        f,
                        family_names(pr, c).join(", ")
                    ))
                }
                Some(fv) => {
                    let types = family_types(fv);
                    if !types.contains(&ty) {
                        return Err(format!("{} {}: type `{}` doesn't exist (there are: {})", c, id, ty, types.join(", ")));
                    }
                }
            }
        }
        None => check_type(pr, id, e, c)?,
    }
    let hv = e.get("host").cloned().unwrap_or(Value::Null);
    let host = by_ref(pr, &hv).filter(|h| pr.category(*h) == Some("wall"));
    let Some(host) = host else {
        return Err(format!("{} {}: host wall {} doesn't exist", c, id, ref_word(pr, &hv)));
    };
    let w = Wall::read(pr, host).unwrap();
    let size = opening_size(pr, e);
    let off = numd(e, "offset", 0.0);
    let len = w.length();
    if off - size.width / 2.0 < -1.0 || off + size.width / 2.0 > len + 1.0 {
        return Err(format!(
            "{} {}: {} mm wide at offset {} doesn't fit wall {}, {} mm long",
            c,
            id,
            d(size.width),
            d(off),
            host,
            d(len)
        ));
    }
    let sill = numd(e, "sill", 0.0);
    let wh = match pr.el(host) {
        Some(we) => super::hosts::height_along(pr, &w, we, off - size.width / 2.0, off + size.width / 2.0),
        None => w.top(pr) - w.base(pr),
    };
    if sill < 0.0 || sill + size.height > wh + 1.0 {
        return Err(format!(
            "{} {}: sill {} + height {} doesn't fit wall {}'s height",
            c,
            id,
            d(sill),
            d(size.height),
            host
        ));
    }
    Ok(())
}

/// No two openings of a wall overlap (along it and up it, by more than a millimetre).
pub fn check_overlaps(pr: &Project) -> R<()> {
    use std::collections::BTreeMap;
    let mut by_wall: BTreeMap<u64, Vec<(f64, f64, f64, f64, u64)>> = BTreeMap::new();
    for (id, e) in &pr.elements {
        let c = cat(e);
        if c != "door" && c != "window" {
            continue;
        }
        let Some(h) = e.get("host").and_then(|v| by_ref(pr, v)) else { continue };
        let s = opening_size(pr, e);
        let off = numd(e, "offset", 0.0);
        let sill = numd(e, "sill", 0.0);
        by_wall.entry(h).or_default().push((off - s.width / 2.0, off + s.width / 2.0, sill, sill + s.height, *id));
    }
    for (w, mut list) in by_wall {
        list.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        for i in 0..list.len() {
            for j in i + 1..list.len() {
                let a = list[i];
                let b = list[j];
                let along = a.1.min(b.1) - a.0.max(b.0);
                let up = a.3.min(b.3) - a.2.max(b.2);
                if along > 1.0 && up > 1.0 {
                    let ca = pr.category(a.4).unwrap_or("");
                    let cb = pr.category(b.4).unwrap_or("");
                    return Err(format!(
                        "{} {} and {} {} overlap in wall {}",
                        ca,
                        a.4,
                        cb,
                        b.4,
                        pr.guid_of(w).unwrap_or_default()
                    ));
                }
            }
        }
    }
    Ok(())
}
