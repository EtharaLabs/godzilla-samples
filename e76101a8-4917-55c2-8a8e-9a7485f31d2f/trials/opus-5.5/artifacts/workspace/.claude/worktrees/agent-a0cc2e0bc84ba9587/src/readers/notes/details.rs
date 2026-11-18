//! Detail lines, filled regions, detail groups and repeating details as `elements` shows them: a
//! line's shape, length and style, a region's area and type, a group's type and members, how many
//! times a detail repeats.

use super::annot::view_level;
use super::geo::{self, Arc, P};
use crate::json::Value;
use crate::readers::common::{self, r2, Ctx};
use std::f64::consts::PI;

/// What kind of curve a detail line is.
pub fn shape(e: &Value) -> &'static str {
    if e.get("control").is_some() {
        return "spline";
    }
    if e.get("fit").is_some() {
        return "fitted spline";
    }
    if e.get("radii").is_some() {
        return if e.get("span").map(|s| !s.is_null()).unwrap_or(false) { "partial ellipse" } else { "ellipse" };
    }
    if e.get("radius").is_some() {
        return "circle";
    }
    if e.get("points").is_some() {
        return "polyline";
    }
    if common::num(e, "arc").map(|a| a != 0.0).unwrap_or(false) {
        return "arc";
    }
    "line"
}

/// A straight segment's or an arc's length, from `a` to `b` turning `turn` degrees.
fn seg_len(a: P, b: P, turn: f64) -> f64 {
    match Arc::from_chord(a, b, turn) {
        Some(arc) if turn != 0.0 => arc.length(),
        _ => geo::dist(a, b),
    }
}

/// An ellipse's points (or part of one), as the original draws it.
pub fn ellipse_points(c: P, rx: f64, ry: f64, angle: f64, span: Option<(f64, f64)>) -> Vec<P> {
    let (from, to) = match span {
        Some((a, b)) => (a.to_radians(), b.to_radians()),
        None => (0.0, 2.0 * PI),
    };
    let n = ((to - from).abs() / (2.0 * PI) * 200.0).ceil().max(1.0) as usize;
    let (s, co) = angle.to_radians().sin_cos();
    (0..=n)
        .map(|i| {
            let t = from + (to - from) * i as f64 / n as f64;
            let (x, y) = (rx * t.cos(), ry * t.sin());
            [c[0] + x * co - y * s, c[1] + x * s + y * co]
        })
        .collect()
}

fn poly_len(pts: &[P]) -> f64 {
    pts.windows(2).map(|w| geo::dist(w[0], w[1])).sum()
}

/// A clamped B-spline's points (degree from its knots, else 3), as the original draws it.
pub fn spline_points(ctrl: &[P], knots: Option<Vec<f64>>) -> Vec<P> {
    let n = ctrl.len();
    if n < 2 {
        return ctrl.to_vec();
    }
    let (deg, ks) = match knots {
        Some(k) if k.len() > n => (k.len() - n - 1, k),
        _ => {
            let d = 3.min(n - 1);
            let mut k = vec![0.0; d + 1];
            let inner = n - d - 1;
            for i in 1..=inner {
                k.push(i as f64 / (inner + 1) as f64);
            }
            k.extend(std::iter::repeat(1.0).take(d + 1));
            (d, k)
        }
    };
    let (t0, t1) = (ks[deg], ks[n]);
    let steps = 64 * (n - deg).max(1);
    (0..=steps)
        .map(|i| {
            let t = t0 + (t1 - t0) * i as f64 / steps as f64;
            de_boor(ctrl, &ks, deg, t)
        })
        .collect()
}

fn de_boor(ctrl: &[P], ks: &[f64], deg: usize, t: f64) -> P {
    let n = ctrl.len();
    let mut k = deg;
    while k + 1 < n && t >= ks[k + 1] {
        k += 1;
    }
    let mut d: Vec<P> = (0..=deg).map(|j| ctrl[j + k - deg]).collect();
    for r in 1..=deg {
        for j in (r..=deg).rev() {
            let i = j + k - deg;
            let den = ks[i + deg - r + 1] - ks[i];
            let a = if den == 0.0 { 0.0 } else { (t - ks[i]) / den };
            d[j] = geo::lerp(d[j - 1], d[j], a);
        }
    }
    d[deg]
}

/// A spline through points (a natural cubic through them, by chord length).
pub fn fit_points(pts: &[P], _t0: Option<P>, _t1: Option<P>) -> Vec<P> {
    let n = pts.len();
    if n < 3 {
        return pts.to_vec();
    }
    // chord-length parameters
    let mut u = vec![0.0];
    for i in 1..n {
        u.push(u[i - 1] + geo::dist(pts[i - 1], pts[i]));
    }
    let mut out = Vec::new();
    for dim in 0..2 {
        let y: Vec<f64> = pts.iter().map(|p| p[dim]).collect();
        let m = natural_second(&u, &y);
        out.push((u.clone(), y, m));
    }
    let steps = 64;
    let mut res = Vec::new();
    for i in 0..n - 1 {
        for s in 0..steps {
            let t = u[i] + (u[i + 1] - u[i]) * s as f64 / steps as f64;
            res.push([cubic_at(&out[0], i, t), cubic_at(&out[1], i, t)]);
        }
    }
    res.push(pts[n - 1]);
    res
}

