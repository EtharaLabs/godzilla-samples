//! Columns, architectural and structural: the rectangle of the box, levels and height as a
//! wall's, the type by its symbol's name entry. A column turned off the axes comes in at its
//! placement, turned, as large as its symbol's box.

use super::build::{self, mm, r3};
use super::bytes::*;
use super::cats;
use super::curves::MAX_FEET;
use super::import::Ctx;
use super::notes::Kind;
use super::openings;
use super::records::Record;
use crate::json::Value;

pub const NOTE_BOX: &str = "comes in as the rectangle of its box: the shape of its section is not read";
pub const NOTE_TURNED: &str = "it is turned, and its family symbol's size is not known: it comes in as its box, turned";

/// How far a placement's axes may be from a turn in plan.
const TOL: f64 = 1e-9;

fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

/// A family instance's placement at the start of its data: a rotation in plan (nine numbers,
/// row by row) and an origin (feet). Gives the angle in degrees and the origin.
pub fn placement(d: &[u8]) -> Option<(f64, [f64; 3])> {
    let mut m = [0f64; 12];
    for (k, x) in m.iter_mut().enumerate() {
        *x = rd_f64(d, 8 * k)?;
        if !x.is_finite() {
            return None;
        }
    }
    let o = [m[9], m[10], m[11]];
    if o.iter().any(|v| v.abs() > MAX_FEET) {
        return None;
    }
    // the axes (the matrix's columns): orthonormal, right-handed, z up and x, y in plan
    let x = [m[0], m[3], m[6]];
    let y = [m[1], m[4], m[7]];
    let z = [m[2], m[5], m[8]];
    for (a, b, want) in [(x, x, 1.0), (y, y, 1.0), (z, z, 1.0), (x, y, 0.0), (x, z, 0.0), (y, z, 0.0)] {
        if (dot(a, b) - want).abs() > TOL {
            return None;
        }
    }
    if m[6].abs() > TOL || m[7].abs() > TOL || m[8] <= 0.0 {
        return None;
    }
    let cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]];
    if dot(cross, z) <= 0.0 {
        return None;
    }
    Some((m[3].atan2(m[0]).to_degrees(), o))
}

/// Whether an angle (degrees) is a whole number of quarter turns.
fn square(deg: f64) -> bool {
    let q = deg / 90.0;
    (q - q.round()).abs() < 1e-6
}

/// The column's z-range from its geometry node (from 2024, where its record's box begins at
/// zero): its id, 3 and -1, after two boxes.
fn node_z(ctx: &Ctx, id: u64) -> Option<(f64, f64)> {
    let mut key = id.to_le_bytes().to_vec();
    key.extend_from_slice(&3u64.to_le_bytes());
    key.extend_from_slice(&[0xff; 8]);
    for pi in ctx.doc.parts_newest_first() {
        let d = &ctx.doc.parts[pi].data;
        if let Some(q) = find(d, &key, 96, d.len()) {
            let z0 = rd_f64(d, q - 96 + 16)?;
            let z1 = rd_f64(d, q - 96 + 40)?;
            if z0.is_finite() && z1.is_finite() && z1 > z0 {
                return Some((z0, z1));
            }
        }
    }
    None
}

pub fn read(ctx: &mut Ctx) {
    let kind = Kind::simple("column");
    for (cat, tcat, jcat) in [
        (cats::OST_COLUMNS, "column", "column"),
        (cats::OST_STRUCTURAL_COLUMNS, "structural_column", "structuralcolumn"),
    ] {
        for r in ctx.instances(cat) {
            match read_one(ctx, r, cat, tcat, jcat) {
                Ok(Some(notes)) => {
                    for n in notes {
                        ctx.notes.note(&kind, n, r.id);
                    }
                }
                Ok(None) => {}
                Err(reason) => ctx.notes.leave(&kind, &reason, r.id),
            }
        }
    }
}

fn read_one(ctx: &mut Ctx, r: &Record, cat: i64, tcat: &str, jcat: &'static str) -> Result<Option<Vec<&'static str>>, String> {
    let b = match r.bbox {
        Some(b) => b,
        None => return Ok(None),
    };
    if !(b[3] > b[0] && b[4] > b[1] && b[5] > b[2]) {
        return Ok(None);
    }
    let (mut z0, mut z1) = (b[2], b[5]);
    if ctx.doc.wide() && b[2] == 0.0 {
        if let Some((a, c)) = node_z(ctx, r.id) {
            z0 = a;
            z1 = c;
        }
    }
    let bottom = mm(z0);
    let top = mm(z1);
    let level = ctx.base_level(&r.refs, z0).ok_or_else(|| super::walls::NO_LEVEL.to_string())?;
    let top_level = ctx.top_level(&r.refs, level, z1);
    let mut notes = vec![NOTE_BOX];
    let (sym, name) = openings::symbol(ctx, r, cat);
    let mut w = r3(mm(b[3]) - mm(b[0]));
    let mut d = r3(mm(b[4]) - mm(b[1]));
    let mut at = [r3((b[0] + b[3]) / 2.0 * 304.8), r3((b[1] + b[4]) / 2.0 * 304.8)];
    let mut angle = 0.0;
    if let Some((deg, o)) = ctx.data(r.id).and_then(placement) {
        if !square(deg) {
            // kept as read: a turn just short of zero is -0.0
            angle = (deg * 1000.0).round() / 1000.0;
            at = [mm(o[0]), mm(o[1])];
            let size = if name.is_some() { sym.and_then(|s| symbol_size(ctx, s)) } else { None };
            match size {
                Some((sw, sd)) => {
                    w = sw;
                    d = sd;
                }
                None => notes.push(NOTE_TURNED),
            }
        }
    }
    let tname = name.unwrap_or_else(|| "Imported column".to_string());
    let tv = jobj! {"width" => w, "depth" => d, "round" => false};
    let tname = build::add_type(&mut ctx.pr, tcat, &tname, tv);
    let tg = ctx.lib_guid(&build::type_kind(tcat), &tname);
    let lev = ctx.levels[level].elevation;
    let v = jobj! {
        "guid" => crate::rand::guid(),
        "category" => jcat,
        "type" => tg,
        "level" => ctx.level_guid(level),
        "at" => Value::Arr(vec![Value::f(at[0]), Value::f(at[1])]),
        "angle" => angle,
        "top_level" => match top_level { Some(t) => ctx.level_guid(t), None => Value::Null },
        "height" => r3(top - bottom),
        "base_offset" => r3(bottom - lev),
    };
    ctx.add(r.id, jcat, v);
    Ok(Some(notes))
}

/// A family symbol's size: the plan extents of its record's box.
fn symbol_size(ctx: &Ctx, sym: u64) -> Option<(f64, f64)> {
    let b = ctx.record(sym)?.bbox?;
    Some((r3(mm(b[3]) - mm(b[0])), r3(mm(b[4]) - mm(b[1]))))
}
