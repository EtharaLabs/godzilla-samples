//! Line patterns and line styles: `line_pattern`, `line_style`.
//!
//! The file keeps `line_patterns` (by name: the segments, as serde writes an externally tagged
//! enum: `{"dash": mm}`, `{"space": mm}`, `"dot"`, `{"dot_length": mm}`, `{"offset": {length,
//! count, distance}}`, `{"wave"|"zigzag": {length, frequency, amplitude}}`, `{"text": {length,
//! size, text}}`) and `line_styles` (by name: `pen`, `color`, and `pattern`, the GUID of the
//! library's `line-pattern` entry, none for Solid), both sorted by name. What draws in a style
//! names it by the GUID of its `line-style` entry, so a rename is the entry's and the rest follows.

use super::common::*;
use crate::json::{Map, Num, Value};
use crate::project::Project;
use crate::session::Session;

const LP: &str = "line_pattern";
const LS: &str = "line_style";
const KIND_LP: &str = "line-pattern";
const KIND_LS: &str = "line-style";
const SEC_LP: &str = "line_patterns";
const SEC_LS: &str = "line_styles";

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "line_pattern" => line_pattern(&mut s.project, p),
        "line_style" => line_style(&mut s.project, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// A name as given, or the name of the library entry (of any kind) whose GUID it is.
fn resolve(pr: &Project, name: String) -> String {
    super::electrical::resolve(pr, "", &name)
}

// ---------------------------------------------------------------- segments

const VARIANTS: &str = "`dash`, `space`, `dot`, `dot_length`, `offset`, `wave`, `zigzag`, `text`";

/// A segment of a line pattern.
#[derive(Clone, Debug)]
enum Seg {
    Dash(f64),
    Space(f64),
    Dot,
    DotLength(f64),
    Offset { length: f64, count: u8, distance: f64 },
    Wave { length: f64, frequency: f64, amplitude: f64 },
    Zigzag { length: f64, frequency: f64, amplitude: f64 },
    Text { length: f64, size: f64, text: String },
}

fn f64_de(v: &Value) -> R<f64> {
    f64_of(v)
}

fn u8_de(v: &Value) -> R<u8> {
    match v {
        Value::Num(Num::U(u)) if *u <= 255 => Ok(*u as u8),
        Value::Num(Num::U(u)) => Err(format!("invalid value: integer `{}`, expected u8", u)),
        Value::Num(Num::I(i)) => Err(format!("invalid value: integer `{}`, expected u8", i)),
        _ => Err(invalid_type(v, "u8")),
    }
}

fn string_de(v: &Value) -> R<String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(invalid_type(v, "a string")),
    }
}

/// A struct variant's fields, read as serde reads a map: the keys in order (sorted, as the
/// original's parameters are), unknown ones refused, missing ones named in the struct's order.
fn struct_fields<'a>(v: &'a Value, fields: &[&str]) -> R<Vec<&'a Value>> {
    let m = match v {
        Value::Obj(m) => m,
        _ => return Err(invalid_type(v, "struct variant")),
    };
    let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
    keys.sort_by(|a, b| a.0.cmp(&b.0));
    let mut out: Vec<Option<&Value>> = vec![None; fields.len()];
    for (k, x) in keys {
        match fields.iter().position(|f| f == k) {
            Some(i) => out[i] = Some(x),
            None => {
                let list: Vec<String> = fields.iter().map(|f| format!("`{}`", f)).collect();
                return Err(format!("unknown field `{}`, expected one of {}", k, list.join(", ")));
            }
        }
    }
    let mut res = Vec::new();
    for (i, f) in fields.iter().enumerate() {
        match out[i] {
            Some(x) => res.push(x),
            None => return Err(format!("missing field `{}`", f)),
        }
    }
    Ok(res)
}

/// The fields of a struct variant read in sorted key order: each value is parsed when its key is
/// visited, so the first bad one (by key) is the one refused, before any missing one is named.
fn parse_struct<T>(v: &Value, fields: &[&str], parse: &dyn Fn(&str, &Value) -> R<()>, build: &dyn Fn(Vec<&Value>) -> R<T>) -> R<T> {
    if let Value::Obj(m) = v {
        let mut keys: Vec<&(String, Value)> = m.items.iter().collect();
        keys.sort_by(|a, b| a.0.cmp(&b.0));
        for (k, x) in keys {
            if fields.contains(&k.as_str()) {
                parse(k, x)?;
            } else {
                let list: Vec<String> = fields.iter().map(|f| format!("`{}`", f)).collect();
                return Err(format!("unknown field `{}`, expected one of {}", k, list.join(", ")));
            }
        }
    }
    let vals = struct_fields(v, fields)?;
    build(vals)
}

