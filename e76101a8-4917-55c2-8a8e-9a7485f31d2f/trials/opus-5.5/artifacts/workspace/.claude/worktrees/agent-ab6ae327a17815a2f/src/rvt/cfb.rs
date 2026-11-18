//! A Compound File (MS-CFB) reader, opened permissively, whose errors read as those of the
//! `cfb` crate the original reader used.

const MAGIC: [u8; 8] = [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1];
const HEADER_LEN: usize = 512;
const MAX_REGULAR_SECTOR: u32 = 0xFFFF_FFFA;
const DIFAT_SECTOR: u32 = 0xFFFF_FFFC;
const FAT_SECTOR: u32 = 0xFFFF_FFFD;
const END_OF_CHAIN: u32 = 0xFFFF_FFFE;
const FREE_SECTOR: u32 = 0xFFFF_FFFF;
const NO_STREAM: u32 = 0xFFFF_FFFF;
const MAX_REGULAR_STREAM_ID: u32 = 0xFFFF_FFFA;
const MINI_SECTOR_LEN: usize = 64;
const MINI_STREAM_CUTOFF: u32 = 4096;
const NUM_DIFAT_ENTRIES_IN_HEADER: usize = 109;

pub const OBJ_UNALLOCATED: u8 = 0;
pub const OBJ_STORAGE: u8 = 1;
pub const OBJ_STREAM: u8 = 2;
pub const OBJ_ROOT: u8 = 5;

fn fill_err() -> String {
    "failed to fill whole buffer".to_string()
}

#[derive(Clone, Debug)]
pub struct DirEntry {
    pub name: String,
    pub obj_type: u8,
    pub left: u32,
    pub right: u32,
    pub child: u32,
    pub start: u32,
    pub len: u64,
}

pub struct Cfb {
    data: Vec<u8>,
    sector_len: usize,
    num_sectors: u32,
    fat: Vec<u32>,
    minifat: Vec<u32>,
    pub entries: Vec<DirEntry>,
}

fn u16_at(d: &[u8], o: usize) -> u16 {
    u16::from_le_bytes([d[o], d[o + 1]])
}
fn u32_at(d: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]])
}
fn u64_at(d: &[u8], o: usize) -> u64 {
    let mut b = [0u8; 8];
    b.copy_from_slice(&d[o..o + 8]);
    u64::from_le_bytes(b)
}

/// The names of the object types, as the `cfb` crate's `Debug` shows them.
fn obj_type_name(t: u8) -> &'static str {
    match t {
        OBJ_UNALLOCATED => "Unallocated",
        OBJ_STORAGE => "Storage",
        OBJ_STREAM => "Stream",
        _ => "Root",
    }
}

/// Compares two names as the `cfb` crate (and MS-CFB) orders siblings: shorter first, then by
/// the uppercased UTF-16 code units.
pub fn compare_names(a: &str, b: &str) -> std::cmp::Ordering {
    let au: Vec<u16> = a.encode_utf16().collect();
    let bu: Vec<u16> = b.encode_utf16().collect();
    match au.len().cmp(&bu.len()) {
        std::cmp::Ordering::Equal => {}
        o => return o,
    }
    a.to_uppercase().cmp(&b.to_uppercase())
}

/// A reader over the file's bytes that fails as `read_exact` does when it runs out.
struct At<'a> {
    d: &'a [u8],
    pos: usize,
    end: usize,
}

