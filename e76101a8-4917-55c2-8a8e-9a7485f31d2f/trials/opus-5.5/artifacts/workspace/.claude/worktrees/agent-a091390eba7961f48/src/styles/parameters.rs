//! Project parameters: `parameter`.
//!
//! The file keeps them in `parameters`, by name in name order: `{kind, categories}` (the categories
//! in name order), and the library names each (`parameter`) with its GUID. An element holds its
//! values in its `params`, by the parameter's GUID; so do schedules' fields, filters and sorts and
//! view filters' rules. Renamed, a parameter keeps its GUID and all of that follows; taken off a
//! category, that category's elements and schedules lose it; deleted, every one does. A view
//! filter with a rule on it keeps it from going.

use super::common::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const CMD: &str = "parameter";
const LIB: &str = "parameter";

/// The categories a project parameter can be for, in the order the original lists them.
pub const CATEGORIES: &[&str] = &[
    "wall",
    "floor",
    "ceiling",
    "roof",
    "door",
    "window",
    "room",
    "column",
    "component",
    "stair",
    "ramp",
    "railing",
    "mass",
    "structuralcolumn",
    "footing",
    "beam",
    "stripfooting",
    "pipe",
    "duct",
    "conduit",
    "cabletray",
    "wire",
    "downconductor",
    "groundconductor",
    "cable",
];

pub const KINDS: &[&str] = &["text", "number", "length", "yesno"];

/// Names elements hold their phase, design option, paint and mass under.
pub const RESERVED: &[&str] = &["Phase Created", "Phase Demolished", "Design Option", "Paint", "Mass Floor"];

/// The fields a category's elements have of their own (its schedule's, but the phasing ones).
pub fn own_fields(cat: &str) -> &'static [&'static str] {
    match cat {
        "wall" => &["Id", "Type", "Level", "Length", "Height", "Thickness", "Count"],
        "floor" => &["Id", "Type", "Level", "Area", "Thickness", "Offset", "Count", "Structural"],
        "ceiling" => &["Id", "Type", "Level", "Offset", "Area", "Thickness", "Count"],
        "roof" => &["Id", "Type", "Level", "Slope", "Plan Area", "Offset", "Count"],
        "door" => &["Mark", "Type", "Width", "Height", "Level", "Wall", "Family", "Operation", "Count"],
        "window" => &["Mark", "Type", "Width", "Height", "Sill", "Level", "Wall", "Family", "Operation", "Count"],
        "room" => &["Number", "Name", "Level", "Area", "Perimeter", "Count", "Unbounded Height", "Volume"],
        "column" | "structuralcolumn" => &["Id", "Type", "Level", "Width", "Depth", "Height", "Count"],
        "component" => &["Family", "Type", "Level", "Count"],
        "stair" => &["Id", "Level", "Width", "Height", "Risers", "Riser Height", "Tread", "Length", "Count"],
        "ramp" => &["Id", "Level", "Width", "Height", "Length", "Slope", "Count"],
        "railing" => &["Id", "Type", "Level", "Length", "Height", "Count"],
        "mass" => &["Name", "Level", "Height", "Area", "Volume", "Gross Floor Area", "Count"],
        "footing" => &["Id", "Type", "Level", "Width", "Depth", "Thickness", "Count"],
        "beam" | "stripfooting" => &["Id", "Type", "Level", "Length", "Width", "Depth", "System", "Count"],
        "pipe" | "conduit" | "wire" | "cable" => &["Id", "Type", "Level", "System", "Length", "Diameter", "Count"],
        "duct" | "cabletray" | "downconductor" | "groundconductor" => {
            &["Id", "Type", "Level", "System", "Length", "Width", "Depth", "Count"]
        }
        _ => &[],
    }
}

/// A category as typed (any case, spaces, `_` or `-`, plural): its key.
pub fn category_of(s: &str) -> Option<&'static str> {
    let key: String = s.chars().filter(|c| c.is_ascii_alphanumeric()).collect::<String>().to_ascii_lowercase();
    if let Some(c) = CATEGORIES.iter().find(|c| **c == key) {
        return Some(c);
    }
    let bare = key.trim_end_matches('s');
    for c in CATEGORIES {
        if c.ends_with('s') {
            if key == format!("{}es", c) {
                return Some(c);
            }
        } else if *c == bare {
            return Some(c);
        }
    }
    None
}

