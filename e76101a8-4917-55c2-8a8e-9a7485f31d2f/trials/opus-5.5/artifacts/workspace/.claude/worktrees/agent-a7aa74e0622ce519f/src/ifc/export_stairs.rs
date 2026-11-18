//! Stairs and ramps (their flights and landings) and railings, on a host or along a path.
//!
//! A stair climbs from its start (the middle of its first riser) the way its angle says, in as
//! many risers as keep each at most its `riser`, its runs broken by landings after so many
//! risers (a ramp's at so many mm up), each landing as deep as the stair is wide and the next
//! run going on, turned left or right, or back beside the last. Flights are written as their
//! treads, each a block from the level up to its top; a ramp's as a wedge, solid down to the
//! level; landings as blocks the same way. A railing runs 50 mm in from a side of its host,
//! round each landing, its rail at its type's height over what it runs along and its
//! balusters its type's spacing apart along its plan length.

use super::geom::*;
use super::step::{gid, real, refs, st};
use super::Ex;
use crate::json::Value;

/// A run of a stair or a ramp: from the middle of its start, the way it climbs, the height it
/// starts at and how much it rises, and its length in plan.
#[derive(Clone, Copy, Debug)]
pub struct Run {
    pub start: V2,
    pub d: V2,
    pub base: f64,
    pub rise: f64,
    pub len: f64,
    pub risers: usize,
}

impl Run {
    pub fn end(&self) -> V2 {
        self.start + self.d * self.len
    }
}

/// A landing between two runs: its outline, its height, and how the next run turns from it.
#[derive(Clone, Debug)]
pub struct Landing {
    pub ring: Vec<V2>,
    pub z: f64,
    pub turn: f64,
}

pub struct Layout {
    pub runs: Vec<Run>,
    pub landings: Vec<Landing>,
    pub width: f64,
    pub riser: f64,
    pub tread: f64,
}

fn num(e: &Value, k: &str, d: f64) -> f64 {
    e.get(k).and_then(|v| v.as_f64()).unwrap_or(d)
}

fn turn_key(t: f64) -> i64 {
    t.round() as i64
}

/// Lays out runs between break heights (each run's base and top), turning at each landing.
fn lay_out(start: V2, angle: f64, width: f64, runs: &[(f64, f64, f64, usize)], turns: &[f64]) -> (Vec<Run>, Vec<Landing>) {
    let r = angle.to_radians();
    let mut d = v2(r.cos(), r.sin());
    let mut p = start;
    let mut out = Vec::new();
    let mut lands = Vec::new();
    let w = width;
    for (i, &(base, rise, len, risers)) in runs.iter().enumerate() {
        let run = Run { start: p, d, base, rise, len, risers };
        out.push(run);
        if i + 1 == runs.len() {
            break;
        }
        let t = turns.get(i).copied().unwrap_or(0.0);
        let end = run.end();
        let n = d.perp();
        let back = turn_key(t).abs() == 180;
        let c0 = if turn_key(t) == -180 { end - n * (w / 2.0) - n * w } else { end - n * (w / 2.0) };
        let lateral = if back { w * 2.0 } else { w };
        let ring = vec![c0, c0 + d * w, c0 + d * w + n * lateral, c0 + n * lateral];
        lands.push(Landing { ring, z: base + rise, turn: t });
        match turn_key(t) {
            90 => {
                p = end + d * (w / 2.0) + n * (w / 2.0);
                d = n;
            }
            -90 => {
                p = end + d * (w / 2.0) - n * (w / 2.0);
                d = -n;
            }
            180 => {
                p = end + n * w;
                d = -d;
            }
            -180 => {
                p = end - n * w;
                d = -d;
            }
            _ => {
                p = end + d * w;
            }
        }
    }
    (out, lands)
}

