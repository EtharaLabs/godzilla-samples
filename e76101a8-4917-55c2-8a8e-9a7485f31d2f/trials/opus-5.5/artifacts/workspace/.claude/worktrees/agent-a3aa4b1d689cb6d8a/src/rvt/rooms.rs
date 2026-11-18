//! Rooms: number, name, level, and a point the imported walls enclose.

use super::build::mm;
use super::bytes::*;
use super::cats;
use super::data;
use super::import::Ctx;
use super::notes::Kind;
use super::plan;
use crate::json::Value;

const NUMBER: i64 = -1006901;
const NAME: i64 = -1006900;
pub const NOT_ENCLOSED: &str =
    "the walls imported do not enclose its box (curtain walls and room separation lines are not imported)";

/// The room's number and name, from its object in the newest partition that has one.
fn params(ctx: &Ctx, id: u64) -> (Option<String>, Option<String>) {
    let doc = ctx.doc;
    let wide = doc.wide();
    let mut key = vec![1u8, 0, 0, 0];
    if wide {
        key.extend_from_slice(&id.to_le_bytes());
    } else {
        key.extend_from_slice(&(id as u32).to_le_bytes());
    }
    for pi in doc.parts_newest_first() {
        let d = &doc.parts[pi].data;
        let mut last = None;
        let mut q = 0;
        while let Some(p) = find(d, &key, q, d.len()) {
            last = Some(p);
            q = p + 1;
        }
        let p = match last {
            Some(p) => p,
            None => continue,
        };
        let end = (p + 0x400).min(d.len());
        let entry = |pid: i64| -> Option<String> {
            let k: Vec<u8> = if wide { pid.to_le_bytes().to_vec() } else { (pid as i32).to_le_bytes().to_vec() };
            let m = find(d, &k, p, end)?;
            let (s, _) = data::counted(d, m + k.len(), 1000)?;
            Some(s)
        };
        return (entry(NUMBER), entry(NAME));
    }
    (None, None)
}

pub fn read(ctx: &mut Ctx) {
    let kind = Kind::simple("room");
    // the walls that came in, as lines in plan, by level
    // the walls that came in, as lines in plan, with the heights they span (mm)
    let elev = |g: &str| -> f64 {
        ctx.levels.iter().find(|l| l.guid.as_deref() == Some(g)).map(|l| l.elevation).unwrap_or(0.0)
    };
    let mut segs: Vec<((f64, f64), plan::P, plan::P)> = Vec::new();
    for e in ctx.pr.elements.values() {
        if e.get("category").and_then(|c| c.as_str()) != Some("wall") {
            continue;
        }
        let num = |k: &str| e.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0);
        let base = elev(e.get("level").and_then(|l| l.as_str()).unwrap_or("")) + num("base_offset");
        let lv = (base, base + num("height"));
        let s = e.get("start").and_then(crate::commands::params::point_of);
        let t = e.get("end").and_then(crate::commands::params::point_of);
        let (s, t) = match (s, t) {
            (Some(s), Some(t)) => (s, t),
            _ => continue,
        };
        match e.get("arc").and_then(|a| a.as_f64()) {
            Some(sweep) if sweep != 0.0 => {
                // the arc through both ends with this sweep (degrees, counter-clockwise when positive)
                let sw = sweep.to_radians();
                let chord = ((t[0] - s[0]).powi(2) + (t[1] - s[1]).powi(2)).sqrt();
                let r = chord / 2.0 / (sw.abs() / 2.0).sin();
                let mid = [(s[0] + t[0]) / 2.0, (s[1] + t[1]) / 2.0];
                let d = (r * r - (chord / 2.0).powi(2)).max(0.0).sqrt();
                let n = [-(t[1] - s[1]) / chord, (t[0] - s[0]) / chord];
                let sign = if (sw > 0.0) == (sw.abs() < std::f64::consts::PI) { 1.0 } else { -1.0 };
                let c = [mid[0] + sign * d * n[0], mid[1] + sign * d * n[1]];
                let a0 = (s[1] - c[1]).atan2(s[0] - c[0]);
                let pts = plan::arc_points(c, r, a0, sw);
                for w in pts.windows(2) {
                    segs.push((lv, w[0], w[1]));
                }
            }
            _ => segs.push((lv, s, t)),
        }
    }
    for r in ctx.instances(cats::OST_ROOMS) {
        let b = match r.bbox {
            Some(b) => b,
            None => continue,
        };
        let level = match ctx.base_level(&r.refs, b[2]) {
            Some(l) => l,
            None => {
                ctx.notes.leave(&kind, super::walls::NO_LEVEL, r.id);
                continue;
            }
        };
        // the walls the level's plan cuts, 1200 mm over it, whatever level they stand on
        let cut = ctx.levels[level].elevation + 1200.0;
        let lsegs: Vec<(plan::P, plan::P)> = segs.iter().filter(|s| s.0 .0 <= cut && cut < s.0 .1).map(|s| (s.1, s.2)).collect();
        let faces = plan::faces(&lsegs);
        let (x0, y0, x1, y1) = (mm(b[0]), mm(b[1]), mm(b[3]), mm(b[4]));
        let (w, h) = (x1 - x0, y1 - y0);
        // the box's centre first, then the centres of a 9 by 9 grid over it, nearest first
        let c = [(x0 + x1) / 2.0, (y0 + y1) / 2.0];
        let mut cands: Vec<(f64, plan::P)> = vec![(-1.0, c)];
        for iy in 0..9 {
            for ix in 0..9 {
                let p = [x0 + (ix as f64 + 0.5) * w / 9.0, y0 + (iy as f64 + 0.5) * h / 9.0];
                let d = (p[0] - c[0]) * (p[0] - c[0]) + (p[1] - c[1]) * (p[1] - c[1]);
                cands.push((d, p));
            }
        }
        cands.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        let tol = 1e-6;
        let mut point = None;
        for (_, p) in cands {
            if let Some(f) = faces.around(p) {
                let fx0 = f.iter().map(|q| q[0]).fold(f64::INFINITY, f64::min);
                let fy0 = f.iter().map(|q| q[1]).fold(f64::INFINITY, f64::min);
                let fx1 = f.iter().map(|q| q[0]).fold(f64::NEG_INFINITY, f64::max);
                let fy1 = f.iter().map(|q| q[1]).fold(f64::NEG_INFINITY, f64::max);
                if fx0 <= x0 + tol && fy0 <= y0 + tol && fx1 >= x1 - tol && fy1 >= y1 - tol {
                    point = Some(p);
                    break;
                }
            }
        }
        let point = match point {
            Some(p) => p,
            None => {
                ctx.notes.leave(&kind, NOT_ENCLOSED, r.id);
                continue;
            }
        };
        let (number, name) = params(ctx, r.id);
        let v = jobj! {
            "guid" => crate::rand::guid(),
            "category" => "room",
            "level" => ctx.level_guid(level),
            "point" => Value::Arr(vec![Value::f(point[0]), Value::f(point[1])]),
            "name" => name.unwrap_or_else(|| "Room".to_string()),
            "number" => number.unwrap_or_default(),
        };
        ctx.add(r.id, "room", v);
    }
}
