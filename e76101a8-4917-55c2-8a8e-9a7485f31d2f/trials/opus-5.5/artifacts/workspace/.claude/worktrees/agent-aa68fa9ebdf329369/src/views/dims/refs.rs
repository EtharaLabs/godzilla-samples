//! A dimension's references: `{id, face, point?}` as a dimension keeps them (the element by GUID),
//! read from a command as serde reads the original's `Reference` (a map or a sequence), or given as
//! a point on a line or `{endpoint}`, and named in messages.

use super::super::common::*;
use crate::json::{Num, Value};
use crate::project::Project;

/// What of an element a reference measures to.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Face {
    Centre,
    Left,
    Right,
    Start,
    End,
}

impl Face {
    pub fn word(self) -> &'static str {
        match self {
            Face::Centre => "centre",
            Face::Left => "left",
            Face::Right => "right",
            Face::Start => "start",
            Face::End => "end",
        }
    }
    pub fn parse(s: &str) -> Option<Face> {
        Some(match s {
            "centre" | "center" => Face::Centre,
            "left" => Face::Left,
            "right" => Face::Right,
            "start" => Face::Start,
            "end" => Face::End,
            _ => return None,
        })
    }
}

/// An end of a line.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum End {
    Start,
    End,
}

impl End {
    pub fn word(self) -> &'static str {
        match self {
            End::Start => "start",
            End::End => "end",
        }
    }
    pub fn parse(s: &str) -> Option<End> {
        match s {
            "start" => Some(End::Start),
            "end" => Some(End::End),
            _ => None,
        }
    }
}

/// The element a reference names: by GUID as kept, or an id or GUID the project hasn't (only while
/// a command checks what it was given).
#[derive(Clone, Debug, PartialEq)]
pub enum Target {
    Guid(String),
    /// Not in the project: how the command named it (an id, or a GUID).
    Missing(String),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Ref {
    pub target: Target,
    pub face: Face,
    pub point: Option<End>,
}

impl Ref {
    pub fn guid(&self) -> &str {
        match &self.target {
            Target::Guid(g) => g,
            Target::Missing(s) => s,
        }
    }
    /// The element's id, if the project has it.
    pub fn id(&self, pr: &Project) -> Option<u64> {
        match &self.target {
            Target::Guid(g) => pr.find_guid(g),
            Target::Missing(_) => None,
        }
    }
    /// The same reference: the same element, face and end.
    pub fn same(&self, o: &Ref) -> bool {
        self.target == o.target && self.face == o.face && self.point == o.point
    }
    /// As a dimension keeps it: `{id, face, point?}`.
    pub fn to_value(&self) -> Value {
        let mut v = jobj! {"id" => self.guid(), "face" => self.face.word()};
        if let Some(p) = self.point {
            v.set("point", Value::s(p.word()));
        }
        v
    }
    /// As a dimension keeps it.
    pub fn from_value(v: &Value) -> Option<Ref> {
        let id = s_of(v, "id")?.to_string();
        let face = s_of(v, "face").and_then(Face::parse).unwrap_or(Face::Centre);
        let point = s_of(v, "point").and_then(End::parse);
        Some(Ref { target: Target::Guid(id), face, point })
    }
}

/// A dimension's references as it keeps them.
pub fn refs_of(e: &Value) -> Vec<Ref> {
    e.get("refs").and_then(|r| r.as_arr()).map(|a| a.iter().filter_map(Ref::from_value).collect()).unwrap_or_default()
}

/// What a command's `refs` holds, one by one: a reference, a point on a line, or `{endpoint}`.
pub enum RefIn {
    Ref { id: IdIn, face: Face, point: Option<End> },
    Point(P),
    Endpoint(P),
}

pub type P = [f64; 2];

/// An element named by id or GUID.
pub enum IdIn {
    Id(u64),
    Guid(String),
}

/// The element an id or GUID names: kept by its GUID, or missing.
pub fn target_of(pr: &Project, id: &IdIn) -> Target {
    match id {
        IdIn::Id(n) => match pr.guid_of(*n) {
            Some(g) if pr.elements.contains_key(n) => Target::Guid(g),
            _ => Target::Missing(n.to_string()),
        },
        IdIn::Guid(g) => match pr.find_guid(g) {
            Some(_) => Target::Guid(g.clone()),
            None => Target::Missing(g.clone()),
        },
    }
}

/// serde's words for what it got.
fn unexpected(v: &Value) -> String {
    v.kind_name()
}

/// Reads `refs[i]` as the original reads it; the error is the reason only.
pub fn parse_ref_in(v: &Value) -> Result<RefIn, String> {
    if let Some(a) = v.as_arr() {
        if a.len() == 2 {
            if let Some(p) = point_of(v) {
                return Ok(RefIn::Point(p));
            }
        }
    }
    if let Value::Obj(m) = v {
        if m.len() == 1 && m.contains("endpoint") {
            let x = m.get("endpoint").unwrap();
            return match point_of(x) {
                Some(p) => Ok(RefIn::Endpoint(p)),
                None => Err(format!("`endpoint` is a point [x, y], not {}", x.clone().sorted().to_compact())),
            };
        }
    }
    parse_reference(v)
        .map(|(id, face, point)| RefIn::Ref { id, face, point })
        .map_err(|e| format!("{} is not a reference {{id, face?}} or a point [x, y]: {}", v.clone().sorted().to_compact(), e))
}

/// serde's `Reference {id, face, point}`, from a map (fields in sorted order, unknown ones refused)
/// or a sequence.
fn parse_reference(v: &Value) -> Result<(IdIn, Face, Option<End>), String> {
    match v {
        Value::Obj(m) => {
            let mut keys: Vec<&String> = m.items.iter().map(|(k, _)| k).collect();
            keys.sort();
            let mut id = None;
            let mut face = Face::Centre;
            let mut point = None;
            for k in keys {
                let x = m.get(k).unwrap();
                match k.as_str() {
                    "id" => id = Some(parse_id(x)?),
                    "face" => face = parse_face(x)?,
                    "point" => point = parse_point(x)?,
                    _ => return Err(format!("unknown field `{}`, expected one of `id`, `face`, `point`", k)),
                }
            }
            match id {
                Some(id) => Ok((id, face, point)),
                None => Err("missing field `id`".into()),
            }
        }
        Value::Arr(a) => {
            if a.is_empty() {
                return Err("invalid length 0, expected struct Reference with 3 elements".into());
            }
            if a.len() > 3 {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            let id = parse_id(&a[0])?;
            let face = match a.get(1) {
                Some(x) => parse_face(x)?,
                None => Face::Centre,
            };
            let point = match a.get(2) {
                Some(x) => parse_point(x)?,
                None => None,
            };
            Ok((id, face, point))
        }
        other => Err(format!("invalid type: {}, expected struct Reference", unexpected(other))),
    }
}

/// An element's GUID, or its id (a whole number, or one in a string).
pub fn parse_id(v: &Value) -> Result<IdIn, String> {
    match v {
        Value::Num(n) => {
            let f = n.as_f64();
            match n {
                Num::U(u) => Ok(IdIn::Id(*u)),
                Num::I(i) => Err(format!("{} is not an element id", i)),
                Num::F(_) => {
                    if f >= 0.0 && f.fract() == 0.0 && f < 1.8e19 {
                        Ok(IdIn::Id(f as u64))
                    } else {
                        Err(format!("{} is not an element id", f))
                    }
                }
            }
        }
        Value::Str(s) => {
            let t = s.trim();
            if let Ok(id) = t.parse::<u64>() {
                return Ok(IdIn::Id(id));
            }
            match crate::model::normalize_guid(t) {
                Some(g) => Ok(IdIn::Guid(g)),
                None => Err(format!("`{}` is not a GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or an id", s)),
            }
        }
        other => Err(format!("invalid type: {}, expected an element's GUID, or its id", unexpected(other))),
    }
}

/// A unit variant of an enum as serde reads one: its name, or a map of it to null.
fn variant<'a>(v: &'a Value, names: &[&str], expected: &str) -> Result<&'a str, String> {
    let unknown = |s: &str| format!("unknown variant `{}`, expected {}", s, expected);
    match v {
        Value::Str(s) => {
            if names.contains(&s.as_str()) {
                Ok(s.as_str())
            } else {
                Err(unknown(s))
            }
        }
        Value::Obj(m) => {
            if m.items.len() != 1 {
                return Err("invalid value: map, expected map with a single key".into());
            }
            let (k, x) = &m.items[0];
            if !names.contains(&k.as_str()) {
                return Err(unknown(k));
            }
            match x {
                Value::Null => Ok(k.as_str()),
                other => Err(format!("invalid type: {}, expected unit", unexpected(other))),
            }
        }
        other => Err(format!("invalid type: {}, expected string or map", unexpected(other))),
    }
}

