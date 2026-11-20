// JSX -> React.createElement transform (classic runtime), done as a single pre-pass scan over the
// source text: JavaScript is copied through unchanged (strings, templates, comments and regex
// literals are skipped as units) and every JSX element is replaced by a one-line
// `React.createElement(tag, props, ...children)` call.
//
// Whether a `<` starts an element is decided from the previous significant token: after a value
// (identifier, literal, `)`, `]`, `}`) it is the less-than operator, after an operator, a
// punctuator or one of a few keywords (`return`, `typeof`, ...) it opens JSX when followed by an
// identifier character or `>` (fragment).

const JSX_KEYWORDS: &[&str] = &[
    "return", "typeof", "void", "await", "yield", "delete", "new", "in", "of", "instanceof", "case", "else", "do", "throw",
    "extends", "default",
];

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    /// whole program
    Top,
    /// JSX `{ ... }` container: ends at the first `}` in code position
    Container,
    /// template `${ ... }` substitution: ends at the matching `}`
    Subst,
}

struct Jsx<'a> {
    s: &'a [char],
    i: usize,
}

pub type JsxResult<T> = Result<T, String>;

fn is_word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_' || c == '$'
}

fn is_id_start(c: char) -> bool {
    c.is_alphabetic() || c == '_' || c == '$'
}

fn is_tag_char(c: char) -> bool {
    c.is_alphanumeric() || matches!(c, '_' | '$' | '-' | '.' | ':')
}

fn is_attr_char(c: char) -> bool {
    c.is_alphanumeric() || matches!(c, '_' | '-' | ':')
}

fn is_ws(c: char) -> bool {
    c.is_whitespace()
}

/// Double-quoted string literal for JSX text / attribute strings.
fn quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// JSX text child: whitespace-only text disappears; multi-line text has its lines trimmed
/// (except the outer edges) and joined with single spaces.
fn clean_text(raw: &str) -> Option<String> {
    if raw.trim().is_empty() {
        return None;
    }
    if !raw.contains('\n') {
        return Some(raw.to_string());
    }
    let lines: Vec<&str> = raw.split('\n').collect();
    let last = lines.len() - 1;
    let mut parts: Vec<&str> = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        let mut l: &str = line;
        if i > 0 {
            l = l.trim_start();
        }
        if i < last {
            l = l.trim_end();
        }
        if !l.is_empty() {
            parts.push(l);
        }
    }
    Some(parts.join(" "))
}

fn attr_key(name: &str) -> String {
    let mut cs = name.chars();
    let bare = match cs.next() {
        Some(c) if c.is_ascii_alphabetic() || c == '_' => name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_'),
        _ => false,
    };
    if bare {
        name.to_string()
    } else {
        quote(name)
    }
}

fn tag_expr(name: &str) -> String {
    let first = name.chars().next().unwrap_or(' ');
    if first.is_ascii_lowercase() && !name.contains('.') && !name.contains(':') {
        quote(name)
    } else {
        name.to_string()
    }
}

impl<'a> Jsx<'a> {
    fn peek(&self) -> Option<char> {
        self.s.get(self.i).copied()
    }

    fn peek_at(&self, n: usize) -> Option<char> {
        self.s.get(self.i + n).copied()
    }

    fn eof(&self) -> bool {
        self.i >= self.s.len()
    }

