//! What `bimcraft-cli info x.rvt` shows.

use super::atom::Atom;
use super::basic::BasicInfo;
use super::cats;
use super::doc::Doc;
use super::inventory::{self, inventory};
use crate::json::{Map, Value};

pub const NOTE: &str = "saved_by is the file's Username line, which is set only when worksharing is on; saved_to is the path it was last saved to, on the saving machine. Both are shown here and written nowhere else";

fn opt(s: &Option<String>) -> Value {
    match s {
        Some(x) => Value::s(x),
        None => Value::Null,
    }
}

pub fn elements(doc: &Doc) -> Value {
    let inv = inventory(doc);
    let mut cats_out = Vec::new();
    let mut total = 0usize;
    let mut placed = 0usize;
    for (cat, ids) in &inv.cats {
        let n = ids.len();
        let p = ids.values().filter(|v| **v).count();
        total += n;
        placed += p;
        cats_out.push(jobj! {
            "category" => Value::i(*cat),
            "elements" => n,
            "name" => match cats::name(*cat) { Some(s) => Value::s(s), None => Value::Null },
            "placed" => p,
        });
    }
    let mut levels: Vec<(f64, u64, Value)> = inv
        .levels
        .iter()
        .map(|l| {
            let mm = inventory::mm3(l.elevation);
            (
                mm,
                l.id,
                jobj! {
                    "building_story" => match l.story { Some(b) => Value::Bool(b), None => Value::Null },
                    "elevation" => Value::f(mm),
                    "id" => l.id,
                    "name" => l.name.as_str(),
                },
            )
        })
        .collect();
    levels.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then(a.1.cmp(&b.1)));
    let mut m = Map::new();
    m.insert("categories", Value::Arr(cats_out));
    m.insert("declared", Value::u(doc.table.ids.len() as u64));
    m.insert("levels", Value::Arr(levels.into_iter().map(|x| x.2).collect()));
    m.insert("owned_levels", Value::Arr(inv.owned.iter().map(|i| Value::u(*i)).collect()));
    m.insert("placed", Value::u(placed as u64));
    m.insert("total", Value::u(total as u64));
    m.insert("unread_levels", Value::u(inv.unread.len() as u64));
    Value::Obj(m)
}

pub fn build(basic: &BasicInfo, atom: &Atom, elements: Value) -> Value {
    let mut revit = Map::new();
    revit.insert("build", opt(&basic.build));
    revit.insert("document", opt(&basic.document));
    revit.insert("locale", opt(&basic.locale));
    revit.insert("omniclass", opt(&atom.omniclass));
    revit.insert("release", Value::u(basic.release as u64));
    revit.insert("saved", opt(&atom.updated));
    revit.insert("title", opt(&atom.title));
    revit.insert("worksharing", opt(&basic.worksharing));
    let mut m = Map::new();
    m.insert("elements", elements);
    m.insert("note", Value::s(NOTE));
    m.insert("revit", Value::Obj(revit));
    m.insert("saved_by", opt(&basic.username));
    m.insert("saved_to", opt(&basic.last_save_path));
    Value::Obj(m)
}
