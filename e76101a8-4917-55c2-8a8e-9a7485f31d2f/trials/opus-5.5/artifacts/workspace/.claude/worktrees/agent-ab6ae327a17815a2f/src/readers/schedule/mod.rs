//! Schedules: the `schedule` command (a category's schedule, a new or changed one saved as a
//! `schedule` element, its table, totals, CSV and XLSX files) and `filter_selection`.

use crate::json::Value;
use crate::session::Session;

/// `schedule {name?, category?, categories?, fields?, filters?, sort?, grouped?, path?, available?}`.
pub fn cmd_schedule(s: &mut Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("schedule: not supported here".into())
}

/// An element's value of a field of its category's schedule (`Mark`, `Area`, `Type`, a project
/// parameter…) as a schedule's cell shows it, for a tag's label: None where its category's
/// schedule has no such field.
pub fn field_display(cx: &crate::readers::common::Ctx, id: u64, field: &str) -> Option<String> {
    let _ = (cx, id, field);
    None
}

/// `filter_selection {ids, by?, keep?}`.
pub fn cmd_filter_selection(s: &Session, p: &Value) -> Result<Value, String> {
    let _ = (s, p);
    Err("filter_selection: not supported here".into())
}
