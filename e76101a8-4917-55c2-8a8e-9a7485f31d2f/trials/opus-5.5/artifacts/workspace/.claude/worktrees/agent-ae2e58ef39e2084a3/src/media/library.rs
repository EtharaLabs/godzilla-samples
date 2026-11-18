//! `library`: the project's library entries with their ids and GUIDs, and the parts entries
//! hold that have an id and a GUID of their own (types' layers, families' forms, symbols and
//! connectors), each listed by id.

use crate::commands::params::*;
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

/// A part of a library entry: (id, guid, index in its list, kind, what it's of, its owner's name).
pub struct Part {
    pub id: u64,
    pub guid: String,
    pub index: usize,
    pub kind: &'static str,
    pub of: String,
    pub owner: String,
}

fn id_guid(v: &Value) -> Option<(u64, String)> {
    let id = v.get("id")?.as_u64()?;
    let g = v.get("guid")?.as_str()?.to_string();
    Some((id, g))
}

/// Every part, in id order.
pub fn parts(pr: &Project) -> Vec<Part> {
    let mut out = Vec::new();
    if let Some(types) = pr.section("types") {
        for (cat, ts) in types.iter() {
            if cat == "runs" {
                continue;
            }
            let Some(ts) = ts.as_obj() else { continue };
            for (tn, t) in ts.iter() {
                if let Some(layers) = t.get("layers").and_then(|l| l.as_arr()) {
                    for (i, l) in layers.iter().enumerate() {
                        if let Some((id, guid)) = id_guid(l) {
                            out.push(Part {
                                id,
                                guid,
                                index: i,
                                kind: "layer",
                                of: format!("{} type {}", super::material::type_word(cat), tn),
                                owner: tn.clone(),
                            });
                        }
                    }
                }
            }
        }
    }
    if let Some(fams) = pr.section("families") {
        for (fname, f) in fams.iter() {
            for (key, kind) in [("forms", "form"), ("symbols", "symbol"), ("connectors", "connector")] {
                if let Some(list) = f.get(key).and_then(|l| l.as_arr()) {
                    for (i, x) in list.iter().enumerate() {
                        if let Some((id, guid)) = id_guid(x) {
                            out.push(Part { id, guid, index: i, kind, of: format!("family {}", fname), owner: fname.clone() });
                        }
                    }
                }
            }
        }
    }
    out.sort_by_key(|p| p.id);
    out
}

pub fn cmd(s: &mut Session, p: &Value) -> Result<Value, String> {
    let kind = opt_text(p, "library", "kind")?;
    let name = opt_text(p, "library", "name")?;
    let pr = &s.project;
    let mut lib = Vec::new();
    for (id, e) in &pr.library {
        let k = e.get("kind").and_then(|x| x.as_str()).unwrap_or("");
        let n = e.get("name").and_then(|x| x.as_str()).unwrap_or("");
        if kind.as_deref().map(|w| w != k).unwrap_or(false) || name.as_deref().map(|w| w != n).unwrap_or(false) {
            continue;
        }
        lib.push(jobj! {
            "guid" => e.get("guid").cloned().unwrap_or(Value::Null),
            "id" => *id,
            "kind" => k,
            "name" => n,
        });
    }
    let mut ps = Vec::new();
    for part in parts(pr) {
        if kind.as_deref().map(|w| w != part.kind).unwrap_or(false) || name.as_deref().map(|w| w != part.owner).unwrap_or(false) {
            continue;
        }
        ps.push(jobj! {
            "guid" => part.guid,
            "id" => part.id,
            "index" => part.index,
            "kind" => part.kind,
            "of" => part.of,
        });
    }
    let n = lib.len();
    Ok(jobj! {"count" => n, "library" => Value::Arr(lib), "parts" => Value::Arr(ps)})
}
