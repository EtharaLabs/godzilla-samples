//! `hydrant_size`: IT 22/2025 of the CBPMESP: hydrants and hose reels. The system type and the
//! fire reserve of Tabela 3 by the occupation's column and the built area; the flow of the two most
//! unfavourable jets of Tabela 2's type; and a pipe's speed, Hazen-Williams head loss (Tabela 1)
//! and the head needed at its start.

use super::drainage::args::{self, given, known, num, object, round};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;

/// Tabela 2: the type, its system, the flow of one jet (L/min), the hose's DN and length (mm, m)
/// and the head at the nozzle (mca).
const TYPES: &[(&str, &str, f64, f64, f64, f64)] = &[
    ("1", "1", 100.0, 25.0, 30.0, 80.0),
    ("2", "2", 150.0, 40.0, 30.0, 30.0),
    ("3", "3", 200.0, 40.0, 30.0, 40.0),
    ("4-40", "4", 300.0, 40.0, 30.0, 65.0),
    ("4-65", "4", 300.0, 65.0, 30.0, 30.0),
    ("5", "5", 600.0, 65.0, 30.0, 60.0),
];

/// Tabela 3: the built area's classes (m², up to) and, per column, the system and the reserve (m³).
const AREA_UP_TO: &[f64] = &[2500.0, 5000.0, 10000.0, 20000.0, 50000.0];
const TABLE3: &[[(&str, f64); 6]] = &[
    [("1", 5.0), ("1", 8.0), ("1", 12.0), ("1", 18.0), ("1", 25.0), ("1", 35.0)],
    [("2", 8.0), ("2", 12.0), ("2", 18.0), ("2", 25.0), ("2", 35.0), ("2", 48.0)],
    [("3", 12.0), ("3", 18.0), ("3", 25.0), ("3", 35.0), ("3", 48.0), ("3", 70.0)],
    [("4", 28.0), ("4", 32.0), ("4", 48.0), ("4", 64.0), ("4", 96.0), ("4", 120.0)],
    [("4", 32.0), ("4", 48.0), ("5", 64.0), ("5", 96.0), ("5", 120.0), ("5", 180.0)],
];

/// Tabela 1: Hazen-Williams' C by material.
const MATERIALS: &[(&str, f64)] = &[
    ("steel", 100.0),
    ("steel-wet", 120.0),
    ("copper", 150.0),
    ("pvc", 150.0),
    ("pex", 150.0),
];

const MAX_SPEED: f64 = 5.0;
const MAX_NOZZLE: f64 = 100.0;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = s;
    size(cid, p).map_err(args::clip)
}

