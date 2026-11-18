//! Sheets and what is placed on them: `sheet`, `place` (viewports; schedules and the 3D view come to be as first placed).

pub mod paper;

use super::common::*;
use crate::commands::params::{get, mm_of, opt_point, opt_text};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "sheet" => sheet(s, p),
        _ => place(s, p),
    }
}

const UNNAMED: [&str; 9] = [
    "Unnamed",
    "Sem nome",
    "Sin nombre",
    "Namnlös",
    "Nepojmenovaný",
    "Sans nom",
    "Naamloos",
    "Unbenannt",
    "Senza nome",
];

// ---------------------------------------------------------------- sheet

fn sheet(s: &mut Session, p: &Value) -> R<Value> {
    let number = opt_text(p, "sheet", "number")?;
    let name = opt_text(p, "sheet", "name")?;
    let size = opt_text(p, "sheet", "size")?;
    let pr = &mut s.project;
    let number = match number {
        Some(n) => n,
        None => {
            let taken: Vec<String> = pr
                .elements
                .values()
                .filter(|e| cat(e) == "sheet")
                .filter_map(|e| s_of(e, "number").map(|x| x.to_string()))
                .collect();
            let mut n = 101u64;
            loop {
                let c = format!("A{}", n);
                if !taken.contains(&c) {
                    break c;
                }
                n += 1;
            }
        }
    };
    let name = name.unwrap_or_else(|| word(pr, UNNAMED).to_string());
    let size = match size {
        Some(x) => paper::normalize_size(&x),
        None => "A3".to_string(),
    };
    let id = pr.alloc_id();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => "sheet",
            "number" => number.clone(),
            "name" => name,
            "size" => size,
        },
    );
    Ok(jobj! {"id" => id, "number" => number})
}

// ---------------------------------------------------------------- place

/// A number in degrees, as `place` reads `azimuth` and `elevation`.
fn opt_degrees(p: &Value, key: &str) -> R<Option<f64>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => mm_of(v)
            .map(Some)
            .ok_or_else(|| format!("place: `{}` must be a number in mm, got {}", key, v.to_compact())),
    }
}

/// The sheet `place` puts the view on: by number, or by id.
fn find_sheet(pr: &Project, v: &Value) -> R<u64> {
    match v {
        Value::Str(s) => pr
            .elements
            .iter()
            .find(|(_, e)| cat(e) == "sheet" && s_of(e, "number") == Some(s.as_str()))
            .map(|(id, _)| *id)
            .ok_or_else(|| format!("place: no sheet numbered `{}`", s)),
        _ => {
            let not = || format!("place: `sheet`: {} is not a sheet", v.to_compact());
            let id = match v {
                Value::Num(_) => id_of(v).ok_or_else(not)?,
                _ => return Err(not()),
            };
            if cat_of(pr, id) == "sheet" {
                Ok(id)
            } else {
                Err(not())
            }
        }
    }
}

/// What `place` takes: a view by id, or by name (a level's, a section's, an elevation's, a
/// schedule's or a 3D view's; a schedule of a category by its name in any language, made as it
/// is first placed; the 3D view by `{3D}`, made likewise). Some(id) of a view there, or the
/// schedule or 3D view to make.
enum Placed {
    Here(u64),
    NewSchedule(&'static str),
    New3D,
}

const PLACEABLE: &[&str] = &["level", "planview", "section", "elevation", "schedule", "view3d"];

fn find_placed(pr: &Project, v: &Value) -> R<Placed> {
    let not = || format!("place: `view`: {} is not a plan, a section, an elevation, a schedule or a 3D view", v.to_compact());
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(not)?;
            if PLACEABLE.contains(&cat_of(pr, id).as_str()) {
                Ok(Placed::Here(id))
            } else {
                Err(not())
            }
        }
        Value::Str(s) => {
            for (id, e) in &pr.elements {
                if PLACEABLE.contains(&cat(e)) && s_of(e, "name") == Some(s.as_str()) {
                    return Ok(Placed::Here(*id));
                }
            }
            if let Some(of) = paper::schedule_of(s) {
                let name = paper::schedule_name(pr, of);
                if let Some((id, _)) = pr
                    .elements
                    .iter()
                    .find(|(_, e)| cat(e) == "schedule" && s_of(e, "name") == Some(name.as_str()))
                {
                    return Ok(Placed::Here(*id));
                }
                return Ok(Placed::NewSchedule(of));
            }
            if s == DEFAULT_3D {
                return Ok(Placed::New3D);
            }
            Err(format!("place: no level, section, elevation, schedule or 3D view named `{}`", s))
        }
        _ => Err(not()),
    }
}

