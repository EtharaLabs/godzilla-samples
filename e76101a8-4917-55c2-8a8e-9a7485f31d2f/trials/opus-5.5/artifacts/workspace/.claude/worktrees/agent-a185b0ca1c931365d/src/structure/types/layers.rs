//! A type's layers as `type {layers}` gives them: read field by field as the original reads its
//! `Layer` (serde, from a JSON value), with its defaults and its very errors; and as the file and
//! the replies hold them.

use crate::json::{fmt_f64, Map, Num, Value};
use crate::structure::members::read::parse_guid;

/// A layer's function, in the order the original lists them.
pub const FUNCTIONS: &[&str] = &["structure", "substrate", "thermal", "membrane", "finish"];

/// The most layers a type has.
pub const MAX_LAYERS: usize = 32;

/// What a part's `guid` names: a GUID, or (as a command may give it) an element's id; id 0 is none.
#[derive(Clone, Debug, PartialEq)]
pub enum GRef {
    Guid(String),
    Id(u64),
}

impl GRef {
    pub fn is_none(&self) -> bool {
        matches!(self, GRef::Id(0))
    }
    pub fn value(&self) -> Value {
        match self {
            GRef::Guid(g) => Value::s(g),
            GRef::Id(n) => Value::u(*n),
        }
    }
}

/// A layer of a wall, floor, roof or ceiling type, as the original holds it: its material by
/// name ("" for none).
#[derive(Clone, Debug, PartialEq)]
pub struct Layer {
    /// Its part id; None (0) until it has one.
    pub id: Option<u64>,
    pub guid: Option<GRef>,
    pub function: String,
    pub material: String,
    pub thickness: f64,
    pub variable: bool,
}

impl Layer {
    pub fn has_ref(&self) -> bool {
        self.id.is_some() || self.guid.is_some()
    }
    /// As replies and `inspect` show it: keys sorted, its material by name, its id and GUID
    /// where it has them.
    pub fn view(&self) -> Value {
        let mut m = Map::new();
        m.insert("function", Value::s(&self.function));
        if let Some(g) = &self.guid {
            m.insert("guid", g.value());
        }
        if let Some(id) = self.id {
            m.insert("id", Value::u(id));
        }
        m.insert("material", Value::s(&self.material));
        m.insert("thickness", Value::f(self.thickness));
        if self.variable {
            m.insert("variable", Value::Bool(true));
        }
        Value::Obj(m)
    }
}

/// A GUID as the original takes one (hyphenated, maybe in braces, any case): one whose first
/// 64 bits are all zero is how it writes an element's id, so not a GUID.
pub fn real_guid(s: &str) -> Option<String> {
    let g = parse_guid(s)?;
    let hi: String = g.chars().filter(|c| *c != '-').take(16).collect();
    if hi.bytes().all(|b| b == b'0') {
        None
    } else {
        Some(g)
    }
}

// ---------------------------------------------------------------- serde's wording

/// A value as serde_json names it in "invalid type" errors.
pub fn unexpected(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => format!("boolean `{}`", b),
        Value::Num(Num::U(u)) => format!("integer `{}`", u),
        Value::Num(Num::I(i)) => format!("integer `{}`", i),
        Value::Num(Num::F(f)) => format!("floating point `{}`", fmt_f64(*f)),
        Value::Str(s) => format!("string {:?}", s),
        Value::Arr(_) => "sequence".into(),
        Value::Obj(_) => "map".into(),
    }
}

fn invalid(v: &Value, what: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), what)
}

fn de_u64(v: &Value) -> Result<u64, String> {
    match v {
        Value::Num(Num::U(u)) => Ok(*u),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u64", i)),
        _ => Err(invalid(v, "u64")),
    }
}

fn de_f64(v: &Value) -> Result<f64, String> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid(v, "f64")),
    }
}

fn de_bool(v: &Value) -> Result<bool, String> {
    match v {
        Value::Bool(b) => Ok(*b),
        _ => Err(invalid(v, "a boolean")),
    }
}

fn de_string(v: &Value) -> Result<String, String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(invalid(v, "a string")),
    }
}

fn unknown_variant(s: &str) -> String {
    let list: Vec<String> = FUNCTIONS.iter().map(|f| format!("`{}`", f)).collect();
    format!("unknown variant `{}`, expected one of {}", s, list.join(", "))
}

/// A layer's `function`: a unit variant, by name or as a map of one key.
fn de_function(v: &Value) -> Result<String, String> {
    match v {
        Value::Str(s) => {
            if FUNCTIONS.contains(&s.as_str()) {
                Ok(s.clone())
            } else {
                Err(unknown_variant(s))
            }
        }
        Value::Obj(m) => {
            if m.len() != 1 {
                return Err("invalid value: map, expected map with a single key".into());
            }
            let (k, x) = &m.items[0];
            if !FUNCTIONS.contains(&k.as_str()) {
                return Err(unknown_variant(k));
            }
            match x {
                Value::Null => Ok(k.clone()),
                other => Err(invalid(other, "unit")),
            }
        }
        _ => Err(invalid(v, "string or map")),
    }
}

