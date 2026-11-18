//! The STEP physical file the IFC export writes: numbered entities, and how numbers, strings
//! and GlobalIds are spelled in it.

use std::fmt::Write as _;

/// The entities of a file, numbered from 1 in the order they are added.
pub struct Step {
    pub ents: Vec<String>,
    seed: [u64; 2],
}

impl Step {
    pub fn new(uid: u64) -> Step {
        Step { ents: Vec::new(), seed: [uid ^ 0x6a09e667f3bcc908, uid.rotate_left(29) ^ 0xbb67ae8584caa73b] }
    }

    /// Adds an entity (`IFCWALL(...)`), returning its number.
    pub fn add<S: Into<String>>(&mut self, s: S) -> usize {
        self.ents.push(s.into());
        self.ents.len()
    }

    /// The number the next entity will get.
    pub fn next(&self) -> usize {
        self.ents.len() + 1
    }

    /// A GlobalId of its own for what has no GUID (relationships, property sets), the same
    /// for the same project each time it is written.
    pub fn fresh_gid(&mut self) -> String {
        let a = splitmix(&mut self.seed[0]);
        let b = splitmix(&mut self.seed[1]);
        gid_of_u128(((a as u128) << 64) | b as u128)
    }

    pub fn point2(&mut self, x: f64, y: f64) -> usize {
        self.add(format!("IFCCARTESIANPOINT(({},{}))", real(x), real(y)))
    }
    pub fn point3(&mut self, x: f64, y: f64, z: f64) -> usize {
        self.add(format!("IFCCARTESIANPOINT(({},{},{}))", real(x), real(y), real(z)))
    }
    pub fn dir3(&mut self, x: f64, y: f64, z: f64) -> usize {
        self.add(format!("IFCDIRECTION(({},{},{}))", dir(x), dir(y), dir(z)))
    }
    pub fn dir2(&mut self, x: f64, y: f64) -> usize {
        self.add(format!("IFCDIRECTION(({},{}))", dir(x), dir(y)))
    }

    pub fn text(&self) -> String {
        let mut out = String::with_capacity(self.ents.iter().map(|e| e.len() + 8).sum());
        for (i, e) in self.ents.iter().enumerate() {
            let _ = write!(out, "#{}={};\n", i + 1, e);
        }
        out
    }
}

fn splitmix(s: &mut u64) -> u64 {
    *s = s.wrapping_add(0x9e3779b97f4a7c15);
    let mut z = *s;
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
    z ^ (z >> 31)
}

const B64: &[u8; 64] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$";

fn gid_of_u128(mut n: u128) -> String {
    let mut c = [0u8; 22];
    for i in (0..22).rev() {
        c[i] = B64[(n & 63) as usize];
        n >>= 6;
    }
    String::from_utf8(c.to_vec()).unwrap()
}

/// An element's GlobalId: its GUID in IFC's 22 characters.
pub fn gid(guid: &str) -> String {
    let hex: String = guid.chars().filter(|c| c.is_ascii_hexdigit()).collect();
    let n = u128::from_str_radix(&hex, 16).unwrap_or(0);
    gid_of_u128(n)
}

fn trim_fixed(s: String) -> String {
    if let Some(dot) = s.find('.') {
        let t = s.trim_end_matches('0');
        if t.len() <= dot + 1 {
            return s[..dot + 1].to_string();
        }
        return t.to_string();
    }
    s
}

/// A real as the export writes lengths, areas and colours: six places, trailing zeros cut,
/// the point kept (`0.`, `3000.`, `-0.`).
pub fn real(x: f64) -> String {
    trim_fixed(format!("{:.6}", x + 0.0))
}

/// A direction ratio: twelve places.
pub fn dir(x: f64) -> String {
    trim_fixed(format!("{:.12}", x + 0.0))
}

/// A STEP string, quoted: `'` doubled, `\` doubled, and each character that isn't printable
/// ASCII on its own as `\X2\00E7\X0\` (the basic plane) or `\X4\0001F600\X0\` (beyond it).
pub fn st(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('\'');
    for c in s.chars() {
        if c == '\'' {
            out.push_str("''");
        } else if c == '\\' {
            out.push_str("\\\\");
        } else if (' '..='~').contains(&c) {
            out.push(c);
        } else if (c as u32) > 0xffff {
            let _ = write!(out, "\\X4\\{:08X}\\X0\\", c as u32);
        } else {
            let _ = write!(out, "\\X2\\{:04X}\\X0\\", c as u32);
        }
    }
    out.push('\'');
    out
}

/// `#1,#2,#3`
pub fn refs(ids: &[usize]) -> String {
    let mut s = String::new();
    for (i, id) in ids.iter().enumerate() {
        if i > 0 {
            s.push(',');
        }
        let _ = write!(s, "#{}", id);
    }
    s
}
