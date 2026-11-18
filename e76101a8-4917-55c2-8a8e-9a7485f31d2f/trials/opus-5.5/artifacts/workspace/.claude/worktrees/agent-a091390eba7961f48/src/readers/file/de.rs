//! Reading a value as serde reads it into the original's types: the same messages where it is of
//! the wrong shape, the fields it doesn't know listed (JSON pointers), and the value written back
//! as the original writes it (its defaults filled, in its fields' order, what it leaves out left out).

use super::schema::{registry, Def, Enum, Skip, Struct, Ty};
use crate::json::{Map, Num, Value};

pub type R<T> = Result<T, String>;

/// Where a value is read: inside an element (serde's buffered content, whose sequences say "N
/// elements in sequence") or in the file's other sections (serde_json's own value).
pub struct Ctx {
    pub content: bool,
    pub path: Vec<String>,
    pub left: Vec<String>,
}

thread_local! {
    /// The format of the file being read (what some of its values mean changed with it).
    static FILE_FORMAT: std::cell::Cell<u64> = const { std::cell::Cell::new(super::FORMAT) };
}

pub fn set_file_format(f: u64) {
    FILE_FORMAT.with(|c| c.set(f));
}

fn file_format() -> u64 {
    FILE_FORMAT.with(|c| c.get())
}

/// A pen for a line `w` wide in a file of before format 4 (its overrides' weights were widths, a
/// fifth of a mm each): the one whose width is nearest.
fn pen_of_width(w: f64) -> u64 {
    const WIDTHS: [f64; 16] = [0.1, 0.13, 0.15, 0.18, 0.2, 0.22, 0.25, 0.28, 0.3, 0.35, 0.4, 0.5, 0.7, 1.0, 1.4, 2.0];
    let mm = w / 5.0;
    let mut best = 0;
    for (i, x) in WIDTHS.iter().enumerate() {
        if (x - mm).abs() < (WIDTHS[best] - mm).abs() {
            best = i;
        }
    }
    best as u64 + 1
}

impl Ctx {
    pub fn new(content: bool) -> Ctx {
        Ctx { content, path: Vec::new(), left: Vec::new() }
    }
    pub fn pointer(&self, last: &str) -> String {
        let mut s = String::new();
        for p in self.path.iter().map(|p| p.as_str()).chain(std::iter::once(last)) {
            s.push('/');
            s.push_str(&p.replace('~', "~0").replace('/', "~1"));
        }
        s
    }
    pub fn leave(&mut self, key: &str) {
        let p = self.pointer(key);
        self.left.push(p);
    }
}

// ---------------------------------------------------------------- serde's messages

/// How serde shows a float: Rust's Display, with `.0` where it has no point.
pub fn float_text(f: f64) -> String {
    let s = format!("{}", f);
    if f.is_finite() && !s.contains('.') {
        s + ".0"
    } else {
        s
    }
}

/// A value as serde names it in an "invalid type" message.
pub fn unexpected(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => format!("boolean `{}`", b),
        Value::Num(Num::U(u)) => format!("integer `{}`", u),
        Value::Num(Num::I(i)) => format!("integer `{}`", i),
        Value::Num(Num::F(f)) => format!("floating point `{}`", crate::json::fmt_f64(*f)),
        Value::Str(s) => format!("string {:?}", s),
        Value::Arr(_) => "sequence".into(),
        Value::Obj(_) => "map".into(),
    }
}

pub fn invalid_type(v: &Value, exp: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), exp)
}

pub fn missing(f: &str) -> String {
    format!("missing field `{}`", f)
}

/// serde's list of what it expected: `a`, `a` or `b`, one of `a`, `b`, `c`.
pub fn one_of(names: &[&str]) -> String {
    match names.len() {
        0 => "nothing".into(),
        1 => format!("`{}`", names[0]),
        2 => format!("`{}` or `{}`", names[0], names[1]),
        _ => format!("one of {}", names.iter().map(|n| format!("`{}`", n)).collect::<Vec<_>>().join(", ")),
    }
}

pub fn unknown_variant(v: &str, names: &[&str]) -> String {
    if names.is_empty() {
        format!("unknown variant `{}`, there are no variants", v)
    } else {
        format!("unknown variant `{}`, expected {}", v, one_of(names))
    }
}

