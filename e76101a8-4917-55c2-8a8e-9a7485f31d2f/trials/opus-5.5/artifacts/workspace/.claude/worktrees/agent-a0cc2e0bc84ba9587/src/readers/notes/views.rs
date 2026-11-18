//! Sections, elevations, sheets and viewports as `elements` shows them: a section's length and the
//! way it looks, a sheet's paper and the viewports on it, a viewport's title and its size on the
//! paper.

use super::geo;
use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, Ctx};

/// A section's or an elevation's length and the way it looks (to the left of its line).
pub fn section_view(x: &mut Value) {
    let (Some(a), Some(b)) = (geo::pt(x.get("start")), geo::pt(x.get("end"))) else { return };
    let d = geo::sub(b, a);
    let l = geo::len(d);
    x.set("length", Value::f(l));
    if l > 0.0 {
        let nz = |v: f64| if v == 0.0 { 0.0 } else { v };
        x.set("looking", Value::Arr(vec![Value::f(nz(-d[1] / l)), Value::f(nz(d[0] / l))]));
    }
}

/// A sheet size's paper, landscape, mm.
pub fn paper(size: &str) -> Option<[f64; 2]> {
    Some(match size.trim().to_uppercase().as_str() {
        "A0" => [1189.0, 841.0],
        "A1" => [841.0, 594.0],
        "A2" => [594.0, 420.0],
        "A3" => [420.0, 297.0],
        "A4" => [297.0, 210.0],
        "ANSI A" | "LETTER" => [279.4, 215.9],
        "ANSI B" | "TABLOID" | "LEDGER" => [431.8, 279.4],
        "ANSI C" => [558.8, 431.8],
        "ANSI D" => [863.6, 558.8],
        "ANSI E" => [1117.6, 863.6],
        "ARCH A" => [304.8, 228.6],
        "ARCH B" => [457.2, 304.8],
        "ARCH C" => [609.6, 457.2],
        "ARCH D" => [914.4, 609.6],
        "ARCH E" => [1219.2, 914.4],
        "ARCH E1" => [1066.8, 762.0],
        _ => return None,
    })
}

pub fn sheet_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    let size = common::text(x, "size").unwrap_or("A3").to_string();
    if let Some(p) = paper(&size) {
        x.set("paper", geo::pval(p));
    }
    let g = common::text(x, "guid").unwrap_or("").to_string();
    let vps: Vec<Value> = pr
        .elements
        .iter()
        .filter(|(_, e)| common::category(e) == "viewport" && common::text(e, "sheet") == Some(g.as_str()))
        .map(|(id, _)| Value::u(*id))
        .collect();
    x.set("viewports", Value::Arr(vps));
}

pub fn viewport_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    let Some((vid, v)) = common::target(pr, x, "view") else { return };
    if let Some(n) = common::text(v, "name") {
        x.set("title", Value::s(n));
    }
    let scale = common::num(x, "scale").unwrap_or(100.0);
    if let Some(s) = super::extent::viewport_size(cx, vid, v, scale, x) {
        x.set("size", geo::pval(s));
    }
}

/// The level of a plan view (a level's own, or a plan view's).
pub fn plan_level(pr: &Project, id: u64) -> Option<u64> {
    crate::model::level_of_view(pr, id)
}
