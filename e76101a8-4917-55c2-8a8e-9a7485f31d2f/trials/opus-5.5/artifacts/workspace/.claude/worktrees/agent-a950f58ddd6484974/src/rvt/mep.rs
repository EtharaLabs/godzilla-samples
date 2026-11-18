//! Pipes, ducts and cable trays: a pipe between its two connectors, as wide as its box says
//! across it; a duct or a tray along its line, with the section its record gives.

use super::build::{self, mm, r3};
use super::bytes::*;
use super::cats;
use super::curves::{self, MARK};
use super::import::Ctx;
use super::notes::Kind;
use super::records::Record;
use crate::json::Value;

pub const NOTE_PIPE: &str = "its diameter is the outside diameter its box gives; its system, type name and material are not read";
pub const NOTE_DUCT: &str = "its system, type name and material are not read, and it is not turned about its line";

type P3 = [f64; 3];

/// A pipe's connectors in its data: `01 00 00 00`, the point (feet), a number, `03 00 00 00`,
/// the connector's index and `ff ff ff ff`. Gives the points of connectors 0 and 1.
fn connectors(d: &[u8]) -> Option<(P3, P3)> {
    let mut found: [Option<P3>; 2] = [None, None];
    let mut q = 0;
    while let Some(k) = find(d, &[3, 0, 0, 0], q, d.len()) {
        q = k + 1;
        if k < 36 || rd_u32(d, k - 36) != Some(1) || rd_u32(d, k + 8) != Some(u32::MAX) {
            continue;
        }
        let idx = match rd_u32(d, k + 4) {
            Some(i) if i < 2 => i as usize,
            _ => continue,
        };
        let mut p = [0f64; 3];
        let mut ok = true;
        for (j, x) in p.iter_mut().enumerate() {
            match rd_f64(d, k - 32 + 8 * j) {
                Some(v) if v.is_finite() && v.abs() <= curves::MAX_FEET => *x = v,
                _ => ok = false,
            }
        }
        if ok && found[idx].is_none() {
            found[idx] = Some(p);
        }
    }
    Some((found[0]?, found[1]?))
}

/// A pipe's diameter (feet) from its box: across each axis it does not run mostly along, the
/// box's extent less the pipe's own, square to the pipe; their mean.
fn diameter(b: &[f64; 6], a: P3, e: P3) -> Option<f64> {
    let v = [e[0] - a[0], e[1] - a[1], e[2] - a[2]];
    let len = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
    if !(len > 0.0) {
        return None;
    }
    let mut sum = 0.0;
    let mut n = 0;
    for k in 0..3 {
        let dk = (v[k] / len).abs();
        if dk < 0.8 {
            sum += (b[k + 3] - b[k] - len * dk) / (1.0 - dk * dk).sqrt();
            n += 1;
        }
    }
    let d = sum / n as f64;
    if d.is_finite() && d > 0.001 && d < 20.0 {
        Some(d)
    } else {
        None
    }
}

/// A duct's or a tray's section (feet) and line: the width and height 48 bytes into its data,
/// the first curve record as a line.
fn run_of(d: &[u8]) -> Option<(f64, f64, P3, P3)> {
    let w = rd_f64(d, 48)?;
    let h = rd_f64(d, 56)?;
    let ok = |x: f64| x.is_finite() && x > 0.001 && x <= 30.0;
    if !ok(w) || !ok(h) {
        return None;
    }
    let p = find(d, &MARK, 0, d.len())?;
    let l = curves::line_at(d, p)?;
    Some((w, h, l.start, l.end))
}

fn fmt1(x: f64) -> String {
    format!("{:.1}", x)
}

pub fn read(ctx: &mut Ctx) {
    for (cat, jcat, kind) in [
        (cats::OST_PIPES, "pipe", Kind::simple("pipe")),
        (cats::OST_DUCTS, "duct", Kind::simple("duct")),
        (cats::OST_CABLE_TRAYS, "cabletray", Kind::simple("cable tray")),
    ] {
        for r in ctx.instances(cat) {
            match read_one(ctx, r, jcat) {
                Ok(Some(note)) => ctx.notes.note(&kind, note, r.id),
                Ok(None) => {}
                Err(reason) => ctx.notes.leave(&kind, reason, r.id),
            }
        }
    }
}

fn read_one(ctx: &mut Ctx, r: &Record, jcat: &'static str) -> Result<Option<&'static str>, &'static str> {
    let b = match r.bbox {
        Some(b) => b,
        None => return Ok(None),
    };
    if !(b[3] > b[0] && b[4] > b[1] && b[5] > b[2]) {
        return Ok(None);
    }
    let (a, e, tname, tv, note) = if jcat == "pipe" {
        let (a, e) = ctx.first_data(r.id, connectors).ok_or("its two connectors are not in the record")?;
        let d = diameter(&b, a, e).ok_or("its diameter cannot be worked out from its box")?;
        let dm = mm(d);
        (a, e, format!("Pipe {} mm", fmt1(dm)), jobj! {"width" => dm, "depth" => dm, "round" => true}, NOTE_PIPE)
    } else {
        let (w, h, a, e) = ctx.first_data(r.id, run_of).ok_or("its line and section are not in the record")?;
        let (wm, hm) = (mm(w), mm(h));
        let (name, round) = if jcat == "cabletray" {
            (format!("Cable tray {} x {} mm", fmt1(wm), fmt1(hm)), false)
        } else if w == h {
            (format!("Round duct {} mm", fmt1(wm)), true)
        } else {
            (format!("Duct {} x {} mm", fmt1(wm), fmt1(hm)), false)
        };
        (a, e, name, jobj! {"width" => wm, "depth" => hm, "round" => round}, NOTE_DUCT)
    };
    let (z0, z1) = (mm(a[2]), mm(e[2]));
    let level = ctx.level_at(a[2]).ok_or(super::walls::NO_LEVEL)?;
    let name = build::add_type_once(&mut ctx.pr, jcat, &tname, tv);
    let tg = ctx.lib_guid(&format!("type:{}", jcat), &name);
    let lev = ctx.levels[level].elevation;
    let mut v = jobj! {
        "guid" => crate::rand::guid(),
        "category" => jcat,
        "type" => tg,
        "level" => ctx.level_guid(level),
        "start" => Value::Arr(vec![Value::f(mm(a[0])), Value::f(mm(a[1]))]),
        "end" => Value::Arr(vec![Value::f(mm(e[0])), Value::f(mm(e[1]))]),
        "offset" => r3(z0 - lev),
    };
    if z1 != z0 {
        v.set("end_offset", Value::f(r3(z1 - lev)));
    }
    v.set("justify", Value::s("centre"));
    ctx.add(r.id, jcat, v);
    Ok(Some(note))
}
