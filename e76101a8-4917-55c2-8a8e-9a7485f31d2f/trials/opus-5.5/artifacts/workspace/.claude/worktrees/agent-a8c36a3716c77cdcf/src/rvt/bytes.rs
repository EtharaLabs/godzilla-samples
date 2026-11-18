//! Bounds-checked little-endian reads and byte searches.

pub fn rd_u8(d: &[u8], o: usize) -> Option<u8> {
    d.get(o).copied()
}
pub fn rd_u16(d: &[u8], o: usize) -> Option<u16> {
    let b = d.get(o..o.checked_add(2)?)?;
    Some(u16::from_le_bytes([b[0], b[1]]))
}
pub fn rd_u32(d: &[u8], o: usize) -> Option<u32> {
    let b = d.get(o..o.checked_add(4)?)?;
    Some(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}
pub fn rd_i32(d: &[u8], o: usize) -> Option<i32> {
    rd_u32(d, o).map(|v| v as i32)
}
pub fn rd_u64(d: &[u8], o: usize) -> Option<u64> {
    let b = d.get(o..o.checked_add(8)?)?;
    Some(u64::from_le_bytes(b.try_into().ok()?))
}
pub fn rd_i64(d: &[u8], o: usize) -> Option<i64> {
    rd_u64(d, o).map(|v| v as i64)
}
pub fn rd_f64(d: &[u8], o: usize) -> Option<f64> {
    rd_u64(d, o).map(f64::from_bits)
}

/// The first place in `d[from..to]` where `needle` starts (wholly inside the range).
pub fn find(d: &[u8], needle: &[u8], from: usize, to: usize) -> Option<usize> {
    let to = to.min(d.len());
    if needle.is_empty() || from >= to || to - from < needle.len() {
        return None;
    }
    let first = needle[0];
    let last_start = to - needle.len();
    let mut i = from;
    while i <= last_start {
        match d[i..=last_start].iter().position(|b| *b == first) {
            Some(k) => {
                let s = i + k;
                if &d[s..s + needle.len()] == needle {
                    return Some(s);
                }
                i = s + 1;
            }
            None => return None,
        }
    }
    None
}

/// UTF-16LE text, with what does not decode replaced.
pub fn utf16(d: &[u8]) -> String {
    let u: Vec<u16> = d.chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
    String::from_utf16_lossy(&u)
}
