//! What the original does with some of its types once serde has read them: a detail line's or a
//! sketch line's curve made of the fields given, and the like.

use super::de::{Ctx, R};
use crate::json::{Map, Value};
use std::cell::RefCell;

thread_local! {
    /// The text types notes of a size of their own took (name, size), for the reader to make.
    static SIZES: RefCell<Vec<(String, f64)>> = const { RefCell::new(Vec::new()) };
}

/// The text types notes asked for by their sizes since the last call.
pub fn take_sizes() -> Vec<(String, f64)> {
    SIZES.with(|s| std::mem::take(&mut *s.borrow_mut()))
}

pub fn run(name: &str, full: &mut Map, cx: &mut Ctx) -> R<Option<Value>> {
    match name {
        "detail_line" => detail_line(full, cx).map(Some),
        "sketch_line" => sketch_line(full, cx).map(Some),
        "room" => {
            // a room keeps a boundary only while frozen
            if full.get("frozen") != Some(&Value::Bool(true)) {
                full.insert("kept", Value::Null);
            }
            Ok(None)
        }
        "dimension" => {
            // a dimension of no type is of its kind's: arrows for a radius or a diameter
            if full.get("type").and_then(|t| t.as_str()) == Some("") {
                let kind = full.get("kind").and_then(|k| k.as_str()).unwrap_or("");
                let t = if kind == "radial" || kind == "diameter" { "Arrow - 2.5mm Arial" } else { "Diagonal - 2.5mm Arial" };
                full.insert("type", Value::s(t));
            }
            Ok(None)
        }
        "note" => {
            // a note of a size of its own (as files once had it) is of the text type of that size
            if let Some(size) = full.get("size").and_then(|s| s.as_f64()) {
                let name = format!("{}mm", size);
                SIZES.with(|s| s.borrow_mut().push((name.clone(), size)));
                full.insert("type", Value::s(&name));
            } else if full.get("type").and_then(|t| t.as_str()) == Some("") {
                full.insert("type", Value::s("2.5mm"));
            }
            Ok(None)
        }
        "picture" => picture(full),
        "cad" => cad(full),
        _ => panic!("no hook {}", name),
    }
}

/// A picture's data, as the original reads it: base64 (blanks and `=` let go), a PNG or a JPEG;
/// written back as base64 of what it read.
fn picture(full: &mut Map) -> R<Option<Value>> {
    let s = full.get("png").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let bytes = crate::cloud::file::base64_lenient(&s).ok_or_else(|| "a picture's data isn't base64".to_string())?;
    let name = full.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
    match crate::media::picture::decode_any(&bytes) {
        Ok(_) => {}
        Err(crate::media::picture::Fail::Msg(m)) => return Err(format!("picture `{}`: {}", name, m)),
        Err(crate::media::picture::Fail::Panic { msg, .. }) => return Err(format!("picture `{}`: {}", name, msg)),
    }
    full.insert("png", Value::Str(crate::util::base64_encode(&bytes)));
    Ok(None)
}

/// The most a CAD drawing's data unpacks to.
const CAD_CAP: usize = 1 << 30;

/// A CAD drawing's data: base64 of zlib of its DXF; written back packed as the original packs it.
fn cad(full: &mut Map) -> R<Option<Value>> {
    let s = full.get("dxf").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let z = crate::cloud::file::base64_lenient(&s).ok_or_else(|| "a CAD drawing's data isn't base64".to_string())?;
    let raw = crate::inflate::zlib_decode(&z, CAD_CAP).map_err(|e| match e {
        crate::inflate::InflateError::Corrupt => "a CAD drawing's data isn't zlib: corrupt deflate stream".to_string(),
        crate::inflate::InflateError::Truncated => "a CAD drawing's data isn't zlib: incomplete deflate stream".to_string(),
        crate::inflate::InflateError::TooBig => format!("a CAD drawing's data holds more than {} bytes", CAD_CAP),
    })?;
    full.insert("dxf", Value::Str(crate::util::base64_encode(&crate::deflate::zlib_compress(&raw))));
    Ok(None)
}

const LINE_FORMS: &str = "a line is `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

fn some<'a>(full: &'a Map, k: &str) -> Option<&'a Value> {
    match full.get(k) {
        Some(Value::Null) | None => None,
        Some(v) => Some(v),
    }
}

