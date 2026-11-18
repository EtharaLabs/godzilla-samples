//! The records of a partition: each element's frame (id, category, container, placement kind,
//! class, box) and its two reference lists, in the 2024 chain form and the earlier marker form.

use super::bytes::*;

pub const KIND_PLACED: u32 = 0xffff_ef7f;
pub const KIND_TYPE: u32 = 0xffff_8080;
pub const KIND_MATERIAL: u32 = 0xffff_8020;
pub const OST_LEVELS: i64 = -2000240;

#[derive(Clone, Debug)]
pub struct Record {
    pub id: u64,
    pub category: i64,
    pub container: u64,
    pub kind: u32,
    pub class_tag: u16,
    /// The full marker with a box after it (an element), not a box-less record (a type, a level…).
    pub boxed: bool,
    pub bbox: Option<[f64; 6]>,
    pub refs: Vec<u64>,
    pub refs2: Vec<u64>,
    /// A placed instance framed inside another record's body: it takes that record's id.
    pub inner: bool,
    pub partition: usize,
    /// Where the frame starts and the record ends in the partition's data.
    pub start: usize,
    pub end: usize,
}

impl Record {
    pub fn placed(&self) -> bool {
        self.kind == KIND_PLACED && (self.container == u64::MAX || self.container == u32::MAX as u64)
    }
}

pub struct Tags {
    pub outline: u16,
    pub parents: u16,
    pub header: u16,
}

fn marker8(t: &Tags) -> [u8; 8] {
    let mut m = [0u8; 8];
    m[0..2].copy_from_slice(&t.outline.to_le_bytes());
    m[2..6].copy_from_slice(&[0xff; 4]);
    m[6..8].copy_from_slice(&t.parents.to_le_bytes());
    m
}

fn marker6(t: &Tags) -> [u8; 6] {
    let mut m = [0u8; 6];
    m[0..4].copy_from_slice(&[0xff; 4]);
    m[4..6].copy_from_slice(&t.parents.to_le_bytes());
    m
}

/// A counted list of ids at `p` (`u64` from 2024, `u32` before); the list and where it ends.
fn id_list(d: &[u8], p: usize, wide: bool, limit: usize) -> Option<(Vec<u64>, usize)> {
    let n = rd_u32(d, p)? as usize;
    let w = if wide { 8 } else { 4 };
    let end = p.checked_add(4)?.checked_add(n.checked_mul(w)?)?;
    if end > limit || end > d.len() {
        return None;
    }
    let mut v = Vec::with_capacity(n);
    for k in 0..n {
        let o = p + 4 + k * w;
        v.push(if wide { rd_u64(d, o)? } else { rd_u32(d, o)? as u64 });
    }
    Some((v, end))
}

/// A record's box (feet): numbers within the reader's limit, each minimum at most its maximum;
/// a record with any other box is no record.
fn read_box(d: &[u8], p: usize) -> Option<[f64; 6]> {
    let mut b = [0f64; 6];
    for (k, x) in b.iter_mut().enumerate() {
        *x = rd_f64(d, p + 8 * k)?;
        if !x.is_finite() || x.abs() > super::curves::MAX_FEET {
            return None;
        }
    }
    if b[0] > b[3] || b[1] > b[4] || b[2] > b[5] {
        return None;
    }
    Some(b)
}

/// The records of a partition from 2024 on: a frame 0x50 bytes before each marker. A frame
/// inside a record whose length the record's two copies of it agree on is one of its placed
/// instances (its own id 0 or one the table declares): it takes the record's id; any other
/// frame is a record of its own.
pub fn chain(d: &[u8], t: &Tags, partition: usize, declared: &dyn Fn(u64) -> bool) -> Vec<Record> {
    let m8 = marker8(t);
    let m6 = marker6(t);
    let mut marks: Vec<(usize, bool)> = Vec::new();
    let mut q = 0usize;
    while let Some(p) = find(d, &m6, q, d.len()) {
        q = p + 1;
        if p >= 2 && d[p - 2..p + 6] == m8 {
            marks.push((p - 2, true));
        } else {
            marks.push((p, false));
        }
    }
    let mut out = Vec::new();
    // the record frames fall in: its start, its end (past its closing length) and its id
    let mut enclosing: Option<(usize, usize, u64)> = None;
    for &(m, boxed) in &marks {
        if m < 0x50 {
            continue;
        }
        let fs = m - 0x50;
        if let Some((s, e, eid)) = enclosing {
            if fs > s && fs < e {
                if boxed {
                    let own = rd_u64(d, fs).unwrap_or(0);
                    if own == 0 || declared(own) {
                        if let Some(mut r) = frame_2024(d, fs, e - 16, eid, t, &m8, &m6, partition, true) {
                            if r.placed() {
                                r.inner = true;
                                out.push(r);
                            }
                        }
                    }
                }
                continue;
            }
        }
        let id = match rd_u64(d, fs) {
            Some(i) => i,
            None => continue,
        };
        let size = rd_u32(d, fs + 8).unwrap_or(0) as usize;
        let whole = fs.checked_add(size).and_then(|x| x.checked_add(16)).map(|x| x <= d.len()).unwrap_or(false)
            && rd_u32(d, fs + size + 12) == Some(size as u32);
        let end = if whole { fs + size } else { d.len() };
        if let Some(r) = frame_2024(d, fs, end, id, t, &m8, &m6, partition, false) {
            out.push(r);
        }
        enclosing = if whole { Some((fs, fs + size + 16, id)) } else { None };
    }
    out
}

