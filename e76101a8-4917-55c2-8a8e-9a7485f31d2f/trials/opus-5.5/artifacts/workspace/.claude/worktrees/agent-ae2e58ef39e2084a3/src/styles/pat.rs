//! PAT files: reading AutoCAD's and Revit's fill pattern files, and writing them.
//!
//! A pattern is a header `*Name[, description]` and one line per family of parallel lines,
//! `angle, x, y, shift, offset[, dash, …]`; `;` starts a comment, `;%UNITS=INCH` makes the lines
//! read after it inches, `;%TYPE=MODEL` makes the pattern it is in a model one.

use super::fills::{Hatch, Pattern};

/// The most patterns a file is read for.
pub const MAX_PATTERNS: usize = 2000;
/// The most families of lines a pattern has.
pub const MAX_FAMILIES: usize = 256;
/// The most dashes and spaces a family has.
pub const MAX_DASHES: usize = 16;
/// The biggest PAT file (or `text`) read, in bytes.
pub const MAX_FILE: u64 = 16 * 1024 * 1024;

/// A pattern as a file gives it: its name, and the pattern or why it can't be one.
pub struct Read {
    pub name: String,
    pub pattern: Result<Pattern, String>,
}

/// What a file holds: its patterns (the first 2000), and how many headers past them weren't read.
pub struct File {
    pub patterns: Vec<Read>,
    pub unread: usize,
}

/// The text of a file's bytes: UTF-8 if they are, else Latin-1, a character a byte.
pub fn decode(bytes: &[u8]) -> String {
    match std::str::from_utf8(bytes) {
        Ok(s) => s.to_string(),
        Err(_) => bytes.iter().map(|b| *b as char).collect(),
    }
}

/// A pattern's name from its header (what follows `*`, up to a comma).
fn header_name(rest: &str) -> String {
    let raw = rest.split(',').next().unwrap_or("");
    let clean: String = raw.trim().chars().filter(|c| !c.is_control()).collect();
    if clean.is_empty() {
        return "Unnamed".to_string();
    }
    clean.chars().take(256).collect()
}

/// A line shown in a reason: at most 40 characters, then an ellipsis.
fn clip40(s: &str) -> String {
    if s.chars().count() > 40 {
        let mut out: String = s.chars().take(40).collect();
        out.push('…');
        out
    } else {
        s.to_string()
    }
}

struct Building {
    name: String,
    model: bool,
    lines: Vec<Hatch>,
    error: Option<String>,
}

impl Building {
    fn finish(self) -> Read {
        let pattern = match self.error {
            Some(e) => Err(e),
            None if self.lines.is_empty() => Err("it has no lines".to_string()),
            None => Ok(Pattern { model: self.model, lines: self.lines, drawn: None }),
        };
        Read { name: self.name, pattern }
    }
}

/// One family of lines from a data line (its comment gone), in mm.
fn family(text: &str, scale: f64) -> Result<Hatch, String> {
    let fields: Vec<&str> = text.split(',').collect();
    if fields.len() > 5 + MAX_DASHES {
        return Err(format!("a family has more than {} dashes", MAX_DASHES));
    }
    let not_numbers = || {
        format!("`{}` isn't a line of numbers: angle, x, y, shift, offset and dashes", clip40(text))
    };
    if fields.len() < 5 {
        return Err(not_numbers());
    }
    let mut nums = Vec::with_capacity(fields.len());
    for f in &fields {
        match f.trim().parse::<f64>() {
            Ok(x) if x.is_finite() => nums.push(x),
            _ => return Err(not_numbers()),
        }
    }
    let (mut shift, mut offset) = (nums[3], nums[4]);
    if offset == 0.0 {
        return Err("a family's lines lie on each other: its offset is 0".to_string());
    }
    let dashes: Vec<f64> = nums[5..].to_vec();
    if !dashes.is_empty() && dashes.iter().all(|d| *d < 0.0) {
        return Err("a family's dashes are all spaces: it draws nothing".to_string());
    }
    if offset < 0.0 {
        offset = -offset;
        shift = -shift;
    }
    Ok(Hatch {
        angle: nums[0].rem_euclid(360.0),
        origin: [nums[1] * scale, nums[2] * scale],
        shift: shift * scale,
        spacing: offset * scale,
        dashes: dashes.iter().map(|d| d * scale).collect(),
    })
}

