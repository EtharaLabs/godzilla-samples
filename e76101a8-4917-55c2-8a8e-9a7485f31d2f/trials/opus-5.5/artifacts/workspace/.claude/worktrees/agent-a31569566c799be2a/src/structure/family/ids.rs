//! A family's library entries (`family`, `family-type` "Family: Type", `family-parameter`
//! "Family: Parameter") and its parts' ids and GUIDs, given as the original gives them after a
//! command: the entries first (the family's, its types' in name order, its parameters' in their
//! order), then the parts that need one (forms, symbols, connectors), ids counting down from the
//! lowest the library and the parts use (or, where that would run into the elements', the next
//! element id; for parts, up from the highest).

use crate::json::{Map, Value};
use crate::project::Project;
use std::collections::HashSet;

pub const FAMILY: &str = "family";
pub const FAMILY_TYPE: &str = "family-type";
pub const FAMILY_PARAMETER: &str = "family-parameter";

/// The library name of a family's type or parameter.
pub fn entry_name(family: &str, part: &str) -> String {
    format!("{}: {}", family, part)
}

fn scan_ids(v: &Value, f: &mut dyn FnMut(u64)) {
    match v {
        Value::Obj(m) => {
            if let Some(id) = m.get("id").and_then(|x| x.as_u64()) {
                if id != 0 {
                    f(id);
                }
            }
            m.items.iter().for_each(|(_, x)| scan_ids(x, f));
        }
        Value::Arr(a) => a.iter().for_each(|x| scan_ids(x, f)),
        _ => {}
    }
}

/// Every part id the project's sections hold: types' layers and families' parts whatever they
/// are, the other sections' in the library's range.
fn part_ids(pr: &Project, f: &mut dyn FnMut(u64)) {
    for (k, v) in &pr.doc.items {
        match k.as_str() {
            "elements" | "library" => {}
            "types" | "families" => scan_ids(v, f),
            _ => scan_ids(v, &mut |id| {
                if (900_000..1_000_000).contains(&id) {
                    f(id)
                }
            }),
        }
    }
}

/// The lowest id the library and the parts use, and the lowest handed out.
pub fn lowest(pr: &Project) -> u64 {
    let mut low = pr.lib_low.min(1_000_000);
    if let Some(k) = pr.library.keys().next() {
        low = low.min(*k);
    }
    part_ids(pr, &mut |id| low = low.min(id));
    low
}

/// The highest id the library and the parts use.
fn highest(pr: &Project) -> u64 {
    let mut high = pr.library.keys().next_back().copied().unwrap_or(0);
    part_ids(pr, &mut |id| {
        if id >= 900_000 {
            high = high.max(id)
        }
    });
    high
}

/// A new library entry's id.
pub fn alloc_entry(pr: &mut Project) -> u64 {
    let low = lowest(pr);
    let next = pr.next_id();
    if low > next {
        pr.lib_low = low - 1;
        low - 1
    } else {
        pr.doc.insert("next_id", Value::u(next + 1));
        next
    }
}

/// A new part's id.
pub fn alloc_part(pr: &mut Project) -> u64 {
    let low = lowest(pr);
    if low > pr.next_id() {
        pr.lib_low = low - 1;
        low - 1
    } else {
        highest(pr) + 1
    }
}

/// Adds a library entry of a kind and name where there's none: its id.
pub fn ensure_entry(pr: &mut Project, kind: &str, name: &str) -> u64 {
    if let Some(id) = pr.lib_find(kind, name) {
        return id;
    }
    let id = alloc_entry(pr);
    let g = crate::structure::common::new_guid();
    pr.library.insert(id, crate::jobj! {"kind" => kind, "name" => name, "guid" => g});
    id
}

/// Takes a library entry away.
pub fn remove_entry(pr: &mut Project, kind: &str, name: &str) {
    if let Some(id) = pr.lib_find(kind, name) {
        pr.library.remove(&id);
    }
}

/// Renames a library entry (it keeps its id and GUID).
pub fn rename_entry(pr: &mut Project, kind: &str, from: &str, to: &str) {
    if let Some(id) = pr.lib_find(kind, from) {
        if let Some(e) = pr.library.get_mut(&id) {
            e.set("name", Value::s(to));
        }
    }
}

