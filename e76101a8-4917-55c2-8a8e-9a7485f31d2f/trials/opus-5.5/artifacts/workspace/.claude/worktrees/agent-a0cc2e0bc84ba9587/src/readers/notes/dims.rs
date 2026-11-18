//! Dimensions as `elements` shows them: their type's name, the lengths (or angle, radius…) they
//! measure, and their text as it is lettered.

use super::geo::{self, Arc, P};
use super::units;
use crate::json::Value;
use crate::readers::common::{self, r2, Ctx};

/// What a dimension's reference is in plan.
#[derive(Clone, Copy, Debug)]
pub enum Geo {
    /// A line through a point along a direction.
    Line(P, P),
    Point(P),
    Circle(P, f64),
    Arc(Arc),
}

fn ref_str<'a>(r: &'a Value, k: &str) -> Option<&'a str> {
    r.get(k).and_then(|v| v.as_str())
}

/// The plan geometry a stored reference `{id, face, point?}` stands for.
pub fn resolve(cx: &Ctx, r: &Value) -> Option<Geo> {
    let pr = cx.pr;
    let g = ref_str(r, "id")?;
    let (id, e) = common::by_guid(pr, g)?;
    let face = ref_str(r, "face").unwrap_or("centre");
    let point = ref_str(r, "point");
    match common::category(e) {
        "wall" => {
            let w = geo::wall(cx, id)?;
            if let Some(pt) = point {
                let end = pt == "end";
                return Some(Geo::Point(match face {
                    "start" | "end" => w.face_end("centre", end),
                    f => w.face_end(f, end),
                }));
            }
            match face {
                "start" | "end" => {
                    let along = w.end_along(face == "end");
                    Some(Geo::Line(geo::add(w.a, geo::mul(w.d, along)), w.n))
                }
                f => {
                    if let Some(a) = w.face_arc(f) {
                        return Some(Geo::Arc(a));
                    }
                    Some(Geo::Line(w.face_point(f), w.d))
                }
            }
        }
        "door" | "window" => {
            let (p, d, w) = geo::opening_place(cx, e)?;
            let width = geo::opening_width(pr, e).unwrap_or(0.0);
            let at = match face {
                "start" => geo::sub(p, geo::mul(d, width / 2.0)),
                "end" => geo::add(p, geo::mul(d, width / 2.0)),
                _ => p,
            };
            let n = geo::left(d);
            if let Some(pt) = point {
                let off = if pt == "end" { w.right } else { w.left };
                return Some(Geo::Point(geo::add(at, geo::mul(n, off))));
            }
            Some(Geo::Line(at, n))
        }
        "grid" => {
            let a = geo::pt(e.get("start"))?;
            let b = geo::pt(e.get("end"))?;
            if let Some(pt) = point {
                return Some(Geo::Point(if pt == "end" { b } else { a }));
            }
            Some(Geo::Line(a, geo::unit(geo::sub(b, a))))
        }
        "line" => line_geo(e, point),
        "column" | "structuralcolumn" => {
            let at = geo::pt(e.get("at"))?;
            let (_, def) = common::element_type(pr, e)?;
            let w = common::num(def, "width").unwrap_or(0.0);
            Some(Geo::Circle(at, w / 2.0))
        }
        _ => None,
    }
}

/// A detail line's geometry: a straight one's line, an arc, a circle; with `point`, an end.
fn line_geo(e: &Value, point: Option<&str>) -> Option<Geo> {
    if let Some(c) = geo::pt(e.get("centre")) {
        if let Some(r) = common::num(e, "radius") {
            if let Some(pt) = point {
                let _ = pt;
                return Some(Geo::Point([c[0] + r, c[1]]));
            }
            return Some(Geo::Circle(c, r));
        }
    }
    let (a, b) = match (geo::pt(e.get("start")), geo::pt(e.get("end"))) {
        (Some(a), Some(b)) => (a, b),
        _ => {
            let pts = common::points(e.get("points").unwrap_or(&Value::Null));
            if pts.len() >= 2 {
                if let Some(pt) = point {
                    return Some(Geo::Point(if pt == "end" { *pts.last()? } else { pts[0] }));
                }
                return Some(Geo::Line(pts[0], geo::unit(geo::sub(pts[1], pts[0]))));
            }
            for k in ["control", "fit"] {
                let pts = common::points(e.get(k).unwrap_or(&Value::Null));
                if pts.len() >= 2 {
                    if let Some(pt) = point {
                        return Some(Geo::Point(if pt == "end" { *pts.last()? } else { pts[0] }));
                    }
                }
            }
            return None;
        }
    };
    if let Some(pt) = point {
        return Some(Geo::Point(if pt == "end" { b } else { a }));
    }
    if let Some(t) = common::num(e, "arc").filter(|t| *t != 0.0) {
        return Arc::from_chord(a, b, t).map(Geo::Arc);
    }
    Some(Geo::Line(a, geo::unit(geo::sub(b, a))))
}

