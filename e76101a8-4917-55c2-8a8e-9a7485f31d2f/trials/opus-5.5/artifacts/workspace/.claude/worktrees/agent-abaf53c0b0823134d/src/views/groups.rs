//! Detail groups: `create_group`, `detail_group`, `repeating_detail`, `ungroup`, `group_type`.
//!
//! A group type is the file's `detail_groups.<name>`: `{members: [{id, guid, element}]}`, each
//! member a detail line, a filled region or a text note as an element of no view (`view: 0`),
//! about the middle of what was grouped, and a `detail-group` library entry. A placed group is
//! `{guid, category: "detailgroup", view, type, at, angle?, mirrored?}`; a repeating detail
//! `{guid, category: "repeatingdetail", view, type, start, end, spacing, mirrored?}`, one group
//! every `spacing` from `start` toward `end`, each turned along the line.

use super::common::*;
use super::regions::curve::{self, Place, P};
use super::regions::{self, view_check, view_level, view_or_level};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

const KIND: &str = "detail-group";
const SECTION: &str = "detail_groups";
/// The most repeats a repeating detail places.
pub const MAX_REPEATS: u64 = 2000;
/// The most group members a view draws.
pub const MAX_PLACED: u64 = 10000;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "create_group" => create_group(s, p),
        "detail_group" => detail_group(s, p),
        "repeating_detail" => repeating_detail(s, p),
        "ungroup" => ungroup(s, p),
        "group_type" => group_type(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

fn check_keys(p: &Value, cmd: &str, allowed: &[&str]) -> R<()> {
    crate::styles::common::check_keys(p, cmd, allowed)
}

fn opt_name(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    crate::styles::common::opt_name(p, cmd, key)
}

// ---------------------------------------------------------------- the types

/// The project's group types' names, in order.
pub fn type_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = pr.section(SECTION).map(|s| s.keys().cloned().collect()).unwrap_or_default();
    v.sort();
    v
}

/// A type's members.
pub fn members(pr: &Project, name: &str) -> Vec<Value> {
    pr.section(SECTION)
        .and_then(|s| s.get(name))
        .and_then(|t| t.get("members"))
        .and_then(|m| m.as_arr())
        .cloned()
        .unwrap_or_default()
}

/// The name of the group type a GUID names.
pub fn type_of_guid(pr: &Project, g: &str) -> Option<String> {
    regions::lib_kind_name(pr, KIND, g)
}

/// The type a placed group or a repeating detail is of, by name.
pub fn type_name(pr: &Project, e: &Value) -> Option<String> {
    type_of_guid(pr, s_of(e, "type")?)
}

fn type_guid(pr: &mut Project, name: &str) -> String {
    match pr.lib_guid(KIND, name) {
        Some(g) => g,
        None => pr.lib_add(KIND, name).1,
    }
}

/// How many times a repeating detail places its group: one at `start` and one every `spacing`
/// on to `end`.
pub fn repeat_count(e: &Value) -> u64 {
    let a = pt_of(e, "start").unwrap_or([0.0, 0.0]);
    let b = pt_of(e, "end").unwrap_or([0.0, 0.0]);
    let sp = f_of(e, "spacing").unwrap_or(0.0);
    let l = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2)).sqrt();
    if !(sp > 0.0) {
        return 1;
    }
    let n = (l / sp).floor();
    if !n.is_finite() || n >= 1e15 {
        return u64::MAX / 2;
    }
    n as u64 + 1
}

// ---------------------------------------------------------------- elements, by id or GUID

fn not_an_id(cmd: &str, v: &Value) -> String {
    format!("{}: {} is not an element id or GUID", cmd, v.to_compact())
}

/// An element by its id (a number, or one in a string) or its GUID.
pub fn element_ref(pr: &Project, cmd: &str, v: &Value) -> R<u64> {
    match v {
        Value::Num(_) => {
            let id = id_of(v).ok_or_else(|| not_an_id(cmd, v))?;
            if pr.elements.contains_key(&id) {
                Ok(id)
            } else {
                Err(format!("{}: no element {}", cmd, id))
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                return if pr.elements.contains_key(&id) { Ok(id) } else { Err(format!("{}: no element {}", cmd, id)) };
            }
            match crate::model::normalize_guid(t) {
                Some(g) => pr.find_guid(&g).ok_or_else(|| format!("{}: no element {}", cmd, g)),
                None => Err(not_an_id(cmd, v)),
            }
        }
        _ => Err(not_an_id(cmd, v)),
    }
}

