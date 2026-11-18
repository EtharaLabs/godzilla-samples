//! What the view and annotation commands share: views found by name or id, element fields read
//! with defaults, GUID references, rounding to the micron, and the default 3D view.

use crate::json::{Map, Value};
use crate::project::Project;

pub type R<T> = Result<T, String>;

pub use crate::commands::params::{get, given, has, id_of, mm_of, num_of, point3_of, point_of, points_of};

// ---------------------------------------------------------------- numbers

/// A length rounded to the micron, as the original keeps the points it works out.
pub fn r3(x: f64) -> f64 {
    let y = (x * 1000.0).round() / 1000.0;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

/// A point rounded to the micron.
pub fn r3p(p: [f64; 2]) -> [f64; 2] {
    [r3(p[0]), r3(p[1])]
}

/// A float as Rust's Display shows it in the original's messages (1.5, 17, 1000000000).
pub fn disp(x: f64) -> String {
    format!("{}", x)
}

// ---------------------------------------------------------------- element fields

pub fn cat(e: &Value) -> &str {
    e.get("category").and_then(|c| c.as_str()).unwrap_or("")
}

/// The category of an element by id ("" if there is none).
pub fn cat_of(pr: &Project, id: u64) -> String {
    pr.el(id).map(|e| cat(e).to_string()).unwrap_or_default()
}

/// "wall 100002", as the original's messages name an element.
pub fn cat_id(pr: &Project, id: u64) -> String {
    format!("{} {}", cat_of(pr, id), id)
}

pub fn s_of<'a>(e: &'a Value, k: &str) -> Option<&'a str> {
    e.get(k).and_then(|x| x.as_str())
}

pub fn f_of(e: &Value, k: &str) -> Option<f64> {
    e.get(k).and_then(|x| x.as_f64())
}

pub fn pt_of(e: &Value, k: &str) -> Option<[f64; 2]> {
    let a = e.get(k)?.as_arr()?;
    if a.len() < 2 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?])
}

pub fn pt3_of(e: &Value, k: &str) -> Option<[f64; 3]> {
    let a = e.get(k)?.as_arr()?;
    if a.len() < 3 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?, a[2].as_f64()?])
}

pub fn pts_of(e: &Value, k: &str) -> Option<Vec<[f64; 2]>> {
    let a = e.get(k)?.as_arr()?;
    a.iter()
        .map(|p| {
            let q = p.as_arr()?;
            if q.len() < 2 {
                return None;
            }
            Some([q[0].as_f64()?, q[1].as_f64()?])
        })
        .collect()
}

pub fn pt_value(p: [f64; 2]) -> Value {
    Value::from(p)
}

pub fn pts_value(ps: &[[f64; 2]]) -> Value {
    Value::Arr(ps.iter().map(|p| Value::from(*p)).collect())
}

/// The element's name ("" without one).
pub fn name_of(pr: &Project, id: u64) -> String {
    pr.el(id).and_then(|e| s_of(e, "name")).unwrap_or("").to_string()
}

// ---------------------------------------------------------------- references by GUID

/// The id of the element a GUID field names.
pub fn ref_id(pr: &Project, e: &Value, k: &str) -> Option<u64> {
    let g = s_of(e, k)?;
    pr.find_guid(g)
}

pub fn guid(pr: &Project, id: u64) -> String {
    pr.guid_of(id).unwrap_or_default()
}

/// The library entry name a GUID field of an element names.
pub fn lib_ref_name(pr: &Project, e: &Value, k: &str) -> Option<String> {
    let g = s_of(e, k)?;
    pr.lib_name(g)
}

// ---------------------------------------------------------------- views

/// The categories that are views of the model or of paper.
pub const VIEW_CATEGORIES: &[&str] = &["level", "planview", "section", "elevation", "view3d", "sheet", "schedule"];

pub fn is_view_category(c: &str) -> bool {
    VIEW_CATEGORIES.contains(&c)
}

/// A plan: a level's own plan (the level) or a plan view of it.
pub fn is_plan(pr: &Project, id: u64) -> bool {
    matches!(cat_of(pr, id).as_str(), "level" | "planview")
}

/// The level a plan shows (a level is its own plan).
pub fn plan_level(pr: &Project, id: u64) -> Option<u64> {
    crate::model::level_of_view(pr, id)
}

