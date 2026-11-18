//! Linework: `linework` (an edge of an element drawn in a line style in one plan, or hidden
//! there). A plan's `graphics.linework` holds each edge as the element's GUID, the edge's two ends
//! and a line style (none: hidden). The edge is the one the plan draws nearest the point given,
//! found as the original finds it: the plan drawn again around the point, a pixel to `PIXEL` mm,
//! and the nearest segment of the element's lines within `REACH`.

pub mod family;
pub mod plan;

use super::common::*;
use super::notes::{clip_error, element_ref, usable, view_ref_of};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use plan::{element_lines, plan_of, Plan};

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "linework" => linework(&mut s.project, &p.clone().sorted()).map_err(clip_error),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

pub const PARAMS: &[&str] = &["view", "level", "id", "at", "style", "invisible", "remove"];

/// How near the point an edge is picked, mm.
pub const REACH: f64 = 200.0;
/// The most edges of Linework a view holds.
pub const MAX_LINEWORK: usize = 2000;

/// The scale of the drawing edges are picked in (px a mm), and its middle (px).
const SCALE: f64 = 1.0 / plan::PIXEL;
const MIDDLE: f64 = 500.0;

/// A point as the picking drawing holds it: pixels round the point picked, in single precision.
fn to_px(p: [f64; 2], at: [f64; 2]) -> [f64; 2] {
    [((p[0] - at[0]) * SCALE + MIDDLE) as f32 as f64, ((at[1] - p[1]) * SCALE + MIDDLE) as f32 as f64]
}

fn from_px(q: [f64; 2], at: [f64; 2]) -> [f64; 2] {
    [(q[0] - MIDDLE) / SCALE + at[0], at[1] - (q[1] - MIDDLE) / SCALE]
}

fn px_dist(p: [f64; 2], a: [f64; 2], b: [f64; 2]) -> f64 {
    plan::seg_dist(p, a, b)
}

/// The edge of an element a plan draws nearest a point within reach, as the picking drawing
/// gives its ends back.
pub fn edge_at(pr: &Project, pl: &Plan, id: u64, at: [f64; 2]) -> Option<([f64; 2], [f64; 2])> {
    let pl = Plan { frame: Some(at), ..*pl };
    let lines = element_lines(pr, &pl, id);
    let c = [MIDDLE, MIDDLE];
    let mut best: Option<(f64, [f64; 2], [f64; 2])> = None;
    for l in &lines {
        for (a, b) in l.segments() {
            let (pa, pb) = (to_px(a, at), to_px(b, at));
            let d = px_dist(c, pa, pb);
            if d / SCALE <= REACH && best.map(|(bd, _, _)| d < bd).unwrap_or(true) {
                best = Some(if l.exact { (d, a, b) } else { (d, from_px(pa, at), from_px(pb, at)) });
            }
        }
    }
    best.map(|(_, a, b)| (a, b))
}

/// Every edge an element draws in a plan (in plan mm, as drawn round the point).
fn edges(pr: &Project, pl: &Plan, id: u64, at: [f64; 2]) -> Vec<([f64; 2], [f64; 2])> {
    let mut out = Vec::new();
    let pl = Plan { frame: Some(at), ..*pl };
    for l in element_lines(pr, &pl, id) {
        for (a, b) in l.segments() {
            if l.exact {
                out.push((a, b));
            } else {
                out.push((from_px(to_px(a, at), at), from_px(to_px(b, at), at)));
            }
        }
    }
    out
}

fn same_end(a: [f64; 2], b: [f64; 2]) -> bool {
    (a[0] - b[0]).abs() < 0.01 && (a[1] - b[1]).abs() < 0.01
}

/// Whether an entry lies on an edge (its ends, either way round).
fn on_edge(e: &Value, from: [f64; 2], to: [f64; 2]) -> bool {
    let (Some(f), Some(t)) = (pt_of(e, "from"), pt_of(e, "to")) else { return false };
    (same_end(f, from) && same_end(t, to)) || (same_end(f, to) && same_end(t, from))
}

