//! A STEP (ISO 10303-21) reader: the header's schema and the DATA section's entity instances,
//! with the errors worded as the original words them (`line N: expected `;``…).

use std::collections::BTreeMap;

/// A parameter of an entity instance.
#[derive(Clone, Debug, PartialEq)]
pub enum P {
    /// `$`
    Null,
    /// `*`
    Derived,
    /// A number, and whether it was written as an integer (no `.` and no exponent).
    Num(f64, bool),
    Str(String),
    Bin(String),
    /// `.NAME.`, the text between the dots.
    Enum(String),
    Ref(u64),
    List(Vec<P>),
    /// `IFCLABEL('x')`: the type's name (upper case) and its parameters.
    Typed(String, Vec<P>),
}

impl P {
    /// The value a typed parameter of one value holds, at any depth.
    pub fn untyped(&self) -> &P {
        let mut p = self;
        while let P::Typed(_, v) = p {
            if v.len() == 1 {
                p = &v[0];
            } else {
                break;
            }
        }
        p
    }
    pub fn num(&self) -> Option<f64> {
        match self.untyped() {
            P::Num(x, _) => Some(*x),
            _ => None,
        }
    }
    pub fn int(&self) -> Option<i64> {
        match self.untyped() {
            P::Num(x, _) if x.fract() == 0.0 => Some(*x as i64),
            _ => None,
        }
    }
    pub fn str(&self) -> Option<&str> {
        match self.untyped() {
            P::Str(s) => Some(s),
            _ => None,
        }
    }
    pub fn enm(&self) -> Option<&str> {
        match self.untyped() {
            P::Enum(s) => Some(s),
            _ => None,
        }
    }
    pub fn r(&self) -> Option<u64> {
        match self {
            P::Ref(r) => Some(*r),
            _ => None,
        }
    }
    pub fn list(&self) -> Option<&Vec<P>> {
        match self {
            P::List(v) => Some(v),
            _ => None,
        }
    }
    pub fn is_null(&self) -> bool {
        matches!(self, P::Null)
    }
    /// The references of a list (or the one reference).
    pub fn refs(&self) -> Vec<u64> {
        match self {
            P::Ref(r) => vec![*r],
            P::List(v) => v.iter().filter_map(|x| x.r()).collect(),
            _ => Vec::new(),
        }
    }
    /// The numbers of a list.
    pub fn nums(&self) -> Option<Vec<f64>> {
        let v = self.list()?;
        let mut out = Vec::with_capacity(v.len());
        for x in v {
            out.push(x.num()?);
        }
        Some(out)
    }
    /// `.T.`/`.F.` (and `.U.`, none).
    pub fn boolean(&self) -> Option<bool> {
        match self.enm() {
            Some("T") => Some(true),
            Some("F") => Some(false),
            _ => None,
        }
    }
}

/// An entity instance: `#id=NAME(params);`. A complex instance `#id=(A(..) B(..));` has no name
/// and its parts.
#[derive(Clone, Debug)]
pub struct Entity {
    pub name: String,
    pub params: Vec<P>,
    pub parts: Vec<(String, Vec<P>)>,
}

impl Entity {
    pub fn p(&self, i: usize) -> &P {
        static NULL: P = P::Null;
        self.params.get(i).unwrap_or(&NULL)
    }
}

pub struct StepFile {
    /// The header's entities by name (upper case): the last of a name.
    pub header: BTreeMap<String, Vec<P>>,
    pub entities: BTreeMap<u64, Entity>,
}

impl StepFile {
    /// The schema FILE_SCHEMA names: its first string, trimmed and in upper case; empty if none.
    pub fn schema(&self) -> String {
        fn first(v: &[P]) -> Option<String> {
            for p in v {
                match p {
                    P::Str(s) => return Some(s.clone()),
                    P::List(l) => {
                        if let Some(s) = first(l) {
                            return Some(s);
                        }
                    }
                    _ => {}
                }
            }
            None
        }
        match self.header.get("FILE_SCHEMA") {
            Some(v) => first(v).map(|s| s.trim().to_uppercase()).unwrap_or_default(),
            None => String::new(),
        }
    }
}