/// `ids`: elements by id or GUID, each once, in the order given.
pub fn ids_param(pr: &Project, cmd: &str, p: &Value) -> R<Vec<u64>> {
    let a = match get(p, "ids") {
        Some(Value::Arr(a)) => a,
        _ => return Err(format!("{}: `ids` [id, …] is required", cmd)),
    };
    let mut out = Vec::new();
    for v in a {
        let id = element_ref(pr, cmd, v)?;
        if !out.contains(&id) {
            out.push(id);
        }
    }
    Ok(out)
}

// ---------------------------------------------------------------- the members' geometry

/// The points what an element of a group draws spans: a line's drawn points, a region's
/// boundary's, a note's place.
fn extent(e: &Value) -> Vec<P> {
    match cat(e) {
        "line" => curve::Shape::from_fields(e).map(|s| s.drawn()).unwrap_or_default(),
        "region" => regions::region_points(e),
        "text" => {
            let mut v = Vec::new();
            if let Some(p) = pt_of(e, "at") {
                v.push(p);
            }
            v
        }
        _ => Vec::new(),
    }
}

fn pval(p: P) -> Value {
    Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
}

/// An element moved as `f` says: a line's points to the micron, a note's and a region's as they
/// work out; a note keeps its own angle under a mirror, a region's pattern turns.
pub fn place_element(e: &mut Value, f: &Place) {
    let c = cat(e).to_string();
    let Some(m) = e.as_obj_mut() else { return };
    match c.as_str() {
        "line" => curve::place_curve(m, f, true),
        "text" => {
            for k in ["at", "leader"] {
                if let Some(p) = curve::pt(m.get(k)) {
                    m.insert(k, pval(f.point(p)));
                }
            }
            let a = m.get("angle").and_then(|x| x.as_f64()).unwrap_or(0.0);
            m.insert("angle", Value::f(f.turn_note(a)));
        }
        "region" => {
            if let Some(Value::Arr(a)) = m.get_mut("sketch") {
                for l in a.iter_mut() {
                    if let Some(lm) = l.as_obj_mut() {
                        curve::place_curve(lm, f, false);
                    }
                }
            }
            let po = curve::pt(m.get("pattern_origin")).unwrap_or([0.0, 0.0]);
            let po2 = f.point(po);
            if po2[0] == 0.0 && po2[1] == 0.0 {
                m.remove("pattern_origin");
            } else {
                curve::insert_after(m, &["sketch"], "pattern_origin", pval(po2));
            }
            let pa = m.get("pattern_angle").and_then(|x| x.as_f64()).unwrap_or(0.0);
            let pa2 = f.turn(pa);
            if pa2 == 0.0 {
                m.remove("pattern_angle");
            } else {
                curve::insert_after(m, &["sketch", "pattern_origin"], "pattern_angle", Value::f(pa2));
            }
        }
        _ => {}
    }
}

/// The frame a placed group draws its members in.
pub fn group_frame(e: &Value) -> Place {
    Place::group(
        pt_of(e, "at").unwrap_or([0.0, 0.0]),
        f_of(e, "angle").unwrap_or(0.0),
        e.get("mirrored").and_then(|m| m.as_bool()).unwrap_or(false),
    )
}

/// The frames a repeating detail draws its group in: one every `spacing` from `start`, turned
/// along the line to `end`.
pub fn repeat_frames(e: &Value) -> Vec<Place> {
    let a = pt_of(e, "start").unwrap_or([0.0, 0.0]);
    let b = pt_of(e, "end").unwrap_or([0.0, 0.0]);
    let sp = f_of(e, "spacing").unwrap_or(0.0);
    let mirrored = e.get("mirrored").and_then(|m| m.as_bool()).unwrap_or(false);
    let d = [b[0] - a[0], b[1] - a[1]];
    let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
    let angle = if l > 0.0 { d[1].atan2(d[0]).to_degrees() } else { 0.0 };
    let u = if l > 0.0 { [d[0] / l, d[1] / l] } else { [0.0, 0.0] };
    let n = repeat_count(e).min(MAX_REPEATS);
    (0..n)
        .map(|i| {
            let s = sp * i as f64;
            Place::group([a[0] + u[0] * s, a[1] + u[1] * s], angle, mirrored)
        })
        .collect()
}

/// The members of a type as elements of a view, placed as `f` says (no id or GUID of their own).
pub fn placed_members(pr: &Project, type_name: &str, f: &Place, view_guid: &str) -> Vec<Value> {
    members(pr, type_name)
        .iter()
        .filter_map(|m| m.get("element").cloned())
        .map(|mut e| {
            place_element(&mut e, f);
            e.set("view", Value::s(view_guid));
            e
        })
        .collect()
}

