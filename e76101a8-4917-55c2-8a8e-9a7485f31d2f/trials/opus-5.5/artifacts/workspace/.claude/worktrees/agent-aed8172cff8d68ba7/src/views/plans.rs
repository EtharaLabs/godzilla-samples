//! Plans: `crop`, `duplicate_view` (plan views: duplicate, detailing, dependent); the rules of
//! every view and sheet; what goes with a view, a sheet or a level when it is deleted.

pub mod shows;

use super::common::*;
use crate::commands::params::{get, given, opt_text};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use std::collections::BTreeSet;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "crop" => crop(s, p),
        _ => duplicate_view(s, p),
    }
}

// ---------------------------------------------------------------- finding views

/// A view by id, GUID or name, as `crop` and `duplicate_view` take one; `sheets` lets a sheet's
/// number name it. "`view`: X is not a view", "no view named `X`".
pub fn find_any_view(pr: &Project, cmd: &str, v: &Value, sheets: bool) -> R<u64> {
    let not = || format!("{}: `view`: {} is not a view", cmd, v.to_compact());
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
            for (id, e) in &pr.elements {
                let c = cat(e);
                let named = if c == "sheet" {
                    sheets && s_of(e, "number") == Some(s.as_str())
                } else {
                    is_view_category(c) && s_of(e, "name") == Some(s.as_str())
                };
                if named {
                    return Ok(*id);
                }
            }
            if let Ok(id) = s.trim().parse::<u64>() {
                if pr.elements.contains_key(&id) {
                    return Ok(id);
                }
            }
            if let Some(g) = dashed_guid(s) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(id);
                }
            }
            Err(format!("{}: no view named `{}`", cmd, s))
        }
        _ => Err(not()),
    }
}

/// A GUID as a view is taken by: hyphenated, in any case, braced or not.
pub fn dashed_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let t = t.strip_prefix('{').and_then(|x| x.strip_suffix('}')).unwrap_or(t);
    let b = t.as_bytes();
    if b.len() != 36 || [8, 13, 18, 23].iter().any(|&i| b[i] != b'-') {
        return None;
    }
    crate::model::normalize_guid(t)
}

/// How a view is named in messages: its name, a sheet as "sheet A101".
fn what_view(pr: &Project, id: u64) -> String {
    match pr.el(id) {
        Some(e) if cat(e) == "sheet" => format!("sheet {}", s_of(e, "number").unwrap_or("")),
        Some(e) => match s_of(e, "name") {
            Some(n) => n.to_string(),
            None => cat_id(pr, id),
        },
        None => String::new(),
    }
}

// ---------------------------------------------------------------- crop