/// The fields of a raw line's curve, in the order the original's raw line has them.
const CURVE_FIELDS: &[&str] = &[
    "points", "arcs", "closed", "start", "end", "arc", "through", "centre", "radius", "radii", "angle", "span", "control",
    "knots", "fit", "start_tangent", "end_tangent",
];

/// Whether a raw line gives this field (a `closed` that is false gives nothing).
fn given(full: &Map, k: &str) -> bool {
    match k {
        "closed" => full.get(k) == Some(&Value::Bool(true)),
        _ => some(full, k).is_some(),
    }
}

fn p2(v: Option<&Value>) -> Option<[f64; 2]> {
    let a = v?.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?])
}

/// The turn of an arc from `a` through `t` to `b`, as the original takes it: none (straight) when
/// `a` and `b` are one point, when the three lie on a line, or when `t` is within 1 mm of the line
/// from `a` to `b`.
fn through_turn(a: [f64; 2], t: [f64; 2], b: [f64; 2]) -> f64 {
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    let len2 = dx * dx + dy * dy;
    if len2 == 0.0 {
        return 0.0;
    }
    let (px, py) = (t[0] - a[0], t[1] - a[1]);
    let cross = dx * py - dy * px;
    if cross == 0.0 {
        return 0.0;
    }
    let u = (px * dx + py * dy) / len2;
    let dist = if u <= 0.0 {
        px.hypot(py)
    } else if u >= 1.0 {
        (t[0] - b[0]).hypot(t[1] - b[1])
    } else {
        cross.abs() / len2.sqrt()
    };
    if dist <= 1.0 {
        return 0.0;
    }
    turn_through(a, t, b)
}

/// The turn, in degrees counter-clockwise, of the arc from `a` through `t` to `b` (0: straight).
fn turn_through(a: [f64; 2], t: [f64; 2], b: [f64; 2]) -> f64 {
    let ta = [a[0] - t[0], a[1] - t[1]];
    let tb = [b[0] - t[0], b[1] - t[1]];
    let cr = ta[0] * tb[1] - ta[1] * tb[0];
    let dot = ta[0] * tb[0] + ta[1] * tb[1];
    let at = cr.atan2(dot);
    let pi = std::f64::consts::PI;
    if at >= 0.0 {
        (2.0 * (at - pi)).to_degrees()
    } else {
        (2.0 * (at + pi)).to_degrees()
    }
}

/// The curve a raw line's fields make (each form's fields alone), written as the original writes
/// it: a polyline of two points as a line from its start to its end, no turns of nought, an arc's
/// `through` point as the turn it makes.
fn curve(full: &Map, out: &mut Map) -> R<()> {
    let forms: [(&[&str], bool); 6] = [
        (&["start", "end", "through", "arc"], given(full, "start") && given(full, "end")),
        (&["points", "arcs", "closed"], given(full, "points")),
        (&["centre", "radius"], given(full, "centre") && given(full, "radius")),
        (&["centre", "radii", "angle", "span"], given(full, "centre") && given(full, "radii")),
        (&["control", "knots"], given(full, "control")),
        (&["fit", "start_tangent", "end_tangent"], given(full, "fit")),
    ];
    let (fields, _) = match forms.iter().find(|(_, on)| *on) {
        Some(f) => *f,
        None => return Err(LINE_FORMS.to_string()),
    };
    if let Some(k) = CURVE_FIELDS.iter().find(|k| given(full, k) && !fields.contains(k)) {
        return Err(format!("`{}` doesn't go with the {} given: {}", k, fields.join(", "), LINE_FORMS));
    }
    let put = |out: &mut Map, k: &str| {
        if let Some(v) = some(full, k) {
            out.insert(k, v.clone());
        }
    };
    let nought = |v: Option<&Value>| v.and_then(|x| x.as_f64()) == Some(0.0);
    match fields[0] {
        "start" => {
            if given(full, "arc") && given(full, "through") {
                return Err("give an arc's `through` point or its `arc` turn, not both".into());
            }
            put(out, "start");
            put(out, "end");
            if let Some(a) = some(full, "arc") {
                if !nought(Some(a)) {
                    out.insert("arc", a.clone());
                }
            } else if let (Some(a), Some(t), Some(b)) = (p2(full.get("start")), p2(full.get("through")), p2(full.get("end"))) {
                let turn = through_turn(a, t, b);
                if turn != 0.0 {
                    out.insert("arc", Value::f(turn));
                }
            }
        }
        "points" => {
            let pts = some(full, "points").and_then(|p| p.as_arr()).cloned().unwrap_or_default();
            let arcs = some(full, "arcs").and_then(|p| p.as_arr()).cloned();
            let curved = arcs.as_ref().map(|a| a.iter().any(|x| x.as_f64() != Some(0.0))).unwrap_or(false);
            let closed = given(full, "closed");
            if pts.len() == 2 && !closed {
                // a polyline of one segment is a line
                out.insert("start", pts[0].clone());
                out.insert("end", pts[1].clone());
                if let Some(a) = arcs.as_ref().and_then(|a| a.first()) {
                    if arcs.as_ref().map(|a| a.len()) == Some(1) && !nought(Some(a)) {
                        out.insert("arc", a.clone());
                    }
                }
                if !curved || arcs.as_ref().map(|a| a.len()).unwrap_or(1) == 1 {
                    return Ok(());
                }
                // turns (not all nought) for more segments than it has: kept, for the model to refuse
                out.remove("start");
                out.remove("end");
                out.remove("arc");
            }
            out.insert("points", Value::Arr(pts));
            if curved {
                put(out, "arcs");
            }
            if closed {
                out.insert("closed", Value::Bool(true));
            }
        }
        "centre" if fields[1] == "radius" => {
            put(out, "centre");
            put(out, "radius");
        }
        "centre" => {
            put(out, "centre");
            put(out, "radii");
            if let Some(a) = some(full, "angle") {
                if !nought(Some(a)) {
                    out.insert("angle", a.clone());
                }
            }
            put(out, "span");
        }
        "control" => {
            put(out, "control");
            put(out, "knots");
        }
        _ => {
            put(out, "fit");
            put(out, "start_tangent");
            put(out, "end_tangent");
        }
    }
    Ok(())
}

