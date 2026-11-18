//! A stand-in for the model geometry the views and the annotation read (ARCH and STRUCTURE own
//! the real thing): a wall's type, thickness, core, location line and centre line, its faces, the
//! heights an element spans, and outlines in plan of what the model builds.

use super::common::*;
use crate::json::Value;
use crate::project::Project;

/// A wall type's entry in `types.wall` (its `thickness`, `layers`).
pub fn wall_type<'a>(pr: &'a Project, e: &Value) -> Option<&'a Value> {
    let name = lib_ref_name(pr, e, "type")?;
    pr.section("types")?.get("wall")?.get(&name)
}

/// A type of a category's entry in `types.<cat>` by the element's `type` GUID.
pub fn type_entry<'a>(pr: &'a Project, cat: &str, e: &Value) -> Option<&'a Value> {
    let name = lib_ref_name(pr, e, "type")?;
    pr.section("types")?.get(cat)?.get(&name)
}

pub fn wall_thickness(pr: &Project, e: &Value) -> f64 {
    wall_type(pr, e).and_then(|t| f_of(t, "thickness")).unwrap_or(200.0)
}

/// The wall's layers, exterior first: (function, thickness).
pub fn wall_layers(pr: &Project, e: &Value) -> Vec<(String, f64)> {
    let Some(t) = wall_type(pr, e) else { return Vec::new() };
    let Some(a) = t.get("layers").and_then(|l| l.as_arr()) else { return Vec::new() };
    a.iter()
        .map(|l| (s_of(l, "function").unwrap_or("").to_string(), f_of(l, "thickness").unwrap_or(0.0)))
        .collect()
}

/// The core's two faces, as distances from the exterior face: the span of its structure layers
/// (the whole wall where it has none).
pub fn wall_core(pr: &Project, e: &Value) -> (f64, f64) {
    let t = wall_thickness(pr, e);
    let layers = wall_layers(pr, e);
    let mut at = 0.0;
    let mut core: Option<(f64, f64)> = None;
    for (f, th) in &layers {
        if f == "structure" {
            core = Some(match core {
                None => (at, at + th),
                Some((a, _)) => (a, at + th),
            });
        }
        at += th;
    }
    core.unwrap_or((0.0, t))
}

/// How far the wall's centre line lies left of its location line (the line its `start` and `end`
/// give), as its `location` says. The exterior face is the left one.
pub fn centre_offset(pr: &Project, e: &Value) -> f64 {
    let t = wall_thickness(pr, e);
    let (a, b) = wall_core(pr, e);
    match s_of(e, "location").unwrap_or("centre") {
        "exterior-finish" => -t / 2.0,
        "interior-finish" => t / 2.0,
        "core-centre" => (a + b) / 2.0 - t / 2.0,
        "exterior-core" => a - t / 2.0,
        "interior-core" => b - t / 2.0,
        _ => 0.0,
    }
}

/// A wall's line in plan: straight from `start` to `end`, or an arc turning `arc` degrees
/// counter-clockwise between them.
#[derive(Clone, Copy, Debug)]
pub struct WallLine {
    pub start: [f64; 2],
    pub end: [f64; 2],
    /// Degrees turned counter-clockwise (0: straight).
    pub arc: f64,
}

impl WallLine {
    pub fn is_arc(&self) -> bool {
        self.arc.abs() > 1e-9
    }
    pub fn length(&self) -> f64 {
        let c = dist(self.start, self.end);
        if !self.is_arc() {
            return c;
        }
        let (_, r) = self.circle().unwrap();
        r * self.arc.abs().to_radians()
    }
    /// The arc's centre and radius.
    pub fn circle(&self) -> Option<([f64; 2], f64)> {
        if !self.is_arc() {
            return None;
        }
        arc_circle(self.start, self.end, self.arc)
    }
    /// The line moved `d` to its left (an arc: concentric, its radius less `d` for a
    /// counter-clockwise one).
    pub fn offset(&self, d: f64) -> WallLine {
        if !self.is_arc() {
            let n = left_normal(self.start, self.end);
            return WallLine { start: add(self.start, mul(n, d)), end: add(self.end, mul(n, d)), arc: 0.0 };
        }
        let (c, _) = self.circle().unwrap();
        // left of a counter-clockwise arc is toward its centre
        let s = if self.arc > 0.0 { -d } else { d };
        let move_out = |p: [f64; 2]| {
            let v = sub(p, c);
            let l = norm(v);
            add(c, mul(v, (l + s) / l))
        };
        WallLine { start: move_out(self.start), end: move_out(self.end), arc: self.arc }
    }
    /// Points along it, `n` segments for an arc.
    pub fn points(&self, n: usize) -> Vec<[f64; 2]> {
        if !self.is_arc() {
            return vec![self.start, self.end];
        }
        let (c, r) = self.circle().unwrap();
        let a0 = (self.start[1] - c[1]).atan2(self.start[0] - c[0]);
        let sweep = self.arc.to_radians();
        (0..=n).map(|i| {
            let a = a0 + sweep * i as f64 / n as f64;
            [c[0] + r * a.cos(), c[1] + r * a.sin()]
        }).collect()
    }
}

/// The centre and radius of the arc from `a` to `b` turning `deg` degrees counter-clockwise.
pub fn arc_circle(a: [f64; 2], b: [f64; 2], deg: f64) -> Option<([f64; 2], f64)> {
    let t = deg.to_radians();
    let c = dist(a, b);
    if c == 0.0 || t == 0.0 {
        return None;
    }
    let r = c / (2.0 * (t / 2.0).sin().abs());
    let m = mid(a, b);
    // distance from the chord's middle to the centre, toward the left of a→b for a turn under 180
    let h = r * (t / 2.0).cos();
    let n = left_normal(a, b);
    let sign = if t > 0.0 { 1.0 } else { -1.0 };
    Some((add(m, mul(n, h * sign)), r))
}

