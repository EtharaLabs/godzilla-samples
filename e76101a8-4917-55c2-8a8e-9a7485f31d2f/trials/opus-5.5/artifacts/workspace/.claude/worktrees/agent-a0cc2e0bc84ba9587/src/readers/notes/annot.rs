//! Tags, text notes and spot elevations as `elements` shows them: where a tag stands and what it
//! says, a note's type and size, the height a spot reads, and the level of the plan each is in.

use super::geo::{self, P};
use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, r2, Ctx};

/// The level a view (by GUID) is the plan of: a level's own plan, or a plan view's level; null
/// for a section, an elevation, a sheet or a 3D view.
pub fn view_level(pr: &Project, g: Option<&str>) -> Value {
    let Some(g) = g else { return Value::Null };
    match common::by_guid(pr, g) {
        Some((_, e)) => match common::category(e) {
            "level" => Value::s(g),
            "planview" => e.get("level").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        },
        None => Value::Null,
    }
}

/// The point of an element a tag names it at: a door's or window's place on its wall, a room's
/// point, the middle of a wall or a run, a column's or a component's point, the middle of a
/// floor's, ceiling's or roof's outline (its corners' mean), a stair's or ramp's start.
pub fn host_point(cx: &Ctx, e: &Value) -> Option<P> {
    match common::category(e) {
        "door" | "window" => geo::opening_place(cx, e).map(|(p, _, _)| p),
        "room" => geo::pt(e.get("point")),
        "wall" => {
            let a = geo::pt(e.get("start"))?;
            let b = geo::pt(e.get("end"))?;
            if let Some(t) = common::num(e, "arc").filter(|t| *t != 0.0) {
                if let Some(arc) = geo::Arc::from_chord(a, b, t) {
                    return Some(arc.at(0.5));
                }
            }
            Some(geo::lerp(a, b, 0.5))
        }
        "floor" | "ceiling" | "roof" | "shaft" | "mass" => {
            let pts = common::points(e.get("boundary").unwrap_or(&Value::Null));
            if pts.is_empty() {
                return None;
            }
            let n = pts.len() as f64;
            let sx: f64 = pts.iter().map(|p| p[0]).sum();
            let sy: f64 = pts.iter().map(|p| p[1]).sum();
            Some([sx / n, sy / n])
        }
        "stair" | "ramp" => geo::pt(e.get("start")),
        _ => {
            if let Some(p) = geo::pt(e.get("at")) {
                return Some(p);
            }
            let a = geo::pt(e.get("start"))?;
            let b = geo::pt(e.get("end"))?;
            Some(geo::lerp(a, b, 0.5))
        }
    }
}

/// The level an element stands on (a door's or window's wall's).
pub fn host_level(pr: &Project, e: &Value) -> Value {
    match common::category(e) {
        "door" | "window" => common::target(pr, e, "host")
            .and_then(|(_, w)| w.get("level").cloned())
            .unwrap_or(Value::Null),
        _ => e.get("level").cloned().unwrap_or(Value::Null),
    }
}

/// A type's name as the element names it (a family's type by its own name).
pub fn type_name(pr: &Project, e: &Value) -> Option<String> {
    let g = common::text(e, "type")?;
    if let Some(fg) = common::text(e, "family") {
        if let Some((fname, _)) = common::family(pr, fg) {
            if let Some(t) = common::family_type(pr, &fname, g) {
                return Some(t);
            }
        }
    }
    pr.lib_name(g).map(|n| match n.split_once(": ") {
        Some((_, t)) if pr.lib_find_guid(g).and_then(|l| pr.library.get(&l)).and_then(|l| l.get("kind")).and_then(|k| k.as_str()) == Some("family-type") => t.to_string(),
        _ => n,
    })
}

/// What a tag says of an element without a label: a door's or window's mark, a room's name, else
/// its type's name ("?" for none).
pub fn tag_text(pr: &Project, e: &Value) -> String {
    let s = match common::category(e) {
        "door" | "window" => common::text(e, "mark").map(|s| s.to_string()),
        "room" => common::text(e, "name").map(|s| s.to_string()),
        _ => type_name(pr, e),
    };
    match s {
        Some(s) if !s.is_empty() => s,
        _ => "?".into(),
    }
}

pub fn tag_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    let Some((hid, h)) = common::target(pr, x, "host") else { return };
    let off = geo::pt(x.get("offset")).unwrap_or([0.0, 0.0]);
    if let Some(p) = host_point(cx, h) {
        x.set("at", geo::pval(geo::add(p, off)));
    }
    x.set("level", host_level(pr, h));
    let text = match common::text(x, "label") {
        Some(label) => match crate::readers::schedule::field_display(cx, hid, label) {
            Some(s) if !s.is_empty() => s,
            Some(_) => "?".into(),
            None => tag_text(pr, h),
        },
        None => tag_text(pr, h),
    };
    x.set("text", Value::Str(text));
}

pub fn text_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    if let Some(g) = common::text(x, "type").map(|s| s.to_string()) {
        if let Some(name) = common::lib_name_of(pr, "text-type", &g) {
            let size = pr
                .section("text_types")
                .and_then(|m| m.get(&name))
                .and_then(|t| common::num(t, "size"))
                .unwrap_or(2.5);
            x.set("type", Value::Str(name));
            x.set("size", Value::f(size));
        }
    }
    let lv = view_level(pr, common::text(x, "view"));
    x.set("level", lv);
}

pub fn spot_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    let lv = view_level(pr, common::text(x, "view"));
    let at = geo::pt(x.get("at")).unwrap_or([0.0, 0.0]);
    let elev = match common::target(pr, x, "host") {
        Some((hid, h)) => super::heights::top_at(cx, hid, h, at),
        None => {
            if lv.is_null() {
                Some(at[1])
            } else {
                None
            }
        }
    };
    if let Some(z) = elev {
        x.set("elevation", Value::f(r2(z)));
    }
    x.set("level", lv);
}