/// The ids and GUIDs the project uses but those of one family's parts.
fn used_but(pr: &Project, family: &str) -> (HashSet<u64>, HashSet<String>) {
    let mut ids: HashSet<u64> = pr.elements.keys().copied().collect();
    let mut guids: HashSet<String> = HashSet::new();
    for e in pr.elements.values() {
        if let Some(g) = e.get("guid").and_then(|g| g.as_str()) {
            guids.insert(g.to_string());
        }
    }
    for (id, e) in &pr.library {
        ids.insert(*id);
        if let Some(g) = e.get("guid").and_then(|g| g.as_str()) {
            guids.insert(g.to_string());
        }
    }
    fn scan(v: &Value, ids: &mut HashSet<u64>, guids: &mut HashSet<String>) {
        match v {
            Value::Obj(m) => {
                if let Some(id) = m.get("id").and_then(|x| x.as_u64()) {
                    ids.insert(id);
                }
                if m.get("id").is_some() {
                    if let Some(g) = m.get("guid").and_then(|g| g.as_str()) {
                        guids.insert(g.to_string());
                    }
                }
                m.items.iter().for_each(|(_, x)| scan(x, ids, guids));
            }
            Value::Arr(a) => a.iter().for_each(|x| scan(x, ids, guids)),
            _ => {}
        }
    }
    for (k, v) in &pr.doc.items {
        if k == "elements" || k == "library" {
            continue;
        }
        if k == "families" {
            if let Value::Obj(fams) = v {
                for (n, f) in &fams.items {
                    if n != family {
                        scan(f, &mut ids, &mut guids);
                    }
                }
            }
            continue;
        }
        scan(v, &mut ids, &mut guids);
    }
    (ids, guids)
}

/// Gives a family's parts (in the file) that need one an id and a GUID: one it hasn't, or one
/// something else in the project (or a part of it before) has. Forms, then symbols, then
/// connectors.
pub fn fix_parts(pr: &mut Project, family: &str) {
    let (mut ids, mut guids) = used_but(pr, family);
    let mut need_id: Vec<(&'static str, usize)> = Vec::new();
    let mut new_guid: Vec<(&'static str, usize, String)> = Vec::new();
    {
        let Some(f) = pr.section("families").and_then(|m| m.get(family)) else { return };
        for key in ["forms", "symbols", "connectors"] {
            let Some(list) = f.get(key).and_then(|x| x.as_arr()) else { continue };
            for (i, part) in list.iter().enumerate() {
                match part.get("id").and_then(|x| x.as_u64()).filter(|n| *n != 0) {
                    Some(id) if !ids.contains(&id) => {
                        ids.insert(id);
                    }
                    _ => need_id.push((key, i)),
                }
                match part.get("guid").and_then(|g| g.as_str()) {
                    Some(g) if !guids.contains(g) => {
                        guids.insert(g.to_string());
                    }
                    _ => {
                        let g = crate::structure::common::new_guid();
                        guids.insert(g.clone());
                        new_guid.push((key, i, g));
                    }
                }
            }
        }
    }
    let mut fresh: Vec<u64> = Vec::with_capacity(need_id.len());
    for _ in &need_id {
        let id = alloc_part(pr);
        fresh.push(id);
        // what's handed out counts as used for the next
        set_part(pr, family, need_id[fresh.len() - 1], |m| m.insert_first("id", Value::u(id)));
    }
    for (key, i, g) in new_guid {
        set_part(pr, family, (key, i), |m| m.insert_after_id("guid", Value::s(&g)));
    }
}

trait PartMap {
    fn insert_first(&mut self, k: &str, v: Value);
    fn insert_after_id(&mut self, k: &str, v: Value);
}

impl PartMap for Map {
    fn insert_first(&mut self, k: &str, v: Value) {
        if let Some(slot) = self.get_mut(k) {
            *slot = v;
        } else {
            self.items.insert(0, (k.to_string(), v));
        }
    }
    fn insert_after_id(&mut self, k: &str, v: Value) {
        if let Some(slot) = self.get_mut(k) {
            *slot = v;
        } else {
            let at = if self.contains("id") { 1 } else { 0 };
            self.items.insert(at, (k.to_string(), v));
        }
    }
}

fn set_part(pr: &mut Project, family: &str, at: (&str, usize), f: impl FnOnce(&mut Map)) {
    let Some(fam) = pr.section_mut("families").get_mut(family) else { return };
    let Some(list) = fam.get_mut(at.0).and_then(|x| x.as_arr_mut()) else { return };
    if let Some(Value::Obj(m)) = list.get_mut(at.1) {
        f(m);
    }
}