struct Rd<'a> {
    b: &'a [u8],
    s: &'a str,
    pos: usize,
    /// Lines counted up to `lpos`.
    line: usize,
    lpos: usize,
}

type R<T> = Result<T, String>;

fn is_name(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

impl<'a> Rd<'a> {
    fn line_at(&mut self, pos: usize) -> usize {
        if pos >= self.lpos {
            self.line += self.b[self.lpos..pos].iter().filter(|c| **c == b'\n').count();
        } else {
            self.line -= self.b[pos..self.lpos].iter().filter(|c| **c == b'\n').count();
        }
        self.lpos = pos;
        self.line
    }
    fn err<T>(&mut self, pos: usize, msg: &str) -> R<T> {
        let l = self.line_at(pos);
        Err(format!("line {}: {}", l, msg))
    }
    fn peek(&self) -> Option<u8> {
        self.b.get(self.pos).copied()
    }
    /// Skips spaces, tabs, line ends and comments (an unended comment runs to the end).
    fn ws(&mut self) {
        loop {
            match self.peek() {
                Some(b' ') | Some(b'\t') | Some(b'\r') | Some(b'\n') => self.pos += 1,
                Some(b'/') if self.b.get(self.pos + 1) == Some(&b'*') => {
                    match find(self.b, self.pos + 2, b"*/") {
                        Some(e) => self.pos = e + 2,
                        None => self.pos = self.b.len(),
                    }
                }
                _ => return,
            }
        }
    }
    fn name(&mut self) -> &'a str {
        let st = self.pos;
        while self.pos < self.b.len() && is_name(self.b[self.pos]) {
            self.pos += 1;
        }
        &self.s[st..self.pos]
    }
    fn expect(&mut self, c: u8, msg: &str) -> R<()> {
        self.ws();
        if self.peek() == Some(c) {
            self.pos += 1;
            Ok(())
        } else {
            let p = self.pos;
            self.err(p, msg)
        }
    }
    /// A parameter list, its `(` read.
    fn list(&mut self) -> R<Vec<P>> {
        let mut out = Vec::new();
        self.ws();
        if self.peek() == Some(b')') {
            self.pos += 1;
            return Ok(out);
        }
        loop {
            out.push(self.value()?);
            self.ws();
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b')') => {
                    self.pos += 1;
                    return Ok(out);
                }
                _ => {
                    let p = self.pos;
                    return self.err(p, "expected `,` or `)`");
                }
            }
        }
    }
    fn entity_number(&mut self) -> R<u64> {
        let st = self.pos;
        while self.pos < self.b.len() && self.b[self.pos].is_ascii_digit() {
            self.pos += 1;
        }
        let t = &self.s[st..self.pos];
        match t.parse::<u64>() {
            Ok(n) => Ok(n),
            Err(_) => self.err(st, &format!("`{}` is not an entity number", t)),
        }
    }
    fn value(&mut self) -> R<P> {
        self.ws();
        let st = self.pos;
        let c = match self.peek() {
            Some(c) => c,
            None => return self.err(st, "unexpected character"),
        };
        match c {
            b'$' => {
                self.pos += 1;
                Ok(P::Null)
            }
            b'*' => {
                self.pos += 1;
                Ok(P::Derived)
            }
            b'\'' => {
                let mut raw = String::new();
                let mut i = st + 1;
                loop {
                    match find_byte(self.b, i, b'\'') {
                        Some(q) => {
                            raw.push_str(&self.s[i..q]);
                            if self.b.get(q + 1) == Some(&b'\'') {
                                raw.push('\'');
                                i = q + 2;
                            } else {
                                self.pos = q + 1;
                                break;
                            }
                        }
                        None => return self.err(st, "a string doesn't end"),
                    }
                }
                Ok(P::Str(decode(&raw)))
            }
            b'"' => match find_byte(self.b, st + 1, b'"') {
                Some(q) => {
                    self.pos = q + 1;
                    Ok(P::Bin(self.s[st + 1..q].to_string()))
                }
                None => self.err(st, "no closing `\"`"),
            },
            b'.' => match find_byte(self.b, st + 1, b'.') {
                Some(q) => {
                    self.pos = q + 1;
                    Ok(P::Enum(self.s[st + 1..q].to_string()))
                }
                None => self.err(st, "no closing `.`"),
            },
            b'#' => {
                self.pos += 1;
                Ok(P::Ref(self.entity_number()?))
            }
            b'(' => {
                self.pos += 1;
                Ok(P::List(self.list()?))
            }
            b'0'..=b'9' | b'+' | b'-' => {
                while self.pos < self.b.len() {
                    match self.b[self.pos] {
                        b'0'..=b'9' | b'+' | b'-' | b'.' | b'e' | b'E' => self.pos += 1,
                        _ => break,
                    }
                }
                let t = &self.s[st..self.pos];
                match t.parse::<f64>() {
                    Ok(x) => Ok(P::Num(x, !t.contains(['.', 'e', 'E']))),
                    Err(_) => self.err(st, &format!("`{}` is not a number", t)),
                }
            }
            c if c.is_ascii_alphabetic() || c == b'_' => {
                let n = self.name().to_ascii_uppercase();
                self.expect(b'(', "expected `(`")?;
                Ok(P::Typed(n, self.list()?))
            }
            _ => self.err(st, "unexpected character"),
        }
    }
}

