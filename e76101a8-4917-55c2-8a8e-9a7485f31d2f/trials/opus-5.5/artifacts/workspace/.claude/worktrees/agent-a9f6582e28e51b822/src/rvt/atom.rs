//! The Atom entry of `PartAtom` (a family's, plain XML) and of `ProjectInformation` (a one-entry ZIP):
//! its title, its save time and an OmniClass code, read by a small scanner with limits.

pub const MAX_XML: usize = 1 << 20;
const MAX_DEPTH: usize = 64;
const MAX_TAGS: usize = 100_000;

#[derive(Default, Clone)]
pub struct Atom {
    pub title: Option<String>,
    pub updated: Option<String>,
    pub omniclass: Option<String>,
}

/// The XML of a one-entry ZIP (a local file header, stored or deflated).
pub fn unzip(data: &[u8]) -> Option<Vec<u8>> {
    if data.len() < 30 || &data[..4] != b"PK\x03\x04" {
        return None;
    }
    let u16_at = |o: usize| u16::from_le_bytes([data[o], data[o + 1]]) as usize;
    let u32_at = |o: usize| u32::from_le_bytes([data[o], data[o + 1], data[o + 2], data[o + 3]]) as usize;
    let method = u16_at(8);
    let csize = u32_at(18);
    let nlen = u16_at(26);
    let xlen = u16_at(28);
    let start = 30 + nlen + xlen;
    if start > data.len() {
        return None;
    }
    match method {
        // stored: its size, which the stream must hold
        0 => {
            if csize > data.len() - start {
                return None;
            }
            let body = &data[start..start + csize];
            if body.len() > MAX_XML {
                return None;
            }
            Some(body.to_vec())
        }
        // deflated: decoded from the rest of the stream, whatever its size says
        8 => match super::deflate::inflate(&data[start..], MAX_XML) {
            Ok(r) => Some(r.data),
            Err(_) => None,
        },
        _ => None,
    }
}

/// Decodes the five named entities and numeric references; anything else stays as written.
pub fn decode_entities(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        let after = &rest[i..];
        let mut done = false;
        if let Some(semi) = after.find(';') {
            let ent = &after[1..semi];
            let rep: Option<String> = match ent {
                "amp" => Some("&".into()),
                "lt" => Some("<".into()),
                "gt" => Some(">".into()),
                "quot" => Some("\"".into()),
                "apos" => Some("'".into()),
                _ => {
                    if let Some(hex) = ent.strip_prefix("#x") {
                        if !hex.is_empty() && hex.chars().all(|c| c.is_ascii_hexdigit()) {
                            u32::from_str_radix(hex, 16).ok().and_then(char::from_u32).map(|c| c.to_string())
                        } else {
                            None
                        }
                    } else if let Some(dec) = ent.strip_prefix('#') {
                        if !dec.is_empty() && dec.chars().all(|c| c.is_ascii_digit()) {
                            dec.parse::<u32>().ok().and_then(char::from_u32).map(|c| c.to_string())
                        } else {
                            None
                        }
                    } else {
                        None
                    }
                }
            };
            if let Some(r) = rep {
                out.push_str(&r);
                rest = &after[semi + 1..];
                done = true;
            }
        }
        if !done {
            out.push('&');
            rest = &after[1..];
        }
    }
    out.push_str(rest);
    out
}

fn dotted_digits(s: &str) -> bool {
    !s.is_empty() && s.contains('.') && s.chars().all(|c| c.is_ascii_digit() || c == '.')
}

/// The `term="…"` (or `term='…'`) of a tag's text.
fn term_attr(raw: &str) -> Option<String> {
    let mut best: Option<(usize, char)> = None;
    for q in ['"', '\''] {
        let pat = format!("term={}", q);
        if let Some(i) = raw.find(&pat) {
            if best.map(|(b, _)| i < b).unwrap_or(true) {
                best = Some((i, q));
            }
        }
    }
    let (i, q) = best?;
    let start = i + 6;
    let end = raw[start..].find(q)?;
    Some(decode_entities(&raw[start..start + end]))
}

/// Scans the XML; any error in it gives nothing at all.
pub fn scan(xml: &[u8]) -> Option<Atom> {
    if xml.len() > MAX_XML {
        return None;
    }
    let s = std::str::from_utf8(xml).ok()?;
    let mut atom = Atom::default();
    let mut stack: Vec<String> = Vec::new();
    let mut text = String::new();
    let mut tags = 0usize;
    let mut pos = 0usize;
    loop {
        let lt = match s[pos..].find('<') {
            Some(i) => pos + i,
            None => break,
        };
        text.push_str(&s[pos..lt]);
        let rest = &s[lt..];
        if rest.starts_with("<!--") {
            let e = rest[4..].find("-->")?;
            pos = lt + 4 + e + 3;
            continue;
        }
        if rest.starts_with("<![CDATA[") {
            let e = rest[9..].find("]]>")?;
            pos = lt + 9 + e + 3;
            continue;
        }
        if rest.starts_with("<?") {
            let e = rest[2..].find("?>")?;
            pos = lt + 2 + e + 2;
            continue;
        }
        if rest.starts_with("<!") {
            let e = rest[2..].find('>')?;
            pos = lt + 2 + e + 1;
            continue;
        }
        let gt = rest.find('>')?;
        let raw = &rest[1..gt];
        pos = lt + gt + 1;
        if let Some(close) = raw.strip_prefix('/') {
            let name = close.trim();
            if name.is_empty() {
                return None;
            }
            tags += 1;
            if tags > MAX_TAGS {
                return None;
            }
            let open = stack.pop()?;
            if open != name {
                return None;
            }
            let t = text.trim();
            if stack.len() == 1 && stack[0] == "entry" {
                if name == "title" && atom.title.is_none() && !t.is_empty() {
                    atom.title = Some(decode_entities(t));
                }
                if name == "updated" && atom.updated.is_none() && !t.is_empty() {
                    atom.updated = Some(decode_entities(t));
                }
            }
            if name == "term" && stack.last().map(|p| p == "category").unwrap_or(false) && atom.omniclass.is_none() {
                let v = decode_entities(t);
                if dotted_digits(&v) {
                    atom.omniclass = Some(v);
                }
            }
            text.clear();
            continue;
        }
        let self_closing = raw.ends_with('/');
        let body = if self_closing { &raw[..raw.len() - 1] } else { raw };
        let name = body.split(|c: char| c.is_whitespace()).next().unwrap_or("");
        if name.is_empty() {
            return None;
        }
        tags += 1;
        if tags > MAX_TAGS {
            return None;
        }
        if name == "category" && atom.omniclass.is_none() {
            if let Some(v) = term_attr(body) {
                if dotted_digits(&v) {
                    atom.omniclass = Some(v);
                }
            }
        }
        if !self_closing {
            stack.push(name.to_string());
            if stack.len() > MAX_DEPTH {
                return None;
            }
        }
        text.clear();
    }
    if !stack.is_empty() {
        return None;
    }
    Some(atom)
}

/// The Atom of the file: `PartAtom` if it has one, else `ProjectInformation`'s.
pub fn read(part_atom: Option<&[u8]>, project_info: Option<&[u8]>) -> Atom {
    if let Some(p) = part_atom {
        return scan(p).unwrap_or_default();
    }
    if let Some(z) = project_info {
        if let Some(xml) = unzip(z) {
            return scan(&xml).unwrap_or_default();
        }
    }
    Atom::default()
}
