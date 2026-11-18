//! Editing detail lines: `join_polyline`, `explode`, `vertex`, `convert_spline`, `offset`,
//! `trim_extend`.

use super::common::*;
use super::curves::{self, Carrier, Curve, VertexError, P2};
use super::lines::{self, Props};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// Runs the commands of this part.
pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let pr = &mut s.project;
    let p = &lines::with_names(pr, p);
    match cid {
        "join_polyline" => join_polyline(pr, p),
        "explode" => explode(pr, p),
        "vertex" => vertex(pr, p),
        "convert_spline" => convert_spline(pr, p),
        "offset" => offset(pr, p),
        "trim_extend" => trim_extend(pr, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// The model rules of this part, checked after every command (the lines' own are `lines::check`).
pub fn check(pr: &Project) -> R<()> {
    let _ = pr;
    Ok(())
}

// ---------------------------------------------------------------- parameters

/// An element id as these commands take one: a number, or a string of an id or a GUID.
fn elem_ref(pr: &Project, v: &Value) -> Option<Option<u64>> {
    match v {
        Value::Num(_) => {
            let id = id_of(v)?;
            Some(if pr.elements.contains_key(&id) { Some(id) } else { None })
        }
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                return Some(if pr.elements.contains_key(&id) { Some(id) } else { None });
            }
            let g = crate::model::normalize_guid(t)?;
            Some(pr.find_guid(&g))
        }
        _ => None,
    }
}

/// The detail line `id` names: "`id`, a detail line, is required" when it is missing or names
/// nothing (`missing` says what for one that names nothing).
fn line_param(pr: &Project, cmd: &str, p: &Value, key: &str, missing: &str) -> R<u64> {
    let req = || format!("{}: `{}`, a detail line, is required", cmd, key);
    let v = get(p, key).ok_or_else(req)?;
    match elem_ref(pr, v) {
        None => Err(format!("{}: `{}` must be an element id or GUID, got {}", cmd, key, v.to_compact())),
        Some(None) => Err(if missing.is_empty() { req() } else { format!("{}: {}", cmd, missing) }),
        Some(Some(id)) => {
            if cat_of(pr, id) != "line" {
                return Err(format!("{}: {} is not a detail line", cmd, id));
            }
            Ok(id)
        }
    }
}

/// A list of element ids (each existing), in order, without repeats.
fn ids_param(pr: &Project, cmd: &str, p: &Value) -> R<Vec<u64>> {
    let one;
    let a = match get(p, "ids") {
        None if cmd == "join_polyline" && get(p, "id").is_some() => {
            one = vec![get(p, "id").unwrap().clone()];
            &one
        }
        v => v.and_then(|v| v.as_arr()).ok_or_else(|| format!("{}: `ids` [id, …] is required", cmd))?,
    };
    let mut out: Vec<u64> = Vec::new();
    for v in a {
        match elem_ref(pr, v) {
            None => return Err(format!("{}: {} is not an element id or GUID", cmd, v.to_compact())),
            Some(None) => {
                let shown = match id_of(v) {
                    Some(id) => id.to_string(),
                    None => v.as_str().unwrap_or("").trim().to_string(),
                };
                return Err(format!("{}: no element {}", cmd, shown));
            }
            Some(Some(id)) => {
                if !out.contains(&id) {
                    out.push(id);
                }
            }
        }
    }
    Ok(out)
}

fn point_param(p: &Value, cmd: &str, key: &str) -> R<P2> {
    crate::commands::params::req_point(p, cmd, key)
}

fn curve_of(pr: &Project, id: u64) -> R<Curve> {
    lines::curve_of(pr, id).ok_or_else(|| format!("detail line {} holds no curve", id))
}

// ---------------------------------------------------------------- join_polyline

