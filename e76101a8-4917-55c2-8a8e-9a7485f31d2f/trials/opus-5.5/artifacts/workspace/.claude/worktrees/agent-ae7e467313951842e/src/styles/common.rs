//! What the style and settings commands share: reading their parameters with the errors the
//! original gives, colours and pens, and the library entries that name the project's styles.

use crate::json::{Map, Value};
use crate::project::Project;

pub type R<T> = Result<T, String>;

/// Refuses a parameter the command doesn't take: "`x` isn't one of its parameters: a, b, c", the
/// first such in sorted order (the original's parameters are a sorted map).
pub fn check_keys(p: &Value, cmd: &str, allowed: &[&str]) -> R<()> {
    if let Value::Obj(m) = p {
        let mut keys: Vec<&String> = m.items.iter().map(|(k, _)| k).collect();
        keys.sort();
        for k in keys {
            if !allowed.contains(&k.as_str()) {
                return Err(format!("{}: `{}` isn't one of its parameters: {}", cmd, k, allowed.join(", ")));
            }
        }
    }
    Ok(())
}

/// A text parameter, trimmed: None when absent, null or blank.
pub fn opt_name(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) if s.chars().count() <= 256 => {
            let t = s.trim();
            if t.is_empty() {
                Ok(None)
            } else {
                Ok(Some(t.to_string()))
            }
        }
        Some(v) => Err(format!("{}: `{}` must be text of at most 256 characters, got {}", cmd, key, v.to_compact())),
    }
}

/// `true` or `false` (null or absent: None).
pub fn opt_bool(p: &Value, cmd: &str, key: &str) -> R<Option<bool>> {
    crate::commands::params::opt_bool(p, cmd, key)
}

/// serde's "invalid type" message for a value that should have been of `expected` (f64, u8…).
pub fn invalid_type(v: &Value, expected: &str) -> String {
    format!("invalid type: {}, expected {}", v.kind_name(), expected)
}

/// A number as serde reads an f64 (any JSON number), else serde's error.
pub fn f64_of(v: &Value) -> Result<f64, String> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid_type(v, "f64")),
    }
}

/// A float as Rust's Display shows it (1.5, 17, 100000000000000000000).
pub fn disp(x: f64) -> String {
    format!("{}", x)
}

/// A pen: a whole number 0 (a hairline) to 16.
pub fn opt_pen(p: &Value, cmd: &str, key: &str) -> R<Option<u64>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => {
            let x = f64_of(v).map_err(|e| format!("{}: `{}`: {}", cmd, key, e))?;
            pen_of(x).map(Some).ok_or_else(|| {
                format!(
                    "{}: `{}`: a line weight is a pen, a whole number from 0 (a hairline) to 16, not {}",
                    cmd,
                    key,
                    disp(x)
                )
            })
        }
    }
}

pub fn pen_of(x: f64) -> Option<u64> {
    if x.is_finite() && x.fract() == 0.0 && (0.0..=16.0).contains(&x) {
        Some(x as u64)
    } else {
        None
    }
}

/// A colour from "#rrggbb" or [r, g, b] (whole numbers 0 to 255).
pub fn color_of(v: &Value) -> Option<[u8; 3]> {
    match v {
        Value::Str(s) => {
            let h = s.strip_prefix('#')?;
            if h.len() != 6 || !h.chars().all(|c| c.is_ascii_hexdigit()) {
                return None;
            }
            let b = |i: usize| u8::from_str_radix(&h[i..i + 2], 16).ok();
            Some([b(0)?, b(2)?, b(4)?])
        }
        Value::Arr(a) if a.len() == 3 => {
            let mut out = [0u8; 3];
            for (i, x) in a.iter().enumerate() {
                match x {
                    Value::Num(crate::json::Num::U(u)) if *u <= 255 => out[i] = *u as u8,
                    _ => return None,
                }
            }
            Some(out)
        }
        _ => None,
    }
}

pub fn opt_color(p: &Value, cmd: &str, key: &str) -> R<Option<[u8; 3]>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => color_of(v).map(Some).ok_or_else(|| {
            format!("{}: `{}` is \"#rrggbb\" or [r, g, b], each 0 to 255, not {}", cmd, key, v.to_compact())
        }),
    }
}

pub fn color_value(c: [u8; 3]) -> Value {
    Value::Arr(vec![Value::u(c[0] as u64), Value::u(c[1] as u64), Value::u(c[2] as u64)])
}

/// A colour as a file holds it ([r, g, b]); black when it holds none.
pub fn color_in(v: Option<&Value>) -> [u8; 3] {
    v.and_then(color_of).unwrap_or([0, 0, 0])
}

// ---------------------------------------------------------------- the library

/// The GUID of the library entry of this kind and name.
pub fn guid_of(pr: &Project, kind: &str, name: &str) -> Option<String> {
    pr.lib_guid(kind, name)
}

/// The name of the library entry of this kind with this GUID.
pub fn name_of_guid(pr: &Project, kind: &str, g: &str) -> Option<String> {
    pr.library
        .values()
        .find(|e| e.get("kind").and_then(|x| x.as_str()) == Some(kind) && e.get("guid").and_then(|x| x.as_str()) == Some(g))
        .and_then(|e| e.get("name"))
        .and_then(|n| n.as_str())
        .map(|s| s.to_string())
}

/// Renames the library entry of this kind and name.
pub fn lib_rename(pr: &mut Project, kind: &str, from: &str, to: &str) {
    if let Some(id) = pr.lib_find(kind, from) {
        if let Some(e) = pr.library.get_mut(&id) {
            e.set("name", Value::s(to));
        }
    }
}

/// Takes the library entry of this kind and name away.
pub fn lib_remove(pr: &mut Project, kind: &str, name: &str) {
    if let Some(id) = pr.lib_find(kind, name) {
        pr.library.remove(&id);
    }
}

/// The library entry of this kind and name, made if the project lacks it; its GUID.
pub fn lib_ensure(pr: &mut Project, kind: &str, name: &str) -> String {
    match pr.lib_guid(kind, name) {
        Some(g) => g,
        None => pr.lib_add(kind, name).1,
    }
}

/// How the model's check calls a library entry's kind ("line style", "design option set"); None
/// for the kinds it isn't known to hold to the rule below.
fn kind_words(kind: &str) -> Option<String> {
    if kind.starts_with("type:") || kind == "design-option" {
        return None;
    }
    Some(match kind {
        "option-set" => "design option set".to_string(),
        k => k.replace('-', " "),
    })
}

/// The model rule that no library entry is named like a GUID (a command takes a name or a GUID,
/// so one can't be the other): "line style `…`: a name isn't a GUID; name it otherwise", the
/// first such entry by id.
pub fn check_library_names(pr: &Project) -> R<()> {
    for e in pr.library.values() {
        let kind = e.get("kind").and_then(|k| k.as_str()).unwrap_or("");
        let Some(words) = kind_words(kind) else { continue };
        let name = e.get("name").and_then(|n| n.as_str()).unwrap_or("");
        if super::electrical::as_guid(name).is_some() {
            return Err(format!("{} `{}`: a name isn't a GUID; name it otherwise", words, name));
        }
    }
    Ok(())
}

/// A section of the file as a map (empty if the project has none).
pub fn section(pr: &Project, key: &str) -> Map {
    pr.section(key).cloned().unwrap_or_default()
}
