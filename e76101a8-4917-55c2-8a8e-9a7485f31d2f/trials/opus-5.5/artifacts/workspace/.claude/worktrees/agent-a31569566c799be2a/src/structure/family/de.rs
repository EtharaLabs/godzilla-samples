//! Reading a `family` command's parts as the original's serde reads them from a JSON value:
//! objects key by key in name order (as serde_json's map holds them), unknown keys refused, a
//! missing one said after the others, and sequences field by field; with serde's very words.

use super::model::*;
use crate::json::{fmt_f64, Map, Num, Value};

pub type DeR<T> = Result<T, String>;

/// A value as serde names it in "invalid type" errors.
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

pub fn invalid(v: &Value, what: &str) -> String {
    format!("invalid type: {}, expected {}", unexpected(v), what)
}

/// serde's "expected" list of names: `a`; `a` or `b`; one of `a`, `b`, `c`.
pub fn one_of(names: &[&str]) -> String {
    match names.len() {
        0 => "there are no variants".into(),
        1 => format!("`{}`", names[0]),
        2 => format!("`{}` or `{}`", names[0], names[1]),
        _ => format!("one of {}", names.iter().map(|n| format!("`{}`", n)).collect::<Vec<_>>().join(", ")),
    }
}

pub fn de_string(v: &Value) -> DeR<String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(invalid(v, "a string")),
    }
}

pub fn de_bool(v: &Value) -> DeR<bool> {
    match v {
        Value::Bool(b) => Ok(*b),
        _ => Err(invalid(v, "a boolean")),
    }
}

pub fn de_u64(v: &Value) -> DeR<u64> {
    match v {
        Value::Num(Num::U(u)) => Ok(*u),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u64", i)),
        _ => Err(invalid(v, "u64")),
    }
}

pub fn de_u8(v: &Value) -> DeR<u8> {
    match v {
        Value::Num(Num::U(u)) if *u <= 255 => Ok(*u as u8),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u8", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u8", i)),
        _ => Err(invalid(v, "u8")),
    }
}

pub fn de_f64(v: &Value) -> DeR<f64> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(invalid(v, "f64")),
    }
}

pub fn de_expr(v: &Value) -> DeR<Expr> {
    match v {
        Value::Num(n) => Ok(Expr::Num(n.as_f64())),
        Value::Str(s) => Ok(Expr::Text(s.clone())),
        _ => Err("data did not match any variant of untagged enum Expr".into()),
    }
}

fn de_opt<T>(v: &Value, f: impl Fn(&Value) -> DeR<T>) -> DeR<Option<T>> {
    match v {
        Value::Null => Ok(None),
        _ => f(v).map(Some),
    }
}

/// A unit enum's variant: by name, or as a map of one key.
pub fn de_variant(v: &Value, variants: &[&str]) -> DeR<String> {
    let unknown = |s: &str| format!("unknown variant `{}`, expected {}", s, one_of(variants));
    match v {
        Value::Str(s) => {
            if variants.contains(&s.as_str()) {
                Ok(s.clone())
            } else {
                Err(unknown(s))
            }
        }
        Value::Obj(m) => {
            if m.len() != 1 {
                return Err("invalid value: map, expected map with a single key".into());
            }
            let (k, x) = &m.items[0];
            if !variants.contains(&k.as_str()) {
                return Err(unknown(k));
            }
            match x {
                Value::Null => Ok(k.clone()),
                other => Err(invalid(other, "unit")),
            }
        }
        _ => Err(invalid(v, "string or map")),
    }
}