fn natural_second(x: &[f64], y: &[f64]) -> Vec<f64> {
    let n = x.len();
    let mut m = vec![0.0; n];
    if n < 3 {
        return m;
    }
    let mut a = vec![0.0; n];
    let mut b = vec![0.0; n];
    let mut c = vec![0.0; n];
    let mut d = vec![0.0; n];
    b[0] = 1.0;
    b[n - 1] = 1.0;
    for i in 1..n - 1 {
        let h0 = x[i] - x[i - 1];
        let h1 = x[i + 1] - x[i];
        a[i] = h0;
        b[i] = 2.0 * (h0 + h1);
        c[i] = h1;
        d[i] = 6.0 * ((y[i + 1] - y[i]) / h1 - (y[i] - y[i - 1]) / h0);
    }
    for i in 1..n {
        let w = a[i] / b[i - 1];
        b[i] -= w * c[i - 1];
        d[i] -= w * d[i - 1];
    }
    m[n - 1] = d[n - 1] / b[n - 1];
    for i in (0..n - 1).rev() {
        m[i] = (d[i] - c[i] * m[i + 1]) / b[i];
    }
    m
}

fn cubic_at(s: &(Vec<f64>, Vec<f64>, Vec<f64>), i: usize, t: f64) -> f64 {
    let (x, y, m) = s;
    let h = x[i + 1] - x[i];
    let a = (x[i + 1] - t) / h;
    let b = (t - x[i]) / h;
    a * y[i] + b * y[i + 1] + ((a * a * a - a) * m[i] + (b * b * b - b) * m[i + 1]) * h * h / 6.0
}

/// How long a detail line is along its curve.
pub fn line_length(e: &Value) -> Option<f64> {
    match shape(e) {
        "line" | "arc" => {
            let a = geo::pt(e.get("start"))?;
            let b = geo::pt(e.get("end"))?;
            Some(seg_len(a, b, common::num(e, "arc").unwrap_or(0.0)))
        }
        "polyline" => {
            let pts = common::points(e.get("points")?);
            let turns: Vec<f64> = e
                .get("arcs")
                .and_then(|a| a.as_arr())
                .map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0)).collect())
                .unwrap_or_default();
            let closed = e.get("closed").and_then(|c| c.as_bool()).unwrap_or(false);
            let n = if closed { pts.len() } else { pts.len().saturating_sub(1) };
            let mut l = 0.0;
            for i in 0..n {
                l += seg_len(pts[i], pts[(i + 1) % pts.len()], turns.get(i).cloned().unwrap_or(0.0));
            }
            Some(l)
        }
        "circle" => Some(2.0 * PI * common::num(e, "radius")?.abs()),
        "ellipse" | "partial ellipse" => {
            let c = geo::pt(e.get("centre"))?;
            let rr = common::points(&Value::Arr(vec![e.get("radii")?.clone()]));
            let (rx, ry) = (rr.first()?[0].abs(), rr.first()?[1].abs());
            let span = geo::pt(e.get("span")).map(|s| (s[0], s[1]));
            Some(poly_len(&ellipse_points(c, rx, ry, common::num(e, "angle").unwrap_or(0.0), span)))
        }
        "spline" => {
            let ctrl = common::points(e.get("control")?);
            let knots = e.get("knots").and_then(|k| k.as_arr()).map(|a| a.iter().filter_map(|x| x.as_f64()).collect());
            Some(poly_len(&spline_points(&ctrl, knots)))
        }
        "fitted spline" => {
            let pts = common::points(e.get("fit")?);
            Some(poly_len(&fit_points(&pts, geo::pt(e.get("start_tangent")), geo::pt(e.get("end_tangent")))))
        }
        _ => None,
    }
}

pub fn line_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    let sh = shape(x);
    if let Some(l) = line_length(x) {
        x.set("length", Value::f(r2(l)));
    }
    x.set("shape", Value::s(sh));
    if let Some(g) = common::text(x, "style").map(|s| s.to_string()) {
        if let Some(n) = common::lib_name_of(pr, "line-style", &g) {
            x.set("style", Value::Str(n));
        }
    }
    let lv = view_level(pr, common::text(x, "view"));
    x.set("level", lv);
}