/// The view whose graphics keep a plan's Linework: a dependent view's parent.
fn holder(pr: &Project, key: u64) -> u64 {
    pr.el(key).and_then(|e| ref_id(pr, e, "parent")).unwrap_or(key)
}

fn linework(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "linework";
    crate::styles::common::check_keys(p, CMD, PARAMS)?;
    let key = match get(p, "view") {
        Some(v) => {
            let id = view_ref_of(pr, CMD, "view", v, false)?;
            if !is_plan(pr, id) {
                return Err("linework: Linework works in plans: give a level's plan or a plan view as `view`".into());
            }
            id
        }
        None => {
            let (level, view) = super::tags::plan_param(pr, CMD, p, "level")?;
            view.unwrap_or(level)
        }
    };
    let id = element_ref(pr, CMD, p.get("id").unwrap_or(&Value::Null))?;
    let at = crate::commands::params::req_point(p, CMD, "at")?;
    let remove = crate::commands::params::opt_bool(p, CMD, "remove")?.unwrap_or(false);
    let invisible = crate::commands::params::opt_bool(p, CMD, "invisible")?.unwrap_or(false);
    let style = super::notes::opt_name(p, CMD, "style")?;
    if !remove && !invisible && style.is_none() {
        return Err("linework: give `style`, a line style, or `invisible: true`; `remove: true` takes Linework off".into());
    }
    // a style given must be the project's, whatever else is asked; hidden, the edge keeps none
    let style_guid = match &style {
        Some(s) => Some(line_style_guid(pr, s).ok_or_else(|| {
            format!("linework: there's no line style `{}` (there are: {})", s, line_style_names(pr).join(", "))
        })?),
        None => None,
    }
    .filter(|_| !invisible);
    let Some(pl) = plan_of(pr, key) else {
        return Err("linework: Linework works in plans: give a level's plan or a plan view as `view`".into());
    };
    let edge = edge_at(pr, &pl, id, at);
    let hold = holder(pr, key);
    let eg = guid(pr, id);
    super::mark_step();
    if remove {
        let mut list = entries(pr, hold);
        let mut removed = 0;
        let on_picked = edge.and_then(|(f, t)| {
            list.iter().position(|e| s_of(e, "element") == Some(eg.as_str()) && on_edge(e, r3p(f), r3p(t)))
        });
        if let Some(k) = on_picked {
            list.remove(k);
            removed = 1;
        } else {
            // the nearest entry within reach on an edge the element no longer draws
            let drawn = edges(pr, &pl, id, at);
            let mut best: Option<(f64, usize)> = None;
            for (k, e) in list.iter().enumerate() {
                if s_of(e, "element") != Some(eg.as_str()) {
                    continue;
                }
                let (Some(f), Some(t)) = (pt_of(e, "from"), pt_of(e, "to")) else { continue };
                if drawn.iter().any(|(a, b)| on_edge(e, r3p(*a), r3p(*b))) {
                    continue;
                }
                let d = plan::seg_dist(at, f, t);
                if d <= REACH && best.map(|(bd, _)| d < bd).unwrap_or(true) {
                    best = Some((d, k));
                }
            }
            if let Some((_, k)) = best {
                list.remove(k);
                removed = 1;
            }
        }
        set_entries(pr, hold, list);
        return Ok(jobj! {"removed" => removed as u64});
    }
    let Some((from, to)) = edge else {
        return Err(format!(
            "linework: element {} draws no edge within {} mm of [{}, {}] in that view",
            id,
            disp(REACH),
            disp(at[0]),
            disp(at[1])
        ));
    };
    let (f3, t3) = (r3p(from), r3p(to));
    let mut list = entries(pr, hold);
    list.retain(|e| !(s_of(e, "element") == Some(eg.as_str()) && on_edge(e, f3, t3)));
    let mut m = Map::new();
    m.insert("element", Value::s(&eg));
    m.insert("from", pt_value(f3));
    m.insert("to", pt_value(t3));
    if let Some(g) = style_guid {
        m.insert("style", Value::s(&g));
    }
    list.push(Value::Obj(m));
    set_entries(pr, hold, list);
    Ok(jobj! {"from" => pt_value(from), "to" => pt_value(to)})
}