/// A name as a parameter may have it: a letter (or `_`) first, then letters, digits, `_` and spaces.
fn name_ok(n: &str) -> bool {
    let mut cs = n.chars();
    match cs.next() {
        Some(c) if c.is_alphabetic() || c == '_' => {}
        _ => return false,
    }
    cs.all(|c| c.is_alphanumeric() || c == '_' || c == ' ')
}

/// A parameter by its name or its GUID: its name.
pub fn resolve(pr: &Project, name: &str) -> String {
    super::electrical::resolve(pr, LIB, name)
}

/// The project parameter an element's `params` key names (its GUID, or its name): its name.
pub fn param_of_key(pr: &Project, key: &str) -> Option<String> {
    if let Some(g) = crate::model::normalize_guid(key) {
        if let Some(e) = pr.library.values().find(|e| e.get("guid").and_then(|x| x.as_str()) == Some(g.as_str())) {
            if e.get("kind").and_then(|k| k.as_str()) == Some(LIB) {
                return e.get("name").and_then(|n| n.as_str()).map(|n| n.to_string());
            }
            return None;
        }
    }
    if pr.section("parameters").map(|m| m.contains(key)).unwrap_or(false) {
        return Some(key.to_string());
    }
    None
}

/// The project parameters an element of a category may hold, in name order: (name, the GUID an
/// element's `params` keys it by, kind). For `modify`, `elements`, schedules and filters.
pub fn for_category(pr: &Project, cat: &str) -> Vec<(String, Option<String>, String)> {
    let mut out: Vec<(String, Option<String>, String)> = section(pr, "parameters")
        .items
        .into_iter()
        .filter(|(_, d)| cats_of(d).iter().any(|c| c == cat))
        .map(|(n, d)| {
            let kind = d.get("kind").and_then(|k| k.as_str()).unwrap_or("text").to_string();
            let g = pr.lib_guid(LIB, &n);
            (n, g, kind)
        })
        .collect();
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

/// The key an element's `params` holds a project parameter's value under (its GUID).
pub fn key_of(pr: &Project, name: &str) -> Option<String> {
    pr.lib_guid(LIB, name)
}

/// Whether a key of an element's `params` is this parameter's (its GUID, or its name).
fn is_key(k: &str, guid: &Option<String>, name: &str) -> bool {
    k == name || guid.as_deref() == Some(k)
}

fn cats_of(v: &Value) -> Vec<String> {
    v.get("categories")
        .and_then(|c| c.as_arr())
        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default()
}

/// Whether any element holds a value of it.
fn has_values(pr: &Project, guid: &Option<String>, name: &str) -> bool {
    pr.elements.values().any(|e| {
        e.get("params")
            .and_then(|p| p.as_obj())
            .map(|m| m.keys().any(|k| is_key(k, guid, name)))
            .unwrap_or(false)
    })
}

/// The first view filter (by name) with a rule on it, among those of these categories (any, for None).
fn filter_with_rule(pr: &Project, guid: &Option<String>, name: &str, cats: Option<&[String]>) -> Option<String> {
    let filters = section(pr, "view_filters");
    let mut names: Vec<&String> = filters.keys().collect();
    names.sort();
    for fname in names {
        let f = filters.get(fname).unwrap();
        if let Some(cats) = cats {
            let fc = cats_of(f);
            if !fc.iter().any(|c| cats.contains(c)) {
                continue;
            }
        }
        let rules = f.get("rules").and_then(|r| r.as_arr()).cloned().unwrap_or_default();
        if rules.iter().any(|r| r.get("field").and_then(|x| x.as_str()).map(|x| is_key(x, guid, name)).unwrap_or(false)) {
            return Some(fname.clone());
        }
    }
    None
}

/// Takes the parameter's values off the elements (of these categories; all, for None), and its
/// fields, filters and sorts off the schedules of them.
fn strip(pr: &mut Project, guid: &Option<String>, name: &str, cats: Option<&[String]>) {
    for e in pr.elements.values_mut() {
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        if cat == "schedule" {
            let of = e.get("of").and_then(|c| c.as_str()).unwrap_or("").to_string();
            if cats.map(|cs| cs.contains(&of)).unwrap_or(true) {
                strip_schedule(e, guid, name);
            }
            continue;
        }
        if !cats.map(|cs| cs.contains(&cat)).unwrap_or(true) {
            continue;
        }
        let mut empty = false;
        if let Some(Value::Obj(m)) = e.get_mut("params") {
            m.items.retain(|(k, _)| !is_key(k, guid, name));
            empty = m.is_empty();
        }
        if empty {
            e.remove("params");
        }
    }
}

fn strip_schedule(e: &mut Value, guid: &Option<String>, name: &str) {
    for (list, key) in [("fields", "name"), ("filters", "field"), ("sort", "field")] {
        let mut empty = false;
        if let Some(Value::Arr(a)) = e.get_mut(list) {
            let before = a.len();
            a.retain(|x| !x.get(key).and_then(|f| f.as_str()).map(|f| is_key(f, guid, name)).unwrap_or(false));
            empty = a.is_empty() && before > 0;
        }
        if empty {
            e.remove(list);
        }
    }
}

fn shown(v: &Value) -> Value {
    v.clone().sorted()
}

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = cid;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Err(format!("{}: `name` is required", CMD));
    };
    let name = resolve(pr, &name);
    let existing = pr.section("parameters").and_then(|m| m.get(&name)).cloned();
    let guid = pr.lib_guid(LIB, &name);
    if opt_bool(p, CMD, "delete")? == Some(true) {
        if existing.is_none() {
            return Err(format!("{}: there's no parameter `{}`", CMD, name));
        }
        if let Some(f) = filter_with_rule(pr, &guid, &name, None) {
            return Err(format!(
                "{}: view filter `{}` has a rule on `{}`; take the rule off before the parameter goes",
                CMD, f, name
            ));
        }
        strip(pr, &guid, &name, None);
        pr.section_mut("parameters").remove(&name);
        lib_remove(pr, LIB, &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let kind = match p.get("kind") {
        None | Some(Value::Null) => None,
        Some(Value::Str(k)) if KINDS.contains(&k.as_str()) => Some(k.clone()),
        Some(v) => {
            return Err(format!("{}: `kind`: {} isn't one of {}", CMD, v.to_compact(), KINDS.join(", ")));
        }
    };
    let old_kind = existing.as_ref().and_then(|e| e.get("kind")).and_then(|k| k.as_str()).map(|k| k.to_string());
    if let (Some(k), Some(ok)) = (&kind, &old_kind) {
        if k != ok && has_values(pr, &guid, &name) {
            return Err(format!(
                "{}: `{}` has values of its kind; take them away before it holds another",
                CMD, name
            ));
        }
    }
    let cats: Option<Vec<String>> = match p.get("categories") {
        None | Some(Value::Null) => None,
        Some(Value::Arr(a)) if a.iter().all(|x| matches!(x, Value::Str(_))) => {
            let mut out: Vec<String> = Vec::new();
            for x in a {
                let t = x.as_str().unwrap();
                let c = category_of(t).ok_or_else(|| {
                    format!("{}: `{}` isn't a category it can be for; there are {}", CMD, t, CATEGORIES.join(", "))
                })?;
                if !out.iter().any(|o| o == c) {
                    out.push(c.to_string());
                }
            }
            out.sort();
            Some(out)
        }
        Some(v) => return Err(format!("{}: `categories` is a list of categories, not {}", CMD, v.to_compact())),
    };
    let old_cats = existing.as_ref().map(cats_of).unwrap_or_default();
    let removed: Vec<String> = match (&cats, &existing) {
        (Some(c), Some(_)) => old_cats.iter().filter(|o| !c.contains(o)).cloned().collect(),
        _ => Vec::new(),
    };
    if !removed.is_empty() {
        if let Some(f) = filter_with_rule(pr, &guid, &name, Some(&removed)) {
            return Err(format!(
                "{}: view filter `{}` has a rule on `{}`; take the rule off before the parameter goes",
                CMD, f, name
            ));
        }
    }
    let rename = match crate::commands::params::opt_text(p, CMD, "rename")? {
        None => None,
        Some(r) => {
            let t = r.trim();
            if t.is_empty() {
                return Err(format!("{}: `rename` needs a name", CMD));
            }
            Some(t.to_string())
        }
    };
    let target = rename.unwrap_or_else(|| name.clone());
    if target != name && pr.section("parameters").map(|m| m.contains(&target)).unwrap_or(false) {
        return Err(format!("{}: there's a parameter `{}` already", CMD, target));
    }
    let what = format!("{} `{}`", CMD, target);
    if !name_ok(&target) {
        return Err(format!(
            "{}: a name starts with a letter and holds letters, digits, `_` and spaces, up to 256",
            what
        ));
    }
    if RESERVED.contains(&target.as_str()) {
        return Err(format!(
            "{}: elements hold their phase, their design option, their paint and their mass under that name; name it otherwise",
            what
        ));
    }
    let cats = cats.unwrap_or_else(|| old_cats.clone());
    if cats.is_empty() {
        return Err(format!("{}: it needs a category: one of {}", what, CATEGORIES.join(", ")));
    }
    for c in &cats {
        if own_fields(c).contains(&target.as_str()) {
            return Err(format!("{}: {}s have a `{}` of their own; name it otherwise", what, c, target));
        }
    }
    if cats.iter().any(|c| c == "component") {
        if let Some(f) = family_with_param(pr, &target) {
            return Err(format!("{}: family `{}` has a parameter of that name; name it otherwise", what, f));
        }
    }
    let kind = kind.or(old_kind).unwrap_or_else(|| "text".to_string());
    if !removed.is_empty() {
        strip(pr, &guid, &name, Some(&removed));
    }
    if target != name {
        // values kept by name follow it (GUID keys need nothing)
        for e in pr.elements.values_mut() {
            if let Some(Value::Obj(m)) = e.get_mut("params") {
                for (k, _) in m.items.iter_mut() {
                    if *k == name && guid.as_deref() != Some(k.as_str()) {
                        *k = target.clone();
                    }
                }
            }
        }
    }
    let mut m = Map::new();
    m.insert("kind", Value::Str(kind));
    m.insert("categories", Value::Arr(cats.iter().map(|c| Value::Str(c.clone())).collect()));
    let v = Value::Obj(m);
    {
        let sec = pr.section_mut("parameters");
        if target != name {
            sec.remove(&name);
        }
        sec.insert_sorted(&target, v.clone());
    }
    if existing.is_some() {
        if target != name {
            lib_rename(pr, LIB, &name, &target);
        }
    } else {
        lib_ensure(pr, LIB, &target);
    }
    super::mark_step();
    Ok(jobj! {"name" => target, "parameter" => shown(&v)})
}

/// What `inspect` says of the project's parameters.
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    out.push(("parameters".into(), Value::Obj(section(&s.project, "parameters")).sorted()));
}