fn crop(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "crop";
    // a crop is a step of its own even where the view was cropped so already
    super::mark_step();
    let pr = &mut s.project;
    let view = match get(p, "view") {
        Some(v) => find_any_view(pr, CMD, v, true)?,
        None => default_plan(pr).ok_or_else(|| format!("{}: the project has no level", CMD))?,
    };
    // the region: two corners, or null to uncrop; none, what the view shows
    let region: Option<Option<[[f64; 2]; 2]>> = if !given(p, "region") {
        None
    } else {
        match p.get("region").unwrap() {
            Value::Null => Some(None),
            Value::Arr(a) => {
                let mut pts = Vec::new();
                for q in a {
                    match crate::commands::params::point_of(q) {
                        Some(x) => pts.push(x),
                        None => {
                            return Err(format!("{}: `region`: {} is not a point [x, y] in mm", CMD, q.to_compact()))
                        }
                    }
                }
                if pts.len() != 2 {
                    return Err(format!("{}: `region` is two corners, [[x, y], [x, y]]", CMD));
                }
                Some(Some([pts[0], pts[1]]))
            }
            _ => return Err(format!("{}: `region` [[x, y], …] is required", CMD)),
        }
    };
    let c = cat_of(pr, view);
    match c.as_str() {
        "level" | "planview" => {
            let e = pr.el_mut(view).unwrap();
            match region {
                Some(None) => {
                    e.remove("crop");
                    Ok(jobj! {"crop" => Value::Null, "view" => view})
                }
                Some(Some([a, b])) => {
                    let v = Value::Arr(vec![Value::from(a), Value::from(b)]);
                    set_crop(e, v.clone());
                    Ok(jobj! {"crop" => v, "view" => view})
                }
                None => {
                    let Some((lo, hi)) = shows::plan_shows(pr, view) else {
                        return Err(format!("{}: {} shows nothing to crop to", CMD, what_view(pr, view)));
                    };
                    let v = Value::Arr(vec![
                        Value::from(r3p([lo[0] - 1000.0, lo[1] - 1000.0])),
                        Value::from(r3p([hi[0] + 1000.0, hi[1] + 1000.0])),
                    ]);
                    let e = pr.el_mut(view).unwrap();
                    set_crop(e, v.clone());
                    Ok(jobj! {"crop" => v, "view" => view})
                }
            }
        }
        "section" | "elevation" => match region {
            Some(None) => {
                pr.el_mut(view).unwrap().remove("crop");
                Ok(jobj! {"crop" => Value::Null, "view" => view})
            }
            Some(Some([a, b])) => {
                if !(b[0] - a[0] > 1.0 && b[1] - a[1] > 1.0) {
                    return Err(format!(
                        "{}: a crop region runs from its bottom left corner to its top right one (in a plan, south-west to north-east)",
                        CMD
                    ));
                }
                let e = pr.el(view).unwrap().clone();
                let (st, d, _, _) = shows::view_line(&e);
                let ns = r3p([st[0] + d[0] * a[0], st[1] + d[1] * a[0]]);
                let ne = r3p([st[0] + d[0] * b[0], st[1] + d[1] * b[0]]);
                let v = Value::Arr(vec![Value::f(a[1]), Value::f(b[1])]);
                {
                    let x = pr.el_mut(view).unwrap();
                    x.set("start", Value::from(ns));
                    x.set("end", Value::from(ne));
                    set_crop(x, v.clone());
                }
                // the notes in it stay where they are: along the line from its new start
                keep_annotation(pr, view, a[0]);
                Ok(jobj! {"crop" => v, "view" => view})
            }
            None => {
                let (_, _, v0, v1) = shows::section_frame_uncropped(pr, view);
                let v = Value::Arr(vec![Value::f(v0), Value::f(v1)]);
                set_crop(pr.el_mut(view).unwrap(), v.clone());
                Ok(jobj! {"crop" => v, "view" => view})
            }
        },
        _ => Err(format!(
            "{}: {} isn't a plan, a section or an elevation; only those crop",
            CMD,
            what_view(pr, view)
        )),
    }
}

/// Sets an element's crop where its fields put it (after its view range or its depth).
fn set_crop(e: &mut Value, v: Value) {
    if e.get("crop").is_some() {
        e.set("crop", v);
        return;
    }
    let order: &[&str] = match cat(e) {
        "level" => &["guid", "category", "name", "elevation", "view_range", "crop", "extent", "graphics", "section_box", "computation_height"],
        "planview" => &["guid", "category", "level", "name", "view_range", "crop", "graphics", "parent", "section_box"],
        _ => &["guid", "category", "name", "start", "end", "depth", "crop", "graphics"],
    };
    insert_in_order(e, "crop", v, order);
}

/// Puts a key into an object at its place in a struct's field order.
pub fn insert_in_order(e: &mut Value, key: &str, v: Value, order: &[&str]) {
    let Some(map) = e.as_obj_mut() else { return };
    if map.contains(key) {
        map.insert(key, v);
        return;
    }
    let rank = |k: &str| order.iter().position(|o| *o == k);
    let mine = rank(key).unwrap_or(usize::MAX);
    let pos = map
        .items
        .iter()
        .position(|(k, _)| match rank(k) {
            Some(r) => r > mine,
            None => false,
        })
        .unwrap_or(map.items.len());
    map.items.insert(pos, (key.to_string(), v));
}