// ---------------------------------------------------------------- line styles

fn line_style_guid(pr: &Project, name: &str) -> Option<String> {
    pr.lib_guid("line-style", name)
}

/// The project's line styles' names in order.
fn line_style_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = pr
        .library
        .values()
        .filter(|e| s_of(e, "kind") == Some("line-style"))
        .filter_map(|e| s_of(e, "name").map(|s| s.to_string()))
        .collect();
    v.sort();
    v.dedup();
    v
}

// ---------------------------------------------------------------- a view's entries

fn entries(pr: &Project, view: u64) -> Vec<Value> {
    pr.el(view)
        .and_then(|e| e.get("graphics"))
        .and_then(|g| g.get("linework"))
        .and_then(|l| l.as_arr())
        .cloned()
        .unwrap_or_default()
}

/// Puts a view's entries back: none takes `linework` away, and its graphics where that leaves
/// them empty.
fn set_entries(pr: &mut Project, view: u64, list: Vec<Value>) {
    let Some(e) = pr.el_mut(view) else { return };
    if list.is_empty() {
        if let Some(g) = e.get_mut("graphics") {
            g.remove("linework");
            if g.as_obj().map(|m| m.is_empty()).unwrap_or(false) {
                e.remove("graphics");
            }
        }
        return;
    }
    let g = obj_field(e, "graphics");
    g.insert("linework", Value::Arr(list));
}

// ---------------------------------------------------------------- the model's rules

/// The model rules of this part, checked after every command: a view's Linework is at most
/// `MAX_LINEWORK` edges, their ends usable numbers, their styles the project's.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        let Some(list) = e.get("graphics").and_then(|g| g.get("linework")).and_then(|l| l.as_arr()) else { continue };
        let name = format!("{} {}", cat(e), id);
        if list.len() > MAX_LINEWORK {
            return Err(format!(
                "{}: it has {} edges of Linework; a view holds up to {}, so take some off (linework with remove)",
                name,
                list.len(),
                MAX_LINEWORK
            ));
        }
        for (k, x) in list.iter().enumerate() {
            let ends = [pt_of(x, "from"), pt_of(x, "to")];
            if ends.iter().any(|p| match p {
                Some(p) => !usable(p[0]) || !usable(p[1]),
                None => false,
            }) {
                return Err(format!("{}: Linework edge {}: its ends are numbers within 1000000000 mm", name, k));
            }
            if let Some(st) = s_of(x, "style") {
                let ok = crate::styles::common::name_of_guid(pr, "line-style", st).is_some();
                if !ok {
                    return Err(format!(
                        "{}: Linework edge {}: there's no line style `{}` (there are: {})",
                        name,
                        k,
                        st,
                        line_style_names(pr).join(", ")
                    ));
                }
            }
        }
    }
    Ok(())
}

/// What `elements` shows of a view's Linework: each edge's line style by name. For the views'
/// `element_view` of levels and plan views to call.
pub fn show_linework(pr: &Project, x: &mut Value) {
    let Some(list) = x.get_mut("graphics").and_then(|g| g.get_mut("linework")).and_then(|l| l.as_arr_mut()) else { return };
    for e in list.iter_mut() {
        if let Some(g) = e.get("style").and_then(|s| s.as_str()).map(|s| s.to_string()) {
            if let Some(n) = crate::styles::common::name_of_guid(pr, "line-style", &g) {
                e.set("style", Value::s(&n));
            }
        }
    }
}

/// An element's Linework goes with it: the entries of the elements deleted (by GUID), taken out
/// of every view. For `delete` to call.
pub fn forget(pr: &mut Project, guids: &[String]) {
    let views: Vec<u64> = pr.elements.iter().filter(|(_, e)| e.get("graphics").and_then(|g| g.get("linework")).is_some()).map(|(id, _)| *id).collect();
    for v in views {
        let list: Vec<Value> = entries(pr, v)
            .into_iter()
            .filter(|e| !s_of(e, "element").map(|g| guids.iter().any(|x| x == g)).unwrap_or(false))
            .collect();
        set_entries(pr, v, list);
    }
}