/// What a placed group or a repeating detail draws: its type's members as elements of its view,
/// where it draws them (for drawing, picking and snapping).
pub fn placed(pr: &Project, id: u64) -> Vec<Value> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let Some(t) = type_name(pr, e) else { return Vec::new() };
    let view = s_of(e, "view").unwrap_or("").to_string();
    match cat(e) {
        "detailgroup" => placed_members(pr, &t, &group_frame(e), &view),
        "repeatingdetail" => repeat_frames(e).iter().flat_map(|f| placed_members(pr, &t, f, &view)).collect(),
        _ => Vec::new(),
    }
}

// ---------------------------------------------------------------- create_group

const CG: &str = "create_group";

fn create_group(s: &mut Session, p: &Value) -> R<Value> {
    check_keys(p, CG, &["ids", "name"])?;
    let pr = &mut s.project;
    let ids = ids_param(pr, CG, p)?;
    if ids.is_empty() {
        return Err(format!("{}: `ids`: the detail lines, filled regions and text notes to group", CG));
    }
    for id in &ids {
        let c = cat_of(pr, *id);
        if !matches!(c.as_str(), "line" | "region" | "text") {
            return Err(format!(
                "{}: {} {} can't be in a detail group: it holds detail lines, filled regions and text notes",
                CG, c, id
            ));
        }
    }
    let view = s_of(pr.el(ids[0]).unwrap(), "view").map(|v| v.to_string());
    for id in &ids[1..] {
        if s_of(pr.el(*id).unwrap(), "view").map(|v| v.to_string()) != view {
            return Err(format!("{}: the elements are in different views; a group's members are all in one", CG));
        }
    }
    let given = opt_name(p, CG, "name")?;
    let names = type_names(pr);
    let name = match given {
        Some(n) => {
            if names.contains(&n) {
                return Err(format!("{}: there's already a detail group `{}`", CG, n));
            }
            n
        }
        None => {
            let mut k = 1;
            loop {
                let n = format!("Group {}", k);
                if !names.contains(&n) {
                    break n;
                }
                k += 1;
            }
        }
    };
    // the middle of what is grouped
    let mut all: Vec<P> = Vec::new();
    for id in &ids {
        all.extend(extent(pr.el(*id).unwrap()));
    }
    let mid = match curve::bounds(&all) {
        Some((lo, hi)) => [r3((lo[0] + hi[0]) / 2.0), r3((lo[1] + hi[1]) / 2.0)],
        None => [0.0, 0.0],
    };
    let tg = type_guid(pr, &name);
    let f = Place::minus(mid);
    let mut mem: Vec<Value> = Vec::new();
    for id in &ids {
        let mut e = pr.el(*id).unwrap().clone();
        if let Some(m) = e.as_obj_mut() {
            m.remove("guid");
            m.insert("view", Value::u(0));
            if let Some(Value::Arr(a)) = m.get_mut("sketch") {
                for l in a.iter_mut() {
                    if let Some(lm) = l.as_obj_mut() {
                        lm.remove("id");
                        lm.remove("guid");
                    }
                }
            }
        }
        place_element(&mut e, &f);
        let mid_id = pr.alloc_lib_id();
        mem.push(jobj! {"id" => mid_id, "guid" => crate::rand::guid(), "element" => e});
    }
    let gone: Vec<String> = ids.iter().map(|id| guid(pr, *id)).collect();
    for id in &ids {
        pr.elements.remove(id);
    }
    drop_references(pr, &gone);
    pr.section_mut(SECTION).insert_sorted(&name, jobj! {"members" => Value::Arr(mem)});
    let gid = pr.alloc_id();
    let mut g = Map::new();
    g.insert("guid", Value::s(&crate::rand::guid()));
    g.insert("category", Value::s("detailgroup"));
    g.insert("view", view.map(Value::from).unwrap_or(Value::Null));
    g.insert("type", Value::s(&tg));
    g.insert("at", pval(mid));
    pr.elements.insert(gid, Value::Obj(g));
    Ok(jobj! {"id" => gid, "name" => name})
}

