// JSON-family to YAML projection (`yamark to-yaml`).

use crate::cli::Matches;
use crate::format_cmd::Diagnostic;
use crate::options::Options;
use std::io::{Read, Write};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Dialect {
    Json,
    Jsonc,
    Json5,
}

#[derive(Debug, Clone)]
enum Value {
    Null,
    Bool(bool),
    /// Number spelled for YAML.
    Num(String),
    Str(String),
    Arr(Vec<Elem>, Vec<String>),
    Obj(Vec<(String, Elem)>, Vec<String>),
}

#[derive(Debug, Clone)]
struct Elem {
    /// Comments preceding the element.
    comments: Vec<String>,
    value: Value,
}

struct P<'a> {
    s: &'a [char],
    i: usize,
    d: Dialect,
    depth: usize,
    pending: Vec<String>,
    any_comment: bool,
}

type R<T> = Result<T, (usize, String)>;

impl<'a> P<'a> {
    fn peek(&self) -> Option<char> {
        self.s.get(self.i).copied()
    }

    fn skip_ws(&mut self) -> R<()> {
        loop {
            let c = match self.peek() {
                Some(c) => c,
                None => return Ok(()),
            };
            let is_ws = match self.d {
                Dialect::Json5 => c.is_whitespace() && c != '\u{85}' || c == '\u{feff}',
                _ => matches!(c, ' ' | '\t' | '\n' | '\r'),
            };
            if is_ws {
                self.i += 1;
                continue;
            }
            if c == '/' && self.d != Dialect::Json {
                match self.s.get(self.i + 1) {
                    Some('/') => {
                        let st = self.i + 2;
                        let mut j = st;
                        while j < self.s.len() && self.s[j] != '\n' {
                            j += 1;
                        }
                        let text: String = self.s[st..j].iter().collect();
                        self.pending.push(text.trim().to_string());
                        self.any_comment = true;
                        self.i = j;
                        continue;
                    }
                    Some('*') => {
                        let st = self.i + 2;
                        let mut j = st;
                        while j + 1 < self.s.len() && !(self.s[j] == '*' && self.s[j + 1] == '/') {
                            j += 1;
                        }
                        if j + 1 >= self.s.len() {
                            return Err((self.i, "Unterminated comment".into()));
                        }
                        let text: String = self.s[st..j].iter().collect();
                        for l in text.split('\n') {
                            let t = l.trim().trim_start_matches('*').trim();
                            if !t.is_empty() {
                                self.pending.push(t.to_string());
                            }
                        }
                        self.any_comment = true;
                        self.i = j + 2;
                        continue;
                    }
                    _ => {}
                }
            }
            return Ok(());
        }
    }

    fn take_comments(&mut self) -> Vec<String> {
        std::mem::take(&mut self.pending)
    }

    fn unexpected(&self) -> (usize, String) {
        match self.d {
            Dialect::Json5 => {
                let c = self.peek().unwrap_or(' ');
                let kind = match c {
                    ',' => "Comma",
                    ':' => "Colon",
                    '}' => "CloseBrace",
                    ']' => "CloseBracket",
                    '{' => "OpenBrace",
                    '[' => "OpenBracket",
                    _ => "Name",
                };
                if kind == "Name" {
                    let mut j = self.i;
                    while j < self.s.len() && (self.s[j].is_alphanumeric() || self.s[j] == '_' || self.s[j] == '$') {
                        j += 1;
                    }
                    let w: String = self.s[self.i..j.max(self.i + 1).min(self.s.len())].iter().collect();
                    return (self.i, format!("Unexpected token of type Name: \"{}\"", w));
                }
                (self.i, format!("Unexpected token of type {}: \"{}\"", kind, c))
            }
            _ => {
                if self.peek() == Some(',') {
                    return (self.i, "Unexpected comma".into());
                }
                (self.i, "Unexpected token".into())
            }
        }
    }

