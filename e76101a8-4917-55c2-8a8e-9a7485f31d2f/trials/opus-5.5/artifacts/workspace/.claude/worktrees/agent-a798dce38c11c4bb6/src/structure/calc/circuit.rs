//! `circuit`: NBR 5410:2004: one electrical circuit sized for copper.
//!
//! The design current I_B from the load (W, or VA with `apparent`) times its demand factor, over
//! the power factor, at the voltage of the phases (`FN` phase to neutral; `FF`, `3F`, `3FN` line
//! to line, three phases over √3); then, from the least section the use asks (and the one already
//! chosen) up, the first section whose current I_Z (Tabela 36 or 37 for the reference method of
//! Tabela 33 and the loaded conductors, times the temperature, grouping and soil factors) takes the
//! least breaker I_n ≥ I_B (and the one chosen), I_n ≤ I_Z, and whose drop is within the limit
//! (k·I_B·L·(R cos φ + X sin φ)/V, k 2 or √3, R at the insulation's working temperature, X 0.1
//! ohm/km). The neutral is the phase's (Tabela 48's reduced one on asking, three phases and
//! neutral only), the protective conductor Tabela 58's.

pub(super) mod args;
mod tables;

use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;
use args::{disp, flag, known, num, object, round2, word};
use tables::*;

const KEYS: &[&str] = &[
    "ambient",
    "apparent",
    "breaker",
    "bundle",
    "conductor",
    "demand",
    "drop_limit",
    "grouped",
    "insulation",
    "length",
    "load",
    "method",
    "phases",
    "power_factor",
    "reduced_neutral",
    "section",
    "soil",
    "spacing",
    "system",
    "use",
];

const PHASES: &[&str] = &["FN", "FF", "3F", "3FN"];
const SYSTEMS: &[&str] = &["127/220", "220/380", "230/400"];
/// (phase to neutral, line to line) of each system.
const VOLTS: [(f64, f64); 3] = [(127.0, 220.0), (220.0, 380.0), (230.0, 400.0)];
const USES: &[&str] = &["power", "lighting"];
const METHODS: &[&str] = &["1", "2", "3", "4", "5", "6", "7", "8", "11", "11A", "61", "61A"];
const INSULATIONS: &[&str] = &["pvc", "epr"];
const CONDUCTORS: &[&str] = &["flexible", "rigid"];

/// The comparisons' slack.
const EPS: f64 = 1e-9;

/// Tabela 33's methods taken: the reference method (A1, A2, B1, B2, C, D: 0 to 5) of each.
fn reference(method: &str) -> usize {
    match method {
        "1" => 0,
        "2" => 1,
        "3" | "5" | "7" => 2,
        "4" | "6" | "8" => 3,
        "11" | "11A" => 4,
        _ => 5,
    }
}

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = s;
    size(cid, p).map_err(args::clip)
}

/// What a section and breaker give: the current the section carries and the drop.
struct Inputs {
    ib: f64,
    volts: f64,
    three: bool,
    pf: f64,
    length: Option<f64>,
    flexible: bool,
    theta: f64,
    table: &'static [f64; 24],
    factors: (f64, f64, f64),
}

impl Inputs {
    fn carries(&self, i: usize) -> f64 {
        let (ft, fg, fs) = self.factors;
        self.table[i] * ft * fg * fs
    }
    fn drop(&self, i: usize) -> Option<f64> {
        let len = self.length?;
        let r20 = if self.flexible {
            if i < R20_FLEXIBLE.len() {
                R20_FLEXIBLE[i]
            } else {
                R20_RIGID[i] * 1.07
            }
        } else {
            R20_RIGID[i]
        };
        let r = r20 * (1.0 + 0.00393 * (self.theta - 20.0));
        let sin = (1.0 - self.pf * self.pf).sqrt();
        let k = if self.three { 3f64.sqrt() } else { 2.0 };
        Some(k * self.ib * (len / 1e6) * (r * self.pf + 0.1 * sin) / self.volts * 100.0)
    }
}

/// The place of a section or breaker given in its list (within 1e-9).
fn place(list: &[f64], x: f64) -> Option<usize> {
    list.iter().position(|v| (x - v).abs() <= EPS)
}