/// What goes with elements taken into a group, as with a deleted one: dimensions lose their
/// references to them (one left with fewer than two goes). (A stand-in for the delete command's
/// own cascade, which EDIT owns.)
fn drop_references(pr: &mut Project, gone: &[String]) {
    let mut drop: Vec<u64> = Vec::new();
    for (id, e) in pr.elements.iter_mut() {
        if cat(e) != "dimension" {
            continue;
        }
        let Some(refs) = e.get_mut("refs").and_then(|r| r.as_arr_mut()) else { continue };
        let before = refs.len();
        refs.retain(|r| {
            let g = r.get("id").and_then(|x| x.as_str()).unwrap_or("");
            !gone.iter().any(|x| x == g)
        });
        if refs.len() != before && refs.len() < 2 {
            drop.push(*id);
        }
    }
    for id in drop {
        pr.elements.remove(&id);
    }
}

// ---------------------------------------------------------------- detail_group

const DG: &str = "detail_group";

fn no_such_type(pr: &Project, who: &str, name: &str) -> String {
    format!("{}: there's no detail group `{}` (there are: {})", who, name, type_names(pr).join(", "))
}

/// An angle as the file keeps it: to nine places.
fn r9(x: f64) -> f64 {
    let y = (x * 1e9).round() / 1e9;
    if y == 0.0 {
        0.0
    } else {
        y
    }
}

fn detail_group(s: &mut Session, p: &Value) -> R<Value> {
    use crate::commands::params::{opt_bool, opt_num, req_point};
    check_keys(p, DG, &["type", "at", "angle", "mirrored", "view", "level"])?;
    let pr = &mut s.project;
    let Some(t) = opt_name(p, DG, "type")? else {
        return Err(format!("{}: `type`, the detail group to place, is required", DG));
    };
    if !type_names(pr).contains(&t) {
        return Err(no_such_type(pr, DG, &t));
    }
    let at = req_point(p, DG, "at")?;
    let angle = opt_num(p, DG, "angle")?.unwrap_or(0.0);
    let mirrored = opt_bool(p, DG, "mirrored")?.unwrap_or(false);
    let view = view_or_level(pr, DG, p)?;
    let vg = guid(pr, view);
    let tg = type_guid(pr, &t);
    let id = pr.alloc_id();
    let mut g = Map::new();
    g.insert("guid", Value::s(&crate::rand::guid()));
    g.insert("category", Value::s("detailgroup"));
    g.insert("view", Value::s(&vg));
    g.insert("type", Value::s(&tg));
    g.insert("at", pval(at));
    let a = r9(angle);
    if a != 0.0 {
        g.insert("angle", Value::f(a));
    }
    if mirrored {
        g.insert("mirrored", Value::Bool(true));
    }
    pr.elements.insert(id, Value::Obj(g));
    Ok(jobj! {"id" => id})
}

// ---------------------------------------------------------------- repeating_detail

const RD: &str = "repeating_detail";

fn repeating_detail(s: &mut Session, p: &Value) -> R<Value> {
    use crate::commands::params::{opt_bool, req_point};
    check_keys(p, RD, &["type", "start", "end", "spacing", "mirrored", "view", "level"])?;
    let pr = &mut s.project;
    let Some(t) = opt_name(p, RD, "type")? else {
        return Err(format!("{}: `type`, the detail group to repeat, is required", RD));
    };
    let start = req_point(p, RD, "start")?;
    let end = req_point(p, RD, "end")?;
    let spacing = match get(p, "spacing") {
        None => return Err(format!("{}: `spacing`, mm from one group to the next, is required", RD)),
        Some(v) => mm_of(v).ok_or_else(|| format!("{}: `spacing` must be a number in mm, got {}", RD, v.to_compact()))?,
    };
    let mirrored = opt_bool(p, RD, "mirrored")?.unwrap_or(false);
    let view = view_or_level(pr, RD, p)?;
    let id = pr.alloc_id();
    let who = format!("repeatingdetail {}", id);
    view_check(pr, &who, Some(view))?;
    check_spacing(&who, spacing, start, end)?;
    if !type_names(pr).contains(&t) {
        return Err(no_such_type(pr, &who, &t));
    }
    let vg = guid(pr, view);
    let tg = type_guid(pr, &t);
    let mut g = Map::new();
    g.insert("guid", Value::s(&crate::rand::guid()));
    g.insert("category", Value::s("repeatingdetail"));
    g.insert("view", Value::s(&vg));
    g.insert("type", Value::s(&tg));
    g.insert("start", pval(start));
    g.insert("end", pval(end));
    g.insert("spacing", Value::f(spacing));
    if mirrored {
        g.insert("mirrored", Value::Bool(true));
    }
    let e = Value::Obj(g);
    let count = repeat_count(&e);
    pr.elements.insert(id, e);
    Ok(jobj! {"count" => count, "id" => id})
}

