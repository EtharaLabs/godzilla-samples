//! The elements of a project by `BuiltInCategory` (placed instances told from the rest) and its levels.

use super::cats;
use super::doc::Doc;
use super::levels::{self, Block};
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub struct Level {
    pub id: u64,
    pub name: String,
    /// Feet, as in the file.
    pub elevation: f64,
    pub story: Option<bool>,
}

pub struct Inventory {
    /// category → id → placed
    pub cats: BTreeMap<i64, BTreeMap<u64, bool>>,
    pub levels: Vec<Level>,
    pub owned: Vec<u64>,
    pub unread: Vec<u64>,
}

/// The placed level records' ids, in id order.
pub fn level_ids(doc: &Doc) -> Vec<u64> {
    let mut m: BTreeMap<u64, bool> = BTreeMap::new();
    for r in &doc.records {
        if r.category == cats::OST_LEVELS && !r.boxed && !r.inner && doc.declared(r.id) {
            let e = m.entry(r.id).or_insert(false);
            *e = *e || r.placed();
        }
    }
    m.into_iter().filter(|(_, p)| *p).map(|(id, _)| id).collect()
}

/// The block of a level, from the newest partition that has one.
pub fn level_block(doc: &Doc, id: u64) -> Option<Block> {
    for i in doc.parts_newest_first() {
        if let Some(b) = levels::block(&doc.parts[i].data, id, doc.wide(), doc.plane) {
            return Some(b);
        }
    }
    None
}

pub fn inventory(doc: &Doc) -> Inventory {
    let mut c: BTreeMap<i64, BTreeMap<u64, bool>> = BTreeMap::new();
    for r in &doc.records {
        if !(r.boxed || r.category == cats::OST_LEVELS) {
            continue;
        }
        if !r.inner && !doc.declared(r.id) {
            continue;
        }
        if !cats::plausible(r.category) {
            continue;
        }
        let e = c.entry(r.category).or_default().entry(r.id).or_insert(false);
        *e = *e || r.placed();
    }
    let mut lv = Vec::new();
    let mut owned = Vec::new();
    let mut unread = Vec::new();
    for id in level_ids(doc) {
        match level_block(doc, id) {
            Some(Block::Read { name, elevation, story }) => lv.push(Level { id, name, elevation, story }),
            Some(Block::Owned) => owned.push(id),
            None => unread.push(id),
        }
    }
    Inventory { cats: c, levels: lv, owned, unread }
}

/// Feet to millimetres, as the reader shows them (to a thousandth of a millimetre).
pub fn mm3(ft: f64) -> f64 {
    // a level just below zero shows as -0.0
    ((ft * 304.8) * 1000.0).round() / 1000.0
}
