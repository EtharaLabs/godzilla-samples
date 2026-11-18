//! Tags: `tag` (Tag by Category and Tag All). A tag names an element that has a place in a plan
//! (`host`) with a field of it, in the level's own plan or in a plan view of the host's level
//! (`view`), at an `offset` from the point it names.

pub mod fields;
pub mod rooms;

use super::common::*;
use super::model::WallLine;
use super::notes::{clip_error, element_ref, usable};
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "tag" => tag(&mut s.project, &p.clone().sorted()).map_err(clip_error),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// The categories a tag can name: what has a place in a plan.
pub const TAGGABLE: &[&str] = &[
    "door",
    "window",
    "wall",
    "column",
    "structuralcolumn",
    "footing",
    "component",
    "floor",
    "ceiling",
    "roof",
    "room",
    "pipe",
    "duct",
    "conduit",
    "cabletray",
    "wire",
    "cable",
    "downconductor",
    "groundconductor",
    "beam",
    "stripfooting",
    "stair",
    "ramp",
];

pub fn taggable(c: &str) -> bool {
    TAGGABLE.contains(&c)
}

/// How far beside its wall a door's or a window's tag goes by default, mm.
pub const BESIDE: f64 = 500.0;
/// How far up and right of what it names any other tag goes by default, mm.
pub const UP_RIGHT: f64 = 400.0;

// ================================================================ geometry of what a tag names

/// A vector of unit length the way glam makes one (times the reciprocal of its length).
pub fn normalize(v: [f64; 2]) -> [f64; 2] {
    let inv = 1.0 / (v[0] * v[0] + v[1] * v[1]).sqrt();
    [v[0] * inv, v[1] * inv]
}

/// A point `d` along a wall's line from its start, and the unit vector of the way the line runs
/// there.
pub fn point_along(l: &WallLine, d: f64) -> ([f64; 2], [f64; 2]) {
    if !l.is_arc() {
        let u = normalize([l.end[0] - l.start[0], l.end[1] - l.start[1]]);
        return ([l.start[0] + u[0] * d, l.start[1] + u[1] * d], u);
    }
    let (c, r) = l.circle().unwrap();
    let a0 = (l.start[1] - c[1]).atan2(l.start[0] - c[0]);
    let sign = if l.arc > 0.0 { 1.0 } else { -1.0 };
    let a = a0 + sign * d / r;
    let p = [c[0] + r * a.cos(), c[1] + r * a.sin()];
    // counter-clockwise, the way runs a quarter turn on from the radius
    let dir = [-a.sin() * sign, a.cos() * sign];
    (p, dir)
}

/// Where a door or a window stands in plan (on its wall's location line, `offset` along it), its
/// wall's left normal there and how far the wall's centre line lies left of that point.
pub fn opening_point(pr: &Project, e: &Value) -> Option<([f64; 2], [f64; 2], f64)> {
    let wall = pr.el(ref_id(pr, e, "host")?)?;
    let line = super::model::location_line(wall);
    let (p, u) = point_along(&line, f_of(e, "offset").unwrap_or(0.0));
    Some((p, [-u[1], u[0]], super::model::centre_offset(pr, wall)))
}

/// The level an element stands on: a door's or a window's is its wall's.
pub fn host_level(pr: &Project, id: u64) -> Option<u64> {
    let e = pr.el(id)?;
    match cat(e) {
        "door" | "window" => {
            let w = ref_id(pr, e, "host")?;
            ref_id(pr, pr.el(w)?, "level")
        }
        _ => ref_id(pr, e, "level"),
    }
}

/// The middle of a wall's location line (of its arc, for a curved one).
pub fn wall_middle(e: &Value) -> [f64; 2] {
    let l = super::model::location_line(e);
    point_along(&l, l.length() / 2.0).0
}

/// The point a tag of an element names: a door's or a window's place in its wall, a wall's
/// middle, a room's point, a column's, footing's or component's place, the middle of the corners
/// of a floor, ceiling or roof, the middle of a run, a stair's or a ramp's start.
pub fn anchor(pr: &Project, id: u64) -> Option<[f64; 2]> {
    let e = pr.el(id)?;
    match cat(e) {
        "door" | "window" => opening_point(pr, e).map(|(p, _, _)| p),
        "wall" => Some(wall_middle(e)),
        "room" => pt_of(e, "point"),
        "column" | "structuralcolumn" | "footing" | "component" => pt_of(e, "at"),
        "floor" | "ceiling" | "roof" => {
            let b = pts_of(e, "boundary")?;
            if b.is_empty() {
                return None;
            }
            let n = b.len() as f64;
            let s = b.iter().fold([0.0, 0.0], |a, p| [a[0] + p[0], a[1] + p[1]]);
            Some([s[0] / n, s[1] / n])
        }
        "stair" | "ramp" => pt_of(e, "start"),
        _ => {
            let a = pt_of(e, "start")?;
            let b = pt_of(e, "end").unwrap_or(a);
            Some(super::model::mid(a, b))
        }
    }
}

