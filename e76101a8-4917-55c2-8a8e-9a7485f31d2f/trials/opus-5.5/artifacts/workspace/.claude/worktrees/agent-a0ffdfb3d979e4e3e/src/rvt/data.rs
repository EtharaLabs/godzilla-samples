//! An element's serialised data (from its header to the next one), the names in it, and the
//! names of materials.

use super::bytes::*;
use super::doc::Doc;
use std::collections::BTreeMap;

/// How far past its header an element's data is read.
pub const WINDOW: usize = 256 * 1024;

#[derive(Clone, Copy, Debug)]
pub struct Block {
    pub part: usize,
    /// The header's start, and where the data ends (the next header, or the window).
    pub start: usize,
    pub end: usize,
    /// Where the data proper starts, after the header.
    pub body: usize,
}

/// Every element's data blocks, by id, in partition order and then file order.
pub struct DataIndex {
    pub blocks: BTreeMap<u64, Vec<Block>>,
}

fn header_len(wide: bool) -> usize {
    // ff ff ff ff, tag, 01 00 00 00, id (u64; or u32 and four more bytes)
    4 + 2 + 4 + 8
    + if wide { 0 } else { 0 }
}

pub fn index(doc: &Doc) -> DataIndex {
    let mut blocks: BTreeMap<u64, Vec<Block>> = BTreeMap::new();
    let tag = match doc.schema.tag("CellList") {
        Some(t) => t,
        None => return DataIndex { blocks },
    };
    let mut hdr = vec![0xffu8; 4];
    hdr.extend_from_slice(&tag.to_le_bytes());
    hdr.extend_from_slice(&[1, 0, 0, 0]);
    let wide = doc.wide();
    for (pi, p) in doc.parts.iter().enumerate() {
        let d = &p.data;
        let mut starts = Vec::new();
        let mut q = 0;
        while let Some(h) = find(d, &hdr, q, d.len()) {
            starts.push(h);
            q = h + 1;
        }
        for (k, &h) in starts.iter().enumerate() {
            let id = if wide { rd_u64(d, h + 10) } else { rd_u32(d, h + 10).map(|v| v as u64) };
            let id = match id {
                Some(i) => i,
                None => continue,
            };
            let next = starts.get(k + 1).copied().unwrap_or(d.len());
            let end = next.min(h + WINDOW).min(d.len());
            let body = (h + header_len(wide)).min(end);
            blocks.entry(id).or_default().push(Block { part: pi, start: h, end, body });
        }
    }
    DataIndex { blocks }
}

impl DataIndex {
    /// The element's current data: its copy in the newest partition (the last copy there).
    pub fn newest(&self, doc: &Doc, id: u64) -> Option<Block> {
        let v = self.blocks.get(&id)?;
        for pi in doc.parts_newest_first() {
            if let Some(b) = v.iter().rev().find(|b| b.part == pi) {
                return Some(*b);
            }
        }
        None
    }
    pub fn bytes<'a>(&self, doc: &'a Doc, b: &Block) -> &'a [u8] {
        &doc.parts[b.part].data[b.start..b.end]
    }
    /// All of an element's data blocks, the newest partition's first, each partition's in file order.
    pub fn all_newest_first(&self, doc: &Doc, id: u64) -> Vec<Block> {
        let v = match self.blocks.get(&id) {
            Some(v) => v,
            None => return Vec::new(),
        };
        let mut out = Vec::new();
        for pi in doc.parts_newest_first() {
            out.extend(v.iter().filter(|b| b.part == pi).copied());
        }
        out
    }
}

/// A name read from the file, trimmed, if it is one to show: not blank, no control characters,
/// whole (and before 2023, of two characters at least).
pub fn usable_name(s: &str, release: u32) -> Option<String> {
    if s.chars().any(|c| c.is_control() || c == '\u{fffd}') {
        return None;
    }
    let t = s.trim();
    if t.is_empty() || (release <= 2022 && t.chars().count() < 2) {
        return None;
    }
    Some(t.to_string())
}

/// A counted UTF-16 string at `p` (u32 count, then the units), and where it ends.
pub fn counted(d: &[u8], p: usize, max: usize) -> Option<(String, usize)> {
    let n = rd_u32(d, p)? as usize;
    if n == 0 || n > max {
        return None;
    }
    let s = p + 4;
    let e = s.checked_add(n * 2)?;
    if e > d.len() {
        return None;
    }
    let units: Vec<u16> = d[s..e].chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
    let text = String::from_utf16(&units).ok()?;
    Some((text, e))
}

/// The name entries of a data block: `ff ff ff ff 02 10`, then a counted string.
pub fn name_entries(d: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    let mk = [0xffu8, 0xff, 0xff, 0xff, 0x02, 0x10];
    let mut q = 0;
    while let Some(p) = find(d, &mk, q, d.len()) {
        q = p + 1;
        let n = match rd_u32(d, p + 6) {
            Some(n) => n as usize,
            None => continue,
        };
        if n == 0 || n > 1000 || p + 10 + 2 * n > d.len() {
            continue;
        }
        let units: Vec<u16> = d[p + 10..p + 10 + 2 * n].chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
        out.push(String::from_utf16(&units).unwrap_or_else(|_| "\u{fffd}".to_string()));
    }
    out
}

/// A type's name: the first usable name entry of its own data.
pub fn type_name(d: &[u8], release: u32) -> Option<String> {
    name_entries(d).into_iter().find_map(|s| usable_name(&s, release))
}