fn detail_line(full: &mut Map, _cx: &mut Ctx) -> R<Value> {
    let mut out = Map::new();
    out.insert("view", full.get("view").cloned().unwrap_or(Value::Null));
    out.insert("style", full.get("style").cloned().unwrap_or(Value::Null));
    if let Some(v) = some(full, "insulation") {
        out.insert("insulation", v.clone());
    }
    if full.get("centre_mark") == Some(&Value::Bool(true)) {
        out.insert("centre_mark", Value::Bool(true));
    }
    for k in ["cloud", "revision"] {
        if let Some(v) = some(full, k) {
            out.insert(k, v.clone());
        }
    }
    curve(full, &mut out)?;
    Ok(Value::Obj(out))
}

fn sketch_line(full: &mut Map, _cx: &mut Ctx) -> R<Value> {
    let mut out = Map::new();
    out.insert("id", full.get("id").cloned().unwrap_or(Value::u(0)));
    out.insert("guid", full.get("guid").cloned().unwrap_or(Value::Null));
    if let Some(v) = some(full, "style") {
        out.insert("style", v.clone());
    }
    if full.get("invisible") == Some(&Value::Bool(true)) {
        out.insert("invisible", Value::Bool(true));
    }
    curve(full, &mut out)?;
    if let Some(v) = some(full, "slope") {
        out.insert("slope", v.clone());
    }
    Ok(Value::Obj(out))
}

#[cfg(test)]
mod tests {
    use super::through_turn;

    #[test]
    fn an_arc_through_a_point_as_the_original_turns_it() {
        let (a, b) = ([0.0, 0.0], [1000.0, 0.0]);
        // the original's own turns, to the last digit
        assert_eq!(through_turn(a, [500.0, 10.0], b), -4.583051352700409);
        assert_eq!(through_turn(a, [300.0, 50.0], b), -27.09587797600099);
        assert_eq!(through_turn(a, [500.0, 100.0], b), -45.23972989608083);
        assert_eq!(through_turn(a, [500.0, -100.0], b), 45.23972989608083);
        // within 1 mm of the line between its ends, on its line, or with no length: straight
        assert_eq!(through_turn(a, [500.0, 1.0], b), 0.0);
        assert_eq!(through_turn(a, [0.1, 0.05], b), 0.0);
        assert_eq!(through_turn(a, [1500.0, 0.0], b), 0.0);
        assert_eq!(through_turn(a, [500.0, 5.0], a), 0.0);
        // just past 1 mm, or beyond an end: an arc
        assert!(through_turn(a, [500.0, 1.0001], b) != 0.0);
        assert!(through_turn(a, [1500.0, 0.05], b) != 0.0);
    }
}
