//! The check-and-drop pass: the model's rules checked on what came in, and the first element
//! that breaks one left out (with the rule's words) until none does.

use super::import::Ctx;
use super::notes::Kind;
use crate::json::Value;
use std::collections::BTreeMap;

fn num(v: &Value, k: &str) -> f64 {
    v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0)
}

fn level_elev(ctx: &Ctx, g: &str) -> Option<f64> {
    ctx.pr.elements.values().find(|e| e.get("guid").and_then(|x| x.as_str()) == Some(g)).and_then(|e| e.get("elevation")).and_then(|x| x.as_f64())
}

/// The first element (by id) that breaks a rule, and the rule's words.
fn first_failure(ctx: &Ctx) -> Option<(u64, String)> {
    let pr = &ctx.pr;
    let by_guid: BTreeMap<String, u64> = pr
        .elements
        .iter()
        .filter_map(|(id, e)| e.get("guid").and_then(|g| g.as_str()).map(|g| (g.to_string(), *id)))
        .collect();
    for (id, e) in &pr.elements {
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        match cat {
            "wall" => {
                let lv = e.get("level").and_then(|l| l.as_str()).and_then(|g| level_elev(ctx, g)).unwrap_or(0.0);
                let base = lv + num(e, "base_offset");
                let top = match e.get("top_level").and_then(|t| t.as_str()).and_then(|g| level_elev(ctx, g)) {
                    Some(t) => t + num(e, "top_offset"),
                    None => base + num(e, "height"),
                };
                if !(top - base > 1.0) {
                    // the heights to the millimetre (half to even), the difference rounded away from zero
                    return Some((
                        *id,
                        format!(
                            "its top ({:.0} mm) must be above its base ({:.0} mm); it comes out {} mm tall, so raise its top constraint, top offset or height by more than {} mm",
                            top,
                            base,
                            (top - base).round() as i64,
                            (base - top).round() as i64
                        ),
                    ));
                }
            }
            "door" | "window" => {
                let host = e.get("host").and_then(|h| h.as_str()).unwrap_or("");
                let hid = match by_guid.get(host) {
                    Some(h) => *h,
                    None => return Some((*id, "its wall was left out".into())),
                };
                let _ = hid;
                // two openings may not share a place along their wall
                let w = super::build::type_value(pr, cat, &type_name(ctx, e).unwrap_or_default()).map(|t| num(t, "width")).unwrap_or(0.0);
                let (a0, a1) = (num(e, "offset") - w / 2.0, num(e, "offset") + w / 2.0);
                for (id2, e2) in pr.elements.range(id + 1..) {
                    let c2 = e2.get("category").and_then(|c| c.as_str()).unwrap_or("");
                    if !(c2 == "door" || c2 == "window") || e2.get("host").and_then(|h| h.as_str()) != Some(host) {
                        continue;
                    }
                    let w2 = super::build::type_value(pr, c2, &type_name(ctx, e2).unwrap_or_default()).map(|t| num(t, "width")).unwrap_or(0.0);
                    let (b0, b1) = (num(e2, "offset") - w2 / 2.0, num(e2, "offset") + w2 / 2.0);
                    if a0.max(b0) < a1.min(b1) - 1e-6 {
                        return Some((*id, format!("{} {} and {} {} overlap in wall {}", cat, id, c2, id2, host)));
                    }
                }
            }
            "roof" => {
                if let Some(r) = roof_rule(e) {
                    return Some((*id, r));
                }
            }
            "pipe" | "duct" | "cabletray" => {
                let a = e.get("start").and_then(point).unwrap_or([0.0, 0.0]);
                let b = e.get("end").and_then(point).unwrap_or([0.0, 0.0]);
                let z0 = num(e, "offset");
                let z1 = e.get("end_offset").and_then(|x| x.as_f64()).unwrap_or(z0);
                let len = ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2) + (z1 - z0).powi(2)).sqrt();
                if !(len > 1.0) {
                    return Some((*id, format!("too short ({} mm)", len)));
                }
            }
            _ => {}
        }
    }
    None
}

fn point(v: &Value) -> Option<[f64; 2]> {
    let a = v.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?])
}

/// The rules a roof the import makes can break: an extrusion's line, profile and sweep, and a
/// footprint's boundary.
fn roof_rule(e: &Value) -> Option<String> {
    if let Some(x) = e.get("extrusion") {
        let line: Vec<[f64; 2]> = x.get("line").and_then(|l| l.as_arr()).map(|a| a.iter().filter_map(point).collect()).unwrap_or_default();
        if line.len() == 2 {
            let len = ((line[1][0] - line[0][0]).powi(2) + (line[1][1] - line[0][1]).powi(2)).sqrt();
            if !(len > 1.0) {
                return Some(format!("too short ({} mm)", len));
            }
        }
        let prof: Vec<[f64; 2]> = x.get("profile").and_then(|l| l.as_arr()).map(|a| a.iter().filter_map(point).collect()).unwrap_or_default();
        if prof.len() < 2 || prof.len() > 10000 {
            return Some("an extrusion's profile needs 2 to 10000 points".into());
        }
        if prof.windows(2).any(|w| !(w[1][0] - w[0][0] > 1.0)) {
            return Some("its profile runs along its line one way, each point past the one before".into());
        }
        if !(num(x, "to") - num(x, "from") > 1.0) {
            return Some("it's swept across its line from `from` to `to`, further to the left".into());
        }
        return None;
    }
    let b: Vec<[f64; 2]> = e.get("boundary").and_then(|l| l.as_arr()).map(|a| a.iter().filter_map(point).collect()).unwrap_or_default();
    if b.len() < 3 || b.len() > 10000 {
        return Some("a boundary needs 3 to 10000 points".into());
    }
    if !(super::plan::area(&b).abs() > 1.0) {
        return Some("its boundary encloses no area".into());
    }
    None
}

fn type_name(ctx: &Ctx, e: &Value) -> Option<String> {
    let g = e.get("type")?.as_str()?;
    if let Some(n) = ctx.pr.lib_name(g) {
        return Some(n);
    }
    ctx.lib_guids.iter().find(|(_, v)| v.as_str() == g).map(|((_, n), _)| n.clone())
}

pub fn run(ctx: &mut Ctx) {
    loop {
        let (id, reason) = match first_failure(ctx) {
            Some(x) => x,
            None => break,
        };
        let e = ctx.pr.elements.remove(&id).unwrap();
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("").to_string();
        let rid = ctx.made.iter().find(|(_, (pid, _))| *pid == id).map(|((r, _), _)| *r);
        if let Some(rid) = rid {
            ctx.notes.leave(&Kind::simple(&cat), &reason, rid);
        }
    }
}