/// A sequence longer than what took from it.
fn too_long(cx: &Ctx, len: usize, took: usize) -> String {
    if cx.content {
        if took == 1 {
            format!("invalid length {}, expected 1 element in sequence", len)
        } else {
            format!("invalid length {}, expected {} elements in sequence", len, took)
        }
    } else {
        format!("invalid length {}, expected fewer elements in array", len)
    }
}

/// The entries of a map in the order serde visits a JSON object's (sorted by key).
pub fn sorted(m: &Map) -> Vec<(&String, &Value)> {
    let mut v: Vec<(&String, &Value)> = m.iter().collect();
    v.sort_by(|a, b| a.0.cmp(b.0));
    // a key twice keeps the last
    v.dedup_by(|b, a| {
        if a.0 == b.0 {
            a.1 = b.1;
            true
        } else {
            false
        }
    });
    v
}

/// A value as serde_json's own value holds it: every map's keys sorted.
pub fn kept(v: &Value) -> Value {
    v.clone().sorted()
}

// ---------------------------------------------------------------- GUIDs and ids

/// A GUID as the original reads one: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, in braces or not, in
/// any case, blanks round it let go; lowercase.
pub fn parse_guid(s: &str) -> Option<String> {
    let t = s.trim();
    let t = match t.strip_prefix('{') {
        Some(x) => x.strip_suffix('}')?,
        None => t,
    };
    let b = t.as_bytes();
    if b.len() != 36 {
        return None;
    }
    for (i, c) in b.iter().enumerate() {
        let dash = matches!(i, 8 | 13 | 18 | 23);
        if dash != (*c == b'-') || (!dash && !c.is_ascii_hexdigit()) {
            return None;
        }
    }
    Some(t.to_ascii_lowercase())
}

pub enum RefV {
    Guid(String),
    Id(u64),
}

/// What an element points at, as the original reads it: a GUID, or an id (a whole number, or
/// digits in a string).
pub fn parse_ref(v: &Value) -> R<RefV> {
    match v {
        Value::Str(s) => {
            if let Some(g) = parse_guid(s) {
                return Ok(RefV::Guid(g));
            }
            let t = s.trim();
            if !t.is_empty() && t.bytes().all(|c| c.is_ascii_digit()) {
                if let Ok(n) = t.parse::<u64>() {
                    return Ok(RefV::Id(n));
                }
            }
            Err(format!("`{}` is not a GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or an id", s))
        }
        Value::Num(Num::U(n)) => Ok(RefV::Id(*n)),
        Value::Num(Num::I(n)) => Err(format!("{} is not an element id", n)),
        Value::Num(Num::F(f)) => {
            if *f >= 0.0 && f.fract() == 0.0 && *f < 18446744073709551616.0 {
                Ok(RefV::Id(*f as u64))
            } else {
                Err(format!("{} is not an element id", f))
            }
        }
        _ => Err(invalid_type(v, "an element's GUID, or its id")),
    }
}

pub fn ref_value(r: RefV) -> Value {
    match r {
        RefV::Guid(g) => Value::Str(g),
        RefV::Id(n) => Value::u(n),
    }
}

/// A GUID that must be one (an element's own, a library entry's): an id is refused.
pub fn own_guid(v: &Value) -> R<String> {
    match parse_ref(v)? {
        RefV::Guid(g) => Ok(g),
        RefV::Id(n) => Err(format!("{} is an id, not a GUID", n)),
    }
}

// ---------------------------------------------------------------- types read by code of their own

pub const CUSTOM: &[&str] = &["LibKind", "Colour", "Pen", "Weight", "MemberElement"];

/// A colour as a file may give it: `[r, g, b]` (whole numbers 0 to 255) or `"#rrggbb"`.
pub fn colour_of(v: &Value) -> Option<[u64; 3]> {
    match v {
        Value::Arr(a) if a.len() == 3 => {
            let mut c = [0u64; 3];
            for (i, x) in a.iter().enumerate() {
                match x {
                    Value::Num(Num::U(u)) if *u <= 255 => c[i] = *u,
                    _ => return None,
                }
            }
            Some(c)
        }
        Value::Str(s) => {
            let h = s.strip_prefix('#')?;
            if h.len() != 6 || !h.bytes().all(|b| b.is_ascii_hexdigit()) {
                return None;
            }
            let n = u32::from_str_radix(h, 16).ok()?;
            Some([(n >> 16) as u64 & 255, (n >> 8) as u64 & 255, n as u64 & 255])
        }
        _ => None,
    }
}

