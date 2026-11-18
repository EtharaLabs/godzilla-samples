//! Reading `reinforce`'s parameters as the original's serde types read them (structs that deny
//! unknown fields, from a JSON object, its keys in sorted order, or from an array, field by
//! field), with serde's very words: "unknown field `x`, expected one of `a`, `b`", "missing field
//! `x`", "invalid type: string \"x\", expected f64", "invalid length 2, expected struct Row with 4
//! elements".

use crate::json::{fmt_f64, Map, Num, Value};

/// What a field holds.
#[derive(Clone, Copy, Debug)]
pub enum Ty {
    F64,
    Usize,
    U8,
    Str,
    /// Any JSON value, read later (a hook: a length or {start, end}).
    Any,
    Struct(&'static Shape),
}

/// A field of a struct: its name, what it holds, and whether it may be left out (an `Option`).
#[derive(Clone, Copy, Debug)]
pub struct Field {
    pub name: &'static str,
    pub ty: Ty,
    pub optional: bool,
}

/// A struct: its name (as serde says it) and its fields in order.
#[derive(Debug)]
pub struct Shape {
    pub name: &'static str,
    pub fields: &'static [Field],
}

pub const fn req(name: &'static str, ty: Ty) -> Field {
    Field { name, ty, optional: false }
}

pub const fn opt(name: &'static str, ty: Ty) -> Field {
    Field { name, ty, optional: true }
}

/// A value as serde names it in "invalid type" errors (a float as serde_json writes it).
pub fn unexpected(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => format!("boolean `{}`", b),
        Value::Num(Num::U(u)) => format!("integer `{}`", u),
        Value::Num(Num::I(i)) => format!("integer `{}`", i),
        Value::Num(Num::F(f)) => format!("floating point `{}`", fmt_f64(*f)),
        Value::Str(s) => format!("string {}", Value::Str(s.clone()).to_compact()),
        Value::Arr(_) => "sequence".into(),
        Value::Obj(_) => "map".into(),
    }
}

pub fn invalid_type(v: &Value, expected: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), expected)
}

/// serde's list of the fields a struct has, as its "unknown field" error words it.
fn one_of(fields: &[Field]) -> String {
    let names: Vec<String> = fields.iter().map(|f| format!("`{}`", f.name)).collect();
    match names.len() {
        0 => "there are no fields".into(),
        1 => names[0].clone(),
        2 => format!("{} or {}", names[0], names[1]),
        _ => format!("one of {}", names.join(", ")),
    }
}

pub fn de_f64(v: &Value) -> Result<f64, String> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid_type(v, "f64")),
    }
}

pub fn de_usize(v: &Value) -> Result<u64, String> {
    match v {
        Value::Num(Num::U(u)) => Ok(*u),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected usize", i)),
        _ => Err(invalid_type(v, "usize")),
    }
}

pub fn de_u8(v: &Value) -> Result<u64, String> {
    match v {
        Value::Num(Num::U(u)) if *u <= 255 => Ok(*u),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u8", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u8", i)),
        _ => Err(invalid_type(v, "u8")),
    }
}

pub fn de_str(v: &Value) -> Result<String, String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(invalid_type(v, "a string")),
    }
}

/// One field's value: None where an `Option` is null.
fn de_field(v: &Value, f: &Field) -> Result<Option<Value>, String> {
    if f.optional && v.is_null() {
        return Ok(None);
    }
    Ok(Some(match f.ty {
        Ty::F64 => Value::f(de_f64(v)?),
        Ty::Usize => Value::u(de_usize(v)?),
        Ty::U8 => Value::u(de_u8(v)?),
        Ty::Str => Value::s(&de_str(v)?),
        Ty::Any => v.clone(),
        Ty::Struct(s) => Value::Obj(de_struct(v, s)?),
    }))
}

/// A struct read from a value: the fields given (none for an `Option` left out or null), each
/// as it was read (a float as a float, a count as a whole number, a struct as its fields).
pub fn de_struct(v: &Value, shape: &Shape) -> Result<Map, String> {
    match v {
        Value::Obj(m) => {
            // serde_json's objects hold their keys sorted, the last of a key given twice
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            keys.dedup();
            let mut out = Map::new();
            for k in keys {
                let val = m.items.iter().rev().find(|(kk, _)| kk == k).map(|(_, v)| v).unwrap();
                match shape.fields.iter().find(|f| f.name == k.as_str()) {
                    None => return Err(format!("unknown field `{}`, expected {}", k, one_of(shape.fields))),
                    Some(f) => {
                        if let Some(x) = de_field(val, f)? {
                            out.insert(f.name, x);
                        }
                    }
                }
            }
            for f in shape.fields {
                if !f.optional && !out.contains(f.name) {
                    return Err(format!("missing field `{}`", f.name));
                }
            }
            // in the order the struct declares its fields
            let mut sorted = Map::new();
            for f in shape.fields {
                if let Some(x) = out.get(f.name) {
                    sorted.insert(f.name, x.clone());
                }
            }
            Ok(sorted)
        }
        Value::Arr(a) => {
            let n = shape.fields.len();
            let mut out = Map::new();
            for (i, f) in shape.fields.iter().enumerate() {
                let Some(val) = a.get(i) else {
                    return Err(format!(
                        "invalid length {}, expected struct {} with {} elements",
                        a.len(),
                        shape.name,
                        n
                    ));
                };
                if let Some(x) = de_field(val, f)? {
                    out.insert(f.name, x);
                }
            }
            if a.len() > n {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(out)
        }
        _ => Err(invalid_type(v, &format!("struct {}", shape.name))),
    }
}

/// Whether a value reads as this struct (an untagged enum's variant).
pub fn fits(v: &Value, shape: &Shape) -> bool {
    de_struct(v, shape).is_ok()
}

// ---------------------------------------------------------------- reading what was read

pub fn f(m: &Map, k: &str) -> Option<f64> {
    m.get(k).and_then(|x| x.as_f64())
}

pub fn u(m: &Map, k: &str) -> Option<u64> {
    m.get(k).and_then(|x| x.as_u64())
}

pub fn s(m: &Map, k: &str) -> Option<String> {
    m.get(k).and_then(|x| x.as_str()).map(|x| x.to_string())
}

pub fn sub<'a>(m: &'a Map, k: &str) -> Option<&'a Map> {
    m.get(k).and_then(|x| x.as_obj())
}

pub fn any<'a>(m: &'a Map, k: &str) -> Option<&'a Value> {
    m.get(k)
}