/// A part's `guid`: a GUID, or an element's id (a whole number, or one in a string).
pub fn de_ref(v: &Value) -> Result<GRef, String> {
    match v {
        Value::Str(s) => {
            if let Some(g) = real_guid(s) {
                return Ok(GRef::Guid(g));
            }
            let t = s.trim();
            if !t.is_empty() && t.bytes().all(|b| b.is_ascii_digit()) {
                if let Ok(n) = t.parse::<u64>() {
                    return Ok(GRef::Id(n));
                }
            }
            Err(format!("`{}` is not a GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or an id", s))
        }
        Value::Num(Num::U(u)) => Ok(GRef::Id(*u)),
        Value::Num(Num::I(i)) => Err(format!("{} is not an element id", i)),
        Value::Num(Num::F(f)) => {
            if *f >= 0.0 && f.fract() == 0.0 && *f < 18446744073709551616.0 {
                Ok(GRef::Id(*f as u64))
            } else {
                Err(format!("{} is not an element id", f))
            }
        }
        _ => Err(invalid(v, "an element's GUID, or its id")),
    }
}

const FIELDS: &[&str] = &["id", "guid", "function", "material", "thickness", "variable"];

/// One layer of `layers`, as serde reads the original's `Layer` from a JSON value: a map (its
/// keys in order, as serde_json's map holds them; no others) or a sequence of its fields.
pub fn de_layer(v: &Value) -> Result<Layer, String> {
    let mut l = Layer {
        id: None,
        guid: None,
        function: "structure".into(),
        material: String::new(),
        thickness: 0.0,
        variable: false,
    };
    match v {
        Value::Obj(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            keys.dedup();
            let mut thickness = None;
            for k in keys {
                let x = m.get(k).unwrap();
                match k.as_str() {
                    "id" => l.id = Some(de_u64(x)?),
                    "guid" => l.guid = Some(de_ref(x)?),
                    "function" => l.function = de_function(x)?,
                    "material" => l.material = de_string(x)?,
                    "thickness" => thickness = Some(de_f64(x)?),
                    "variable" => l.variable = de_bool(x)?,
                    other => {
                        let list: Vec<String> = FIELDS.iter().map(|f| format!("`{}`", f)).collect();
                        return Err(format!("unknown field `{}`, expected one of {}", other, list.join(", ")));
                    }
                }
            }
            l.thickness = thickness.ok_or_else(|| "missing field `thickness`".to_string())?;
        }
        Value::Arr(a) => {
            let mut it = a.iter();
            if let Some(x) = it.next() {
                l.id = Some(de_u64(x)?);
            }
            if let Some(x) = it.next() {
                l.guid = Some(de_ref(x)?);
            }
            if let Some(x) = it.next() {
                l.function = de_function(x)?;
            }
            if let Some(x) = it.next() {
                l.material = de_string(x)?;
            }
            match it.next() {
                Some(x) => l.thickness = de_f64(x)?,
                None => return Err("invalid length 4, expected struct Layer with 6 elements".into()),
            }
            if let Some(x) = it.next() {
                l.variable = de_bool(x)?;
            }
            if a.len() > FIELDS.len() {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
        }
        _ => return Err(invalid(v, "struct Layer")),
    }
    // id 0 and guid 0 are none
    if l.id == Some(0) {
        l.id = None;
    }
    if l.guid.as_ref().map(|g| g.is_none()).unwrap_or(false) {
        l.guid = None;
    }
    Ok(l)
}

/// A command's `layers`: None when not given (or null), else at most 32 layers.
pub fn param(p: &Value, cmd: &str) -> Result<Option<Vec<Layer>>, String> {
    match p.get("layers") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Arr(a)) if a.len() <= MAX_LAYERS => {
            let mut out = Vec::with_capacity(a.len());
            for x in a {
                out.push(de_layer(x).map_err(|e| format!("{}: `layers`: {}", cmd, e))?);
            }
            Ok(Some(out))
        }
        Some(_) => Err(format!("{}: `layers` is a list of at most {} layers", cmd, MAX_LAYERS)),
    }
}

// ---------------------------------------------------------------- the file's form

/// A layer as the file holds it, read back: its material as the file names it (a GUID, or
/// a name a hand-made file may hold), resolved by `mat`.
pub fn from_file(v: &Value, mat: &dyn Fn(&str) -> String) -> Layer {
    let id = v.get("id").and_then(|x| x.as_u64()).filter(|n| *n != 0);
    let guid = match v.get("guid") {
        Some(Value::Str(s)) => Some(GRef::Guid(s.clone())),
        Some(Value::Num(Num::U(n))) if *n != 0 => Some(GRef::Id(*n)),
        _ => None,
    };
    let material = match v.get("material").and_then(|m| m.as_str()) {
        Some(m) if !m.is_empty() => mat(m),
        _ => String::new(),
    };
    Layer {
        id,
        guid,
        function: v.get("function").and_then(|f| f.as_str()).unwrap_or("structure").to_string(),
        material,
        thickness: v.get("thickness").and_then(|x| x.as_f64()).unwrap_or(0.0),
        variable: v.get("variable").and_then(|x| x.as_bool()).unwrap_or(false),
    }
}

/// A layer as the file holds it: id, guid, function, its material's GUID (or "" for none),
/// thickness, and `variable` when it is.
pub fn to_file(l: &Layer, material_ref: &str) -> Value {
    let mut m = Map::new();
    if let Some(id) = l.id {
        m.insert("id", Value::u(id));
    }
    if let Some(g) = &l.guid {
        m.insert("guid", g.value());
    }
    m.insert("function", Value::s(&l.function));
    m.insert("material", Value::s(material_ref));
    m.insert("thickness", Value::f(l.thickness));
    if l.variable {
        m.insert("variable", Value::Bool(true));
    }
    Value::Obj(m)
}