/// Where a new tag of an element goes from the point it names: a door's beside its wall on the
/// side it opens to (the other with `flip_facing`), a window's on its outer side, anything else's
/// up and right.
pub fn default_offset(pr: &Project, id: u64) -> [f64; 2] {
    let Some(e) = pr.el(id) else { return [UP_RIGHT, UP_RIGHT] };
    match cat(e) {
        c @ ("door" | "window") => {
            let Some((_, n, co)) = opening_point(pr, e) else { return [UP_RIGHT, UP_RIGHT] };
            let flip = e.get("flip_facing").and_then(|f| f.as_bool()).unwrap_or(false);
            let mut k = if c == "door" { -BESIDE } else { BESIDE };
            if flip {
                k = -k;
            }
            // beside the wall's centre line, which may lie off the line the door stands on
            [n[0] * (co + k) + 0.0, n[1] * (co + k) + 0.0]
        }
        _ => [UP_RIGHT, UP_RIGHT],
    }
}

// ================================================================ views

/// The plan a tag is drawn in: its `view` (a plan view), else its host's level's own plan.
pub fn tag_view(pr: &Project, e: &Value) -> Option<u64> {
    if let Some(v) = ref_id(pr, e, "view") {
        return Some(v);
    }
    host_level(pr, ref_id(pr, e, "host")?)
}

/// Whether a plan shows a tag: one drawn in it, or (a dependent view) in its parent.
pub fn plan_shows_tag(pr: &Project, plan: u64, e: &Value) -> bool {
    let Some(v) = tag_view(pr, e) else { return false };
    if v == plan {
        return true;
    }
    match pr.el(plan).and_then(|p| ref_id(pr, p, "parent")) {
        Some(parent) => parent == v,
        None => false,
    }
}

/// Whether a level's own plan hides an element (its category, or it).
fn level_hides(pr: &Project, level: u64, id: u64) -> bool {
    let Some(g) = pr.el(level).and_then(|l| l.get("graphics")) else { return false };
    let c = cat_of(pr, id);
    if g.get("categories").and_then(|m| m.get(&c)).and_then(|o| o.get("hidden")).and_then(|h| h.as_bool()) == Some(true) {
        return true;
    }
    let gid = guid(pr, id);
    let by_guid = g.get("elements").and_then(|m| m.get(&gid)).and_then(|o| o.get("hidden")).and_then(|h| h.as_bool());
    let by_id = g.get("elements").and_then(|m| m.get(&id.to_string())).and_then(|o| o.get("hidden")).and_then(|h| h.as_bool());
    by_guid == Some(true) || by_id == Some(true)
}

/// A category as `category` gives it: letters and digits in lower case, plurals' `s` taken off.
pub fn category_key(s: &str) -> String {
    let key: String = s.chars().filter(|c| c.is_alphanumeric()).flat_map(|c| c.to_lowercase()).collect();
    // a category whose name ends in `s` is itself, and its plural takes `es`
    for c in ["mass"] {
        if key == c || key == format!("{}es", c) {
            return c.to_string();
        }
    }
    key.trim_end_matches('s').to_string()
}

/// A level, or a plan view of one, from `key` (the lowest level by default): the level and the
/// plan view named, if one was.
pub fn plan_param(pr: &Project, cmd: &str, p: &Value, key: &str) -> R<(u64, Option<u64>)> {
    let level = crate::model::level_param(pr, cmd, p, key)?;
    let view = match get(p, key) {
        Some(v) => {
            let found = match v {
                Value::Str(s) => crate::model::find(pr, v).or_else(|| {
                    if crate::model::levels(pr).iter().any(|l| crate::model::name(pr, *l) == *s) {
                        None
                    } else {
                        pr.ids_of("planview").into_iter().find(|id| crate::model::name(pr, *id) == *s)
                    }
                }),
                _ => crate::model::find(pr, v),
            };
            found.filter(|id| cat_of(pr, *id) == "planview")
        }
        None => None,
    };
    Ok((level, view))
}

// ================================================================ tag

