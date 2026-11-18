//! Common lookups on the model: levels, elements by id or GUID.

use crate::json::Value;
use crate::project::Project;

/// Levels from the lowest up (ties by id).
pub fn levels(pr: &Project) -> Vec<u64> {
    crate::commands::basic::level_ids_sorted(pr)
}

pub fn elev(pr: &Project, level: u64) -> f64 {
    pr.el(level).and_then(|e| e.get("elevation")).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

pub fn name(pr: &Project, id: u64) -> String {
    pr.el(id).and_then(|e| e.get("name")).and_then(|x| x.as_str()).unwrap_or("").to_string()
}

/// The lowest level, where commands go without one.
pub fn default_level(pr: &Project) -> Option<u64> {
    levels(pr).first().copied()
}

/// The next level up from one, if any.
pub fn level_above(pr: &Project, level: u64) -> Option<u64> {
    let ls = levels(pr);
    let i = ls.iter().position(|l| *l == level)?;
    ls.get(i + 1).copied()
}

/// An element by its id (a number or a string of one) or its GUID.
pub fn find(pr: &Project, v: &Value) -> Option<u64> {
    match v {
        Value::Num(_) => {
            let id = crate::commands::params::id_of(v)?;
            if pr.elements.contains_key(&id) {
                Some(id)
            } else {
                None
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                return if pr.elements.contains_key(&id) { Some(id) } else { None };
            }
            let g = normalize_guid(t)?;
            pr.find_guid(&g)
        }
        _ => None,
    }
}

/// A GUID as the model keeps it (lowercase, hyphenated), from one with or without braces and dashes.
pub fn normalize_guid(s: &str) -> Option<String> {
    let t = s.trim().trim_start_matches('{').trim_end_matches('}');
    let hex: String = t.chars().filter(|c| *c != '-').collect();
    if hex.len() != 32 || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let h = hex.to_lowercase();
    Some(format!("{}-{}-{}-{}-{}", &h[0..8], &h[8..12], &h[12..16], &h[16..20], &h[20..32]))
}

/// A level (or a plan view, whose level it is) given by name, id or GUID.
pub fn resolve_level(pr: &Project, cmd: &str, key: &str, v: &Value) -> Result<u64, String> {
    let not = || format!("{}: `{}`: {} is not a level or a plan view", cmd, key, v.to_compact());
    match v {
        Value::Num(_) => {
            let id = find(pr, v).ok_or_else(not)?;
            level_of_view(pr, id).ok_or_else(not)
        }
        Value::Str(s) => {
            if let Some(id) = find(pr, v) {
                return level_of_view(pr, id).ok_or_else(not);
            }
            if s.trim().parse::<u64>().is_ok() || normalize_guid(s).is_some() {
                return Err(not());
            }
            for id in levels(pr) {
                if name(pr, id) == *s {
                    return Ok(id);
                }
            }
            for id in pr.ids_of("planview") {
                if name(pr, id) == *s {
                    if let Some(l) = level_of_view(pr, id) {
                        return Ok(l);
                    }
                }
            }
            let names: Vec<String> = levels(pr).iter().map(|l| name(pr, *l)).collect();
            Err(format!(
                "{}: no level or plan view named `{}` (the levels are: {})",
                cmd,
                s,
                names.join(", ")
            ))
        }
        _ => Err(not()),
    }
}

/// The level of a level, or of a plan view.
pub fn level_of_view(pr: &Project, id: u64) -> Option<u64> {
    match pr.category(id)? {
        "level" => Some(id),
        "planview" => {
            let g = pr.el(id)?.get("level")?.as_str()?.to_string();
            pr.find_guid(&g)
        }
        _ => None,
    }
}

/// A level from the params' `key`, else the lowest.
pub fn level_param(pr: &Project, cmd: &str, p: &Value, key: &str) -> Result<u64, String> {
    match crate::commands::params::get(p, key) {
        Some(v) => resolve_level(pr, cmd, key, v),
        None => default_level(pr).ok_or_else(|| format!("{}: the project has no level", cmd)),
    }
}
