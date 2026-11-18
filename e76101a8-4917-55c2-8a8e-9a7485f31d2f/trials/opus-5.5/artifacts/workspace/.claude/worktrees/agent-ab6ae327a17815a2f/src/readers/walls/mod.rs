//! Walls, rooms and room separators as `elements` shows them: a wall's length, thickness, type and
//! height; a room's boundary worked out of the walls, separators and columns around its point,
//! its area, perimeter, height and volume.

use crate::json::Value;
use crate::readers::common::{self, Ctx};

/// Adds a wall's, room's or room separator's derived values to its view `x` (its stored fields
/// and `id`).
pub fn view(cx: &Ctx, id: u64, x: &mut Value) {
    let pr = cx.pr;
    let _ = id;
    match common::category(x) {
        "wall" => {
            if let Some((name, def)) = common::element_type(pr, x) {
                let t = common::num(def, "thickness").unwrap_or(0.0);
                let g = common::text(x, "type").unwrap_or("").to_string();
                x.set("type", Value::Str(name));
                x.set("type_guid", Value::Str(g));
                x.set("thickness", Value::f(t));
            }
            if let (Some(a), Some(b)) = (common::point(x, "start"), common::point(x, "end")) {
                x.set("length", Value::f(((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt()));
            }
            if x.get("room_bounding").is_none() {
                x.set("room_bounding", Value::Bool(true));
            }
            if let Some(h) = crate::readers::slabs::attached_height(cx, id) {
                x.set("height", Value::f(h));
            }
        }
        "roomseparator" => {
            if let (Some(a), Some(b)) = (common::point(x, "start"), common::point(x, "end")) {
                x.set("length", Value::f(((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt()));
            }
        }
        _ => {}
    }
}