    /// Copy JavaScript, transforming JSX elements. In Container/Subst mode stops after the
    /// closing `}` (which is consumed, not copied); returns false if the input ended first.
    fn scan_js(&mut self, mode: Mode, out: &mut String) -> JsxResult<bool> {
        let mut prev_value = false;
        let mut depth = 0usize;
        while let Some(c) = self.peek() {
            match c {
                c if is_ws(c) => {
                    out.push(c);
                    self.i += 1;
                }
                '/' if self.peek_at(1) == Some('/') => {
                    while let Some(c) = self.peek() {
                        if c == '\n' {
                            break;
                        }
                        out.push(c);
                        self.i += 1;
                    }
                }
                '/' if self.peek_at(1) == Some('*') => {
                    out.push_str("/*");
                    self.i += 2;
                    while let Some(c) = self.peek() {
                        if c == '*' && self.peek_at(1) == Some('/') {
                            out.push_str("*/");
                            self.i += 2;
                            break;
                        }
                        out.push(c);
                        self.i += 1;
                    }
                }
                '\'' | '"' => {
                    self.copy_string(c, out);
                    prev_value = true;
                }
                '`' => {
                    self.copy_template(out)?;
                    prev_value = true;
                }
                '/' => {
                    if prev_value {
                        out.push('/');
                        self.i += 1;
                        prev_value = false;
                    } else {
                        self.copy_regex(out);
                        prev_value = true;
                    }
                }
                '<' if !prev_value && self.peek_at(1).map_or(false, |n| is_id_start(n) || n == '>') => {
                    let el = self.parse_element()?;
                    out.push_str(&el);
                    prev_value = true;
                }
                '<' if !prev_value && self.peek_at(1) == Some('/') => {
                    return Err("expected a JSX element name after `<`".into());
                }
                c if is_word_char(c) => {
                    // identifiers, keywords and numbers (a number keeps its `.`: `5.`, `1.5`)
                    let number = c.is_ascii_digit();
                    let start = self.i;
                    while let Some(c) = self.peek() {
                        if !(is_word_char(c) || (number && c == '.')) {
                            break;
                        }
                        self.i += 1;
                    }
                    let w: String = self.s[start..self.i].iter().collect();
                    prev_value = !JSX_KEYWORDS.contains(&w.as_str());
                    out.push_str(&w);
                }
                '{' => {
                    depth += 1;
                    out.push('{');
                    self.i += 1;
                    prev_value = false;
                }
                '}' => {
                    if mode == Mode::Container || (mode == Mode::Subst && depth == 0) {
                        self.i += 1;
                        return Ok(true);
                    }
                    depth = depth.saturating_sub(1);
                    out.push('}');
                    self.i += 1;
                    prev_value = true;
                }
                ')' | ']' => {
                    out.push(c);
                    self.i += 1;
                    prev_value = true;
                }
                _ => {
                    out.push(c);
                    self.i += 1;
                    prev_value = false;
                }
            }
        }
        Ok(mode == Mode::Top)
    }

    fn copy_string(&mut self, q: char, out: &mut String) {
        out.push(q);
        self.i += 1;
        while let Some(c) = self.peek() {
            out.push(c);
            self.i += 1;
            if c == '\\' {
                if let Some(n) = self.peek() {
                    out.push(n);
                    self.i += 1;
                }
                continue;
            }
            if c == q || c == '\n' {
                break;
            }
        }
    }

    fn copy_template(&mut self, out: &mut String) -> JsxResult<()> {
        out.push('`');
        self.i += 1;
        while let Some(c) = self.peek() {
            if c == '\\' {
                out.push(c);
                self.i += 1;
                if let Some(n) = self.peek() {
                    out.push(n);
                    self.i += 1;
                }
                continue;
            }
            if c == '`' {
                out.push('`');
                self.i += 1;
                return Ok(());
            }
            if c == '$' && self.peek_at(1) == Some('{') {
                out.push_str("${");
                self.i += 2;
                if self.scan_js(Mode::Subst, out)? {
                    out.push('}');
                }
                continue;
            }
            out.push(c);
            self.i += 1;
        }
        Ok(())
    }

    /// Copy a regular expression literal: up to the next unescaped '/' outside a character
    /// class (line breaks do not end it), then its flags.
    fn copy_regex(&mut self, out: &mut String) {
        out.push('/');
        self.i += 1;
        let mut in_class = false;
        while let Some(c) = self.peek() {
            out.push(c);
            self.i += 1;
            match c {
                '\\' => {
                    if let Some(n) = self.peek() {
                        out.push(n);
                        self.i += 1;
                    }
                }
                '[' => in_class = true,
                ']' => in_class = false,
                '/' if !in_class => break,
                _ => {}
            }
        }
        while let Some(c) = self.peek() {
            if !is_word_char(c) {
                break;
            }
            out.push(c);
            self.i += 1;
        }
    }

    /// Code of a `{ ... }` container (after the `{`), with nested JSX transformed.
    fn container(&mut self) -> JsxResult<String> {
        let mut inner = String::new();
        if !self.scan_js(Mode::Container, &mut inner)? {
            return Err("unterminated `{ … }` in JSX".into());
        }
        Ok(inner)
    }

    fn skip_ws_comments(&mut self) {
        while let Some(c) = self.peek() {
            if is_ws(c) {
                self.i += 1;
            } else if c == '/' && self.peek_at(1) == Some('*') {
                self.i += 2;
                while !self.eof() && !(self.peek() == Some('*') && self.peek_at(1) == Some('/')) {
                    self.i += 1;
                }
                self.i = (self.i + 2).min(self.s.len());
            } else if c == '/' && self.peek_at(1) == Some('/') {
                while let Some(c) = self.peek() {
                    if c == '\n' {
                        break;
                    }
                    self.i += 1;
                }
            } else {
                break;
            }
        }
    }

    fn skip_ws(&mut self) {
        while let Some(c) = self.peek() {
            if !is_ws(c) {
                break;
            }
            self.i += 1;
        }
    }