fn custom(name: &str, v: &Value, cx: &mut Ctx) -> R<Value> {
    match name {
        "MemberElement" => {
            // an element of a detail group: the model's `Element`, read as serde reads one
            let was = cx.content;
            cx.content = true;
            let r = super::read_member_element(v, cx);
            cx.content = was;
            r
        }
        "Colour" => match colour_of(v) {
            Some(c) => Ok(Value::Arr(c.iter().map(|x| Value::u(*x)).collect())),
            None => Err(format!(
                "{} isn't a colour: [r, g, b], each 0 to 255, or \"#rrggbb\"",
                kept(v).to_compact()
            )),
        },
        "Weight" if file_format() < 4 => match v {
            Value::Num(n) => Ok(Value::u(pen_of_width(n.as_f64()))),
            _ => Err(invalid_type(v, "f64")),
        },
        "Pen" | "Weight" => match v {
            Value::Num(n) => {
                let x = n.as_f64();
                if x >= 0.0 && x <= 16.0 && x.fract() == 0.0 {
                    Ok(Value::u(x as u64))
                } else {
                    Err(format!("a line weight is a pen, a whole number from 0 (a hairline) to 16, not {}", x))
                }
            }
            _ => Err(invalid_type(v, "f64")),
        },
        "LibKind" => match v {
            Value::Str(s) => {
                if super::LIB_KINDS.contains(&s.as_str()) || s.starts_with("type:") {
                    Ok(v.clone())
                } else {
                    Err(format!("`{}` isn't a kind of library entry", s))
                }
            }
            _ => Err(invalid_type(v, "a string")),
        },
        _ => panic!("no custom type {}", name),
    }
}

// ---------------------------------------------------------------- reading

fn int_name(signed: bool, bits: u32) -> &'static str {
    match (signed, bits) {
        (false, 0) => "usize",
        (false, 8) => "u8",
        (false, 16) => "u16",
        (false, 32) => "u32",
        (false, _) => "u64",
        (true, 8) => "i8",
        (true, 16) => "i16",
        (true, 32) => "i32",
        (true, _) => "i64",
    }
}

fn de_uint(v: &Value, bits: u32) -> R<Value> {
    let name = int_name(false, bits);
    let max: u64 = match bits {
        8 => u8::MAX as u64,
        16 => u16::MAX as u64,
        32 => u32::MAX as u64,
        _ => u64::MAX,
    };
    match v {
        Value::Num(Num::U(u)) => {
            if *u <= max {
                Ok(Value::u(*u))
            } else {
                Err(format!("invalid value: integer `{}`, expected {}", u, name))
            }
        }
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected {}", i, name)),
        _ => Err(invalid_type(v, name)),
    }
}

fn de_int(v: &Value, bits: u32) -> R<Value> {
    let name = int_name(true, bits);
    let (min, max): (i64, i64) = match bits {
        8 => (i8::MIN as i64, i8::MAX as i64),
        16 => (i16::MIN as i64, i16::MAX as i64),
        32 => (i32::MIN as i64, i32::MAX as i64),
        _ => (i64::MIN, i64::MAX),
    };
    match v {
        Value::Num(Num::U(u)) => {
            if *u <= max as u64 {
                Ok(Value::u(*u))
            } else {
                Err(format!("invalid value: integer `{}`, expected {}", u, name))
            }
        }
        Value::Num(Num::I(i)) => {
            if *i >= min && *i <= max {
                Ok(Value::i(*i))
            } else {
                Err(format!("invalid value: integer `{}`, expected {}", i, name))
            }
        }
        _ => Err(invalid_type(v, name)),
    }
}

/// The name serde gives a type in "invalid type: …, expected X".
pub fn expecting(t: &Ty) -> String {
    match t {
        Ty::F64 => "f64".into(),
        Ty::F32 => "f32".into(),
        Ty::Bool => "a boolean".into(),
        Ty::Str => "a string".into(),
        Ty::U(b) => int_name(false, *b).into(),
        Ty::I(b) => int_name(true, *b).into(),
        Ty::Ref => "an element's GUID, or its id".into(),
        Ty::Any => "any valid JSON value".into(),
        Ty::Opt(x) | Ty::Some(x) => expecting(x),
        Ty::Vec(_) | Ty::Set(_) => "a sequence".into(),
        Ty::Arr(_, n) => format!("an array of length {}", n),
        Ty::Tup(ts) => format!("a tuple of size {}", ts.len()),
        Ty::Map(_) | Ty::EnumMap(..) | Ty::RefMap(_) => "a map".into(),
        Ty::Named(n) => match registry().get(n) {
            Def::Struct(s) if s.tuple => format!("tuple struct {}", s.name),
            Def::Struct(s) => format!("struct {}", s.name),
            Def::Enum(_) => "string or map".into(),
            Def::Untagged(_) => format!("untagged enum {}", n),
            Def::Alias(t) => expecting(t),
            Def::Custom => match n.as_str() {
                "Pen" | "Weight" => "f64".into(),
                "LibKind" => "a string".into(),
                "MemberElement" => "internally tagged enum Element".into(),
                _ => n.clone(),
            },
        },
    }
}

