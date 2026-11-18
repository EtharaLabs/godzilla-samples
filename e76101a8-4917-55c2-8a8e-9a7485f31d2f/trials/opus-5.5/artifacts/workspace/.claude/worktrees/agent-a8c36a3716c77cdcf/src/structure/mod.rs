//! Structure, MEP and families: columns, footings, beams, runs (pipes, ducts, conduits, trays, wires, conductors, cabling), rebar and reinforce, types, families and components, and the sizing calculators.

use crate::json::Value;
use crate::session::Session;

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    let _ = (s, cid, p);
    None
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    let _ = pr;
    Ok(())
}