/// A section's notes (its text notes and spot elevations) stay put as its start moves `by` along
/// its line: their places along it, measured from its start, move back by as much. Its detail
/// lines, regions and groups keep their numbers, as the original keeps them.
fn keep_annotation(pr: &mut Project, view: u64, by: f64) {
    if by == 0.0 {
        return;
    }
    let g = guid(pr, view);
    let ids: Vec<u64> = pr
        .elements
        .iter()
        .filter(|(_, e)| matches!(cat(e), "text" | "spot") && s_of(e, "view") == Some(g.as_str()))
        .map(|(id, _)| *id)
        .collect();
    for id in ids {
        let e = pr.el_mut(id).unwrap();
        shift_points(e, [-by, 0.0]);
    }
}

fn shift_pt(v: &mut Value, d: [f64; 2]) {
    if let Some(a) = v.as_arr_mut() {
        if a.len() >= 2 {
            if let (Some(x), Some(y)) = (a[0].as_f64(), a[1].as_f64()) {
                a[0] = Value::f(x + d[0]);
                a[1] = Value::f(y + d[1]);
            }
        }
    }
}

/// Moves the points an element of annotation holds (in its view's own terms).
fn shift_points(e: &mut Value, d: [f64; 2]) {
    for k in ["at", "leader", "start", "end", "through", "centre"] {
        if let Some(v) = e.get_mut(k) {
            shift_pt(v, d);
        }
    }
    for k in ["points", "control", "fit"] {
        if let Some(Value::Arr(a)) = e.get_mut(k) {
            for q in a.iter_mut() {
                shift_pt(q, d);
            }
        }
    }
    if let Some(Value::Arr(a)) = e.get_mut("sketch") {
        for l in a.iter_mut() {
            for k in ["start", "end", "through"] {
                if let Some(v) = l.get_mut(k) {
                    shift_pt(v, d);
                }
            }
        }
    }
}

// ---------------------------------------------------------------- duplicate_view

const COPY_WORD: [&str; 9] = ["Copy", "Cópia", "Copia", "Kopiera", "Kopie", "Copie", "Kopie", "Kopie", "Copia"];
const DEPENDENT_WORD: [&str; 9] = [
    "Dependent",
    "Dependente",
    "Dependiente",
    "Beroende",
    "Závislý",
    "Dépendant",
    "Afhankelijk",
    "Abhängig",
    "Dipendente",
];

/// The categories of annotation a view holds by its `view`.
pub const ANNOTATION: &[&str] = &[
    "text",
    "dimension",
    "tag",
    "spot",
    "spotslope",
    "spot_slope",
    "line",
    "region",
    "detailgroup",
    "repeatingdetail",
    "dimension3d",
];

/// Each annotation category's fields in order, where `view` goes in a copy that has none.
fn annotation_order(c: &str) -> &'static [&'static str] {
    match c {
        "tag" => &["guid", "category", "host", "view", "offset", "leader", "label"],
        "dimension" => &[
            "guid", "category", "level", "view", "kind", "orient", "refs", "at", "type", "prefix", "suffix", "above", "below",
            "replace", "equality", "texts", "equal", "locked", "alignment",
        ],
        _ => &["guid", "category", "view"],
    }
}