/// How a set's members sort, as the original's `BTreeSet` keeps them: strings by their bytes,
/// numbers by value, an enum's variants in its order.
fn set_order(t: &Ty, a: &Value, b: &Value) -> std::cmp::Ordering {
    match t {
        Ty::Str => a.as_str().cmp(&b.as_str()),
        Ty::U(_) | Ty::I(_) | Ty::F64 | Ty::F32 => {
            a.as_f64().partial_cmp(&b.as_f64()).unwrap_or(std::cmp::Ordering::Equal)
        }
        Ty::Named(n) => match registry().get(n) {
            Def::Enum(e) => {
                let at = |v: &Value| v.as_str().and_then(|s| e.variants.iter().position(|x| x.out == s));
                at(a).cmp(&at(b))
            }
            Def::Alias(t) => set_order(t, a, b),
            _ => a.to_compact().cmp(&b.to_compact()),
        },
        _ => a.to_compact().cmp(&b.to_compact()),
    }
}

pub fn de(v: &Value, t: &Ty, cx: &mut Ctx) -> R<Value> {
    match t {
        Ty::F64 => match v {
            Value::Num(n) => Ok(Value::f(n.as_f64())),
            _ => Err(invalid_type(v, "f64")),
        },
        Ty::F32 => match v {
            Value::Num(n) => Ok(Value::f(f32_back(n.as_f64() as f32))),
            _ => Err(invalid_type(v, "f32")),
        },
        Ty::Bool => match v {
            Value::Bool(_) => Ok(v.clone()),
            _ => Err(invalid_type(v, "a boolean")),
        },
        Ty::Str => match v {
            Value::Str(_) => Ok(v.clone()),
            _ => Err(invalid_type(v, "a string")),
        },
        Ty::U(b) => de_uint(v, *b),
        Ty::I(b) => de_int(v, *b),
        Ty::Ref => Ok(ref_value(parse_ref(v)?)),
        Ty::Any => Ok(kept(v)),
        Ty::Opt(x) => match v {
            Value::Null => Ok(Value::Null),
            _ => de(v, x, cx),
        },
        Ty::Some(x) => de(v, x, cx),
        Ty::Vec(x) => match v {
            Value::Arr(a) => {
                let mut out = Vec::with_capacity(a.len());
                for (i, e) in a.iter().enumerate() {
                    cx.path.push(i.to_string());
                    let r = de(e, x, cx);
                    cx.path.pop();
                    out.push(r?);
                }
                Ok(Value::Arr(out))
            }
            _ => Err(invalid_type(v, "a sequence")),
        },
        Ty::Set(x) => {
            let mut out = match de(v, &Ty::Vec(x.clone()), cx)? {
                Value::Arr(a) => a,
                _ => unreachable!(),
            };
            out.sort_by(|a, b| set_order(x, a, b));
            out.dedup();
            Ok(Value::Arr(out))
        }
        Ty::Arr(x, n) => {
            let exp = format!("an array of length {}", n);
            match v {
                Value::Arr(a) => {
                    let mut out = Vec::with_capacity(*n);
                    for i in 0..*n {
                        match a.get(i) {
                            Some(e) => {
                                cx.path.push(i.to_string());
                                let r = de(e, x, cx);
                                cx.path.pop();
                                out.push(r?);
                            }
                            None => return Err(format!("invalid length {}, expected {}", i, exp)),
                        }
                    }
                    if a.len() > *n {
                        return Err(too_long(cx, a.len(), *n));
                    }
                    Ok(Value::Arr(out))
                }
                _ => Err(invalid_type(v, &exp)),
            }
        }
        Ty::Tup(ts) => {
            let exp = format!("a tuple of size {}", ts.len());
            match v {
                Value::Arr(a) => {
                    let mut out = Vec::new();
                    for (i, x) in ts.iter().enumerate() {
                        match a.get(i) {
                            Some(e) => {
                                cx.path.push(i.to_string());
                                let r = de(e, x, cx);
                                cx.path.pop();
                                out.push(r?);
                            }
                            None => return Err(format!("invalid length {}, expected {}", i, exp)),
                        }
                    }
                    if a.len() > ts.len() {
                        return Err(too_long(cx, a.len(), ts.len()));
                    }
                    Ok(Value::Arr(out))
                }
                _ => Err(invalid_type(v, &exp)),
            }
        }
        Ty::Map(x) => match v {
            Value::Obj(m) => {
                let mut out = Map::new();
                for (k, e) in sorted(m) {
                    cx.path.push(k.clone());
                    let r = de(e, x, cx);
                    cx.path.pop();
                    out.items.push((k.clone(), r?));
                }
                Ok(Value::Obj(out))
            }
            _ => Err(invalid_type(v, "a map")),
        },
        Ty::RefMap(x) => match v {
            Value::Obj(m) => {
                let mut out = Map::new();
                for (k, e) in sorted(m) {
                    // the key first, as serde reads a map's
                    let key = match parse_ref(&Value::Str(k.clone()))? {
                        RefV::Guid(g) => g,
                        RefV::Id(n) => n.to_string(),
                    };
                    cx.path.push(k.clone());
                    let r = de(e, x, cx);
                    cx.path.pop();
                    out.insert(&key, r?);
                }
                out.sort();
                Ok(Value::Obj(out))
            }
            _ => Err(invalid_type(v, "a map")),
        },
        Ty::EnumMap(en, x) => match v {
            Value::Obj(m) => {
                let e = match registry().get(en) {
                    Def::Enum(e) => e,
                    _ => panic!("{} isn't an enum", en),
                };
                let names: Vec<&str> = e.variants.iter().map(|x| x.name.as_str()).collect();
                let mut got: Vec<(usize, Value)> = Vec::new();
                for (k, ev) in sorted(m) {
                    let i = match e.variants.iter().position(|var| var.name == *k) {
                        Some(i) => i,
                        None => return Err(unknown_variant(k, &names)),
                    };
                    cx.path.push(k.clone());
                    let r = de(ev, x, cx);
                    cx.path.pop();
                    let r = r?;
                    got.retain(|(j, _)| e.variants[*j].out != e.variants[i].out);
                    got.push((i, r));
                }
                got.sort_by_key(|(i, _)| *i);
                let mut out = Map::new();
                for (i, r) in got {
                    out.items.push((e.variants[i].out.clone(), r));
                }
                Ok(Value::Obj(out))
            }
            _ => Err(invalid_type(v, "a map")),
        },
        Ty::Named(n) => match registry().get(n) {
            Def::Struct(s) => de_struct(s, v, cx),
            Def::Enum(e) => de_enum(e, v, cx),
            Def::Untagged(ts) => {
                for x in ts {
                    let mut sub = Ctx::new(cx.content);
                    sub.path = cx.path.clone();
                    if let Ok(r) = de(v, x, &mut sub) {
                        cx.left.extend(sub.left);
                        return Ok(r);
                    }
                }
                Err(format!("data did not match any variant of untagged enum {}", n))
            }
            Def::Alias(t) => de(v, t, cx),
            Def::Custom => custom(n, v, cx),
        },
    }
}