fn join_polyline(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "join_polyline";
    let ids = ids_param(pr, CMD, p)?;
    if ids.len() < 2 {
        return Err(format!("{}: give two detail lines or more to join", CMD));
    }
    for id in &ids {
        if cat_of(pr, *id) != "line" {
            return Err(format!("{}: {} is not a detail line", CMD, id));
        }
    }
    let mut cs = Vec::new();
    for id in &ids {
        let c = curve_of(pr, *id)?;
        let ok = matches!(&c, Curve::Polyline { closed: false, .. });
        if !ok {
            return Err(format!("{}: detail line {} is a {}; only open lines, arcs and polylines join", CMD, id, c.shape()));
        }
        cs.push(c);
    }
    let first = ids[0];
    let view = pr.el(first).and_then(|e| s_of(e, "view")).unwrap_or("").to_string();
    for id in &ids[1..] {
        let v = pr.el(*id).and_then(|e| s_of(e, "view")).unwrap_or("").to_string();
        if v != view {
            return Err(format!("{}: detail line {} is in another view than {}; join lines of one view", CMD, id, first));
        }
    }
    let joined = curves::join(&cs, 1.0)
        .ok_or_else(|| format!("{}: the lines don't make one chain, each end meeting the next within 1 mm", CMD))?;
    lines::set_curve(pr, first, &joined);
    let gone: Vec<String> = ids[1..].iter().map(|id| guid(pr, *id)).collect();
    for id in &ids[1..] {
        pr.elements.remove(id);
    }
    let notes = drop_refs(pr, &gone, "a line that is joined in");
    let mut out = jobj! {"id" => first};
    if !notes.is_empty() {
        out.set("notes", Value::Arr(notes.into_iter().map(Value::Str).collect()));
    }
    Ok(out)
}

/// Dimensions lose their references to elements gone (by GUID): one left with fewer than two is
/// deleted. What each says, by dimension.
pub fn drop_refs(pr: &mut Project, gone: &[String], what: &str) -> Vec<String> {
    let mut notes = Vec::new();
    let dims: Vec<u64> = pr.ids_of("dimension");
    for d in dims {
        let Some(e) = pr.el(d) else { continue };
        let Some(refs) = e.get("refs").and_then(|r| r.as_arr()) else { continue };
        let keep: Vec<Value> = refs
            .iter()
            .filter(|r| !r.get("id").and_then(|i| i.as_str()).map(|g| gone.iter().any(|x| x == g)).unwrap_or(false))
            .cloned()
            .collect();
        if keep.len() == refs.len() {
            continue;
        }
        if keep.len() < 2 {
            pr.elements.remove(&d);
            notes.push(format!("dimension {} measured {}, was left with fewer than two references, and is deleted", d, what));
        } else {
            if let Some(e) = pr.el_mut(d) {
                e.set("refs", Value::Arr(keep));
            }
            notes.push(format!("dimension {} measured {}: it lost that reference", d, what));
        }
    }
    notes
}

// ---------------------------------------------------------------- explode

fn explode(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "explode";
    let id = line_param(pr, CMD, p, "id", "there's no such element")?;
    let c = curve_of(pr, id)?;
    let segs = c.segments();
    if segs.len() < 2 {
        return Err(format!("{}: detail line {} is a {}, already one piece", CMD, id, c.shape()));
    }
    let props = Props::of(pr.el(id).unwrap());
    let mut ids = vec![id];
    for (i, s) in segs.iter().enumerate() {
        let piece = Curve::arc(s.a, s.b, s.arc);
        if i == 0 {
            lines::set_curve(pr, id, &piece);
        } else {
            ids.push(lines::add_line(pr, &props, &piece));
        }
    }
    Ok(jobj! {"ids" => Value::Arr(ids.into_iter().map(Value::u).collect())})
}

// ---------------------------------------------------------------- vertex

fn vertex(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "vertex";
    let id = line_param(pr, CMD, p, "id", "")?;
    let at = point_param(p, CMD, "at")?;
    let delete = crate::commands::params::opt_bool(p, CMD, "delete")?.unwrap_or(false);
    let c = curve_of(pr, id)?;
    let res = if delete { c.without_vertex(at) } else { c.with_vertex(at) };
    let nc = res.map_err(|e| match e {
        VertexError::NotBetweenEnds => {
            format!("{}: detail line {} is a {}: only polylines and splines take a vertex, between their ends", CMD, id, c.shape())
        }
        VertexError::TooFar(d) => format!("{}: {} isn't on detail line {}: it is {} mm from it", CMD, curves::disp_point(at), id, disp(d)),
        VertexError::NoVertexNear(d) => {
            format!("{}: {} isn't on a vertex of detail line {}: it is {} mm from it", CMD, curves::disp_point(at), id, disp(d))
        }
        VertexError::NoneToSpare => format!("{}: detail line {} is a {}: it has no vertex to spare", CMD, id, c.shape()),
    })?;
    if nc != c {
        lines::set_curve(pr, id, &nc);
    }
    super::mark_step();
    Ok(jobj! {"id" => id})
}

