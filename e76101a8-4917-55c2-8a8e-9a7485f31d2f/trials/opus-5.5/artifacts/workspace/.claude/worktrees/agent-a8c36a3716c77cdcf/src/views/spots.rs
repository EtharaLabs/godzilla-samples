//! Spot elevations and slopes: `spot`, `spot_slope`.
//!
//! A `spot` keeps its `view` (a plan, a section or an elevation, by GUID), the point it is at
//! (`at`, plan mm in a plan; along and up in a section or an elevation), what it reads (`host`, a
//! GUID, in a plan) and, for a spot slope, `slope: true`. What it reads it reads live: in a plan
//! the top of its host at its point (or its slope there), in a section its point's height.

use super::common::*;
use super::view3d::{self, scene};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// A height or a slope as the original reports it, to the hundredth.
pub fn r2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// A point as the original's messages show it: [5000, -100.5].
fn show(p: [f64; 2]) -> String {
    format!("[{}, {}]", disp(p[0]), disp(p[1]))
}

/// What `host` names: an id (number or digits) or a GUID; `Err` for anything else.
fn host_param(p: &Value, cmd: &str) -> R<Option<Host>> {
    let Some(v) = get(p, "host") else { return Ok(None) };
    let bad = || format!("{}: `host` must be an element id or GUID, got {}", cmd, v.clone().sorted().to_compact());
    match v {
        Value::Num(_) => id_of(v).map(|id| Some(Host::Id(id))).ok_or_else(bad),
        Value::Str(s) => {
            if let Ok(id) = s.trim().parse::<u64>() {
                return Ok(Some(Host::Id(id)));
            }
            match view3d::strict_guid(s) {
                Some(g) => Ok(Some(Host::Guid(g))),
                None => Err(bad()),
            }
        }
        _ => Err(bad()),
    }
}

#[derive(Clone, Debug)]
enum Host {
    Id(u64),
    Guid(String),
}

impl Host {
    fn resolve(&self, pr: &Project) -> Option<u64> {
        match self {
            Host::Id(id) => pr.elements.contains_key(id).then_some(*id),
            Host::Guid(g) => pr.find_guid(g),
        }
    }
    fn name(&self) -> String {
        match self {
            Host::Id(id) => id.to_string(),
            Host::Guid(g) => g.clone(),
        }
    }
}

/// The view a spot goes in: `view`, else the lowest level's plan.
fn view_param(pr: &Project, cmd: &str, p: &Value) -> R<u64> {
    match get(p, "view") {
        None => default_plan(pr).ok_or_else(|| format!("{}: the project has no level", cmd)),
        Some(v) => view3d::lookup_view(pr, cmd, "view", v),
    }
}

/// The id the next element made gets.
fn next_id(pr: &Project) -> u64 {
    let mut id = pr.next_id();
    while pr.elements.contains_key(&id) {
        id += 1;
    }
    id
}

/// A spot's view is a plan, a section or an elevation.
fn view_ok(pr: &Project, view: u64) -> bool {
    matches!(cat_of(pr, view).as_str(), "level" | "planview" | "section" | "elevation")
}

fn view_refused(pr: &Project, id: u64, view: u64) -> String {
    format!("spot {}: {} isn't a plan, a section, an elevation", id, cat_id(pr, view))
}

/// What stands on a plan's level at a point, the highest top (the last made of those as high):
/// its id and that top.
pub fn highest_at(pr: &Project, level: u64, p: [f64; 2], slopes_only: bool) -> Option<(u64, f64)> {
    let lg = guid(pr, level);
    let walls = scene::walls(pr);
    let mut best: Option<(u64, f64)> = None;
    for (id, e) in &pr.elements {
        if s_of(e, "level") != Some(lg.as_str()) {
            continue;
        }
        let c = cat(e);
        if slopes_only && !matches!(c, "floor" | "roof") {
            continue;
        }
        if !slopes_only && !scene::spot_reads(c) {
            continue;
        }
        if let Some(z) = scene::top_at_in(pr, *id, p, &walls) {
            if best.map_or(true, |(_, b)| z >= b) {
                best = Some((*id, z));
            }
        }
    }
    best
}

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "spot" => spot(s, p),
        "spot_slope" => spot_slope(s, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

fn spot(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "spot";
    let at = crate::commands::params::req_point(p, cmd, "at")?;
    let pr = &s.project;
    let view = view_param(pr, cmd, p)?;
    let host = host_param(p, cmd)?;
    let id = next_id(pr);
    let level = plan_level(pr, view);
    let (host_id, elevation) = match (level, &host) {
        (Some(_), Some(h)) => {
            let hid = h.resolve(pr);
            (hid, hid.and_then(|h| scene::top_at(pr, h, at)))
        }
        (Some(l), None) => match highest_at(pr, l, at, false) {
            Some((h, z)) => (Some(h), Some(z)),
            None => {
                return Err(format!(
                    "{}: nothing to read at {} on {}; place it on a floor, a roof, a stair, a wall or a column",
                    cmd,
                    show(at),
                    name_of(pr, l)
                ))
            }
        },
        (None, h) => (h.as_ref().and_then(|h| h.resolve(pr)), Some(at[1])),
    };
    if !view_ok(pr, view) {
        return Err(view_refused(pr, id, view));
    }
    if let (Some(h), None) = (&host, host_id) {
        return Err(format!("spot {}: element {} doesn't exist", id, h.name()));
    }
    let pr = &mut s.project;
    let id = pr.alloc_id();
    let mut e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "spot",
        "view" => guid(pr, view),
        "at" => at,
    };
    if let Some(h) = host_id {
        e.set("host", Value::s(&guid(pr, h)));
    }
    pr.elements.insert(id, e);
    Ok(jobj! {"elevation" => elevation.map(r2), "host" => host_id, "id" => id})
}