fn size(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(cmd, m, KEYS)?;
    let load = num(cmd, m, "load", 0.0, 1e9)?.unwrap_or(0.0);
    if load == 0.0 {
        return Err(format!("{}: `load` (W, or VA with `apparent`) is required", cmd));
    }
    let system = word(cmd, m, "system", SYSTEMS)?.unwrap_or(0);
    let section = chosen(cmd, m, "section", &SECTIONS, |list| {
        format!("{}: `section` must be one of the standard's: {}", cmd, list)
    })?;
    let breaker_given = num(cmd, m, "breaker", 0.0, 1000.0)?;
    let breaker = chosen(cmd, m, "breaker", &BREAKERS, |list| format!("{}: `breaker` must be one of: {}", cmd, list))?;
    let ambient = num(cmd, m, "ambient", -50.0, 200.0)?;
    let apparent = flag(cmd, m, "apparent")?.unwrap_or(false);
    let demand = num(cmd, m, "demand", f64::MIN_POSITIVE, 1.0)?.unwrap_or(1.0);
    let pf = num(cmd, m, "power_factor", f64::MIN_POSITIVE, 1.0)?.unwrap_or(1.0);
    let phases = word(cmd, m, "phases", PHASES)?.unwrap_or(0);
    let lighting = word(cmd, m, "use", USES)?.unwrap_or(0) == 1;
    let length = num(cmd, m, "length", 0.0, 1e9)?.filter(|l| *l != 0.0);
    let method = METHODS[word(cmd, m, "method", METHODS)?.unwrap_or(6)];
    let epr = word(cmd, m, "insulation", INSULATIONS)?.unwrap_or(0) == 1;
    let flexible = word(cmd, m, "conductor", CONDUCTORS)?.unwrap_or(0) == 0;
    let grouped = num(cmd, m, "grouped", 1.0, 1000.0)?.unwrap_or(1.0);
    let bundle = flag(cmd, m, "bundle")?.unwrap_or(false);
    let spacing = num(cmd, m, "spacing", 0.0, 100000.0)?.unwrap_or(0.0);
    let soil = num(cmd, m, "soil", 0.0, 100.0)?;
    let limit = num(cmd, m, "drop_limit", f64::MIN_POSITIVE, 100.0)?.unwrap_or(4.0);
    let reduced = flag(cmd, m, "reduced_neutral")?.unwrap_or(false);

    let r = reference(method);
    let buried = r == 5;
    let three = phases >= 2;
    let volts = if phases == 0 { VOLTS[system].0 } else { VOLTS[system].1 };
    let va = load * demand / if apparent { 1.0 } else { pf };
    let ib = va / (if three { 3f64.sqrt() } else { 1.0 } * volts);

    // Tabela 40
    let ambient = ambient.unwrap_or(if buried { 20.0 } else { 30.0 });
    let rows = match (buried, epr) {
        (false, false) => TEMP_AIR_PVC,
        (false, true) => TEMP_AIR_EPR,
        (true, false) => TEMP_SOIL_PVC,
        (true, true) => TEMP_SOIL_EPR,
    };
    let ft = if ambient < rows[0].0 { None } else { rows.iter().find(|(t, _)| ambient <= t + EPS).map(|(_, f)| *f) };
    let Some(ft) = ft else {
        return Err(format!(
            "{}: the temperature is under 10 degrees or above what the insulation allows (Tabela 40)",
            cmd
        ));
    };
    // Tabelas 42 and 45
    let n = grouped.round() as usize;
    let Some(fg) = grouping(method, n, bundle, spacing) else {
        return Err(format!("{}: Tabela 42 and 45 have no factor for that many circuits at that spacing", cmd));
    };
    // Tabela 41
    let fs = if buried {
        match soil {
            None => 1.0,
            Some(s) => {
                let f = if s < SOIL[0].0 { None } else { SOIL.iter().find(|(r, _)| s <= r + EPS).map(|(_, f)| *f) };
                match f {
                    Some(f) => f,
                    None => {
                        return Err(format!("{}: the soil's resistivity is outside Tabela 41 (1 to 3 K.m/W)", cmd))
                    }
                }
            }
        }
    } else {
        1.0
    };

    let loaded = if three { 1 } else { 0 };
    let table = if epr { &EPR[r][loaded] } else { &PVC[r][loaded] };
    let inp = Inputs {
        ib,
        volts,
        three,
        pf,
        length,
        flexible,
        theta: if epr { 90.0 } else { 70.0 },
        table,
        factors: (ft, fg, fs),
    };

    let min_section = if lighting { 1.5 } else { 2.5 };
    let min_i = place(&SECTIONS, min_section).unwrap_or(0);
    let start = min_i.max(section.map(|(_, i)| i).unwrap_or(0));
    let bmin = breaker.map(|(_, j)| j).unwrap_or(0);
    let mut found = None;
    for i in start..SECTIONS.len() {
        let iz = inp.carries(i);
        let Some(j) = (bmin..BREAKERS.len()).find(|&j| ib <= BREAKERS[j] + EPS) else { continue };
        if BREAKERS[j] > iz + EPS {
            continue;
        }
        let drop = inp.drop(i);
        if let Some(d) = drop {
            if d > limit + EPS {
                continue;
            }
        }
        found = Some((i, j, iz, drop));
        break;
    }
    let Some((i, j, iz, drop)) = found else {
        return Err(format!("{}: no conductor of the tables carries it: split the circuit", cmd));
    };

    let chosen_v = match section {
        None => Value::Null,
        Some((sv, ci)) => {
            let izc = inp.carries(ci);
            let dropc = inp.drop(ci);
            let mut c = Map::new();
            c.insert("breaker_a", Value::f(breaker_given.unwrap_or(0.0)));
            c.insert(
                "breaker_ok",
                match breaker {
                    None => Value::Null,
                    Some((_, bj)) => Value::Bool(ib <= BREAKERS[bj] + EPS && BREAKERS[bj] <= izc + EPS),
                },
            );
            c.insert("carries_a", Value::f(round2(izc)));
            c.insert("carries_ok", Value::Bool(ib <= izc + EPS));
            c.insert("drop_ok", dropc.map(|d| Value::Bool(d <= limit + EPS)).unwrap_or(Value::Null));
            c.insert("drop_percent", dropc.map(|d| Value::f(round2(d))).unwrap_or(Value::Null));
            c.insert("minimum_section_ok", Value::Bool(ci >= min_i));
            c.insert("section_mm2", Value::f(sv));
            Value::Obj(c)
        }
    };
    let grew = section.map(|(_, ci)| i > ci).unwrap_or(true) || breaker.map(|(_, bj)| j > bj).unwrap_or(true);

    let s = SECTIONS[i];
    let neutral = if reduced && phases == 3 { reduced_neutral(s) } else { s };
    let pe = protective(s);
    let conductors = match phases {
        0 => format!("1 × {} + N {} + PE {} mm²", disp(s), disp(neutral), disp(pe)),
        1 => format!("2 × {} + PE {} mm²", disp(s), disp(pe)),
        2 => format!("3 × {} + PE {} mm²", disp(s), disp(pe)),
        _ => format!("3 × {} + N {} + PE {} mm²", disp(s), disp(neutral), disp(pe)),
    };

    let mut out = Map::new();
    out.insert("breaker_a", Value::f(BREAKERS[j]));
    out.insert("carries_a", Value::f(round2(iz)));
    out.insert("chosen", chosen_v);
    out.insert("conductors", Value::s(&conductors));
    out.insert("current_a", Value::f(round2(ib)));
    out.insert("drop_percent", drop.map(|d| Value::f(round2(d))).unwrap_or(Value::Null));
    out.insert("factors", crate::jobj! { "grouping" => fg, "soil" => fs, "temperature" => ft });
    out.insert("grew", Value::Bool(grew));
    out.insert("minimum_section_mm2", Value::f(min_section));
    out.insert("section_mm2", Value::f(s));
    out.insert("volts", Value::f(volts));
    Ok(Value::Obj(out))
}