fn tag(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "tag";
    let offset = crate::commands::params::opt_point(p, CMD, "offset")?;
    let leader = crate::commands::params::opt_bool(p, CMD, "leader")?.unwrap_or(false);
    let label = crate::commands::params::opt_text(p, CMD, "label")?.filter(|l| !l.trim().is_empty());
    let (level, view) = plan_param(pr, CMD, p, "level")?;
    let plan = view.unwrap_or(level);
    let hosts: Vec<u64> = match get(p, "ids") {
        Some(v) => {
            let a = v.as_arr().ok_or("tag: `ids` [id, …] is required")?;
            let mut out: Vec<u64> = Vec::new();
            for x in a {
                let id = element_ref(pr, CMD, x)?;
                if !out.contains(&id) {
                    out.push(id);
                }
            }
            out
        }
        None => {
            let want = crate::commands::params::opt_text(p, CMD, "category")?.map(|c| category_key(&c));
            let tags: Vec<Value> = pr.ids_of("tag").iter().filter_map(|t| pr.el(*t).cloned()).collect();
            let mut out = Vec::new();
            for (id, e) in &pr.elements {
                let c = cat(e);
                let wanted = match &want {
                    Some(w) => c == w,
                    None => c == "door" || c == "window",
                };
                if !wanted || host_level(pr, *id) != Some(level) || level_hides(pr, level, *id) {
                    continue;
                }
                let g = guid(pr, *id);
                let tagged = tags.iter().any(|t| s_of(t, "host") == Some(g.as_str()) && plan_shows_tag(pr, plan, t));
                if !tagged {
                    out.push(*id);
                }
            }
            if out.is_empty() {
                return Err(format!(
                    "tag: nothing to tag: {} has no {} without a tag",
                    crate::model::name(pr, level),
                    want.unwrap_or_else(|| "door and window".into())
                ));
            }
            out
        }
    };
    let mut ids = Vec::new();
    for h in hosts {
        let off = offset.unwrap_or_else(|| default_offset(pr, h));
        let id = pr.alloc_id();
        let mut m = Map::new();
        m.insert("guid", Value::s(&crate::rand::guid()));
        m.insert("category", Value::s("tag"));
        m.insert("host", Value::s(&guid(pr, h)));
        if let Some(v) = view {
            m.insert("view", Value::s(&guid(pr, v)));
        }
        m.insert("offset", pt_value(off));
        m.insert("leader", Value::Bool(leader));
        if let Some(l) = &label {
            m.insert("label", Value::s(l));
        }
        pr.elements.insert(id, Value::Obj(m));
        ids.push(id);
    }
    super::mark_step();
    Ok(jobj! {"ids" => ids})
}

// ================================================================ the model's rules

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    for (id, e) in &pr.elements {
        if cat(e) != "tag" {
            continue;
        }
        let host = ref_id(pr, e, "host");
        let host_cat = host.map(|h| cat_of(pr, h)).unwrap_or_default();
        let host_guid = s_of(e, "host").unwrap_or("").to_string();
        if let Some(v) = ref_id(pr, e, "view") {
            let ok = cat_of(pr, v) == "planview"
                && host.and_then(|h| host_level(pr, h)).is_some()
                && crate::model::level_of_view(pr, v) == host.and_then(|h| host_level(pr, h));
            if !ok {
                return Err(format!("tag {}: view {} isn't a plan view of its host's level", id, v));
            }
        }
        if host.is_some() && !taggable(&host_cat) {
            return Err(format!(
                "tag {}: tags name what has a place in a plan (doors, windows, walls, columns, floors, rooms and the like), not {} {}",
                id, host_cat, host_guid
            ));
        }
        if let (Some(h), Some(Value::Str(l))) = (host, e.get("label")) {
            let names = fields::field_names(pr, h);
            if !names.iter().any(|n| n == l) {
                return Err(format!(
                    "tag {}: {} {} has no field `{}`; its fields are: {}",
                    id,
                    host_cat,
                    host_guid,
                    l,
                    names.join(", ")
                ));
            }
        }
        if let Some(o) = pt_of(e, "offset") {
            for (what, x) in [("offset x", o[0]), ("offset y", o[1])] {
                if !usable(x) {
                    return Err(format!("tag {} {}: {} is not a usable number", id, what, disp(x)));
                }
            }
        }
    }
    Ok(())
}

/// What `elements` shows of a tag beyond its own fields: where it stands (`at`), its host's
/// level and its text.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    let Some(h) = ref_id(pr, e, "host") else { return };
    let off = pt_of(e, "offset").unwrap_or([0.0, 0.0]);
    if let Some(a) = anchor(pr, h) {
        x.set("at", pt_value([a[0] + off[0], a[1] + off[1]]));
    }
    x.set("level", host_level(pr, h).map(|l| Value::s(&guid(pr, l))).unwrap_or(Value::Null));
    x.set("text", Value::s(&tag_text(pr, e)));
}

/// What a tag reads: its label's field of its host, else a door's or a window's mark, a room's
/// name, or the host's type ("?" for what has none).
pub fn tag_text(pr: &Project, e: &Value) -> String {
    let Some(h) = ref_id(pr, e, "host") else { return "?".into() };
    if let Some(l) = s_of(e, "label") {
        return fields::field_text(pr, h, l);
    }
    let he = match pr.el(h) {
        Some(x) => x,
        None => return "?".into(),
    };
    let t = match cat(he) {
        "door" | "window" => s_of(he, "mark").unwrap_or("").to_string(),
        "room" => s_of(he, "name").unwrap_or("").to_string(),
        _ => fields::type_name(pr, he).unwrap_or_default(),
    };
    if t.is_empty() {
        "?".into()
    } else {
        t
    }
}