// ---------------------------------------------------------------- convert_spline

fn convert_spline(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "convert_spline";
    let id = line_param(pr, CMD, p, "id", "")?;
    let c = curve_of(pr, id)?;
    let nc = match &c {
        Curve::Fitted { fit, start_tangent, end_tangent } => {
            let (control, knots) = curves::fit_to_control(fit, *start_tangent, *end_tangent);
            Curve::Spline { control: control.iter().map(|q| curves::r3p(*q)).collect(), knots: Some(knots) }
        }
        Curve::Spline { control, knots } => {
            let b = curves::Bspline::new(control, knots.as_deref());
            let at = |u: f64| b.at(u);
            let (st, et) = curves::end_tangents(&at, b.u0(), b.u1());
            curves::refit(&at, b.u0(), b.u1(), Some(st), Some(et), &c.breaks())
        }
        _ => return Err(format!("{}: detail line {} is a {}, not a spline", CMD, id, c.shape())),
    };
    lines::set_curve(pr, id, &nc);
    Ok(jobj! {"id" => id, "shape" => nc.shape()})
}

// ---------------------------------------------------------------- offset

fn offset(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "offset";
    let id = line_param(pr, CMD, p, "id", "")?;
    let d = match get(p, "distance") {
        None => return Err(format!("{}: `distance`, mm, is required", CMD)),
        Some(v) => crate::commands::params::mm_of(v)
            .ok_or_else(|| format!("{}: `distance` must be a number in mm, got {}", CMD, v.to_compact()))?,
    };
    if !(d > 0.0) {
        return Err(format!("{}: `distance` is more than 0 mm, not {}", CMD, disp(d)));
    }
    let toward = point_param(p, CMD, "toward")?;
    let copy = crate::commands::params::opt_bool(p, CMD, "copy")?.unwrap_or(true);
    let c = curve_of(pr, id)?;
    let side = c.side_of(toward);
    let sd = if side >= 0.0 { d } else { -d };
    let nc = c
        .offset(sd)
        .ok_or_else(|| format!("{}: a {} can't be offset by {} mm (it would turn inside out, or fold over itself)", CMD, c.shape(), disp(d)))?;
    if copy {
        let props = Props::of(pr.el(id).unwrap());
        let nid = lines::add_line(pr, &props, &nc);
        Ok(jobj! {"id" => nid})
    } else {
        lines::set_curve(pr, id, &nc);
        Ok(jobj! {"id" => id})
    }
}

// ---------------------------------------------------------------- trim_extend

/// What a line can be trimmed or extended to: its carrier, and which views may trim to it.
struct Boundary {
    carrier: Carrier,
    /// The view a detail line boundary is drawn in.
    view: Option<String>,
    /// The level a wall stands on.
    level: Option<u64>,
    /// A grid: any plan.
    grid: bool,
}

fn boundary_of(pr: &Project, id: u64) -> Option<Option<Boundary>> {
    let e = pr.el(id)?;
    match cat(e) {
        "line" => {
            let c = curves::parse(e).ok()?;
            let view = s_of(e, "view").map(|s| s.to_string());
            Some(c.carrier().map(|carrier| Boundary { carrier, view, level: None, grid: false }))
        }
        "wall" => {
            let a = pt_of(e, "start")?;
            let b = pt_of(e, "end")?;
            let arc = f_of(e, "arc").unwrap_or(0.0);
            let carrier = match curves::arc_geo(a, b, arc) {
                Some(g) => Carrier::Circle(g.centre, g.radius),
                None => Carrier::Line(a, b),
            };
            Some(Some(Boundary { carrier, view: None, level: ref_id(pr, e, "level"), grid: false }))
        }
        "grid" => {
            let a = pt_of(e, "start")?;
            let b = pt_of(e, "end")?;
            Some(Some(Boundary { carrier: Carrier::Line(a, b), view: None, level: None, grid: true }))
        }
        _ => None,
    }
}

