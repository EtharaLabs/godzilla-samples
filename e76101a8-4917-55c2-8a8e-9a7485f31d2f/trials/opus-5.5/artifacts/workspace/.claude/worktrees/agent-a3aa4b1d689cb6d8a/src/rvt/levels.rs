//! Levels: each one's name and elevation, from the block keyed by its ElementId, its Building Story
//! setting, and the levels that sit inside other elements.

use super::bytes::*;

/// The largest elevation (feet) a level may have.
pub const MAX_ELEVATION_FT: f64 = 1e7;

#[derive(Clone, Debug)]
pub enum Block {
    Read { name: String, elevation: f64, story: Option<bool> },
    /// A level inside another element (a group's, a family's): not a project level.
    Owned,
}

/// The block of level `id` in a partition's data.
pub fn block(d: &[u8], id: u64, wide: bool, plane: u16) -> Option<Block> {
    let mut key = Vec::new();
    if wide {
        key.extend_from_slice(&id.to_le_bytes());
        key.extend_from_slice(&[0xff; 56]);
    } else {
        key.extend_from_slice(&(id as u32).to_le_bytes());
        key.extend_from_slice(&[0xff; 28]);
    }
    if let Some(q) = find(d, &key, 0, d.len()) {
        if let Some(b) = read_block(d, q + key.len(), id, wide, plane) {
            return Some(b);
        }
    }
    if wide {
        let mut owned = vec![1u8, 0, 0, 0];
        owned.extend_from_slice(&id.to_le_bytes());
        owned.extend_from_slice(&[0xff; 8]);
        if find(d, &owned, 0, d.len()).is_some() {
            return Some(Block::Owned);
        }
    }
    None
}

fn read_block(d: &[u8], after_key: usize, id: u64, wide: bool, plane: u16) -> Option<Block> {
    // a flag (0 or 1) and two zero bytes, then the name
    if !matches!(d.get(after_key)?, 0 | 1) || *d.get(after_key + 1)? != 0 || *d.get(after_key + 2)? != 0 {
        return None;
    }
    let p = after_key + 3;
    let n = rd_u32(d, p)? as usize;
    // a name of 1 to 128 units, whole UTF-16, no control characters
    if n == 0 || n > 128 {
        return None;
    }
    let name_start = p + 4;
    let name_end = name_start.checked_add(n.checked_mul(2)?)?;
    if name_end > d.len() {
        return None;
    }
    let units: Vec<u16> = d[name_start..name_end].chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
    let name = String::from_utf16(&units).ok()?;
    if name.chars().any(|c| c.is_control()) {
        return None;
    }
    let mut mk = vec![5u8, 0, 0, 0];
    mk.extend_from_slice(&plane.to_le_bytes());
    let m = find(d, &mk, name_end, name_end + 0x800)?;
    let ep = m + 55;
    let elevation = rd_f64(d, ep)?;
    if ep < 24 || ep + 8 > d.len() {
        return None;
    }
    let chunk = &d[ep - 24..ep + 8];
    find(d, chunk, ep + 8, d.len())?;
    if !elevation.is_finite() || elevation.abs() > MAX_ELEVATION_FT {
        return None;
    }
    // the Building Story setting
    let mut unset = vec![0xffu8; if wide { 8 } else { 4 }];
    unset.extend_from_slice(&[0, 1]);
    let mut story = None;
    if let Some(s) = find(d, &unset, name_end, name_end + 0x200) {
        let t = s + unset.len() + 8;
        let own: Vec<u8> = if wide { id.to_le_bytes().to_vec() } else { (id as u32).to_le_bytes().to_vec() };
        if d.get(t..t + own.len()) == Some(&own[..]) {
            story = match d.get(t + own.len()) {
                Some(1) => Some(true),
                Some(0) => Some(false),
                _ => None,
            };
        }
    }
    Some(Block::Read { name, elevation, story })
}