fn seg_de(v: &Value) -> R<Seg> {
    let (tag, content) = match v {
        Value::Str(s) => (s.as_str(), None),
        Value::Obj(m) => {
            if m.items.len() != 1 {
                return Err("invalid value: map, expected map with a single key".into());
            }
            (m.items[0].0.as_str(), Some(&m.items[0].1))
        }
        _ => return Err(invalid_type(v, "string or map")),
    };
    let newtype = |c: Option<&Value>| -> R<f64> {
        match c {
            None => Err("invalid type: unit variant, expected newtype variant".into()),
            Some(x) => f64_de(x),
        }
    };
    fn structv(c: Option<&Value>) -> R<&Value> {
        match c {
            None => Err("invalid type: unit variant, expected struct variant".into()),
            Some(x @ Value::Obj(_)) => Ok(x),
            Some(x) => Err(invalid_type(x, "struct variant")),
        }
    }
    match tag {
        "dash" => Ok(Seg::Dash(newtype(content)?)),
        "space" => Ok(Seg::Space(newtype(content)?)),
        "dot_length" => Ok(Seg::DotLength(newtype(content)?)),
        "dot" => match content {
            None | Some(Value::Null) => Ok(Seg::Dot),
            Some(x) => Err(invalid_type(x, "unit")),
        },
        "offset" => {
            let x = structv(content)?;
            parse_struct(
                x,
                &["length", "count", "distance"],
                &|k, x| match k {
                    "count" => u8_de(x).map(|_| ()),
                    _ => f64_de(x).map(|_| ()),
                },
                &|vals| Ok(Seg::Offset { length: f64_de(vals[0])?, count: u8_de(vals[1])?, distance: f64_de(vals[2])? }),
            )
        }
        "wave" | "zigzag" => {
            let x = structv(content)?;
            let wave = tag == "wave";
            parse_struct(
                x,
                &["length", "frequency", "amplitude"],
                &|_, x| f64_de(x).map(|_| ()),
                &|vals| {
                    let (length, frequency, amplitude) = (f64_de(vals[0])?, f64_de(vals[1])?, f64_de(vals[2])?);
                    Ok(if wave {
                        Seg::Wave { length, frequency, amplitude }
                    } else {
                        Seg::Zigzag { length, frequency, amplitude }
                    })
                },
            )
        }
        "text" => {
            let x = structv(content)?;
            parse_struct(
                x,
                &["length", "size", "text"],
                &|k, x| match k {
                    "text" => string_de(x).map(|_| ()),
                    _ => f64_de(x).map(|_| ()),
                },
                &|vals| Ok(Seg::Text { length: f64_de(vals[0])?, size: f64_de(vals[1])?, text: string_de(vals[2])? }),
            )
        }
        _ => Err(format!("unknown variant `{}`, expected one of {}", tag, VARIANTS)),
    }
}

fn segs_de(v: &Value) -> R<Vec<Seg>> {
    match v {
        Value::Arr(a) => a.iter().map(seg_de).collect(),
        _ => Err(invalid_type(v, "a sequence")),
    }
}

impl Seg {
    fn length(&self) -> Option<f64> {
        match self {
            Seg::Dash(l) | Seg::Space(l) | Seg::DotLength(l) => Some(*l),
            Seg::Dot => None,
            Seg::Offset { length, .. } | Seg::Wave { length, .. } | Seg::Zigzag { length, .. } | Seg::Text { length, .. } => {
                Some(*length)
            }
        }
    }

    /// Whether what it holds besides its length is as a segment of its kind takes it.
    fn shape_ok(&self) -> bool {
        match self {
            Seg::Offset { count, distance, .. } => (2..=9).contains(count) && *distance > 0.0 && *distance <= 100.0,
            Seg::Wave { frequency, amplitude, .. } | Seg::Zigzag { frequency, amplitude, .. } => {
                (0.1..=100.0).contains(frequency) && *amplitude > 0.0 && *amplitude <= 100.0
            }
            Seg::Text { size, text, .. } => {
                let n = text.chars().count();
                (1..=256).contains(&n)
                    && !text.trim().is_empty()
                    && !text.chars().any(|c| c.is_control())
                    && (0.05..=100.0).contains(size)
            }
            _ => true,
        }
    }

