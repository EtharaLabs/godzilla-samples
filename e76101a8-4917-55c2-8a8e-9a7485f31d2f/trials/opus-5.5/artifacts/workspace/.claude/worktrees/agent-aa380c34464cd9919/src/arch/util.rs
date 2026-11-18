//! What the architecture commands share: element and library lookups, types and their layers,
//! levels, and reading the parameters they take.

use crate::commands::params::{self, R};
use crate::geom::P2;
use crate::json::{Map, Value};
use crate::project::Project;

/// A number as Rust's Display shows it (the original's messages).
pub fn d(x: f64) -> String {
    format!("{}", x)
}

/// A point as the messages show it: [x, y].
pub fn dp(p: P2) -> String {
    format!("[{}, {}]", p[0], p[1])
}

pub fn num(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

pub fn numd(e: &Value, k: &str, dflt: f64) -> f64 {
    num(e, k).unwrap_or(dflt)
}

pub fn text<'a>(e: &'a Value, k: &str) -> Option<&'a str> {
    e.get(k).and_then(|x| x.as_str())
}

pub fn flag(e: &Value, k: &str) -> Option<bool> {
    e.get(k).and_then(|x| x.as_bool())
}

pub fn pt(e: &Value, k: &str) -> Option<P2> {
    let a = e.get(k)?.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn pts_of(v: &Value) -> Option<Vec<P2>> {
    let a = v.as_arr()?;
    let mut out = Vec::with_capacity(a.len());
    for x in a {
        let q = x.as_arr()?;
        if q.len() < 2 {
            return None;
        }
        out.push([q[0].as_f64()?, q[1].as_f64()?]);
    }
    Some(out)
}

pub fn pts(e: &Value, k: &str) -> Option<Vec<P2>> {
    pts_of(e.get(k)?)
}

pub fn rings(e: &Value, k: &str) -> Vec<Vec<P2>> {
    e.get(k).and_then(|v| v.as_arr()).map(|a| a.iter().filter_map(pts_of).collect()).unwrap_or_default()
}

pub fn pv(p: P2) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

pub fn ring_v(r: &[P2]) -> Value {
    Value::Arr(r.iter().map(|p| pv(*p)).collect())
}

pub fn rings_v(rs: &[Vec<P2>]) -> Value {
    Value::Arr(rs.iter().map(|r| ring_v(r)).collect())
}

pub fn cat(e: &Value) -> &str {
    e.get("category").and_then(|c| c.as_str()).unwrap_or("")
}

/// The category word the messages use for an element (`roomseparator` is "room separator").
pub fn cat_word(c: &str) -> String {
    match c {
        "roomseparator" => "room separator".to_string(),
        "structuralcolumn" => "structural column".to_string(),
        "stripfooting" => "strip footing".to_string(),
        "planview" => "plan view".to_string(),
        _ => c.to_string(),
    }
}

/// The element a reference (a GUID, or an id) names.
pub fn by_ref(pr: &Project, v: &Value) -> Option<u64> {
    match v {
        Value::Str(s) => {
            if let Some(id) = pr.find_guid(s) {
                return Some(id);
            }
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                if pr.elements.contains_key(&id) {
                    return Some(id);
                }
                return None;
            }
            let g = crate::model::normalize_guid(t)?;
            pr.find_guid(&g)
        }
        Value::Num(_) => {
            let id = params::id_of(v)?;
            if pr.elements.contains_key(&id) {
                Some(id)
            } else {
                None
            }
        }
        _ => None,
    }
}

/// How a reference shows in a message: the element's id when it names one, else as given.
pub fn ref_word(pr: &Project, v: &Value) -> String {
    if let Some(id) = by_ref(pr, v) {
        return id.to_string();
    }
    match v {
        Value::Str(s) => s.clone(),
        _ => v.to_compact(),
    }
}

/// The level (id) an element stands on.
pub fn level_of(pr: &Project, e: &Value) -> Option<u64> {
    let v = e.get("level")?;
    let id = by_ref(pr, v)?;
    if pr.category(id) == Some("level") {
        Some(id)
    } else {
        None
    }
}

pub fn elev(pr: &Project, level: u64) -> f64 {
    crate::model::elev(pr, level)
}

pub fn level_guid(pr: &Project, level: u64) -> String {
    pr.guid_of(level).unwrap_or_default()
}

