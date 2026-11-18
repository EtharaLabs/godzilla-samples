//! `drain_size, vent_size`: NBR 8160: sanitary drains and vents, by the fixture units (UHC) they
//! carry, with the standard's own tables (recovered from the original's answers).

pub mod args;

use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;
use args::{disp, given, known, num, object};

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    let _ = s;
    match cid {
        "vent_size" => vent(cid, p),
        _ => drain(cid, p),
    }
    .map_err(args::clip)
}

/// Tabela 3: a fixture's units (UHC) and the smallest DN of its own drain, in the order the
/// original names them.
const FIXTURES: &[(&str, f64, f64)] = &[
    ("wc", 6.0, 100.0),
    ("lav", 1.0, 40.0),
    ("sink", 3.0, 50.0),
    ("shower", 2.0, 40.0),
    ("laundry", 3.0, 40.0),
];

/// Tabela 5: branches (ramais de esgoto): DN and the most UHC.
const BRANCH: &[(f64, f64)] = &[(40.0, 3.0), (50.0, 6.0), (75.0, 20.0), (100.0, 160.0)];

/// Tabela 6: stacks (tubos de queda), a building of up to three floors and of more.
const STACK_LOW: &[(f64, f64)] = &[
    (40.0, 4.0),
    (50.0, 10.0),
    (75.0, 30.0),
    (100.0, 240.0),
    (150.0, 960.0),
    (200.0, 2200.0),
    (250.0, 3800.0),
    (300.0, 6000.0),
];
const STACK_HIGH: &[(f64, f64)] = &[
    (40.0, 8.0),
    (50.0, 24.0),
    (75.0, 70.0),
    (100.0, 500.0),
    (150.0, 1900.0),
    (200.0, 3600.0),
    (250.0, 5600.0),
    (300.0, 8400.0),
];

/// Tabela 7: building drains and collectors (subcoletores, coletor predial) by slope; a blank
/// (not allowed) is left out.
const MAIN_SLOPES: &[(f64, &[(f64, f64)])] = &[
    (0.005, &[(200.0, 1400.0), (250.0, 2500.0), (300.0, 3900.0), (400.0, 7000.0)]),
    (0.01, &[(100.0, 180.0), (150.0, 700.0), (200.0, 1600.0), (250.0, 2900.0), (300.0, 4600.0), (400.0, 8300.0)]),
    (0.02, &[(100.0, 216.0), (150.0, 840.0), (200.0, 1920.0), (250.0, 3500.0), (300.0, 5600.0), (400.0, 10000.0)]),
    (0.04, &[(100.0, 250.0), (150.0, 1000.0), (200.0, 2300.0), (250.0, 4200.0), (300.0, 6700.0), (400.0, 12000.0)]),
];

/// Tabela 8: branch vents (ramais de ventilação): without and with a water closet in the group.
const VENT_NO_WC: &[(f64, f64)] = &[(40.0, 12.0), (50.0, 18.0), (75.0, 36.0)];
const VENT_WC: &[(f64, f64)] = &[(50.0, 17.0), (75.0, 60.0)];

