//! Material names: each material's object, its name read by the rules in order, and a category's
//! material in the object styles.

use super::bytes::*;
use super::cats;
use super::data::{self, DataIndex};
use super::doc::Doc;
use std::collections::BTreeMap;

const REGION: usize = 0x400;
const PARAM_NAME: i64 = -1001203;

pub struct Materials {
    /// material id → name (as read), if a name could be read
    pub names: BTreeMap<u64, Option<String>>,
}

fn name_at(d: &[u8], p: usize, release: u32) -> Option<String> {
    let (s, _) = data::counted(d, p, 256)?;
    data::usable_name(&s, release)
}

/// A counted string that ends exactly at `end`.
fn name_ending_at(d: &[u8], end: usize, release: u32) -> Option<String> {
    for n in 1..=256usize {
        if end < 4 + 2 * n {
            break;
        }
        let p = end - 4 - 2 * n;
        if rd_u32(d, p) == Some(n as u32) {
            if let Some(s) = name_at(d, p, release) {
                return Some(s);
            }
        }
    }
    None
}

/// The objects `01 00 00 00` + id with the Material tag where it belongs, in a partition.
fn objects(d: &[u8], id: u64, wide: bool, tag: u16) -> Vec<usize> {
    let mut key = vec![1u8, 0, 0, 0];
    if wide {
        key.extend_from_slice(&id.to_le_bytes());
    } else {
        key.extend_from_slice(&(id as u32).to_le_bytes());
    }
    let off = if wide { 4 + 0x47 } else { 4 + 0x27 };
    let mut out = Vec::new();
    let mut q = 0;
    while let Some(p) = find(d, &key, q, d.len()) {
        q = p + 1;
        if rd_u16(d, p + off) == Some(tag) {
            out.push(p);
        }
    }
    out
}

fn read_name(doc: &Doc, idx: &DataIndex, id: u64) -> Option<String> {
    let wide = doc.wide();
    let mtag = doc.schema.tag("Material")?;
    let pps = doc.schema.tag("PhysicalParamSet");
    let ph = doc.schema.tag("PatternHelper");
    // the newest copy: the newest partition's last object
    let mut found: Option<(usize, usize)> = None;
    for pi in doc.parts_newest_first() {
        let objs = objects(&doc.parts[pi].data, id, wide, mtag);
        if let Some(&p) = objs.last() {
            found = Some((pi, p));
            break;
        }
    }
    let (pi, p) = found?;
    let d = &doc.parts[pi].data;
    let tag_at = p + if wide { 4 + 0x47 } else { 4 + 0x27 };
    let end = (tag_at + REGION).min(d.len());
    // its own name field
    if let Some(s) = name_at(d, tag_at + 2 + 8, doc.release) {
        return Some(s);
    }
    // the string that ends at PhysicalParamSet
    if let Some(t) = pps {
        let mut mk = vec![0xffu8; 4];
        mk.extend_from_slice(&t.to_le_bytes());
        if let Some(m) = find(d, &mk, tag_at + 2, end) {
            if let Some(s) = name_ending_at(d, m, doc.release) {
                return Some(s);
            }
        }
    }
    // the first string framed by PatternHelper (from 2024)
    if let Some(t) = ph.filter(|_| wide) {
        let mut mk = vec![0xffu8; 4];
        mk.extend_from_slice(&t.to_le_bytes());
        if let Some(m) = find(d, &mk, tag_at + 2, end) {
            if let Some(s) = name_at(d, m + 6, doc.release) {
                return Some(s);
            }
        }
    }
    // the -1001203 entry
    let key: Vec<u8> = if wide { PARAM_NAME.to_le_bytes().to_vec() } else { (PARAM_NAME as i32).to_le_bytes().to_vec() };
    if let Some(m) = find(d, &key, tag_at + 2, end) {
        if let Some(s) = name_at(d, m + key.len() + 4, doc.release) {
            return Some(s);
        }
    }
    if wide {
        // the string closed by eight zero bytes, the id and ff x8
        let mut mk = vec![0u8; 8];
        mk.extend_from_slice(&id.to_le_bytes());
        mk.extend_from_slice(&[0xff; 8]);
        if let Some(m) = find(d, &mk, tag_at + 2, end) {
            if let Some(s) = name_ending_at(d, m, doc.release) {
                return Some(s);
            }
        }
    } else if let Some(b) = idx.newest(doc, id) {
        // the first framed name in its own data
        let bytes = idx.bytes(doc, &b);
        if let Some(s) = data::name_entries(bytes).into_iter().find_map(|s| data::usable_name(&s, doc.release)) {
            return Some(s);
        }
    }
    None
}

pub fn read(doc: &Doc, idx: &DataIndex) -> Materials {
    let mut names = BTreeMap::new();
    for r in &doc.records {
        if r.category == cats::OST_MATERIALS && !r.boxed && doc.declared(r.id) && !names.contains_key(&r.id) {
            names.insert(r.id, read_name(doc, idx, r.id));
        }
    }
    Materials { names }
}

impl Materials {
    pub fn is_material(&self, id: u64) -> bool {
        self.names.contains_key(&id)
    }
    pub fn name(&self, id: u64) -> Option<&str> {
        self.names.get(&id).and_then(|n| n.as_deref())
    }
}

/// The material a category has in the object styles, when the file says it once.
pub fn category_material(doc: &Doc, mats: &Materials, cat: i64) -> Option<u64> {
    if doc.release > 2024 {
        return None;
    }
    let mut found: Vec<u64> = Vec::new();
    for p in &doc.parts {
        let d = &p.data;
        if doc.wide() {
            let mut key = cat.to_le_bytes().to_vec();
            key.extend_from_slice(&[0xff; 8]);
            key.extend_from_slice(&[1, 0, 0, 0]);
            key.extend_from_slice(&[0xff; 8]);
            let mut q = 0;
            while let Some(m) = find(d, &key, q, d.len()) {
                q = m + 1;
                if let Some(mid) = rd_u64(d, m + key.len()) {
                    if mats.is_material(mid) {
                        found.push(mid);
                    }
                }
            }
        } else {
            let mut key = (cat as i32).to_le_bytes().to_vec();
            key.extend_from_slice(&[0xff; 4]);
            key.extend_from_slice(&[1, 0, 0, 0]);
            let mut q = 0;
            while let Some(m) = find(d, &key, q, d.len()) {
                q = m + 1;
                let s = m + key.len();
                for o in s..(s + 32).min(d.len().saturating_sub(4)) {
                    if let Some(v) = rd_u32(d, o) {
                        if mats.is_material(v as u64) {
                            found.push(v as u64);
                            break;
                        }
                    }
                }
            }
        }
    }
    if found.len() == 1 {
        Some(found[0])
    } else {
        None
    }
}