/// The level's computation height (where walls bound its rooms), mm above it.
pub fn computation_height(pr: &Project, level: u64) -> f64 {
    pr.el(level).and_then(|e| num(e, "computation_height")).unwrap_or(1200.0)
}

/// The level's name.
pub fn level_name(pr: &Project, level: u64) -> String {
    crate::model::name(pr, level)
}

// ---------------------------------------------------------------- types

/// The section of the file holding a category's types (`types.wall`…).
pub fn types<'a>(pr: &'a Project, c: &str) -> Option<&'a Map> {
    pr.section("types").and_then(|t| t.get(c)).and_then(|x| x.as_obj())
}

/// The names of a category's types, sorted.
pub fn type_names(pr: &Project, c: &str) -> Vec<String> {
    let mut v: Vec<String> = types(pr, c).map(|m| m.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

pub fn type_def<'a>(pr: &'a Project, c: &str, name: &str) -> Option<&'a Value> {
    types(pr, c).and_then(|m| m.get(name))
}

/// The library kind of a category's types.
pub fn type_kind(c: &str) -> String {
    format!("type:{}", c)
}

/// The GUID that names a type in a file.
pub fn type_guid(pr: &Project, c: &str, name: &str) -> Option<String> {
    pr.lib_guid(&type_kind(c), name)
}

/// The name an element's `type` field holds (a GUID in a file; a name where a command left it).
pub fn type_name(pr: &Project, e: &Value) -> Option<String> {
    let v = e.get("type")?.as_str()?;
    let kind = type_kind(cat(e));
    if let Some(n) = pr
        .library
        .values()
        .find(|x| text(x, "guid") == Some(v) && text(x, "kind") == Some(kind.as_str()))
        .and_then(|x| text(x, "name"))
    {
        return Some(n.to_string());
    }
    Some(v.to_string())
}

/// The type a new element of the category takes: the usual one if the project has it, else the
/// first by name.
pub fn default_type(pr: &Project, c: &str) -> Option<String> {
    let usual = match c {
        "wall" => "Generic - 200mm",
        "floor" => "Generic - 200mm",
        "roof" => "Generic - 300mm",
        "ceiling" => "Generic - 20mm",
        "door" => "Single 900 x 2100",
        "window" => "Fixed 1200 x 1500",
        "railing" => "Railing - 1000mm",
        _ => "",
    };
    let names = type_names(pr, c);
    if names.iter().any(|n| n == usual) {
        return Some(usual.to_string());
    }
    names.first().cloned()
}

/// The value an element's `type` field takes for a type name: its GUID, or the name itself when
/// the project has no such type (the model's check then says so).
pub fn type_ref(pr: &Project, c: &str, name: &str) -> Value {
    match (type_def(pr, c, name), type_guid(pr, c, name)) {
        (Some(_), Some(g)) => Value::Str(g),
        _ => Value::s(name),
    }
}

/// The model's rule for an element's type: it must be one of its category's.
pub fn check_type(pr: &Project, id: u64, e: &Value, c: &str) -> R<()> {
    let Some(raw) = e.get("type").and_then(|t| t.as_str()) else { return Ok(()) };
    // a GUID names a type of this category's in the library; anything else is taken as a name
    let kind = type_kind(c);
    let name = pr
        .library
        .values()
        .find(|x| text(x, "guid") == Some(raw) && text(x, "kind") == Some(kind.as_str()))
        .and_then(|x| text(x, "name"))
        .map(|s| s.to_string());
    let n = name.unwrap_or_else(|| raw.to_string());
    if type_def(pr, c, &n).is_some() {
        return Ok(());
    }
    Err(format!(
        "{} {}: type `{}` doesn't exist (there are: {})",
        cat_word(c),
        id,
        n,
        type_names(pr, c).join(", ")
    ))
}

/// A wall, floor, roof or ceiling type's thickness.
pub fn thickness(pr: &Project, c: &str, name: &str) -> f64 {
    type_def(pr, c, name).and_then(|t| num(t, "thickness")).unwrap_or(0.0)
}

