//! Dimensions: `dimension` (aligned, linear, angular, radial, diameter, arc length).

pub mod geom;
pub mod labels;
pub mod measure;
pub mod pick;
pub mod refs;

use super::common::*;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;
use measure::{Ctx, Dim, Kind, Orient};
use refs::RefIn;

const CMD: &str = "dimension";

/// The dimension type a kind starts in.
pub fn default_type(kind: Kind) -> &'static str {
    match kind {
        Kind::Radial | Kind::Diameter => "Arrow - 2.5mm Arial",
        _ => "Diagonal - 2.5mm Arial",
    }
}

/// The project's dimension types' names, as the original lists them.
pub fn type_names(pr: &Project) -> Vec<String> {
    let mut v: Vec<String> = match pr.section("dimension_types") {
        Some(m) => m.keys().cloned().collect(),
        None => vec!["Arrow - 2.5mm Arial".into(), "Diagonal - 2.5mm Arial".into()],
    };
    v.sort();
    v
}

/// The GUID of a dimension type by name: its library entry's (made where the project has the
/// type but not yet the entry).
fn type_guid(pr: &mut Project, name: &str) -> Option<String> {
    // a type given by its GUID (in braces, in any case)
    let g = name.trim_start_matches('{').trim_end_matches('}').to_lowercase();
    if g.len() == 36 && g.chars().filter(|c| *c == '-').count() == 4 {
        let found = pr.library.values().find(|e| s_of(e, "kind") == Some("dimension-type") && s_of(e, "guid") == Some(g.as_str()));
        if let Some(n) = found.and_then(|e| s_of(e, "name")).map(|s| s.to_string()) {
            if type_names(pr).contains(&n) {
                return Some(g);
            }
        }
    }
    if !type_names(pr).iter().any(|n| n == name) {
        return None;
    }
    Some(match pr.lib_guid("dimension-type", name) {
        Some(g) => g,
        None => pr.lib_add("dimension-type", name).1,
    })
}

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "dimension" => dimension(&mut s.project, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// A text parameter: None when absent or null.
fn text(p: &Value, key: &str) -> R<Option<String>> {
    crate::commands::params::opt_text(p, CMD, key)
}

/// The plan a `level` parameter names: a level, or a plan view (and its level).
pub fn plan_param(pr: &Project, cmd: &str, p: &Value) -> R<pick::Plan> {
    let level = crate::model::level_param(pr, cmd, p, "level")?;
    let mut view = None;
    if let Some(v) = get(p, "level") {
        if let Some(id) = crate::model::find(pr, v) {
            if pr.category(id) == Some("planview") {
                view = Some(id);
            }
        } else if let Value::Str(s) = v {
            let is_level = crate::model::levels(pr).iter().any(|l| name_of(pr, *l) == *s);
            if !is_level {
                view = pr.ids_of("planview").into_iter().find(|id| name_of(pr, *id) == *s);
            }
        }
    }
    Ok(pick::Plan { level, view })
}

fn dimension(pr: &mut Project, p: &Value) -> R<Value> {
    let plan = plan_param(pr, CMD, p)?;
    let at = crate::commands::params::req_point(p, CMD, "at")?;
    let kind = match text(p, "kind")? {
        None => Kind::Aligned,
        Some(k) => Kind::parse(&k).ok_or_else(|| format!("{}: `kind` is aligned, linear, angular, radial, diameter or arc_length, not `{}`", CMD, k))?,
    };
    let orient = match text(p, "orient")? {
        None => None,
        Some(o) => Some(Orient::parse(&o).ok_or_else(|| format!("{}: `orient` is horizontal or vertical, not `{}`", CMD, o))?),
    };
    let Some(raw) = get(p, "refs").and_then(|r| r.as_arr()) else {
        return Err(format!("{}: `refs` [ref, …] is required", CMD));
    };
    // each reference read, and a point found its line, in order
    let mut rs: Vec<refs::Ref> = Vec::new();
    {
        let cx = Ctx::new(pr);
        for v in raw {
            // a point picks a line along the first reference's (an aligned one's), or across it
            let along = rs.first().and_then(|f| {
                let line = refs::Ref { point: None, ..f.clone() };
                match measure::ref_geo(&cx, &line) {
                    Ok(measure::Geo::Line(a, b)) => Some(pick::Along { dir: geom::unit(geom::sub(b, a)), parallel: kind == Kind::Aligned }),
                    _ => None,
                }
            });
            let r = match refs::parse_ref_in(v).map_err(|e| format!("{}: {}", CMD, e))? {
                RefIn::Ref { id, face, point } => refs::Ref { target: refs::target_of(pr, &id), face, point },
                RefIn::Point(q) => match kind {
                    Kind::Radial | Kind::Diameter | Kind::ArcLength => pick::round_at(&cx, &plan, q, kind),
                    _ => pick::line_at(&cx, &plan, q, along),
                }
                .map_err(|e| format!("{}: {}", CMD, e))?,
                RefIn::Endpoint(q) => pick::end_at(&cx, &plan, q).map_err(|e| format!("{}: {}", CMD, e))?,
            };
            rs.push(r);
        }
    }
    let type_name = text(p, "type")?.map(|t| t.trim().to_string()).filter(|t| !t.is_empty());
    let mut texts: Vec<(&str, String)> = Vec::new();
    for k in labels::TEXT_KEYS {
        if let Some(t) = text(p, k)? {
            texts.push((k, t));
        }
    }
    let equality = crate::commands::params::opt_bool(p, CMD, "equality")?;
    let id = pr.alloc_id();
    // a linear one without `orient` runs vertical where `at` is east or west of all it measures
    let orient = match (kind, orient) {
        (Kind::Linear, None) => {
            let cx = Ctx::new(pr);
            let xs: Vec<f64> = rs.iter().flat_map(|r| pick::extent(&cx, r)).map(|p| p[0]).collect();
            let lo = xs.iter().cloned().fold(f64::INFINITY, f64::min);
            let hi = xs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
            if !xs.is_empty() && (at[0] > hi || at[0] < lo) {
                Some(Orient::Vertical)
            } else {
                Some(Orient::Horizontal)
            }
        }
        (_, o) => o,
    };
    let tname = match type_name.clone() {
        Some(t) => t,
        None => {
            // the kind's own, else the first the project has
            let names = type_names(pr);
            let d = default_type(kind).to_string();
            if names.contains(&d) {
                d
            } else {
                names.first().cloned().unwrap_or(d)
            }
        }
    };
    let Some(tguid) = type_guid(pr, &tname) else {
        return Err(format!("{} {}: there's no dimension type `{}` (there are: {})", CMD, id, tname, type_names(pr).join(", ")));
    };
    let mut e = Map::new();
    e.insert("guid", Value::s(&crate::rand::guid()));
    e.insert("category", Value::s("dimension"));
    e.insert("level", Value::s(&guid(pr, plan.level)));
    if let Some(v) = plan.view {
        e.insert("view", Value::s(&guid(pr, v)));
    }
    e.insert("kind", Value::s(kind.word()));
    if let Some(o) = orient {
        e.insert("orient", Value::s(o.word()));
    }
    e.insert("refs", Value::Arr(rs.iter().map(|r| r.to_value()).collect()));
    e.insert("at", Value::from(at));
    e.insert("type", Value::s(&tguid));
    for (k, t) in &texts {
        if !t.is_empty() {
            e.insert(k, Value::s(t));
        }
    }
    if equality == Some(true) {
        e.insert("equality", Value::Bool(true));
    }
    pr.elements.insert(id, Value::Obj(e));
    let values = check_one(&Ctx::new(pr), id)?;
    Ok(jobj! {"id" => id, "values" => Value::Arr(values.iter().map(|v| Value::f(measure::r2(*v))).collect())})
}

/// One dimension's rules (its type's first): its values, or "dimension N: …".
pub fn check_one(cx: &Ctx, id: u64) -> R<Vec<f64>> {
    let pr = cx.pr;
    let e = pr.el(id).ok_or_else(|| format!("no element {}", id))?;
    let tname = lib_ref_name(pr, e, "type");
    let names = type_names(pr);
    match &tname {
        Some(n) if names.contains(n) => {}
        _ => {
            let n = tname.clone().unwrap_or_else(|| s_of(e, "type").unwrap_or("").to_string());
            return Err(format!("dimension {}: there's no dimension type `{}` (there are: {})", id, n, names.join(", ")));
        }
    }
    let d = Dim::from_element(id, e);
    let v = measure::measure(cx, &d).map_err(|m| format!("dimension {}: {}", id, m))?;
    super::constraints::rules(id, e, &d)?;
    Ok(v)
}

/// The model rules of this part, checked after every command.
pub fn check(pr: &Project) -> R<()> {
    let ids = pr.ids_of("dimension");
    if ids.is_empty() {
        return Ok(());
    }
    let cx = Ctx::new(pr);
    for id in ids {
        check_one(&cx, id)?;
    }
    Ok(())
}

/// A dimension's values as `elements` and the replies give them (to the hundredth).
pub fn values(pr: &Project, id: u64) -> Vec<f64> {
    let cx = Ctx::new(pr);
    match pr.el(id) {
        Some(e) => measure::measure(&cx, &Dim::from_element(id, e)).unwrap_or_default(),
        None => Vec::new(),
    }
}

/// What a dimension's numbers read.
pub fn dimension_labels(pr: &Project, id: u64) -> Vec<String> {
    let Some(e) = pr.el(id) else { return Vec::new() };
    let d = Dim::from_element(id, e);
    let v = values(pr, id);
    labels::labels(pr, e, d.kind, &v)
}

/// What `elements` shows of this part's elements beyond their own fields.
pub fn element_view(pr: &Project, id: u64, x: &mut Value) {
    let Some(e) = pr.el(id) else { return };
    let d = Dim::from_element(id, e);
    let v = values(pr, id);
    let ls = labels::labels(pr, e, d.kind, &v);
    x.set("labels", Value::Arr(ls.into_iter().map(Value::from).collect()));
    x.set("values", Value::Arr(v.iter().map(|v| Value::f(measure::r2(*v))).collect()));
    if let Some(n) = lib_ref_name(pr, e, "type") {
        x.set("type", Value::s(&n));
    }
}

// ---------------------------------------------------------------- for the editing commands

/// What `delete` does to dimensions (they lose what's deleted): every reference to an element of
/// these GUIDs is taken out, and a dimension that lost one and has fewer than two left goes too
/// (its texts and locks stay as they were). Returns the dimensions deleted, by id.
pub fn drop_refs(pr: &mut Project, gone: &[String]) -> Vec<u64> {
    let mut deleted = Vec::new();
    for id in pr.ids_of("dimension") {
        let e = pr.el(id).unwrap();
        let rs = refs::refs_of(e);
        let kept: Vec<refs::Ref> = rs.iter().filter(|r| !gone.iter().any(|g| g == r.guid())).cloned().collect();
        if kept.len() == rs.len() {
            continue;
        }
        if kept.len() < 2 {
            pr.elements.remove(&id);
            deleted.push(id);
            continue;
        }
        let e = pr.el_mut(id).unwrap();
        e.set("refs", Value::Arr(kept.iter().map(|r| r.to_value()).collect()));
    }
    deleted
}

/// Rewrites the references to some elements: `f` maps a reference's face and end.
fn remap_refs(pr: &mut Project, guids: &[String], f: &dyn Fn(refs::Face, Option<refs::End>, bool) -> (refs::Face, Option<refs::End>)) {
    for id in pr.ids_of("dimension") {
        let e = pr.el(id).unwrap();
        let mut rs = refs::refs_of(e);
        let mut changed = false;
        for r in rs.iter_mut() {
            if guids.iter().any(|g| g == r.guid()) {
                let opening = r.id(pr).map_or(false, |x| matches!(cat_of(pr, x).as_str(), "door" | "window"));
                let (face, point) = f(r.face, r.point, opening);
                r.face = face;
                r.point = point;
                changed = true;
            }
        }
        if changed {
            let e = pr.el_mut(id).unwrap();
            e.set("refs", Value::Arr(rs.iter().map(|r| r.to_value()).collect()));
        }
    }
}

/// The GUIDs of walls and of the doors and windows they hold.
fn with_openings(pr: &Project, walls: &[u64]) -> Vec<String> {
    let mut gs: Vec<String> = walls.iter().map(|w| guid(pr, *w)).collect();
    for c in ["door", "window"] {
        for id in pr.ids_of(c) {
            let host = pr.el(id).and_then(|e| s_of(e, "host")).unwrap_or("").to_string();
            if gs.contains(&host) {
                gs.push(guid(pr, id));
            }
        }
    }
    gs
}

fn swap_end(p: Option<refs::End>) -> Option<refs::End> {
    p.map(|x| if x == refs::End::Start { refs::End::End } else { refs::End::Start })
}

/// What `flip` does to the dimensions of the walls it turns round (their start and end, left and
/// right swap, and their doors' and windows' jambs): each reference still measures what it did.
pub fn flip_refs(pr: &mut Project, walls: &[u64]) {
    use refs::Face::*;
    let gs = with_openings(pr, walls);
    remap_refs(pr, &gs, &|f, p, _| {
        let f = match f {
            Left => Right,
            Right => Left,
            Start => End,
            End => Start,
            Centre => Centre,
        };
        (f, swap_end(p))
    });
}

/// What `mirror` does to the dimensions of the walls it mirrors (their start and end swap, their
/// faces keeping their sides): a line along the wall keeps its side and swaps its ends; an end of
/// the wall becomes the other, the end of its line across the wall staying.
pub fn mirror_refs(pr: &mut Project, walls: &[u64]) {
    use refs::Face::*;
    let gs = with_openings(pr, walls);
    remap_refs(pr, &gs, &|f, p, opening| match f {
        Start => (End, p),
        End => (Start, p),
        // a door's or window's centre runs across its wall
        Centre if opening => (Centre, p),
        x => (x, swap_end(p)),
    });
}