    fn to_value(&self) -> Value {
        let one = |k: &str, v: Value| {
            let mut m = Map::new();
            m.insert(k, v);
            Value::Obj(m)
        };
        match self {
            Seg::Dash(l) => one("dash", Value::f(*l)),
            Seg::Space(l) => one("space", Value::f(*l)),
            Seg::Dot => Value::s("dot"),
            Seg::DotLength(l) => one("dot_length", Value::f(*l)),
            Seg::Offset { length, count, distance } => one(
                "offset",
                jobj! {"length" => Value::f(*length), "count" => Value::u(*count as u64), "distance" => Value::f(*distance)},
            ),
            Seg::Wave { length, frequency, amplitude } => one(
                "wave",
                jobj! {"length" => Value::f(*length), "frequency" => Value::f(*frequency), "amplitude" => Value::f(*amplitude)},
            ),
            Seg::Zigzag { length, frequency, amplitude } => one(
                "zigzag",
                jobj! {"length" => Value::f(*length), "frequency" => Value::f(*frequency), "amplitude" => Value::f(*amplitude)},
            ),
            Seg::Text { length, size, text } => one(
                "text",
                jobj! {"length" => Value::f(*length), "size" => Value::f(*size), "text" => Value::s(text)},
            ),
        }
    }
}