/// Tabela 2: vent stacks and headers, by the DN served: rows of (most UHC, [(vent DN, longest m)]).
type VentRow = (f64, &'static [(f64, f64)]);
const VENT_STACKS: &[(f64, &[VentRow])] = &[
    (40.0, &[(8.0, &[(40.0, 46.0)]), (10.0, &[(40.0, 30.0)])]),
    (50.0, &[(12.0, &[(40.0, 23.0), (50.0, 61.0)]), (20.0, &[(40.0, 15.0), (50.0, 46.0)])]),
    (
        75.0,
        &[
            (10.0, &[(40.0, 13.0), (50.0, 46.0), (75.0, 317.0)]),
            (21.0, &[(40.0, 10.0), (50.0, 33.0), (75.0, 247.0)]),
            (53.0, &[(40.0, 8.0), (50.0, 29.0), (75.0, 207.0)]),
            (102.0, &[(40.0, 8.0), (50.0, 26.0), (75.0, 189.0)]),
        ],
    ),
    (
        100.0,
        &[
            (43.0, &[(50.0, 11.0), (75.0, 76.0), (100.0, 299.0)]),
            (140.0, &[(50.0, 8.0), (75.0, 61.0), (100.0, 229.0)]),
            (320.0, &[(50.0, 7.0), (75.0, 52.0), (100.0, 195.0)]),
            (530.0, &[(50.0, 6.0), (75.0, 46.0), (100.0, 177.0)]),
        ],
    ),
    (
        150.0,
        &[
            (500.0, &[(75.0, 10.0), (100.0, 40.0), (150.0, 305.0)]),
            (1100.0, &[(75.0, 8.0), (100.0, 31.0), (150.0, 238.0)]),
            (2000.0, &[(75.0, 7.0), (100.0, 26.0), (150.0, 201.0)]),
            (2900.0, &[(75.0, 6.0), (100.0, 23.0), (150.0, 183.0)]),
        ],
    ),
    (
        200.0,
        &[
            (1800.0, &[(100.0, 10.0), (150.0, 73.0), (200.0, 286.0)]),
            (3400.0, &[(100.0, 7.0), (150.0, 57.0), (200.0, 219.0)]),
            (5600.0, &[(100.0, 6.0), (150.0, 49.0), (200.0, 186.0)]),
            (7600.0, &[(100.0, 5.0), (150.0, 43.0), (200.0, 171.0)]),
        ],
    ),
    (
        250.0,
        &[
            (4000.0, &[(150.0, 24.0), (200.0, 94.0), (250.0, 293.0)]),
            (7200.0, &[(150.0, 18.0), (200.0, 73.0), (250.0, 225.0)]),
            (11000.0, &[(150.0, 16.0), (200.0, 60.0), (250.0, 192.0)]),
            (15000.0, &[(150.0, 14.0), (200.0, 55.0), (250.0, 174.0)]),
        ],
    ),
    (
        300.0,
        &[
            (7300.0, &[(150.0, 9.0), (200.0, 37.0), (250.0, 116.0), (300.0, 287.0)]),
            (13000.0, &[(150.0, 7.0), (200.0, 29.0), (250.0, 90.0), (300.0, 219.0)]),
            (20000.0, &[(150.0, 6.0), (200.0, 24.0), (250.0, 76.0), (300.0, 186.0)]),
            (26000.0, &[(150.0, 5.0), (200.0, 22.0), (250.0, 70.0), (300.0, 152.0)]),
        ],
    ),
    (400.0, &[]),
];

/// Tabela 1: a trap's DN and the longest run from it to its vent (mm).
const TRAPS: &[(f64, f64)] = &[(40.0, 1000.0), (50.0, 1200.0), (75.0, 1800.0), (100.0, 2400.0)];

/// The tolerance the original matches a DN with.
const EPS: f64 = 1e-9;

fn same_dn(x: f64, dn: f64) -> bool {
    (x - dn).abs() <= EPS
}

fn drain(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(cmd, &m, &["fixtures", "floors", "min_dn", "role", "slope", "units"])?;
    let units = num(cmd, &m, "units", 0.0, 1e7)?.unwrap_or(0.0);
    let min_dn = num(cmd, &m, "min_dn", 0.0, 1000.0)?.unwrap_or(0.0);
    let (fix_units, fix_dn) = fixtures(cmd, &m)?;
    let total = units + fix_units;
    if total <= 0.0 {
        return Err(format!("{}: `units` (UHC) or `fixtures` is required", cmd));
    }
    let role = args::choice(cmd, &m, "role", &["branch", "main", "stack"])?.unwrap_or_else(|| "branch".into());
    let slope = num(cmd, &m, "slope", 0.0, 1.0)?.unwrap_or(0.01);
    let floors = num(cmd, &m, "floors", 1.0, 1000.0)?.unwrap_or(1.0);
    // the larger of the two, +0 over -0 (as f64::max does)
    let minimum = if min_dn > fix_dn { min_dn } else { fix_dn };
    let table: &[(f64, f64)] = match role.as_str() {
        "main" => MAIN_SLOPES
            .iter()
            .rev()
            .find(|(s, _)| slope + EPS >= *s)
            .map(|(_, t)| *t)
            .unwrap_or(&[]),
        "stack" => {
            if floors.round() > 3.0 {
                STACK_HIGH
            } else {
                STACK_LOW
            }
        }
        _ => BRANCH,
    };
    match table.iter().find(|(dn, cap)| total <= *cap && *dn + EPS >= minimum) {
        Some((dn, cap)) => {
            let mut o = Map::new();
            o.insert("capacity", Value::f(*cap));
            o.insert("dn", Value::f(*dn));
            o.insert("minimum_dn", Value::f(minimum));
            o.insert("units", Value::f(total));
            Ok(Value::Obj(o))
        }
        None => {
            let (dn, cap) = table.last().copied().unwrap_or((0.0, 0.0));
            Err(format!(
                "{}: {} UHC is more than the tables of this version list for this role and slope: the most is DN {} at {} UHC (a blank in the standard's table means not allowed, not that the tables ended); split the load, or give a steeper `slope`",
                cmd,
                disp(total),
                disp(dn),
                disp(cap)
            ))
        }
    }
}

/// The fixtures counted: their units and the largest of their own drains' DN.
fn fixtures(cmd: &str, m: &Map) -> R<(f64, f64)> {
    let Some(v) = given(m, "fixtures") else { return Ok((0.0, 0.0)) };
    let Value::Obj(f) = v else {
        return Err(format!("{}: `fixtures` must be an object {{kind: count}}, got {}", cmd, v.to_compact()));
    };
    let mut units = 0.0;
    let mut dn: f64 = 0.0;
    for (k, c) in f.iter() {
        let Some((_, u, d)) = FIXTURES.iter().find(|(n, _, _)| n == k) else {
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
        units += n * u;
        if n > 0.0 && *d > dn {
            dn = *d;
        }
    }
    Ok((units, dn))
}

fn vent(cmd: &str, p: &Value) -> R<Value> {
    let m = object(cmd, p)?;
    known(cmd, &m, &["length", "stack_dn", "trap_dn", "units", "wc"])?;
    let units = num(cmd, &m, "units", 0.0, 1e7)?.unwrap_or(0.0);
    if units <= 0.0 {
        return Err(format!("{}: `units` (UHC of what it vents) is required", cmd));
    }
    let stack_dn = num(cmd, &m, "stack_dn", 0.0, 1000.0)?;
    let mut o = Map::new();
    if let Some(sd) = stack_dn {
        let Some((_, rows)) = VENT_STACKS.iter().find(|(dn, _)| same_dn(sd, *dn)) else {
            return Err(format!("{}: `stack_dn` must be one of 40, 50, 75, 100, 150, 200, 250, 300, 400", cmd));
        };
        let Some(length) = num(cmd, &m, "length", 0.0, 1e9)? else {
            return Err(format!("{}: `length` (mm, from the foot to the open end) is required with `stack_dn`", cmd));
        };
        let len_m = length / 1000.0;
        let found = rows
            .iter()
            .find(|(most, _)| units <= *most)
            .and_then(|(_, vents)| vents.iter().find(|(_, longest)| len_m <= *longest + EPS));
        let Some((dn, longest)) = found else {
            return Err(format!(
                "{}: no vent of the table (Tabela 2) is long enough for that, or the units pass its last row",
                cmd
            ));
        };
        o.insert("dn", Value::f(*dn));
        o.insert("longest_m", Value::f(*longest));
    } else {
        let wc = args::boolean(cmd, &m, "wc")?.unwrap_or(false);
        let table = if wc { VENT_WC } else { VENT_NO_WC };
        let Some((dn, _)) = table.iter().find(|(_, most)| units <= *most) else {
            return Err(format!("{}: {} UHC is more than the table gives a branch vent (Tabela 8)", cmd, disp(units)));
        };
        o.insert("dn", Value::f(*dn));
    }
    if let Some(t) = num(cmd, &m, "trap_dn", 0.0, 1000.0)? {
        let Some((_, run)) = TRAPS.iter().find(|(dn, _)| same_dn(t, *dn)) else {
            return Err(format!("{}: `trap_dn` must be 40, 50, 75 or 100 (Tabela 1)", cmd));
        };
        o.insert("trap_to_vent_mm", Value::f(*run));
    }
    Ok(Value::Obj(o))
}