fn find(b: &[u8], from: usize, pat: &[u8]) -> Option<usize> {
    if from >= b.len() {
        return None;
    }
    b[from..].windows(pat.len()).position(|w| w == pat).map(|p| p + from)
}

fn find_byte(b: &[u8], from: usize, c: u8) -> Option<usize> {
    if from >= b.len() {
        return None;
    }
    b[from..].iter().position(|x| *x == c).map(|p| p + from)
}

/// Decodes a string's escapes (its doubled quotes already single): `\\`, `\S\c`, `\X\hh`,
/// `\X2\…\X0\` (UTF-16), `\X4\…\X0\` (UTF-32), `\Pc\` (dropped); any other backslash stays.
pub fn decode(raw: &str) -> String {
    if !raw.contains('\\') {
        return raw.to_string();
    }
    let ch: Vec<char> = raw.chars().collect();
    let n = ch.len();
    let mut out = String::with_capacity(raw.len());
    let at = |i: usize| -> Option<char> { ch.get(i).copied() };
    let mut i = 0;
    while i < n {
        let c = ch[i];
        if c != '\\' {
            out.push(c);
            i += 1;
            continue;
        }
        match at(i + 1) {
            Some('\\') => {
                out.push('\\');
                i += 2;
            }
            Some('S') if at(i + 2) == Some('\\') && i + 3 < n => {
                let x = ch[i + 3] as u32 + 0x80;
                out.push(char::from_u32(x).unwrap_or('\u{FFFD}'));
                i += 4;
            }
            Some('X') if at(i + 2) == Some('\\') && i + 4 < n => {
                let h: String = ch[i + 3..i + 5].iter().collect();
                match u8::from_str_radix(&h, 16) {
                    Ok(b) => {
                        out.push(b as char);
                        i += 5;
                    }
                    Err(_) => {
                        out.push('\\');
                        i += 1;
                    }
                }
            }
            Some('X') if (at(i + 2) == Some('2') || at(i + 2) == Some('4')) && at(i + 3) == Some('\\') => {
                let wide = at(i + 2) == Some('4');
                let st = i + 4;
                // the hex runs to the `\X0\` that ends it, or to the end
                let mut e = n;
                let mut j = st;
                while j + 3 < n {
                    if ch[j] == '\\' && ch[j + 1] == 'X' && ch[j + 2] == '0' && ch[j + 3] == '\\' {
                        e = j;
                        break;
                    }
                    j += 1;
                }
                let seg = &ch[st..e];
                if wide {
                    for chunk in seg.chunks(8) {
                        if chunk.len() < 8 {
                            break;
                        }
                        let h: String = chunk.iter().collect();
                        if let Ok(u) = u32::from_str_radix(&h, 16) {
                            out.push(char::from_u32(u).unwrap_or('\u{FFFD}'));
                        }
                    }
                } else {
                    let mut units: Vec<u16> = Vec::new();
                    for chunk in seg.chunks(4) {
                        if chunk.len() < 4 {
                            break;
                        }
                        let h: String = chunk.iter().collect();
                        if let Ok(u) = u16::from_str_radix(&h, 16) {
                            units.push(u);
                        }
                    }
                    out.push_str(&String::from_utf16_lossy(&units));
                }
                i = if e < n { e + 4 } else { n };
            }
            Some('P') if i + 3 < n && ch[i + 3] == '\\' => {
                i += 4;
            }
            _ => {
                out.push('\\');
                i += 1;
            }
        }
    }
    out
}