/// A repeating detail's spacing is from 1 mm, and it repeats at most 2000 times.
fn check_spacing(who: &str, sp: f64, start: P, end: P) -> R<()> {
    if !(sp >= 1.0 && sp <= 1e9) {
        return Err(format!("{}: spacing {} mm isn't from 1 mm to 1000000000", who, disp(sp)));
    }
    let e = jobj! {"start" => start, "end" => end, "spacing" => sp};
    if repeat_count(&e) > MAX_REPEATS {
        return Err(format!("{}: it would repeat more than {} times; space it wider or draw it shorter", who, MAX_REPEATS));
    }
    Ok(())
}

// ---------------------------------------------------------------- ungroup

const UG: &str = "ungroup";

fn ungroup(s: &mut Session, p: &Value) -> R<Value> {
    check_keys(p, UG, &["id"])?;
    let pr = &mut s.project;
    let v = p.get("id").cloned().unwrap_or(Value::Null);
    let id = element_ref(pr, UG, &v)?;
    let e = pr.el(id).unwrap().clone();
    if cat(&e) != "detailgroup" {
        return Err(format!("{}: element {} isn't a detail group", UG, id));
    }
    let t = type_name(pr, &e).unwrap_or_default();
    let view = s_of(&e, "view").unwrap_or("").to_string();
    let placed = placed_members(pr, &t, &group_frame(&e), &view);
    pr.elements.remove(&id);
    let mut ids = Vec::new();
    for el in placed {
        let nid = pr.alloc_id();
        let mut out = Map::new();
        out.insert("guid", Value::s(&crate::rand::guid()));
        if let Value::Obj(m) = el {
            for (k, v) in m.items {
                if k == "sketch" {
                    // the boundary lines become parts again, each with an id and a GUID
                    let mut fresh = Vec::new();
                    for l in v.as_arr().cloned().unwrap_or_default() {
                        let mut lm = Map::new();
                        lm.insert("id", Value::u(pr.alloc_lib_id()));
                        lm.insert("guid", Value::s(&crate::rand::guid()));
                        if let Value::Obj(o) = l {
                            lm.items.extend(o.items);
                        }
                        fresh.push(Value::Obj(lm));
                    }
                    out.items.push((k, Value::Arr(fresh)));
                } else {
                    out.items.push((k, v));
                }
            }
        }
        pr.elements.insert(nid, Value::Obj(out));
        ids.push(nid);
    }
    Ok(jobj! {"ids" => ids})
}

// ---------------------------------------------------------------- group_type

const GT: &str = "group_type";

