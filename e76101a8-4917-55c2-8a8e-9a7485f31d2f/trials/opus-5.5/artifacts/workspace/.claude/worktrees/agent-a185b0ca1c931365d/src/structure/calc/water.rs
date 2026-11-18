//! `water_size`: NBR 5626: a cold water pipe of PVC soldável: the design flow of the fixtures
//! (Tigre's flows and weights), the smallest DN within 3 m/s, the Darcy-Weisbach head loss
//! (Colebrook, PVC at 20 °C) over the length and the fittings' equivalent length, and the
//! pressure left at the end.

use super::drainage::args::{self, given, known, num, object, round};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;

/// Tigre's fixtures (Manual Técnico, page 198): name, flow (L/s) and weight.
const FIXTURES: &[(&str, f64, f64)] = &[
    ("wc", 0.15, 0.3),
    ("lav", 0.15, 0.3),
    ("sink", 0.25, 0.7),
    ("shower", 0.2, 0.4),
    ("laundry", 0.25, 0.7),
];

/// PVC soldável: DN and inside diameter (mm).
const PIPES: &[(f64, f64)] = &[
    (20.0, 17.0),
    (25.0, 21.6),
    (32.0, 27.8),
    (40.0, 35.2),
    (50.0, 44.0),
    (60.0, 53.4),
    (75.0, 66.6),
    (85.0, 75.6),
    (110.0, 97.8),
];

/// The fittings in the order the original names them.
const FITTINGS: &[&str] = &["elbow90", "elbow45", "tee_through", "tee_side", "gate", "globe", "check"];

/// Their equivalent lengths (m) per DN, in the order of `FITTINGS`.
const EQUIVALENT: &[(f64, [f64; 7])] = &[
    (20.0, [1.1, 0.4, 0.7, 2.3, 0.1, 11.1, 2.5]),
    (25.0, [1.2, 0.5, 0.8, 2.4, 0.2, 11.4, 2.7]),
    (32.0, [1.5, 0.7, 0.9, 3.1, 0.3, 15.0, 3.8]),
    (40.0, [2.0, 1.0, 1.5, 4.6, 0.4, 22.0, 4.9]),
    (50.0, [3.2, 1.3, 2.2, 7.3, 0.7, 35.8, 6.8]),
    (60.0, [3.4, 1.5, 2.3, 7.6, 0.8, 37.9, 7.1]),
    (75.0, [3.7, 1.7, 2.4, 7.8, 0.9, 38.0, 8.2]),
    (85.0, [3.9, 1.8, 2.5, 8.0, 0.9, 40.0, 9.3]),
    (110.0, [4.3, 1.9, 2.6, 8.3, 1.0, 42.3, 10.4]),
];

/// Water at 20 °C: kinematic viscosity (m²/s); PVC's roughness (mm); g (m/s²).
const NU: f64 = 1.004e-6;
const ROUGHNESS_MM: f64 = 0.0015;
const G: f64 = 9.81;
/// The most speed (m/s) and the least pressure at a point of use (kPa).
const MAX_SPEED: f64 = 3.0;
const MIN_END_KPA: f64 = 10.0;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = s;
    size(cid, p).map_err(args::clip)
}

fn size(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(cmd, &m, &["dn", "fittings", "fixtures", "flow", "length", "method", "pressure", "rise"])?;
    let method = args::choice(cmd, &m, "method", &["weights", "sum"])?.unwrap_or_else(|| "weights".into());
    if given(&m, "flow").is_some() && given(&m, "fixtures").is_some() {
        return Err(format!("{}: give `flow` or `fixtures`, not both", cmd));
    }
    let fixtures = fixture_flows(cmd, &m)?;
    let flow = num(cmd, &m, "flow", f64::MIN_POSITIVE, 1000.0)?;
    let q = match (flow, fixtures) {
        (Some(q), _) => q,
        (None, Some((sum_q, sum_p))) => {
            if method == "sum" {
                sum_q
            } else {
                let w = 0.3 * sum_p.sqrt();
                if w > sum_q {
                    sum_q
                } else {
                    w
                }
            }
        }
        (None, None) => return Err(format!("{}: `flow` (L/s) or `fixtures` is required", cmd)),
    };
    let dn = num(cmd, &m, "dn", 0.0, 1000.0)?;
    let (dn, inside) = match dn {
        Some(d) => match PIPES.iter().find(|(n, _)| *n == d) {
            Some(p) => *p,
            None => {
                return Err(format!(
                    "{}: `dn` must be one of 20, 25, 32, 40, 50, 60, 75, 85, 110 (PVC soldável)",
                    cmd
                ))
            }
        },
        None => match PIPES.iter().find(|(_, di)| speed(q, *di) <= MAX_SPEED + 1e-9) {
            Some(p) => *p,
            None => {
                return Err(format!(
                    "{}: no DN of PVC soldável (20 to 110) keeps the speed within 3 m/s at that flow",
                    cmd
                ))
            }
        },
    };
    let length = num(cmd, &m, "length", 0.0, 1e9)?.unwrap_or(0.0);
    let fits = fitting_counts(cmd, &m)?;
    let pressure = num(cmd, &m, "pressure", 0.0, 100000.0)?;
    let rise = match pressure {
        Some(_) => num(cmd, &m, "rise", -1e9, 1e9)?.unwrap_or(0.0),
        None => 0.0,
    };
    // the equivalent length: the pipe's, then each fitting in turn (in sorted order)
    let eq = &EQUIVALENT.iter().find(|(n, _)| *n == dn).expect("a DN of the table").1;
    let mut leq = length / 1000.0;
    for (name, count) in &fits {
        let i = FITTINGS.iter().position(|f| f == name).expect("a fitting of the table");
        leq += count * eq[i];
    }
    let v = speed(q, inside);
    let j = head_loss(q, inside);
    let loss = j * leq * G;
    let speed_ok = v <= MAX_SPEED + 1e-9;
    let mut o = Map::new();
    o.insert("dn", Value::f(dn));
    match pressure {
        Some(pr) => {
            let end = pr - loss - rise / 1000.0 * G;
            o.insert("end_kpa", Value::f(round(end, 2)));
            o.insert("ok", Value::Bool(speed_ok && end >= MIN_END_KPA));
            o.insert("ok_covers", Value::s("the speed and the pressure left at the end"));
        }
        None => {
            o.insert("end_kpa", Value::Null);
            o.insert("ok", Value::Bool(speed_ok));
            o.insert("ok_covers", Value::s("the speed alone: no pressure was given"));
        }
    }
    o.insert("equivalent_length_m", Value::f(round(leq, 2)));
    o.insert("flow_lps", Value::f(round(q, 3)));
    o.insert("head_loss_m_per_m", Value::f(round(j, 5)));
    o.insert("inside_mm", Value::f(inside));
    o.insert("loss_kpa", Value::f(round(loss, 2)));
    o.insert("speed_ms", Value::f(round(v, 2)));
    Ok(Value::Obj(o))
}