    fn value(&mut self) -> R<Value> {
        self.skip_ws()?;
        let c = match self.peek() {
            Some(c) => c,
            None => return Err((self.i, "expected a JSON value".into())),
        };
        match c {
            '{' => self.object(),
            '[' => self.array(),
            '"' => Ok(Value::Str(self.string('"')?)),
            '\'' if self.d == Dialect::Json5 => Ok(Value::Str(self.string('\'')?)),
            _ => self.literal(),
        }
    }

    fn enter(&mut self) -> R<()> {
        self.depth += 1;
        if self.depth > 256 {
            return Err((self.i, "nesting too deep".into()));
        }
        Ok(())
    }

    fn object(&mut self) -> R<Value> {
        let start = self.i;
        self.enter()?;
        self.i += 1;
        let mut members = Vec::new();
        loop {
            self.skip_ws()?;
            match self.peek() {
                None => {
                    return Err(match self.d {
                        Dialect::Json5 => (self.i, "Expecting '}' at end of object".into()),
                        _ => (start, "Unterminated object".into()),
                    })
                }
                Some('}') => {
                    self.i += 1;
                    break;
                }
                _ => {}
            }
            let comments = self.take_comments();
            let key = match self.peek() {
                Some('"') => self.string('"')?,
                Some('\'') if self.d == Dialect::Json5 => self.string('\'')?,
                Some(c) if self.d == Dialect::Json5 && (c.is_alphabetic() || c == '_' || c == '$' || c == '\\') => {
                    let st = self.i;
                    while self.i < self.s.len() && (self.s[self.i].is_alphanumeric() || self.s[self.i] == '_' || self.s[self.i] == '$') {
                        self.i += 1;
                    }
                    self.s[st..self.i].iter().collect()
                }
                _ => return Err(self.unexpected()),
            };
            self.skip_ws()?;
            if self.peek() != Some(':') {
                return Err(match self.d {
                    Dialect::Json5 => (self.i, "Expecting ':' delimiter".into()),
                    _ => (self.i, "Expected colon after the string or word in object property".into()),
                });
            }
            self.i += 1;
            let mut v = self.value()?;
            let _ = &mut v;
            members.push((key, Elem { comments, value: v }));
            self.skip_ws()?;
            match self.peek() {
                Some(',') => {
                    let comma = self.i;
                    self.i += 1;
                    self.skip_ws()?;
                    if self.peek() == Some('}') && self.d == Dialect::Json {
                        return Err((comma, "Trailing commas are not allowed".into()));
                    }
                }
                Some('}') => {
                    self.i += 1;
                    break;
                }
                None => {
                    return Err(match self.d {
                        Dialect::Json5 => (self.i, "Expecting '}' at end of object".into()),
                        _ => (start, "Unterminated object".into()),
                    })
                }
                _ => return Err(self.unexpected()),
            }
        }
        let trailing = self.take_comments();
        self.depth -= 1;
        Ok(Value::Obj(members, trailing))
    }

    fn array(&mut self) -> R<Value> {
        let start = self.i;
        self.enter()?;
        self.i += 1;
        let mut items = Vec::new();
        loop {
            self.skip_ws()?;
            match self.peek() {
                None => {
                    return Err(match self.d {
                        Dialect::Json5 => (self.i, "Expecting ']' at end of array".into()),
                        _ => (start, "Unterminated array".into()),
                    })
                }
                Some(']') => {
                    self.i += 1;
                    break;
                }
                Some(',') => return Err(self.unexpected()),
                _ => {}
            }
            let comments = self.take_comments();
            let v = self.value()?;
            items.push(Elem { comments, value: v });
            self.skip_ws()?;
            match self.peek() {
                Some(',') => {
                    let comma = self.i;
                    self.i += 1;
                    self.skip_ws()?;
                    if self.peek() == Some(']') && self.d == Dialect::Json {
                        return Err((comma, "Trailing commas are not allowed".into()));
                    }
                }
                Some(']') => {
                    self.i += 1;
                    break;
                }
                None => {
                    return Err(match self.d {
                        Dialect::Json5 => (self.i, "Expecting ']' at end of array".into()),
                        _ => (start, "Unterminated array".into()),
                    })
                }
                _ => return Err(self.unexpected()),
            }
        }
        let trailing = self.take_comments();
        self.depth -= 1;
        Ok(Value::Arr(items, trailing))
    }

