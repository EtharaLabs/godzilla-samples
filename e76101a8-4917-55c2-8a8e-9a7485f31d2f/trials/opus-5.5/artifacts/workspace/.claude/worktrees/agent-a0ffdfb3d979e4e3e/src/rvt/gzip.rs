//! Gzip members (RFC 1952) in Revit's streams: the stored pages, the header, a bounded inflate.

use super::deflate::{self, Error as InflateError};

/// A stored page: 65,249 bytes, of which the first 64,896 are data.
pub const PAGE: usize = 65_249;
pub const PAGE_DATA: usize = 64_896;
/// What one stream may inflate to.
pub const INFLATE_CAP: usize = 512 << 20;
/// A single-member stream has its member within its first 256 bytes.
pub const HEAD_WINDOW: usize = 256;

/// Whether the container stores the stream in pages.
pub fn is_paged(name: &str) -> bool {
    name.starts_with("Partitions/")
        || matches!(
            name,
            "Formats/Latest"
                | "Global/ContentDocuments"
                | "Global/DocumentIncrementTable"
                | "Global/ElemTable"
                | "Global/History"
                | "Global/Latest"
                | "Global/PartitionTable"
        )
}

/// The stream with the run at the end of each whole page taken out (a short last page is kept whole).
pub fn strip_pages(data: &[u8]) -> Vec<u8> {
    if data.len() < PAGE {
        return data.to_vec();
    }
    let mut out = Vec::with_capacity(data.len());
    let mut i = 0;
    while i < data.len() {
        if i + PAGE <= data.len() {
            out.extend_from_slice(&data[i..i + PAGE_DATA]);
        } else {
            out.extend_from_slice(&data[i..]);
        }
        i += PAGE;
    }
    out
}

fn find_magic(data: &[u8], from: usize, limit: usize) -> Option<usize> {
    let end = limit.min(data.len());
    let mut i = from;
    while i + 3 <= data.len() && i < end {
        if data[i] == 0x1f && data[i + 1] == 0x8b && data[i + 2] == 0x08 {
            return Some(i);
        }
        i += 1;
    }
    None
}

/// The offset of the deflate data of the member whose magic is at `m`.
fn parse_header(data: &[u8], m: usize) -> Result<usize, String> {
    let cut = || "the gzip header is cut short".to_string();
    if m + 10 > data.len() {
        return Err(cut());
    }
    let flg = data[m + 3];
    if flg & 0xe0 != 0 {
        return Err(cut());
    }
    let mut p = m + 10;
    if flg & 0x04 != 0 {
        if p + 2 > data.len() {
            return Err(cut());
        }
        let xlen = u16::from_le_bytes([data[p], data[p + 1]]) as usize;
        p += 2;
        if p + xlen > data.len() {
            return Err(cut());
        }
        p += xlen;
    }
    for bit in [0x08u8, 0x10] {
        if flg & bit != 0 {
            match data[p.min(data.len())..].iter().position(|b| *b == 0) {
                Some(z) => p += z + 1,
                None => return Err(cut()),
            }
        }
    }
    if flg & 0x02 != 0 {
        if p + 2 > data.len() {
            return Err(cut());
        }
        p += 2;
    }
    Ok(p)
}

fn inflate_err(e: &InflateError) -> String {
    match e {
        InflateError::Truncated => "incomplete deflate stream".to_string(),
        _ => "corrupt deflate stream".to_string(),
    }
}

pub struct Members {
    pub data: Vec<u8>,
    pub members: usize,
    pub trailers: usize,
}

/// Inflates the one member of a stream that has its member at its head (`Formats/Latest`, `Global/*`).
pub fn inflate_single(name: &str, data: &[u8]) -> Result<Vec<u8>, String> {
    let data = if is_paged(name) { strip_pages(data) } else { data.to_vec() };
    let m = match find_magic(&data, 0, HEAD_WINDOW) {
        Some(m) => m,
        None => return Err(format!("stream {} has no gzip data in it", name)),
    };
    let fail = |e: String| format!("stream {} does not inflate at byte {}: {}", name, m, e);
    let p = parse_header(&data, m).map_err(fail)?;
    match deflate::inflate(&data[p..], INFLATE_CAP) {
        Ok(r) => Ok(r.data),
        Err(e) => Err(fail(inflate_err(&e))),
    }
}

/// Inflates and joins the members of a partition, each found by its magic from the end of the last one.
pub fn inflate_members(name: &str, data: &[u8]) -> Result<Members, String> {
    let data = if is_paged(name) { strip_pages(data) } else { data.to_vec() };
    let mut out = Vec::new();
    let mut members = 0;
    let mut trailers = 0;
    let mut pos = 0;
    let mut last_err: Option<String> = None;
    let mut found_any = false;
    while let Some(m) = find_magic(&data, pos, usize::MAX) {
        found_any = true;
        let p = match parse_header(&data, m) {
            Ok(p) => p,
            Err(e) => {
                last_err = Some(format!("stream {} does not inflate at byte {}: {}", name, m, e));
                pos = m + 1;
                continue;
            }
        };
        let cap = INFLATE_CAP.saturating_sub(out.len());
        match deflate::inflate(&data[p..], cap) {
            Ok(r) => {
                let end = p + r.consumed;
                let crc = crate::inflate::crc32(&r.data);
                let mut next = end;
                if end + 8 <= data.len() {
                    let c = u32::from_le_bytes([data[end], data[end + 1], data[end + 2], data[end + 3]]);
                    let l = u32::from_le_bytes([data[end + 4], data[end + 5], data[end + 6], data[end + 7]]);
                    if c == crc && l == r.data.len() as u32 {
                        trailers += 1;
                        next = end + 8;
                    }
                }
                out.extend_from_slice(&r.data);
                members += 1;
                pos = next;
            }
            Err(e) => {
                last_err = Some(format!("stream {} does not inflate at byte {}: {}", name, m, inflate_err(&e)));
                pos = m + 1;
            }
        }
    }
    if members == 0 {
        if !found_any {
            return Err(format!("stream {} has no gzip data in it", name));
        }
        return Err(last_err.unwrap_or_else(|| format!("stream {} has no gzip data in it", name)));
    }
    Ok(Members { data: out, members, trailers })
}
