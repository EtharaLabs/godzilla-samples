//! The `sketch` command (a sketch solved without making anything) and `edit_boundary` (a floor's,
//! ceiling's, roof's or shaft's outline and holes redrawn as one sketch).

use super::util::*;
use crate::commands::params::{self, R};
use crate::geom::sketch;
use crate::json::Value;
use crate::session::Session;

pub fn cmd_sketch(_s: &mut Session, p: &Value) -> R<Value> {
    let c = "sketch";
    let v = match params::get(p, "lines") {
        None => return Err("sketch: `lines` [[[x,y],[x,y]],…] is required".into()),
        Some(v) => v,
    };
    let mut lines = sketch::parse(v).map_err(|e| sketch::parse_message(c, "lines", &e))?;
    let regions = sketch::solve(&mut lines).map_err(|p| format!("sketch: {}", sketch::unsolved(&p)))?;
    let mut total = 0.0;
    let mut out = Vec::new();
    for r in &regions {
        let a = r.area();
        total += a;
        out.push(jobj! {
            "area_m2" => m2(a),
            "holes" => rings_v(&r.holes),
            "outline" => ring_v(&r.outline),
        });
    }
    Ok(jobj! {"area_m2" => m2(total), "regions" => Value::Arr(out)})
}

// ---------------------------------------------------------------- edit_boundary

use crate::geom::{self, P2};
use crate::project::Project;

/// The rings an outlined element has: its boundary and its holes (a floor's or a ceiling's
/// openings, a roof's courtyards; a shaft has none).
fn element_rings(e: &Value) -> (Vec<P2>, Vec<Vec<P2>>) {
    let b = pts(e, "boundary").unwrap_or_default();
    let holes = match cat(e) {
        "roof" => rings(e, "courtyards"),
        "floor" | "ceiling" => rings(e, "openings"),
        _ => Vec::new(),
    };
    (b, holes)
}

/// The element's kept sketch, read back into lines.
fn kept_lines(e: &Value) -> Option<Vec<sketch::Line>> {
    let v = e.get("sketch")?;
    let a = v.as_arr()?;
    if a.is_empty() {
        return None;
    }
    // the stored form, its part ids taken as given
    let ids: Vec<u64> = a.iter().filter_map(|l| l.get("id").and_then(|x| x.as_u64())).collect();
    let stripped: Vec<Value> = a
        .iter()
        .map(|l| {
            let mut l = l.clone();
            l.remove("guid");
            l
        })
        .collect();
    sketch::parse_with(&Value::Arr(stripped), &ids).ok()
}

/// Whether the kept sketch still draws the element's outline and holes.
fn sketch_draws(e: &Value) -> bool {
    let Some(mut lines) = kept_lines(e) else { return false };
    let (b, holes) = element_rings(e);
    if cat(e) == "region" {
        return true;
    }
    match sketch::solve_region(&mut lines) {
        Ok(r) => r.outline == b && r.holes == holes,
        Err(_) => false,
    }
}

