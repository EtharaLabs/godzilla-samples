//! Reading a command's parameters, with the errors the commands give.

use crate::json::Value;

pub type R<T> = Result<T, String>;

pub fn get<'a>(p: &'a Value, key: &str) -> Option<&'a Value> {
    match p.get(key) {
        Some(Value::Null) | None => None,
        Some(v) => Some(v),
    }
}

pub fn has(p: &Value, key: &str) -> bool {
    get(p, key).is_some()
}

/// Present in the object, even as null.
pub fn given(p: &Value, key: &str) -> bool {
    p.get(key).is_some()
}

pub fn num_of(v: &Value) -> Option<f64> {
    match v {
        Value::Num(n) => Some(n.as_f64()),
        _ => None,
    }
}

/// The largest length a command takes, in mm (1000 km).
pub const MAX_MM: f64 = 1e9;

/// A length in mm, within the model's reach.
pub fn mm_of(v: &Value) -> Option<f64> {
    let x = num_of(v)?;
    if x.is_finite() && x.abs() <= MAX_MM {
        Some(x)
    } else {
        None
    }
}

pub fn req_num(p: &Value, cmd: &str, key: &str) -> R<f64> {
    match get(p, key) {
        None => Err(format!("{}: `{}` in mm is required", cmd, key)),
        Some(v) => mm_of(v).ok_or_else(|| format!("{}: `{}` must be a number in mm, got {}", cmd, key, v.to_compact())),
    }
}

pub fn opt_num(p: &Value, cmd: &str, key: &str) -> R<Option<f64>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => mm_of(v)
            .map(Some)
            .ok_or_else(|| format!("{}: `{}` must be a number in mm, got {}", cmd, key, v.to_compact())),
    }
}

/// A number in some unit other than mm (degrees, percent…).
pub fn opt_num_unit(p: &Value, cmd: &str, key: &str, unit: &str) -> R<Option<f64>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => num_of(v)
            .map(Some)
            .ok_or_else(|| format!("{}: `{}` must be a number{}, got {}", cmd, key, unit, v.to_compact())),
    }
}

pub fn opt_text(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    match get(p, key) {
        None => Ok(None),
        Some(Value::Str(s)) if s.chars().count() <= 256 => Ok(Some(s.clone())),
        Some(v) => Err(format!("{}: `{}` must be text of at most 256 characters, got {}", cmd, key, v.to_compact())),
    }
}

pub fn opt_bool(p: &Value, cmd: &str, key: &str) -> R<Option<bool>> {
    match get(p, key) {
        None => Ok(None),
        Some(Value::Bool(b)) => Ok(Some(*b)),
        Some(v) => Err(format!("{}: `{}` must be true or false, got {}", cmd, key, v.to_compact())),
    }
}

pub fn point_of(v: &Value) -> Option<[f64; 2]> {
    let a = v.as_arr()?;
    if a.len() != 2 {
        return None;
    }
    Some([mm_of(&a[0])?, mm_of(&a[1])?])
}

pub fn point3_of(v: &Value) -> Option<[f64; 3]> {
    let a = v.as_arr()?;
    if a.len() != 3 {
        return None;
    }
    Some([mm_of(&a[0])?, mm_of(&a[1])?, mm_of(&a[2])?])
}

pub fn req_point(p: &Value, cmd: &str, key: &str) -> R<[f64; 2]> {
    match get(p, key) {
        None => Err(format!("{}: `{}` [x, y] is required", cmd, key)),
        Some(v) => point_of(v).ok_or_else(|| format!("{}: `{}` must be a point [x, y] in mm, got {}", cmd, key, v.to_compact())),
    }
}

pub fn opt_point(p: &Value, cmd: &str, key: &str) -> R<Option<[f64; 2]>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => point_of(v)
            .map(Some)
            .ok_or_else(|| format!("{}: `{}` must be a point [x, y] in mm, got {}", cmd, key, v.to_compact())),
    }
}

/// A list of points; anything but a list of points reads as missing.
pub fn points_of(v: &Value) -> Option<Vec<[f64; 2]>> {
    let a = v.as_arr()?;
    a.iter().map(point_of).collect()
}

pub fn req_points(p: &Value, cmd: &str, key: &str) -> R<Vec<[f64; 2]>> {
    match get(p, key).and_then(points_of) {
        None => Err(format!("{}: `{}` [[x, y], …] is required", cmd, key)),
        Some(v) => Ok(v),
    }
}

pub fn opt_points(p: &Value, cmd: &str, key: &str) -> R<Option<Vec<[f64; 2]>>> {
    match get(p, key) {
        None => Ok(None),
        Some(v) => match points_of(v) {
            Some(pts) => Ok(Some(pts)),
            None => Err(format!("{}: `{}` [[x, y], …] is required", cmd, key)),
        },
    }
}

/// An element id: a number, or a GUID or an id in a string.
pub fn id_of(v: &Value) -> Option<u64> {
    match v {
        Value::Num(n) => {
            let f = n.as_f64();
            if f >= 0.0 && f.fract() == 0.0 {
                Some(f as u64)
            } else {
                None
            }
        }
        Value::Str(s) => s.trim().parse::<u64>().ok(),
        _ => None,
    }
}
