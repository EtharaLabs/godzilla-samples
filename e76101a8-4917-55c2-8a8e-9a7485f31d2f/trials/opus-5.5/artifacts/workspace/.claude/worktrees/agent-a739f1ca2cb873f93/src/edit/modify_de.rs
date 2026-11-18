//! What `modify` reads a field's new value as: the checks the original's deserializer makes of
//! an element's fields (serde's messages, as serde_json words them), and the value as the file
//! keeps it.
//!
//! The original merges the fields given over the element and reads the whole back as the element
//! of its category: an object of the element's keys in name order, each read as its type says.
//! The first value that isn't one of its type gives the error, after `modify: element N: `.

use crate::json::{fmt_f64, Map, Num, Value};
use crate::project::Project;

/// A value's type, as the original's element structs have it.
pub enum T {
    F64,
    Bool,
    Str,
    U8,
    U32,
    U64,
    Usize,
    /// `Option<T>`: null is none.
    Opt(&'static T),
    /// A tuple struct of a name (`P2`) and its elements.
    Tup(&'static str, &'static [T]),
    /// `[T; N]`.
    Arr(usize, &'static T),
    Vec(&'static T),
    /// An enum of unit variants: the names it reads (aliases too).
    Enum(&'static [&'static str]),
    Struct(&'static Sd),
    /// A map of any values (`params`).
    Map,
    /// An element: its GUID or its id.
    Ref,
    /// Anything at all.
    Any,
}

/// A struct: its name, its fields in order, and whether it refuses fields it doesn't know.
pub struct Sd {
    pub name: &'static str,
    pub fields: &'static [Fd],
    pub deny: bool,
}

pub struct Fd {
    pub name: &'static str,
    pub t: T,
    /// Missing, it is an error (`missing field`); else it takes its default.
    pub required: bool,
    /// What the file holds when it's missing (None: it's left out).
    pub default: Option<fn() -> Value>,
    /// A null is written as null (else it's left out).
    pub keep_null: bool,
    /// Left out when this says so of its value.
    pub skip_if: Option<fn(&Value) -> bool>,
}

pub const F: T = T::F64;
pub const P2: T = T::Tup("P2", &[T::F64, T::F64]);
pub const P3: T = T::Arr(3, &T::F64);
pub const OPT_F: T = T::Opt(&T::F64);
pub const OPT_P2: T = T::Opt(&P2);
pub const OPT_STR: T = T::Opt(&T::Str);
pub const OPT_REF: T = T::Opt(&T::Ref);
pub const PTS: T = T::Vec(&P2);
pub const OPT_PTS: T = T::Opt(&PTS);
pub const LOOPS: T = T::Vec(&PTS);
pub const PTS3: T = T::Vec(&P3);
pub const SEG: T = T::Arr(2, &P2);
pub const OPT_SEG: T = T::Opt(&SEG);
pub const F2: T = T::Arr(2, &T::F64);
pub const OPT_F2: T = T::Opt(&F2);
pub const VEC_F: T = T::Vec(&T::F64);
pub const OPT_VEC_F: T = T::Opt(&VEC_F);
pub const OPT_U8X3: T = T::Opt(&T::Arr(3, &T::U8));
pub const VEC_STR: T = T::Vec(&T::Str);
pub const VEC_USIZE: T = T::Vec(&T::Usize);

/// How serde_json words a value that isn't what it expected.
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

pub fn invalid_type(v: &Value, exp: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), exp)
}

/// serde's list of what it expected: `a`, `a` or `b`, one of `a`, `b`, `c`.
fn one_of(names: &[&str]) -> String {
    match names.len() {
        0 => String::new(),
        1 => format!("`{}`", names[0]),
        2 => format!("`{}` or `{}`", names[0], names[1]),
        _ => format!("one of {}", names.iter().map(|n| format!("`{}`", n)).collect::<Vec<_>>().join(", ")),
    }
}

pub fn unknown_field(k: &str, names: &[&str]) -> String {
    if names.is_empty() {
        format!("unknown field `{}`, there are no fields", k)
    } else {
        format!("unknown field `{}`, expected {}", k, one_of(names))
    }
}

pub fn unknown_variant(k: &str, names: &[&str]) -> String {
    if names.is_empty() {
        format!("unknown variant `{}`, there are no variants", k)
    } else {
        format!("unknown variant `{}`, expected {}", k, one_of(names))
    }
}

fn in_seq(n: usize) -> String {
    if n == 1 {
        "1 element in sequence".into()
    } else {
        format!("{} elements in sequence", n)
    }
}

/// An element a value names: by its id (a number, or a string of one), or by its GUID.
#[derive(Clone, Debug, PartialEq)]
pub enum RefVal {
    Id(u64),
    Guid(u64),
}

impl RefVal {
    pub fn id(&self) -> u64 {
        match self {
            RefVal::Id(i) | RefVal::Guid(i) => *i,
        }
    }
}

/// An element reference as the original reads one; Err with its message.
pub fn de_ref(pr: &Project, v: &Value) -> Result<RefVal, String> {
    match v {
        Value::Num(Num::U(u)) => Ok(RefVal::Id(*u)),
        Value::Num(Num::I(i)) => Err(format!("{} is not an element id", i)),
        Value::Num(Num::F(f)) => {
            if f.is_finite() && *f >= 0.0 && f.fract() == 0.0 && *f < 18446744073709551616.0 {
                Ok(RefVal::Id(*f as u64))
            } else {
                Err(format!("{} is not an element id", f))
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                return Ok(RefVal::Id(id));
            }
            if let Some(g) = super::common::strict_guid(t) {
                if let Some(id) = pr.find_guid(&g) {
                    return Ok(RefVal::Guid(id));
                }
            }
            Err(format!("`{}` is not a GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or an id", s))
        }
        _ => Err(invalid_type(v, "an element's GUID, or its id")),
    }
}

fn de_uint(v: &Value, exp: &str, max: u64) -> Result<(), String> {
    match v {
        Value::Num(Num::U(u)) if *u <= max => Ok(()),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected {}", u, exp)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected {}", i, exp)),
        _ => Err(invalid_type(v, exp)),
    }
}