fn duplicate_view(s: &mut Session, p: &Value) -> R<Value> {
    const CMD: &str = "duplicate_view";
    let pr = &mut s.project;
    let view = match get(p, "view") {
        Some(v) => find_any_view(pr, CMD, v, false)?,
        None => default_plan(pr).ok_or_else(|| format!("{}: the project has no level", CMD))?,
    };
    let mode = match opt_text(p, CMD, "mode")? {
        None => "duplicate".to_string(),
        Some(m) => match m.as_str() {
            "duplicate" | "detailing" | "dependent" => m,
            _ => return Err(format!("{}: `mode` is duplicate, detailing or dependent, not `{}`", CMD, m)),
        },
    };
    let name = opt_text(p, CMD, "name")?;
    let c = cat_of(pr, view);
    if c != "level" && c != "planview" {
        return Err(format!(
            "{}: {} isn't a plan: plans are duplicated, sections, elevations, schedules, sheets and the 3D view not yet",
            CMD,
            what_view(pr, view)
        ));
    }
    let src = pr.el(view).unwrap().clone();
    if mode == "dependent" && src.get("parent").is_some() {
        return Err(format!(
            "{}: {} is a dependent view, which has none of its own: make it of its parent",
            CMD,
            what_view(pr, view)
        ));
    }
    let level = plan_level(pr, view).ok_or_else(|| format!("{}: {} has no level", CMD, what_view(pr, view)))?;
    let src_name = s_of(&src, "name").unwrap_or("").to_string();
    let name = match name {
        Some(n) => n,
        None => {
            let w = if mode == "dependent" { word(pr, DEPENDENT_WORD) } else { word(pr, COPY_WORD) };
            super::sections::numbered_name(pr, &format!("{} {}", src_name, w))
        }
    };
    let mut e = Map::new();
    e.insert("guid", Value::s(&crate::rand::guid()));
    e.insert("category", Value::s("planview"));
    e.insert("level", Value::s(&guid(pr, level)));
    e.insert("name", Value::s(&name));
    let vr = src.get("view_range").cloned().unwrap_or_else(|| {
        jobj! {"top" => Value::Null, "cut" => 1200.0, "bottom" => 0.0, "depth" => 0.0}
    });
    e.insert("view_range", vr);
    if let Some(c) = src.get("crop") {
        e.insert("crop", c.clone());
    }
    if mode == "dependent" {
        e.insert("parent", Value::s(&guid(pr, view)));
    } else {
        if let Some(g) = src.get("graphics") {
            e.insert("graphics", g.clone());
        }
        if let Some(b) = src.get("section_box") {
            e.insert("section_box", b.clone());
        }
    }
    let id = pr.alloc_id();
    let new_guid = s_of(&Value::Obj(e.clone()), "guid").unwrap().to_string();
    pr.elements.insert(id, Value::Obj(e));
    let mut copies = 0u64;
    if mode == "detailing" {
        let src_ids: Vec<u64> = pr
            .elements
            .iter()
            .filter(|(i, x)| **i != id && ANNOTATION.contains(&cat(x)) && in_view_own(pr, view, x))
            .map(|(i, _)| *i)
            .collect();
        for sid in src_ids {
            let mut x = pr.el(sid).unwrap().clone();
            x.set("guid", Value::s(&crate::rand::guid()));
            let ord = annotation_order(cat(&x));
            insert_in_order(&mut x, "view", Value::s(&new_guid), ord);
            renumber_parts(pr, &mut x);
            let nid = pr.alloc_id();
            pr.elements.insert(nid, x);
            copies += 1;
        }
    }
    Ok(jobj! {"annotations" => copies, "id" => id, "level" => level, "name" => name})
}

/// Whether annotation is a view's own (not a dependent's parent's): by its `view`, or with none
/// a dimension or a tag on a level's own plan.
fn in_view_own(pr: &Project, view: u64, e: &Value) -> bool {
    let g = guid(pr, view);
    if let Some(v) = s_of(e, "view") {
        return v == g;
    }
    if cat_of(pr, view) != "level" {
        return false;
    }
    match cat(e) {
        "dimension" => s_of(e, "level") == Some(g.as_str()),
        "tag" => shows::host_level(pr, e).as_deref() == Some(g.as_str()),
        _ => false,
    }
}

/// A copy's parts (a region's sketch lines…) get ids and GUIDs of their own.
fn renumber_parts(pr: &mut Project, x: &mut Value) {
    if let Some(Value::Arr(a)) = x.get_mut("sketch") {
        let n = a.len();
        let mut ids = Vec::new();
        for _ in 0..n {
            ids.push(pr.alloc_lib_id());
        }
        for (l, nid) in a.iter_mut().zip(ids) {
            if l.get("id").is_some() {
                l.set("id", Value::u(nid));
            }
            if l.get("guid").is_some() {
                l.set("guid", Value::s(&crate::rand::guid()));
            }
        }
    }
}

