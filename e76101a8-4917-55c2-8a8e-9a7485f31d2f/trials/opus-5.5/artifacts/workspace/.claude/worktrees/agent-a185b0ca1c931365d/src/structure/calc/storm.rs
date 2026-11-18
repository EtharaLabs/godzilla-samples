//! `storm_size`: NBR 10844: storm drains. The flow is given, or the rain on a roof (Q = I·A/60);
//! a downpipe takes the inner diameter of the standard's Figure 3 abacuses, read curve by curve
//! (the water depth in the gutter and the downpipe's length, for a sharp-edged or a funnel
//! outlet), 70 mm at least; a horizontal drain takes Manning at two thirds full (n 0.011).

use super::drainage::args::{self, given, known, num, object, round};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;

/// The abacuses' water-depth curves: depth (mm) and the line D = a + b·Q (mm, Q in L/min).
const DEPTH_EDGE: &[(f64, f64, f64)] = &[
    (50.0, -35.9298, 0.225112),
    (60.0, -46.8196, 0.180246),
    (70.0, -52.2541, 0.141298),
    (80.0, -61.4213, 0.117392),
    (90.0, -66.4115, 0.0970961),
    (100.0, -74.0949, 0.0831159),
];
const DEPTH_FUNNEL: &[(f64, f64, f64)] = &[
    (50.0, -31.2141, 0.185536),
    (60.0, -43.985, 0.148011),
    (70.0, -45.8972, 0.115612),
    (80.0, -50.0707, 0.0924092),
    (90.0, -56.8891, 0.0777569),
    (100.0, -64.1189, 0.0672002),
];

/// The abacuses' length curves: the downpipe's length (m) and ln Q = a + b·ln D + c·ln² D; the
/// last is the length without end, which the readings past the last length tend to (in 1/L).
const LENGTH_EDGE: &[(f64, f64, f64, f64)] = &[
    (0.3, -5.335566, 2.955357, -0.0699641),
    (0.6, -2.474349, 1.861605, 0.03953277),
    (1.0, -3.238297, 2.271285, -0.006142782),
    (1.5, -3.909381, 2.662537, -0.0534521),
    (2.0, -1.863548, 1.785209, 0.04467243),
    (3.0, -2.737448, 2.226814, -0.004120258),
    (6.0, -1.68533, 1.777841, 0.05398324),
    (25.0, -2.783537, 2.265283, 0.01298375),
    (f64::INFINITY, -3.356874, 2.528462, -0.01051506),
];
const LENGTH_FUNNEL: &[(f64, f64, f64, f64)] = &[
    (0.3, -4.579124, 2.661122, -0.0352465),
    (0.6, -0.4543047, 1.02079, 0.1325171),
    (1.0, -2.228662, 1.905355, 0.03019043),
    (1.5, 2.299307, -0.005009665, 0.2364149),
    (2.0, -5.589389, 3.483486, -0.1450473),
    (3.0, 0.03895126, 0.9977121, 0.1351049),
    (6.0, -1.222848, 1.558281, 0.08180418),
    (25.0, 4.10884, -0.9274304, 0.3834927),
    (f64::INFINITY, -5.859644, 3.620164, -0.1288296),
];

/// What the abacuses read: 50 to 150 mm.
const CHART_MIN: f64 = 50.0;
const CHART_MAX: f64 = 150.0;
/// The least inner diameter of a downpipe (mm).
const DOWNPIPE_MIN: f64 = 70.0;
/// Manning's n for PVC (the standard's Table 2).
const MANNING_N: f64 = 0.011;

const OFF_CHART: &str = "more than 150 mm inside is off the abacuses of NBR 10844's Figure 3";

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = s;
    size(cid, p).map_err(args::clip)
}

