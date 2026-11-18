//! Overrides as Visibility/Graphics holds them (a category's, an element's, an applied filter's):
//! read with serde's messages, written in the file's field order (fill patterns by GUID) or with
//! their patterns named, and merged as a JSON merge patch.

use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::styles::common::{color_of, color_value, f64_of, pen_of};

pub type R<T> = Result<T, String>;

#[derive(Clone, Default, PartialEq, Debug)]
pub struct PFill {
    pub pattern: Option<String>,
    pub color: [u8; 3],
}

#[derive(Clone, Default, PartialEq, Debug)]
pub struct Style {
    pub color: Option<[u8; 3]>,
    pub weight: Option<u64>,
    pub dash: Option<String>,
    pub fill: Option<[u8; 3]>,
    pub foreground: Option<PFill>,
    pub background: Option<PFill>,
}

impl Style {
    pub fn is_empty(&self) -> bool {
        *self == Style::default()
    }
}

#[derive(Clone, Default, PartialEq, Debug)]
pub struct Ovr {
    pub hidden: bool,
    pub projection: Option<Style>,
    pub cut: Option<Style>,
    pub halftone: bool,
    pub transparency: u64,
    pub shown: bool,
}

/// An object's items with their keys sorted (serde reads a map in that order).
pub fn sorted_items(m: &Map) -> Vec<(String, Value)> {
    Value::Obj(m.clone()).sorted().as_obj().map(|m| m.items.clone()).unwrap_or_default()
}

pub fn de_bool(v: &Value) -> R<bool> {
    match v {
        Value::Bool(b) => Ok(*b),
        _ => Err(format!("invalid type: {}, expected a boolean", v.kind_name())),
    }
}

pub fn de_u8(v: &Value) -> R<u64> {
    match v {
        Value::Num(Num::U(u)) if *u <= 255 => Ok(*u),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u8", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u8", i)),
        _ => Err(format!("invalid type: {}, expected u8", v.kind_name())),
    }
}

pub fn de_u16(v: &Value) -> R<u64> {
    match v {
        Value::Num(Num::U(u)) if *u <= 65535 => Ok(*u),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u16", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u16", i)),
        _ => Err(format!("invalid type: {}, expected u16", v.kind_name())),
    }
}

pub fn de_string(v: &Value) -> R<String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(format!("invalid type: {}, expected a string", v.kind_name())),
    }
}

fn de_colour(v: &Value) -> R<[u8; 3]> {
    color_of(v).ok_or_else(|| format!("{} isn't a colour: [r, g, b], each 0 to 255, or \"#rrggbb\"", v.to_compact()))
}

/// [u8; 3] as serde reads it.
pub fn de_rgb_array(v: &Value) -> R<[u8; 3]> {
    let a = match v {
        Value::Arr(a) => a,
        _ => return Err(format!("invalid type: {}, expected an array of length 3", v.kind_name())),
    };
    let mut out = [0u8; 3];
    for i in 0..3 {
        match a.get(i) {
            Some(x) => out[i] = de_u8(x)? as u8,
            None => return Err(format!("invalid length {}, expected an array of length 3", i)),
        }
    }
    if a.len() > 3 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

/// A pen as an override's weight takes it.
pub fn de_pen(v: &Value) -> R<u64> {
    let w = f64_of(v)?;
    pen_of(w).ok_or_else(|| format!("a line weight is a pen, a whole number from 0 (a hairline) to 16, not {}", w))
}

fn de_fill(v: &Value) -> R<PFill> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct PatternFill", v.kind_name())),
    };
    let mut f = PFill::default();
    for (k, x) in sorted_items(m) {
        match k.as_str() {
            "pattern" => {
                f.pattern = match &x {
                    Value::Null => None,
                    Value::Str(s) => Some(s.clone()),
                    _ => return Err(format!("invalid type: {}, expected a string", x.kind_name())),
                }
            }
            "color" => f.color = de_rgb_array(&x)?,
            _ => return Err(format!("unknown field `{}`, expected `pattern` or `color`", k)),
        }
    }
    Ok(f)
}

fn de_style(v: &Value) -> R<Style> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct Style", v.kind_name())),
    };
    let mut st = Style::default();
    for (k, x) in sorted_items(m) {
        // each of a style's fields may be null, as not given
        if x.is_null() && ["color", "weight", "dash", "fill", "foreground", "background"].contains(&k.as_str()) {
            continue;
        }
        match k.as_str() {
            "color" => st.color = Some(de_colour(&x)?),
            "weight" => st.weight = Some(de_pen(&x)?),
            "dash" => {
                st.dash = Some(match &x {
                    Value::Str(s) if ["solid", "dashed", "dotted"].contains(&s.as_str()) => s.clone(),
                    Value::Str(s) => {
                        return Err(format!("unknown variant `{}`, expected one of `solid`, `dashed`, `dotted`", s))
                    }
                    _ => return Err(format!("invalid type: {}, expected string or map", x.kind_name())),
                })
            }
            "fill" => st.fill = Some(de_colour(&x)?),
            "foreground" => st.foreground = Some(de_fill(&x)?),
            "background" => st.background = Some(de_fill(&x)?),
            _ => {
                return Err(format!(
                    "unknown field `{}`, expected one of `color`, `weight`, `dash`, `fill`, `foreground`, `background`",
                    k
                ))
            }
        }
    }
    Ok(st)
}

/// One of an override's own fields (`shown` among them unless `applied`, a filter's entry).
fn de_field(o: &mut Ovr, k: &str, x: &Value) -> R<bool> {
    match k {
        "hidden" => o.hidden = de_bool(x)?,
        "projection" => o.projection = Some(de_style(x)?),
        "cut" => o.cut = Some(de_style(x)?),
        "halftone" => o.halftone = de_bool(x)?,
        "transparency" => o.transparency = de_u8(x)?,
        _ => return Ok(false),
    }
    Ok(true)
}

