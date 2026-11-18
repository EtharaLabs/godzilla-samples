//! `load_points`: NBR 5410:2004 item 9.5.2: a dwelling's lighting and general-use outlets.
//!
//! Each room has a ceiling lighting point of 100 VA up to 6 m², 60 VA more for each whole 4 m²
//! above; and general-use outlets (TUG) by its kind: a bathroom 1, a kitchen (pantry) or service
//! area (laundry) one for each 3.5 m of perimeter, a room or bedroom one for each 5 m, a veranda 1,
//! the others 1 up to 6 m² and one for each 5 m above; 600 VA each for the first 3 in a
//! bathroom, kitchen or service area (the first 2 by the alternative, where those rooms have more
//! than 6 points together) and 100 VA for the others. The rooms are given, or the model's,
//! measured inside the walls' finish.

mod kinds;
mod rooms;

use super::circuit::args::{clip, flag, given, num};
use crate::json::{Map, Value};
use crate::session::Session;
use crate::structure::common::R;

const NOT_COVERED: &str = "the exceptions to the lighting point and to a veranda's outlet, the placement of the outlets (near the lavatory, over a counter, up to 0.80 m outside the door of a room of 2.25 m² or less) and the TUE";
const KINDS: &[&str] = &["bath", "kitchen", "service", "dry", "veranda", "other"];
const ROOM_KEYS: &[&str] = &["area", "kind", "name", "perimeter", "points"];

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    // a room's own reading refuses it clipped, then says which room
    points(s, cid, p).map_err(|e| if e.starts_with("rooms[") { e } else { clip(e) })
}

/// A room as the rules read it: its name, kind (and whether the name gave it), area (m²),
/// perimeter (m) and the outlets it has.
struct Room {
    name: String,
    kind: &'static str,
    named: bool,
    area: f64,
    perimeter: f64,
    points: Option<u64>,
}

fn points(s: &mut Session, cmd: &str, p: &Value) -> R<Value> {
    let m = p.as_obj().ok_or_else(|| format!("{}: params must be an object", cmd))?;
    let mut keys: Vec<&String> = m.keys().collect();
    keys.sort();
    for k in keys {
        if k != "rooms" && k != "alternative" {
            return Err(format!("{}: `{}` isn't one of its parameters: rooms, alternative", cmd, k));
        }
    }
    let alternative = flag(cmd, m, "alternative")?.unwrap_or(false);
    let mut list = Vec::new();
    let mut skipped = Vec::new();
    match given(m, "rooms") {
        None => {
            let (found, left) = rooms::model_rooms(&s.project);
            for (name, area, perimeter) in found {
                list.push(room_of(name, None, area, perimeter, None));
            }
            skipped = left;
        }
        Some(v) => {
            let arr = match v {
                Value::Arr(a) if a.len() <= 5000 => a,
                _ => {
                    return Err(format!(
                        "{}: `rooms` must be a list of at most 5000 rooms, got {}",
                        cmd,
                        v.to_compact()
                    ))
                }
            };
            for (i, r) in arr.iter().enumerate() {
                list.push(read_room(cmd, i, r)?);
            }
        }
    }
    Ok(report(list, skipped, alternative))
}

/// One room of `rooms`, read with the original's texts and in its order.
fn read_room(cmd: &str, i: usize, r: &Value) -> R<Room> {
    let m = r.as_obj().ok_or_else(|| format!("{}: rooms[{}] must be an object", cmd, i))?;
    let mut keys: Vec<&String> = m.keys().collect();
    keys.sort();
    for k in keys {
        if !ROOM_KEYS.contains(&k.as_str()) {
            return Err(format!("{}: rooms[{}]: unknown parameter `{}`", cmd, i, k));
        }
    }
    let at = |e: String| format!("rooms[{}]: {}", i, clip(e));
    let name = match given(m, "name") {
        None => String::new(),
        Some(Value::Str(s)) if s.chars().count() <= 256 => s.clone(),
        Some(v) => {
            return Err(at(format!(
                "{}: `name` must be text of at most 256 characters, got {}",
                cmd,
                v.to_compact()
            )))
        }
    };
    let area = num(cmd, m, "area", 0.0, 1e6).map_err(at)?;
    let perimeter = num(cmd, m, "perimeter", 0.0, 1e9).map_err(at)?;
    let (Some(area), Some(perimeter)) = (area, perimeter) else {
        return Err(format!("{}: rooms[{}]: `area` (m²) and `perimeter` (mm) are required", cmd, i));
    };
    let kind = match given(m, "kind") {
        None => None,
        Some(v) => match v.as_str().and_then(|s| KINDS.iter().find(|k| **k == s)) {
            Some(k) => Some(*k),
            None => {
                return Err(at(format!(
                    "{}: `kind` must be one of {}, got {}",
                    cmd,
                    KINDS.join(", "),
                    v.to_compact()
                )))
            }
        },
    };
    let points = match given(m, "points") {
        None => None,
        Some(Value::Num(crate::json::Num::U(n))) if *n <= 1000 => Some(*n),
        Some(v) => {
            return Err(format!(
                "{}: rooms[{}]: `points` must be a whole number from 0 to 1000, got {}",
                cmd,
                i,
                v.to_compact()
            ))
        }
    };
    Ok(room_of(name, kind, area, perimeter / 1000.0, points))
}