/// Reads a STEP file's text: its header and the entities of its first DATA section.
pub fn parse(bytes: &[u8]) -> R<StepFile> {
    let text = String::from_utf8_lossy(bytes);
    let s: &str = &text;
    let b = s.as_bytes();
    let h = match find(b, 0, b"HEADER;") {
        Some(h) => h,
        None => return Err("not a STEP file: it has no HEADER section".into()),
    };
    let mut r = Rd { b, s, pos: h + 7, line: 1, lpos: 0 };
    let mut header: BTreeMap<String, Vec<P>> = BTreeMap::new();
    loop {
        r.ws();
        let st = r.pos;
        let n = r.name();
        if n.is_empty() {
            return r.err(st, "expected a name");
        }
        if n == "ENDSEC" {
            r.expect(b';', "expected `;`")?;
            break;
        }
        let n = n.to_ascii_uppercase();
        r.expect(b'(', "expected `(`")?;
        let v = r.list()?;
        r.expect(b';', "expected `;`")?;
        header.insert(n, v);
    }
    r.ws();
    let st = r.pos;
    if r.name() != "DATA" {
        return r.err(st, "expected the DATA section");
    }
    r.ws();
    if r.peek() == Some(b'(') {
        r.pos += 1;
        r.list()?;
    }
    r.expect(b';', "expected `;`")?;
    let mut entities: BTreeMap<u64, Entity> = BTreeMap::new();
    loop {
        r.ws();
        let st = r.pos;
        match r.peek() {
            Some(b'#') => {}
            Some(c) if is_name(c) => {
                if r.name() == "ENDSEC" {
                    break;
                }
                return r.err(st, "expected `#`");
            }
            _ => return r.err(st, "expected `#`"),
        }
        r.pos += 1;
        let id = r.entity_number()?;
        r.expect(b'=', "expected `=`")?;
        r.ws();
        let e = if r.peek() == Some(b'(') {
            r.pos += 1;
            let mut parts = Vec::new();
            loop {
                r.ws();
                if r.peek() == Some(b')') {
                    r.pos += 1;
                    break;
                }
                let st = r.pos;
                let n = r.name();
                if n.is_empty() {
                    return r.err(st, "expected a name");
                }
                let n = n.to_ascii_uppercase();
                r.expect(b'(', "expected `(`")?;
                let v = r.list()?;
                parts.push((n, v));
            }
            Entity { name: String::new(), params: Vec::new(), parts }
        } else {
            let st = r.pos;
            let n = r.name();
            if n.is_empty() {
                return r.err(st, "expected a name");
            }
            let n = n.to_ascii_uppercase();
            r.expect(b'(', "expected `(`")?;
            let v = r.list()?;
            Entity { name: n, params: v, parts: Vec::new() }
        };
        r.expect(b';', "expected `;`")?;
        entities.insert(id, e);
    }
    Ok(StepFile { header, entities })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escapes() {
        assert_eq!(decode(r"A\X2\D83DDE00\X0\B"), "A😀B");
        assert_eq!(decode(r"A\X2\0041\X4\0001F600\X0\B"), "AA\u{1}\u{F600}B");
        assert_eq!(decode(r"A\S\\B"), "AÜB");
        assert_eq!(decode(r"A\\S\D"), "A\\S\\D");
        assert_eq!(decode(r"A\X2\00E9\B"), "Aé");
        assert_eq!(decode(r"A\P\C"), "A\\P\\C");
        assert_eq!(decode(r"A\PB\C"), "AC");
        assert_eq!(decode(r"A\X\G1"), "A\\X\\G1");
        assert_eq!(decode("A\\"), "A\\");
    }
}