/// The largest number or length a value may be, either way.
const MAX_VALUE: f64 = 1e9;

/// Whether a value is one a parameter of this kind holds; else what it holds, for the error.
pub fn value_fits(kind: &str, v: &Value) -> Result<(), &'static str> {
    match kind {
        "text" => match v {
            Value::Str(s) if s.chars().count() <= 256 => Ok(()),
            _ => Err("text"),
        },
        "number" | "length" => match v {
            Value::Num(n) if n.as_f64().is_finite() && n.as_f64().abs() <= MAX_VALUE => Ok(()),
            _ => Err(if kind == "number" { "a number" } else { "a length" }),
        },
        "yesno" => match v {
            Value::Bool(_) => Ok(()),
            _ => Err("yes or no"),
        },
        _ => Ok(()),
    }
}

/// The first family (by name) with a parameter of this name.
fn family_with_param(pr: &Project, name: &str) -> Option<String> {
    let fams = section(pr, "families");
    let mut fnames: Vec<&String> = fams.keys().collect();
    fnames.sort();
    for fname in fnames {
        let has = fams
            .get(fname)
            .and_then(|f| f.get("parameters"))
            .and_then(|x| x.as_arr())
            .map(|a| a.iter().any(|x| x.get("name").and_then(|n| n.as_str()) == Some(name)))
            .unwrap_or(false);
        if has {
            return Some(fname.clone());
        }
    }
    None
}

