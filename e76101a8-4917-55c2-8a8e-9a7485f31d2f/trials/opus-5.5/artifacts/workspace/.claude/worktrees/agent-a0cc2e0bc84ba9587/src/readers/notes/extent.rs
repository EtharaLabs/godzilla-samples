//! Where elements lie in plan: each one's extent as its level's plan draws it, a plan's extent of
//! everything it shows, and the size a view takes on a sheet at a scale.

use super::geo::{self, P};
use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, Ctx};

/// A box in plan: its south-west and north-east corners.
pub type BoxP = [P; 2];

#[derive(Default, Clone, Copy)]
pub struct Bounds {
    pub b: Option<BoxP>,
}

impl Bounds {
    pub fn add(&mut self, p: P) {
        if !(p[0].is_finite() && p[1].is_finite()) {
            return;
        }
        self.b = Some(match self.b {
            None => [p, p],
            Some([lo, hi]) => [[lo[0].min(p[0]), lo[1].min(p[1])], [hi[0].max(p[0]), hi[1].max(p[1])]],
        });
    }
    pub fn add_box(&mut self, o: Option<BoxP>) {
        if let Some([lo, hi]) = o {
            self.add(lo);
            self.add(hi);
        }
    }
}

fn rect_around(a: P, b: P, half: f64) -> Vec<P> {
    let d = geo::unit(geo::sub(b, a));
    let n = geo::mul(geo::left(d), half);
    vec![geo::add(a, n), geo::add(b, n), geo::sub(b, n), geo::sub(a, n)]
}

fn rotated_rect(c: P, w: f64, d: f64, angle_deg: f64) -> Vec<P> {
    let (s, co) = angle_deg.to_radians().sin_cos();
    [[-w / 2.0, -d / 2.0], [w / 2.0, -d / 2.0], [w / 2.0, d / 2.0], [-w / 2.0, d / 2.0]]
        .iter()
        .map(|p| [c[0] + p[0] * co - p[1] * s, c[1] + p[0] * s + p[1] * co])
        .collect()
}

/// The points of an element's outline in plan (enough of them for its extent).
pub fn plan_points(cx: &Ctx, id: u64, e: &Value) -> Vec<P> {
    let pr = cx.pr;
    let cat = common::category(e);
    match cat {
        "wall" => match geo::wall(cx, id) {
            Some(w) => {
                let mut v = w.corners.to_vec();
                if let Some(a) = w.arc {
                    for off in [w.left, w.right] {
                        let o = a.offset(off);
                        for i in 0..=64 {
                            v.push(o.at(i as f64 / 64.0));
                        }
                    }
                }
                v
            }
            None => Vec::new(),
        },
        "floor" | "ceiling" | "roof" | "shaft" | "mass" => common::points(e.get("boundary").unwrap_or(&Value::Null)),
        "column" | "structuralcolumn" | "footing" => {
            let Some(at) = geo::pt(e.get("at")) else { return Vec::new() };
            let (w, d, round) = common::element_type(pr, e)
                .map(|(_, t)| {
                    (
                        common::num(t, "width").unwrap_or(0.0),
                        common::num(t, "depth").unwrap_or(0.0),
                        t.get("round").and_then(|r| r.as_bool()).unwrap_or(false),
                    )
                })
                .unwrap_or((0.0, 0.0, false));
            if round {
                return vec![[at[0] - w / 2.0, at[1] - w / 2.0], [at[0] + w / 2.0, at[1] + w / 2.0]];
            }
            rotated_rect(at, w, d, common::num(e, "angle").unwrap_or(0.0))
        }
        "beam" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor" | "groundconductor" | "cable"
        | "stripfooting" => {
            let (Some(a), Some(b)) = (geo::pt(e.get("start")), geo::pt(e.get("end"))) else { return Vec::new() };
            let w = common::element_type(pr, e).and_then(|(_, t)| common::num(t, "width")).unwrap_or(0.0);
            if geo::dist(a, b) == 0.0 {
                return vec![[a[0] - w / 2.0, a[1] - w / 2.0], [a[0] + w / 2.0, a[1] + w / 2.0]];
            }
            rect_around(a, b, w / 2.0)
        }
        "roomseparator" | "section" | "elevation" | "grid" => {
            let mut v = Vec::new();
            for k in ["start", "end"] {
                if let Some(p) = geo::pt(e.get(k)) {
                    v.push(p);
                }
            }
            v
        }
        "railing" => common::points(e.get("path").unwrap_or(&Value::Null)),
        "room" | "text" | "spot" => geo::pt(e.get("point")).or_else(|| geo::pt(e.get("at"))).into_iter().collect(),
        "tag" => {
            let mut x = e.clone();
            super::annot::tag_view(cx, &mut x);
            geo::pt(x.get("at")).into_iter().collect()
        }
        "line" => line_points(e),
        "region" => {
            let mut v = Vec::new();
            for s in e.get("sketch").and_then(|s| s.as_arr()).cloned().unwrap_or_default() {
                v.extend(line_points(&s));
            }
            v
        }
        "stair" | "ramp" => {
            let w = common::num(e, "width").unwrap_or(0.0);
            let runs = e.get("runs").and_then(|r| r.as_arr()).cloned().unwrap_or_default();
            let mut v = Vec::new();
            for r in runs {
                let pts = common::points(&r);
                if pts.len() == 2 {
                    v.extend(rect_around(pts[0], pts[1], w / 2.0));
                }
            }
            if v.is_empty() {
                if let (Some(a), Some(b)) = (geo::pt(e.get("start")), geo::pt(e.get("end"))) {
                    v.extend(rect_around(a, b, w / 2.0));
                }
            }
            v
        }
        _ => Vec::new(),
    }
}

