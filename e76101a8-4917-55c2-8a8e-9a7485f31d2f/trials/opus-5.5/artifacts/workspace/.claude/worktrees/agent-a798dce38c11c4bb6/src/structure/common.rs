//! What the structure, MEP and family commands share: where each category's types live, the
//! library kinds that name them, and making a new element.

use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use std::cell::Cell;

pub type R<T> = Result<T, String>;

/// The categories that are runs: a straight element from `start` to `end` of a type with a section.
pub const RUN_CATS: &[&str] = &[
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

/// The categories that are columns (a plan outline, a base, a height).
pub const COLUMN_CATS: &[&str] = &["column", "structuralcolumn", "footing"];

pub fn is_run(cat: &str) -> bool {
    RUN_CATS.contains(&cat)
}

/// The library kind of a category's types: `type:beam`, `type:structuralcolumn`…
pub fn type_kind(cat: &str) -> String {
    format!("type:{}", cat)
}

/// Where a category's types are in the project file's `types`: (section, sub-key for runs).
pub fn type_path(cat: &str) -> (&'static str, Option<&'static str>) {
    if let Some(c) = RUN_CATS.iter().find(|c| **c == cat) {
        return ("runs", Some(c));
    }
    let sec = match cat {
        "wall" => "wall",
        "floor" => "floor",
        "door" => "door",
        "window" => "window",
        "column" => "column",
        "roof" => "roof",
        "ceiling" => "ceiling",
        "railing" => "railing",
        "structuralcolumn" => "structural_column",
        "footing" => "footing",
        _ => "",
    };
    (sec, None)
}

/// A category's types by name (None when the project has none of it).
pub fn types_of<'a>(pr: &'a Project, cat: &str) -> Option<&'a Map> {
    let (sec, sub) = type_path(cat);
    if sec.is_empty() {
        return None;
    }
    let t = pr.section("types")?.get(sec)?;
    match sub {
        Some(k) => t.get(k)?.as_obj(),
        None => t.as_obj(),
    }
}

/// One type of a category, by name.
pub fn type_of<'a>(pr: &'a Project, cat: &str, name: &str) -> Option<&'a Value> {
    types_of(pr, cat)?.get(name)
}

/// The name of the type of a category with this GUID.
pub fn type_name_of_guid(pr: &Project, cat: &str, g: &str) -> Option<String> {
    let id = pr.lib_find_guid(g)?;
    let e = pr.library.get(&id)?;
    if e.get("kind").and_then(|k| k.as_str()) != Some(type_kind(cat).as_str()) {
        return None;
    }
    e.get("name").and_then(|n| n.as_str()).map(|s| s.to_string())
}

/// The GUID of a category's type by name.
pub fn type_guid(pr: &Project, cat: &str, name: &str) -> Option<String> {
    pr.lib_guid(&type_kind(cat), name)
}

/// The type an element of a category refers to (by its `type` GUID): (name, type value).
pub fn element_type<'a>(pr: &'a Project, e: &Value) -> Option<(String, &'a Value)> {
    let cat = e.get("category")?.as_str()?;
    let g = e.get("type")?.as_str()?;
    let name = type_name_of_guid(pr, cat, g)?;
    let t = type_of(pr, cat, &name)?;
    Some((name, t))
}

/// Puts a new element in the project under a fresh id: stamped with the session's phase and
/// design option (as every new element is), and returns its id. `e` is the element as the file
/// holds it, its `guid` first.
pub fn add_element(s: &mut Session, mut e: Value) -> u64 {
    crate::styles::phasing::stamp_new(&s.project, s.now_phase.as_deref(), s.now_option.as_deref(), &mut e);
    let id = s.project.alloc_id();
    s.project.elements.insert(id, e);
    id
}

/// A new GUID.
pub fn new_guid() -> String {
    crate::rand::guid()
}

thread_local! {
    /// Set by a command that makes an undo step even where the model is as it was.
    static STEP: Cell<bool> = const { Cell::new(false) };
}

/// A command of this module says it makes an undo step whether or not the model changed.
pub fn mark_step() {
    STEP.with(|s| s.set(true));
}

pub fn clear_step() {
    STEP.with(|s| s.set(false));
}

pub fn step_marked() -> bool {
    STEP.with(|s| s.get())
}
