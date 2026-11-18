//! Reading the calculators' parameters as the original does: an object whose keys are taken in
//! sorted order (as serde_json's map holds them), every key known, numbers within a range.

use crate::json::{Map, Value};
use crate::structure::common::R;

/// The parameters as an object, keys sorted (a repeated key keeps its last value).
pub fn object(cmd: &str, p: &Value) -> R<Map> {
    match p.clone().sorted() {
        Value::Obj(m) => Ok(m),
        _ => Err(format!("{}: params must be an object", cmd)),
    }
}

/// Every key is one the command takes; the first that isn't (in sorted order) is named.
pub fn known(cmd: &str, m: &Map, allowed: &[&str]) -> R<()> {
    for k in m.keys() {
        if !allowed.contains(&k.as_str()) {
            return Err(format!("{}: unknown parameter `{}`", cmd, k));
        }
    }
    Ok(())
}

/// A key given with a value other than null.
pub fn given<'a>(m: &'a Map, key: &str) -> Option<&'a Value> {
    match m.get(key) {
        None | Some(Value::Null) => None,
        Some(v) => Some(v),
    }
}

/// A number as f64 (any JSON number).
pub fn number(v: &Value) -> Option<f64> {
    match v {
        Value::Num(n) => Some(n.as_f64()),
        _ => None,
    }
}

/// A float as Rust's Display shows it (as the original's messages print their bounds).
pub fn disp(x: f64) -> String {
    format!("{}", x)
}

/// A number from `lo` to `hi`; none when the key is missing or null.
pub fn num(cmd: &str, m: &Map, key: &str, lo: f64, hi: f64) -> R<Option<f64>> {
    let Some(v) = given(m, key) else { return Ok(None) };
    match number(v) {
        Some(x) if x >= lo && x <= hi => Ok(Some(x)),
        _ => Err(format!(
            "{}: `{}` must be a number from {} to {}, got {}",
            cmd,
            key,
            disp(lo),
            disp(hi),
            v.to_compact()
        )),
    }
}

/// A whole number from `lo` to `hi` (a float with no fraction counts), as a count.
pub fn whole_of(v: &Value, lo: f64, hi: f64) -> Option<f64> {
    let x = number(v)?;
    if x >= lo && x <= hi && x.fract() == 0.0 {
        Some(x)
    } else {
        None
    }
}

/// True or false; none when missing or null.
pub fn boolean(cmd: &str, m: &Map, key: &str) -> R<Option<bool>> {
    match given(m, key) {
        None => Ok(None),
        Some(Value::Bool(b)) => Ok(Some(*b)),
        Some(v) => Err(format!("{}: `{}` must be true or false, got {}", cmd, key, v.to_compact())),
    }
}

/// One of some words; none when missing or null.
pub fn choice(cmd: &str, m: &Map, key: &str, words: &[&str]) -> R<Option<String>> {
    match given(m, key) {
        None => Ok(None),
        Some(Value::Str(s)) if words.contains(&s.as_str()) => Ok(Some(s.clone())),
        Some(v) => Err(format!("{}: `{}` must be one of {}, got {}", cmd, key, words.join(", "), v.to_compact())),
    }
}

/// A refusal as the original shows it: cut at 2000 characters, saying how many more there were.
pub fn clip(e: String) -> String {
    const MAX: usize = 2000;
    let n = e.chars().count();
    if n <= MAX {
        return e;
    }
    let mut out: String = e.chars().take(MAX).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX));
    out
}

/// Rounds to `n` decimals as the original does: x scaled, rounded half away from zero, scaled
/// back; a zero is +0 (the original never shows -0.0).
pub fn round(x: f64, n: i32) -> f64 {
    let k = 10f64.powi(n);
    let r = (x * k).round() / k;
    if r == 0.0 {
        0.0
    } else {
        r
    }
}
