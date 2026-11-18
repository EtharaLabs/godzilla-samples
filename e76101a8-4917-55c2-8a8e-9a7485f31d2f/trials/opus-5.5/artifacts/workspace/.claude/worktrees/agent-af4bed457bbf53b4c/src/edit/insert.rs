//! Insert from File: elements of another project brought into this one.
//!
//! `insert {path, ids?}` reads the other project (a .bimcraft as Open reads one, or an IFC file
//! as Open imports one; the path as given, from where the program runs), then brings in its
//! library (`insert_lib`) and the elements named in `ids` (their ids there; all without, or with
//! none) with what they point at (`insert_elems`). Replies `ids` {there: here}, `copies` (the
//! elements given GUIDs of their own, here), `library` (what came in) and `left_out` (values the
//! elements had that this project can't hold).

use super::common::*;
use super::insert_lib::Ids;
use crate::commands::params::opt_text;
use crate::json::{Map, Value};
use crate::project::Project;
use crate::session::Session;

pub fn run(s: &mut Session, p: &Value) -> R<Value> {
    let path = match opt_text(p, "insert", "path")? {
        Some(x) => x,
        None => return Err("insert: `path` is required".into()),
    };
    let src = super::link::read_project(&path).map_err(|e| format!("insert: {}", e))?;
    let named: Option<Vec<u64>> = match p.get("ids") {
        None | Some(Value::Null) => None,
        Some(Value::Arr(a)) if a.is_empty() => None,
        Some(Value::Arr(a)) => {
            let mut v: Vec<u64> = Vec::new();
            for x in a {
                let id = resolve(&src, "insert", x)?;
                if !v.contains(&id) {
                    v.push(id);
                }
            }
            Some(v)
        }
        Some(_) => return Err("insert: `ids` [id, …] is required".into()),
    };
    insert_project(&mut s.project, &src, named)
}

/// Brings `src`'s library and elements (`named`, or all) into `pr`; the reply.
pub fn insert_project(pr: &mut Project, src: &Project, named: Option<Vec<u64>>) -> R<Value> {
    let mut ids = Ids::of(pr);
    let lib = super::insert_lib::merge(pr, src, &mut ids);
    let sel = super::insert_elems::select(pr, src, named);
    // the parts of what comes in count as held while the library's are given new ids
    if let Some(low) = sel.lowest_part(src) {
        ids.low = ids.low.min(low);
    }
    super::insert_lib::renumber_imported(pr, &lib.copied, &mut ids);
    let placed = super::insert_elems::place(pr, src, sel, &lib, &mut ids)?;
    pr.lib_low = pr.lib_low.min(ids.low);
    drop_unplaced_cads(pr);
    let mut idm = Map::new();
    for (there, here) in &placed.ids {
        idm.insert(&there.to_string(), Value::u(*here));
    }
    Ok(crate::jobj! {
        "copies" => Value::Arr(placed.copies.iter().map(|x| Value::u(*x)).collect()),
        "ids" => Value::Obj(idm),
        "left_out" => Value::Arr(placed.left_out.iter().map(|x| Value::s(x)).collect()),
        "library" => Value::Arr(lib.labels.iter().map(|x| Value::s(x)).collect()),
    })
}

/// A CAD drawing nothing places goes, as a scan does (one that came in with the library while
/// no import of it did is listed, then gone).
fn drop_unplaced_cads(pr: &mut Project) {
    let names: Vec<String> = match pr.section("cads") {
        Some(m) => m.keys().cloned().collect(),
        None => return,
    };
    let placed: std::collections::HashSet<String> = pr
        .elements
        .values()
        .filter(|e| cat_of(e) == "cadimport")
        .filter_map(|e| e.get("cad").and_then(|c| c.as_str()).map(|s| s.to_string()))
        .collect();
    let mut changed = false;
    for n in names {
        let g = pr.lib_guid("cad", &n);
        if g.as_ref().map(|g| placed.contains(g)).unwrap_or(false) {
            continue;
        }
        if let Some(id) = pr.lib_find("cad", &n) {
            pr.library.remove(&id);
        }
        if let Some(Value::Obj(m)) = pr.doc.get_mut("cads") {
            m.remove(&n);
        }
        changed = true;
    }
    if changed && pr.section("cads").map(|m| m.is_empty()).unwrap_or(false) {
        pr.remove_top("cads");
    }
}