/// Reads a value as its type; Err with serde's message.
pub fn de(pr: &Project, v: &Value, t: &T) -> Result<(), String> {
    match t {
        T::F64 => match v {
            Value::Num(_) => Ok(()),
            _ => Err(invalid_type(v, "f64")),
        },
        T::Bool => match v {
            Value::Bool(_) => Ok(()),
            _ => Err(invalid_type(v, "a boolean")),
        },
        T::Str => match v {
            Value::Str(_) => Ok(()),
            _ => Err(invalid_type(v, "a string")),
        },
        T::U8 => de_uint(v, "u8", 255),
        T::U32 => de_uint(v, "u32", u32::MAX as u64),
        T::U64 => de_uint(v, "u64", u64::MAX),
        T::Usize => de_uint(v, "usize", u64::MAX),
        T::Opt(inner) => match v {
            Value::Null => Ok(()),
            _ => de(pr, v, inner),
        },
        T::Tup(name, elems) => match v {
            Value::Arr(a) => {
                for (i, e) in elems.iter().enumerate() {
                    match a.get(i) {
                        Some(x) => de(pr, x, e)?,
                        None => {
                            return Err(format!(
                                "invalid length {}, expected tuple struct {} with {} elements",
                                a.len(),
                                name,
                                elems.len()
                            ))
                        }
                    }
                }
                if a.len() > elems.len() {
                    return Err(format!("invalid length {}, expected {}", a.len(), in_seq(elems.len())));
                }
                Ok(())
            }
            _ => Err(invalid_type(v, &format!("tuple struct {}", name))),
        },
        T::Arr(n, e) => match v {
            Value::Arr(a) => {
                for i in 0..*n {
                    match a.get(i) {
                        Some(x) => de(pr, x, e)?,
                        None => return Err(format!("invalid length {}, expected an array of length {}", i, n)),
                    }
                }
                if a.len() > *n {
                    return Err(format!("invalid length {}, expected {}", a.len(), in_seq(*n)));
                }
                Ok(())
            }
            _ => Err(invalid_type(v, &format!("an array of length {}", n))),
        },
        T::Vec(e) => match v {
            Value::Arr(a) => {
                for x in a {
                    de(pr, x, e)?;
                }
                Ok(())
            }
            _ => Err(invalid_type(v, "a sequence")),
        },
        T::Enum(names) => match v {
            Value::Str(s) => {
                if names.contains(&s.as_str()) {
                    Ok(())
                } else {
                    Err(unknown_variant(s, names))
                }
            }
            Value::Obj(m) if m.len() == 1 => {
                let (k, x) = &m.items[0];
                if !names.contains(&k.as_str()) {
                    return Err(unknown_variant(k, names));
                }
                match x {
                    Value::Null => Ok(()),
                    _ => Err(invalid_type(x, "unit")),
                }
            }
            Value::Obj(_) => Err("invalid value: map, expected map with a single key".into()),
            _ => Err(invalid_type(v, "string or map")),
        },
        T::Struct(sd) => de_struct(pr, v, sd),
        T::Map => match v {
            Value::Obj(_) => Ok(()),
            _ => Err(invalid_type(v, "a map")),
        },
        T::Ref => de_ref(pr, v).map(|_| ()),
        T::Any => Ok(()),
    }
}

