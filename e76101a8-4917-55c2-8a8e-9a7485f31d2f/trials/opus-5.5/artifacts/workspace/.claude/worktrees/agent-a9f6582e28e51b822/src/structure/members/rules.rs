//! The model's rules for runs and columns, as the original checks them after every command and
//! when it opens a file: element by element in id order, each one's rules in turn.

use super::geom::{may_stand, run_line, MAX_SLOPE, TOL};
use super::read::{guid_index, lib_by_guid, norm_ref, parse_guid};
use crate::commands::params::MAX_MM;
use crate::json::Value;
use crate::project::Project;
use crate::structure::common::{is_run, type_kind, types_of, COLUMN_CATS, R};
use std::collections::HashMap;

struct Ctx<'a> {
    pr: &'a Project,
    guids: HashMap<String, u64>,
}

pub fn check(pr: &Project) -> R<()> {
    let mut ctx: Option<Ctx> = None;
    for (id, e) in &pr.elements {
        let cat = match e.get("category").and_then(|c| c.as_str()) {
            Some(c) => c,
            None => continue,
        };
        let run = is_run(cat);
        if !run && !COLUMN_CATS.contains(&cat) {
            continue;
        }
        let c = ctx.get_or_insert_with(|| Ctx { pr, guids: guid_index(pr) });
        if run {
            check_run(c, *id, cat, e)?;
        } else {
            check_column(c, *id, cat, e)?;
        }
    }
    Ok(())
}

/// The type an element names must be one of its category's.
fn check_type(c: &Ctx, id: u64, cat: &str, e: &Value) -> R<()> {
    let pr = c.pr;
    let types = types_of(pr, cat);
    let raw = match e.get("type") {
        Some(Value::Str(s)) => s.clone(),
        Some(v) => v.to_compact(),
        None => String::new(),
    };
    // a GUID of one of the category's types stands for its name
    let mut shown = raw.clone();
    if parse_guid(&raw).is_some() {
        if let Some(lid) = lib_by_guid(pr, &raw) {
            let le = &pr.library[&lid];
            if le.get("kind").and_then(|k| k.as_str()) == Some(type_kind(cat).as_str()) {
                if let Some(n) = le.get("name").and_then(|n| n.as_str()) {
                    shown = n.to_string();
                }
            }
        }
    }
    if types.map(|t| t.contains(&shown)).unwrap_or(false) {
        return Ok(());
    }
    let mut names: Vec<&String> = types.map(|t| t.keys().collect()).unwrap_or_default();
    names.sort();
    let names: Vec<&str> = names.iter().map(|s| s.as_str()).collect();
    Err(format!("{} {}: type `{}` doesn't exist (there are: {})", cat, id, shown, names.join(", ")))
}

/// A reference to a level (`level`, `top_level`) must be one.
fn check_level_ref(c: &Ctx, id: u64, cat: &str, v: Option<&Value>) -> R<()> {
    let shown = match v {
        Some(Value::Str(s)) => match c.guids.get(&norm_ref(s)) {
            Some(target) => {
                if c.pr.category(*target) == Some("level") {
                    return Ok(());
                }
                target.to_string()
            }
            None => s.clone(),
        },
        Some(v) => v.to_compact(),
        None => "null".to_string(),
    };
    Err(format!("{} {}: level {} doesn't exist", cat, id, shown))
}

/// A number the model can hold: within 1000 km.
fn usable(cat: &str, id: u64, what: &str, x: Option<f64>) -> R<()> {
    match x {
        Some(v) if !(v.is_finite() && v.abs() <= MAX_MM) => {
            Err(format!("{} {} {}: {} is not a usable number", cat, id, what, v))
        }
        _ => Ok(()),
    }
}

fn num(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

fn coord(e: &Value, k: &str, i: usize) -> Option<f64> {
    e.get(k).and_then(|p| p.as_arr()).and_then(|a| a.get(i)).and_then(|x| x.as_f64())
}

fn check_run(c: &Ctx, id: u64, cat: &str, e: &Value) -> R<()> {
    check_type(c, id, cat, e)?;
    check_level_ref(c, id, cat, e.get("level"))?;
    usable(cat, id, "start x", coord(e, "start", 0))?;
    usable(cat, id, "start y", coord(e, "start", 1))?;
    usable(cat, id, "end x", coord(e, "end", 0))?;
    usable(cat, id, "end y", coord(e, "end", 1))?;
    usable(cat, id, "offset", num(e, "offset"))?;
    usable(cat, id, "end_offset", num(e, "end_offset"))?;
    if let Some(sys) = e.get("system").and_then(|s| s.as_str()) {
        if sys.chars().count() > 256 {
            return Err(format!("{} {}: system is longer than 256 characters", cat, id));
        }
    }
    let line = match run_line(e) {
        Some(l) => l,
        None => return Ok(()),
    };
    let len = line.length();
    if len <= TOL {
        return Err(format!("{} {}: too short ({} mm)", cat, id, len));
    }
    if !may_stand(cat) {
        if line.stands() {
            return Err(format!(
                "{} {}: its ends are one over the other; a {} runs along, and what stands is a column",
                cat, id, cat
            ));
        }
        let slope = line.slope_degrees();
        if slope > MAX_SLOPE {
            return Err(format!(
                "{} {}: it slopes {:.1}°, more than the {}° a {} may; what stands is a column",
                cat, id, slope, MAX_SLOPE, cat
            ));
        }
    }
    Ok(())
}

fn check_column(c: &Ctx, id: u64, cat: &str, e: &Value) -> R<()> {
    check_type(c, id, cat, e)?;
    check_level_ref(c, id, cat, e.get("level"))?;
    usable(cat, id, "x", coord(e, "at", 0))?;
    usable(cat, id, "y", coord(e, "at", 1))?;
    usable(cat, id, "angle", num(e, "angle"))?;
    usable(cat, id, "base_offset", num(e, "base_offset"))?;
    let connected = matches!(e.get("top_level"), Some(v) if !v.is_null());
    let height = num(e, "height").unwrap_or(0.0);
    if connected {
        check_level_ref(c, id, cat, e.get("top_level"))?;
    } else {
        usable(cat, id, "height", Some(height))?;
        if height <= 0.0 {
            return Err(format!("{} {} height must be above zero, got {}", cat, id, height));
        }
    }
    let pr = c.pr;
    let elev = |key: &str| -> f64 {
        e.get(key)
            .and_then(|g| g.as_str())
            .and_then(|g| c.guids.get(&norm_ref(g)))
            .and_then(|l| pr.el(*l))
            .and_then(|l| l.get("elevation"))
            .and_then(|x| x.as_f64())
            .unwrap_or(0.0)
    };
    let base = elev("level") + num(e, "base_offset").unwrap_or(0.0);
    let top = if connected { elev("top_level") } else { base + height };
    if top <= base + TOL {
        return Err(format!("{} {}: its top must be above its base", cat, id));
    }
    Ok(())
}
