//! Reading a calculator's parameters, with the texts the calculators refuse them in: the
//! parameters are an object of known keys (null is as absent), numbers within a range, `true` or
//! `false`, or one of a list of words.

use crate::json::{Map, Value};
use crate::structure::common::R;

/// The longest a calculator's refusal is.
const MAX_ERROR: usize = 2000;

/// A refusal cut to its first 2000 characters, saying how many more there were.
pub fn clip(e: String) -> String {
    let n = e.chars().count();
    if n <= MAX_ERROR {
        return e;
    }
    let mut out: String = e.chars().take(MAX_ERROR).collect();
    out.push_str(&format!("… ({} more characters)", n - MAX_ERROR));
    out
}

/// The parameters as an object.
pub fn object<'a>(cmd: &str, p: &'a Value) -> R<&'a Map> {
    p.as_obj().ok_or_else(|| format!("{}: params must be an object", cmd))
}

/// Refuses the first key (in sorted order) the command doesn't take.
pub fn known(cmd: &str, m: &Map, keys: &[&str]) -> R<()> {
    let mut ks: Vec<&String> = m.keys().collect();
    ks.sort();
    for k in ks {
        if !keys.contains(&k.as_str()) {
            return Err(format!("{}: unknown parameter `{}`", cmd, k));
        }
    }
    Ok(())
}

/// A value given (null is as absent).
pub fn given<'a>(m: &'a Map, key: &str) -> Option<&'a Value> {
    match m.get(key) {
        None | Some(Value::Null) => None,
        Some(v) => Some(v),
    }
}

/// A number from `lo` to `hi`.
pub fn num(cmd: &str, m: &Map, key: &str, lo: f64, hi: f64) -> R<Option<f64>> {
    match given(m, key) {
        None => Ok(None),
        Some(v) => match v {
            Value::Num(n) if n.as_f64() >= lo && n.as_f64() <= hi => Ok(Some(n.as_f64())),
            _ => Err(format!("{}: `{}` must be a number from {} to {}, got {}", cmd, key, lo, hi, v.to_compact())),
        },
    }
}

/// `true` or `false`.
pub fn flag(cmd: &str, m: &Map, key: &str) -> R<Option<bool>> {
    match given(m, key) {
        None => Ok(None),
        Some(Value::Bool(b)) => Ok(Some(*b)),
        Some(v) => Err(format!("{}: `{}` must be true or false, got {}", cmd, key, v.to_compact())),
    }
}

/// One of `words` (exactly, case and all): its place in the list.
pub fn word(cmd: &str, m: &Map, key: &str, words: &[&str]) -> R<Option<usize>> {
    match given(m, key) {
        None => Ok(None),
        Some(v) => match v.as_str().and_then(|s| words.iter().position(|w| *w == s)) {
            Some(i) => Ok(Some(i)),
            None => Err(format!("{}: `{}` must be one of {}, got {}", cmd, key, words.join(", "), v.to_compact())),
        },
    }
}

/// A float rounded to two decimals, half away from zero.
pub fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// A number as Rust shows it (2.5, 10, 0.75).
pub fn disp(x: f64) -> String {
    format!("{}", x)
}