/// Reads a PAT file's text: each pattern, or why it can't be one (in file order).
pub fn parse(text: &str) -> File {
    let mut out = File { patterns: Vec::new(), unread: 0 };
    let mut inch = false;
    let mut cur: Option<Building> = None;
    let mut headers = 0usize;
    for raw in text.split('\n') {
        // a line's byte order marks go with its leading blanks (one a file starts with among them)
        let t = raw.trim().trim_start_matches('\u{feff}');
        if t.is_empty() {
            continue;
        }
        if headers > MAX_PATTERNS {
            if t.starts_with('*') {
                out.unread += 1;
            }
            continue;
        }
        if let Some(rest) = t.strip_prefix(';') {
            if let Some(dir) = rest.strip_prefix('%') {
                let (k, v) = dir.split_once('=').unwrap_or((dir, ""));
                let (k, v) = (k.trim(), v.trim());
                if k.eq_ignore_ascii_case("UNITS") {
                    inch = v.eq_ignore_ascii_case("INCH") || v.eq_ignore_ascii_case("INCHES");
                } else if k.eq_ignore_ascii_case("TYPE") {
                    if let Some(b) = cur.as_mut() {
                        b.model = v.eq_ignore_ascii_case("MODEL");
                    }
                }
            }
            continue;
        }
        if let Some(rest) = t.strip_prefix('*') {
            headers += 1;
            if let Some(b) = cur.take() {
                out.patterns.push(b.finish());
            }
            if headers > MAX_PATTERNS {
                out.unread += 1;
                continue;
            }
            cur = Some(Building { name: header_name(rest), model: false, lines: Vec::new(), error: None });
            continue;
        }
        let Some(b) = cur.as_mut() else { continue };
        if b.error.is_some() {
            continue;
        }
        let data = t.split(';').next().unwrap_or("").trim();
        match family(data, if inch { 25.4 } else { 1.0 }) {
            Ok(h) => {
                if b.lines.len() >= MAX_FAMILIES {
                    b.error = Some(format!("more than {} line families", MAX_FAMILIES));
                } else {
                    b.lines.push(h);
                }
            }
            Err(e) => b.error = Some(e),
        }
    }
    if let Some(b) = cur.take() {
        out.patterns.push(b.finish());
    }
    out
}

/// A number as a PAT file has it: to a millionth, without trailing zeros.
pub fn num(x: f64) -> String {
    let y = (x * 1e6).round() / 1e6;
    let y = if y == 0.0 { 0.0 } else { y };
    format!("{}", y)
}

/// The PAT text of patterns, in mm; solid ones (no lines) left out.
pub fn write<'a>(patterns: impl Iterator<Item = (&'a str, &'a Pattern)>) -> String {
    let mut s = String::from(";%UNITS=MM\n;%VERSION=3.0\n;Fill patterns from BIMCraft\n");
    for (name, p) in patterns {
        if p.lines.is_empty() {
            continue;
        }
        // a name's commas and control characters would end it or its line: spaces stand in
        s.push('*');
        s.extend(name.chars().map(|c| if c == ',' || c.is_control() { ' ' } else { c }));
        s.push('\n');
        s.push_str(if p.model { ";%TYPE=MODEL\n" } else { ";%TYPE=DRAFTING\n" });
        for h in &p.lines {
            let mut f = vec![num(h.angle), num(h.origin[0]), num(h.origin[1]), num(h.shift), num(h.spacing)];
            f.extend(h.dashes.iter().map(|d| num(*d)));
            s.push_str(&f.join(","));
            s.push('\n');
        }
    }
    s
}