    fn read_while(&mut self, f: fn(char) -> bool) -> String {
        let start = self.i;
        while let Some(c) = self.peek() {
            if !f(c) {
                break;
            }
            self.i += 1;
        }
        self.s[start..self.i].iter().collect()
    }

    /// Parse an element or fragment starting at `<`; returns the createElement call.
    fn parse_element(&mut self) -> JsxResult<String> {
        self.i += 1; // <
        if self.peek() == Some('>') {
            self.i += 1;
            let children = self.parse_children()?;
            return Ok(emit("React.Fragment", &[], &children));
        }
        let name = self.read_while(is_tag_char);
        let mut attrs: Vec<String> = Vec::new();
        let self_closing;
        loop {
            self.skip_ws_comments();
            let c = match self.peek() {
                Some(c) => c,
                None => return Err("unterminated JSX opening tag".into()),
            };
            if c == '/' && self.peek_at(1) == Some('>') {
                self.i += 2;
                self_closing = true;
                break;
            }
            if c == '>' {
                self.i += 1;
                self_closing = false;
                break;
            }
            if c == '{' {
                self.i += 1;
                let inner = self.container()?;
                let t = inner.trim();
                let t = t.strip_prefix("...").unwrap_or(t).trim();
                attrs.push(format!("...{}", t));
                continue;
            }
            let an = self.read_while(is_attr_char);
            if an.is_empty() {
                return Err("expected a JSX attribute name".into());
            }
            self.skip_ws();
            if self.peek() != Some('=') {
                attrs.push(format!("{}: true", attr_key(&an)));
                continue;
            }
            self.i += 1;
            self.skip_ws();
            let value = match self.peek() {
                Some(q) if q == '"' || q == '\'' => {
                    self.i += 1;
                    let start = self.i;
                    while let Some(c) = self.peek() {
                        if c == q {
                            break;
                        }
                        self.i += 1;
                    }
                    if self.eof() {
                        return Err("unterminated JSX opening tag".into());
                    }
                    let v: String = self.s[start..self.i].iter().collect();
                    self.i += 1;
                    quote(&v)
                }
                Some('{') => {
                    self.i += 1;
                    self.container()?.trim().to_string()
                }
                Some('<') => self.parse_element()?,
                _ => return Err("expected a JSX attribute value".into()),
            };
            attrs.push(format!("{}: {}", attr_key(&an), value));
        }
        let children = if self_closing { Vec::new() } else { self.parse_children()? };
        Ok(emit(&tag_expr(&name), &attrs, &children))
    }

    fn parse_children(&mut self) -> JsxResult<Vec<String>> {
        let mut children = Vec::new();
        loop {
            let c = match self.peek() {
                Some(c) => c,
                None => return Err("unterminated JSX element".into()),
            };
            if c == '<' {
                match self.peek_at(1) {
                    Some('/') => {
                        // closing tag: its name is not checked against the opening one
                        self.i += 2;
                        self.read_while(is_tag_char);
                        self.skip_ws();
                        if self.peek() == Some('>') {
                            self.i += 1;
                        }
                        return Ok(children);
                    }
                    Some(n) if is_tag_char(n) || n == '>' => {
                        let el = self.parse_element()?;
                        children.push(el);
                    }
                    _ => return Err("expected a JSX element name after `<`".into()),
                }
            } else if c == '{' {
                self.i += 1;
                let inner = self.container()?;
                let t = inner.trim();
                if !t.is_empty() {
                    children.push(t.to_string());
                }
            } else {
                let start = self.i;
                while let Some(c) = self.peek() {
                    if c == '<' || c == '{' {
                        break;
                    }
                    self.i += 1;
                }
                let raw: String = self.s[start..self.i].iter().collect();
                if let Some(t) = clean_text(&raw) {
                    children.push(quote(&t));
                }
            }
        }
    }
}

fn emit(tag: &str, attrs: &[String], children: &[String]) -> String {
    let mut s = format!("React.createElement({}, ", tag);
    if attrs.is_empty() {
        s.push_str("null");
    } else {
        s.push_str("{ ");
        s.push_str(&attrs.join(", "));
        s.push_str(" }");
    }
    for c in children {
        s.push_str(", ");
        s.push_str(c);
    }
    s.push(')');
    s
}

/// Transform JSX in `src`; Err carries the reason ("expected a JSX attribute name", ...).
pub fn jsx_transform(src: &str) -> JsxResult<String> {
    let chars: Vec<char> = src.chars().collect();
    let mut j = Jsx { s: &chars, i: 0 };
    let mut out = String::with_capacity(src.len() + 64);
    j.scan_js(Mode::Top, &mut out)?;
    Ok(out)
}
