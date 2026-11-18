//! Architecture: walls, doors, windows, floors, ceilings, shafts, roofs, dormers, rooms, room separators, stairs, ramps, railings, masses and what is made from them; sketches and shapes.

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
