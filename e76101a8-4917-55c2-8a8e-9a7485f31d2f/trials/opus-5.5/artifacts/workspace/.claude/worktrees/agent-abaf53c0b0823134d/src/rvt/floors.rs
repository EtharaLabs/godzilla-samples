//! Floors and ceilings: the sketch, the one type the reference list names, the level, the offset.

use super::build::{self, mm, r3};
use super::cats;
use super::import::Ctx;
use super::notes::Kind;
use super::plan::P;
use super::sketch::{self, SLine, Trace};
use super::types::{self, Layers};
use crate::json::Value;
use std::collections::BTreeMap;

pub const NOTE_LOOPS_FLOOR: &str = "its sketch is several separate loops: one floor for each";
pub const NOTE_OPEN: &str = "its sketch lines do not close: the ends that do not meet are joined by a straight line";
pub const NOTE_FAIL: &str =
    "its sketch lines close no boundary the reader can follow: it comes in as the footprint of its own box";
pub const NOTE_THIN: &str = "its type has no layers the reader can read: it comes in as thick as its own box";

pub fn pts_value(p: &[P]) -> Value {
    Value::Arr(p.iter().map(|q| Value::Arr(vec![Value::f(q[0]), Value::f(q[1])])).collect())
}

/// The boundaries a sketch gives: (outer, voids) each, and the notes on how.
pub fn boundaries(lines: &[SLine], bbox: &[f64; 6], word: &str, notes: &mut Vec<String>) -> Vec<(Vec<P>, Vec<Vec<P>>)> {
    match sketch::trace(lines) {
        Trace::Loops { loops, leftover } => {
            if !leftover.is_empty() {
                let mut left = leftover.clone();
                left.sort();
                let ids: Vec<String> = left.iter().map(|i| i.to_string()).collect();
                notes.push(format!(
                    "{} sketch {} close nothing and are left out (ids {})",
                    left.len(),
                    if left.len() == 1 { "line" } else { "lines" },
                    ids.join(", ")
                ));
            }
            if loops.len() > 1 {
                notes.push(format!("its sketch is several separate loops: one {} for each", word));
            }
            loops
        }
        Trace::Open(p) => {
            notes.push(NOTE_OPEN.into());
            vec![(p, Vec::new())]
        }
        Trace::Fail => {
            notes.push(NOTE_FAIL.into());
            vec![(sketch::footprint(bbox), Vec::new())]
        }
    }
}

/// A type with layers as BIMCraft keeps it (thickness and layers).
pub fn layered_type(ctx: &Ctx, ls: &[types::Layer], cat: i64, extra: Option<(&str, Value)>) -> (Value, f64) {
    let mut arr = Vec::new();
    let mut total = 0.0;
    for l in ls {
        total += l.width;
        arr.push(jobj! {
            "guid" => crate::rand::guid(),
            "function" => types::function_name(l.function).unwrap_or("structure"),
            "material" => ctx.material_guid(l.material, cat),
            "thickness" => mm(l.width),
        });
    }
    let t = mm(total);
    let mut v = jobj! {"thickness" => t};
    if let Some((k, x)) = extra {
        v.set(k, x);
    }
    v.set("layers", Value::Arr(arr));
    (v, t)
}

pub fn standin_type(t: f64, extra: Option<(&str, Value)>) -> Value {
    let mut v = jobj! {"thickness" => t};
    if let Some((k, x)) = extra {
        v.set(k, x);
    }
    v.set(
        "layers",
        Value::Arr(vec![jobj! {"guid" => crate::rand::guid(), "function" => "structure", "material" => "", "thickness" => t}]),
    );
    v
}

pub fn read(ctx: &mut Ctx, sketches: &BTreeMap<u64, Vec<SLine>>) {
    for (cat, word, tcat) in [(cats::OST_FLOORS, "floor", "floor"), (cats::OST_CEILINGS, "ceiling", "ceiling")] {
        let kind = Kind::simple(word);
        for r in ctx.instances(cat) {
            let b = match r.bbox {
                Some(b) => b,
                None => continue,
            };
            let lines = match sketches.get(&r.id) {
                Some(l) if !l.is_empty() => l.clone(),
                _ => {
                    ctx.notes.leave(&kind, "it has no sketch lines", r.id);
                    continue;
                }
            };
            let tid = match ctx.one_type(r, cat) {
                Some(t) => t,
                None => {
                    ctx.notes.leave(&kind, &format!("its record does not name one {} type", word), r.id);
                    continue;
                }
            };
            let (bottom, top) = (mm(b[2]), mm(b[5]));
            let lv = if cat == cats::OST_FLOORS { ctx.base_level(&r.refs, b[5]) } else { ctx.base_level(&r.refs, b[2]) };
            let level = match lv {
                Some(l) => l,
                None => {
                    ctx.notes.leave(&kind, super::walls::NO_LEVEL, r.id);
                    continue;
                }
            };
            let mut notes: Vec<String> = Vec::new();
            let loops = boundaries(&lines, &b, word, &mut notes);
            let box_h = r3(top - bottom);
            let extra = if word == "ceiling" { Some(("grid", Value::f(0.0))) } else { None };
            let (tv, tname, thick) = match ctx.type_layers(tid) {
                Layers::Read(ls) => {
                    let (v, t) = layered_type(ctx, &ls, cat, extra);
                    let name = ctx.type_name(tid).unwrap_or_else(|| format!("Imported - {}mm", t));
                    (v, name, t)
                }
                _ => {
                    notes.push(NOTE_THIN.into());
                    (standin_type(box_h, extra), format!("Imported - {}mm", box_h), box_h)
                }
            };
            if (box_h - thick).abs() > 1.0 {
                notes.push(format!(
                    "its box is {} mm tall and its type {} mm thick: it is sloped or stepped, and its slopes are not read: it comes in level",
                    box_h, thick
                ));
            }
            for n in &notes {
                ctx.notes.note(&kind, n, r.id);
            }
            let name = build::add_type(&mut ctx.pr, tcat, &tname, tv);
            let tg = ctx.lib_guid(&build::type_kind(tcat), &name);
            let lev = ctx.levels[level].elevation;
            for (outer, voids) in loops {
                let mut v = jobj! {
                    "guid" => crate::rand::guid(),
                    "category" => word,
                    "type" => tg.as_str(),
                    "level" => ctx.level_guid(level),
                    "boundary" => pts_value(&outer),
                };
                if !voids.is_empty() {
                    v.set("openings", Value::Arr(voids.iter().map(|p| pts_value(p)).collect()));
                }
                if word == "ceiling" {
                    v.set("offset", Value::f(r3(bottom - lev)));
                } else {
                    let o = r3(top - lev);
                    if o != 0.0 {
                        v.set("offset", Value::f(o));
                    }
                }
                ctx.add(r.id, if word == "floor" { "floor" } else { "ceiling" }, v);
            }
        }
    }
}