/// The signed area of a loop of a region's sketch lines.
fn loops_area(sketch: &[Value]) -> f64 {
    // the lines, each from its start to its end (an arc by its `arc` turn), chained into loops
    let mut segs: Vec<(P, P, f64)> = Vec::new();
    for s in sketch {
        if let (Some(a), Some(b)) = (geo::pt(s.get("start")), geo::pt(s.get("end"))) {
            segs.push((a, b, common::num(s, "arc").unwrap_or(0.0)));
        } else if let (Some(c), Some(r)) = (geo::pt(s.get("centre")), common::num(s, "radius")) {
            // a whole circle: a loop of its own
            let _ = c;
            segs.push(([0.0, 0.0], [0.0, 0.0], f64::NAN));
            let _ = r;
        }
    }
    let mut used = vec![false; segs.len()];
    let mut areas = Vec::new();
    for i in 0..segs.len() {
        if used[i] {
            continue;
        }
        if segs[i].2.is_nan() {
            used[i] = true;
            if let Some(s) = sketch.get(i) {
                let r = common::num(s, "radius").unwrap_or(0.0);
                areas.push(PI * r * r);
            }
            continue;
        }
        used[i] = true;
        let mut lp: Vec<(P, P, f64)> = vec![segs[i]];
        let start = segs[i].0;
        let mut cur = segs[i].1;
        let mut guard = 0;
        while geo::dist(cur, start) > 1e-6 && guard < segs.len() + 1 {
            guard += 1;
            let mut found = false;
            for j in 0..segs.len() {
                if used[j] || segs[j].2.is_nan() {
                    continue;
                }
                if geo::dist(segs[j].0, cur) <= 1e-6 {
                    used[j] = true;
                    lp.push(segs[j]);
                    cur = segs[j].1;
                    found = true;
                    break;
                }
                if geo::dist(segs[j].1, cur) <= 1e-6 {
                    used[j] = true;
                    lp.push((segs[j].1, segs[j].0, -segs[j].2));
                    cur = segs[j].0;
                    found = true;
                    break;
                }
            }
            if !found {
                break;
            }
        }
        let mut a = 0.0;
        for (p, q, t) in &lp {
            a += geo::cross(*p, *q) / 2.0;
            if *t != 0.0 {
                if let Some(arc) = Arc::from_chord(*p, *q, *t) {
                    // the segment between the chord and the arc, on the side it bulges
                    let th = arc.sweep.abs();
                    let seg = arc.r * arc.r / 2.0 * (th - th.sin());
                    a += if arc.sweep > 0.0 { -seg } else { seg };
                }
            }
        }
        areas.push(a.abs());
    }
    // the largest loops are outlines; a loop inside one is a hole, one inside that an island:
    // without containment tests, the first is the outline and the rest holes
    if areas.is_empty() {
        return 0.0;
    }
    let mut sorted = areas.clone();
    sorted.sort_by(|a, b| b.partial_cmp(a).unwrap());
    let total = sorted[0] - sorted[1..].iter().sum::<f64>();
    total
}

pub fn region_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    if let Some(sk) = x.get("sketch").and_then(|s| s.as_arr()) {
        let a = loops_area(sk);
        x.set("area_m2", Value::f(r2(a / 1e6)));
    }
    if let Some(g) = common::text(x, "type").map(|s| s.to_string()) {
        if let Some(n) = common::lib_name_of(pr, "filled-region-type", &g) {
            x.set("type", Value::Str(n));
        }
    }
    if let Some(g) = common::text(x, "line_style").map(|s| s.to_string()) {
        if let Some(n) = common::lib_name_of(pr, "line-style", &g) {
            x.set("line_style", Value::Str(n));
        }
    }
    if x.get("pattern_angle").is_none() {
        x.set("pattern_angle", Value::f(0.0));
    }
    if x.get("pattern_origin").is_none() {
        x.set("pattern_origin", geo::pval([0.0, 0.0]));
    }
    let lv = view_level(pr, common::text(x, "view"));
    x.set("level", lv);
}

/// A detail group type's name and how many members it has, by its GUID.
fn group_type(cx: &Ctx, g: &str) -> Option<(String, usize)> {
    let name = common::lib_name_of(cx.pr, "detail-group", g)?;
    let n = cx
        .pr
        .section("detail_groups")
        .and_then(|m| m.get(&name))
        .and_then(|t| t.get("members"))
        .and_then(|m| m.as_arr())
        .map(|a| a.len())
        .unwrap_or(0);
    Some((name, n))
}

pub fn group_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    if let Some(g) = common::text(x, "type").map(|s| s.to_string()) {
        if let Some((n, m)) = group_type(cx, &g) {
            x.set("type", Value::Str(n));
            x.set("members", Value::u(m as u64));
        }
    }
    let lv = view_level(pr, common::text(x, "view"));
    x.set("level", lv);
}

/// How many times a repeating detail places its group along its line.
pub fn repeat_count(x: &Value) -> u64 {
    let (Some(a), Some(b)) = (geo::pt(x.get("start")), geo::pt(x.get("end"))) else { return 0 };
    let s = common::num(x, "spacing").unwrap_or(0.0);
    if s <= 0.0 {
        return 1;
    }
    ((geo::dist(a, b) / s + 1e-9).floor() as u64 + 1).min(2000)
}

pub fn repeating_view(cx: &Ctx, x: &mut Value) {
    let pr = cx.pr;
    if let Some(g) = common::text(x, "type").map(|s| s.to_string()) {
        if let Some((n, _)) = group_type(cx, &g) {
            x.set("type", Value::Str(n));
        }
    }
    let c = repeat_count(x);
    x.set("count", Value::u(c));
    let lv = view_level(pr, common::text(x, "view"));
    x.set("level", lv);
}
