//! Drafting styles and project settings: line patterns and styles, fill patterns (and PAT files),
//! filled region types, text and dimension types, line weights, object styles, units, standards,
//! phases and design options, project parameters, electrical settings and reinforcement presets.

pub mod common;
pub mod electrical;
pub mod fills;
pub mod lines;
pub mod parameters;
pub mod pat;
pub mod phasing;
pub mod presets;
pub mod settings;
pub mod text;
pub mod weights;

use crate::json::Value;
use crate::session::Session;
use std::cell::Cell;

thread_local! {
    /// Set by a command that makes an undo step even where the model is as it was.
    static STEP: Cell<bool> = const { Cell::new(false) };
}

/// A command says it makes an undo step whether or not it changed the model (the original's
/// edits of a named style always do).
pub fn mark_step() {
    STEP.with(|s| s.set(true));
}

/// Whether the command just run makes an undo step though the model is as it was.
pub fn step_anyway(cid: &str) -> bool {
    owns(cid) && STEP.with(|s| s.get())
}

pub const COMMANDS: &[&str] = &[
    "line_pattern",
    "line_style",
    "fill_pattern",
    "import_fill_patterns",
    "export_fill_patterns",
    "filled_region_type",
    "text_type",
    "dimension_type",
    "line_weights",
    "object_styles",
    "units",
    "room_area",
    "language",
    "standard",
    "phase",
    "phase_filter",
    "option",
    "parameter",
    "voltage",
    "distribution_system",
    "wire_type",
    "reinforcement_preset",
];

pub fn owns(cid: &str) -> bool {
    COMMANDS.contains(&cid)
}

/// The longest error the original gives whole; past it, the rest is counted.
const MAX_ERROR: usize = 2000;

/// Marks an error the original's model check gives (after the command), which isn't clipped.
const CHECK: char = '\u{1}';

/// An error as the original's model check gives it after the command: said whole.
pub fn check_error(e: String) -> String {
    format!("{}{}", CHECK, e)
}

/// A command's error past 2000 characters: its first 2000 and how many more there were (what the
/// model's check finds is said whole).
fn clip_error(e: String) -> String {
    if let Some(rest) = e.strip_prefix(CHECK) {
        return rest.to_string();
    }
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX_ERROR));
    out
}

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    if !owns(cid) {
        return None;
    }
    STEP.with(|st| st.set(false));
    Some(run(s, cid, p).map_err(clip_error))
}

fn run(s: &mut Session, cid: &str, p: &Value) -> Result<Value, String> {
    match cid {
        "line_pattern" | "line_style" => lines::run(s, cid, p),
        "fill_pattern" | "import_fill_patterns" | "export_fill_patterns" | "filled_region_type" => fills::run(s, cid, p),
        "text_type" | "dimension_type" => text::run(s, cid, p),
        "line_weights" | "object_styles" => weights::run(s, cid, p),
        "units" | "room_area" | "language" | "standard" => settings::run(s, cid, p),
        "phase" | "phase_filter" | "option" => phasing::run(s, cid, p),
        "parameter" => parameters::run(s, cid, p),
        "voltage" | "distribution_system" | "wire_type" => electrical::run(s, cid, p),
        "reinforcement_preset" => presets::run(s, cid, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    // presets, electrical settings and project parameters; then phasing's rules, which go through
    // each element's params once, in order, the project parameters' values among them; then the
    // library's names
    parameters::check_project(pr)?;
    let params = common::section(pr, "parameters");
    phasing::check_with(pr, &|_, e, k, v| parameters::check_value(pr, &params, e, k, v))?;
    common::check_library_names(pr)?;
    parameters::check_names(pr)
}

/// What `inspect` says of the sections this module keeps: (key, value) pairs, for the core's
/// `inspect` to merge into its reply (which it prints sorted).
pub fn inspect_entries(s: &Session) -> Vec<(String, Value)> {
    let mut out = Vec::new();
    settings::inspect_entries(s, &mut out);
    phasing::inspect_entries(s, &mut out);
    parameters::inspect_entries(s, &mut out);
    electrical::inspect_entries(s, &mut out);
    out
}