/// The wall's location line, as its `start`, `end` and `arc` give it.
pub fn location_line(e: &Value) -> WallLine {
    WallLine {
        start: pt_of(e, "start").unwrap_or([0.0, 0.0]),
        end: pt_of(e, "end").unwrap_or([0.0, 0.0]),
        arc: f_of(e, "arc").unwrap_or(0.0),
    }
}

/// The wall's centre line (its location line moved as its `location` says).
pub fn centre_line(pr: &Project, e: &Value) -> WallLine {
    location_line(e).offset(centre_offset(pr, e))
}

/// The wall's left (exterior) and right faces, ends as the wall's own (no joins).
pub fn faces(pr: &Project, e: &Value) -> (WallLine, WallLine) {
    let c = centre_line(pr, e);
    let t = wall_thickness(pr, e);
    (c.offset(t / 2.0), c.offset(-t / 2.0))
}

// ---------------------------------------------------------------- heights

pub fn level_elevation(pr: &Project, e: &Value, k: &str) -> Option<f64> {
    let id = ref_id(pr, e, k)?;
    f_of(pr.el(id)?, "elevation")
}

/// The heights a wall (or a column) spans: its base over its level and its top at its top level
/// (with `top_offset`) or `height` over its base.
pub fn base_top(pr: &Project, e: &Value) -> (f64, f64) {
    let lv = level_elevation(pr, e, "level").unwrap_or(0.0);
    let base = lv + f_of(e, "base_offset").unwrap_or(0.0);
    let top = match level_elevation(pr, e, "top_level") {
        Some(t) => t + f_of(e, "top_offset").unwrap_or(0.0),
        None => base + f_of(e, "height").unwrap_or(3000.0),
    };
    (base, top)
}

// ---------------------------------------------------------------- outlines in plan

/// The outline in plan of a built element where the stand-in knows it: a wall's (its faces, no
/// joins), a floor's, ceiling's or roof's boundary, a column's or footing's rectangle or circle.
pub fn outline(pr: &Project, id: u64) -> Option<Vec<[f64; 2]>> {
    let e = pr.el(id)?;
    match cat(e) {
        "wall" => {
            let (l, r) = faces(pr, e);
            let mut pts = l.points(32);
            let mut back = r.points(32);
            back.reverse();
            pts.extend(back);
            Some(pts)
        }
        "floor" | "ceiling" | "roof" | "shaft" => pts_of(e, "boundary"),
        "column" | "structural_column" | "structuralcolumn" | "footing" => {
            let c = pt_of(e, "at")?;
            let cat_key = match cat(e) {
                "structuralcolumn" => "structural_column",
                x => x,
            };
            let t = type_entry(pr, cat_key, e);
            let w = t.and_then(|t| f_of(t, "width")).unwrap_or(400.0);
            let d = t.and_then(|t| f_of(t, "depth")).unwrap_or(w);
            let round = t.and_then(|t| t.get("round")).and_then(|r| r.as_bool()).unwrap_or(false);
            let a = f_of(e, "angle").unwrap_or(0.0).to_radians();
            if round {
                return Some((0..32).map(|i| {
                    let t = i as f64 / 32.0 * std::f64::consts::TAU;
                    [c[0] + w / 2.0 * t.cos(), c[1] + w / 2.0 * t.sin()]
                }).collect());
            }
            let (ca, sa) = (a.cos(), a.sin());
            Some([[-w / 2.0, -d / 2.0], [w / 2.0, -d / 2.0], [w / 2.0, d / 2.0], [-w / 2.0, d / 2.0]]
                .iter()
                .map(|p| [c[0] + p[0] * ca - p[1] * sa, c[1] + p[0] * sa + p[1] * ca])
                .collect())
        }
        _ => None,
    }
}

/// The south-west and north-east corners round some points.
pub fn bounds(pts: &[[f64; 2]]) -> Option<([f64; 2], [f64; 2])> {
    let mut it = pts.iter();
    let f = *it.next()?;
    let (mut lo, mut hi) = (f, f);
    for p in it {
        lo = [lo[0].min(p[0]), lo[1].min(p[1])];
        hi = [hi[0].max(p[0]), hi[1].max(p[1])];
    }
    Some((lo, hi))
}

// ---------------------------------------------------------------- vectors

pub fn add(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] + b[0], a[1] + b[1]]
}
pub fn sub(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] - b[0], a[1] - b[1]]
}
pub fn mul(a: [f64; 2], k: f64) -> [f64; 2] {
    [a[0] * k, a[1] * k]
}
pub fn dot(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}
pub fn cross(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}
pub fn norm(a: [f64; 2]) -> f64 {
    (a[0] * a[0] + a[1] * a[1]).sqrt()
}
pub fn dist(a: [f64; 2], b: [f64; 2]) -> f64 {
    norm(sub(a, b))
}
pub fn mid(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]
}
pub fn unit(a: [f64; 2]) -> [f64; 2] {
    let l = norm(a);
    if l == 0.0 {
        [0.0, 0.0]
    } else {
        [a[0] / l, a[1] / l]
    }
}
/// The unit normal to the left of the way from `a` to `b`.
pub fn left_normal(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    let d = unit(sub(b, a));
    [-d[1], d[0]]
}
