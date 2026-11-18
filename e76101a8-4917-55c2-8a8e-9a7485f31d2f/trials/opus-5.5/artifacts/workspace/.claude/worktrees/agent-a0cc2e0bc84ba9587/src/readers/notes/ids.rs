//! `ids_of`, `select_by_id` and `measure`: what names an element (its id, GUID, IFC GlobalId,
//! category and name), the elements a list of names finds and the plan that shows them, and what
//! a ruler between two points reads.

use crate::json::Value;
use crate::project::Project;
use crate::readers::common::{self, r2, rn, Ctx};
use crate::session::Session;

const B64: &[u8; 64] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";

/// A GUID (hyphenated hex) compressed into IFC's 22-character GlobalId.
pub fn ifc_global_id(guid: &str) -> Option<String> {
    let hex: String = guid.chars().filter(|c| *c != '-').collect();
    if hex.len() != 32 {
        return None;
    }
    let mut bytes = [0u8; 16];
    for i in 0..16 {
        bytes[i] = u8::from_str_radix(&hex[2 * i..2 * i + 2], 16).ok()?;
    }
    let mut out = String::with_capacity(22);
    // the first byte's top two bits… as IFC does: 2 bits, then 21 groups of 6 bits
    let v = u128::from_be_bytes(bytes);
    out.push(B64[((v >> 126) & 0x3) as usize] as char);
    for i in (0..21).rev() {
        out.push(B64[((v >> (6 * i)) & 0x3f) as usize] as char);
    }
    Some(out)
}

/// An IFC GlobalId back to its GUID (lowercase, hyphenated).
pub fn guid_of_global_id(s: &str) -> Option<String> {
    if s.len() != 22 {
        return None;
    }
    let mut v: u128 = 0;
    for (i, c) in s.bytes().enumerate() {
        let d = B64.iter().position(|b| *b == c)? as u128;
        if i == 0 {
            if d > 3 {
                return None;
            }
            v = d;
        } else {
            v = (v << 6) | d;
        }
    }
    let h = format!("{:032x}", v);
    Some(format!("{}-{}-{}-{}-{}", &h[0..8], &h[8..12], &h[12..16], &h[16..20], &h[20..32]))
}

/// What a library entry or part is: its category (kind) and its name.
struct LibHit {
    id: u64,
    guid: String,
    category: String,
    name: String,
}

/// The parts of the library and of elements with ids and GUIDs of their own: types' layers,
/// families' forms, symbols and connectors, regions' sketch lines.
fn parts(pr: &Project) -> Vec<LibHit> {
    let mut out = Vec::new();
    for p in crate::media::library::parts(pr) {
        out.push(LibHit { id: p.id, guid: p.guid, category: p.kind.to_string(), name: format!("{} {} of {}", p.kind, p.index + 1, p.of) });
    }
    for (_, e) in &pr.elements {
        let Some(sk) = e.get("sketch").and_then(|s| s.as_arr()) else { continue };
        let cat = common::category(e);
        let g = common::text(e, "guid").unwrap_or("");
        for (i, s) in sk.iter().enumerate() {
            if let (Some(id), Some(sg)) = (s.get("id").and_then(|x| x.as_u64()), common::text(s, "guid")) {
                out.push(LibHit {
                    id,
                    guid: sg.to_string(),
                    category: "sketch line".into(),
                    name: format!("sketch line {} of {} {}", i + 1, cat, g),
                });
            }
        }
    }
    out
}

fn lib_category(kind: &str) -> String {
    match kind.strip_prefix("type:") {
        Some(c) => format!("{} type", c),
        None => kind.replace('-', " "),
    }
}

fn lib_hit(pr: &Project, id: u64) -> Option<LibHit> {
    if let Some(e) = pr.library.get(&id) {
        return Some(LibHit {
            id,
            guid: common::text(e, "guid").unwrap_or("").to_string(),
            category: lib_category(common::text(e, "kind").unwrap_or("")),
            name: common::text(e, "name").unwrap_or("").to_string(),
        });
    }
    parts(pr).into_iter().find(|p| p.id == id)
}

fn lib_hit_guid(pr: &Project, g: &str) -> Option<LibHit> {
    if let Some(id) = pr.lib_find_guid(g) {
        return lib_hit(pr, id);
    }
    parts(pr).into_iter().find(|p| p.guid == g)
}

/// What names an element: its name, else its type's, else its tag's text, number or mark.
pub fn element_name(cx: &Ctx, id: u64, e: &Value) -> String {
    let pr = cx.pr;
    if let Some(n) = common::text(e, "name") {
        return n.to_string();
    }
    if common::category(e) == "tag" {
        if let Some(v) = crate::readers::view::element_view(cx, id) {
            if let Some(t) = common::text(&v, "text") {
                return t.to_string();
            }
        }
    }
    if common::text(e, "type").is_some() {
        if let Some(t) = super::annot::type_name(pr, e) {
            return t;
        }
    }
    for k in ["number", "mark"] {
        if let Some(n) = common::text(e, k) {
            return n.to_string();
        }
    }
    String::new()
}

enum Found {
    Element(u64),
    Library(LibHit),
}