fn group_type(s: &mut Session, p: &Value) -> R<Value> {
    use crate::commands::params::opt_bool;
    check_keys(p, GT, &["name", "rename", "delete"])?;
    let pr = &mut s.project;
    let Some(name) = opt_name(p, GT, "name")? else {
        let mut all = Map::new();
        for n in type_names(pr) {
            let g = pr.lib_guid(KIND, &n);
            let placed = pr
                .elements
                .values()
                .filter(|e| matches!(cat(e), "detailgroup" | "repeatingdetail") && s_of(e, "type") == g.as_deref())
                .count();
            all.insert(&n, jobj! {"members" => members(pr, &n).len(), "placed" => placed});
        }
        return Ok(jobj! {"groups" => Value::Obj(all)});
    };
    if !type_names(pr).contains(&name) {
        return Err(format!("{}: there's no detail group `{}`", GT, name));
    }
    let delete = opt_bool(p, GT, "delete")?.unwrap_or(false);
    if delete {
        if let Some(g) = pr.lib_guid(KIND, &name) {
            for (id, e) in &pr.elements {
                if matches!(cat(e), "detailgroup" | "repeatingdetail") && s_of(e, "type") == Some(g.as_str()) {
                    return Err(format!("{}: detail group {} is of `{}`; delete or ungroup it first", GT, id, name));
                }
            }
        }
        pr.section_mut(SECTION).remove(&name);
        if pr.section(SECTION).map(|s| s.is_empty()).unwrap_or(false) {
            pr.remove_top(SECTION);
        }
        if let Some(lid) = pr.lib_find(KIND, &name) {
            pr.library.remove(&lid);
        }
        return Ok(jobj! {"deleted" => name});
    }
    let rename = opt_name(p, GT, "rename")?;
    if let Some(r) = rename {
        if r != name {
            if type_names(pr).contains(&r) {
                return Err(format!("{}: there's already a detail group `{}`", GT, r));
            }
            let sec = pr.section_mut(SECTION);
            let v = sec.remove(&name).unwrap_or_else(Value::obj);
            sec.insert_sorted(&r, v);
            if let Some(lid) = pr.lib_find(KIND, &name) {
                if let Some(le) = pr.library.get_mut(&lid) {
                    le.set("name", Value::s(&r));
                }
            }
            return Ok(jobj! {"name" => r});
        }
    }
    Ok(jobj! {"name" => name})
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command: the types' members are what the
/// same elements in a view must be; a placed group and a repeating detail are in a view that
/// draws annotation, of a type the project has; a repeating detail's spacing is from 1 mm, and it
/// repeats at most 2000 times; a view draws at most 10000 group members.
pub fn check(pr: &Project) -> R<()> {
    for n in type_names(pr) {
        for (i, m) in members(pr, &n).iter().enumerate() {
            let Some(e) = m.get("element") else { continue };
            let who = format!("detail group `{}` member {}", n, i);
            match cat(e) {
                "region" => regions::check_region_refs(pr, &who, e)?,
                "text" => {
                    if let Some(g) = s_of(e, "type") {
                        let name = regions::lib_kind_name(pr, "text-type", g);
                        let mut all: Vec<String> =
                            pr.section("text_types").map(|s| s.keys().cloned().collect()).unwrap_or_default();
                        all.sort();
                        if !name.as_ref().map(|n| all.contains(n)).unwrap_or(false) {
                            return Err(format!(
                                "{}: there's no text type `{}` (there are: {})",
                                who,
                                name.unwrap_or_else(|| g.to_string()),
                                all.join(", ")
                            ));
                        }
                    }
                }
                "line" => {
                    if let Some(g) = s_of(e, "style") {
                        let name = regions::lib_kind_name(pr, "line-style", g);
                        if !name.as_ref().map(|n| regions::has_line_style(pr, n)).unwrap_or(false) {
                            return Err(format!("{}: there's no line style `{}`", who, name.unwrap_or_else(|| g.to_string())));
                        }
                    }
                }
                _ => {}
            }
        }
    }
    let mut per_view: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    for (id, e) in &pr.elements {
        let c = cat(e);
        if c != "detailgroup" && c != "repeatingdetail" {
            continue;
        }
        let who = format!("{} {}", c, id);
        if let Some(v) = ref_id(pr, e, "view") {
            view_check(pr, &who, Some(v))?;
        }
        if c == "repeatingdetail" {
            let sp = f_of(e, "spacing").unwrap_or(0.0);
            check_spacing(&who, sp, pt_of(e, "start").unwrap_or([0.0, 0.0]), pt_of(e, "end").unwrap_or([0.0, 0.0]))?;
        }
        let t = type_name(pr, e);
        let Some(t) = t.filter(|t| type_names(pr).contains(t)) else {
            let n = type_name(pr, e).unwrap_or_else(|| s_of(e, "type").unwrap_or("").to_string());
            return Err(no_such_type(pr, &who, &n));
        };
        let mut draws = members(pr, &t).len() as u64;
        if c == "repeatingdetail" {
            draws *= repeat_count(e);
        }
        let v = s_of(e, "view").unwrap_or("").to_string();
        let total = per_view.entry(v).or_insert(0);
        *total += draws;
        if *total > MAX_PLACED {
            return Err(format!(
                "{}: its view would draw {} group members (a group places each of its type's members, a repeating detail once for each repeat); a view draws up to {}, so use fewer repeats or a smaller group",
                who, total, MAX_PLACED
            ));
        }
    }
    Ok(())
}

/// What `elements` shows of this part's elements beyond their own fields: the view's level, the
/// type by name, how many members it has, and how many times a repeating detail repeats.
pub fn element_view(pr: &Project, _id: u64, x: &mut Value) {
    let e = x.clone();
    x.set("level", view_level(pr, &e));
    let t = type_name(pr, &e);
    if let Some(t) = &t {
        x.set("type", Value::s(t));
    }
    match cat(&e) {
        "detailgroup" => {
            let n = t.as_ref().map(|t| members(pr, t).len()).unwrap_or(0);
            x.set("members", Value::u(n as u64));
        }
        "repeatingdetail" => {
            x.set("count", Value::u(repeat_count(&e)));
        }
        _ => {}
    }
}

/// What `inspect` says of the sections this part keeps: nothing (it lists no detail groups).
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    let _ = (s, out);
}