// ---------------------------------------------------------------- the rules of views and sheets

/// The rules of every view and sheet this area keeps, element by element in id order: a
/// section's or an elevation's line, depth and crop; a plan's crop; a plan view's level; names no
/// two views share and no view shares with a level; sheets' numbers and sizes; a viewport's
/// scale, and a view on one sheet.
pub fn views_check(pr: &Project) -> R<()> {
    let level_names: Vec<String> = pr
        .elements
        .values()
        .filter(|e| cat(e) == "level")
        .filter_map(|e| s_of(e, "name").map(|s| s.to_string()))
        .collect();
    let mut view_names: Vec<String> = Vec::new();
    let mut numbers: Vec<String> = Vec::new();
    let mut placed: Vec<(String, u64)> = Vec::new();
    let mut level_clash: Option<String> = None;
    for (id, e) in &pr.elements {
        let id = *id;
        let c = cat(e);
        match c {
            "section" | "elevation" | "view3d" | "schedule" | "planview" => {
                if c == "section" || c == "elevation" {
                    super::sections::check_line_view(pr, id, e)?;
                }
                if c == "view3d" {
                    // the 3D view's own elevation, as `place` may set it (VIEW3D checks the rest)
                    if let Some(el) = f_of(e, "elevation") {
                        if !(-89.0..=89.0).contains(&el) {
                            return Err(format!("view3d {}: elevation {}° isn't between -89° and 89°", id, disp(el)));
                        }
                    }
                }
                let name = s_of(e, "name").unwrap_or("").to_string();
                if c == "planview" {
                    if name.trim().is_empty() {
                        return Err(format!("planview {}: a view needs a name", id));
                    }
                    if level_names.contains(&name) {
                        return Err(format!(
                            "planview {}: a level is already named `{}`; a plan view of it needs another name",
                            id, name
                        ));
                    }
                    let level = ref_id(pr, e, "level");
                    if level.map(|l| cat_of(pr, l)) != Some("level".to_string()) {
                        let what = level.map(|l| l.to_string()).unwrap_or_else(|| s_of(e, "level").unwrap_or("").to_string());
                        return Err(format!("planview {}: level {} doesn't exist", id, what));
                    }
                    if s_of(e, "parent").is_some() {
                        // a dependent hangs from a plan of its own level that is no dependent itself
                        let parent = ref_id(pr, e, "parent");
                        let ok = parent.map_or(false, |p| match pr.el(p) {
                            Some(pe) if cat(pe) == "level" => Some(p) == level,
                            Some(pe) if cat(pe) == "planview" => pe.get("parent").is_none() && ref_id(pr, pe, "level") == level,
                            _ => false,
                        });
                        if !ok {
                            let what = parent.map(|p| p.to_string()).unwrap_or_else(|| s_of(e, "parent").unwrap_or("").to_string());
                            return Err(format!(
                                "planview {}: a dependent view hangs from a plan of its own level that is no dependent itself, not {}",
                                id, what
                            ));
                        }
                    }
                    check_plan_crop(id, e)?;
                } else if level_names.contains(&name) && level_clash.is_none() {
                    level_clash = Some(name.clone());
                }
                if view_names.contains(&name) {
                    return Err(format!("{} {}: another view is already named `{}`", c, id, name));
                }
                view_names.push(name);
            }
            "level" => check_plan_crop(id, e)?,
            "sheet" => {
                let num = s_of(e, "number").unwrap_or("").to_string();
                if num.trim().is_empty() {
                    return Err(format!("sheet {}: a sheet needs a number", id));
                }
                if numbers.contains(&num) {
                    return Err(format!("sheet {}: another sheet is already numbered `{}`", id, num));
                }
                numbers.push(num);
                let size = s_of(e, "size").unwrap_or("");
                if super::sheets::paper::paper_size(size).is_none() {
                    return Err(format!(
                        "sheet {}: size `{}` isn't A0, A1, A2, A3 or A4, or an Arch / ANSI size",
                        id, size
                    ));
                }
            }
            "viewport" => {
                match ref_id(pr, e, "sheet") {
                    Some(sh) if cat_of(pr, sh) == "sheet" => {}
                    Some(sh) => return Err(format!("viewport {}: {} isn't a sheet", id, cat_id(pr, sh))),
                    None => {}
                }
                match ref_id(pr, e, "view") {
                    Some(v) if ["level", "planview", "section", "elevation", "schedule", "view3d"].contains(&cat_of(pr, v).as_str()) => {}
                    Some(v) => {
                        return Err(format!(
                            "viewport {}: {} isn't a plan, a section, an elevation, a schedule or a 3D view",
                            id,
                            cat_id(pr, v)
                        ))
                    }
                    None => {}
                }
                let sc = f_of(e, "scale").unwrap_or(100.0);
                if !(sc >= 1.0 && sc <= 100000.0) {
                    return Err(format!("viewport {}: scale 1 : {} isn't between 1 : 1 and 1 : 100000", id, disp(sc)));
                }
                let v = s_of(e, "view").unwrap_or("").to_string();
                if let Some((_, sheet)) = placed.iter().find(|(g, _)| *g == v) {
                    let vid = pr.find_guid(&v);
                    let vname = vid.map(|x| super::common::view_name(pr, x)).unwrap_or_default();
                    let sname = super::common::view_name(pr, *sheet);
                    return Err(format!(
                        "viewport {}: {} is on sheet {} already; a view goes on one sheet",
                        id, vname, sname
                    ));
                }
                if let Some(sh) = ref_id(pr, e, "sheet") {
                    placed.push((v, sh));
                }
            }
            _ => {}
        }
    }
    if let Some(n) = level_clash {
        return Err(format!("a view is named `{}`, as a level is; name it otherwise", n));
    }
    Ok(())
}