fn predefined(turns: &[f64], kind: &str) -> String {
    let t: Vec<i64> = turns.iter().map(|x| turn_key(*x)).collect();
    let name = match t.as_slice() {
        [] => "STRAIGHT_RUN",
        [0] => "TWO_STRAIGHT_RUN",
        [90] | [-90] => "QUARTER_TURN",
        [180] | [-180] => "HALF_TURN",
        [90, 90] | [-90, -90] => "TWO_QUARTER_TURN",
        _ => return "NOTDEFINED".to_string(),
    };
    format!("{}_{}", name, kind)
}

impl<'a> Ex<'a> {
    /// How high a stair or a ramp climbs: to its top level, or its height.
    fn climb(&self, e: &Value) -> f64 {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("");
        match e.get("top_level").and_then(|v| v.as_str()) {
            Some(tl) if self.storey_of(tl).is_some() => self.level_elev(tl) - self.level_elev(level),
            _ => num(e, "height", 3000.0),
        }
    }

    fn landings_of(e: &Value) -> Vec<(f64, f64)> {
        let mut out: Vec<(f64, f64)> = e
            .get("landings")
            .and_then(|l| l.as_arr())
            .map(|a| a.iter().map(|l| (num(l, "at", 0.0), num(l, "turn", 0.0))).collect())
            .unwrap_or_default();
        out.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        out
    }

    pub fn stair_layout(&self, e: &Value) -> Layout {
        let height = self.climb(e);
        let rmax = num(e, "riser", 180.0);
        let tread = num(e, "tread", 280.0);
        let width = num(e, "width", 1000.0);
        let n = ((height / rmax) - 1e-9).ceil().max(1.0) as usize;
        let riser = height / n as f64;
        let lands = Self::landings_of(e);
        let mut bounds = vec![0usize];
        for (at, _) in &lands {
            let a = at.round() as usize;
            if a > *bounds.last().unwrap() && a < n {
                bounds.push(a);
            }
        }
        bounds.push(n);
        let turns: Vec<f64> = lands.iter().map(|l| l.1).collect();
        let mut runs = Vec::new();
        for k in 0..bounds.len() - 1 {
            let risers = bounds[k + 1] - bounds[k];
            let base = bounds[k] as f64 * riser;
            runs.push((base, risers as f64 * riser, (risers.max(1) - 1) as f64 * tread, risers));
        }
        let start = super::walls::pt(e.get("start"));
        let (runs, landings) = lay_out(start, num(e, "angle", 0.0), width, &runs, &turns);
        Layout { runs, landings, width, riser, tread }
    }

    pub fn ramp_layout(&self, e: &Value) -> Layout {
        let height = self.climb(e);
        let slope = num(e, "slope", 100.0 / 12.0) / 100.0;
        let width = num(e, "width", 1200.0);
        let lands = Self::landings_of(e);
        let mut bounds = vec![0.0f64];
        for (at, _) in &lands {
            if *at > *bounds.last().unwrap() && *at < height {
                bounds.push(*at);
            }
        }
        bounds.push(height);
        let turns: Vec<f64> = lands.iter().map(|l| l.1).collect();
        let mut runs = Vec::new();
        for k in 0..bounds.len() - 1 {
            let rise = bounds[k + 1] - bounds[k];
            runs.push((bounds[k], rise, rise / slope, 0));
        }
        let start = super::walls::pt(e.get("start"));
        let (runs, landings) = lay_out(start, num(e, "angle", 0.0), width, &runs, &turns);
        Layout { runs, landings, width, riser: 0.0, tread: 0.0 }
    }