    fn string(&mut self, q: char) -> R<String> {
        let start = self.i;
        self.i += 1;
        let mut out = String::new();
        loop {
            let c = match self.peek() {
                Some(c) => c,
                None => return Err((start, "Unterminated string literal".into())),
            };
            if c == q {
                self.i += 1;
                return Ok(out);
            }
            if c == '\n' && self.d != Dialect::Json5 {
                return Err((start, "Unterminated string literal".into()));
            }
            if c == '\\' {
                let esc_pos = self.i;
                self.i += 1;
                let e = match self.peek() {
                    Some(e) => e,
                    None => return Err((start, "Unterminated string literal".into())),
                };
                self.i += 1;
                match e {
                    '"' => out.push('"'),
                    '\'' if self.d == Dialect::Json5 => out.push('\''),
                    '\\' => out.push('\\'),
                    '/' => out.push('/'),
                    'b' => out.push('\u{8}'),
                    'f' => out.push('\u{c}'),
                    'n' => out.push('\n'),
                    'r' => out.push('\r'),
                    't' => out.push('\t'),
                    'v' if self.d == Dialect::Json5 => out.push('\u{b}'),
                    '0' if self.d == Dialect::Json5 && !self.peek().map(|c| c.is_ascii_digit()).unwrap_or(false) => out.push('\0'),
                    '\n' if self.d == Dialect::Json5 => {}
                    'x' if self.d == Dialect::Json5 => {
                        let h: String = self.s[self.i..(self.i + 2).min(self.s.len())].iter().collect();
                        let v = u32::from_str_radix(&h, 16).map_err(|_| (esc_pos, "Invalid escape sequence".to_string()))?;
                        self.i += 2;
                        out.push(char::from_u32(v).unwrap_or('\u{fffd}'));
                    }
                    'u' => {
                        let h: String = self.s[self.i..(self.i + 4).min(self.s.len())].iter().collect();
                        let v = u32::from_str_radix(&h, 16).map_err(|_| (esc_pos, "Invalid unicode escape sequence".to_string()))?;
                        self.i += 4;
                        if (0xD800..0xDC00).contains(&v) {
                            // Expect a low surrogate.
                            if self.peek() == Some('\\') && self.s.get(self.i + 1) == Some(&'u') {
                                let h2: String = self.s[self.i + 2..(self.i + 6).min(self.s.len())].iter().collect();
                                if let Ok(v2) = u32::from_str_radix(&h2, 16) {
                                    if (0xDC00..0xE000).contains(&v2) {
                                        self.i += 6;
                                        let cp = 0x10000 + ((v - 0xD800) << 10) + (v2 - 0xDC00);
                                        out.push(char::from_u32(cp).unwrap_or('\u{fffd}'));
                                        continue;
                                    }
                                }
                            }
                            return Err(match self.d {
                                Dialect::Json5 => (start, "lone high surrogate in Unicode escape sequence".into()),
                                _ => (start, format!("Invalid unicode escape sequence. '{} (unpaired high surrogate)' is not a valid UTF8 character", h.to_lowercase())),
                            });
                        }
                        if (0xDC00..0xE000).contains(&v) {
                            return Err(match self.d {
                                Dialect::Json5 => (start, "lone low surrogate in Unicode escape sequence".into()),
                                _ => (start, format!("Invalid unicode escape sequence. '{} (unpaired low surrogate)' is not a valid UTF8 character", h.to_lowercase())),
                            });
                        }
                        out.push(char::from_u32(v).unwrap_or('\u{fffd}'));
                    }
                    other => {
                        if self.d == Dialect::Json5 && !other.is_ascii_digit() {
                            out.push(other);
                        } else {
                            return Err((esc_pos, "Invalid escape sequence".into()));
                        }
                    }
                }
                continue;
            }
            out.push(c);
            self.i += 1;
        }
    }