fn trim_extend(pr: &mut Project, p: &Value) -> R<Value> {
    const CMD: &str = "trim_extend";
    let breq = || format!("{}: `boundary`, a line to trim or extend to, is required", CMD);
    let bv = get(p, "boundary").ok_or_else(breq)?;
    let bid = match elem_ref(pr, bv) {
        None => return Err(format!("{}: `boundary` must be an element id or GUID, got {}", CMD, bv.to_compact())),
        Some(None) => return Err(breq()),
        Some(Some(id)) => id,
    };
    let boundary = boundary_of(pr, bid).ok_or_else(|| format!("{}: {} has no line to trim or extend to", CMD, bid))?;
    let ids = ids_param(pr, CMD, p)?;
    let keep_v = get(p, "keep").and_then(|v| v.as_arr()).ok_or_else(|| format!("{}: `keep` [[x, y], …] is required", CMD))?;
    let mut keep: Vec<P2> = Vec::new();
    for k in keep_v {
        match crate::commands::params::point_of(k) {
            Some(q) => keep.push(q),
            None => return Err(format!("{}: `keep`: {} is not a point [x, y] in mm", CMD, k.to_compact())),
        }
    }
    if keep.len() != ids.len() {
        return Err(format!("{}: `keep` gives a point on each line to keep: {} for {} lines", CMD, keep.len(), ids.len()));
    }
    let mut changes: Vec<(u64, Curve)> = Vec::new();
    for (k, id) in ids.iter().enumerate() {
        let id = *id;
        if cat_of(pr, id) != "line" {
            return Err(format!("{}: {} is not a detail line", CMD, id));
        }
        let e = pr.el(id).unwrap();
        let lview = s_of(e, "view").unwrap_or("").to_string();
        let same_view = match &boundary {
            None => true,
            Some(b) => {
                if let Some(v) = &b.view {
                    *v == lview
                } else {
                    let vid = pr.find_guid(&lview);
                    let plan = vid.map(|v| matches!(pr.category(v), Some("level") | Some("planview"))).unwrap_or(false);
                    if b.grid {
                        plan
                    } else {
                        plan && vid.and_then(|v| crate::model::level_of_view(pr, v)) == b.level
                    }
                }
            }
        };
        if !same_view {
            return Err(format!(
                "{}: detail line {} is in another view than {} is drawn in; trim it to a line of its own view",
                CMD, id, bid
            ));
        }
        let never = || format!("{}: detail line {} never meets {}", CMD, id, bid);
        let b = boundary.as_ref().ok_or_else(never)?;
        if id == bid {
            return Err(never());
        }
        let c = curve_of(pr, id)?;
        let nc = trim_to(&c, b.carrier, keep[k]).ok_or_else(never)?;
        let nc = match nc {
            Some(x) => x,
            None => return Err(format!("{}: detail line {} can't be cut there: nothing would be left", CMD, id)),
        };
        changes.push((id, nc));
    }
    for (id, nc) in changes {
        let old = lines::curve_of(pr, id);
        if old.as_ref() != Some(&nc) {
            lines::set_curve(pr, id, &nc);
        }
    }
    super::mark_step();
    Ok(jobj! {"ids" => Value::Arr(ids.into_iter().map(Value::u).collect())})
}

/// The crossing nearest the point kept (the first of two as near), and its parameter.
fn nearest_hit(hits: &[P2], keep: P2, param: &dyn Fn(P2) -> f64) -> Option<(f64, P2)> {
    let mut best: Option<(f64, P2)> = None;
    for h in hits {
        let d = (h[0] - keep[0]) * (h[0] - keep[0]) + (h[1] - keep[1]) * (h[1] - keep[1]);
        if best.map(|x| d.sqrt() < x.0).unwrap_or(true) {
            best = Some((d.sqrt(), *h));
        }
    }
    best.map(|(_, h)| (param(h), h))
}