/// A project parameter as the model holds it: a name it may have, categories it can be for (at
/// least one), none of whose elements has a field of that name of its own, nor, for components,
/// any family a parameter of it.
fn check_def(pr: &Project, name: &str, def: &Value) -> R<()> {
    let what = format!("{} `{}`", CMD, name);
    if !name_ok(name) {
        return Err(format!(
            "{}: a name starts with a letter and holds letters, digits, `_` and spaces, up to 256",
            what
        ));
    }
    if RESERVED.contains(&name) {
        return Err(format!(
            "{}: elements hold their phase, their design option, their paint and their mass under that name; name it otherwise",
            what
        ));
    }
    let cats = cats_of(def);
    for c in &cats {
        if !CATEGORIES.contains(&c.as_str()) {
            return Err(format!("{}: `{}` isn't a category it can be for; there are {}", what, c, CATEGORIES.join(", ")));
        }
    }
    if cats.is_empty() {
        return Err(format!("{}: it needs a category: one of {}", what, CATEGORIES.join(", ")));
    }
    for c in &cats {
        if own_fields(c).contains(&name) {
            return Err(format!("{}: {}s have a `{}` of their own; name it otherwise", what, c, name));
        }
    }
    if cats.iter().any(|c| c == "component") {
        if let Some(f) = family_with_param(pr, name) {
            return Err(format!("{}: family `{}` has a parameter of that name; name it otherwise", what, f));
        }
    }
    Ok(())
}