impl<'a> At<'a> {
    fn u8(&mut self) -> Result<u8, String> {
        if self.pos + 1 > self.end {
            self.pos = self.end;
            return Err(fill_err());
        }
        let v = self.d[self.pos];
        self.pos += 1;
        Ok(v)
    }
    fn u16(&mut self) -> Result<u16, String> {
        if self.pos + 2 > self.end {
            self.pos = self.end;
            return Err(fill_err());
        }
        let v = u16_at(self.d, self.pos);
        self.pos += 2;
        Ok(v)
    }
    fn u32(&mut self) -> Result<u32, String> {
        if self.pos + 4 > self.end {
            self.pos = self.end;
            return Err(fill_err());
        }
        let v = u32_at(self.d, self.pos);
        self.pos += 4;
        Ok(v)
    }
    fn u64(&mut self) -> Result<u64, String> {
        if self.pos + 8 > self.end {
            self.pos = self.end;
            return Err(fill_err());
        }
        let v = u64_at(self.d, self.pos);
        self.pos += 8;
        Ok(v)
    }
    fn skip(&mut self, n: usize) -> Result<(), String> {
        if self.pos + n > self.end {
            self.pos = self.end;
            return Err(fill_err());
        }
        self.pos += n;
        Ok(())
    }
}

impl Cfb {
    /// A reader positioned in a sector (the rest of the sector, as far as the file goes).
    fn sector_reader(&self, sector: u32, offset: usize) -> Result<At<'_>, String> {
        if sector >= self.num_sectors {
            return Err(format!(
                "Tried to seek to sector {}, but sector count is only {}",
                sector, self.num_sectors
            ));
        }
        let start = (sector as usize + 1) * self.sector_len + offset;
        let end = ((sector as usize + 2) * self.sector_len).min(self.data.len());
        Ok(At { d: &self.data, pos: start.min(end), end })
    }

    fn next_sector(&self, sector: u32) -> Result<u32, String> {
        let index = sector as usize;
        if index >= self.fat.len() {
            return Err(format!(
                "Found reference to sector {}, but FAT has only {} entries",
                index,
                self.fat.len()
            ));
        }
        let next = self.fat[index];
        if next != END_OF_CHAIN && (next > MAX_REGULAR_SECTOR || next as usize >= self.fat.len()) {
            return Err(format!("next_id ({}) is invalid", next));
        }
        Ok(next)
    }

    fn next_mini_sector(&self, sector: u32) -> Result<u32, String> {
        let index = sector as usize;
        if index >= self.minifat.len() {
            return Err(format!(
                "Found reference to mini sector {}, but MiniFAT has only {} entries",
                index,
                self.minifat.len()
            ));
        }
        let next = self.minifat[index];
        if next != END_OF_CHAIN && (next > MAX_REGULAR_SECTOR || next as usize >= self.minifat.len()) {
            return Err(format!("next_id ({}) is invalid", next));
        }
        Ok(next)
    }

    /// The sectors of a chain from its first one (a chain that comes back to it is refused).
    fn chain(&self, start: u32) -> Result<Vec<u32>, String> {
        let mut ids = Vec::new();
        let mut cur = start;
        while cur != END_OF_CHAIN {
            ids.push(cur);
            cur = self.next_sector(cur)?;
            if cur == start || ids.len() > self.fat.len() + 1 {
                return Err(format!("Chain contained duplicate sector id {}", cur));
            }
        }
        Ok(ids)
    }

    fn mini_chain(&self, start: u32) -> Result<Vec<u32>, String> {
        let mut ids = Vec::new();
        let mut cur = start;
        while cur != END_OF_CHAIN {
            ids.push(cur);
            cur = self.next_mini_sector(cur)?;
            if cur == start || ids.len() > self.minifat.len() + 1 {
                return Err(format!("Minichain contained duplicate sector id {}", cur));
            }
        }
        Ok(ids)
    }

    /// Reads `len` bytes of a regular chain, from its start.
    fn read_chain(&self, start: u32, len: u64) -> Result<Vec<u8>, String> {
        let ids = self.chain(start)?;
        let chain_len = ids.len() as u64 * self.sector_len as u64;
        if len > chain_len {
            return Err(fill_err());
        }
        let mut out = Vec::with_capacity(len as usize);
        let mut left = len as usize;
        for id in ids {
            if left == 0 {
                break;
            }
            let r = self.sector_reader(id, 0)?;
            let take = left.min(self.sector_len);
            let avail = r.end - r.pos;
            if avail < take {
                out.extend_from_slice(&self.data[r.pos..r.end]);
                return Err(fill_err());
            }
            out.extend_from_slice(&self.data[r.pos..r.pos + take]);
            left -= take;
        }
        Ok(out)
    }

    /// Reads `len` bytes of a mini chain, from its start, each mini sector where the mini
    /// stream (the root entry's chain) has it, in order.
    fn read_mini(&self, start: u32, len: u64) -> Result<Vec<u8>, String> {
        let ids = self.mini_chain(start)?;
        let root = &self.entries[0];
        let root_sectors = self.chain(root.start)?;
        let mut out = Vec::with_capacity(len as usize);
        let mut left = len as usize;
        let mut k = 0usize;
        while left > 0 {
            if k >= ids.len() {
                return Err(fill_err());
            }
            let off = ids[k] as u64 * MINI_SECTOR_LEN as u64;
            let take = left.min(MINI_SECTOR_LEN);
            let sec_idx = (off / self.sector_len as u64) as usize;
            let in_sec = (off % self.sector_len as u64) as usize;
            if sec_idx >= root_sectors.len() {
                return Err("invalid sector id".to_string());
            }
            let r = self.sector_reader(root_sectors[sec_idx], in_sec)?;
            let avail = r.end - r.pos;
            if avail < take {
                return Err(fill_err());
            }
            out.extend_from_slice(&self.data[r.pos..r.pos + take]);
            left -= take;
            k += 1;
        }
        Ok(out)
    }

    /// The whole of a stream entry.
    pub fn read_stream(&self, idx: usize) -> Result<Vec<u8>, String> {
        let e = &self.entries[idx];
        if e.len == 0 {
            return Ok(Vec::new());
        }
        if e.len < MINI_STREAM_CUTOFF as u64 {
            self.read_mini(e.start, e.len)
        } else {
            self.read_chain(e.start, e.len)
        }
    }

    /// The entries in the order the `cfb` crate's `walk()` gives them (each storage, then what
    /// it holds, siblings in name order), with their paths (no leading slash). The root is left out.
    pub fn walk(&self) -> Vec<(String, usize)> {
        let mut out = Vec::new();
        // (parent path, id, visit siblings)
        let mut stack: Vec<(String, u32, bool)> = Vec::new();
        let left_spine = |stack: &mut Vec<(String, u32, bool)>, parent: &str, mut id: u32| {
            let mut guard = 0;
            while id != NO_STREAM && (id as usize) < self.entries.len() && guard <= self.entries.len() {
                stack.push((parent.to_string(), id, true));
                id = self.entries[id as usize].left;
                guard += 1;
            }
        };
        left_spine(&mut stack, "", self.entries[0].child);
        let mut steps = 0usize;
        while let Some((parent, id, visit)) = stack.pop() {
            steps += 1;
            if steps > 4 * self.entries.len() + 16 {
                break;
            }
            let e = &self.entries[id as usize];
            let path = if parent.is_empty() { e.name.clone() } else { format!("{}/{}", parent, e.name) };
            if visit {
                left_spine(&mut stack, &parent, e.right);
            }
            if e.obj_type != OBJ_STREAM {
                left_spine(&mut stack, &path, e.child);
            }
            out.push((path, id as usize));
        }
        out
    }

    /// The stream a path names, found as the `cfb` crate finds it: the path's parts (empty ones
    /// and `.` dropped, `..` going up), each looked up among the siblings by name order.
    pub fn open_stream(&self, path: &str) -> Result<usize, String> {
        let mut names: Vec<&str> = Vec::new();
        for part in path.split('/') {
            match part {
                "" | "." => {}
                ".." => {
                    if names.pop().is_none() {
                        return Err("Invalid path (must be within root)".to_string());
                    }
                }
                p => names.push(p),
            }
        }
        let shown = format!("/{}", names.join("/"));
        let mut id = 0u32;
        for name in &names {
            id = self.entries[id as usize].child;
            let mut guard = 0;
            loop {
                if id == NO_STREAM || id as usize >= self.entries.len() || guard > self.entries.len() {
                    return Err(format!("No such stream: {}", debug_str(&shown)));
                }
                let e = &self.entries[id as usize];
                match compare_names(name, &e.name) {
                    std::cmp::Ordering::Equal => break,
                    std::cmp::Ordering::Less => id = e.left,
                    std::cmp::Ordering::Greater => id = e.right,
                }
                guard += 1;
            }
        }
        if self.entries[id as usize].obj_type != OBJ_STREAM {
            return Err(format!("Not a stream: {}", debug_str(&shown)));
        }
        Ok(id as usize)
    }
}