fn size(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(cmd, &m, &["area", "flow", "gutter", "inside", "kind", "length", "outlet", "rainfall", "slope"])?;
    if given(&m, "kind").is_none() {
        return Err(format!("{}: `kind` (downpipe or horizontal) is required", cmd));
    }
    let kind = args::choice(cmd, &m, "kind", &["downpipe", "horizontal"])?.unwrap_or_default();
    let downpipe = kind == "downpipe";
    let not_here: &[&str] = if downpipe { &["slope", "inside"] } else { &["outlet", "gutter", "length"] };
    for k in not_here {
        if m.contains(k) {
            return Err(format!("{}: `{}` does not apply to a {}", cmd, k, kind));
        }
    }
    for k in ["area", "rainfall"] {
        if m.contains(k) && given(&m, "flow").is_some() {
            return Err(format!("{}: `{}` and `flow` are two ways to give the flow: give one", cmd, k));
        }
    }
    let outlet = if downpipe {
        args::choice(cmd, &m, "outlet", &["edge", "funnel"])?.unwrap_or_else(|| "edge".into())
    } else {
        String::new()
    };
    let area = num(cmd, &m, "area", 0.0, 1e7)?.unwrap_or(0.0);
    let flow = num(cmd, &m, "flow", f64::MIN_POSITIVE, 1e9)?;
    let q = match flow {
        Some(q) => q,
        None => {
            if area <= 0.0 {
                return Err(format!("{}: `area` (m², the roof that drains) or `flow` (L/min) is required", cmd));
            }
            let rainfall = num(cmd, &m, "rainfall", f64::MIN_POSITIVE, 1000.0)?;
            let i = match rainfall {
                Some(i) => i,
                None if area > 100.0 => {
                    return Err(format!(
                        "{}: `rainfall` (mm/h, from the standard's table for the place and return period) is required above 100 m²: the default 150 mm/h is for smaller roofs",
                        cmd
                    ))
                }
                None => 150.0,
            };
            i * area / 60.0
        }
    };
    if downpipe {
        downpipe_size(cmd, &m, q, &outlet)
    } else {
        horizontal_size(cmd, &m, q)
    }
}

fn downpipe_size(cmd: &str, m: &Map, q: f64, outlet: &str) -> R<Value> {
    if given(m, "gutter").is_none() {
        return Err(format!("{}: `gutter` (the water depth in the gutter, 50 to 100 mm) is required", cmd));
    }
    if given(m, "length").is_none() {
        return Err(format!("{}: `length` (the downpipe's, mm) is required", cmd));
    }
    let gutter = num(cmd, m, "gutter", 0.0, 10000.0)?.unwrap_or(0.0);
    let length = num(cmd, m, "length", 0.0, 1e9)?.unwrap_or(0.0);
    if !(gutter >= CHART_MIN - 1e-9 && gutter <= 100.0 + 1e-9) {
        return Err(format!(
            "{}: the water depth in the gutter must be 50 to 100 mm: the abacuses stop there",
            cmd
        ));
    }
    let len_m = length / 1000.0;
    if len_m < 0.3 - 1e-9 {
        return Err(format!("{}: a downpipe shorter than 0.3 m is off the abacuses", cmd));
    }
    let funnel = outlet == "funnel";
    let depth = by_depth(q, gutter, if funnel { DEPTH_FUNNEL } else { DEPTH_EDGE });
    if depth > CHART_MAX {
        return Err(format!("{}: {}", cmd, OFF_CHART));
    }
    let Some(len) = by_length(q, len_m, if funnel { LENGTH_FUNNEL } else { LENGTH_EDGE }) else {
        return Err(format!("{}: {}", cmd, OFF_CHART));
    };
    let mut inside = if depth > len { depth } else { len };
    if inside < DOWNPIPE_MIN {
        inside = DOWNPIPE_MIN;
    }
    let mut o = Map::new();
    o.insert("by_depth_mm", Value::f(round(depth, 1)));
    o.insert("by_length_mm", Value::f(round(len, 1)));
    o.insert("flow_lpm", Value::f(round(q, 2)));
    o.insert("inside_mm", Value::f(round(inside, 1)));
    Ok(Value::Obj(o))
}

/// The reading by the water depth: between the two depth curves round it, in a straight line.
fn by_depth(q: f64, h: f64, curves: &[(f64, f64, f64)]) -> f64 {
    let mut i = 0;
    while i + 2 < curves.len() && h > curves[i + 1].0 {
        i += 1;
    }
    let (h0, a0, b0) = curves[i];
    let (h1, a1, b1) = curves[i + 1];
    let d0 = a0 + b0 * q;
    let d1 = a1 + b1 * q;
    let t = (h - h0) / (h1 - h0);
    d0 + t * (d1 - d0)
}