/// The way a dimension counts its segments: west to east, or south to north.
fn canonical(u: P) -> P {
    if u[0] < -1e-9 || (u[0].abs() <= 1e-9 && u[1] < 0.0) {
        [-u[0], -u[1]]
    } else {
        u
    }
}

fn geo_point(g: &Geo) -> P {
    match g {
        Geo::Line(p, _) | Geo::Point(p) | Geo::Circle(p, _) => *p,
        Geo::Arc(a) => a.c,
    }
}

/// The lengths between references along a direction: their places sorted, and the steps between.
fn along(geos: &[Geo], u: P) -> Vec<f64> {
    let mut at: Vec<f64> = geos.iter().map(|g| geo::dot(geo_point(g), u)).collect();
    at.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    at.windows(2).map(|w| w[1] - w[0]).collect()
}

/// An aligned dimension's lengths: square to its lines, or along its first two points.
fn aligned(geos: &[Geo]) -> Vec<f64> {
    let line = geos.iter().find_map(|g| if let Geo::Line(_, d) = g { Some(*d) } else { None });
    let u = match line {
        Some(d) => geo::left(d),
        None => {
            let pts: Vec<P> = geos.iter().map(geo_point).collect();
            if pts.len() < 2 {
                return Vec::new();
            }
            geo::unit(geo::sub(pts[1], pts[0]))
        }
    };
    along(geos, canonical(u))
}

/// The angle between two lines that meet, on the side of `at`.
fn angular(geos: &[Geo], at: P) -> Option<f64> {
    let (p, d) = match geos.first()? {
        Geo::Line(p, d) => (*p, *d),
        _ => return None,
    };
    let (q, e) = match geos.get(1)? {
        Geo::Line(q, e) => (*q, *e),
        _ => return None,
    };
    let o = geo::meet(p, d, q, e)?;
    let v = geo::sub(at, o);
    // at = s d + t e: the rays toward `at`
    let den = geo::cross(d, e);
    let s = geo::cross(v, e) / den;
    let t = geo::cross(d, v) / den;
    let d1 = if s < 0.0 { geo::mul(d, -1.0) } else { d };
    let e1 = if t < 0.0 { geo::mul(e, -1.0) } else { e };
    let c = geo::dot(geo::unit(d1), geo::unit(e1)).clamp(-1.0, 1.0);
    Some(c.acos().to_degrees())
}

/// What a dimension measures, unrounded, in mm (degrees for an angle).
pub fn measure(cx: &Ctx, x: &Value) -> Vec<f64> {
    let refs: Vec<Geo> = match x.get("refs").and_then(|r| r.as_arr()) {
        Some(a) => a.iter().filter_map(|r| resolve(cx, r)).collect(),
        None => Vec::new(),
    };
    let kind = common::text(x, "kind").unwrap_or("aligned");
    let at = geo::pt(x.get("at")).unwrap_or([0.0, 0.0]);
    match kind {
        "linear" => {
            let u = if common::text(x, "orient") == Some("vertical") { [0.0, 1.0] } else { [1.0, 0.0] };
            along(&refs, u)
        }
        "angular" => angular(&refs, at).into_iter().collect(),
        "radial" | "diameter" => {
            let r = match refs.first() {
                Some(Geo::Circle(_, r)) => Some(*r),
                Some(Geo::Arc(a)) => Some(a.r),
                _ => None,
            };
            r.map(|r| if kind == "diameter" { 2.0 * r } else { r }).into_iter().collect()
        }
        "arc_length" => {
            let a = match refs.first() {
                Some(Geo::Arc(a)) => *a,
                Some(Geo::Circle(c, r)) => Arc { c: *c, r: *r, a0: 0.0, sweep: 2.0 * std::f64::consts::PI },
                _ => return Vec::new(),
            };
            if let (Some(Geo::Point(p)), Some(Geo::Point(q))) = (refs.get(1), refs.get(2)) {
                let ang = |p: P| (p[1] - a.c[1]).atan2(p[0] - a.c[0]);
                let norm = |x: f64| {
                    let mut f = (x - a.a0) / a.sweep;
                    let tau = 2.0 * std::f64::consts::PI / a.sweep.abs();
                    while f < 0.0 {
                        f += tau;
                    }
                    f
                };
                let (f1, f2) = (norm(ang(*p)), norm(ang(*q)));
                return vec![(f2 - f1).abs() * a.length()];
            }
            vec![a.length()]
        }
        _ => aligned(&refs),
    }
}

