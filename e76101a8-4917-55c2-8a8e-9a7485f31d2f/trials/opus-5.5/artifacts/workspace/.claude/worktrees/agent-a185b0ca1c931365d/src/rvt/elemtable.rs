//! `Global/ElemTable`: the ElementIds the file declares, in the 28-byte (up to 2023) or 40-byte
//! (from 2024) record layout: two id columns (32-bit, at the record's start and at 4 or 20
//! bytes in), one of which rises; both are listed.

use std::collections::BTreeSet;

pub struct ElemTable {
    pub ids: BTreeSet<u64>,
    pub count: u32,
    pub record_len: usize,
}

fn layout(d: &[u8], count: usize, size: usize) -> Option<BTreeSet<u64>> {
    let need = 6usize.checked_add(count.checked_mul(size)?)?;
    if need > d.len() {
        return None;
    }
    let second = if size == 28 { 4 } else { 20 };
    let at = |o: usize| u32::from_le_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]]) as u64;
    let a: Vec<u64> = (0..count).map(|k| at(6 + k * size)).collect();
    let b: Vec<u64> = (0..count).map(|k| at(6 + k * size + second)).collect();
    let rises = |v: &[u64]| v.windows(2).all(|w| w[1] > w[0]);
    if !rises(&a) && !rises(&b) {
        return None;
    }
    Some(a.into_iter().chain(b).collect())
}

pub fn parse(d: &[u8], release: u32) -> Result<ElemTable, String> {
    if d.len() < 6 {
        return Err("Global/ElemTable is too short to hold its record count".into());
    }
    let count = u32::from_le_bytes([d[2], d[3], d[4], d[5]]);
    if count == 0 {
        return Err("Global/ElemTable lists no elements".into());
    }
    let order: [usize; 2] = if release >= 2024 { [40, 28] } else { [28, 40] };
    for size in order {
        if let Some(ids) = layout(d, count as usize, size) {
            return Ok(ElemTable { ids, count, record_len: size });
        }
    }
    Err(format!(
        "Global/ElemTable has no record layout (28 or 40 bytes) in which its {} records fit with ElementIds that rise",
        count
    ))
}
