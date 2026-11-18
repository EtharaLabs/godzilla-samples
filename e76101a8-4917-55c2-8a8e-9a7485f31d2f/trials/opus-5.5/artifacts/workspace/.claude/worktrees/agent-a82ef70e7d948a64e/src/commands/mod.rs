//! The commands: their registry, dispatch, and the project-level ones.

pub mod basic;
pub mod params;

use crate::json::Value;
use crate::session::Session;
use std::sync::OnceLock;

pub struct CmdInfo {
    pub id: String,
    pub label: String,
    pub aliases: Vec<String>,
}

fn registry() -> &'static Vec<CmdInfo> {
    static REG: OnceLock<Vec<CmdInfo>> = OnceLock::new();
    REG.get_or_init(|| {
        let v = crate::json::parse(crate::catalog::CATALOG).unwrap();
        v.as_arr()
            .unwrap()
            .iter()
            .map(|c| CmdInfo {
                id: c.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string(),
                label: c.get("label").and_then(|x| x.as_str()).unwrap_or("").to_string(),
                aliases: c
                    .get("aliases")
                    .and_then(|x| x.as_arr())
                    .map(|a| a.iter().filter_map(|s| s.as_str().map(|s| s.to_string())).collect())
                    .unwrap_or_default(),
            })
            .collect()
    })
}

/// A command's id and label, from its id or one of its aliases, in any case.
pub fn resolve(id: &str) -> Option<(String, String)> {
    let reg = registry();
    let low = id.to_lowercase();
    if let Some(c) = reg.iter().find(|c| c.id.to_lowercase() == low) {
        return Some((c.id.clone(), c.label.clone()));
    }
    if let Some(c) = reg.iter().find(|c| c.aliases.iter().any(|a| a.to_lowercase() == low)) {
        return Some((c.id.clone(), c.label.clone()));
    }
    None
}

pub fn label_of(cid: &str) -> String {
    registry().iter().find(|c| c.id == cid).map(|c| c.label.clone()).unwrap_or_default()
}

/// Commands that only read the model (no undo step, no check).
pub fn changes_model(cid: &str) -> bool {
    !matches!(
        cid,
        "inspect"
            | "elements"
            | "render"
            | "measure"
            | "library"
            | "select_by_id"
            | "ids_of"
            | "filter_selection"
            | "sketch"
            | "save"
            | "autosave"
            | "circuit"
            | "conduit_fill"
            | "drain_size"
            | "vent_size"
            | "hydrant_size"
            | "load_points"
            | "water_size"
            | "storm_size"
            | "export_fill_patterns"
            | "cad_query"
    )
}

/// Undo and redo move the history themselves; opening a project starts a new one.
pub fn is_history_cmd(cid: &str) -> bool {
    matches!(cid, "undo" | "redo" | "new" | "open" | "recover" | "highrise")
}

pub fn always_step(cid: &str) -> bool {
    crate::styles::step_anyway(cid)
}

pub fn run(s: &mut Session, cid: &str, p: &Value) -> Result<Value, String> {
    if s.read_only && changes_model(cid) && !matches!(cid, "save") {
        return Err(format!("{}: this project is open read-only, so it can't be changed", cid));
    }
    if let Some(r) = crate::cloud::dispatch(s, cid, p) {
        return r;
    }
    if let Some(r) = crate::media::dispatch(s, cid, p) {
        return r;
    }
    if let Some(r) = crate::styles::dispatch(s, cid, p) {
        return r;
    }
    basic::run(s, cid, p)
}

pub fn io_err(e: &std::io::Error) -> String {
    e.to_string()
}

pub fn open_path(s: &mut Session, path: &str) -> Result<Value, String> {
    basic::open_path(s, path)
}

pub fn info(path: &str) -> Result<Value, String> {
    basic::info(path)
}

pub fn build_sample(s: &mut Session) -> Result<(), String> {
    basic::build_sample(s)
}

pub fn build_highrise(s: &mut Session, storeys: u64) -> Result<Value, String> {
    basic::build_highrise(s, storeys)
}

pub fn mcp_main(args: &[String]) {
    crate::mcp::main(args)
}