/// An f32 as serde_json writes it (its shortest digits), held as the f64 those digits read as.
pub fn f32_back(x: f32) -> f64 {
    if !x.is_finite() {
        return x as f64;
    }
    format!("{:e}", x).parse::<f64>().unwrap_or(x as f64)
}

fn de_enum(e: &Enum, v: &Value, cx: &mut Ctx) -> R<Value> {
    let names: Vec<&str> = e.variants.iter().map(|x| x.name.as_str()).collect();
    let find = |s: &str| e.variants.iter().find(|x| x.name == s);
    match v {
        Value::Str(s) => match find(s) {
            Some(var) => match &var.data {
                None => Ok(Value::Str(var.out.clone())),
                Some(t) => Err(format!("invalid type: unit variant, expected {}", newtype_expect(t))),
            },
            None => Err(unknown_variant(s, &names)),
        },
        Value::Obj(m) => {
            if m.len() != 1 {
                return Err("invalid value: map, expected map with a single key".into());
            }
            let (k, x) = &m.items[0];
            match find(k) {
                Some(var) => match &var.data {
                    None => match x {
                        Value::Null => Ok(Value::Str(var.out.clone())),
                        _ => Err(invalid_type(x, "unit")),
                    },
                    Some(t) => {
                        cx.path.push(k.clone());
                        let r = de(x, t, cx);
                        cx.path.pop();
                        let mut out = Map::new();
                        out.insert(&var.out, r?);
                        Ok(Value::Obj(out))
                    }
                },
                None => Err(unknown_variant(k, &names)),
            }
        }
        _ => Err(invalid_type(v, "string or map")),
    }
}

