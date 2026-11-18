//! Levels, grids, annotation (dimensions, tags, text, spots), views (sections, elevations, plan
//! and 3D views, schedules), sheets and viewports, detail lines, regions and groups, links and
//! CAD imports as `elements` shows them; and `select_by_id`, `ids_of` and `measure`.

use crate::json::Value;
use crate::readers::common::{self, Ctx};
use crate::session::Session;

/// Adds the derived values of a level, grid, annotation, view, sheet, viewport, detail, link or
/// CAD import to its view `x`.
pub fn view(cx: &Ctx, id: u64, x: &mut Value) {
    let _ = (cx, id);
    if common::category(x) == "level" && x.get("computation_height").is_none() {
        x.set("computation_height", Value::f(1200.0));
    }
}

/// `select_by_id {text}`.
pub fn cmd_select_by_id(s: &Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("select_by_id: not supported here".into())
}

/// `ids_of {ids}`.
pub fn cmd_ids_of(s: &Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("ids_of: not supported here".into())
}

/// `measure {from, to}`.
pub fn cmd_measure(s: &Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("measure: not supported here".into())
}