/// A struct from a map (its keys in name order) or a sequence (its fields in order). A struct of
/// no fields here is one whose insides aren't read: any map or sequence.
pub fn de_struct(pr: &Project, v: &Value, sd: &Sd) -> Result<(), String> {
    if sd.fields.is_empty() && matches!(v, Value::Obj(_) | Value::Arr(_)) {
        return Ok(());
    }
    match v {
        Value::Obj(m) => {
            let mut items: Vec<&(String, Value)> = m.items.iter().collect();
            items.sort_by(|a, b| a.0.cmp(&b.0));
            let names: Vec<&str> = sd.fields.iter().map(|f| f.name).collect();
            for (k, x) in items {
                match sd.fields.iter().find(|f| f.name == k) {
                    Some(f) => de(pr, x, &f.t)?,
                    None if sd.deny => return Err(unknown_field(k, &names)),
                    None => {}
                }
            }
            for f in sd.fields {
                if f.required && !m.contains(f.name) {
                    return Err(format!("missing field `{}`", f.name));
                }
            }
        }
        Value::Arr(a) => {
            for (i, f) in sd.fields.iter().enumerate() {
                match a.get(i) {
                    Some(x) => de(pr, x, &f.t)?,
                    None if f.required => {
                        return Err(format!(
                            "invalid length {}, expected struct {} with {} elements",
                            i,
                            sd.name,
                            sd.fields.len()
                        ))
                    }
                    None => {}
                }
            }
            if a.len() > sd.fields.len() {
                return Err(format!("invalid length {}, expected {}", a.len(), in_seq(sd.fields.len())));
            }
        }
        _ => return Err(invalid_type(v, &format!("struct {}", sd.name))),
    }
    if sd.name == "RawSketchLine" {
        let m = struct_map(v, sd);
        check_curve(&m)?;
    }
    Ok(())
}

/// A struct given as a map or as a sequence of its fields: as a map.
pub fn struct_map(v: &Value, sd: &Sd) -> Map {
    match v {
        Value::Obj(m) => m.clone(),
        Value::Arr(a) => {
            let mut m = Map::new();
            for (f, x) in sd.fields.iter().zip(a.iter()) {
                m.insert(f.name, x.clone());
            }
            m
        }
        _ => Map::new(),
    }
}

// ---------------------------------------------------------------- curves

/// What a line (a detail line, a sketch line) is, as the original says it.
pub const LINE_IS: &str = "a line is `start` and `end` (with `arc` degrees or a `through` point), `points` (with `arcs` and `closed`), `centre` and `radius`, `centre` and `radii` (with `angle` and `span`), `control` (with `knots`), or `fit` (with `start_tangent` and `end_tangent`)";

/// A curve's fields, in the order the structs hold them.
pub const CURVE_FIELDS: &[&str] = &[
    "start",
    "end",
    "through",
    "arc",
    "points",
    "arcs",
    "closed",
    "centre",
    "radius",
    "radii",
    "angle",
    "span",
    "control",
    "knots",
    "fit",
    "start_tangent",
    "end_tangent",
];

/// The kinds of curve: the fields that make one, and the fields that go with it.
const CURVE_KINDS: &[(&[&str], &[&str])] = &[
    (&["start", "end"], &["start", "end", "through", "arc"]),
    (&["points"], &["points", "arcs", "closed"]),
    (&["centre", "radius"], &["centre", "radius"]),
    (&["centre", "radii"], &["centre", "radii", "angle", "span"]),
    (&["control"], &["control", "knots"]),
    (&["fit"], &["fit", "start_tangent", "end_tangent"]),
];

