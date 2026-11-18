//! Architecture: walls, doors, windows, floors, ceilings, shafts, roofs, dormers, rooms, room separators, stairs, ramps, railings, masses and what is made from them; sketches and shapes.

pub mod dormer;
pub mod edits;
pub mod falls;
pub mod hosts;
pub mod mass;
pub mod openings;
pub mod outline;
pub mod roofs;
pub mod shape;
pub mod rooms;
pub mod sketchcmd;
pub mod slabs;
pub mod stairs;
pub mod util;
pub mod walls;

use crate::json::Value;
use crate::session::Session;

pub const COMMANDS: &[&str] = &[
    "wall",
    "door",
    "window",
    "flip",
    "floor",
    "ceiling",
    "shaft",
    "roof",
    "dormer",
    "room",
    "room_separator",
    "stair",
    "ramp",
    "railing",
    "mass",
    "mass_floors",
    "wall_by_face",
    "floor_by_face",
    "roof_by_face",
    "update_by_face",
    "show_mass",
    "sketch",
    "edit_boundary",
    "edit_shape",
    "add_point",
    "add_split_line",
    "reset_shape",
    "falls",
];

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    if !COMMANDS.contains(&cid) {
        return None;
    }
    edits::reset();
    Some(match cid {
        "wall" => walls::cmd_wall(s, p),
        "door" => openings::cmd_opening(s, "door", p),
        "window" => openings::cmd_opening(s, "window", p),
        "flip" => walls::cmd_flip(s, p),
        "floor" => slabs::cmd_floor(s, p),
        "ceiling" => slabs::cmd_ceiling(s, p),
        "shaft" => slabs::cmd_shaft(s, p),
        "roof" => roofs::cmd_roof(s, p),
        "dormer" => dormer::cmd_dormer(s, p),
        "room" => rooms::cmd_room(s, p),
        "room_separator" => rooms::cmd_separator(s, p),
        "stair" => stairs::cmd_stair(s, p),
        "ramp" => stairs::cmd_ramp(s, p),
        "railing" => stairs::cmd_railing(s, p),
        "mass" => mass::cmd_mass(s, p),
        "mass_floors" => mass::cmd_mass_floors(s, p),
        "wall_by_face" => mass::cmd_wall_by_face(s, p),
        "floor_by_face" => mass::cmd_floor_by_face(s, p),
        "roof_by_face" => mass::cmd_roof_by_face(s, p),
        "update_by_face" => mass::cmd_update_by_face(s, p),
        "show_mass" => mass::cmd_show_mass(s, p),
        "sketch" => sketchcmd::cmd_sketch(s, p),
        "edit_boundary" => sketchcmd::cmd_edit_boundary(s, p),
        "edit_shape" => shape::cmd_edit_shape(s, p),
        "add_point" => shape::cmd_add_point(s, p),
        "add_split_line" => shape::cmd_add_split_line(s, p),
        "reset_shape" => shape::cmd_reset_shape(s, p),
        "falls" => falls::cmd_falls(s, p),
        _ => return None,
    })
}

/// The engine's judgment of the outlines the command just ran made or changed (before the
/// model's check): see `edits`.
pub fn check_edits(before: &crate::project::Project, after: &crate::project::Project, cid: &str) -> Result<(), String> {
    edits::check_edits(before, after, cid)
}

/// The model rules this module owns, checked after every command: each element's own, in id
/// order, then those across elements.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    for (id, e) in &pr.elements {
        match util::cat(e) {
            "wall" => walls::check_wall(pr, *id, e)?,
            "door" | "window" => openings::check_opening(pr, *id, e)?,
            "floor" => slabs::check_floor(pr, *id, e)?,
            "ceiling" => slabs::check_ceiling(pr, *id, e)?,
            "shaft" => slabs::check_shaft(pr, *id, e)?,
            "roof" => roofs::check_roof(pr, *id, e)?,
            "room" => rooms::check_room(pr, *id, e)?,
            "stair" => stairs::check_stair(pr, *id, e)?,
            "ramp" => stairs::check_ramp(pr, *id, e)?,
            "railing" => stairs::check_railing(pr, *id, e)?,
            "mass" => mass::check_mass(pr, *id, e)?,
            _ => {}
        }
    }
    openings::check_overlaps(pr)?;
    Ok(())
}
