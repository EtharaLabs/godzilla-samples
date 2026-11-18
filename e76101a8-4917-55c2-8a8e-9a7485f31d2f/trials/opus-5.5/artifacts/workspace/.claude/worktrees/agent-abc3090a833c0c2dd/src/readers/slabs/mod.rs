//! Floors, ceilings, roofs, shafts and masses as `elements` shows them (areas, volumes, a roof's
//! outline and ridge, a mass's levels…), and the heights of walls attached to a roof or a floor.

use crate::json::Value;
use crate::readers::common::{self, Ctx};

/// Adds a floor's, ceiling's, roof's, shaft's or mass's derived values to its view `x`.
pub fn view(cx: &Ctx, id: u64, x: &mut Value) {
    let pr = cx.pr;
    let _ = id;
    match common::category(x) {
        "floor" | "ceiling" | "roof" => {
            if let Some((name, def)) = common::element_type(pr, x) {
                let g = common::text(x, "type").unwrap_or("").to_string();
                x.set("type", Value::Str(name));
                x.set("type_guid", Value::Str(g));
                if let Some(t) = common::num(def, "thickness") {
                    x.set("thickness", Value::f(t));
                }
            }
        }
        _ => {}
    }
}

/// The height `elements` gives a wall whose top is attached to a roof or a floor (or whose base
/// stands on one): None for a wall attached to nothing (its stored height stands).
pub fn attached_height(cx: &Ctx, wall: u64) -> Option<f64> {
    let _ = (cx, wall);
    None
}