/// What a token names: an element or a library entry, by id, GUID (dashes and braces or not) or
/// IFC GlobalId.
fn find_token(pr: &Project, t: &str) -> Option<Found> {
    let t = t.trim();
    if t.is_empty() {
        return None;
    }
    if t.bytes().all(|b| b.is_ascii_digit()) {
        let id: u64 = t.parse().ok()?;
        if pr.elements.contains_key(&id) {
            return Some(Found::Element(id));
        }
        return lib_hit(pr, id).map(Found::Library);
    }
    let g = crate::model::normalize_guid(t).or_else(|| guid_of_global_id(t))?;
    if let Some(id) = pr.find_guid(&g) {
        return Some(Found::Element(id));
    }
    lib_hit_guid(pr, &g).map(Found::Library)
}

fn found_of_value(pr: &Project, v: &Value) -> Option<Found> {
    match v {
        Value::Num(crate::json::Num::U(u)) => find_token(pr, &u.to_string()),
        Value::Str(s) => find_token(pr, s),
        _ => None,
    }
}

/// `ids_of {ids}`.
pub fn cmd_ids_of(s: &Session, p: &Value) -> Result<Value, String> {
    let pr = &s.project;
    let ids = match crate::commands::params::get(p, "ids") {
        Some(Value::Arr(a)) => a,
        _ => return Err("ids_of: `ids` [id or GUID, …] is required".into()),
    };
    let cx = Ctx::new(pr);
    let mut out = Vec::new();
    for v in ids {
        match found_of_value(pr, v) {
            Some(Found::Element(id)) => {
                let e = pr.el(id).unwrap();
                let g = common::text(e, "guid").unwrap_or("").to_string();
                out.push(jobj! {
                    "category" => common::category(e),
                    "guid" => g.clone(),
                    "id" => id,
                    "ifc" => ifc_global_id(&g).unwrap_or_default(),
                    "name" => element_name(&cx, id, e),
                });
            }
            Some(Found::Library(h)) => {
                out.push(jobj! {
                    "category" => h.category,
                    "guid" => h.guid.clone(),
                    "id" => h.id,
                    "ifc" => ifc_global_id(&h.guid).unwrap_or_default(),
                    "name" => h.name,
                });
            }
            None => return Err(format!("ids_of: no element or library entry {}", v.to_compact())),
        }
    }
    Ok(jobj! {"elements" => Value::Arr(out)})
}

/// `select_by_id {text}`.
pub fn cmd_select_by_id(s: &Session, p: &Value) -> Result<Value, String> {
    let pr = &s.project;
    let text = match crate::commands::params::get(p, "text") {
        Some(Value::Str(t)) => t.clone(),
        _ => return Err("select_by_id: `text`, the ids, GUIDs or IFC GlobalIds to find, is required".into()),
    };
    let mut ids: Vec<u64> = Vec::new();
    let mut lib: Vec<u64> = Vec::new();
    let mut missing: Vec<Value> = Vec::new();
    for tok in text.split(|c: char| c.is_whitespace() || c == ',' || c == ';') {
        if tok.is_empty() {
            continue;
        }
        match find_token(pr, tok) {
            Some(Found::Element(id)) => {
                if !ids.contains(&id) {
                    ids.push(id);
                }
            }
            Some(Found::Library(h)) => {
                if !lib.contains(&h.id) {
                    lib.push(h.id);
                }
            }
            None => {
                let v = Value::s(tok);
                if !missing.contains(&v) {
                    missing.push(v);
                }
            }
        }
    }
    let cx = Ctx::new(pr);
    let (plan, extent) = match super::extent::selection_plan(&cx, &ids) {
        Some((pl, [lo, hi])) => (
            Value::u(pl),
            Value::Arr(vec![
                Value::Arr(vec![Value::f(rn(lo[0], 3)), Value::f(rn(lo[1], 3))]),
                Value::Arr(vec![Value::f(rn(hi[0], 3)), Value::f(rn(hi[1], 3))]),
            ]),
        ),
        None => (Value::Null, Value::Null),
    };
    Ok(jobj! {
        "extent" => extent,
        "ids" => Value::Arr(ids.iter().map(|i| Value::u(*i)).collect()),
        "library" => Value::Arr(lib.iter().map(|i| Value::u(*i)).collect()),
        "missing" => Value::Arr(missing),
        "plan" => plan,
    })
}

/// `measure {from, to}`.
pub fn cmd_measure(_s: &Session, p: &Value) -> Result<Value, String> {
    let empty = Value::obj();
    let p = if matches!(p, Value::Obj(_)) { p } else { &empty };
    let a = crate::commands::params::req_point(p, "measure", "from")?;
    let b = crate::commands::params::req_point(p, "measure", "to")?;
    let dx = b[0] - a[0];
    let dy = b[1] - a[1];
    let mut ang = dy.atan2(dx).to_degrees();
    if ang < 0.0 {
        ang += 360.0;
    }
    Ok(jobj! {
        "angle" => rn(ang, 4),
        "dx" => r2(dx),
        "dy" => r2(dy),
        "length" => r2(dx.hypot(dy)),
    })
}