/// The dimension type a dimension letters in: its name and definition.
fn dim_type<'p>(cx: &'p Ctx, x: &Value) -> Option<(String, Option<&'p Value>)> {
    let g = common::text(x, "type")?;
    let name = common::lib_name_of(cx.pr, "dimension-type", g)?;
    let def = cx.pr.section("dimension_types").and_then(|m| m.get(&name));
    Some((name, def))
}

pub fn view(cx: &Ctx, x: &mut Value) {
    let kind = common::text(x, "kind").unwrap_or("aligned").to_string();
    let (tname, tdef) = match dim_type(cx, x) {
        Some((n, d)) => (Some(n), d.cloned()),
        None => (None, None),
    };
    let raw = measure(cx, x);
    let tget = |k: &str| tdef.as_ref().and_then(|d| d.get(k)).cloned();
    let units = tget("units").and_then(|v| v.as_str().map(|s| s.to_string())).unwrap_or_else(|| units::project_units(cx.pr));
    let decimals = tget("decimals").and_then(|v| v.as_u64());
    let eq_text = tget("equality_text").and_then(|v| v.as_str().map(|s| s.to_string())).unwrap_or_else(|| "EQ".into());
    let rsym = tget("radius_symbol").and_then(|v| v.as_str().map(|s| s.to_string())).unwrap_or_else(|| "R".into());
    let dsym = tget("diameter_symbol").and_then(|v| v.as_str().map(|s| s.to_string())).unwrap_or_else(|| "Ø".into());
    let equality = x.get("equality").and_then(|v| v.as_bool()).unwrap_or(false);
    let texts: Vec<Value> = x.get("texts").and_then(|t| t.as_arr()).cloned().unwrap_or_default();
    let mut labels = Vec::new();
    for (i, v) in raw.iter().enumerate() {
        let number = match kind.as_str() {
            "angular" => format!("{}°", units::shortest(r2(*v))),
            "radial" => format!("{} {}", rsym, units::length_text(*v, &units, decimals)),
            "diameter" => format!("{} {}", dsym, units::length_text(*v, &units, decimals)),
            _ => units::length_text(*v, &units, decimals),
        };
        let seg = texts.iter().find(|t| t.get("segment").and_then(|s| s.as_u64()) == Some(i as u64));
        let field = |k: &str| -> Option<String> {
            if let Some(s) = seg.and_then(|s| s.get(k)).and_then(|v| v.as_str()) {
                if !s.is_empty() {
                    return Some(s.to_string());
                }
            }
            x.get(k).and_then(|v| v.as_str()).filter(|s| !s.is_empty()).map(|s| s.to_string())
        };
        let label = if let Some(r) = field("replace") {
            r
        } else if equality && raw.len() > 1 {
            eq_text.clone()
        } else {
            format!("{}{}{}", field("prefix").unwrap_or_default(), number, field("suffix").unwrap_or_default())
        };
        labels.push(Value::Str(label));
    }
    if let Some(n) = tname {
        x.set("type", Value::Str(n));
    }
    x.set("values", Value::Arr(raw.iter().map(|v| Value::f(r2(*v))).collect()));
    x.set("labels", Value::Arr(labels));
}