/// A detail line's (or a sketch line's) points, enough for its extent.
fn line_points(e: &Value) -> Vec<P> {
    let mut v = Vec::new();
    match super::details::shape(e) {
        "circle" => {
            if let (Some(c), Some(r)) = (geo::pt(e.get("centre")), common::num(e, "radius")) {
                v.push([c[0] - r, c[1] - r]);
                v.push([c[0] + r, c[1] + r]);
            }
        }
        "arc" => {
            if let (Some(a), Some(b), Some(t)) = (geo::pt(e.get("start")), geo::pt(e.get("end")), common::num(e, "arc")) {
                if let Some(arc) = geo::Arc::from_chord(a, b, t) {
                    for i in 0..=256 {
                        v.push(arc.at(i as f64 / 256.0));
                    }
                }
            }
        }
        "polyline" => v.extend(common::points(e.get("points").unwrap_or(&Value::Null))),
        "ellipse" | "partial ellipse" => {
            if let Some(c) = geo::pt(e.get("centre")) {
                let rr = e.get("radii").and_then(|r| r.as_arr()).cloned().unwrap_or_default();
                let rx = rr.first().and_then(|x| x.as_f64()).unwrap_or(0.0).abs();
                let ry = rr.get(1).and_then(|x| x.as_f64()).unwrap_or(0.0).abs();
                let span = geo::pt(e.get("span")).map(|s| (s[0], s[1]));
                v.extend(super::details::ellipse_points(c, rx, ry, common::num(e, "angle").unwrap_or(0.0), span));
            }
        }
        "spline" => {
            let ctrl = common::points(e.get("control").unwrap_or(&Value::Null));
            let knots = e.get("knots").and_then(|k| k.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect());
            v.extend(super::details::spline_points(&ctrl, knots));
        }
        "fitted spline" => {
            let pts = common::points(e.get("fit").unwrap_or(&Value::Null));
            v.extend(super::details::fit_points(&pts, None, None));
        }
        _ => {
            for k in ["start", "end"] {
                if let Some(p) = geo::pt(e.get(k)) {
                    v.push(p);
                }
            }
        }
    }
    v
}

/// Whether a plan of level `lv` (GUID) and view `view` (GUID: the level's own, or a plan view of it)
/// shows an element.
fn in_plan(pr: &Project, e: &Value, lv: &str, view: &str) -> bool {
    match common::category(e) {
        "grid" | "section" | "elevation" => true,
        "text" | "spot" | "line" | "region" | "detailgroup" | "repeatingdetail" => common::text(e, "view") == Some(view),
        "tag" => {
            let l = common::target(pr, e, "host").map(|(_, h)| super::annot::host_level(pr, h));
            matches!(l, Some(Value::Str(s)) if s == lv)
        }
        "roof" => true,
        "level" | "sheet" | "viewport" | "schedule" | "view3d" | "planview" | "door" | "window" | "rebar" | "link" | "pointcloud" => false,
        _ => common::text(e, "level") == Some(lv),
    }
}

/// Everything a plan shows: its extent.
pub fn plan_extent(cx: &Ctx, view_id: u64) -> Option<BoxP> {
    let pr = cx.pr;
    let lid = crate::model::level_of_view(pr, view_id)?;
    let lv = pr.guid_of(lid)?;
    let vg = pr.guid_of(view_id)?;
    let mut b = Bounds::default();
    for (id, e) in &pr.elements {
        if !in_plan(pr, e, &lv, &vg) {
            continue;
        }
        if common::category(e) == "dimension" {
            continue;
        }
        for p in plan_points(cx, *id, e) {
            b.add(p);
        }
    }
    b.b
}

/// Rounds a paper length up to the 0.2 mm a sheet is laid out on.
fn up5(x: f64) -> f64 {
    let k = (x * 5.0 - 1e-6).ceil();
    k / 5.0
}

/// The size a view takes on a sheet at 1 : `scale`, paper mm.
pub fn viewport_size(cx: &Ctx, vid: u64, v: &Value, scale: f64, _vp: &Value) -> Option<P> {
    let scale = if scale > 0.0 { scale } else { 100.0 };
    match common::category(v) {
        "level" | "planview" => {
            let [lo, hi] = plan_extent(cx, vid).unwrap_or([[0.0, 0.0], [10000.0, 10000.0]]);
            let w = super::common_round3(hi[0] - lo[0]);
            let h = super::common_round3(hi[1] - lo[1]);
            Some([up5(w / scale + 24.0), up5(h / scale + 24.0)])
        }
        _ => None,
    }
}

/// The plan that shows the elements of a selection, and where they lie in it.
pub fn selection_plan(cx: &Ctx, ids: &[u64]) -> Option<(u64, BoxP)> {
    let pr = cx.pr;
    let mut plan = None;
    let mut b = Bounds::default();
    for id in ids {
        let e = pr.el(*id)?;
        let lv = match common::category(e) {
            "door" | "window" | "tag" => {
                let h = if common::category(e) == "tag" { common::target(pr, e, "host").map(|(_, h)| h) } else { Some(e) };
                h.map(|h| super::annot::host_level(pr, h)).and_then(|v| v.as_str().map(|s| s.to_string()))
            }
            _ => common::text(e, "level").map(|s| s.to_string()).or_else(|| {
                super::annot::view_level(pr, common::text(e, "view")).as_str().map(|s| s.to_string())
            }),
        };
        let Some(lv) = lv else { continue };
        let Some(lid) = pr.find_guid(&lv) else { continue };
        if plan.is_none() {
            plan = Some(lid);
        }
        for p in plan_points(cx, *id, e) {
            b.add(p);
        }
    }
    Some((plan?, b.b?))
}
