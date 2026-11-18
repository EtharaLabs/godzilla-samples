//! Reading the members' parameters as the original does: points of a chain, levels by name, id,
//! GUID or plan view, types by name or GUID.

use crate::commands::params::{get, mm_of};
use crate::json::Value;
use crate::project::Project;
use crate::structure::common::R;
use std::collections::HashMap;

/// A GUID as the original reads one: hyphenated (8-4-4-4-12 hex digits, any case), maybe in
/// braces, with whitespace round it; lowercase.
pub fn parse_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let t = match t.strip_prefix('{') {
        Some(inner) => inner.strip_suffix('}')?,
        None => t,
    };
    let b = t.as_bytes();
    if b.len() != 36 {
        return None;
    }
    for (i, c) in b.iter().enumerate() {
        let dash = i == 8 || i == 13 || i == 18 || i == 23;
        if dash {
            if *c != b'-' {
                return None;
            }
        } else if !c.is_ascii_hexdigit() {
            return None;
        }
    }
    Some(t.to_ascii_lowercase())
}

/// A GUID as a file holds it, lowercase; anything that isn't one as it is.
pub fn norm_ref(s: &str) -> String {
    parse_guid(s).unwrap_or_else(|| s.to_string())
}

/// The model's elements by GUID (as the file holds them, any case).
pub fn guid_index(pr: &Project) -> HashMap<String, u64> {
    let mut m = HashMap::with_capacity(pr.elements.len());
    for (id, e) in &pr.elements {
        if let Some(g) = e.get("guid").and_then(|g| g.as_str()) {
            m.entry(norm_ref(g)).or_insert(*id);
        }
    }
    m
}

/// An element by its GUID, any case, in braces or not.
pub fn element_by_guid(pr: &Project, g: &str) -> Option<u64> {
    let want = parse_guid(g)?;
    if let Some(id) = pr.find_guid(&want) {
        return Some(id);
    }
    pr.elements
        .iter()
        .find(|(_, e)| e.get("guid").and_then(|x| x.as_str()).map(norm_ref).as_deref() == Some(want.as_str()))
        .map(|(id, _)| *id)
}

/// The library entry with this GUID, any case.
pub fn lib_by_guid(pr: &Project, g: &str) -> Option<u64> {
    let want = parse_guid(g)?;
    if let Some(id) = pr.lib_find_guid(&want) {
        return Some(id);
    }
    pr.library
        .iter()
        .find(|(_, e)| e.get("guid").and_then(|x| x.as_str()).map(norm_ref).as_deref() == Some(want.as_str()))
        .map(|(id, _)| *id)
}

// ---------------------------------------------------------------- levels

fn elevation(pr: &Project, id: u64) -> f64 {
    pr.el(id).and_then(|e| e.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

fn name_of(pr: &Project, id: u64) -> String {
    pr.el(id).and_then(|e| e.get("name")).and_then(|x| x.as_str()).unwrap_or("").to_string()
}

/// The levels from the lowest up, ties by id.
pub fn levels(pr: &Project) -> Vec<u64> {
    let mut v: Vec<(f64, u64)> = pr.ids_of("level").into_iter().map(|id| (elevation(pr, id), id)).collect();
    v.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then(a.1.cmp(&b.1)));
    v.into_iter().map(|(_, id)| id).collect()
}

/// The lowest level, where a member goes without one.
pub fn default_level(pr: &Project, cmd: &str) -> R<u64> {
    levels(pr).first().copied().ok_or_else(|| format!("{}: the model has no levels", cmd))
}

/// The level a column on `level` goes up to: the lowest more than a millimetre above it.
pub fn level_above(pr: &Project, level: u64) -> Option<u64> {
    let e = elevation(pr, level);
    levels(pr).into_iter().find(|l| elevation(pr, *l) > e + 1.0)
}

/// The level of a level, or of a plan view.
fn level_of(pr: &Project, id: u64) -> Option<u64> {
    match pr.category(id)? {
        "level" => Some(id),
        "planview" => {
            let g = pr.el(id)?.get("level")?.as_str()?.to_string();
            let l = element_by_guid(pr, &g)?;
            if pr.category(l) == Some("level") {
                Some(l)
            } else {
                None
            }
        }
        _ => None,
    }
}

/// An id the way the original reads one in a number: a whole number, not negative.
fn id_of_num(x: f64) -> Option<u64> {
    if x.is_finite() && x >= 0.0 && x.fract() == 0.0 && x < 18446744073709551616.0 {
        Some(x as u64)
    } else {
        None
    }
}

/// A level given by name, id or GUID, or a plan view (its level).
pub fn level_ref(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a level or a plan view", cmd, key, v.to_compact());
    match v {
        Value::Num(n) => {
            let id = id_of_num(n.as_f64()).ok_or_else(not)?;
            level_of(pr, id).ok_or_else(not)
        }
        Value::Str(s) => {
            let t = s.trim();
            if !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit()) {
                if let Ok(id) = t.parse::<u64>() {
                    return level_of(pr, id).ok_or_else(not);
                }
            }
            if parse_guid(s).is_some() {
                if let Some(id) = element_by_guid(pr, s) {
                    return level_of(pr, id).ok_or_else(not);
                }
            }
            let ls = levels(pr);
            for id in &ls {
                if name_of(pr, *id) == *s {
                    return Ok(*id);
                }
            }
            for id in pr.ids_of("planview") {
                if name_of(pr, id) == *s {
                    if let Some(l) = level_of(pr, id) {
                        return Ok(l);
                    }
                }
            }
            let names: Vec<String> = ls.iter().map(|l| name_of(pr, *l)).collect();
            Err(format!("{}: no level or plan view named `{}` (the levels are: {})", cmd, s, names.join(", ")))
        }
        _ => Err(not()),
    }
}

/// The `level` of a command: the one given, else the lowest.
pub fn level_param(pr: &Project, cmd: &str, p: &Value) -> R<u64> {
    match get(p, "level") {
        Some(v) => level_ref(pr, cmd, "level", v),
        None => default_level(pr, cmd),
    }
}

// ---------------------------------------------------------------- points

/// A point [x, y] in mm within the model's reach.
pub fn point_of(v: &Value) -> Option<[f64; 2]> {
    let a = v.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([mm_of(&a[0])?, mm_of(&a[1])?])
}

/// `points` of a chain: a list of at least two points.
pub fn chain_points(p: &Value, cmd: &str) -> R<Vec<[f64; 2]>> {
    let a = match get(p, "points").and_then(|v| v.as_arr()) {
        Some(a) => a,
        None => return Err(format!("{}: `points` [[x, y], …] is required", cmd)),
    };
    let mut pts = Vec::with_capacity(a.len());
    for x in a {
        match point_of(x) {
            Some(pt) => pts.push(pt),
            None => return Err(format!("{}: `points`: {} is not a point [x, y] in mm", cmd, x.to_compact())),
        }
    }
    if pts.len() < 2 {
        return Err(format!("{}: `points` needs at least 2 points", cmd));
    }
    Ok(pts)
}

// ---------------------------------------------------------------- types

/// The name a `type` parameter means: a library entry's name where it is that entry's GUID,
/// else the text itself.
pub fn type_name_param(pr: &Project, s: &str) -> String {
    if parse_guid(s).is_some() {
        if let Some(id) = lib_by_guid(pr, s) {
            if let Some(n) = pr.library.get(&id).and_then(|e| e.get("name")).and_then(|n| n.as_str()) {
                return n.to_string();
            }
        }
    }
    s.to_string()
}