    fn literal(&mut self) -> R<Value> {
        let st = self.i;
        let mut j = self.i;
        while j < self.s.len() && !matches!(self.s[j], ',' | ']' | '}' | ':' | ' ' | '\t' | '\n' | '\r' | '/') {
            j += 1;
        }
        let w: String = self.s[st..j].iter().collect();
        let v = match w.as_str() {
            "null" => Value::Null,
            "true" => Value::Bool(true),
            "false" => Value::Bool(false),
            _ => match number(&w, self.d) {
                Some(n) => Value::Num(n),
                None => return Err(self.unexpected()),
            },
        };
        self.i = j;
        Ok(v)
    }
}

fn number(w: &str, d: Dialect) -> Option<String> {
    if d != Dialect::Json5 {
        let b = w.as_bytes();
        let mut i = 0;
        if i < b.len() && b[i] == b'-' {
            i += 1;
        }
        let ds = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == ds || (b[ds] == b'0' && i - ds > 1) {
            return None;
        }
        if i < b.len() && b[i] == b'.' {
            i += 1;
            let fs = i;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
            if i == fs {
                return None;
            }
        }
        if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
            i += 1;
            if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
                i += 1;
            }
            let es = i;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
            if i == es {
                return None;
            }
        }
        if i != b.len() {
            return None;
        }
        return Some(w.to_string());
    }
    // JSON5
    let (neg, body) = if let Some(r) = w.strip_prefix('-') {
        (true, r)
    } else if let Some(r) = w.strip_prefix('+') {
        (false, r)
    } else {
        (false, w)
    };
    let sign = if neg { "-" } else { "" };
    if body == "Infinity" {
        return Some(format!("{}.inf", sign));
    }
    if body == "NaN" {
        return Some(".nan".to_string());
    }
    if body.starts_with("0x") || body.starts_with("0X") {
        let h = &body[2..];
        if h.is_empty() || !h.chars().all(|c| c.is_ascii_hexdigit()) {
            return None;
        }
        if neg {
            let v = u128::from_str_radix(h, 16).ok()?;
            return Some(format!("-{}", v));
        }
        return Some(format!("0x{}", h));
    }
    // decimal: allow leading/trailing dot
    let b = body.as_bytes();
    let mut i = 0;
    let ds = i;
    while i < b.len() && b[i].is_ascii_digit() {
        i += 1;
    }
    let int_part = &body[ds..i];
    let mut frac_part = "";
    let mut has_dot = false;
    if i < b.len() && b[i] == b'.' {
        has_dot = true;
        i += 1;
        let fs = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        frac_part = &body[fs..i];
    }
    if int_part.is_empty() && frac_part.is_empty() {
        return None;
    }
    let mut exp = "";
    if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
        let es = i;
        i += 1;
        if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
            i += 1;
        }
        let ed = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == ed {
            return None;
        }
        exp = &body[es..i];
    }
    if i != b.len() {
        return None;
    }
    let int_s = if int_part.is_empty() { "0" } else { int_part };
    let mut s = String::from(sign);
    s.push_str(int_s);
    if has_dot {
        s.push('.');
        s.push_str(if frac_part.is_empty() { "0" } else { frac_part });
    }
    s.push_str(exp);
    Some(s)
}

