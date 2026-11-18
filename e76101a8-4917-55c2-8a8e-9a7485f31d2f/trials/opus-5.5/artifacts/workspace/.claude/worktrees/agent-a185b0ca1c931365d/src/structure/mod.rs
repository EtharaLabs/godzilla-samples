//! Structure, MEP and families: columns, footings, beams, runs (pipes, ducts, conduits, trays, wires, conductors, cabling), rebar and reinforce, types, families and components, and the sizing calculators.

pub mod calc;
pub mod common;
pub mod component;
pub mod family;
pub mod formula;
pub mod members;
pub mod rebar;
pub mod reinforce;
pub mod symbols;
pub mod types;

use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// The commands this module owns.
pub const COMMANDS: &[&str] = &[
    "column",
    "structural_column",
    "footing",
    "beam",
    "strip_footing",
    "pipe",
    "duct",
    "conduit",
    "cable_tray",
    "wire",
    "down_conductor",
    "ground_conductor",
    "cabling",
    "rebar",
    "reinforce",
    "type",
    "family",
    "symbol_set",
    "component",
    "circuit",
    "conduit_fill",
    "drain_size",
    "vent_size",
    "hydrant_size",
    "load_points",
    "water_size",
    "storm_size",
];

pub fn owns(cid: &str) -> bool {
    COMMANDS.contains(&cid)
}

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    if !owns(cid) {
        return None;
    }
    common::clear_step();
    Some(match cid {
        "column" | "structural_column" | "footing" | "beam" | "strip_footing" | "pipe" | "duct" | "conduit"
        | "cable_tray" | "wire" | "down_conductor" | "ground_conductor" | "cabling" => members::run(s, cid, p),
        "rebar" => rebar::run(s, cid, p),
        "reinforce" => reinforce::run(s, cid, p),
        "type" => types::run(s, cid, p),
        "family" => family::run(s, cid, p),
        "symbol_set" => symbols::run(s, cid, p),
        "component" => component::run(s, cid, p),
        _ => calc::run(s, cid, p),
    })
}

/// Whether the command just run makes an undo step though the model is as it was.
pub fn always_step(cid: &str) -> bool {
    owns(cid) && common::step_marked()
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &Project) -> Result<(), String> {
    types::check(pr)?;
    members::check(pr)?;
    family::check(pr)?;
    component::check(pr)?;
    rebar::check(pr)?;
    reinforce::check(pr)?;
    Ok(())
}

/// What `elements` shows of an element of this module's categories besides its fields (a run's
/// axis and length, its type's name and section; a component's connectors; a bar's length and
/// weight…), added to `x`, the element as the file holds it with its `id`.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let cat = x.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
    match cat.as_str() {
        "component" => component::element_view(pr, id, x),
        "rebar" => rebar::element_view(pr, id, x),
        c if common::is_run(c) || common::COLUMN_CATS.contains(&c) => members::element_view(pr, id, x),
        _ => {}
    }
}

/// What `inspect` warns of in this module's part of the model (a lighting, outlet or switch
/// family in use holding no connector…).
pub fn warnings(pr: &Project) -> Vec<String> {
    family::warnings(pr)
}
