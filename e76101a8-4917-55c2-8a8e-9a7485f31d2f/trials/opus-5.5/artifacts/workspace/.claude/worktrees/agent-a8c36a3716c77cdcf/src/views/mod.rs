//! Views and annotation: sections, elevations, sheets, viewports, view settings and graphics, filters, templates, 3D views and cameras; text, dimensions, tags, spots, detail lines, regions and groups.

pub mod common;
pub mod model;

// views of the model and of paper
pub mod plans;
pub mod sections;
pub mod sheets;
pub mod view3d;

// how views draw
pub mod filters;
pub mod graphics;
pub mod templates;

// dimensions
pub mod constraints;
pub mod dims;
pub mod dims3d;

// notes, tags, spots, linework
pub mod linework;
pub mod notes;
pub mod spots;
pub mod tags;

// detail lines
pub mod curves;
pub mod lineedit;
pub mod lines;

// regions, groups, patterns made of lines
pub mod groups;
pub mod makepat;
pub mod regions;

use crate::json::Value;
use crate::project::Project;
use crate::session::Session;
use std::cell::Cell;

thread_local! {
    /// Set by a command that makes an undo step even where the model is as it was.
    static STEP: Cell<bool> = const { Cell::new(false) };
}

/// A command of this module says it makes an undo step whether or not it changed the model.
pub fn mark_step() {
    STEP.with(|s| s.set(true));
}

/// Whether the command just run makes an undo step though the model is as it was.
pub fn always_step(cid: &str) -> bool {
    owns(cid) && STEP.with(|s| s.get())
}

pub const COMMANDS: &[&str] = &[
    "section",
    "elevation",
    "sheet",
    "place",
    "crop",
    "duplicate_view",
    "scale",
    "detail",
    "visual_style",
    "graphics",
    "filter",
    "template",
    "section_box",
    "perspective",
    "graphic_display_options",
    "camera",
    "work_plane",
    "text",
    "dimension",
    "dimension_3d",
    "dimension_constraint",
    "dimension_text",
    "dimension_value",
    "tag",
    "spot",
    "spot_slope",
    "detail_line",
    "join_polyline",
    "explode",
    "vertex",
    "convert_spline",
    "offset",
    "trim_extend",
    "filled_region",
    "create_group",
    "detail_group",
    "repeating_detail",
    "ungroup",
    "group_type",
    "linework",
    "make_fill_pattern",
];

pub fn owns(cid: &str) -> bool {
    COMMANDS.contains(&cid)
}

/// Runs the commands this module owns; None for the others.
pub fn dispatch(s: &mut Session, cid: &str, p: &Value) -> Option<Result<Value, String>> {
    if !owns(cid) {
        return None;
    }
    STEP.with(|st| st.set(false));
    Some(match cid {
        "section" | "elevation" => sections::run(s, cid, p),
        "sheet" | "place" => sheets::run(s, cid, p),
        "crop" | "duplicate_view" => plans::run(s, cid, p),
        "section_box" | "perspective" | "graphic_display_options" | "camera" | "work_plane" => view3d::run(s, cid, p),
        "graphics" | "scale" | "detail" | "visual_style" => graphics::run(s, cid, p),
        "filter" => filters::run(s, cid, p),
        "template" => templates::run(s, cid, p),
        "dimension" => dims::run(s, cid, p),
        "dimension_3d" => dims3d::run(s, cid, p),
        "dimension_constraint" | "dimension_text" | "dimension_value" => constraints::run(s, cid, p),
        "text" => notes::run(s, cid, p),
        "tag" => tags::run(s, cid, p),
        "spot" | "spot_slope" => spots::run(s, cid, p),
        "linework" => linework::run(s, cid, p),
        "detail_line" => lines::run(s, cid, p),
        "join_polyline" | "explode" | "vertex" | "convert_spline" | "offset" | "trim_extend" => lineedit::run(s, cid, p),
        "filled_region" => regions::run(s, cid, p),
        "create_group" | "detail_group" | "repeating_detail" | "ungroup" | "group_type" => groups::run(s, cid, p),
        "make_fill_pattern" => makepat::run(s, cid, p),
        _ => Err(format!("{}: not supported here", cid)),
    })
}

/// The model rules this module owns, checked after every command.
pub fn check(pr: &Project) -> Result<(), String> {
    sections::check(pr)?;
    sheets::check(pr)?;
    plans::check(pr)?;
    view3d::check(pr)?;
    graphics::check(pr)?;
    filters::check(pr)?;
    templates::check(pr)?;
    dims::check(pr)?;
    dims3d::check(pr)?;
    constraints::check(pr)?;
    notes::check(pr)?;
    tags::check(pr)?;
    spots::check(pr)?;
    linework::check(pr)?;
    lines::check(pr)?;
    lineedit::check(pr)?;
    regions::check(pr)?;
    groups::check(pr)?;
    makepat::check(pr)?;
    Ok(())
}

/// Run after every command that changes the model, before the check: what a constrained
/// dimension measures to moves with what the command moved (or the command is refused).
pub fn keep(pr: &mut Project) -> Result<(), String> {
    constraints::keep(pr)
}

/// What `elements` shows of an element of this module's categories beyond its own fields (a
/// section's `length` and `looking`, a dimension's `values` and `labels`, a text's type by name…),
/// put into `x`, the element as `elements` lists it (its `id` already in).
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let c = x.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
    match c.as_str() {
        "section" | "elevation" => sections::element_view(pr, id, x),
        "sheet" | "viewport" => sheets::element_view(pr, id, x),
        "planview" => plans::element_view(pr, id, x),
        "view3d" => view3d::element_view(pr, id, x),
        "dimension" => dims::element_view(pr, id, x),
        "dimension3d" => dims3d::element_view(pr, id, x),
        "text" => notes::element_view(pr, id, x),
        "tag" => tags::element_view(pr, id, x),
        "spot" | "spotslope" | "spot_slope" => spots::element_view(pr, id, x),
        "line" => lines::element_view(pr, id, x),
        "region" => regions::element_view(pr, id, x),
        "detailgroup" | "repeatingdetail" => groups::element_view(pr, id, x),
        _ => {}
    }
}

/// What `inspect` says of the sections this module keeps (view filters, view templates, detail
/// groups): (key, value) pairs for the core's `inspect` to merge into its reply.
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    filters::inspect_entries(s, out);
    templates::inspect_entries(s, out);
    groups::inspect_entries(s, out);
}
