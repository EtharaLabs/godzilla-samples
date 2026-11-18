//! Reading the model: inspect, elements, schedules, measure, select_by_id, ids_of, filter_selection; reading project files.
//!
//! `elements` (`view`) shows each element with what is worked out of it, each category by the
//! module that knows it: `walls` (walls, rooms, room separators), `slabs` (floors, ceilings,
//! roofs, shafts, masses), `parts` (doors, windows, components and families, columns, footings,
//! beams and runs, rebar, stairs, ramps, railings), `notes` (levels, grids, annotation, views,
//! sheets, details, links, CAD imports; and `select_by_id`, `ids_of`, `measure`). `schedule`
//! makes and reads schedules (and `filter_selection`); `crate::inspect` is `inspect`; `file`
//! reads project files.

pub mod common;
pub mod file;
pub mod notes;
pub mod parts;
pub mod schedule;
pub mod slabs;
pub mod view;
pub mod walls;

use crate::json::Value;
use crate::session::Session;

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    Some(match cid {
        "inspect" => Ok(crate::inspect::inspect(s)),
        "elements" => view::cmd_elements(s, p),
        "schedule" => schedule::cmd_schedule(s, p),
        "filter_selection" => schedule::cmd_filter_selection(s, p),
        "select_by_id" => notes::cmd_select_by_id(s, p),
        "ids_of" => notes::cmd_ids_of(s, p),
        "measure" => notes::cmd_measure(s, p),
        _ => return None,
    })
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    let _ = pr;
    Ok(())
}