fn curve_given(m: &Map, k: &str) -> bool {
    match m.get(k) {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(_) => true,
    }
}

/// A curve is one kind of curve, with only the fields that go with it.
pub fn check_curve(m: &Map) -> Result<(), String> {
    let Some((_, with)) = CURVE_KINDS.iter().find(|(makes, _)| makes.iter().all(|k| curve_given(m, k))) else {
        return Err(LINE_IS.to_string());
    };
    for k in CURVE_FIELDS {
        if curve_given(m, k) && !with.contains(k) {
            return Err(format!("`{}` doesn't go with the {} given: {}", k, with.join(", "), LINE_IS));
        }
    }
    if curve_given(m, "through") && curve_given(m, "arc") {
        return Err("give an arc's `through` point or its `arc` turn, not both".into());
    }
    Ok(())
}

/// The turn of the arc from `s` to `e` through `p`, degrees counter-clockwise; None where `p` is
/// within a millimetre of the line through them (a straight line).
pub fn arc_through(s: [f64; 2], e: [f64; 2], p: [f64; 2]) -> Option<f64> {
    let len = ((e[0] - s[0]).powi(2) + (e[1] - s[1]).powi(2)).sqrt();
    let side = (e[0] - s[0]) * (p[1] - s[1]) - (e[1] - s[1]) * (p[0] - s[0]);
    if len == 0.0 || (side / len).abs() <= 1.0 {
        return None;
    }
    let a = [s[0] - p[0], s[1] - p[1]];
    let b = [e[0] - p[0], e[1] - p[1]];
    let dot = a[0] * b[0] + a[1] * b[1];
    let cr = a[0] * b[1] - a[1] * b[0];
    let ang = cr.abs().atan2(dot);
    let v = (2.0 * (std::f64::consts::PI - ang)).to_degrees();
    Some(if side < 0.0 { v } else { -v })
}

/// A curve as the file keeps it: a `through` point made the arc's turn, a turn of 0 none.
pub fn normalize_curve(m: &mut Map) {
    if curve_given(m, "through") {
        let s = m.get("start").and_then(p2_of);
        let e = m.get("end").and_then(p2_of);
        let p = m.get("through").and_then(p2_of);
        m.remove("through");
        if let (Some(s), Some(e), Some(p)) = (s, e, p) {
            match arc_through(s, e, p) {
                Some(a) => m.insert("arc", Value::f(a)),
                None => {
                    m.remove("arc");
                }
            }
        }
    }
    if m.get("arc").and_then(|a| a.as_f64()) == Some(0.0) {
        m.remove("arc");
    }
}

fn p2_of(v: &Value) -> Option<[f64; 2]> {
    let a = v.as_arr()?;
    Some([a.first()?.as_f64()?, a.get(1)?.as_f64()?])
}

/// JSON merge patch: null takes a key away, objects merge, the rest replaces.
pub fn merge_patch(target: &mut Value, patch: &Value) {
    if let Value::Obj(pm) = patch {
        if !matches!(target, Value::Obj(_)) {
            *target = Value::obj();
        }
        let tm = target.as_obj_mut().unwrap();
        for (k, v) in &pm.items {
            if v.is_null() {
                tm.remove(k);
            } else {
                let mut cur = tm.get(k).cloned().unwrap_or(Value::Null);
                merge_patch(&mut cur, v);
                tm.insert(k, cur);
            }
        }
    } else {
        *target = patch.clone();
    }
}

