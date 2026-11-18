//! Levels, grids, annotation (dimensions, tags, text, spots), views (sections, elevations, plan
//! and 3D views, schedules), sheets and viewports, detail lines, regions and groups, links and
//! CAD imports as `elements` shows them; and `select_by_id`, `ids_of` and `measure`.

pub mod annot;
pub mod details;
pub mod dims;
pub mod extent;
pub mod geo;
pub mod heights;
pub mod ids;
pub mod units;
pub mod views;

use crate::json::Value;
use crate::readers::common::{self, Ctx};
use crate::session::Session;

/// Rounds to thousandths (as extents are reported).
pub(crate) fn common_round3(x: f64) -> f64 {
    common::rn(x, 3)
}

/// Adds the derived values of a level, grid, annotation, view, sheet, viewport, detail, link or
/// CAD import to its view `x`.
pub fn view(cx: &Ctx, id: u64, x: &mut Value) {
    let _ = id;
    match common::category(x) {
        "level" => {
            if x.get("computation_height").is_none() {
                x.set("computation_height", Value::f(1200.0));
            }
        }
        "dimension" => dims::view(cx, x),
        "tag" => annot::tag_view(cx, x),
        "text" => annot::text_view(cx, x),
        "spot" => annot::spot_view(cx, x),
        "section" | "elevation" => views::section_view(x),
        "sheet" => views::sheet_view(cx, x),
        "viewport" => views::viewport_view(cx, x),
        "line" => details::line_view(cx, x),
        "region" => details::region_view(cx, x),
        "detailgroup" => details::group_view(cx, x),
        "repeatingdetail" => details::repeating_view(cx, x),
        _ => {}
    }
}

/// `select_by_id {text}`.
pub fn cmd_select_by_id(s: &Session, p: &Value) -> Result<Value, String> {
    ids::cmd_select_by_id(s, p)
}

/// `ids_of {ids}`.
pub fn cmd_ids_of(s: &Session, p: &Value) -> Result<Value, String> {
    ids::cmd_ids_of(s, p)
}

/// `measure {from, to}`.
pub fn cmd_measure(s: &Session, p: &Value) -> Result<Value, String> {
    ids::cmd_measure(s, p)
}
