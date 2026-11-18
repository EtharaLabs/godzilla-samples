//! Scripts: one `id {json}` per line; blank lines and `#` comments are passed over.

use crate::json::Value;

pub struct Line {
    pub line: usize,
    pub id: String,
    pub params: Value,
}

/// Parses a whole script before anything runs, so a bad line stops it at once.
pub fn parse(text: &str) -> Result<Vec<Line>, String> {
    let mut out = Vec::new();
    for (n, raw) in text.lines().enumerate() {
        let t = raw.trim();
        if t.is_empty() || t.starts_with('#') {
            continue;
        }
        let (id, rest) = match t.find(char::is_whitespace) {
            Some(i) => (&t[..i], t[i..].trim()),
            None => (t, ""),
        };
        let params = if rest.is_empty() {
            Value::obj()
        } else {
            match crate::json::parse(rest) {
                Ok(v) => v,
                Err(e) => return Err(format!("line {}: bad JSON after `{}`: {}", n + 1, id, e)),
            }
        };
        out.push(Line { line: n + 1, id: id.to_string(), params });
    }
    Ok(out)
}