/// Tabela 58: the protective conductor of a phase of `s` mm² (the phase's up to 16, 16 up to 35,
/// then half the phase, the next section of the tables up).
pub(super) fn protective(s: f64) -> f64 {
    if s <= 16.0 {
        s
    } else if s <= 35.0 {
        16.0
    } else {
        SECTIONS.iter().copied().find(|x| *x >= s / 2.0 - EPS).unwrap_or(s)
    }
}

/// Tabela 48: the reduced neutral of a phase of `s` mm² (the phase's where the table has none).
pub(super) fn reduced_neutral(s: f64) -> f64 {
    REDUCED_NEUTRAL.iter().find(|(p, _)| (s - p).abs() <= EPS).map(|(_, n)| *n).unwrap_or(s)
}

/// A section or breaker already chosen: (as given, its place in the list); 0 is none.
fn chosen(
    cmd: &str,
    m: &Map,
    key: &str,
    list: &[f64],
    refuse: impl Fn(String) -> String,
) -> R<Option<(f64, usize)>> {
    match num(cmd, m, key, 0.0, 1000.0)? {
        None => Ok(None),
        Some(x) if x == 0.0 => Ok(None),
        Some(x) => match place(list, x) {
            Some(i) => Ok(Some((x, i))),
            None => Err(refuse(list.iter().map(|v| disp(*v)).collect::<Vec<_>>().join(", "))),
        },
    }
}

/// Tabelas 42 and 45: the grouping factor of `n` circuits laid by the method.
fn grouping(method: &str, n: usize, bundle: bool, spacing: f64) -> Option<f64> {
    let row = |t: &[f64]| t[(n.max(1) - 1).min(t.len() - 1)];
    match method {
        "61" | "61A" => {
            if n <= 1 {
                return Some(1.0);
            }
            if n > 6 {
                return None;
            }
            let s = spacing / 1000.0;
            if s > BURIED_SPACINGS[3] + EPS {
                return None;
            }
            let col = BURIED_SPACINGS.iter().rposition(|c| s + EPS >= *c).unwrap_or(0);
            let t = if method == "61" { &BURIED_MULTI } else { &BURIED_SINGLE };
            Some(t[n - 2][col])
        }
        "11" if !bundle => Some(row(&GROUP_WALL)),
        "11A" if !bundle => Some(row(&GROUP_CEILING)),
        _ => {
            let k = match n {
                0..=8 => n.max(1) - 1,
                9..=11 => 8,
                12..=15 => 9,
                16..=19 => 10,
                _ => 11,
            };
            Some(GROUP_BUNDLE[k])
        }
    }
}