fn parse_face(v: &Value) -> Result<Face, String> {
    let names = ["center", "centre", "left", "right", "start", "end"];
    let s = variant(v, &names, "one of `center`, `centre`, `left`, `right`, `start`, `end`")?;
    Ok(Face::parse(s).unwrap())
}

fn parse_point(v: &Value) -> Result<Option<End>, String> {
    if v.is_null() {
        return Ok(None);
    }
    let s = variant(v, &["start", "end"], "`start` or `end`")?;
    Ok(End::parse(s))
}

// ---------------------------------------------------------------- names in messages

/// How a message names the element a reference is to by id: "wall 100002", "line 100003".
pub fn named(pr: &Project, r: &Ref) -> String {
    match r.id(pr) {
        Some(id) => format!("{} {}", cat_of(pr, id), id),
        None => format!("element {}", r.guid()),
    }
}

/// How a message names it by GUID: "door 5451…", "detail line 8c35…".
pub fn named_guid(pr: &Project, r: &Ref) -> String {
    let c = match r.id(pr) {
        Some(id) => cat_of(pr, id),
        None => String::new(),
    };
    format!("{} {}", category_words(&c), r.guid())
}

/// A category as the messages that name an element by GUID say it.
pub fn category_words(c: &str) -> String {
    match c {
        "line" => "detail line".to_string(),
        x => x.to_string(),
    }
}

/// What of its element a reference is to: "centre line", "left face", "start", "end of its start".
pub fn what(r: &Ref) -> String {
    let f = match r.face {
        Face::Centre => "centre line",
        Face::Left => "left face",
        Face::Right => "right face",
        Face::Start => "start",
        Face::End => "end",
    };
    match r.point {
        None => f.to_string(),
        Some(p) => format!("{} of its {}", p.word(), f),
    }
}