/// The names of the parameters of an element's own family (a component's, a door's…), whose
/// instance values it may hold in `params` too.
fn family_params(pr: &Project, e: &Value) -> Vec<String> {
    let Some(f) = e.get("family").and_then(|f| f.as_str()) else {
        return Vec::new();
    };
    let fname = name_of_guid(pr, "family", f).unwrap_or_else(|| f.to_string());
    pr.section("families")
        .and_then(|m| m.get(&fname))
        .and_then(|fam| fam.get("parameters"))
        .and_then(|a| a.as_arr())
        .map(|a| a.iter().filter_map(|x| x.get("name").and_then(|n| n.as_str()).map(|n| n.to_string())).collect())
        .unwrap_or_default()
}

/// The model rules of project parameters: each value an element holds is of a parameter of its
/// category, and of its kind.
pub fn check(pr: &Project) -> R<()> {
    check_project(pr)?;
    check_values(pr, &section(pr, "parameters"))?;
    check_names(pr)
}

/// What the original checks before the elements: reinforcement presets, the electrical settings
/// and the project parameters themselves.
pub fn check_project(pr: &Project) -> R<()> {
    super::presets::check(pr)?;
    super::electrical::check(pr)?;
    let params = section(pr, "parameters");
    let mut names: Vec<&String> = params.keys().collect();
    names.sort();
    for n in names {
        check_def(pr, n, params.get(n).unwrap())?;
    }
    Ok(())
}

/// What the original checks last: that no library name of these settings is a GUID.
pub fn check_names(pr: &Project) -> R<()> {
    super::electrical::check_guid_names(pr, &["voltage", "distribution-system", "wire-type", "reinforcement-preset"])
}

/// Each value an element holds is of a project parameter of its category, and of its kind.
fn check_values(pr: &Project, params: &Map) -> R<()> {
    for (id, e) in &pr.elements {
        let Some(m) = e.get("params").and_then(|p| p.as_obj()) else {
            continue;
        };
        if m.is_empty() {
            continue;
        }
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
        keys.sort_by(|a, b| a.0.cmp(&b.0));
        for (k, v) in keys {
            check_value(pr, params, e, k, v).map_err(|m| format!("{} {}: {}", cat, id, m))?;
        }
    }
    Ok(())
}

/// One value an element holds under `k`: of a project parameter of its category and of its kind
/// (phasing's, paint and mass floors are checked by their own rules); the message follows the
/// element's `category id: `.
pub fn check_value(pr: &Project, params: &Map, e: &Value, k: &str, v: &Value) -> R<()> {
    if RESERVED.contains(&k) || v.is_null() {
        return Ok(());
    }
    let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
    // a family parameter's value (by its GUID), checked by its family
    if let Some(g) = crate::model::normalize_guid(k) {
        if let Some(le) = pr.library.values().find(|x| x.get("guid").and_then(|g2| g2.as_str()) == Some(g.as_str())) {
            if le.get("kind").and_then(|x| x.as_str()) != Some(LIB) {
                return Ok(());
            }
        }
    }
    let pname = param_of_key(pr, k);
    let def = pname.as_ref().and_then(|n| params.get(n));
    let shown_name = pname.clone().unwrap_or_else(|| k.to_string());
    let Some(def) = def.filter(|d| cats_of(d).iter().any(|c| c == cat)) else {
        if pname.is_none() && family_params(pr, e).iter().any(|x| x == k) {
            return Ok(());
        }
        return Err(format!("`{}` isn't a parameter of {}s; add it with `parameter`", shown_name, cat));
    };
    let kind = def.get("kind").and_then(|k| k.as_str()).unwrap_or("text");
    if let Err(holds) = value_fits(kind, v) {
        return Err(format!("`{}` holds {}, not {}", shown_name, holds, v.to_compact()));
    }
    Ok(())
}