/// A name as Rust's `Debug` shows a string: quoted, with escapes.
fn debug_str(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '\0' => out.push_str("\\0"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            '\n' => out.push_str("\\n"),
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            c if (c as u32) < 0x20 || (0x7f..0xa0).contains(&(c as u32)) || c == '\u{ad}' => {
                out.push_str(&format!("\\u{{{:x}}}", c as u32))
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn read_dir_entry(r: &mut At, version: u16) -> Result<DirEntry, String> {
    let bad = |m: String| -> Result<DirEntry, String> { Err(format!("Malformed directory entry ({})", m)) };
    let mut name_chars = [0u16; 32];
    for c in name_chars.iter_mut() {
        *c = r.u16()?;
    }
    let name_len_bytes = r.u16()?;
    if name_len_bytes > 64 {
        return bad(format!("name length too large: {}", name_len_bytes));
    } else if name_len_bytes % 2 != 0 {
        return bad(format!("odd name length: {}", name_len_bytes));
    }
    let n = if name_len_bytes > 0 { (name_len_bytes / 2 - 1) as usize } else { 0 };
    let mut name = match String::from_utf16(&name_chars[..n]) {
        Ok(s) => s,
        Err(_) => return bad("name not valid UTF-16".to_string()),
    };
    let obj_type = r.u8()?;
    if !matches!(obj_type, 0 | 1 | 2 | 5) {
        return bad(format!("invalid object type: {}", obj_type));
    }
    // the root's name is taken to be what it should be
    if obj_type == OBJ_ROOT {
        name = "Root Entry".to_string();
    }
    for c in ['/', '\\', ':', '!'] {
        if name.contains(c) {
            return Err(format!("Object name cannot contain {} character", c));
        }
    }
    let color = r.u8()?;
    if color > 1 {
        return bad(format!("invalid color: {}", color));
    }
    let left = r.u32()?;
    if left != NO_STREAM && left > MAX_REGULAR_STREAM_ID {
        return bad(format!("invalid left sibling: {}", left));
    }
    let right = r.u32()?;
    if right != NO_STREAM && right > MAX_REGULAR_STREAM_ID {
        return bad(format!("invalid right sibling: {}", right));
    }
    let child = r.u32()?;
    if child != NO_STREAM {
        if obj_type == OBJ_STREAM {
            return bad(format!("non-empty stream child: {}", child));
        } else if child > MAX_REGULAR_STREAM_ID {
            return bad(format!("invalid child: {}", child));
        }
    }
    r.skip(16)?; // CLSID
    let _state = r.u32()?;
    let _created = r.u64()?;
    let _modified = r.u64()?;
    let mut start = r.u32()?;
    let mut len = r.u64()?;
    if version == 3 {
        len &= 0xFFFF_FFFF;
    }
    if obj_type == OBJ_STORAGE {
        start = 0;
        len = 0;
    }
    Ok(DirEntry { name, obj_type, left, right, child, start, len })
}

macro_rules! malformed_fat {
    ($($arg:tt)+) => { return Err(format!("Malformed FAT ({})", format!($($arg)+))) };
}
macro_rules! malformed_dir {
    ($($arg:tt)+) => { return Err(format!("Malformed directory ({})", format!($($arg)+))) };
}

/// Opens a Compound File from its bytes; the error is the `cfb` crate's message.
pub fn open(data: Vec<u8>) -> Result<Cfb, String> {
    let inner_len = data.len() as u64;
    if (data.len()) < HEADER_LEN {
        return Err(format!("Invalid CFB file ({} bytes is too small)", inner_len));
    }
    // header
    if data[..8] != MAGIC {
        return Err("Invalid CFB file (wrong magic number)".to_string());
    }
    let _minor = u16_at(&data, 24);
    let version = u16_at(&data, 26);
    let bom = u16_at(&data, 28);
    if bom != 0xFFFE {
        return Err(format!(
            "Invalid CFB byte order mark (expected 0x{:04X}, found 0x{:04X})",
            0xFFFE, bom
        ));
    }
    let (sector_shift_want, sector_len) = match version {
        3 => (9u16, 512usize),
        4 => (12u16, 4096usize),
        _ => return Err(format!("CFB version {} is not supported", version)),
    };
    let sector_shift = u16_at(&data, 30);
    if sector_shift != sector_shift_want {
        return Err(format!(
            "Incorrect sector shift for CFB version {} (expected {}, found {})",
            version, sector_shift_want, sector_shift
        ));
    }
    let mini_shift = u16_at(&data, 32);
    if mini_shift != 6 {
        return Err(format!("Incorrect mini sector shift (expected {}, found {})", 6, mini_shift));
    }
    let first_dir_sector = u32_at(&data, 48);
    let cutoff = u32_at(&data, 56);
    if cutoff != MINI_STREAM_CUTOFF {
        return Err(format!(
            "Incorrect mini stream cutoff (expected {}, found {})",
            MINI_STREAM_CUTOFF, cutoff
        ));
    }
    let first_minifat_sector = u32_at(&data, 60);
    let mut first_difat_sector = u32_at(&data, 68);
    if first_difat_sector == FREE_SECTOR {
        first_difat_sector = END_OF_CHAIN;
    }
    let mut initial = Vec::with_capacity(NUM_DIFAT_ENTRIES_IN_HEADER);
    for i in 0..NUM_DIFAT_ENTRIES_IN_HEADER {
        let next = u32_at(&data, 76 + 4 * i);
        if next == FREE_SECTOR {
            break;
        } else if next > MAX_REGULAR_SECTOR {
            return Err(format!("Initial DIFAT array refers to invalid sector index 0x{:08X}", next));
        }
        initial.push(next);
    }
    if inner_len > (MAX_REGULAR_SECTOR as u64 + 1) * sector_len as u64 {
        return Err(format!("Invalid CFB file ({} bytes is too large)", inner_len));
    }
    if inner_len < sector_len as u64 {
        return Err(format!(
            "Invalid CFB file (length of {} < sector length of {})",
            inner_len, sector_len
        ));
    }
    let num_sectors = ((inner_len + sector_len as u64 - 1) / sector_len as u64) as u32 - 1;
    let mut cfb = Cfb { data, sector_len, num_sectors, fat: Vec::new(), minifat: Vec::new(), entries: Vec::new() };

    // DIFAT: the header's part (to its first free entry, the rest free), then its chain
    let mut difat: Vec<u32> = initial.clone();
    difat.resize(NUM_DIFAT_ENTRIES_IN_HEADER, FREE_SECTOR);
    let mut seen = std::collections::HashSet::new();
    let mut difat_sector_ids = Vec::new();
    let mut cur = first_difat_sector;
    while cur != END_OF_CHAIN && cur != FREE_SECTOR {
        if cur > MAX_REGULAR_SECTOR {
            return Err(format!("DIFAT chain includes invalid sector index {}", cur));
        } else if cur >= num_sectors {
            return Err(format!(
                "DIFAT chain includes sector index {}, but sector count is only {}",
                cur, num_sectors
            ));
        }
        if !seen.insert(cur) {
            return Err(format!("DIFAT chain includes duplicate sector index {}", cur));
        }
        difat_sector_ids.push(cur);
        let mut r = cfb.sector_reader(cur, 0)?;
        for _ in 0..(sector_len / 4 - 1) {
            let next = r.u32()?;
            if next != FREE_SECTOR && next > MAX_REGULAR_SECTOR {
                return Err(format!("DIFAT refers to invalid sector index {}", next));
            }
            difat.push(next);
        }
        cur = r.u32()?;
    }
    while difat.last() == Some(&FREE_SECTOR) {
        difat.pop();
    }

    // FAT
    let mut fat = Vec::new();
    for &s in &difat {
        if s >= num_sectors {
            return Err(format!("DIFAT refers to sector {}, but sector count is only {}", s, num_sectors));
        }
        let mut r = cfb.sector_reader(s, 0)?;
        for _ in 0..(sector_len / 4) {
            fat.push(r.u32()?);
        }
    }
    // the FAT's tail beyond the file's sectors: padding (free entries, or zeros)
    let n = num_sectors as usize;
    while fat.len() > n && fat.last() == Some(&FREE_SECTOR) {
        fat.pop();
    }
    while fat.len() > n && fat.last() == Some(&0) {
        fat.pop();
    }
    while fat.len() > n && fat.last() == Some(&FREE_SECTOR) {
        fat.pop();
    }
    if fat.len() > n {
        let unused = |v: u32| v == FREE_SECTOR || v == 0 || v == FAT_SECTOR || v == DIFAT_SECTOR;
        if fat[n..].iter().all(|v| unused(*v)) {
            fat.truncate(n);
        } else {
            malformed_fat!("FAT has {} entries, but file has only {} sectors", fat.len(), num_sectors);
        }
    }
    // sectors the FAT does not reach are free
    fat.resize(n, FREE_SECTOR);
    for &ds in &difat_sector_ids {
        let ds = ds as usize;
        if ds >= fat.len() {
            malformed_fat!("FAT has {} entries, but DIFAT lists {} as a DIFAT sector", fat.len(), ds);
        }
        fat[ds] = DIFAT_SECTOR;
    }
    for &fs in &difat {
        let fs = fs as usize;
        if fs >= fat.len() {
            malformed_fat!("FAT has {} entries, but DIFAT lists {} as a FAT sector", fat.len(), fs);
        }
        fat[fs] = FAT_SECTOR;
    }
    let mut pointees = std::collections::HashSet::new();
    let len = fat.len();
    for from in 0..len {
        let to = fat[from];
        if to <= MAX_REGULAR_SECTOR {
            if to as usize >= len {
                // a link past the file's sectors ends its chain
                fat[from] = END_OF_CHAIN;
                continue;
            }
            if !pointees.insert(to) {
                malformed_fat!("sector {} pointed to twice", to);
            }
        }
    }
    cfb.fat = fat;

    // directory
    let mut entries = Vec::new();
    let mut seen_dir = std::collections::HashSet::new();
    let mut cur = first_dir_sector;
    while cur != END_OF_CHAIN {
        if cur > MAX_REGULAR_SECTOR {
            return Err(format!("Directory chain includes invalid sector index {}", cur));
        } else if cur >= num_sectors {
            return Err(format!(
                "Directory chain includes sector index {}, but sector count is only {}",
                cur, num_sectors
            ));
        }
        if !seen_dir.insert(cur) {
            return Err(format!("Directory chain includes duplicate sector index {}", cur));
        }
        let mut r = cfb.sector_reader(cur, 0)?;
        for _ in 0..(sector_len / 128) {
            entries.push(read_dir_entry(&mut r, version)?);
        }
        cur = cfb.next_sector(cur)?;
    }
    // Directory::validate
    if entries.is_empty() {
        malformed_dir!("root entry is missing");
    }
    if entries[0].len % MINI_SECTOR_LEN as u64 != 0 {
        malformed_dir!("root stream len is {}, but should be multiple of {}", entries[0].len, MINI_SECTOR_LEN);
    }
    {
        let mut visited = std::collections::HashSet::new();
        let mut stack = vec![0u32];
        while let Some(id) = stack.pop() {
            if !visited.insert(id) {
                malformed_dir!("loop in tree");
            }
            let e = &entries[id as usize];
            if id == 0 {
                if e.obj_type != OBJ_ROOT {
                    malformed_dir!("root entry has object type {}", obj_type_name(e.obj_type));
                }
            } else if e.obj_type != OBJ_STORAGE && e.obj_type != OBJ_STREAM {
                malformed_dir!("non-root entry with object type {}", obj_type_name(e.obj_type));
            }
            if e.left != NO_STREAM {
                if e.left as usize >= entries.len() {
                    malformed_dir!(
                        "left sibling index is {}, but directory entry count is {}",
                        e.left,
                        entries.len()
                    );
                }
                let l = &entries[e.left as usize];
                if compare_names(&l.name, &e.name) != std::cmp::Ordering::Less {
                    malformed_dir!("name ordering, {} vs {}", debug_str(&e.name), debug_str(&l.name));
                }
                stack.push(e.left);
            }
            if e.right != NO_STREAM {
                if e.right as usize >= entries.len() {
                    malformed_dir!(
                        "right sibling index is {}, but directory entry count is {}",
                        e.right,
                        entries.len()
                    );
                }
                let rt = &entries[e.right as usize];
                if compare_names(&e.name, &rt.name) != std::cmp::Ordering::Less {
                    malformed_dir!("name ordering, {} vs {}", debug_str(&e.name), debug_str(&rt.name));
                }
                stack.push(e.right);
            }
            if e.child != NO_STREAM {
                if e.child as usize >= entries.len() {
                    malformed_dir!("child index is {}, but directory entry count is {}", e.child, entries.len());
                }
                stack.push(e.child);
            }
        }
    }
    cfb.entries = entries;

    // MiniFAT: its chain (none at the end of a chain), as long as the mini stream needs
    let mut minifat = Vec::new();
    if first_minifat_sector != END_OF_CHAIN {
        let ids = cfb.chain(first_minifat_sector)?;
        for id in ids {
            let mut r = cfb.sector_reader(id, 0)?;
            for _ in 0..(sector_len / 4) {
                minifat.push(r.u32()?);
            }
        }
    }
    while minifat.last() == Some(&FREE_SECTOR) {
        minifat.pop();
    }
    {
        let root_mini = (cfb.entries[0].len / MINI_SECTOR_LEN as u64) as usize;
        if minifat.len() > root_mini {
            minifat.truncate(root_mini);
        }
        let mut pointees = std::collections::HashSet::new();
        for (from, &to) in minifat.iter().enumerate() {
            if to <= MAX_REGULAR_SECTOR {
                if to as usize >= minifat.len() {
                    return Err(format!(
                        "Malformed MiniFAT (MiniFAT has {} entries, but mini sector {} points to {})",
                        minifat.len(),
                        from,
                        to
                    ));
                }
                if !pointees.insert(to) {
                    return Err(format!("Malformed MiniFAT (mini sector {} pointed to twice)", to));
                }
            }
        }
    }
    cfb.minifat = minifat;
    let _ = DIFAT_SECTOR;
    Ok(cfb)
}

/// Whether the entry's name equals `name` (exact).
pub fn is_stream(e: &DirEntry) -> bool {
    e.obj_type == OBJ_STREAM
}