/// A plan's crop runs from its south-west corner to its north-east one.
fn check_plan_crop(id: u64, e: &Value) -> R<()> {
    if let Some((a, b)) = shows::plan_crop(e) {
        if !(b[0] - a[0] > 1.0 && b[1] - a[1] > 1.0) {
            return Err(format!(
                "{} {}: a crop region runs from its south-west corner to its north-east one (in a section, bottom left to top right)",
                cat(e),
                id
            ));
        }
    }
    Ok(())
}

/// The model rules of this part, checked after every command (in `views_check`, run once by
/// `sections::check`).
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: a plan view, nothing.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let _ = (pr, id, x);
}

// ---------------------------------------------------------------- delete

/// What else goes when these elements are deleted, as the original's `delete` takes it: the
/// annotation in a deleted view (notes, detail lines, dimensions, tags, spots, regions, groups,
/// repeating details), a deleted plan's dependent plan views, a level's plan views, the
/// viewports of a deleted view or sheet, and so on through what those take with them. The ids
/// that go besides `gone`, in id order.
pub fn dependents(pr: &Project, gone: &BTreeSet<u64>) -> Vec<u64> {
    let mut all: BTreeSet<u64> = gone.clone();
    loop {
        let guids: BTreeSet<String> = all.iter().filter_map(|id| pr.guid_of(*id)).collect();
        let mut more = Vec::new();
        for (id, e) in &pr.elements {
            if all.contains(id) {
                continue;
            }
            let refs = |k: &str| s_of(e, k).map_or(false, |g| guids.contains(g));
            let goes = match cat(e) {
                "viewport" => refs("sheet") || refs("view"),
                "planview" => refs("level") || refs("parent"),
                c if ANNOTATION.contains(&c) => refs("view"),
                _ => false,
            };
            if goes {
                more.push(*id);
            }
        }
        if more.is_empty() {
            break;
        }
        all.extend(more);
    }
    all.into_iter().filter(|id| !gone.contains(id)).collect()
}