#[allow(clippy::too_many_arguments)]
fn frame_2024(
    d: &[u8],
    fs: usize,
    end: usize,
    id: u64,
    _t: &Tags,
    m8: &[u8; 8],
    m6: &[u8; 6],
    partition: usize,
    inner: bool,
) -> Option<Record> {
    let m = fs + 0x50;
    if m + 8 > d.len() {
        return None;
    }
    let boxed = &d[m..m + 8] == m8;
    let tail = &d[m..m + 6] == m6;
    if !boxed && !tail {
        return None;
    }
    // the two bytes before the category are zero in a frame
    if rd_u16(d, fs + 0x10)? != 0 {
        return None;
    }
    let category = rd_i64(d, fs + 0x12)?;
    let container = rd_u64(d, fs + 0x32)?;
    let kind = rd_u32(d, fs + 0x42)?;
    let class_tag = rd_u16(d, fs + 0x4a)?;
    let (bbox, refs, refs2) = if boxed {
        let bbox = Some(read_box(d, m + 8)?);
        let (refs, e1) = id_list(d, m + 8 + 48, true, end).unwrap_or((Vec::new(), m + 56));
        let refs2 = id_list(d, e1, true, end).map(|(v, _)| v).unwrap_or_default();
        (bbox, refs, refs2)
    } else {
        let refs = id_list(d, m + 6, true, end).map(|(v, _)| v).unwrap_or_default();
        (None, refs, Vec::new())
    };
    Some(Record { id, category, container, kind, class_tag, boxed, bbox, refs, refs2, inner, partition, start: fs, end })
}

/// The records of a partition in the marker form (up to 2023): each found by its marker and
/// read back from it.
pub fn markers(d: &[u8], t: &Tags, partition: usize) -> Vec<Record> {
    let mut out = Vec::new();
    let m6 = marker6(t);
    let mut q = 0usize;
    while let Some(p) = find(d, &m6, q, d.len()) {
        q = p + 1;
        let boxed = p >= 2 && rd_u16(d, p - 2) == Some(t.outline);
        let m = if boxed { p - 2 } else { p };
        let mut idp = None;
        let mut k = 0usize;
        while m >= 52 + 14 * k {
            let cand = m - 52 - 14 * k;
            if rd_u16(d, cand + 8) == Some(t.header) && rd_u32(d, cand + 10) == Some(k as u32) {
                idp = Some(cand);
                break;
            }
            k += 1;
            if k > 10_000 {
                break;
            }
        }
        let idp = match idp {
            Some(i) => i,
            None => continue,
        };
        if m < 38 {
            continue;
        }
        let id = rd_u32(d, idp).unwrap() as u64;
        let size = rd_u32(d, idp + 4).unwrap_or(0) as usize;
        let end = (idp + size).min(d.len()).max(m + 6);
        let category = match rd_i64(d, m - 38) {
            Some(c) => c,
            None => continue,
        };
        let container = rd_u32(d, m - 22).unwrap_or(0) as u64;
        let kind = rd_u32(d, m - 14).unwrap_or(0);
        let class_tag = rd_u16(d, m - 6).unwrap_or(0);
        let (bbox, refs, refs2) = if boxed {
            let bbox = match read_box(d, m + 8) {
                Some(b) => Some(b),
                None => continue,
            };
            let (refs, e1) = id_list(d, m + 56, false, d.len()).unwrap_or((Vec::new(), m + 56));
            let refs2 = id_list(d, e1, false, d.len()).map(|(v, _)| v).unwrap_or_default();
            (bbox, refs, refs2)
        } else {
            (None, Vec::new(), Vec::new())
        };
        out.push(Record {
            id,
            category,
            container,
            kind,
            class_tag,
            boxed,
            bbox,
            refs,
            refs2,
            inner: false,
            partition,
            start: idp,
            end,
        });
    }
    out
}