fn room_of(name: String, kind: Option<&'static str>, area: f64, perimeter: f64, points: Option<u64>) -> Room {
    let (kind, named) = match kind {
        Some(k) => (k, true),
        None => match kinds::kind_of(&name) {
            Some(k) => (k, true),
            None => ("other", false),
        },
    };
    Room { name, kind, named, area, perimeter, points }
}

fn wet(kind: &str) -> bool {
    matches!(kind, "bath" | "kitchen" | "service")
}

/// The outlets a room needs at least.
fn minimum(r: &Room) -> u64 {
    let by = |step: f64| ((r.perimeter / step - 1e-9).ceil().max(1.0)) as u64;
    match r.kind {
        "bath" | "veranda" => 1,
        "kitchen" | "service" => by(3.5),
        "dry" => by(5.0),
        _ => {
            if r.area <= 6.0 {
                1
            } else {
                by(5.0)
            }
        }
    }
}

fn lighting(area: f64) -> f64 {
    if area <= 6.0 {
        100.0
    } else {
        100.0 + 60.0 * ((area - 6.0) / 4.0 + 1e-9).floor()
    }
}

fn report(list: Vec<Room>, skipped: Vec<Value>, alternative: bool) -> Value {
    let mins: Vec<u64> = list.iter().map(minimum).collect();
    let pts: Vec<u64> = list.iter().zip(&mins).map(|(r, m)| r.points.unwrap_or(*m)).collect();
    let wet_points: u64 = list.iter().zip(&pts).filter(|(r, _)| wet(r.kind)).map(|(_, p)| *p).sum();
    let possible = wet_points > 6;
    let applied = alternative && possible;
    let first = if applied { 2 } else { 3 };
    let mut rooms = Vec::new();
    let mut light_sum = -0.0;
    let mut tug_sum = -0.0;
    let mut all_ok = true;
    for ((r, m), p) in list.iter().zip(&mins).zip(&pts) {
        let light = lighting(r.area);
        let tug = if wet(r.kind) {
            let k = (*p).min(first);
            600.0 * k as f64 + 100.0 * (*p - k) as f64
        } else {
            100.0 * *p as f64
        };
        let ok = p >= m;
        all_ok &= ok;
        light_sum += light;
        tug_sum += tug;
        let mut o = Map::new();
        o.insert("area_m2", Value::f((r.area * 100.0).round() / 100.0 + 0.0));
        if r.kind == "kitchen" && kinds::has_counter(&r.name) {
            o.insert("counter_outlets", Value::u(2));
        }
        o.insert("kind", Value::s(r.kind));
        o.insert("lighting_points", Value::u(1));
        o.insert("lighting_va", Value::f(light));
        o.insert("name", Value::s(&r.name));
        if !r.named {
            o.insert("note", Value::s("the name says no kind of room: treated as `other`; give `kind`"));
        }
        o.insert("ok", Value::Bool(ok));
        o.insert("perimeter_m", Value::f((r.perimeter * 100.0).round() / 100.0 + 0.0));
        o.insert("tug_minimum", Value::u(*m));
        o.insert("tug_points", Value::u(*p));
        o.insert("tug_va", Value::f(tug));
        rooms.push(Value::Obj(o));
    }
    let mut out = Map::new();
    out.insert("alternative_applied", Value::Bool(applied));
    out.insert("alternative_possible", Value::Bool(possible));
    out.insert("lighting_va", Value::f(light_sum));
    out.insert("not_covered", Value::s(NOT_COVERED));
    out.insert("ok", Value::Bool(all_ok));
    out.insert("rooms", Value::Arr(rooms));
    out.insert("skipped", Value::Arr(skipped));
    out.insert("total_va", Value::f(light_sum + tug_sum));
    out.insert("tug_va", Value::f(tug_sum));
    out.insert("wet_points", Value::u(wet_points));
    Value::Obj(out)
}
