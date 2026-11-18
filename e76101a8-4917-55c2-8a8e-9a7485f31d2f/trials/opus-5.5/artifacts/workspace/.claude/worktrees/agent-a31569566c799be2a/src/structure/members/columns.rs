//! `column`, `structural_column` and `footing`: a member standing at a point, of a type's plan.

use super::read::{level_above, level_param, level_ref, type_name_param};
use crate::commands::params::{get, opt_num, opt_text, req_point};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::{add_element, new_guid, type_guid, R};

/// A column's height when it goes up to no level.
pub const DEFAULT_HEIGHT: f64 = 3000.0;

/// A footing's thickness unless told.
pub const DEFAULT_THICKNESS: f64 = 400.0;

/// A column, a structural column or a footing as the file holds it.
pub fn column_json(
    cat: &str,
    type_ref: &str,
    level_guid: &str,
    at: [f64; 2],
    angle: f64,
    top_level: Option<&str>,
    height: f64,
    base_offset: f64,
) -> Value {
    let mut m = Map::new();
    m.insert("guid", Value::s(&new_guid()));
    m.insert("category", Value::s(cat));
    m.insert("type", Value::s(type_ref));
    m.insert("level", Value::s(level_guid));
    m.insert("at", Value::from(at));
    m.insert("angle", Value::f(angle));
    m.insert("top_level", top_level.map(Value::s).unwrap_or(Value::Null));
    m.insert("height", Value::f(height));
    m.insert("base_offset", Value::f(base_offset));
    Value::Obj(m)
}

fn type_param(s: &Session, cid: &str, cat: &str, p: &Value) -> R<String> {
    match opt_text(p, cid, "type")? {
        Some(t) => Ok(type_name_param(&s.project, &t)),
        None => match crate::structure::types::default_type(&s.project, cat) {
            Some(t) => Ok(t),
            None => Err(format!("{}: the model has no types for this", cid)),
        },
    }
}

/// `column` and `structural_column`.
pub fn column(s: &mut Session, cid: &str, cat: &str, p: &Value) -> R<Value> {
    let at = req_point(p, cid, "at")?;
    let level = level_param(&s.project, cid, p)?;
    let type_name = type_param(s, cid, cat, p)?;
    let angle = opt_num(p, cid, "angle")?.unwrap_or(0.0);
    let height = opt_num(p, cid, "height")?;
    let top_level = match get(p, "top_level") {
        Some(v) => Some(level_ref(&s.project, cid, "top_level", v)?),
        None => None,
    };
    let base_offset = opt_num(p, cid, "base_offset")?.unwrap_or(0.0);
    let pr = &s.project;
    // up to the level given, else (without a height) the next one up
    let top = match (top_level, height) {
        (Some(t), _) => Some(t),
        (None, Some(_)) => None,
        (None, None) => level_above(pr, level),
    };
    let level_guid = pr.guid_of(level).unwrap_or_default();
    let top_guid = top.and_then(|t| pr.guid_of(t));
    let type_ref = type_guid(pr, cat, &type_name).unwrap_or(type_name);
    let e = column_json(
        cat,
        &type_ref,
        &level_guid,
        at,
        angle,
        top_guid.as_deref(),
        height.unwrap_or(DEFAULT_HEIGHT),
        base_offset,
    );
    let id = add_element(s, e);
    Ok(crate::jobj! {"id" => id})
}

/// `footing`: an isolated pad, `thickness` thick, its top `offset` over its level.
pub fn footing(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let cat = "footing";
    let at = req_point(p, cid, "at")?;
    let level = level_param(&s.project, cid, p)?;
    let type_name = type_param(s, cid, cat, p)?;
    let angle = opt_num(p, cid, "angle")?.unwrap_or(0.0);
    let thickness = opt_num(p, cid, "thickness")?.unwrap_or(DEFAULT_THICKNESS);
    if thickness <= 0.0 {
        return Err(format!("{}: `thickness` must be above zero, got {}", cid, thickness));
    }
    let offset = opt_num(p, cid, "offset")?.unwrap_or(0.0);
    let pr = &s.project;
    let level_guid = pr.guid_of(level).unwrap_or_default();
    let type_ref = type_guid(pr, cat, &type_name).unwrap_or(type_name);
    let e = column_json(cat, &type_ref, &level_guid, at, angle, None, thickness, offset - thickness);
    let id = add_element(s, e);
    Ok(crate::jobj! {"id" => id})
}