fn quote_json_str(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn key_text(k: &str) -> String {
    let mut chars = k.chars();
    let ident = match chars.next() {
        Some(c) if c.is_ascii_alphabetic() || c == '_' => chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-'),
        _ => false,
    };
    if ident && !crate::yaml::scalar::resolves_non_string(k) {
        return k.to_string();
    }
    quote_json_str(k)
}

fn flow_key_text(k: &str) -> String {
    quote_json_str(k)
}

/// Compact flow rendering of a value (YAML-compatible JSON text).
fn flow_text(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => if *b { "true".into() } else { "false".into() },
        Value::Num(n) => n.clone(),
        Value::Str(s) => quote_json_str(s),
        Value::Arr(items, _) => {
            let parts: Vec<String> = items.iter().map(|e| flow_text(&e.value)).collect();
            format!("[{}]", parts.join(", "))
        }
        Value::Obj(members, _) => {
            let parts: Vec<String> = members.iter().map(|(k, e)| format!("{}: {}", flow_key_text(k), flow_text(&e.value))).collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

fn sanitize_comment(c: &str) -> String {
    let mut out = String::new();
    for ch in c.chars() {
        if (ch as u32) < 0x20 && ch != '\t' || ch == '\u{7f}' || ch == '\u{85}' || ch == '\u{2028}' || ch == '\u{2029}' || ch == '\u{feff}' {
            out.push_str(&format!("\\x{:02X}", ch as u32));
        } else {
            out.push(ch);
        }
    }
    out
}

/// Block rendering used when the input carries comments.
fn block_text(v: &Value, indent: usize, out: &mut Vec<String>) {
    let pad = " ".repeat(indent);
    match v {
        Value::Arr(items, trailing) if !items.is_empty() => {
            for e in items {
                for c in &e.comments {
                    out.push(format!("{}# {}", pad, sanitize_comment(c)).trim_end().to_string());
                }
                match &e.value {
                    Value::Arr(i2, _) if !i2.is_empty() => {
                        out.push(format!("{}-", pad));
                        block_text(&e.value, indent + 2, out);
                    }
                    Value::Obj(m2, _) if !m2.is_empty() => {
                        out.push(format!("{}-", pad));
                        block_text(&e.value, indent + 2, out);
                    }
                    other => out.push(format!("{}- {}", pad, flow_text(other))),
                }
            }
            for c in trailing {
                out.push(format!("{}# {}", pad, sanitize_comment(c)).trim_end().to_string());
            }
        }
        Value::Obj(members, trailing) if !members.is_empty() => {
            for (k, e) in members {
                for c in &e.comments {
                    out.push(format!("{}# {}", pad, sanitize_comment(c)).trim_end().to_string());
                }
                match &e.value {
                    Value::Arr(i2, _) if !i2.is_empty() => {
                        out.push(format!("{}{}:", pad, key_text(k)));
                        block_text(&e.value, indent + 2, out);
                    }
                    Value::Obj(m2, _) if !m2.is_empty() => {
                        out.push(format!("{}{}:", pad, key_text(k)));
                        block_text(&e.value, indent + 2, out);
                    }
                    other => out.push(format!("{}{}: {}", pad, key_text(k), flow_text(other))),
                }
            }
            for c in trailing {
                out.push(format!("{}# {}", pad, sanitize_comment(c)).trim_end().to_string());
            }
        }
        other => out.push(format!("{}{}", pad, flow_text(other))),
    }
}

fn pos_to_line_col(chars: &[char], pos: usize) -> (usize, usize) {
    let mut line = 1;
    let mut col = 1;
    for &c in chars.iter().take(pos) {
        if c == '\n' {
            line += 1;
            col = 1;
        } else {
            col += 1;
        }
    }
    (line, col)
}

fn parse_document(text: &str, d: Dialect) -> Result<(Value, Vec<String>, bool), Diagnostic> {
    let chars: Vec<char> = text.chars().collect();
    let mut p = P { s: &chars, i: 0, d, depth: 0, pending: Vec::new(), any_comment: false };
    let label = match d {
        Dialect::Json => "JSON",
        Dialect::Jsonc => "JSONC",
        Dialect::Json5 => "JSON5",
    };
    let res = (|| -> R<(Value, Vec<String>)> {
        p.skip_ws()?;
        if p.i >= chars.len() && d == Dialect::Json5 {
            return Err((p.i, "Unexpected EOF. Was expecting value.".into()));
        }
        let v = p.value()?;
        p.skip_ws()?;
        if p.i < chars.len() {
            return Err(match d {
                Dialect::Json5 => {
                    let c = chars[p.i];
                    let kind = if c.is_ascii_digit() || c == '-' || c == '+' || c == '.' {
                        "Integer"
                    } else if c == '"' || c == '\'' {
                        "String"
                    } else if c == '{' || c == '[' {
                        "Punctuator"
                    } else {
                        "Name"
                    };
                    (p.i, format!("Unexpected {} token after value", kind))
                }
                _ => (p.i, "Text cannot contain more than one JSON value".into()),
            });
        }
        let lead = Vec::new();
        Ok((v, lead))
    })();
    match res {
        Ok((v, _)) => {
            let trailing = p.take_comments();
            Ok((v, trailing, p.any_comment))
        }
        Err((pos, msg)) => {
            let (l, c) = pos_to_line_col(&chars, pos);
            Err(Diagnostic { line: l, col: c, msg: format!("invalid {}: {}", label, msg) })
        }
    }
}

fn project(v: &Value, trailing: &[String], has_comments: bool, leading: &[String], opts: &Options) -> String {
    let yaml_src = if has_comments {
        let mut lines = Vec::new();
        for c in leading {
            lines.push(format!("# {}", sanitize_comment(c)).trim_end().to_string());
        }
        block_text(v, 0, &mut lines);
        for c in trailing {
            lines.push(format!("# {}", sanitize_comment(c)).trim_end().to_string());
        }
        format!("{}\n", lines.join("\n"))
    } else {
        format!("{}\n", flow_text(v))
    };
    crate::yaml::format_yaml(&yaml_src, opts).unwrap_or(yaml_src)
}

pub fn convert(text: &str, path: &str, opts: &Options) -> Result<String, Diagnostic> {
    let lower = path.to_ascii_lowercase();
    let ext = lower.rsplit('.').next().unwrap_or("");
    match ext {
        "json" | "jsonc" | "json5" => {
            let d = match ext {
                "json" => Dialect::Json,
                "jsonc" => Dialect::Jsonc,
                _ => Dialect::Json5,
            };
            let (v, trailing, any) = parse_document(text, d)?;
            // Leading comments of the root are pending in the first element; handled via block_text.
            Ok(project(&v, &trailing, any, &[], opts))
        }
        "jsonl" | "ndjson" => {
            let mut out = String::new();
            let body = text.strip_suffix('\n').unwrap_or(text);
            if body.is_empty() {
                return Err(Diagnostic { line: 1, col: 1, msg: "invalid JSON Lines: records cannot be blank".into() });
            }
            for (i, line) in body.split('\n').enumerate() {
                let line = line.strip_suffix('\r').unwrap_or(line);
                if line.trim().is_empty() {
                    return Err(Diagnostic { line: i + 1, col: 1, msg: "invalid JSON Lines: records cannot be blank".into() });
                }
                let (v, _, _) = parse_document(line, Dialect::Json).map_err(|mut d| {
                    d.line = i + 1;
                    d
                })?;
                out.push_str("---\n");
                out.push_str(&project(&v, &[], false, &[], opts));
            }
            Ok(out)
        }
        _ => Err(Diagnostic {
            line: 1,
            col: 1,
            msg: "JSON-to-YAML projection requires a .json, .jsonc, .json5, .jsonl, or .ndjson source path".into(),
        }),
    }
}

pub fn run_to_yaml(m: &Matches) -> i32 {
    let path = m.value("stdin-file-path").unwrap_or("").to_string();
    let mut opts = Options::default();
    if let Some(n) = m.value("line-width") {
        opts.line_width = n.parse().unwrap_or(80);
    }
    if let Some(n) = m.value("prose-width") {
        opts.prose_width = n.parse().unwrap_or(72);
    }
    if let Some(n) = m.value("indent-width") {
        opts.indent_width = n.parse().unwrap_or(2);
    }
    opts.compact = m.flag("compact");
    let mut bytes = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut bytes);
    let text = match crate::format_cmd::decode(&bytes) {
        Ok(t) => t,
        Err(e) => {
            eprint!("{}:1:1: error: {}\n", path, e);
            return 1;
        }
    };
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text).to_string();
    match convert(&text, &path, &opts) {
        Ok(out) => {
            let mut so = std::io::stdout();
            let _ = so.write_all(out.as_bytes());
            let _ = so.flush();
            0
        }
        Err(d) => {
            eprint!("{}:{}:{}: error: {}\n", path, d.line, d.col, d.msg);
            1
        }
    }
}