/// The fixtures given: (the sum of their flows, the sum of their weights); none without them.
fn fixture_flows(cmd: &str, m: &Map) -> R<Option<(f64, f64)>> {
    let Some(v) = given(m, "fixtures") else { return Ok(None) };
    let Value::Obj(f) = v else {
        return Err(format!("{}: `fixtures` must be an object {{kind: count}}, got {}", cmd, v.to_compact()));
    };
    let mut sum_q = 0.0;
    let mut sum_p = 0.0;
    let mut any = false;
    for (k, c) in f.iter() {
        let Some((_, fq, fp)) = FIXTURES.iter().find(|(n, _, _)| n == k) else {
            return Err(format!(
                "{}: `fixtures`: no fixture `{}`, use wc, lav, sink, shower, laundry",
                cmd, k
            ));
        };
        let Some(n) = args::whole_of(c, 0.0, 10000.0) else {
            return Err(format!(
                "{}: `fixtures`: `{}` must be a whole number from 0 to 10000, got {}",
                cmd,
                k,
                c.to_compact()
            ));
        };
        sum_q += n * fq;
        sum_p += n * fp;
        if n > 0.0 {
            any = true;
        }
    }
    Ok(if any { Some((sum_q, sum_p)) } else { None })
}

/// The fittings given, by name in sorted order, with their counts.
fn fitting_counts(cmd: &str, m: &Map) -> R<Vec<(String, f64)>> {
    let Some(v) = given(m, "fittings") else { return Ok(Vec::new()) };
    let Value::Obj(f) = v else {
        return Err(format!("{}: `fittings` must be an object {{fitting: count}}, got {}", cmd, v.to_compact()));
    };
    let mut out = Vec::new();
    for (k, c) in f.iter() {
        if !FITTINGS.contains(&k.as_str()) {
            return Err(format!(
                "{}: `fittings`: no fitting `{}`, use elbow90, elbow45, tee_through, tee_side, gate, globe, check",
                cmd, k
            ));
        }
        let Some(n) = args::whole_of(c, 0.0, 10000.0) else {
            return Err(format!(
                "{}: `fittings`: `{}` must be a whole number from 0 to 10000, got {}",
                cmd,
                k,
                c.to_compact()
            ));
        };
        out.push((k.clone(), n));
    }
    Ok(out)
}

/// The mean speed (m/s) of `q` L/s in a pipe of `inside` mm.
fn speed(q: f64, inside: f64) -> f64 {
    let d = inside / 1000.0;
    let a = std::f64::consts::PI / 4.0 * d * d;
    q / 1000.0 / a
}

/// The head loss (m/m) by Darcy-Weisbach: 64/Re below Re 2300, else Colebrook's friction factor,
/// iterated from Swamee-Jain's until it settles.
fn head_loss(q: f64, inside: f64) -> f64 {
    let d = inside / 1000.0;
    let v = speed(q, inside);
    let re = v * d / NU;
    let f = if re < 2300.0 { 64.0 / re } else { colebrook(re, ROUGHNESS_MM / inside) };
    f / d * v * v / (2.0 * G)
}

fn colebrook(re: f64, rel: f64) -> f64 {
    let l = (rel / 3.7 + 5.74 / re.powf(0.9)).log10();
    let mut f = 0.25 / (l * l);
    for _ in 0..100 {
        let s = -2.0 * (rel / 3.7 + 2.51 / (re * f.sqrt())).log10();
        let next = 1.0 / (s * s);
        let d = (next - f).abs();
        f = next;
        if d < 1e-14 {
            break;
        }
    }
    f
}