/// An override: {hidden?, projection?, cut?, halftone?, transparency?, shown?}.
pub fn de_override(v: &Value) -> R<Ovr> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct Override", v.kind_name())),
    };
    let mut o = Ovr::default();
    for (k, x) in sorted_items(m) {
        if de_field(&mut o, &k, &x)? {
            continue;
        }
        if k == "shown" {
            o.shown = de_bool(&x)?;
            continue;
        }
        return Err(format!(
            "unknown field `{}`, expected one of `hidden`, `projection`, `cut`, `halftone`, `transparency`, `shown`",
            k
        ));
    }
    Ok(o)
}

/// A filter as a view applies it: {filter, hidden?, projection?, cut?, halftone?, transparency?}.
pub fn de_applied(v: &Value) -> R<(String, Ovr)> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(format!("invalid type: {}, expected struct AppliedJson", v.kind_name())),
    };
    let mut o = Ovr::default();
    let mut name = None;
    for (k, x) in sorted_items(m) {
        if k == "filter" {
            name = Some(de_string(&x)?);
            continue;
        }
        if de_field(&mut o, &k, &x)? {
            continue;
        }
        return Err(format!(
            "unknown field `{}`, expected one of `filter`, `hidden`, `projection`, `cut`, `halftone`, `transparency`",
            k
        ));
    }
    match name {
        Some(n) => Ok((n, o)),
        None => Err("missing field `filter`".to_string()),
    }
}

/// A fill pattern's GUID from its name (a name the project hasn't stays as it is, for the check).
fn pattern_ref(pr: &Project, n: &str) -> String {
    pr.lib_guid("fill-pattern", n).unwrap_or_else(|| n.to_string())
}

/// A fill pattern's name from what an override holds (its GUID, or a name).
pub fn pattern_name(pr: &Project, v: &str) -> String {
    crate::styles::common::name_of_guid(pr, "fill-pattern", v).unwrap_or_else(|| v.to_string())
}

fn fill_value(pr: &Project, f: &PFill, names: bool) -> Value {
    let pat = match &f.pattern {
        None => Value::Null,
        Some(n) => {
            if names {
                Value::s(n)
            } else {
                Value::s(&pattern_ref(pr, n))
            }
        }
    };
    jobj! {"pattern" => pat, "color" => color_value(f.color)}
}

fn style_value(pr: &Project, s: &Style, names: bool) -> Value {
    let mut m = Map::new();
    if let Some(c) = s.color {
        m.insert("color", color_value(c));
    }
    if let Some(w) = s.weight {
        m.insert("weight", Value::u(w));
    }
    if let Some(d) = &s.dash {
        m.insert("dash", Value::s(d));
    }
    if let Some(c) = s.fill {
        m.insert("fill", color_value(c));
    }
    if let Some(f) = &s.foreground {
        m.insert("foreground", fill_value(pr, f, names));
    }
    if let Some(f) = &s.background {
        m.insert("background", fill_value(pr, f, names));
    }
    Value::Obj(m)
}

/// The override's fields as the file holds them (`names`: its fill patterns by name instead).
pub fn override_map(pr: &Project, o: &Ovr, names: bool) -> Map {
    let mut m = Map::new();
    if o.hidden {
        m.insert("hidden", Value::Bool(true));
    }
    if let Some(s) = &o.projection {
        if !s.is_empty() {
            m.insert("projection", style_value(pr, s, names));
        }
    }
    if let Some(s) = &o.cut {
        if !s.is_empty() {
            m.insert("cut", style_value(pr, s, names));
        }
    }
    if o.halftone {
        m.insert("halftone", Value::Bool(true));
    }
    if o.transparency != 0 {
        m.insert("transparency", Value::u(o.transparency));
    }
    if o.shown {
        m.insert("shown", Value::Bool(true));
    }
    m
}

pub fn override_value(pr: &Project, o: &Ovr, names: bool) -> Value {
    Value::Obj(override_map(pr, o, names))
}

/// An override (or an applied filter) from the file with its fill patterns named.
pub fn named_override(pr: &Project, v: &Value) -> Value {
    let mut v = v.clone();
    for side in ["projection", "cut"] {
        for layer in ["foreground", "background"] {
            if let Some(Value::Obj(f)) = v.get_mut(side).and_then(|s| s.get_mut(layer)) {
                if let Some(Value::Str(g)) = f.get("pattern") {
                    let n = pattern_name(pr, g);
                    f.insert("pattern", Value::s(&n));
                }
            }
        }
    }
    v
}

/// The fill patterns an override names (as it holds them), foreground before background,
/// projection before cut.
pub fn patterns_in(v: &Value) -> Vec<String> {
    let mut out = Vec::new();
    for side in ["projection", "cut"] {
        for layer in ["foreground", "background"] {
            if let Some(Value::Str(g)) = v.get(side).and_then(|s| s.get(layer)).and_then(|f| f.get("pattern")) {
                out.push(g.clone());
            }
        }
    }
    out
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

/// An override in the file merged with a patch as the command gives it, read again: the result
/// as the file holds it (None where nothing is left).
pub fn merged(pr: &Project, cur: Option<&Value>, patch: &Value) -> R<Option<Value>> {
    let mut target = cur.map(|v| named_override(pr, v)).unwrap_or_else(Value::obj);
    merge_patch(&mut target, patch);
    let o = de_override(&target.sorted())?;
    let m = override_map(pr, &o, false);
    Ok(if m.is_empty() { None } else { Some(Value::Obj(m)) })
}
