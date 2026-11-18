//! The parts of the model that carry an id and a GUID of their own (a type's layers, a family's
//! forms, symbols and connectors, a detail group's members, a sketch's lines, a shape's points and
//! split lines): those a file leaves without one, or with one another part, a library entry or an
//! element has, are given one, as the original gives them.

use crate::json::{Map, Num, Value};
use std::collections::{BTreeMap, HashSet};

fn each_in(v: Option<&mut Value>, f: &mut dyn FnMut(&mut Value)) {
    if let Some(Value::Arr(a)) = v {
        for p in a.iter_mut() {
            f(p);
        }
    }
}

/// An element's parts, in the order the original visits them.
pub fn element_parts(e: &mut Value, f: &mut dyn FnMut(&mut Value)) {
    each_in(e.get_mut("sketch"), f);
    if let Some(sh) = e.get_mut("shape") {
        each_in(sh.get_mut("points"), f);
        each_in(sh.get_mut("lines"), f);
    }
}

/// Every part of the model, in the order the original visits them: the types' layers, the
/// families' forms, symbols and connectors, the detail groups' members, then each element's.
pub fn each_part_mut(doc: &mut Map, elements: &mut BTreeMap<u64, Value>, f: &mut dyn FnMut(&mut Value)) {
    if let Some(Value::Obj(types)) = doc.get_mut("types") {
        for (k, sec) in types.items.iter_mut() {
            if k == "runs" {
                continue;
            }
            if let Value::Obj(ts) = sec {
                for (_, t) in ts.items.iter_mut() {
                    each_in(t.get_mut("layers"), f);
                }
            }
        }
    }
    if let Some(Value::Obj(fams)) = doc.get_mut("families") {
        for (_, fam) in fams.items.iter_mut() {
            each_in(fam.get_mut("forms"), f);
            each_in(fam.get_mut("symbols"), f);
            each_in(fam.get_mut("connectors"), f);
        }
    }
    if let Some(Value::Obj(groups)) = doc.get_mut("detail_groups") {
        for (_, g) in groups.items.iter_mut() {
            if let Some(Value::Arr(ms)) = g.get_mut("members") {
                for m in ms.iter_mut() {
                    f(m);
                    if let Some(el) = m.get_mut("element") {
                        element_parts(el, f);
                    }
                }
            }
        }
    }
    for (_, e) in elements.iter_mut() {
        element_parts(e, f);
    }
}

/// The ids the parts hold, in visiting order.
pub fn part_ids(doc: &Map, elements: &BTreeMap<u64, Value>) -> Vec<u64> {
    let mut d = doc.clone();
    let mut e = elements.clone();
    let mut out = Vec::new();
    each_part_mut(&mut d, &mut e, &mut |p: &mut Value| {
        if let Some(Value::Num(Num::U(n))) = p.get("id") {
            out.push(*n);
        }
    });
    out
}

/// How the original hands out ids for library entries and parts: one below the lowest any entry
/// or part has, while that stays above every element's id; else, for a library entry, the next
/// element id, and for a part, one above the highest an entry or a part has.
pub struct Alloc {
    low: u64,
    top: u64,
    next: u64,
    /// The next element id, when the library took one.
    pub next_id: Option<u64>,
}

impl Alloc {
    pub fn new(library: &BTreeMap<u64, Value>, doc: &Map, elements: &BTreeMap<u64, Value>) -> Alloc {
        let parts: Vec<u64> = part_ids(doc, elements).into_iter().filter(|n| *n != 0).collect();
        let all = library.keys().cloned().chain(parts.iter().cloned());
        let (mut low, mut top) = (1_000_000u64, 999_999u64);
        let mut any = false;
        for n in all {
            if !any {
                low = n;
                any = true;
            }
            low = low.min(n);
            top = top.max(n);
        }
        let next_id = doc.get("next_id").and_then(|v| v.as_u64()).unwrap_or(100_000);
        let after = elements.keys().next_back().map(|n| n + 1).unwrap_or(0);
        Alloc { low, top, next: next_id.max(after), next_id: None }
    }
    fn below(&mut self) -> Option<u64> {
        let c = self.low.checked_sub(1)?;
        if c >= self.next {
            self.low = c;
            Some(c)
        } else {
            None
        }
    }
    /// An id for a new library entry.
    pub fn lib(&mut self) -> u64 {
        match self.below() {
            Some(c) => c,
            None => {
                let id = self.next;
                self.next += 1;
                self.next_id = Some(self.next);
                id
            }
        }
    }
    /// An id for a part.
    pub fn part(&mut self) -> u64 {
        match self.below() {
            Some(c) => c,
            None => {
                self.top += 1;
                self.top
            }
        }
    }
}

/// Gives the parts their ids and GUIDs where the file left them without (an id of 0, one an
/// earlier part, a library entry or an element has; a GUID that is an id, none, or one an earlier
/// part, a library entry or an element has).
pub fn repair(doc: &mut Map, elements: &mut BTreeMap<u64, Value>, library: &BTreeMap<u64, Value>, alloc: &mut Alloc) {
    let element_ids: HashSet<u64> = elements.keys().cloned().collect();
    let mut seen: HashSet<u64> = HashSet::new();
    let mut taken: HashSet<String> = HashSet::new();
    for e in elements.values().chain(library.values()) {
        if let Some(Value::Str(g)) = e.get("guid") {
            taken.insert(g.clone());
        }
    }
    let mut f = |p: &mut Value| {
        let id = p.get("id").and_then(|x| x.as_u64()).unwrap_or(0);
        let fresh = id == 0 || library.contains_key(&id) || element_ids.contains(&id) || seen.contains(&id);
        let id = if fresh {
            let n = alloc.part();
            p.set("id", Value::u(n));
            n
        } else {
            id
        };
        seen.insert(id);
        let g = match p.get("guid") {
            Some(Value::Str(g)) if !taken.contains(g) => g.clone(),
            _ => {
                let g = crate::rand::guid();
                p.set("guid", Value::Str(g.clone()));
                g
            }
        };
        taken.insert(g);
    };
    each_part_mut(doc, elements, &mut f);
}