/// The value as the file keeps it: numbers of `f64` fields as floats, element references as
/// GUIDs, enum variants by their own names (`center` is `centre`).
pub fn store(pr: &Project, v: &Value, t: &T) -> Value {
    match t {
        T::F64 => match v {
            Value::Num(n) => Value::f(n.as_f64()),
            _ => v.clone(),
        },
        T::Opt(inner) => match v {
            Value::Null => Value::Null,
            _ => store(pr, v, inner),
        },
        T::Tup(_, elems) => match v {
            Value::Arr(a) => Value::Arr(a.iter().zip(elems.iter()).map(|(x, e)| store(pr, x, e)).collect()),
            _ => v.clone(),
        },
        T::Arr(_, e) | T::Vec(e) => match v {
            Value::Arr(a) => Value::Arr(a.iter().map(|x| store(pr, x, e)).collect()),
            _ => v.clone(),
        },
        T::Enum(_) => {
            let name = match v {
                Value::Str(s) => s.clone(),
                Value::Obj(m) if m.len() == 1 => m.items[0].0.clone(),
                _ => return v.clone(),
            };
            Value::Str(canonical_variant(&name).to_string())
        }
        T::Struct(sd) => {
            if sd.fields.is_empty() {
                return v.clone();
            }
            let m = match v {
                Value::Obj(_) | Value::Arr(_) => struct_map(v, sd),
                _ => return v.clone(),
            };
            let mut out = Map::new();
            for f in sd.fields {
                if let Some(x) = m.get(f.name) {
                    if !(x.is_null() && !f.keep_null) && !f.skip_if.map(|s| s(x)).unwrap_or(false) {
                        out.insert(f.name, store(pr, x, &f.t));
                    }
                } else if let Some(d) = f.default {
                    out.insert(f.name, d());
                }
            }
            for (k, x) in &m.items {
                if !out.contains(k) && !sd.deny && !sd.fields.iter().any(|f| f.name == k) {
                    out.insert(k, x.clone());
                }
            }
            Value::Obj(out)
        }
        T::Ref => match de_ref(pr, v) {
            Ok(r) => match pr.guid_of(r.id()) {
                Some(g) => Value::Str(g),
                None => v.clone(),
            },
            Err(_) => v.clone(),
        },
        _ => v.clone(),
    }
}

/// Whether a type holds element references.
pub fn has_ref(t: &T) -> bool {
    match t {
        T::Ref => true,
        T::Opt(i) | T::Arr(_, i) | T::Vec(i) => has_ref(i),
        T::Tup(_, es) => es.iter().any(has_ref),
        T::Struct(sd) => sd.fields.iter().any(|f| has_ref(&f.t)),
        _ => false,
    }
}

/// Whether a value given names an element by its id somewhere (as `elements` then shows it).
pub fn ref_by_id(pr: &Project, v: &Value, t: &T) -> bool {
    match (t, v) {
        (T::Ref, _) => matches!(de_ref(pr, v), Ok(RefVal::Id(_))),
        (T::Opt(i), _) => !v.is_null() && ref_by_id(pr, v, i),
        (T::Arr(_, i) | T::Vec(i), Value::Arr(a)) => a.iter().any(|x| ref_by_id(pr, x, i)),
        (T::Struct(sd), Value::Obj(_) | Value::Arr(_)) => {
            let m = struct_map(v, sd);
            sd.fields.iter().any(|f| m.get(f.name).map(|x| ref_by_id(pr, x, &f.t)).unwrap_or(false))
        }
        _ => false,
    }
}

/// A value given as the session holds it until the file is read again: as the file keeps it, but
/// an element named by its id is that id.
pub fn reply_form(pr: &Project, v: &Value, t: &T) -> Value {
    match t {
        T::Ref => match de_ref(pr, v) {
            Ok(RefVal::Id(n)) => Value::u(n),
            _ => store(pr, v, t),
        },
        T::Opt(inner) => match v {
            Value::Null => Value::Null,
            _ => reply_form(pr, v, inner),
        },
        T::Arr(_, e) | T::Vec(e) => match v {
            Value::Arr(a) => Value::Arr(a.iter().map(|x| reply_form(pr, x, e)).collect()),
            _ => v.clone(),
        },
        T::Struct(sd) if !sd.fields.is_empty() => {
            let m = match v {
                Value::Obj(_) | Value::Arr(_) => struct_map(v, sd),
                _ => return v.clone(),
            };
            let mut out = Map::new();
            for f in sd.fields {
                if let Some(x) = m.get(f.name) {
                    if !(x.is_null() && !f.keep_null) && !f.skip_if.map(|s| s(x)).unwrap_or(false) {
                        out.insert(f.name, reply_form(pr, x, &f.t));
                    }
                } else if let Some(d) = f.default {
                    out.insert(f.name, d());
                }
            }
            Value::Obj(out)
        }
        _ => store(pr, v, t),
    }
}

/// The name a variant is kept by (an alias read as the variant it stands for).
pub fn canonical_variant(s: &str) -> &str {
    match s {
        "center" => "centre",
        "core-center" => "core-centre",
        _ => s,
    }
}