/// A view's name as messages give it: a sheet by its number.
pub fn view_name(pr: &Project, id: u64) -> String {
    match pr.el(id) {
        Some(e) if cat(e) == "sheet" => s_of(e, "number").unwrap_or("").to_string(),
        Some(e) => s_of(e, "name").unwrap_or("").to_string(),
        None => String::new(),
    }
}

/// A view given by id (any element: what it isn't is the command's to say) or by name: a level's,
/// a plan view's, a section's, an elevation's, a 3D view's or a schedule's name, or a sheet's
/// number. "`view`: X is not a view" for an id the project hasn't (or what is neither a number
/// nor text), "no view named `X`" for a name none has.
pub fn find_view(pr: &Project, cmd: &str, key: &str, v: &Value) -> R<u64> {
    let not = || format!("{}: `{}`: {} is not a view", cmd, key, v.to_compact());
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(not)?;
            if pr.elements.contains_key(&id) {
                Ok(id)
            } else {
                Err(not())
            }
        }
        Value::Str(s) => {
            if let Some(id) = find_view_named(pr, s) {
                return Ok(id);
            }
            if let Ok(id) = s.trim().parse::<u64>() {
                if pr.elements.contains_key(&id) {
                    return Ok(id);
                }
            }
            if let Some(g) = crate::model::normalize_guid(s) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(id);
                }
            }
            Err(format!("{}: no view named `{}`", cmd, s))
        }
        _ => Err(not()),
    }
}

/// The view of this name (a sheet by its number), the first by id.
pub fn find_view_named(pr: &Project, name: &str) -> Option<u64> {
    for (id, e) in &pr.elements {
        let c = cat(e);
        if c == "sheet" {
            if s_of(e, "number") == Some(name) {
                return Some(*id);
            }
        } else if is_view_category(c) && s_of(e, "name") == Some(name) {
            return Some(*id);
        }
    }
    None
}

/// The `view` parameter (or `key`), if given (null is not given).
pub fn view_param(pr: &Project, cmd: &str, p: &Value, key: &str) -> R<Option<u64>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => find_view(pr, cmd, key, v).map(Some),
    }
}

/// The lowest level, the plan commands draw in without a view.
pub fn default_plan(pr: &Project) -> Option<u64> {
    crate::model::default_level(pr)
}

/// The name the default 3D view goes by.
pub const DEFAULT_3D: &str = "{3D}";

/// Whether a view name is the default 3D view's (in any case).
pub fn is_default_3d_name(s: &str) -> bool {
    s.to_lowercase() == "{3d}"
}

/// The default 3D view, if it has come to be.
pub fn default_3d(pr: &Project) -> Option<u64> {
    pr.elements
        .iter()
        .find(|(_, e)| cat(e) == "view3d" && s_of(e, "name") == Some(DEFAULT_3D) && e.get("camera").is_none())
        .map(|(id, _)| *id)
        .or_else(|| {
            pr.elements
                .iter()
                .find(|(_, e)| cat(e) == "view3d" && s_of(e, "name") == Some(DEFAULT_3D))
                .map(|(id, _)| *id)
        })
}

/// The default 3D view, made as the original makes it when it is first changed or placed.
pub fn ensure_default_3d(pr: &mut Project) -> u64 {
    if let Some(id) = default_3d(pr) {
        return id;
    }
    let id = pr.alloc_id();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => "view3d",
            "name" => DEFAULT_3D,
            "azimuth" => -45.0,
            "elevation" => 30.0,
        },
    );
    id
}

/// Every element of a category, by id.
pub fn ids_of(pr: &Project, c: &str) -> Vec<u64> {
    pr.ids_of(c)
}

/// An element's field as an object, made empty where it isn't one (`graphics`, `crop`…).
pub fn obj_field<'a>(e: &'a mut Value, k: &str) -> &'a mut Map {
    if !matches!(e.get(k), Some(Value::Obj(_))) {
        e.set(k, Value::obj());
    }
    e.get_mut(k).unwrap().as_obj_mut().unwrap()
}

// ---------------------------------------------------------------- languages

/// The project's language code (en by default).
pub fn lang(pr: &Project) -> String {
    pr.language()
}

/// A word of the project's language from a table of (en, pt, es, sv, cs, fr, nl, de, it).
pub fn word(pr: &Project, t: [&'static str; 9]) -> &'static str {
    let i = crate::project::LANGS.iter().position(|l| *l == pr.language()).unwrap_or(0);
    t[i]
}
