//! What `elements` shows of a run or a column besides its fields: its type by name and GUID, its
//! section, a run's centre line and length, a column's height.

use super::geom::{column_height, run_geom, section, type_guid, type_name};
use crate::json::Value;
use crate::project::Project;
use crate::structure::common::is_run;

/// Rounded to the hundredth of a millimetre, as `elements` shows a run's line.
pub fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

pub fn element_view(pr: &Project, _id: u64, x: &mut Value) {
    let e = x.clone();
    let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
    let name = type_name(pr, &e);
    let guid = type_guid(pr, &e);
    let sec = section(pr, &e);
    if let Some(n) = &name {
        x.set("type", Value::s(n));
    }
    if let Some(g) = &guid {
        x.set("type_guid", Value::s(g));
    }
    if let Some(s) = &sec {
        x.set("width", Value::f(s.width));
        x.set("depth", Value::f(s.depth));
        x.set("round", Value::Bool(s.round));
    }
    if is_run(&cat) {
        if let Some(g) = run_geom(pr, &e) {
            let axis: Vec<Value> = g
                .axis
                .iter()
                .map(|p| Value::Arr(p.iter().map(|c| Value::f(round2(*c))).collect()))
                .collect();
            x.set("axis", Value::Arr(axis));
            x.set("length", Value::f(round2(g.length)));
        }
    } else {
        if let Some(h) = column_height(pr, &e) {
            x.set("height", Value::f(h));
        }
        if cat == "column" || cat == "structuralcolumn" {
            if x.get("room_bounding").is_none() {
                x.set("room_bounding", Value::Bool(true));
            }
        }
    }
}