/// A type's layers: (function, thickness), from the exterior in (a wall) or the top down.
pub fn layers(pr: &Project, c: &str, name: &str) -> Vec<(String, f64)> {
    type_def(pr, c, name)
        .and_then(|t| t.get("layers"))
        .and_then(|l| l.as_arr())
        .map(|a| {
            a.iter()
                .map(|l| (text(l, "function").unwrap_or("").to_string(), numd(l, "thickness", 0.0)))
                .collect()
        })
        .unwrap_or_default()
}

/// The thickness of a floor or roof type's variable layer (the one that takes up a shaped top's
/// falls), if it has one.
pub fn variable_layer(pr: &Project, c: &str, name: &str) -> Option<f64> {
    type_def(pr, c, name)
        .and_then(|t| t.get("layers"))
        .and_then(|l| l.as_arr())
        .and_then(|a| a.iter().find(|l| flag(l, "variable") == Some(true)).map(|l| numd(l, "thickness", 0.0)))
}

// ---------------------------------------------------------------- parameters

/// Refuses a parameter the command doesn't take (the first by name), as the shape commands do.
pub fn known_only(p: &Value, cmd: &str, allowed: &[&str]) -> R<()> {
    if let Value::Obj(m) = p {
        let mut keys: Vec<&String> = m.items.iter().map(|(k, _)| k).collect();
        keys.sort();
        for k in keys {
            if !allowed.contains(&k.as_str()) {
                return Err(format!("{}: unknown parameter `{}`", cmd, k));
            }
        }
    }
    Ok(())
}

/// An element reference parameter (an id, or a GUID): the value to hold, or the original's error.
pub fn opt_ref(p: &Value, cmd: &str, key: &str) -> R<Option<Value>> {
    match params::get(p, key) {
        None => Ok(None),
        Some(v) => match v {
            Value::Num(_) => match params::id_of(v) {
                Some(id) => Ok(Some(Value::u(id))),
                None => Err(format!("{}: `{}` must be an element id or GUID, got {}", cmd, key, v.to_compact())),
            },
            Value::Str(s) => {
                let t = s.trim();
                if let Ok(id) = t.parse::<u64>() {
                    return Ok(Some(Value::u(id)));
                }
                match crate::model::normalize_guid(t) {
                    Some(g) => Ok(Some(Value::Str(g))),
                    None => Err(format!("{}: `{}` must be an element id or GUID, got {}", cmd, key, v.to_compact())),
                }
            }
            _ => Err(format!("{}: `{}` must be an element id or GUID, got {}", cmd, key, v.to_compact())),
        },
    }
}

/// An element by reference: its id, if the project has it.
pub fn resolve_ref(pr: &Project, v: &Value) -> Option<u64> {
    by_ref(pr, v)
}

/// What an element reference is held as in a file: the GUID of what it names, else as given.
pub fn ref_value(pr: &Project, v: &Value) -> Value {
    match by_ref(pr, v) {
        Some(id) => Value::Str(pr.guid_of(id).unwrap_or_default()),
        None => v.clone(),
    }
}

/// Rounds an area in mm² to m² with two decimals, as the replies give it.
pub fn m2(a: f64) -> f64 {
    (a.abs() / 1e6 * 100.0).round() / 100.0
}

/// Inserts a key into an element right after another one (or at the end).
pub fn insert_after(e: &mut Value, after: &str, k: &str, v: Value) {
    if let Value::Obj(m) = e {
        if let Some(slot) = m.get_mut(k) {
            *slot = v;
            return;
        }
        let pos = m.items.iter().position(|(kk, _)| kk == after).map(|i| i + 1).unwrap_or(m.items.len());
        m.items.insert(pos, (k.to_string(), v));
    }
}

/// Puts a field into an element where its struct's order puts it (`order` lists the fields
/// after `guid` and `category`).
pub fn put(e: &mut Value, order: &[&str], k: &str, v: Value) {
    let Value::Obj(m) = e else { return };
    if let Some(slot) = m.get_mut(k) {
        *slot = v;
        return;
    }
    let rank = |key: &str| order.iter().position(|o| *o == key);
    let r = rank(k).unwrap_or(usize::MAX);
    let pos = m
        .items
        .iter()
        .position(|(kk, _)| kk != "guid" && kk != "category" && rank(kk).map(|x| x > r).unwrap_or(false))
        .unwrap_or(m.items.len());
    m.items.insert(pos, (k.to_string(), v));
}
