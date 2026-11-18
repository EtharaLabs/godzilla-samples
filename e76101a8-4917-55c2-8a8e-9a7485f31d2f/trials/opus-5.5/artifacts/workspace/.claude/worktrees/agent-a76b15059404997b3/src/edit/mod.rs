//! Editing: modify, match_properties, move, copy, rotate, mirror, corner, split, fillet, align,
//! delete, insert, link, reload, purge, delete_type, rename_type, autosave and recover.
//!
//! `transform` moves, copies, turns and mirrors every category (and the walls joined to what
//! moves); `align` lays a picked line on a reference through the same transforms; `delete` takes
//! what goes with an element; `modify*` patches fields as `elements` shows them; `ops_*`, `corner`,
//! `split` and `fillet` trim, cut and round walls and detail lines; `insert*`, `link` and
//! `autosave` read and write other files; `purge`, `types`, `matchprops` and `library_util` work
//! on the library; `standin` holds model rules other areas own until theirs are in.

pub mod align;
pub mod autosave;
pub mod common;
pub mod corner;
pub mod delete;
pub mod fillet;
pub mod insert;
pub mod insert_elems;
pub mod insert_lib;
pub mod library_util;
pub mod link;
pub mod matchprops;
pub mod modify;
pub mod modify_de;
pub mod modify_room;
pub mod modify_schema;
pub mod ops_arcs;
pub mod ops_curves;
pub mod ops_geom;
pub mod ops_lines;
pub mod purge;
pub mod split;
pub mod standin;
pub mod transform;
pub mod types;

use crate::json::Value;
use crate::session::Session;

/// The commands this module owns.
pub const COMMANDS: &[&str] = &[
    "modify",
    "match_properties",
    "move",
    "copy",
    "rotate",
    "mirror",
    "corner",
    "split",
    "fillet",
    "align",
    "delete",
    "insert",
    "link",
    "reload",
    "purge",
    "delete_type",
    "rename_type",
    "autosave",
    "recover",
];

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    if !COMMANDS.contains(&cid) {
        return None;
    }
    // the original reads a library entry's GUID anywhere in these commands' parameters as its name
    let p = &ops_geom::lib_names(&s.project, p);
    let r = match cid {
        "modify" => modify::run(s, p),
        "match_properties" => matchprops::run(s, p),
        "move" | "copy" | "rotate" | "mirror" => transform::run(s, cid, p),
        "corner" => corner::run(s, p),
        "split" => split::run(s, p),
        "fillet" => fillet::run(s, p),
        "align" => align::run(s, p),
        "delete" => delete::run(s, p),
        "insert" => insert::run(s, p),
        "link" | "reload" => link::run(s, cid, p),
        "purge" => purge::run(s, p),
        "delete_type" | "rename_type" => types::run(s, cid, p),
        "autosave" | "recover" => autosave::run(s, cid, p),
        _ => return None,
    };
    Some(r)
}

/// Commands of this module that make an undo step even when the model is as it was.
pub fn always_step(cid: &str) -> bool {
    matches!(
        cid,
        "modify" | "delete" | "insert" | "delete_type" | "match_properties" | "move" | "copy" | "rotate" | "mirror" | "align"
    )
        || (cid == "corner" && corner::step_anyway())
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &crate::project::Project) -> Result<(), String> {
    link::check(pr)?;
    // ARCH's rules on openings, until theirs are in
    standin::check(pr)?;
    Ok(())
}