/// The slope of a roof's edge (0: the roof's own).
fn edge_slope(e: &Value, k: usize) -> f64 {
    e.get("slopes").and_then(|s| s.as_arr()).and_then(|a| a.get(k)).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

/// The edges of a roof's rings in order (the boundary's, then each courtyard's).
fn roof_edges(e: &Value) -> Vec<(P2, P2)> {
    let (b, holes) = element_rings(e);
    let mut out = Vec::new();
    for r in std::iter::once(&b).chain(holes.iter()) {
        let n = r.len();
        for i in 0..n {
            out.push((r[i], r[(i + 1) % n]));
        }
    }
    out
}

/// The lines to edit: the kept sketch while it still draws the outline, else the edges.
fn current_lines(e: &Value) -> Value {
    // a roof's lines say their slopes when it has slopes of its own
    let is_roof = cat(e) == "roof" && e.get("slopes").and_then(|x| x.as_arr()).map(|a| !a.is_empty()).unwrap_or(false);
    if sketch_draws(e) {
        let mut out = Vec::new();
        let lines = e.get("sketch").and_then(|v| v.as_arr()).cloned().unwrap_or_default();
        if is_roof {
            // each line with the slope its edges share
            let mut kl = kept_lines(e).unwrap_or_default();
            let edges_lines = sketch::solve_region(&mut kl).map(|r| r.lines).unwrap_or_default();
            let flat: Vec<usize> = edges_lines.into_iter().flatten().collect();
            for (i, l) in lines.iter().enumerate() {
                let mut l = l.clone();
                let k = flat.iter().position(|x| *x == i);
                let sl = k.map(|k| edge_slope(e, k)).unwrap_or(0.0);
                l.set("slope", Value::f(sl));
                out.push(l);
            }
        } else {
            out = lines;
        }
        return Value::Arr(out);
    }
    let (b, holes) = element_rings(e);
    let mut out = Vec::new();
    let mut k = 0;
    for r in std::iter::once(&b).chain(holes.iter()) {
        let n = r.len();
        for i in 0..n {
            let mut l = jobj! {"start" => pv(r[i]), "end" => pv(r[(i + 1) % n])};
            if is_roof {
                l.set("slope", Value::f(edge_slope(e, k)));
            }
            out.push(l);
            k += 1;
        }
    }
    Value::Arr(out)
}

/// Whether segment (c, d) lies along segment (a, b).
fn along(a: P2, b: P2, c: P2, d: P2) -> bool {
    let u = geom::sub(b, a);
    let l = geom::len(u);
    if l <= 0.0 {
        return false;
    }
    let off = |q: P2| (geom::cross(u, geom::sub(q, a)) / l).abs();
    if off(c) > 1e-6 || off(d) > 1e-6 {
        return false;
    }
    let t = |q: P2| geom::dot(geom::sub(q, a), u) / (l * l);
    let (tc, td) = (t(c), t(d));
    tc >= -1e-9 && tc <= 1.0 + 1e-9 && td >= -1e-9 && td <= 1.0 + 1e-9
}

pub fn cmd_edit_boundary(s: &mut Session, p: &Value) -> R<Value> {
    let c = "edit_boundary";
    let idv = match opt_ref(p, c, "id")? {
        Some(v) => v,
        None => return Err("edit_boundary: `id`, the floor, ceiling, roof or shaft to edit, is required".into()),
    };
    let pr = &s.project;
    let Some(id) = by_ref(pr, &idv) else {
        return Err(format!("edit_boundary: no element {}", ref_word(pr, &idv)));
    };
    let e = pr.el(id).unwrap().clone();
    let ec = cat(&e).to_string();
    if !matches!(ec.as_str(), "floor" | "ceiling" | "roof" | "shaft" | "region") {
        return Err(format!(
            "edit_boundary: {} isn't a floor, a ceiling, a roof's footprint, a shaft or a filled region",
            id
        ));
    }
    if ec == "roof" && e.get("extrusion").map(|x| !x.is_null()).unwrap_or(false) {
        return Err(format!("edit_boundary: {} is an extrusion roof: change its profile, `modify` its `extrusion`", id));
    }
    let Some(sv) = params::get(p, "sketch") else {
        return Ok(jobj! {"id" => id, "sketch" => current_lines(&e)});
    };
    // the part ids the element's lines have now
    let kept: Vec<(u64, String)> = e
        .get("sketch")
        .and_then(|v| v.as_arr())
        .map(|a| {
            a.iter()
                .filter_map(|l| Some((l.get("id")?.as_u64()?, l.get("guid")?.as_str()?.to_string())))
                .collect()
        })
        .unwrap_or_default();
    let ids: Vec<u64> = kept.iter().map(|k| k.0).collect();
    let mut lines = sketch::parse_with(sv, &ids).map_err(|er| sketch::parse_message(c, "sketch", &er))?;
    let mut ne = e.clone();
    let area;
    if ec == "region" {
        let regions = sketch::solve(&mut lines).map_err(|pr| {
            if pr.is_empty() {
                "edit_boundary: the sketch doesn't close into loops: there are no lines: draw the outline".to_string()
            } else {
                format!("edit_boundary: the sketch doesn't close into loops: {}", sketch::describe(&pr, "line"))
            }
        })?;
        area = regions.iter().map(|r| r.area()).sum::<f64>();
    } else {
        let r = sketch::solve_region(&mut lines).map_err(|er| format!("{}: {}", c, er))?;
        area = r.area();
        match ec.as_str() {
            "floor" | "ceiling" => {
                ne.set("boundary", ring_v(&r.outline));
                let order = if ec == "floor" { super::slabs::FLOOR_ORDER } else { super::slabs::CEILING_ORDER };
                if r.holes.is_empty() {
                    ne.remove("openings");
                } else {
                    put(&mut ne, order, "openings", rings_v(&r.holes));
                }
            }
            "shaft" => {
                if !r.holes.is_empty() {
                    return Err("edit_boundary: a shaft is one outline with no holes in it: sketch each hole as a shaft of its own".into());
                }
                ne.set("boundary", ring_v(&r.outline));
            }
            "roof" => {
                let old_edges = roof_edges(&e);
                let old_gables: Vec<usize> = e
                    .get("gables")
                    .and_then(|g| g.as_arr())
                    .map(|a| a.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect())
                    .unwrap_or_default();
                ne.set("boundary", ring_v(&r.outline));
                if r.holes.is_empty() {
                    ne.remove("courtyards");
                } else {
                    put(&mut ne, super::roofs::ORDER, "courtyards", rings_v(&r.holes));
                }
                let new_edges = roof_edges(&ne);
                let flat: Vec<usize> = r.lines.iter().flatten().copied().collect();
                // gables stay on the edges that stay
                let mut gables = Vec::new();
                for (k, (a, b)) in new_edges.iter().enumerate() {
                    let same = old_gables.iter().any(|g| {
                        old_edges.get(*g).map(|(oa, ob)| (oa == a && ob == b) || (oa == b && ob == a)).unwrap_or(false)
                    });
                    if same {
                        gables.push(k);
                    }
                }
                if !gables.is_empty() {
                    put(&mut ne, super::roofs::ORDER, "gables", Value::Arr(gables.iter().map(|g| Value::u(*g as u64)).collect()));
                } else {
                    ne.remove("gables");
                }
                // slopes: a line's own, else the old edge's it lies along
                let had = e.get("slopes").and_then(|x| x.as_arr()).map(|a| !a.is_empty()).unwrap_or(false);
                let any_line = lines.iter().any(|l| l.fields.get("slope").is_some());
                if had || any_line {
                    let mut sl = Vec::new();
                    for (k, (a, b)) in new_edges.iter().enumerate() {
                        let li = flat.get(k).copied();
                        let own = li.and_then(|i| lines[i].fields.get("slope")).and_then(|x| x.as_f64());
                        let v = match own {
                            Some(x) => x,
                            None => old_edges
                                .iter()
                                .enumerate()
                                .find(|(_, (oa, ob))| along(*oa, *ob, *a, *b))
                                .map(|(j, _)| edge_slope(&e, j))
                                .unwrap_or(0.0),
                        };
                        sl.push(Value::f(v));
                    }
                    put(&mut ne, super::roofs::ORDER, "slopes", Value::Arr(sl));
                }
            }
            _ => {}
        }
    }
    let v = sketch::to_value(&mut s.project, &lines, &kept);
    let v = if ec == "roof" { super::roofs::strip_slopes(v) } else { v };
    let order: &[&str] = match ec.as_str() {
        "floor" => super::slabs::FLOOR_ORDER,
        "ceiling" => super::slabs::CEILING_ORDER,
        "roof" => super::roofs::ORDER,
        "shaft" => super::slabs::SHAFT_ORDER,
        _ => &["view", "type", "line_style", "sketch"],
    };
    put(&mut ne, order, "sketch", v);
    s.project.elements.insert(id, ne);
    let _: Option<&Project> = None;
    Ok(jobj! {"area_m2" => m2(area), "id" => id})
}
