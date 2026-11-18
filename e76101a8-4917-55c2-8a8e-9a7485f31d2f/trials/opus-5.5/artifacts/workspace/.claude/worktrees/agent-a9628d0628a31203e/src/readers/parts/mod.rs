//! Doors, windows, components (and their families' parameters worked out), columns, footings,
//! beams and runs, rebar, stairs, ramps and railings as `elements` shows them.

use crate::json::Value;
use crate::readers::common::{self, Ctx};

/// Adds the derived values of a door, window, component, column, footing, beam, run, rebar,
/// stair, ramp or railing to its view `x`.
pub fn view(cx: &Ctx, id: u64, x: &mut Value) {
    let pr = cx.pr;
    let _ = id;
    if common::type_home(common::category(x)).is_some() && x.get("family").is_none() {
        if let Some((name, _def)) = common::element_type(pr, x) {
            let g = common::text(x, "type").unwrap_or("").to_string();
            x.set("type", Value::Str(name));
            x.set("type_guid", Value::Str(g));
        }
    }
}
