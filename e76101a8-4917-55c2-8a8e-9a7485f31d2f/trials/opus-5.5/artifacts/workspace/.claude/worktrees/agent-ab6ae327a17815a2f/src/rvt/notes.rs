//! What the import tells about what it did not read: notes on elements that came in as stand-ins,
//! and the elements left out, counted by kind and cause.

use std::collections::BTreeMap;

/// A kind of element as the notes name it: singular and plural.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Kind {
    pub one: String,
    pub many: String,
}

impl Kind {
    pub fn new(one: &str, many: &str) -> Kind {
        Kind { one: one.to_string(), many: many.to_string() }
    }
    pub fn simple(one: &str) -> Kind {
        Kind { one: one.to_string(), many: format!("{}s", one) }
    }
}

#[derive(Default)]
pub struct Notes {
    /// Messages of the level reading, in order (no ids).
    pub first: Vec<String>,
    /// Categories with no reader: category → (name, ids).
    pub no_reader: BTreeMap<i64, (String, Vec<u64>)>,
    /// (kind, note) → ids: elements that came in, with what was not read of them.
    pub notes: BTreeMap<(String, String), (Kind, Vec<u64>)>,
    /// (kind, reason) → ids: elements left out.
    pub left: BTreeMap<(String, String), (Kind, Vec<u64>)>,
}

pub fn ids_text(ids: &[u64]) -> String {
    let mut parts: Vec<String> = ids.iter().take(8).map(|i| i.to_string()).collect();
    if ids.len() > 8 {
        parts.push("…".to_string());
    }
    format!("(ids {})", parts.join(", "))
}

impl Notes {
    pub fn note(&mut self, kind: &Kind, text: &str, id: u64) {
        let e = self.notes.entry((kind.one.clone(), text.to_string())).or_insert_with(|| (kind.clone(), Vec::new()));
        if !e.1.contains(&id) {
            e.1.push(id);
        }
    }
    pub fn leave(&mut self, kind: &Kind, reason: &str, id: u64) {
        let e = self.left.entry((kind.one.clone(), reason.to_string())).or_insert_with(|| (kind.clone(), Vec::new()));
        if !e.1.contains(&id) {
            e.1.push(id);
        }
    }
    pub fn no_reader(&mut self, cat: i64, name: &str, id: u64) {
        let e = self.no_reader.entry(cat).or_insert_with(|| (name.to_string(), Vec::new()));
        if !e.1.contains(&id) {
            e.1.push(id);
        }
    }

    pub fn lines(&self) -> Vec<String> {
        let mut out = self.first.clone();
        // the most elements first, then by category
        let mut groups: Vec<(&i64, &(String, Vec<u64>))> = self.no_reader.iter().collect();
        groups.sort_by(|a, b| b.1 .1.len().cmp(&a.1 .1.len()).then(a.0.cmp(b.0)));
        for (_, (name, ids)) in groups {
            let mut ids = ids.clone();
            ids.sort();
            out.push(format!(
                "{} {} left out, the importer has no reader for this category {}",
                ids.len(),
                name,
                ids_text(&ids)
            ));
        }
        for ((_, text), (kind, ids)) in &self.notes {
            let mut ids = ids.clone();
            ids.sort();
            let k = if ids.len() == 1 { &kind.one } else { &kind.many };
            out.push(format!("{} {}: {} {}", ids.len(), k, text, ids_text(&ids)));
        }
        for ((_, reason), (kind, ids)) in &self.left {
            let mut ids = ids.clone();
            ids.sort();
            let k = if ids.len() == 1 { &kind.one } else { &kind.many };
            out.push(format!("{} {} left out, {} {}", ids.len(), k, reason, ids_text(&ids)));
        }
        out
    }
}
