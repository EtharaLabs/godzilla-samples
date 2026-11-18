//! `inspect` (and so `info x.bimcraft`): the project's levels, element counts, types, families,
//! materials and pictures, view filters and templates, the settings the styles keep, warnings, its
//! name, language, file and undo history.
//!
//! What the project holds by GUID (a layer's material, a template's filters, phase and options…)
//! is shown by name, as the original shows it.

mod families;
mod names;
mod templates;
mod types;
mod warnings;

use crate::json::{Map, Value};
use crate::session::Session;

pub fn inspect(s: &Session) -> Value {
    let pr = &s.project;
    let mut m = Map::new();
    m.insert("counts", counts(pr));
    m.insert("families", families::families(pr));
    m.insert("history", s.history().into());
    m.insert("images", crate::media::material::inspect_images(pr));
    m.insert("language", pr.language().into());
    m.insert("levels", levels(pr));
    m.insert("materials", crate::media::material::inspect_materials(pr));
    m.insert("name", pr.name().into());
    m.insert("path", s.path.clone().into());
    m.insert("types", types::types(pr));
    m.insert("view_filters", templates::view_filters(pr));
    m.insert("view_templates", templates::view_templates(pr));
    m.insert("warnings", Value::Arr(warnings::warnings(pr).into_iter().map(Value::Str).collect()));
    for (k, v) in crate::styles::inspect_entries(s) {
        m.insert(&k, v);
    }
    Value::Obj(m).sorted()
}

/// How many elements of each category the project has.
fn counts(pr: &crate::project::Project) -> Value {
    let mut counts = std::collections::BTreeMap::<String, u64>::new();
    for e in pr.elements.values() {
        let c = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        *counts.entry(c).or_insert(0) += 1;
    }
    let mut m = Map::new();
    for (c, n) in counts {
        m.insert(&c, Value::u(n));
    }
    Value::Obj(m)
}

/// The levels, lowest first: each its elevation, id and name.
fn levels(pr: &crate::project::Project) -> Value {
    let levels: Vec<Value> = crate::commands::basic::level_ids_sorted(pr)
        .iter()
        .map(|id| {
            let e = pr.el(*id).unwrap();
            jobj! {"elevation" => e.get("elevation").cloned().unwrap_or(Value::Null), "id" => *id, "name" => e.get("name").cloned().unwrap_or(Value::Null)}
        })
        .collect();
    Value::Arr(levels)
}

/// `elements`, for the callers that still come here: the readers' own.
pub fn elements(s: &Session, p: &Value) -> Result<Value, String> {
    crate::readers::view::cmd_elements(s, p)
}