/// A fixed-size array of `n` elements, each read by `f`.
fn de_array<T>(v: &Value, n: usize, f: &dyn Fn(&Value) -> DeR<T>) -> DeR<Vec<T>> {
    let what = format!("an array of length {}", n);
    match v {
        Value::Arr(a) => {
            let mut out = Vec::with_capacity(n);
            for i in 0..n {
                match a.get(i) {
                    Some(x) => out.push(f(x)?),
                    None => return Err(format!("invalid length {}, expected {}", i, what)),
                }
            }
            if a.len() > n {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(out)
        }
        _ => Err(invalid(v, &what)),
    }
}

pub fn de_seq<T>(v: &Value, f: &dyn Fn(&Value) -> DeR<T>) -> DeR<Vec<T>> {
    match v {
        Value::Arr(a) => a.iter().map(f).collect(),
        _ => Err(invalid(v, "a sequence")),
    }
}

pub fn de_point(v: &Value) -> DeR<Pt> {
    let a = de_array(v, 2, &de_expr)?;
    let mut it = a.into_iter();
    Ok([it.next().unwrap(), it.next().unwrap()])
}

fn de_points(v: &Value) -> DeR<Vec<Pt>> {
    de_seq(v, &de_point)
}

/// A part's `guid`: a GUID (not one of the ids the original writes as GUIDs), or an element's
/// id (a whole number, or one in a string); 0 is none.
pub fn de_gref(v: &Value) -> DeR<GRef> {
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

/// A GUID as the original takes one (hyphenated, maybe in braces, any case): one whose first
/// 64 bits are all zero is how it writes an element's id, so not a GUID.
pub fn real_guid(s: &str) -> Option<String> {
    let g = crate::structure::members::read::parse_guid(s)?;
    let hi: String = g.chars().filter(|c| *c != '-').take(16).collect();
    if hi.bytes().all(|b| b == b'0') {
        None
    } else {
        Some(g)
    }
}

thread_local! {
    /// Reading a project file's families: keys the parts don't have are left alone.
    static LENIENT: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// A family as a project file holds it, read as the original's loader reads it (its serde
/// error, without the file's name, where it can't be): keys in name order, unknown keys left
/// alone, `operation` one of its variants, every part as `family` reads it.
pub fn check_file_family(v: &Value) -> DeR<()> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(invalid(v, "struct Family")),
    };
    LENIENT.with(|l| l.set(true));
    let r = (|| -> DeR<()> {
        let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
        keys.sort_by(|a, b| a.0.cmp(&b.0));
        for (k, x) in keys {
            match k.as_str() {
                "category" => {
                    de_category(x)?;
                }
                "kind" => {
                    de_opt(x, de_string)?;
                }
                "parameters" => {
                    de_seq(x, &de_param)?;
                }
                "types" => match x {
                    Value::Obj(ts) => {
                        let mut tk: Vec<&(String, Value)> = ts.items.iter().collect();
                        tk.sort_by(|a, b| a.0.cmp(&b.0));
                        for (_, t) in tk {
                            if !matches!(t, Value::Obj(_)) {
                                return Err(invalid(t, "a map"));
                            }
                        }
                    }
                    _ => return Err(invalid(x, "a map")),
                },
                "forms" => {
                    de_seq(x, &de_form)?;
                }
                "symbols" => {
                    de_seq(x, &de_symbol)?;
                }
                "operation" => {
                    de_opt(x, |o| de_variant(o, super::model::OPERATIONS))?;
                }
                "connectors" => {
                    de_seq(x, &de_connector)?;
                }
                _ => {}
            }
        }
        Ok(())
    })();
    LENIENT.with(|l| l.set(false));
    r
}

/// Reads a struct: a map key by key in name order (`field` reading each; unknown keys refused),
/// then the first of `required` it lacks; or a sequence of its `fields` in order (the first
/// `required` ones needed).
fn de_struct(
    v: &Value,
    name: &str,
    fields: &[&str],
    required: &[&str],
    field: &mut dyn FnMut(&str, &Value) -> DeR<()>,
) -> DeR<()> {
    match v {
        Value::Obj(m) => {
            let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
            keys.sort_by(|a, b| a.0.cmp(&b.0));
            let mut seen: Vec<&str> = Vec::new();
            for (k, x) in keys {
                if !fields.contains(&k.as_str()) {
                    if LENIENT.with(|l| l.get()) {
                        continue;
                    }
                    return Err(format!("unknown field `{}`, expected {}", k, one_of(fields)));
                }
                field(k, x)?;
                seen.push(k);
            }
            for r in fields {
                if required.contains(r) && !seen.contains(r) {
                    return Err(format!("missing field `{}`", r));
                }
            }
            Ok(())
        }
        Value::Arr(a) => {
            for (i, f) in fields.iter().enumerate() {
                match a.get(i) {
                    Some(x) => field(f, x)?,
                    None => {
                        if required.contains(f) {
                            return Err(format!("invalid length {}, expected struct {} with {} elements", i, name, fields.len()));
                        }
                    }
                }
            }
            if a.len() > fields.len() {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(())
        }
        _ => Err(invalid(v, &format!("struct {}", name))),
    }
}

// ---------------------------------------------------------------- the parts

pub const PARAM_FIELDS: &[&str] = &["name", "kind", "instance", "value", "formula"];

pub fn de_param(v: &Value) -> DeR<Param> {
    let mut p = Param { name: String::new(), kind: Kind::Length, instance: false, value: Value::Null, formula: None };
    de_struct(v, "Parameter", PARAM_FIELDS, &["name"], &mut |k, x| {
        match k {
            "name" => p.name = de_string(x)?,
            "kind" => p.kind = Kind::parse(&de_variant(x, KINDS)?).unwrap(),
            "instance" => p.instance = de_bool(x)?,
            "value" => p.value = x.clone(),
            _ => p.formula = de_opt(x, de_string)?,
        }
        Ok(())
    })?;
    Ok(p)
}

fn de_circle(v: &Value) -> DeR<Circle> {
    let (mut centre, mut radius) = (None, None);
    de_struct(v, "Circle", &["centre", "radius"], &["centre", "radius"], &mut |k, x| {
        match k {
            "centre" => centre = Some(de_point(x)?),
            _ => radius = Some(de_expr(x)?),
        }
        Ok(())
    })?;
    Ok(Circle { centre: centre.unwrap(), radius: radius.unwrap() })
}

fn de_mesh(v: &Value) -> DeR<Vec<[[f64; 3]; 3]>> {
    de_seq(v, &|t: &Value| {
        let pts = de_array(t, 3, &|p: &Value| {
            let c = de_array(p, 3, &de_f64)?;
            Ok([c[0], c[1], c[2]])
        })?;
        Ok([pts[0], pts[1], pts[2]])
    })
}

pub const FORM_FIELDS: &[&str] =
    &["id", "guid", "plane", "profile", "circle", "from", "to", "axis", "void", "material", "visible", "mesh"];

pub fn de_form(v: &Value) -> DeR<Form> {
    let mut f = Form::default();
    de_struct(v, "Form", FORM_FIELDS, &[], &mut |k, x| {
        match k {
            "id" => f.id = Some(de_u64(x)?).filter(|n| *n != 0),
            "guid" => f.guid = Some(de_gref(x)?).filter(|g| *g != GRef::Id(0)),
            "plane" => f.plane = Plane::parse(&de_variant(x, PLANES)?).unwrap(),
            "profile" => f.profile = de_points(x)?,
            "circle" => f.circle = de_opt(x, de_circle)?,
            "from" => f.from = de_expr(x)?,
            "to" => f.to = de_expr(x)?,
            "axis" => {
                f.axis = de_opt(x, |a| {
                    let pts = de_array(a, 2, &de_point)?;
                    let mut it = pts.into_iter();
                    Ok([it.next().unwrap(), it.next().unwrap()])
                })?
            }
            "void" => f.void = de_bool(x)?,
            "material" => f.material = de_string(x)?,
            "visible" => f.visible = de_opt(x, de_expr)?,
            _ => f.mesh = de_mesh(x)?,
        }
        Ok(())
    })?;
    Ok(f)
}

fn de_arc(v: &Value) -> DeR<Arc> {
    let (mut centre, mut radius, mut from, mut to) = (None, None, Expr::zero(), None);
    de_struct(v, "Curve", &["centre", "radius", "from", "to"], &["centre", "radius", "to"], &mut |k, x| {
        match k {
            "centre" => centre = Some(de_point(x)?),
            "radius" => radius = Some(de_expr(x)?),
            "from" => from = de_expr(x)?,
            _ => to = Some(de_expr(x)?),
        }
        Ok(())
    })?;
    Ok(Arc { centre: centre.unwrap(), radius: radius.unwrap(), from, to: to.unwrap() })
}

fn de_text(v: &Value) -> DeR<Text> {
    let (mut at, mut height, mut value, mut align) = (None, None, None, Align::Left);
    de_struct(v, "Label", &["at", "height", "value", "align"], &["at", "height", "value"], &mut |k, x| {
        match k {
            "at" => at = Some(de_point(x)?),
            "height" => height = Some(de_expr(x)?),
            "value" => value = Some(de_string(x)?),
            _ => align = Align::parse(&de_variant(x, ALIGNS)?).unwrap(),
        }
        Ok(())
    })?;
    Ok(Text { at: at.unwrap(), height: height.unwrap(), value: value.unwrap(), align })
}

fn de_dot(v: &Value) -> DeR<Dot> {
    let (mut centre, mut radius) = (None, None);
    de_struct(v, "Circle", &["centre", "radius"], &["centre", "radius"], &mut |k, x| {
        match k {
            "centre" => centre = Some(de_point(x)?),
            _ => radius = Some(de_expr(x)?),
        }
        Ok(())
    })?;
    Ok(Dot { centre: centre.unwrap(), radius: radius.unwrap() })
}

pub const SYMBOL_FIELDS: &[&str] = &["id", "guid", "line", "arc", "text", "dot", "visible"];

pub fn de_symbol(v: &Value) -> DeR<Symbol> {
    let mut s = Symbol::default();
    de_struct(v, "Symbol", SYMBOL_FIELDS, &[], &mut |k, x| {
        match k {
            "id" => s.id = Some(de_u64(x)?).filter(|n| *n != 0),
            "guid" => s.guid = Some(de_gref(x)?).filter(|g| *g != GRef::Id(0)),
            "line" => s.line = de_points(x)?,
            "arc" => s.arc = de_opt(x, de_arc)?,
            "text" => s.text = de_opt(x, de_text)?,
            "dot" => s.dot = de_opt(x, de_dot)?,
            _ => s.visible = de_opt(x, de_expr)?,
        }
        Ok(())
    })?;
    Ok(s)
}

fn de_load(v: &Value) -> DeR<Load> {
    let fail = || "data did not match any variant of untagged enum Load".to_string();
    match v {
        Value::Num(_) | Value::Str(_) => Ok(Load::One(de_expr(v).map_err(|_| fail())?)),
        Value::Arr(a) => {
            let mut out = Vec::with_capacity(a.len());
            for x in a {
                out.push(de_expr(x).map_err(|_| fail())?);
            }
            Ok(Load::PerPole(out))
        }
        _ => Err(fail()),
    }
}

pub const CONNECTOR_FIELDS: &[&str] =
    &["id", "guid", "kind", "system", "poles", "voltage", "load_va", "power_factor", "classification"];

pub fn de_connector(v: &Value) -> DeR<Connector> {
    let mut c = Connector {
        id: None,
        guid: None,
        kind: ConnKind::Power,
        system: System::Balanced,
        poles: 1,
        voltage: Expr::zero(),
        load_va: Load::One(Expr::zero()),
        power_factor: Expr::Num(1.0),
        classification: String::new(),
    };
    de_struct(v, "Connector", CONNECTOR_FIELDS, &["kind", "system"], &mut |k, x| {
        match k {
            "id" => c.id = Some(de_u64(x)?).filter(|n| *n != 0),
            "guid" => c.guid = Some(de_gref(x)?).filter(|g| *g != GRef::Id(0)),
            "kind" => c.kind = ConnKind::parse(&de_variant(x, CONN_KINDS)?).unwrap(),
            "system" => c.system = System::parse(&de_variant(x, SYSTEMS)?).unwrap(),
            "poles" => c.poles = de_u8(x)?,
            "voltage" => c.voltage = de_expr(x)?,
            "load_va" => c.load_va = de_load(x)?,
            "power_factor" => c.power_factor = de_expr(x)?,
            _ => c.classification = de_string(x)?,
        }
        Ok(())
    })?;
    Ok(c)
}

/// `types`: {type: {parameter: value} | null}, null taking a type away; a type's values with
/// their nulls (a null takes a value away).
pub fn de_types(v: &Value) -> DeR<Vec<(String, Option<Map>)>> {
    match v {
        Value::Obj(m) => {
            let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
            keys.sort_by(|a, b| a.0.cmp(&b.0));
            let mut out = Vec::with_capacity(keys.len());
            for (k, x) in keys {
                match x {
                    Value::Null => out.push((k.clone(), None)),
                    Value::Obj(vals) => {
                        let mut t = Map::new();
                        for (pk, pv) in vals.iter() {
                            t.insert_sorted(pk, pv.clone());
                        }
                        out.push((k.clone(), Some(t)));
                    }
                    other => return Err(invalid(other, "a map")),
                }
            }
            Ok(out)
        }
        _ => Err(invalid(v, "a map")),
    }
}

/// `category`: one of the original's.
pub fn de_category(v: &Value) -> DeR<String> {
    de_variant(v, CATEGORIES)
}