/// A pattern's segments as the model takes them: 1 to 32, each 0.05 to 100 mm long, and each
/// offset, wave and text as its kind needs.
fn check_segs(name: &str, segs: &[Seg]) -> R<()> {
    if segs.is_empty() || segs.len() > 32 {
        return Err(format!("{}: line pattern `{}`: a pattern needs 1 to 32 segments", LP, name));
    }
    for (i, sg) in segs.iter().enumerate() {
        if let Some(l) = sg.length() {
            if !(0.05..=100.0).contains(&l) {
                return Err(format!(
                    "{}: line pattern `{}`: segment {} is {} mm; a segment is 0.05 to 100 mm on paper",
                    LP,
                    name,
                    i + 1,
                    disp(l)
                ));
            }
        }
        if !sg.shape_ok() {
            return Err(format!(
                "{}: line pattern `{}`: segment {}: offsets need 2–9 lines and positive spacing; waves need 0.1–100 cycles and positive amplitude; text needs 1–256 characters on one line and a size of 0.05–100 mm",
                LP,
                name,
                i + 1
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------- line_pattern

fn patterns(pr: &Project) -> Map {
    section(pr, SEC_LP)
}

fn pattern_names(pr: &Project) -> Vec<String> {
    patterns(pr).keys().cloned().collect()
}

/// Puts a section's entry under a new name (the section sorted by name, as the original keeps it).
fn rename_in(pr: &mut Project, sec: &str, from: &str, to: &str) {
    let m = pr.section_mut(sec);
    if let Some(v) = m.remove(from) {
        m.insert_sorted(to, v);
    }
}

fn line_pattern(pr: &mut Project, p: &Value) -> R<Value> {
    check_keys(p, LP, &["name", "segments", "rename", "delete"])?;
    let Some(name) = opt_name(p, LP, "name")? else {
        return Ok(jobj! {"patterns" => Value::Obj(patterns(pr))});
    };
    let name = resolve(pr, name);
    let exists = patterns(pr).contains(&name);
    if opt_bool(p, LP, "delete")? == Some(true) {
        if !exists {
            return Err(format!("{}: there's no line pattern `{}`", LP, name));
        }
        let g = guid_of(pr, KIND_LP, &name);
        for (sname, st) in section(pr, SEC_LS).iter() {
            if g.is_some() && st.get("pattern").and_then(|x| x.as_str()) == g.as_deref() {
                return Err(format!("{}: `{}` is line style `{}`'s pattern; give it another first", LP, name, sname));
            }
        }
        pr.section_mut(SEC_LP).remove(&name);
        lib_remove(pr, KIND_LP, &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let segs = match p.get("segments") {
        None | Some(Value::Null) => None,
        Some(v) => Some(
            segs_de(v).map_err(|e| format!("{}: `segments` is [{{\"dash\": mm}} | {{\"space\": mm}} | \"dot\", …]: {}", LP, e))?,
        ),
    };
    let rename = opt_name(p, LP, "rename")?.map(|r| resolve(pr, r));
    if !exists && segs.is_none() {
        return Err(format!(
            "{}: there's no line pattern `{}`; make one with `segments` (there are: {})",
            LP,
            name,
            pattern_names(pr).join(", ")
        ));
    }
    let target = rename.clone().unwrap_or_else(|| name.clone());
    if let Some(r) = &rename {
        if *r != name && patterns(pr).contains(r) {
            return Err(format!("{}: there's already a line pattern `{}`", LP, r));
        }
    }
    if target.to_lowercase() == "solid" {
        return Err(format!("{}: Solid is a line with no pattern; name it another way", LP));
    }
    if let Some(sg) = &segs {
        check_segs(&target, sg)?;
    }
    if exists {
        if let Some(sg) = &segs {
            let v = Value::Arr(sg.iter().map(|x| x.to_value()).collect());
            pr.section_mut(SEC_LP).insert(&name, v);
        }
        if target != name {
            rename_in(pr, SEC_LP, &name, &target);
            lib_rename(pr, KIND_LP, &name, &target);
        }
    } else {
        let sg = segs.unwrap_or_default();
        let v = Value::Arr(sg.iter().map(|x| x.to_value()).collect());
        pr.section_mut(SEC_LP).insert_sorted(&target, v);
        lib_ensure(pr, KIND_LP, &target);
    }
    super::mark_step();
    let segments = patterns(pr).get(&target).cloned().unwrap_or(Value::Arr(Vec::new()));
    Ok(jobj! {"name" => target, "segments" => segments})
}

// ---------------------------------------------------------------- line_style

fn styles(pr: &Project) -> Map {
    section(pr, SEC_LS)
}

/// A style as the commands reply with it: its colour, its pattern by name (none: Solid), its pen.
fn style_shown(pr: &Project, st: &Value) -> Value {
    let mut m = Map::new();
    m.insert("color", st.get("color").cloned().unwrap_or_else(|| color_value([0, 0, 0])));
    if let Some(Value::Str(g)) = st.get("pattern") {
        let n = name_of_guid(pr, KIND_LP, g).unwrap_or_else(|| g.clone());
        m.insert("pattern", Value::s(&n));
    }
    m.insert("pen", st.get("pen").cloned().unwrap_or(Value::u(1)));
    Value::Obj(m)
}

/// What still draws in a style, which keeps it from being deleted: detail lines, Linework in
/// views, filled regions' boundaries and detail groups' members, in that order.
fn style_in_use(pr: &Project, name: &str, g: &str) -> R<()> {
    for (id, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) == Some("line") && e.get("style").and_then(|x| x.as_str()) == Some(g) {
            return Err(format!("{}: detail line {} is drawn in `{}`; give it another style first", LS, id, name));
        }
    }
    for (id, e) in &pr.elements {
        let lw = e.get("graphics").and_then(|x| x.get("linework")).and_then(|x| x.as_arr());
        if let Some(lw) = lw {
            if lw.iter().any(|x| x.get("style").and_then(|s| s.as_str()) == Some(g)) {
                return Err(format!("{}: view {} draws an edge in `{}` with Linework; take it off first", LS, id, name));
            }
        }
    }
    for (id, e) in &pr.elements {
        if e.get("category").and_then(|c| c.as_str()) == Some("region") && e.get("line_style").and_then(|x| x.as_str()) == Some(g) {
            return Err(format!(
                "{}: filled region {} is bounded in `{}`; give it another line style first",
                LS, id, name
            ));
        }
    }
    if let Some(groups) = pr.section("detail_groups") {
        let mut names: Vec<&String> = groups.keys().collect();
        names.sort();
        for gname in names {
            let members = groups.get(gname).and_then(|t| t.get("members")).and_then(|m| m.as_arr());
            for m in members.into_iter().flatten() {
                let el = m.get("element").unwrap_or(m);
                let uses = el.get("style").and_then(|x| x.as_str()) == Some(g)
                    || el.get("line_style").and_then(|x| x.as_str()) == Some(g);
                if uses {
                    return Err(format!(
                        "{}: detail group `{}` has a member drawn in `{}`; ungroup it and change that member first",
                        LS, gname, name
                    ));
                }
            }
        }
    }
    Ok(())
}

fn line_style(pr: &mut Project, p: &Value) -> R<Value> {
    check_keys(p, LS, &["name", "pen", "color", "pattern", "rename", "delete"])?;
    let Some(name) = opt_name(p, LS, "name")? else {
        let mut out = Map::new();
        for (n, st) in styles(pr).iter() {
            out.insert(n, style_shown(pr, st));
        }
        return Ok(jobj! {"styles" => Value::Obj(out)});
    };
    let name = resolve(pr, name);
    let exists = styles(pr).contains(&name);
    if opt_bool(p, LS, "delete")? == Some(true) {
        if !exists {
            return Err(format!("{}: there's no line style `{}`", LS, name));
        }
        if let Some(g) = guid_of(pr, KIND_LS, &name) {
            style_in_use(pr, &name, &g)?;
        }
        pr.section_mut(SEC_LS).remove(&name);
        lib_remove(pr, KIND_LS, &name);
        super::mark_step();
        return Ok(jobj! {"deleted" => name});
    }
    let pen = opt_pen(p, LS, "pen")?;
    if !exists && p.get("pen").is_none() {
        return Err(format!("{}: there's no line style `{}`; make one with `pen`", LS, name));
    }
    let color = opt_color(p, LS, "color")?;
    // `pattern`: a line pattern's name, "Solid" (any case) or null for none
    let pattern: Option<Option<String>> = match p.get("pattern") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::Str(s)) => Some(Some(s.trim().to_string())),
        Some(v) => {
            return Err(format!("{}: `pattern` is a line pattern's name, or \"Solid\", not {}", LS, v.to_compact()));
        }
    };
    let rename = opt_name(p, LS, "rename")?.map(|r| resolve(pr, r));
    if let Some(r) = &rename {
        if *r != name && styles(pr).contains(r) {
            return Err(format!("{}: there's already a line style `{}`", LS, r));
        }
    }
    let target = rename.clone().unwrap_or_else(|| name.clone());
    // the pattern's GUID: Some(None) is Solid
    let pattern_guid: Option<Option<String>> = match pattern {
        None => None,
        Some(None) => Some(None),
        Some(Some(pn)) => {
            let pn = resolve(pr, pn);
            if pn.to_lowercase() == "solid" {
                Some(None)
            } else if patterns(pr).contains(&pn) {
                Some(Some(lib_ensure(pr, KIND_LP, &pn)))
            } else {
                let mut names = vec!["Solid".to_string()];
                names.extend(pattern_names(pr));
                return Err(format!(
                    "{}: line style `{}`: there's no line pattern `{}` (there are: {})",
                    LS,
                    target,
                    pn,
                    names.join(", ")
                ));
            }
        }
    };
    let old = styles(pr).get(&name).cloned();
    let old_pen = old.as_ref().and_then(|o| o.get("pen")).and_then(|x| x.as_u64()).unwrap_or(1);
    let old_color = color_in(old.as_ref().and_then(|o| o.get("color")));
    let old_pattern = old.as_ref().and_then(|o| o.get("pattern")).and_then(|x| x.as_str()).map(|s| s.to_string());
    let mut st = Map::new();
    st.insert("pen", Value::u(pen.unwrap_or(old_pen)));
    st.insert("color", color_value(color.unwrap_or(old_color)));
    let pat = match pattern_guid {
        None => old_pattern,
        Some(x) => x,
    };
    if let Some(g) = pat {
        st.insert("pattern", Value::s(&g));
    }
    if exists {
        pr.section_mut(SEC_LS).insert(&name, Value::Obj(st));
        if target != name {
            rename_in(pr, SEC_LS, &name, &target);
            lib_rename(pr, KIND_LS, &name, &target);
        }
    } else {
        pr.section_mut(SEC_LS).insert_sorted(&target, Value::Obj(st));
        lib_ensure(pr, KIND_LS, &target);
    }
    super::mark_step();
    let shown = style_shown(pr, styles(pr).get(&target).unwrap());
    Ok(jobj! {"name" => target, "style" => shown})
}