/// The reading on one length curve: 50 mm at the foot of the chart, none above its top.
fn on_curve(q: f64, (_, a, b, c): (f64, f64, f64, f64)) -> Option<f64> {
    let q_at = |d: f64| {
        let u = d.ln();
        (a + b * u + c * u * u).exp()
    };
    if q <= q_at(CHART_MIN) {
        return Some(CHART_MIN);
    }
    if q > q_at(CHART_MAX) {
        return None;
    }
    let disc = b * b - 4.0 * c * (a - q.ln());
    let u = (-b + disc.sqrt()) / (2.0 * c);
    Some(u.exp())
}

/// The reading by the length: between the two length curves round it, in a straight line, each
/// curve never above the one of a shorter pipe; past the last length, toward the curve of the
/// length without end in 1/L.
fn by_length(q: f64, l: f64, curves: &[(f64, f64, f64, f64)]) -> Option<f64> {
    let mut i = 0;
    while i + 2 < curves.len() && l >= curves[i + 1].0 {
        i += 1;
    }
    // each curve's reading, held to the reading of the shorter pipe before it
    let mut read: Vec<Option<f64>> = Vec::with_capacity(i + 2);
    let mut least: Option<f64> = None;
    for c in curves.iter().take(i + 2) {
        let d = on_curve(q, *c).map(|d| match least {
            Some(m) if d > m => m,
            _ => d,
        });
        if let Some(v) = d {
            least = Some(match least {
                Some(m) if m < v => m,
                _ => v,
            });
        }
        read.push(d);
    }
    let d0 = read[i]?;
    let d1 = read[i + 1]?;
    let (l0, l1) = (curves[i].0, curves[i + 1].0);
    if l1.is_infinite() {
        return Some(d1 + (d0 - d1) * (l0 / l));
    }
    let t = (l - l0) / (l1 - l0);
    Some(d0 + t * (d1 - d0))
}

fn horizontal_size(cmd: &str, m: &Map, q: f64) -> R<Value> {
    let Some(slope) = num(cmd, m, "slope", 0.0, 1.0)? else {
        return Err(format!("{}: `slope` (a fraction, 0.005 at least) is required", cmd));
    };
    if slope < 0.005 - 1e-9 {
        return Err(format!("{}: `slope` must be 0.5 % (0.005) at least, NBR 10844", cmd));
    }
    let inside = num(cmd, m, "inside", 0.0, 10000.0)?.unwrap_or(0.0);
    let k = manning_k();
    // Q (m³/s) = K·D^(8/3)·√S / n at two thirds full: the diameter it needs
    let q_m3s = q / 60000.0;
    let need = (q_m3s * MANNING_N / (k * slope.sqrt())).powf(3.0 / 8.0) * 1000.0;
    let mut o = Map::new();
    if inside > 0.0 {
        let carries = capacity(inside, slope);
        o.insert("carries_lpm", Value::f(round(carries, 1)));
        o.insert("ok", Value::Bool(q <= carries + 1e-9));
    } else {
        o.insert("carries_lpm", Value::Null);
        o.insert("ok", Value::Null);
    }
    o.insert("flow_lpm", Value::f(round(q, 2)));
    o.insert("inside_mm", Value::f(round(need, 1)));
    Ok(Value::Obj(o))
}

/// The angle a water surface at two thirds of the diameter subtends at the centre.
fn theta() -> f64 {
    2.0 * (1.0f64 - 2.0 * (2.0 / 3.0)).acos()
}

/// A·R^(2/3) / D^(8/3) of a pipe two thirds full.
fn manning_k() -> f64 {
    let th = theta();
    let a = (th - th.sin()) / 8.0;
    let p = th / 2.0;
    let r = a / p;
    a * r.powf(2.0 / 3.0)
}

/// What a pipe of `inside` mm carries two thirds full at `slope` (L/min).
fn capacity(inside: f64, slope: f64) -> f64 {
    let d = inside / 1000.0;
    let th = theta();
    let a = d * d / 8.0 * (th - th.sin());
    let p = th * d / 2.0;
    let r = a / p;
    a * r.powf(2.0 / 3.0) * slope.sqrt() / MANNING_N * 60000.0
}