fn newtype_expect(_t: &Ty) -> String {
    "newtype variant".into()
}

/// A struct read from a map (its keys in sorted order, those it doesn't know left out) or a
/// sequence (its fields in order), its defaults filled; written back in its fields' order.
pub fn de_struct(s: &Struct, v: &Value, cx: &mut Ctx) -> R<Value> {
    let full = read_struct(s, v, cx)?;
    if let Some(h) = &s.hook {
        let mut full = full;
        if let Some(out) = super::hooks::run(h, &mut full, cx)? {
            return Ok(out);
        }
        return Ok(write_struct(s, &full));
    }
    Ok(write_struct(s, &full))
}

/// Every field's value (defaults filled), in declaration order.
pub fn read_struct(s: &Struct, v: &Value, cx: &mut Ctx) -> R<Map> {
    let n = s.fields.len();
    let mut got: Vec<Option<Value>> = vec![None; n];
    let expecting = if s.tuple { format!("tuple struct {}", s.name) } else { format!("struct {}", s.name) };
    match v {
        Value::Obj(m) if !s.tuple => {
            for (k, x) in sorted(m) {
                let idx = s.fields.iter().position(|f| f.name == *k || f.aliases.iter().any(|a| a == k));
                match idx {
                    Some(i) => {
                        cx.path.push(k.clone());
                        let r = de(x, &s.fields[i].ty, cx);
                        cx.path.pop();
                        got[i] = Some(r?);
                    }
                    None => cx.leave(k),
                }
            }
            for (i, f) in s.fields.iter().enumerate() {
                if got[i].is_none() {
                    match &f.default {
                        Some(d) => got[i] = Some(d.clone()),
                        None => return Err(missing(&f.name)),
                    }
                }
            }
        }
        Value::Arr(a) => {
            for (i, f) in s.fields.iter().enumerate() {
                match a.get(i) {
                    Some(x) => {
                        cx.path.push(i.to_string());
                        let r = de(x, &f.ty, cx);
                        cx.path.pop();
                        got[i] = Some(r?);
                    }
                    None => match &f.default {
                        Some(d) if !s.tuple => got[i] = Some(d.clone()),
                        _ => {
                            let plural = if n == 1 { "" } else { "s" };
                            return Err(format!("invalid length {}, expected {} with {} element{}", i, expecting, n, plural));
                        }
                    },
                }
            }
            if a.len() > n {
                return Err(too_long(cx, a.len(), n));
            }
        }
        _ => return Err(invalid_type(v, &expecting)),
    }
    let mut out = Map::new();
    for (f, g) in s.fields.iter().zip(got) {
        out.items.push((f.name.clone(), g.unwrap()));
    }
    Ok(out)
}

/// A struct's fields as the original writes them: in order, those its rules leave out left out.
pub fn write_struct(s: &Struct, full: &Map) -> Value {
    if s.tuple {
        return Value::Arr(full.items.iter().map(|(_, v)| v.clone()).collect());
    }
    let mut out = Map::new();
    for f in &s.fields {
        if f.hidden {
            continue;
        }
        let v = match full.get(&f.name) {
            Some(v) => v,
            None => continue,
        };
        let skip = match &f.skip {
            Skip::Never => false,
            Skip::None => v.is_null(),
            Skip::Empty => match v {
                Value::Arr(a) => a.is_empty(),
                Value::Obj(m) => m.is_empty(),
                Value::Str(s) => s.is_empty(),
                Value::Null => true,
                _ => false,
            },
            Skip::False => matches!(v, Value::Bool(false)),
            Skip::Eq(d) => v == d,
        };
        if !skip {
            out.items.push((f.name.clone(), v.clone()));
        }
    }
    // anything a hook added past the declared fields
    for (k, v) in &full.items {
        if !s.fields.iter().any(|f| f.name == *k) {
            out.items.push((k.clone(), v.clone()));
        }
    }
    Value::Obj(out)
}