/// A slope as the original reports it: percent to the hundredth, and the way down in plan.
fn slope_reply(sl: (f64, Option<[f64; 2]>)) -> (Value, Value) {
    (Value::f(r2(sl.0 * 100.0)), sl.1.map(|d| Value::from([r2(d[0]), r2(d[1])])).unwrap_or(Value::Null))
}

fn spot_slope(s: &mut Session, p: &Value) -> R<Value> {
    let cmd = "spot_slope";
    let at = crate::commands::params::req_point(p, cmd, "at")?;
    let pr = &s.project;
    let view = view_param(pr, cmd, p)?;
    let Some(level) = plan_level(pr, view) else {
        return Err(format!("{}: a spot slope reads a floor's or a roof's top: place it in a plan", cmd));
    };
    let host = host_param(p, cmd)?;
    let none = || {
        format!(
            "{}: no slope to read at {} on {}; place it on a floor or a roof",
            cmd,
            show(at),
            name_of(pr, level)
        )
    };
    let hid = match &host {
        Some(h) => {
            let hid = h.resolve(pr).ok_or_else(none)?;
            if !matches!(cat_of(pr, hid).as_str(), "floor" | "roof") || scene::top_at(pr, hid, at).is_none() {
                return Err(none());
            }
            hid
        }
        None => {
            // what stands there, which has to be a floor or a roof
            let h = highest_at(pr, level, at, false).map(|(h, _)| h).ok_or_else(none)?;
            if !matches!(cat_of(pr, h).as_str(), "floor" | "roof") {
                return Err(none());
            }
            h
        }
    };
    let sl = scene::slope_at(pr, hid, at).ok_or_else(none)?;
    let pr = &mut s.project;
    let id = pr.alloc_id();
    let e = jobj! {
        "guid" => crate::rand::guid(),
        "category" => "spot",
        "view" => guid(pr, view),
        "at" => at,
        "host" => guid(pr, hid),
        "slope" => true,
    };
    pr.elements.insert(id, e);
    let (slope, toward) = slope_reply(sl);
    Ok(jobj! {"host" => hid, "id" => id, "slope" => slope, "toward" => toward})
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) != "spot" {
            continue;
        }
        if let Some(v) = ref_id(pr, e, "view") {
            if !view_ok(pr, v) {
                return Err(view_refused(pr, *id, v));
            }
        }
        if let Some(g) = s_of(e, "host") {
            if pr.find_guid(g).is_none() {
                return Err(format!("spot {}: element {} doesn't exist", id, g));
            }
        }
    }
    Ok(())
}

/// What `elements` shows of a spot beyond its own fields: the `level` of its plan (null in a
/// section), and what it reads now: its `elevation`, or a spot slope's `slope` (percent) and
/// `toward` (the way down in plan).
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    let view = ref_id(pr, e, "view");
    let level = view.and_then(|v| plan_level(pr, v));
    x.set("level", level.map(|l| Value::s(&guid(pr, l))).unwrap_or(Value::Null));
    let at = pt_of(e, "at").unwrap_or([0.0, 0.0]);
    let host = ref_id(pr, e, "host");
    if e.get("slope").and_then(|s| s.as_bool()) == Some(true) {
        let sl = host.and_then(|h| scene::slope_at(pr, h, at));
        match sl {
            Some(sl) => {
                let (slope, toward) = slope_reply(sl);
                x.set("slope", slope);
                x.set("toward", toward);
            }
            None => {
                x.set("slope", Value::Null);
                x.set("toward", Value::Null);
            }
        }
        return;
    }
    let elevation = match level {
        Some(_) => host.and_then(|h| scene::top_at(pr, h, at)),
        None => Some(at[1]),
    };
    x.set("elevation", elevation.map(|z| Value::f(r2(z))).unwrap_or(Value::Null));
}

/// The spots that read an element (for `delete`: what a spot elevation reads takes it).
pub fn spots_reading(pr: &Project, id: u64) -> Vec<u64> {
    let g = guid(pr, id);
    pr.elements
        .iter()
        .filter(|(_, e)| cat(e) == "spot" && s_of(e, "host") == Some(g.as_str()))
        .map(|(i, _)| *i)
        .collect()
}