/// A line or an arc trimmed or extended to where it meets a carrier, keeping the side `keep` is
/// on: None if it never meets it (or isn't a line or an arc), Some(None) if nothing would be left.
fn trim_to(c: &Curve, to: Carrier, keep: P2) -> Option<Option<Curve>> {
    let (a, b, arc) = match c {
        Curve::Polyline { points, arcs, closed: false } if points.len() == 2 => (points[0], points[1], arcs.first().copied().unwrap_or(0.0)),
        _ => return None,
    };
    let own = c.carrier()?;
    let hits = curves::meet(own, to);
    if hits.is_empty() {
        return None;
    }
    let res = match curves::arc_geo(a, b, arc) {
        None => {
            let d = curves::sub(b, a);
            let l2 = curves::dot(d, d);
            let param = |q: P2| curves::dot(curves::sub(q, a), d) / l2;
            let tk = param(keep);
            let (t, h) = nearest_hit(&hits, keep, &param)?;
            let q = curves::r3p(h);
            if tk >= t {
                Curve::line(q, b)
            } else {
                Curve::line(a, q)
            }
        }
        Some(g) => {
            let half = g.turn / 2.0;
            let param = |q: P2| -> f64 {
                let ang = (q[1] - g.centre[1]).atan2(q[0] - g.centre[0]);
                // the angle from the start the way it turns, within half a turn of its middle
                let s = if g.turn > 0.0 { 1.0 } else { -1.0 };
                let mut d = (ang - g.start) * s;
                let mid = half * s;
                while d - mid > std::f64::consts::PI {
                    d -= 2.0 * std::f64::consts::PI;
                }
                while d - mid <= -std::f64::consts::PI {
                    d += 2.0 * std::f64::consts::PI;
                }
                d * s
            };
            let tk = param(keep);
            let (t, h) = nearest_hit(&hits, keep, &param)?;
            let q = curves::r3p(h);
            let ge = (b[1] - g.centre[1]).atan2(b[0] - g.centre[0]);
            let s = if g.turn > 0.0 { 1.0 } else { -1.0 };
            if tk * s >= t * s {
                // the start moves to the crossing: what is left turns from there to the end
                let ah = (h[1] - g.centre[1]).atan2(h[0] - g.centre[0]);
                let mut e = ge - ah;
                if g.turn > 0.0 {
                    e = e.rem_euclid(2.0 * std::f64::consts::PI);
                } else {
                    e = -(-e).rem_euclid(2.0 * std::f64::consts::PI);
                }
                Curve::arc(q, b, e.to_degrees())
            } else {
                // the end moves to the crossing: the turn from the start to there
                Curve::arc(a, q, t.to_degrees())
            }
        }
    };
    if !(res.length() > curves::MIN_LENGTH) || res.check().is_err() {
        return Some(None);
    }
    Some(Some(res))
}

// ---------------------------------------------------------------- split (for EDIT's `split`)

/// `split` on a detail line: cut where it passes nearest `at` (within 100 mm, not within a
/// millimetre of an open line's ends, at a polyline's corner within a millimetre of one), the
/// first part keeping the id and the second a new line in the same view and style; a closed line
/// opens there instead. The reply, or the original's words for what's wrong.
pub fn split_line(pr: &mut Project, id: u64, at: P2) -> R<Value> {
    let c = curve_of(pr, id)?;
    let (_, cut) = c.split_at(at).map_err(|e| match e {
        VertexError::TooFar(d) => format!("split: {} isn't on detail line {}: it passes {} mm from it", curves::disp_point(at), id, disp(d)),
        _ => "split: split between the line's ends".to_string(),
    })?;
    match cut {
        curves::Cut::Two(a, b) => {
            let props = Props::of(pr.el(id).unwrap());
            lines::set_curve(pr, id, &a);
            let nid = lines::add_line(pr, &props, &b);
            Ok(jobj! {"ids" => Value::Arr(vec![Value::u(id), Value::u(nid)])})
        }
        curves::Cut::Opened(o) => {
            lines::set_curve(pr, id, &o);
            Ok(jobj! {"ids" => Value::Arr(vec![Value::u(id)]), "opened" => true})
        }
    }
}

#[cfg(test)]
mod probe {
    /// Splits a line of a project file as SPLIT_IN, SPLIT_ID and SPLIT_AT say; prints the reply and
    /// the lines after (run with `cargo test --release split_probe -- --ignored --nocapture`).
    #[test]
    #[ignore]
    fn split_probe() {
        let path = std::env::var("SPLIT_IN").unwrap();
        let id: u64 = std::env::var("SPLIT_ID").unwrap().parse().unwrap();
        let at = crate::json::parse(&std::env::var("SPLIT_AT").unwrap()).unwrap();
        let at = [at.as_arr().unwrap()[0].as_f64().unwrap(), at.as_arr().unwrap()[1].as_f64().unwrap()];
        let text = std::fs::read_to_string(&path).unwrap();
        let mut pr = crate::load::load(crate::json::parse(&text).unwrap()).unwrap();
        match super::split_line(&mut pr, id, at) {
            Ok(v) => println!("REPLY {}", v.to_compact()),
            Err(e) => println!("ERROR {}", e),
        }
        for (k, e) in &pr.elements {
            if e.get("category").and_then(|c| c.as_str()) == Some("line") {
                println!("EL {} {}", k, e.to_compact());
            }
        }
    }
}