    pub fn write_stair(&mut self, id: u64, e: &Value) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let lay = self.stair_layout(e);
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        self.placements.insert(id, place);
        let turns: Vec<f64> = lay.landings.iter().map(|l| l.turn).collect();
        let product = self.add(format!(
            "IFCSTAIR('{}',$,'Stair',$,$,#{},$,'{}',.{}.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            place,
            id,
            predefined(&turns, "STAIR")
        ));
        self.products.insert(id, product);
        let mut parts = Vec::new();
        for run in &lay.runs {
            let fp = self.placement(place, v3(run.start.x, run.start.y, run.base), Some(run.d));
            let treads = run.risers.saturating_sub(1);
            let mut profs = Vec::new();
            for k in 0..treads {
                let c = self.st.point2(lay.tread * k as f64 + lay.tread / 2.0, 0.0);
                let ax = self.add(format!("IFCAXIS2PLACEMENT2D(#{},$)", c));
                profs.push(self.add(format!(
                    "IFCRECTANGLEPROFILEDEF(.AREA.,$,#{},{},{})",
                    ax,
                    real(lay.tread),
                    real(lay.width)
                )));
            }
            let mut solids = Vec::new();
            for (k, prof) in profs.iter().enumerate() {
                let pos = if run.base != 0.0 {
                    let p = self.st.point3(0.0, 0.0, -run.base);
                    self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p))
                } else {
                    self.origin
                };
                let depth = run.base + (k + 1) as f64 * lay.riser;
                solids.push(self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, pos, self.up, real(depth))));
            }
            let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',({}))", self.body, refs(&solids)));
            let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
            let g = self.fresh();
            parts.push(self.add(format!(
                "IFCSTAIRFLIGHT('{}',$,'Flight',$,$,#{},#{},$,{},{},{},{},.STRAIGHT.)",
                g,
                fp,
                shape,
                run.risers,
                treads,
                real(lay.riser),
                real(lay.tread)
            )));
        }
        for l in &lay.landings {
            parts.push(self.write_landing(place, l));
        }
        self.stair_parts.push((id, product, parts));
        self.finish(id, e, product, Some("Pset_StairCommon"), false);
        self.contain(&level, product);
    }

    /// A landing: a block from the level up to it, placed in its stair's or ramp's axes.
    fn write_landing(&mut self, rel: usize, l: &Landing) -> usize {
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        let poly = self.closed_polyline(&l.ring);
        let prof = self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", poly));
        let solid = self.add(format!("IFCEXTRUDEDAREASOLID(#{},#{},#{},{})", prof, self.origin, self.up, real(l.z)));
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let g = self.fresh();
        self.add(format!("IFCSLAB('{}',$,'Landing',$,$,#{},#{},$,.LANDING.)", g, place, shape))
    }

    pub fn write_ramp(&mut self, id: u64, e: &Value) {
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let lay = self.ramp_layout(e);
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        self.placements.insert(id, place);
        let turns: Vec<f64> = lay.landings.iter().map(|l| l.turn).collect();
        let product = self.add(format!(
            "IFCRAMP('{}',$,'Ramp',$,$,#{},$,'{}',.{}.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            place,
            id,
            predefined(&turns, "RAMP")
        ));
        self.products.insert(id, product);
        let mut parts = Vec::new();
        let w = lay.width;
        for run in &lay.runs {
            let n = run.d.perp();
            let end = run.end();
            let ring = [run.start - n * (w / 2.0), end - n * (w / 2.0), end + n * (w / 2.0), run.start + n * (w / 2.0)];
            let zf = |p: V2| -> f64 {
                let a = (p - run.start).dot(run.d);
                match std::env::var("RZ").as_deref() {
                    Ok("A") => run.base + a * (run.rise / run.len),
                    Ok("B") => run.base + a / run.len * run.rise,
                    Ok("C") => run.base + run.rise * (a / run.len),
                    Ok("D") => run.base + a * run.rise / run.len,
                    _ => f64::NAN,
                }
            };
            let top = if std::env::var("RZ").is_ok() {
                [zf(ring[0]), zf(ring[1]), zf(ring[2]), zf(ring[3])]
            } else {
                [run.base, run.base + run.rise, run.base + run.rise, run.base]
            };
            let b: Vec<usize> = ring.iter().map(|p| self.st.point3(p.x, p.y, 0.0)).collect();
            let t: Vec<usize> = ring.iter().zip(top.iter()).map(|(p, z)| self.st.point3(p.x, p.y, *z)).collect();
            let brep = self.shell_between(&b, &t);
            let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Brep',(#{}))", self.body, brep));
            let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
            let fp = self.placement(place, v3(0.0, 0.0, 0.0), None);
            let g = self.fresh();
            parts.push(self.add(format!("IFCRAMPFLIGHT('{}',$,'Flight',$,$,#{},#{},$,.STRAIGHT.)", g, fp, shape)));
        }
        for l in &lay.landings {
            parts.push(self.write_landing(place, l));
        }
        self.stair_parts.push((id, product, parts));
        self.finish(id, e, product, Some("Pset_RampCommon"), false);
        self.contain(&level, product);
    }

    /// The line a railing on a stair or a ramp runs along, 50 mm in from its side: each run's
    /// start and end, and the corners round each landing; with the height of what it runs
    /// along at each point.
    fn hosted_path(&self, host: &Value, side: &str) -> Vec<V3> {
        let cat = host.get("category").and_then(|c| c.as_str()).unwrap_or("");
        let lay = if cat == "ramp" { self.ramp_layout(host) } else { self.stair_layout(host) };
        let s = if side == "right" { -1.0 } else { 1.0 };
        let off = lay.width / 2.0 - 50.0;
        let mut pts: Vec<V3> = Vec::new();
        let cross = |a: V2, d: V2, b: V2, e: V2| line_cross(a, d, b, e);
        // each run's way from its two ends, as the railing sees it
        let way = |r: &Run| (r.end() - r.start).normalize();
        for (i, run) in lay.runs.iter().enumerate() {
            let u = way(run);
            let n = u.perp();
            let a = run.start + n * (s * off);
            let b = run.end() + n * (s * off);
            pts.push(v3(a.x, a.y, run.base));
            pts.push(v3(b.x, b.y, run.base + run.rise));
            let Some(l) = lay.landings.get(i) else { continue };
            let next = lay.runs[i + 1];
            let nu = way(&next);
            let nn = nu.perp();
            let na = next.start + nn * (s * off);
            let z = l.z;
            let t = turn_key(l.turn);
            let inner = (t > 0 && s > 0.0) || (t < 0 && s < 0.0);
            let end = run.end();
            let w = lay.width;
            let mut corners: Vec<V2> = Vec::new();
            match t.abs() {
                90 if inner => {
                    if let Some(c) = cross(b, u, na, nu) {
                        corners.push(c);
                    }
                }
                90 => {
                    // the far edge, 50 in
                    let fa = end + u * (w - 50.0);
                    if let Some(c) = cross(b, u, fa, n) {
                        corners.push(c);
                    }
                }
                180 => {
                    let fa = if inner { end + u * 50.0 } else { end + u * (w - 50.0) };
                    if let Some(c) = cross(b, u, fa, n) {
                        corners.push(c);
                    }
                    if let Some(c) = cross(fa, n, na, nu) {
                        corners.push(c);
                    }
                }
                _ => {}
            }
            for c in corners {
                pts.push(v3(c.x, c.y, z));
            }
        }
        pts
    }

    pub fn write_railing(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let tname = super::walls::lib_name(pr, &tg);
        let td = super::walls::type_data(pr, "railing", &tg);
        let height = td.and_then(|t| t.get("height")).and_then(|v| v.as_f64()).unwrap_or(1000.0);
        let spacing = td.and_then(|t| t.get("spacing")).and_then(|v| v.as_f64()).unwrap_or(0.0);
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let host = e.get("host").and_then(|h| h.as_str()).filter(|h| !h.is_empty()).and_then(|h| pr.find_guid(h));
        let (path, rel) = match host {
            Some(hid) => {
                let he = pr.el(hid).unwrap();
                let side = e.get("side").and_then(|v| v.as_str()).unwrap_or("left");
                let rel = self.placements.get(&hid).copied().unwrap_or_else(|| self.storey_place(&level));
                (self.hosted_path(he, side), rel)
            }
            None => {
                let base = num(e, "base_offset", 0.0);
                let pts: Vec<V3> = e
                    .get("path")
                    .and_then(|p| p.as_arr())
                    .map(|a| a.iter().map(|q| super::walls::pt(Some(q))).map(|p| v3(p.x, p.y, base)).collect())
                    .unwrap_or_default();
                (pts, self.storey_place(&level))
            }
        };
        let mut breps = Vec::new();
        // the balusters spacing apart along it, the distance to the next carried round each corner
        let mut next_bal = 0.0f64;
        for k in 0..path.len().saturating_sub(1) {
            let (a, b) = (path[k], path[k + 1]);
            let (pa, pb) = (a.xy(), b.xy());
            let seg = pb - pa;
            let len = seg.length();
            if len < 1e-9 {
                continue;
            }
            let d = seg.normalize();
            let n = d.perp();
            let ring = [pa - n * 25.0, pb - n * 25.0, pb + n * 25.0, pa + n * 25.0];
            let zt = [a.z + height, b.z + height, b.z + height, a.z + height];
            let bi: Vec<usize> = ring.iter().zip(zt.iter()).map(|(p, z)| self.st.point3(p.x, p.y, *z - 50.0)).collect();
            let ti: Vec<usize> = ring.iter().zip(zt.iter()).map(|(p, z)| self.st.point3(p.x, p.y, *z)).collect();
            breps.push(self.shell_between(&bi, &ti));
            if spacing > 0.0 {
                while next_bal <= len {
                    let t = next_bal / len;
                    let p = pa + seg * t;
                    let z = a.z + (b.z - a.z) * t;
                    let ring = [p - d * 10.0 - n * 10.0, p + d * 10.0 - n * 10.0, p + d * 10.0 + n * 10.0, p - d * 10.0 + n * 10.0];
                    let bi: Vec<usize> = ring.iter().map(|q| self.st.point3(q.x, q.y, z)).collect();
                    let ti: Vec<usize> = ring.iter().map(|q| self.st.point3(q.x, q.y, z + height - 50.0)).collect();
                    breps.push(self.shell_between(&bi, &ti));
                    next_bal += spacing;
                }
            }
            next_bal -= len;
        }
        let axis_pts: Vec<usize> = path.iter().map(|p| self.st.point3(p.x, p.y, p.z + height)).collect();
        let poly = self.add(format!("IFCPOLYLINE(({}))", refs(&axis_pts)));
        let axis = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Axis','Curve3D',(#{}))", self.axis, poly));
        let body = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Brep',({}))", self.body, refs(&breps)));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{},#{}))", body, axis));
        let place = self.placement(rel, v3(0.0, 0.0, 0.0), None);
        self.placements.insert(id, place);
        let name = st(&tname);
        let product = self.add(format!(
            "IFCRAILING('{}',$,{},$,{},#{},#{},'{}',.GUARDRAIL.)",
            gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or("")),
            name,
            name,
            place,
            shape,
            id
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, Some("Pset_RailingCommon"), false);
        match host {
            Some(hid) => {
                if let Some(s) = self.stair_parts.iter_mut().find(|s| s.0 == hid) {
                    s.2.push(product);
                }
            }
            None => self.contain(&level, product),
        }
    }

    /// After the railings on them: each stair's and ramp's parts aggregated to it.
    pub fn write_stair_aggregates(&mut self) {
        let parts = std::mem::take(&mut self.stair_parts);
        for (_, product, ps) in parts {
            if ps.is_empty() {
                continue;
            }
            let g = self.fresh();
            self.add(format!("IFCRELAGGREGATES('{}',$,$,$,#{},({}))", g, product, refs(&ps)));
        }
    }
}