/// The scale a view is drawn at: its template's where one controls it, its parent's for a
/// dependent plan, else its own, else 1 : 100.
pub fn scale_in_force(pr: &Project, view: u64) -> f64 {
    let Some(mut e) = pr.el(view) else { return 100.0 };
    if let Some(p) = ref_id(pr, e, "parent") {
        if let Some(pe) = pr.el(p) {
            e = pe;
        }
    }
    if let Some(t) = e.get("graphics").and_then(|g| s_of(g, "template")) {
        if let Some(name) = pr.lib_name(t) {
            if let Some(tp) = pr.section("view_templates").and_then(|v| v.get(&name)) {
                let controls = tp.get("controls").and_then(|c| c.as_arr());
                if controls.map_or(false, |c| c.iter().any(|x| x.as_str() == Some("scale"))) {
                    if let Some(sc) = tp.get("graphics").and_then(|g| f_of(g, "scale")) {
                        return sc;
                    }
                    if let Some(sc) = f_of(tp, "scale") {
                        return sc;
                    }
                }
            }
        }
    }
    e.get("graphics").and_then(|g| f_of(g, "scale")).unwrap_or(100.0)
}

fn place(s: &mut Session, p: &Value) -> R<Value> {
    let pr = &mut s.project;
    let sheet = match get(p, "sheet") {
        None => return Err("place: `sheet`, a sheet's number or id, is required".into()),
        Some(v) => find_sheet(pr, v)?,
    };
    let scale = match get(p, "scale") {
        None => None,
        Some(v) => Some(mm_of(v).ok_or_else(|| format!("place: `scale` must be a number in mm, got {}", v.to_compact()))?),
    };
    let at = opt_point(p, "place", "at")?;
    let placed = match get(p, "view") {
        None => {
            return Err("place: `view`, a level's, section's, elevation's, schedule's or 3D view's name or id, is required".into())
        }
        Some(v) => find_placed(pr, v)?,
    };
    let is_3d = match &placed {
        Placed::New3D => true,
        Placed::Here(id) => cat_of(pr, *id) == "view3d",
        _ => false,
    };
    let (azimuth, elevation) = if is_3d {
        (opt_degrees(p, "azimuth")?, opt_degrees(p, "elevation")?)
    } else {
        (None, None)
    };
    let view = match placed {
        Placed::Here(id) => id,
        Placed::NewSchedule(of) => {
            let id = pr.alloc_id();
            let name = paper::schedule_name(pr, of);
            pr.elements.insert(
                id,
                jobj! {"guid" => crate::rand::guid(), "category" => "schedule", "name" => name, "of" => of},
            );
            id
        }
        Placed::New3D => {
            let id = ensure_default_3d(pr);
            let e = pr.el_mut(id).unwrap();
            if let Some(a) = azimuth {
                e.set("azimuth", Value::f(a));
            }
            if let Some(el) = elevation {
                e.set("elevation", Value::f(el));
            }
            id
        }
    };
    let scale = match scale {
        Some(x) => x,
        None => match cat_of(pr, view).as_str() {
            "level" | "planview" | "section" | "elevation" => scale_in_force(pr, view),
            _ => 100.0,
        },
    };
    let size = paper::view_size(pr, view, scale);
    let at = match at {
        Some(a) => a,
        None => paper::default_place(pr, sheet, size),
    };
    let id = pr.alloc_id();
    pr.elements.insert(
        id,
        jobj! {
            "guid" => crate::rand::guid(),
            "category" => "viewport",
            "sheet" => guid(pr, sheet),
            "view" => guid(pr, view),
            "at" => at,
            "scale" => scale,
        },
    );
    Ok(jobj! {"at" => at, "id" => id})
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command (in `plans::views_check`).
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: a sheet's paper and
/// the viewports on it; a viewport's size on the paper and its title.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    match cat(e) {
        "sheet" => {
            let (w, h) = paper::paper_size(s_of(e, "size").unwrap_or("A3")).unwrap_or((420.0, 297.0));
            x.set("paper", Value::from([w, h]));
            let g = guid(pr, id);
            let vps: Vec<Value> = pr
                .elements
                .iter()
                .filter(|(_, v)| cat(v) == "viewport" && s_of(v, "sheet") == Some(g.as_str()))
                .map(|(i, _)| Value::u(*i))
                .collect();
            x.set("viewports", Value::Arr(vps));
        }
        "viewport" => {
            let sz = paper::viewport_size(pr, id);
            x.set("size", Value::from(sz));
            let title = ref_id(pr, e, "view").map(|v| view_name(pr, v)).unwrap_or_default();
            x.set("title", Value::s(&title));
        }
        _ => {}
    }
}
