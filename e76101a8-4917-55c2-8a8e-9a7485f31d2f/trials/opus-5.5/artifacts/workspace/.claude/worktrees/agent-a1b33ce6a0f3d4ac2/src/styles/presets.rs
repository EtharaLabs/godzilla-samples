//! Reinforcement presets: `reinforcement_preset`.
//!
//! The file keeps them in `reinforcement` (left out while there are none), each by name in name
//! order: its `kind` and the `params` `reinforce` takes for it, as given (only their names are
//! checked against the kind); the library names each (`reinforcement-preset`).

use super::common::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub const SECTION: &str = "reinforcement";
const LIB: &str = "reinforcement-preset";
pub const KINDS: &[&str] = &["beam", "column", "footing", "floor"];

/// The parameters of `reinforce` a preset of a kind may hold.
pub fn params_of(kind: &str) -> &'static [&'static str] {
    match kind {
        "beam" => &["cover", "grade", "grade_stirrup", "clearance", "bottom", "top", "stirrup", "skin", "anchor"],
        "column" => &["cover", "grade", "grade_stirrup", "clearance", "bars", "stirrup", "ties", "anchor"],
        "footing" => &["cover", "grade", "grade_stirrup", "clearance", "mesh"],
        "floor" => &["cover", "grade", "grade_stirrup", "clearance", "bottom", "top"],
        _ => &[],
    }
}

/// A preset by its name or its GUID: its kind and its params, for `reinforce {preset}`.
pub fn find(pr: &Project, name: &str) -> Option<(String, Value)> {
    let name = super::electrical::resolve(pr, LIB, name.trim());
    let e = pr.section(SECTION)?.get(&name)?;
    Some((name, e.clone()))
}

/// A preset as the model holds it: of a kind, holding only what `reinforce` takes for that kind.
fn check_preset(name: &str, kind: &str, params: &Value) -> R<()> {
    let what = format!("reinforcement preset `{}`", name);
    if !KINDS.contains(&kind) {
        return Err(format!("{}: `kind` is one of {}, not `{}`", what, KINDS.join(", "), kind));
    }
    let allowed = params_of(kind);
    if let Some(m) = params.as_obj() {
        let mut keys: Vec<&String> = m.keys().collect();
        keys.sort();
        for k in keys {
            if !allowed.contains(&k.as_str()) {
                return Err(format!("{}: `{}` isn't a parameter of a {}: {}", what, k, kind, allowed.join(", ")));
            }
        }
    }
    Ok(())
}

/// The model rules of reinforcement presets, in name order.
pub fn check(pr: &Project) -> R<()> {
    let mut presets: Vec<(String, Value)> = section(pr, SECTION).items;
    presets.sort_by(|a, b| a.0.cmp(&b.0));
    for (n, e) in &presets {
        let kind = e.get("kind").and_then(|k| k.as_str()).unwrap_or("");
        check_preset(n, kind, e.get("params").unwrap_or(&Value::Null))?;
    }
    Ok(())
}

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = cid;
    const CMD: &str = "reinforcement_preset";
    check_keys(p, CMD, &["name", "kind", "params", "rename", "delete"])?;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, CMD, "name")? else {
        return Ok(jobj! {"presets" => Value::Obj(section(pr, SECTION))});
    };
    let name = super::electrical::resolve(pr, LIB, &name);
    let existing = pr.section(SECTION).and_then(|m| m.get(&name)).cloned();
    if opt_bool(p, CMD, "delete")? == Some(true) {
        if existing.is_none() {
            return Err(format!("{}: there's no reinforcement preset `{}`", CMD, name));
        }
        let sec = pr.section_mut(SECTION);
        sec.remove(&name);
        if sec.is_empty() {
            pr.remove_top(SECTION);
        }
        lib_remove(pr, LIB, &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let rename = opt_name(p, CMD, "rename")?;
    let new = existing.is_none();
    let kind = crate::commands::params::opt_text(p, CMD, "kind")?;
    if kind.is_none() && new {
        return Err(format!("{}: `kind` (beam, column, footing, floor) is required for a new preset", CMD));
    }
    let params = match p.get("params") {
        None | Some(Value::Null) => None,
        Some(v @ Value::Obj(_)) => Some(v.clone().sorted()),
        Some(v) => {
            return Err(format!("{}: `params` must be an object of reinforce's parameters, got {}", CMD, v.to_compact()))
        }
    };
    if params.is_none() && new {
        return Err(format!("{}: `params` {{…}} is required for a new preset", CMD));
    }
    let target = rename.unwrap_or_else(|| name.clone());
    if target != name && pr.section(SECTION).map(|m| m.contains(&target)).unwrap_or(false) {
        return Err(format!("{}: there's already a reinforcement preset `{}`", CMD, target));
    }
    let old = existing.clone().unwrap_or_else(Value::obj);
    let kind = kind.or_else(|| old.get("kind").and_then(|k| k.as_str()).map(|k| k.to_string())).unwrap_or_default();
    let params = params.or_else(|| old.get("params").cloned()).unwrap_or_else(Value::obj);
    check_preset(&target, &kind, &params).map_err(|e| format!("{}: {}", CMD, e))?;
    let v = jobj! {"kind" => kind, "params" => params};
    {
        let sec = pr.section_mut(SECTION);
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
    Ok(jobj! {"name" => target, "preset" => v})
}
