//! What the editing commands share: reading the elements a command names, as the original reads
//! them, and small geometry helpers.

use crate::json::{Num, Value};
use crate::project::Project;
use crate::session::Session;

pub type R<T> = Result<T, String>;

/// A GUID as the editing commands take one: 8-4-4-4-12 hex digits with their dashes, in any case,
/// braces or not; lowercased as the model keeps it.
pub fn strict_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let t = match (t.strip_prefix('{'), t.ends_with('}')) {
        (Some(rest), true) => &rest[..rest.len() - 1],
        _ => t,
    };
    let parts: Vec<&str> = t.split('-').collect();
    let lens = [8, 4, 4, 4, 12];
    if parts.len() != 5 {
        return None;
    }
    for (p, n) in parts.iter().zip(lens.iter()) {
        if p.len() != *n || !p.chars().all(|c| c.is_ascii_hexdigit()) {
            return None;
        }
    }
    Some(t.to_lowercase())
}

/// An id as a number names one: a whole number from 0 below 2^64.
pub fn num_id(n: &Num) -> Option<u64> {
    match *n {
        Num::U(u) => Some(u),
        Num::I(_) => None,
        Num::F(f) => {
            if f.is_finite() && f >= 0.0 && f.fract() == 0.0 && f < 18446744073709551616.0 {
                Some(f as u64)
            } else {
                None
            }
        }
    }
}

/// One element a command names (an id, a string of one, or a GUID): its id, or the original's
/// error (`no element 5`, `"x" is not an element id or GUID`), after `cmd: `.
pub fn resolve(pr: &Project, cmd: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: {} is not an element id or GUID", cmd, v.to_compact());
    let id = match v {
        Value::Num(n) => num_id(n).ok_or_else(not)?,
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                id
            } else if let Some(g) = strict_guid(t) {
                // the nil GUID names nothing; a library entry's GUID is read as its name
                if g.chars().all(|c| c == '0' || c == '-') {
                    return Err(not());
                }
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(id);
                }
                if let Some(n) = pr.lib_name(&g) {
                    return Err(format!("{}: {} is not an element id or GUID", cmd, Value::s(&n).to_compact()));
                }
                return Err(format!("{}: no element {}", cmd, g));
            } else {
                return Err(not());
            }
        }
        _ => return Err(not()),
    };
    if pr.elements.contains_key(&id) {
        Ok(id)
    } else {
        Err(format!("{}: no element {}", cmd, id))
    }
}

/// An element named by one parameter (`id`, `to`…): `` `key` must be an element id or GUID, got …``
/// for what can't name one; `no element N` (after `` `key`: `` unless it's `id`) for one that names
/// none.
pub fn element_param(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let bad = || format!("{}: `{}` must be an element id or GUID, got {}", cmd, key, v.to_compact());
    let missing = |what: String| {
        if key == "id" {
            format!("{}: no element {}", cmd, what)
        } else {
            format!("{}: `{}`: no element {}", cmd, key, what)
        }
    };
    let id = match v {
        Value::Num(n) => num_id(n).ok_or_else(bad)?,
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                id
            } else if let Some(g) = strict_guid(t) {
                return pr.find_guid(&g).ok_or_else(|| missing(g.clone()));
            } else {
                return Err(bad());
            }
        }
        _ => return Err(bad()),
    };
    if pr.elements.contains_key(&id) {
        Ok(id)
    } else {
        Err(missing(id.to_string()))
    }
}

/// The elements a command names in `ids` (or, without it, `id`), each once, in the order named.
pub fn ids_param(pr: &Project, cmd: &str, p: &Value) -> R<Vec<u64>> {
    let list: Vec<Value> = match p.get("ids") {
        // `id`, given (even as null), names the one element
        Some(Value::Null) | None => match p.get("id") {
            None => return Err(format!("{}: `ids` [id, …] is required", cmd)),
            Some(v) => vec![v.clone()],
        },
        Some(Value::Arr(a)) => a.clone(),
        Some(_) => return Err(format!("{}: `ids` [id, …] is required", cmd)),
    };
    let mut out: Vec<u64> = Vec::new();
    for v in &list {
        let id = resolve(pr, cmd, v)?;
        if !out.contains(&id) {
            out.push(id);
        }
    }
    Ok(out)
}

/// An element's category.
pub fn cat_of(e: &Value) -> &str {
    e.get("category").and_then(|c| c.as_str()).unwrap_or("")
}

/// Rounds to a thousandth of a millimetre, as the original rounds what it works out.
pub fn r3(x: f64) -> f64 {
    let y = (x * 1000.0).round() / 1000.0;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

pub fn pt(v: Option<&Value>) -> Option<[f64; 2]> {
    let a = v?.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn ptv(p: [f64; 2]) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

/// An element as `elements` shows it (its derived values with it): what `modify` replies.
pub fn element_view(s: &Session, id: u64) -> Value {
    let cat = s.project.category(id).unwrap_or("").to_string();
    let q = crate::jobj! {"category" => cat};
    if let Ok(v) = crate::inspect::elements(s, &q) {
        if let Some(Value::Arr(a)) = v.get("elements") {
            for e in a {
                if e.get("id").and_then(|x| x.as_u64()) == Some(id) {
                    return e.clone();
                }
            }
        }
    }
    let mut e = s.project.el(id).cloned().unwrap_or(Value::Null);
    e.set("id", Value::u(id));
    e
}
