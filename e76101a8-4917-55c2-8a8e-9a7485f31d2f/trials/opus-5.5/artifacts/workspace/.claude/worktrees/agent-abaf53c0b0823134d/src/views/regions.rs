//! Filled regions: `filled_region`.
//!
//! A region is annotation of one view: `{guid, category: "region", view, type, line_style?,
//! sketch: [{id, guid, style?, …a curve's fields}], pattern_origin?, pattern_angle?}`, its type
//! a `filled-region-type` library entry's GUID, its boundary's line style a `line-style` one's
//! (none: invisible lines), each boundary line a part with an id counted down with the library's.

pub mod curve;
pub mod sketch;

use super::common::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const FR: &str = "filled_region";

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "filled_region" => filled_region(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

// ---------------------------------------------------------------- names

/// The filled region type a region is of unless told: Solid Black (in the project's language),
/// else the first by name.
pub fn default_region_type(pr: &Project) -> Option<String> {
    let w = word(pr, [
        "Solid Black",
        "Preto sólido",
        "Negro sólido",
        "Helfylld svart",
        "Plná černá",
        "Noir plein",
        "Effen zwart",
        "Schwarz",
        "Nero pieno",
    ]);
    let types = region_type_names(pr);
    if types.iter().any(|t| t == w) {
        return Some(w.to_string());
    }
    types.first().cloned()
}

/// The line style a line is drawn in unless told: Thin Lines (in the project's language), else
/// the first by name of pen 1, else the first.
pub fn default_line_style(pr: &Project) -> Option<String> {
    let w = word(pr, [
        "Thin Lines",
        "Linhas finas",
        "Líneas finas",
        "Tunna linjer",
        "Tenké čáry",
        "Lignes fines",
        "Dunne lijnen",
        "Dünne Linien",
        "Linee sottili",
    ]);
    let Some(sec) = pr.section("line_styles") else { return None };
    let mut names: Vec<&String> = sec.keys().collect();
    names.sort();
    if names.iter().any(|n| n.as_str() == w) {
        return Some(w.to_string());
    }
    for n in &names {
        if sec.get(n).and_then(|s| s.get("pen")).and_then(|x| x.as_u64()) == Some(1) {
            return Some(n.to_string());
        }
    }
    names.first().map(|n| n.to_string())
}

/// The project's filled region types' names, sorted.
pub fn region_type_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = pr.section("region_types").map(|s| s.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

pub fn has_line_style(pr: &Project, name: &str) -> bool {
    pr.section("line_styles").map(|s| s.contains(name)).unwrap_or(false)
}

/// The GUID of a library entry, made where the project has the style or type but not the entry.
fn lib_ref(pr: &mut Project, kind: &str, name: &str) -> String {
    match pr.lib_guid(kind, name) {
        Some(g) => g,
        None => pr.lib_add(kind, name).1,
    }
}

/// The name of the library entry of this kind a GUID names.
pub fn lib_kind_name(pr: &Project, kind: &str, g: &str) -> Option<String> {
    pr.library
        .values()
        .find(|e| e.get("kind").and_then(|x| x.as_str()) == Some(kind) && e.get("guid").and_then(|x| x.as_str()) == Some(g))
        .and_then(|e| e.get("name"))
        .and_then(|n| n.as_str())
        .map(|s| s.to_string())
}

// ---------------------------------------------------------------- views

/// Whether annotation can be drawn in a view: a plan, a section, an elevation or a sheet.
pub fn annotation_view(c: &str) -> bool {
    matches!(c, "level" | "planview" | "section" | "elevation" | "sheet")
}

/// The view a command draws in: `view`, else `level` (a level or a plan view), else the lowest
/// plan.
pub fn view_or_level(pr: &Project, cmd: &str, p: &Value) -> R<u64> {
    if let Some(v) = view_param(pr, cmd, p, "view")? {
        return Ok(v);
    }
    if get(p, "level").is_some() {
        return crate::model::level_param(pr, cmd, p, "level");
    }
    default_plan(pr).ok_or_else(|| format!("{}: the project has no level", cmd))
}

/// What a view isn't, as the model's check says it: "line 100002 isn't a plan, …".
pub fn view_check(pr: &Project, who: &str, view: Option<u64>) -> R<()> {
    let Some(v) = view else { return Ok(()) };
    let c = cat_of(pr, v);
    if !annotation_view(&c) {
        return Err(format!("{}: {} {} isn't a plan, a section, an elevation or a sheet", who, c, v));
    }
    Ok(())
}

/// The level of the view an element of a view is in (a plan's), else null.
pub fn view_level(pr: &Project, e: &Value) -> Value {
    match ref_id(pr, e, "view").and_then(|v| crate::model::level_of_view(pr, v)) {
        Some(l) => Value::s(&guid(pr, l)),
        None => Value::Null,
    }
}

// ---------------------------------------------------------------- the region's sketch

/// A region's boundary lines' curves, as its file holds them.
pub fn sketch_shapes(e: &Value) -> Vec<curve::Shape> {
    e.get("sketch")
        .and_then(|s| s.as_arr())
        .map(|a| a.iter().filter_map(curve::Shape::from_fields).collect())
        .unwrap_or_default()
}

/// The area a region's sketch closes, in m² to the hundredth (0 where it doesn't close).
pub fn region_area(e: &Value) -> f64 {
    let lines: Vec<sketch::Line> =
        sketch_shapes(e).into_iter().map(|shape| sketch::Line { id: None, style: None, shape }).collect();
    match sketch::solve(&lines) {
        Ok(r) => sketch::area_m2(&r),
        Err(_) => 0.0,
    }
}

/// The points a region's boundary is drawn with.
pub fn region_points(e: &Value) -> Vec<curve::P> {
    sketch_shapes(e).iter().flat_map(|s| s.drawn()).collect()
}

// ---------------------------------------------------------------- filled_region

fn filled_region(s: &mut Session, p: &Value) -> R<Value> {
    crate::styles::common::check_keys(p, FR, &["sketch", "view", "level", "type", "line_style"])?;
    let lines = sketch::parse(FR, "sketch", p.get("sketch"), &[])?;
    let regions = sketch::solve(&lines).map_err(|e| format!("{}: the sketch doesn't close into loops: {}", FR, e))?;
    let pr = &mut s.project;
    let view = view_or_level(pr, FR, p)?;
    let type_name = match crate::styles::common::opt_name(p, FR, "type")? {
        Some(t) => Some(t),
        None => default_region_type(pr),
    };
    let line_style: Option<String> = match p.get("line_style") {
        None => default_line_style(pr),
        Some(Value::Null) => None,
        Some(Value::Str(s)) => Some(s.trim().to_string()),
        Some(v) => {
            return Err(format!("{}: `line_style` is a line style's name, or null for invisible lines, not {}", FR, v.to_compact()))
        }
    };
    let id = pr.alloc_id();
    let who = format!("region {}", id);
    // what the model's check then says of it
    view_check(pr, &who, Some(view))?;
    let tn = type_name.unwrap_or_default();
    if !region_type_names(pr).contains(&tn) {
        return Err(format!(
            "{}: there's no filled region type `{}` (there are: {})",
            who,
            tn,
            region_type_names(pr).join(", ")
        ));
    }
    if let Some(ls) = &line_style {
        if !has_line_style(pr, ls) {
            return Err(format!("{}: there's no line style `{}`", who, ls));
        }
    }
    for (i, l) in lines.iter().enumerate() {
        if let Some(st) = &l.style {
            if !has_line_style(pr, st) {
                return Err(format!("{}: boundary line {} is drawn in `{}`, and there's no such line style", who, i, st));
            }
        }
    }
    let view_guid = guid(pr, view);
    let type_guid = lib_ref(pr, "filled-region-type", &tn);
    let ls_guid = line_style.as_ref().map(|ls| lib_ref(pr, "line-style", ls));
    let mut sk: Vec<Value> = Vec::new();
    for l in &lines {
        let mut m = Map::new();
        m.insert("id", Value::u(pr.alloc_lib_id()));
        m.insert("guid", Value::s(&crate::rand::guid()));
        if let Some(st) = &l.style {
            let g = lib_ref(pr, "line-style", st);
            m.insert("style", Value::s(&g));
        }
        sketch::shape_fields(&l.shape, &mut m);
        sk.push(Value::Obj(m));
    }
    let mut e = Map::new();
    e.insert("guid", Value::s(&crate::rand::guid()));
    e.insert("category", Value::s("region"));
    e.insert("view", Value::s(&view_guid));
    e.insert("type", Value::s(&type_guid));
    if let Some(g) = ls_guid {
        e.insert("line_style", Value::s(&g));
    }
    e.insert("sketch", Value::Arr(sk));
    pr.elements.insert(id, Value::Obj(e));
    Ok(jobj! {"area_m2" => sketch::area_m2(&regions), "id" => id})
}

// ---------------------------------------------------------------- the model's rules

/// What a region (or a group's member region, `who` naming it) must be: of a type the project
/// has, bounded in line styles it has.
pub fn check_region_refs(pr: &Project, who: &str, e: &Value) -> R<()> {
    if let Some(g) = s_of(e, "type") {
        let name = lib_kind_name(pr, "filled-region-type", g);
        let ok = name.as_ref().map(|n| region_type_names(pr).contains(n)).unwrap_or(false);
        if !ok {
            return Err(format!(
                "{}: there's no filled region type `{}` (there are: {})",
                who,
                name.unwrap_or_else(|| g.to_string()),
                region_type_names(pr).join(", ")
            ));
        }
    }
    if let Some(g) = s_of(e, "line_style") {
        let name = lib_kind_name(pr, "line-style", g);
        let ok = name.as_ref().map(|n| has_line_style(pr, n)).unwrap_or(false);
        if !ok {
            return Err(format!("{}: there's no line style `{}`", who, name.unwrap_or_else(|| g.to_string())));
        }
    }
    if let Some(a) = e.get("sketch").and_then(|s| s.as_arr()) {
        for (i, l) in a.iter().enumerate() {
            if let Some(g) = s_of(l, "style") {
                let name = lib_kind_name(pr, "line-style", g);
                let ok = name.as_ref().map(|n| has_line_style(pr, n)).unwrap_or(false);
                if !ok {
                    return Err(format!(
                        "{}: boundary line {} is drawn in `{}`, and there's no such line style",
                        who,
                        i,
                        name.unwrap_or_else(|| g.to_string())
                    ));
                }
            }
        }
    }
    Ok(())
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) != "region" {
            continue;
        }
        let who = format!("region {}", id);
        if let Some(v) = ref_id(pr, e, "view") {
            view_check(pr, &who, Some(v))?;
        }
        check_region_refs(pr, &who, e)?;
    }
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: the area, the view's
/// level, the type and line styles by name, the pattern's origin and angle even at their
/// defaults.
pub fn element_view(pr: &Project, _id: u64, x: &mut Value) {
    let e = x.clone();
    x.set("area_m2", Value::f(region_area(&e)));
    x.set("level", view_level(pr, &e));
    if let Some(g) = s_of(&e, "type") {
        if let Some(n) = lib_kind_name(pr, "filled-region-type", g) {
            x.set("type", Value::s(&n));
        }
    }
    if let Some(g) = s_of(&e, "line_style") {
        if let Some(n) = lib_kind_name(pr, "line-style", g) {
            x.set("line_style", Value::s(&n));
        }
    }
    if x.get("pattern_origin").is_none() {
        x.set("pattern_origin", Value::from([0.0, 0.0]));
    }
    if x.get("pattern_angle").is_none() {
        x.set("pattern_angle", Value::f(0.0));
    }
    if let Some(Value::Arr(a)) = x.get_mut("sketch") {
        for l in a.iter_mut() {
            if let Some(g) = l.get("style").and_then(|s| s.as_str()).map(|s| s.to_string()) {
                if let Some(n) = lib_kind_name(pr, "line-style", &g) {
                    l.set("style", Value::s(&n));
                }
            }
        }
    }
}
