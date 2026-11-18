//! Columns, structural columns and isolated footings; beams, strip footings and the MEP runs
//! (pipes, ducts, conduits, cable trays, wires, down and earthing conductors, cabling).
//!
//! A run is a straight element from `start` to `end` in plan; its `offset` is the height over its
//! level of its `justify` line at the start, `end_offset` at the end (level when none). Its
//! section is its type's, square to its axis, so a sloped run is `depth / cos θ` deep plumb. A
//! column (and a footing, a column laid down) stands at `at` on its level, `base_offset` over it,
//! up to its `top_level` or `height` mm tall. `geom` is where the geometry is, for whoever needs it
//! (IFC export, schedules, plans, rebar).

pub mod columns;
pub mod geom;
pub mod read;
pub mod rules;
pub mod runs;
pub mod view;

use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use crate::structure::common::R;

pub use geom::{
    column_geom, column_height, column_outline, column_span, default_justify, may_stand, run_geom, run_line,
    section, type_guid, type_name, ColumnGeom, Justify, RunGeom, RunLine, Section,
};

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "column" => columns::column(s, cid, "column", p),
        "structural_column" => columns::column(s, cid, "structuralcolumn", p),
        "footing" => columns::footing(s, cid, p),
        _ => runs::run(s, cid, p),
    }
    .map_err(clip)
}

/// The longest a command's own refusal is (the model's rules are said whole).
const MAX_ERROR: usize = 2000;

/// A command's refusal cut to its first 2000 characters, saying how many more there were.
fn clip(e: String) -> String {
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX_ERROR));
    out
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    rules::check(pr)
}

/// What `elements` shows of one besides its fields, added to `x`.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    view::element_view(pr, id, x)
}
