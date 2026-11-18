//! `Formats/Latest`: the classes of the file's schema, each with its tag (its definition ordinal
//! from 12, inline bases and inline references included).

const MAX_NAME: usize = 250;
const MAX_FIELDS: u32 = 2000;
const MAX_ARRAY: u32 = 65_536;
const MAX_DEPTH: usize = 64;
const FIRST_TAG: u32 = 12;

#[derive(Clone, Debug)]
pub struct Class {
    pub name: String,
    pub tag: u32,
}

pub struct Schema {
    pub classes: Vec<Class>,
}

impl Schema {
    pub fn tag(&self, name: &str) -> Option<u16> {
        self.classes.iter().find(|c| c.name == name).map(|c| c.tag as u16)
    }
    pub fn name_of(&self, tag: u16) -> Option<&str> {
        self.classes.iter().find(|c| c.tag == tag as u32).map(|c| c.name.as_str())
    }
}

struct P<'a> {
    d: &'a [u8],
    pos: usize,
    next_tag: u32,
    classes: Vec<Class>,
}

type R<T> = Result<T, String>;

impl<'a> P<'a> {
    fn u16(&mut self, what: &str) -> R<u16> {
        if self.pos + 2 > self.d.len() {
            return Err(format!("{} past the end at {:#x}", what, self.pos));
        }
        let v = u16::from_le_bytes([self.d[self.pos], self.d[self.pos + 1]]);
        self.pos += 2;
        Ok(v)
    }
    fn u32(&mut self, what: &str) -> R<u32> {
        if self.pos + 4 > self.d.len() {
            return Err(format!("{} past the end at {:#x}", what, self.pos));
        }
        let v = u32::from_le_bytes([self.d[self.pos], self.d[self.pos + 1], self.d[self.pos + 2], self.d[self.pos + 3]]);
        self.pos += 4;
        Ok(v)
    }
    fn name(&mut self, len: usize, at: usize) -> R<String> {
        if len == 0 || len > MAX_NAME || self.pos + len > self.d.len() {
            return Err(format!("bad name length {} at {:#x}", len, at));
        }
        let b = &self.d[self.pos..self.pos + len];
        if !b.iter().all(|c| (0x20..0x7f).contains(c)) {
            return Err(format!("name is not ASCII at {:#x}", at));
        }
        self.pos += len;
        Ok(String::from_utf8_lossy(b).to_string())
    }

    /// A class reference; one with the high bit set is defined inline right after it.
    fn reference(&mut self, depth: usize) -> R<()> {
        let tag = self.u16("class reference")?;
        if tag & 0x8000 != 0 {
            self.inline(tag & 0x7fff, depth)?;
        }
        Ok(())
    }

    fn inline(&mut self, tag: u16, depth: usize) -> R<()> {
        let at = self.pos;
        if self.pos + 2 > self.d.len() || self.d[self.pos] != 0 || self.d[self.pos + 1] != 0 {
            return Err(format!("inline pad is not 0 at {:#x}", at));
        }
        if tag as u32 != self.next_tag {
            return Err(format!("inline tag {} does not match reference {} at {:#x}", self.next_tag, tag, at));
        }
        self.pos += 2;
        self.class(depth + 1)
    }

    fn class(&mut self, depth: usize) -> R<()> {
        let at = self.pos;
        if depth > MAX_DEPTH {
            return Err(format!("classes nest too deep at {:#x}", at));
        }
        let len = self.u16("name length")? as usize;
        let name = self.name(len, at)?;
        let tag = self.next_tag;
        self.next_tag += 1;
        let base = self.u16("base reference")?;
        if base & 0x8000 != 0 {
            self.inline(base & 0x7fff, depth)?;
        }
        let _version = self.u32("version")?;
        let fat = self.pos;
        let nfields = self.u32("field count")?;
        if nfields > MAX_FIELDS {
            return Err(format!("field count {} at {:#x}", nfields, fat));
        }
        for _ in 0..nfields {
            let fat = self.pos;
            let flen = self.u32("name length")? as usize;
            self.name(flen, fat)?;
            self.field_type(0, depth)?;
        }
        let gat = self.pos;
        let nguids = self.u32("GUID count")?;
        if (nguids as u64) * 16 > (self.d.len() - self.pos) as u64 {
            return Err(format!("GUID count {} at {:#x}", nguids, gat));
        }
        self.pos += nguids as usize * 16;
        self.classes.push(Class { name, tag });
        Ok(())
    }

    /// A field's type; whether it ends in a class reference.
    fn field_type(&mut self, tdepth: usize, cdepth: usize) -> R<bool> {
        let at = self.pos;
        if tdepth > MAX_DEPTH {
            return Err(format!("types nest too deep at {:#x}", at));
        }
        if self.pos + 4 > self.d.len() {
            return Err(format!("type word past the end at {:#x}", at));
        }
        let code = self.d[self.pos];
        let modifier = self.d[self.pos + 1];
        self.pos += 4;
        let hi = modifier >> 4;
        if !matches!(hi, 0 | 1 | 5 | 6) {
            return Err(format!("unknown modifier {:#x} at {:#x}", modifier, at));
        }
        if hi == 1 {
            let cat = self.pos;
            let count = self.u32("array count")?;
            if count > MAX_ARRAY {
                return Err(format!("array count {} at {:#x}", count, cat));
            }
        }
        match code {
            0x0d => {
                let fat = self.pos;
                if self.pos + 5 > self.d.len() || self.d[self.pos..self.pos + 5] != [1, 0, 0, 0, 0x20] {
                    return Err(format!("array filler at {:#x}", fat));
                }
                self.pos += 5;
                let inner = self.field_type(tdepth + 1, cdepth)?;
                if inner {
                    self.reference(cdepth)?;
                }
                Ok(inner)
            }
            0x0e => {
                if modifier & 0x0f == 0 {
                    self.reference(cdepth)?;
                    Ok(true)
                } else {
                    Ok(false)
                }
            }
            _ => Ok(false),
        }
    }
}

/// Reads the classes; the error is the reason no class could be read.
pub fn parse(d: &[u8]) -> Result<Schema, String> {
    let mut p = P { d, pos: 0, next_tag: FIRST_TAG, classes: Vec::new() };
    let mut err: Option<String> = None;
    loop {
        if p.pos + 2 > d.len() || d[p.pos..].iter().all(|b| *b == 0) {
            break;
        }
        let at = p.pos;
        let sep = u16::from_le_bytes([d[p.pos], d[p.pos + 1]]);
        if sep != 0 {
            err = Some(format!("record separator is not 0 at {:#x}", at));
            break;
        }
        p.pos += 2;
        if let Err(e) = p.class(0) {
            err = Some(e);
            break;
        }
    }
    if p.classes.is_empty() {
        let why = err.unwrap_or_else(|| "it is empty".to_string());
        return Err(format!("Formats/Latest holds no class the reader can read ({})", why));
    }
    Ok(Schema { classes: p.classes })
}