fn size(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(
        cmd,
        &m,
        &["area", "column", "hydrants", "inside", "length", "material", "nominal", "region", "rise", "type"],
    )?;
    // the rule is São Paulo's: `region` may only say so
    match given(&m, "region") {
        None => {}
        Some(Value::Str(r)) if r.chars().count() <= 256 => {
            if r != "SP" {
                return Err(format!(
                    "{}: `region` must be SP: only IT 22/2025 of the Corpo de Bombeiros of São Paulo is covered, no other state's rule",
                    cmd
                ));
            }
        }
        Some(v) => {
            return Err(format!("{}: `region` must be text of at most 256 characters, got {}", cmd, v.to_compact()));
        }
    }
    let has_column = given(&m, "column").is_some();
    let has_area = given(&m, "area").is_some();
    if has_column && !has_area {
        return Err(format!("{}: `area` (m², built) is required with `column`", cmd));
    }
    if has_area && !has_column {
        return Err(format!("{}: `column` (1 to 5, of IT 22's Tabela 3) is required with `area`", cmd));
    }
    let column = whole(cmd, &m, "column", 1.0, 5.0)?;
    let area = num(cmd, &m, "area", f64::MIN_POSITIVE, 1e8)?;
    let ty = args::choice(cmd, &m, "type", &["1", "2", "3", "4-40", "4-65", "5"])?;
    if ty.is_none() && column.is_none() {
        return Err(format!("{}: `type` (1, 2, 3, 4-40, 4-65 or 5) or `column` and `area` is required", cmd));
    }
    let mut o = Map::new();
    let mut eff = ty.clone();
    if let (Some(c), Some(a)) = (column, area) {
        let class = AREA_UP_TO.iter().position(|up| a <= *up).unwrap_or(AREA_UP_TO.len());
        let (system, reserve) = TABLE3[c as usize - 1][class];
        o.insert("reserve_m3", Value::f(reserve));
        o.insert("system", Value::s(system));
        match &ty {
            Some(t) => {
                let ts = TYPES.iter().find(|x| x.0 == t).map(|x| x.1).unwrap_or("");
                if ts != system {
                    let cv = given(&m, "column").map(|v| v.to_compact()).unwrap_or_default();
                    return Err(format!(
                        "{}: `type` {} contradicts `column` {} and `area`, which give type {}: give one, or make them agree",
                        cmd, t, cv, system
                    ));
                }
            }
            None => {
                if system != "4" {
                    eff = Some(system.to_string());
                }
            }
        }
    }
    let Some(t) = eff else {
        if given(&m, "inside").is_some() {
            return Err(format!("{}: the system is type 4: give `type` as 4-40 or 4-65, by the nozzle", cmd));
        }
        return Ok(Value::Obj(o));
    };
    let hydrants = whole(cmd, &m, "hydrants", 1.0, 1000.0)?.unwrap_or(2.0);
    let &(name, _, jet, hose_dn, hose_len, nozzle) = TYPES.iter().find(|x| x.0 == t).expect("a type of the table");
    let jets = if hydrants < 2.0 { hydrants } else { 2.0 };
    let q = jet * jets;
    o.insert("flow_lpm", Value::f(q));
    o.insert("hose_dn_mm", Value::f(hose_dn));
    o.insert("hose_length_m", Value::f(hose_len));
    o.insert("nozzle_head_mca", Value::f(nozzle));
    o.insert("type", Value::s(name));
    let Some(inside) = num(cmd, &m, "inside", f64::MIN_POSITIVE, 5000.0)? else {
        if given(&m, "nominal").is_some() {
            return Err(format!("{}: `nominal` needs the pipe's `inside` diameter (mm)", cmd));
        }
        return Ok(Value::Obj(o));
    };
    let material = args::choice(cmd, &m, "material", &["steel", "steel-wet", "copper", "pvc", "pex"])?
        .unwrap_or_else(|| "steel".into());
    let length = num(cmd, &m, "length", 0.0, 1e9)?.unwrap_or(0.0);
    let rise = num(cmd, &m, "rise", -1e9, 1e9)?.unwrap_or(0.0);
    let nominal = num(cmd, &m, "nominal", f64::MIN_POSITIVE, 5000.0)?;
    let c = MATERIALS.iter().find(|x| x.0 == material).map(|x| x.1).unwrap_or(100.0);
    let d = inside / 1000.0;
    let speed = q / 60000.0 / (std::f64::consts::PI * (d * d) / 4.0);
    let j = 605.0 * q.powf(1.85) * c.powf(-1.85) * inside.powf(-4.87) * 1e4;
    let loss = j * (length / 1000.0);
    let need = nozzle + loss + rise / 1000.0;
    let speed_ok = speed <= MAX_SPEED + 1e-9;
    let mut ok = nozzle <= MAX_NOZZLE && speed_ok;
    o.insert("head_loss_m_per_m", Value::f(round(j, 5)));
    o.insert("loss_mca", Value::f(round(loss, 2)));
    o.insert(
        "need_covers",
        Value::s("nozzle head + head loss of the straight pipe + rise: not the hose, the fittings or the pressure at the source"),
    );
    o.insert("need_mca", Value::f(round(need, 2)));
    if let Some(n) = nominal {
        let least = if name == "1" || name == "2" { 50.0 } else { 65.0 };
        let size_ok = n >= least - 1e-9;
        ok = ok && size_ok;
        o.insert("size_ok", Value::Bool(size_ok));
    }
    o.insert("ok", Value::Bool(ok));
    o.insert(
        "ok_covers",
        Value::s("nozzle head within 100 mca, speed within 5 m/s and the pipe's size only: it is not a verdict on the design"),
    );
    o.insert("speed_ms", Value::f(round(speed, 2)));
    o.insert("speed_ok", Value::Bool(speed_ok));
    Ok(Value::Obj(o))
}

/// A whole number from `lo` to `hi`: a number out of range is named with its value, a fraction not.
fn whole(cmd: &str, m: &Map, key: &str, lo: f64, hi: f64) -> R<Option<f64>> {
    let Some(x) = num(cmd, m, key, lo, hi)? else { return Ok(None) };
    if x.fract() != 0.0 {
        return Err(format!("{}: `{}` must be a whole number from {} to {}", cmd, key, args::disp(lo), args::disp(hi)));
    }
    Ok(Some(x))
}
