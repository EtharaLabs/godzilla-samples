// JavaScript lexer: produces tokens on demand for the parser.

use crate::unicode;

#[derive(Clone, Debug, PartialEq)]
pub enum Tok {
    Ident(String),
    Keyword(&'static str),
    Punct(&'static str),
    Num(f64),
    BigInt(String),
    Str(Vec<u16>),
    Template { cooked: Option<Vec<u16>>, raw: Vec<u16>, tail: bool },
    Regex { pattern: Vec<u16>, flags: Vec<u16> },
    PrivateName(String),
    Eof,
}

#[derive(Clone, Debug)]
pub struct Token {
    pub tok: Tok,
    pub start: usize,
    pub end: usize,
    pub line: u32,
    pub nl_before: bool,
    /// identifier/keyword contained unicode escapes
    pub escaped: bool,
    /// string literal contained a legacy octal escape (or \8 \9)
    pub octal_escape: bool,
    /// numeric literal was a legacy octal (e.g. 017 or 08)
    pub legacy_octal: bool,
}

pub struct LexError {
    pub msg: String,
    pub line: u32,
}

const KEYWORDS: &[&str] = &[
    "break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete", "do", "else", "enum",
    "export", "extends", "false", "finally", "for", "function", "if", "import", "in", "instanceof", "new", "null",
    "return", "super", "switch", "this", "throw", "true", "try", "typeof", "var", "void", "while", "with",
];

pub fn keyword_of(s: &str) -> Option<&'static str> {
    KEYWORDS.iter().copied().find(|k| *k == s)
}

const PUNCTS: &[&str] = &[
    ">>>=", "...", "===", "!==", "**=", "<<=", ">>=", ">>>", "&&=", "||=", "??=", "=>", "==", "!=", "<=", ">=", "&&",
    "||", "??", "?.", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "**", "{", "}", "(",
    ")", "[", "]", ";", ",", "<", ">", "+", "-", "*", "/", "%", "&", "|", "^", "!", "~", "?", ":", "=", ".", "@",
    "#",
];

pub struct Lexer {
    pub src: Vec<char>,
    pub pos: usize,
    pub line: u32,
    pub is_module: bool,
}

fn is_line_term(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{2028}' | '\u{2029}')
}

fn is_ws(c: char) -> bool {
    match c {
        '\t' | '\u{b}' | '\u{c}' | ' ' | '\u{a0}' | '\u{feff}' => true,
        _ if (c as u32) < 128 => false,
        _ => unicode::is_js_whitespace(c as u32),
    }
}

pub fn is_id_start(c: char) -> bool {
    c == '$' || c == '_' || c.is_ascii_alphabetic() || ((c as u32) >= 128 && unicode::is_id_start(c as u32))
}

pub fn is_id_continue(c: char) -> bool {
    c == '$'
        || c == '_'
        || c.is_ascii_alphanumeric()
        || c == '\u{200c}'
        || c == '\u{200d}'
        || ((c as u32) >= 128 && unicode::is_id_continue(c as u32))
}

fn push_utf16(out: &mut Vec<u16>, c: u32) {
    if c >= 0x10000 {
        let c = c - 0x10000;
        out.push(0xD800 + (c >> 10) as u16);
        out.push(0xDC00 + (c & 0x3ff) as u16);
    } else {
        out.push(c as u16);
    }
}

impl Lexer {
    pub fn new(src: &str, is_module: bool) -> Lexer {
        Lexer { src: src.chars().collect(), pos: 0, line: 1, is_module }
    }

    fn peek(&self) -> Option<char> {
        self.src.get(self.pos).copied()
    }
    fn peek_at(&self, n: usize) -> Option<char> {
        self.src.get(self.pos + n).copied()
    }

    fn err(&self, msg: &str) -> LexError {
        LexError { msg: msg.to_string(), line: self.line }
    }

    /// Skips whitespace and comments. Returns whether a line terminator was crossed.
    fn skip_trivia(&mut self) -> Result<bool, LexError> {
        let mut nl = false;
        // hashbang
        if self.pos == 0 && self.peek() == Some('#') && self.peek_at(1) == Some('!') {
            while let Some(c) = self.peek() {
                if is_line_term(c) {
                    break;
                }
                self.pos += 1;
            }
        }
        loop {
            let c = match self.peek() {
                Some(c) => c,
                None => return Ok(nl),
            };
            if is_line_term(c) {
                nl = true;
                self.pos += 1;
                if c == '\r' && self.peek() == Some('\n') {
                    self.pos += 1;
                }
                self.line += 1;
            } else if is_ws(c) {
                self.pos += 1;
            } else if c == '/' && self.peek_at(1) == Some('/') {
                self.skip_line_comment();
            } else if c == '/' && self.peek_at(1) == Some('*') {
                self.pos += 2;
                let mut closed = false;
                while let Some(c) = self.peek() {
                    if c == '*' && self.peek_at(1) == Some('/') {
                        self.pos += 2;
                        closed = true;
                        break;
                    }
                    if is_line_term(c) {
                        nl = true;
                        if c == '\r' && self.peek_at(1) == Some('\n') {
                            self.pos += 1;
                        }
                        self.line += 1;
                    }
                    self.pos += 1;
                }
                if !closed {
                    return Err(self.err("unterminated comment"));
                }
            } else if !self.is_module
                && c == '<'
                && self.peek_at(1) == Some('!')
                && self.peek_at(2) == Some('-')
                && self.peek_at(3) == Some('-')
            {
                self.skip_line_comment();
            } else if !self.is_module
                && c == '-'
                && self.peek_at(1) == Some('-')
                && self.peek_at(2) == Some('>')
                && (nl || self.only_ws_before_on_line())
            {
                self.skip_line_comment();
            } else {
                return Ok(nl);
            }
        }
    }

    fn only_ws_before_on_line(&self) -> bool {
        // true at start of input
        let mut i = self.pos;
        while i > 0 {
            let c = self.src[i - 1];
            if is_line_term(c) {
                return true;
            }
            if !is_ws(c) {
                return false;
            }
            i -= 1;
        }
        true
    }

    fn skip_line_comment(&mut self) {
        while let Some(c) = self.peek() {
            if is_line_term(c) {
                break;
            }
            self.pos += 1;
        }
    }

    fn mk(&self, tok: Tok, start: usize, line: u32, nl: bool) -> Token {
        Token { tok, start, end: self.pos, line, nl_before: nl, escaped: false, octal_escape: false, legacy_octal: false }
    }

    pub fn next_token(&mut self) -> Result<Token, LexError> {
        let nl = self.skip_trivia()?;
        let start = self.pos;
        let line = self.line;
        let c = match self.peek() {
            None => return Ok(self.mk(Tok::Eof, start, line, nl)),
            Some(c) => c,
        };
        if is_id_start(c) || c == '\\' {
            let (name, escaped) = self.read_ident_name()?;
            let tok = if !escaped {
                match keyword_of(&name) {
                    Some(k) => Tok::Keyword(k),
                    None => Tok::Ident(name),
                }
            } else {
                Tok::Ident(name)
            };
            let mut t = self.mk(tok, start, line, nl);
            t.escaped = escaped;
            return Ok(t);
        }
        if c.is_ascii_digit() || (c == '.' && self.peek_at(1).map_or(false, |d| d.is_ascii_digit())) {
            return self.read_number(start, line, nl);
        }
        if c == '"' || c == '\'' {
            return self.read_string(c, start, line, nl);
        }
        if c == '`' {
            self.pos += 1;
            return self.read_template(start, line, nl);
        }
        if c == '#' {
            if let Some(n) = self.peek_at(1) {
                if is_id_start(n) || n == '\\' {
                    self.pos += 1;
                    let (name, _) = self.read_ident_name()?;
                    return Ok(self.mk(Tok::PrivateName(name), start, line, nl));
                }
            }
        }
        // punctuators
        for p in PUNCTS {
            let pc: Vec<char> = p.chars().collect();
            if self.src.len() - self.pos >= pc.len() && self.src[self.pos..self.pos + pc.len()] == pc[..] {
                // `?.` followed by a digit is `?` then `.5`
                if *p == "?." && self.peek_at(2).map_or(false, |d| d.is_ascii_digit()) {
                    continue;
                }
                self.pos += pc.len();
                return Ok(self.mk(Tok::Punct(p), start, line, nl));
            }
        }
        Err(self.err(&format!("unexpected character '{}'", c)))
    }

    fn read_unicode_escape_in_ident(&mut self) -> Result<char, LexError> {
        // at '\'
        self.pos += 1;
        if self.peek() != Some('u') {
            return Err(self.err("invalid escape in identifier"));
        }
        self.pos += 1;
        let v = self.read_unicode_escape_body().ok_or_else(|| self.err("invalid Unicode escape sequence"))?;
        char::from_u32(v).ok_or_else(|| self.err("invalid Unicode escape sequence"))
    }

    fn read_ident_name(&mut self) -> Result<(String, bool), LexError> {
        let mut s = String::new();
        let mut escaped = false;
        let mut first = true;
        loop {
            match self.peek() {
                Some('\\') => {
                    let c = self.read_unicode_escape_in_ident()?;
                    let ok = if first { is_id_start(c) } else { is_id_continue(c) };
                    if !ok {
                        return Err(self.err("invalid identifier escape"));
                    }
                    s.push(c);
                    escaped = true;
                }
                Some(c) if (first && is_id_start(c)) || (!first && is_id_continue(c)) => {
                    s.push(c);
                    self.pos += 1;
                }
                _ => break,
            }
            first = false;
        }
        Ok((s, escaped))
    }

    /// after "\u": reads XXXX or {X...}; returns code point
    fn read_unicode_escape_body(&mut self) -> Option<u32> {
        if self.peek() == Some('{') {
            self.pos += 1;
            let mut v: u32 = 0;
            let mut n = 0;
            loop {
                let c = self.peek()?;
                if c == '}' {
                    self.pos += 1;
                    break;
                }
                let d = c.to_digit(16)?;
                v = v.checked_mul(16)?.checked_add(d)?;
                if v > 0x10FFFF {
                    return None;
                }
                n += 1;
                self.pos += 1;
            }
            if n == 0 {
                return None;
            }
            Some(v)
        } else {
            let mut v = 0u32;
            for _ in 0..4 {
                let d = self.peek()?.to_digit(16)?;
                v = v * 16 + d;
                self.pos += 1;
            }
            Some(v)
        }
    }

    fn read_number(&mut self, start: usize, line: u32, nl: bool) -> Result<Token, LexError> {
        let c = self.peek().unwrap();
        let mut legacy_octal = false;
        let mut text = String::new();
        let mut is_bigint = false;
        let mut radix = 10;
        if c == '0' && matches!(self.peek_at(1), Some('x' | 'X' | 'o' | 'O' | 'b' | 'B')) {
            let p = self.peek_at(1).unwrap().to_ascii_lowercase();
            radix = match p {
                'x' => 16,
                'o' => 8,
                _ => 2,
            };
            self.pos += 2;
            let digits = self.read_digits(radix, true)?;
            if digits.is_empty() {
                return Err(self.err("invalid numeric literal"));
            }
            text.push('0');
            text.push(p);
            text.push_str(&digits);
            if self.peek() == Some('n') {
                self.pos += 1;
                is_bigint = true;
            }
        } else if c == '0' && self.peek_at(1).map_or(false, |d| d.is_ascii_digit()) {
            // legacy octal or decimal with leading zero
            legacy_octal = true;
            let mut j = self.pos + 1;
            let mut all_octal = true;
            while let Some(d) = self.src.get(j) {
                if d.is_ascii_digit() {
                    if *d >= '8' {
                        all_octal = false;
                    }
                    j += 1;
                } else {
                    break;
                }
            }
            if all_octal {
                let digits: String = self.src[self.pos..j].iter().collect();
                self.pos = j;
                text = digits;
                let v = i64::from_str_radix(&text[1..], 8).unwrap_or(0);
                if self.peek().map_or(false, |c| is_id_start(c) || c.is_ascii_digit()) {
                    return Err(self.err("identifier starts immediately after numeric literal"));
                }
                let mut t = self.mk(Tok::Num(v as f64), start, line, nl);
                t.legacy_octal = true;
                return Ok(t);
            }
            // decimal like 08, 09.5
            let digits: String = self.src[self.pos..j].iter().collect();
            self.pos = j;
            text.push_str(&digits);
            if self.peek() == Some('.') {
                self.pos += 1;
                text.push('.');
                text.push_str(&self.read_digits(10, false)?);
            }
            self.read_exponent(&mut text)?;
        } else {
            text.push_str(&self.read_digits(10, true)?);
            if self.peek() == Some('n') {
                self.pos += 1;
                is_bigint = true;
            } else {
                if self.peek() == Some('.') {
                    self.pos += 1;
                    text.push('.');
                    text.push_str(&self.read_digits(10, true)?);
                }
                self.read_exponent(&mut text)?;
            }
        }
        if let Some(c) = self.peek() {
            if is_id_start(c) || c.is_ascii_digit() || c == '\\' {
                return Err(self.err("identifier starts immediately after numeric literal"));
            }
        }
        if is_bigint {
            // text includes possible 0x prefix
            let _ = radix;
            return Ok(self.mk(Tok::BigInt(text), start, line, nl));
        }
        let v = crate::numconv::parse_numeric_literal(&text).ok_or_else(|| self.err("invalid numeric literal"))?;
        let mut t = self.mk(Tok::Num(v), start, line, nl);
        t.legacy_octal = legacy_octal;
        Ok(t)
    }

    fn read_exponent(&mut self, text: &mut String) -> Result<(), LexError> {
        if matches!(self.peek(), Some('e' | 'E')) {
            self.pos += 1;
            text.push('e');
            if matches!(self.peek(), Some('+' | '-')) {
                text.push(self.peek().unwrap());
                self.pos += 1;
            }
            let d = self.read_digits(10, true)?;
            if d.is_empty() {
                return Err(self.err("invalid numeric literal"));
            }
            text.push_str(&d);
        }
        Ok(())
    }

    fn read_digits(&mut self, radix: u32, allow_sep: bool) -> Result<String, LexError> {
        let mut s = String::new();
        let mut last_sep = false;
        loop {
            match self.peek() {
                Some('_') if allow_sep => {
                    if s.is_empty() || last_sep {
                        return Err(self.err("invalid numeric separator"));
                    }
                    if !self.peek_at(1).map_or(false, |c| c.is_digit(radix)) {
                        return Err(self.err("invalid numeric separator"));
                    }
                    last_sep = true;
                    self.pos += 1;
                }
                Some(c) if c.is_digit(radix) => {
                    s.push(c);
                    last_sep = false;
                    self.pos += 1;
                }
                _ => break,
            }
        }
        Ok(s)
    }

    fn read_string(&mut self, q: char, start: usize, line: u32, nl: bool) -> Result<Token, LexError> {
        self.pos += 1;
        let mut out: Vec<u16> = Vec::new();
        let mut octal = false;
        loop {
            let c = match self.peek() {
                None => return Err(self.err("unterminated string literal")),
                Some(c) => c,
            };
            if c == q {
                self.pos += 1;
                break;
            }
            if c == '\n' || c == '\r' {
                return Err(self.err("unterminated string literal"));
            }
            if c == '\\' {
                self.pos += 1;
                let e = match self.peek() {
                    None => return Err(self.err("unterminated string literal")),
                    Some(e) => e,
                };
                match e {
                    '0'..='7' => {
                        // \0 not followed by digit is NUL
                        if e == '0' && !self.peek_at(1).map_or(false, |d| d.is_ascii_digit()) {
                            self.pos += 1;
                            out.push(0);
                        } else {
                            octal = true;
                            let mut v = 0u32;
                            let maxlen = if e <= '3' { 3 } else { 2 };
                            let mut n = 0;
                            while n < maxlen {
                                match self.peek() {
                                    Some(d @ '0'..='7') => {
                                        v = v * 8 + d.to_digit(8).unwrap();
                                        self.pos += 1;
                                        n += 1;
                                    }
                                    _ => break,
                                }
                            }
                            out.push(v as u16);
                        }
                    }
                    '8' | '9' => {
                        octal = true;
                        self.pos += 1;
                        out.push(e as u16);
                    }
                    _ => {
                        let (v, _ok) = self.read_escape(false)?;
                        if let Some(v) = v {
                            for u in v {
                                out.push(u);
                            }
                        }
                    }
                }
                continue;
            }
            self.pos += 1;
            push_utf16(&mut out, c as u32);
        }
        let mut t = self.mk(Tok::Str(out), start, line, nl);
        t.octal_escape = octal;
        Ok(t)
    }

    /// Reads an escape (after backslash, at the escape char). Returns the code units
    /// produced (None for line continuation). For templates, invalid escapes yield Err-less
    /// "invalid" flag (second value false).
    fn read_escape(&mut self, template: bool) -> Result<(Option<Vec<u16>>, bool), LexError> {
        let e = self.peek().unwrap();
        self.pos += 1;
        let simple = |c: u16| Ok((Some(vec![c]), true));
        match e {
            'n' => simple(10),
            't' => simple(9),
            'r' => simple(13),
            'b' => simple(8),
            'f' => simple(12),
            'v' => simple(11),
            '\r' => {
                if self.peek() == Some('\n') {
                    self.pos += 1;
                }
                self.line += 1;
                Ok((None, true))
            }
            '\n' | '\u{2028}' | '\u{2029}' => {
                self.line += 1;
                Ok((None, true))
            }
            'x' => {
                let a = self.peek().and_then(|c| c.to_digit(16));
                let b = self.peek_at(1).and_then(|c| c.to_digit(16));
                match (a, b) {
                    (Some(a), Some(b)) => {
                        self.pos += 2;
                        Ok((Some(vec![(a * 16 + b) as u16]), true))
                    }
                    _ => {
                        if template {
                            Ok((None, false))
                        } else {
                            Err(self.err("invalid hexadecimal escape sequence"))
                        }
                    }
                }
            }
            'u' => {
                let save = self.pos;
                match self.read_unicode_escape_body() {
                    Some(v) => {
                        let mut out = Vec::new();
                        push_utf16(&mut out, v);
                        Ok((Some(out), true))
                    }
                    None => {
                        if template {
                            self.pos = save;
                            Ok((None, false))
                        } else {
                            // distinguish out of range
                            self.pos = save;
                            if self.peek() == Some('{') {
                                let mut j = self.pos + 1;
                                let mut v: u64 = 0;
                                let mut ok = true;
                                while let Some(c) = self.src.get(j) {
                                    if *c == '}' {
                                        break;
                                    }
                                    match c.to_digit(16) {
                                        Some(d) => v = (v * 16 + d as u64).min(0xFFFFFFFF),
                                        None => {
                                            ok = false;
                                            break;
                                        }
                                    }
                                    j += 1;
                                }
                                if ok && v > 0x10FFFF {
                                    return Err(self.err("undefined Unicode code-point"));
                                }
                            }
                            Err(self.err("invalid Unicode escape sequence"))
                        }
                    }
                }
            }
            c => {
                let mut out = Vec::new();
                push_utf16(&mut out, c as u32);
                if is_line_term(c) {
                    self.line += 1;
                }
                Ok((Some(out), true))
            }
        }
    }

    /// Reads template characters after '`' or after the '}' closing a substitution.
    pub fn read_template(&mut self, start: usize, line: u32, nl: bool) -> Result<Token, LexError> {
        let mut cooked: Vec<u16> = Vec::new();
        let mut raw: Vec<u16> = Vec::new();
        let mut valid = true;
        loop {
            let c = match self.peek() {
                None => return Err(self.err("unterminated template literal")),
                Some(c) => c,
            };
            if c == '`' {
                self.pos += 1;
                let cooked = if valid { Some(cooked) } else { None };
                return Ok(self.mk(Tok::Template { cooked, raw, tail: true }, start, line, nl));
            }
            if c == '$' && self.peek_at(1) == Some('{') {
                self.pos += 2;
                let cooked = if valid { Some(cooked) } else { None };
                return Ok(self.mk(Tok::Template { cooked, raw, tail: false }, start, line, nl));
            }
            if c == '\\' {
                let esc_start = self.pos;
                self.pos += 1;
                if self.peek().is_none() {
                    return Err(self.err("unterminated template literal"));
                }
                let e = self.peek().unwrap();
                if e.is_ascii_digit() {
                    if e == '0' && !self.peek_at(1).map_or(false, |d| d.is_ascii_digit()) {
                        self.pos += 1;
                        cooked.push(0);
                    } else {
                        valid = false;
                        self.pos += 1;
                    }
                } else {
                    let (v, ok) = self.read_escape(true)?;
                    if !ok {
                        valid = false;
                    } else if let Some(v) = v {
                        cooked.extend(v);
                    }
                }
                // raw: source text of escape with CRLF/CR normalized to LF
                let mut i = esc_start;
                while i < self.pos {
                    let ch = self.src[i];
                    if ch == '\r' {
                        raw.push(10);
                        if self.src.get(i + 1) == Some(&'\n') {
                            i += 1;
                        }
                    } else {
                        push_utf16(&mut raw, ch as u32);
                    }
                    i += 1;
                }
                continue;
            }
            self.pos += 1;
            if c == '\r' {
                if self.peek() == Some('\n') {
                    self.pos += 1;
                }
                self.line += 1;
                cooked.push(10);
                raw.push(10);
                continue;
            }
            if is_line_term(c) {
                self.line += 1;
            }
            push_utf16(&mut cooked, c as u32);
            push_utf16(&mut raw, c as u32);
        }
    }

    /// Re-scan starting at `start` (position of a '/' or '/=' token) as a regex literal.
    pub fn read_regex(&mut self, start: usize, line: u32, nl: bool) -> Result<Token, LexError> {
        self.pos = start + 1;
        let mut pattern: Vec<u16> = Vec::new();
        let mut in_class = false;
        loop {
            let c = match self.peek() {
                None => return Err(self.err("unterminated regular expression")),
                Some(c) => c,
            };
            if is_line_term(c) {
                return Err(self.err("unterminated regular expression"));
            }
            self.pos += 1;
            if c == '\\' {
                push_utf16(&mut pattern, c as u32);
                match self.peek() {
                    None => return Err(self.err("unterminated regular expression")),
                    Some(n) if is_line_term(n) => return Err(self.err("unterminated regular expression")),
                    Some(n) => {
                        self.pos += 1;
                        push_utf16(&mut pattern, n as u32);
                    }
                }
                continue;
            }
            if c == '[' {
                in_class = true;
            } else if c == ']' {
                in_class = false;
            } else if c == '/' && !in_class {
                break;
            }
            push_utf16(&mut pattern, c as u32);
        }
        let mut flags: Vec<u16> = Vec::new();
        while let Some(c) = self.peek() {
            if is_id_continue(c) {
                push_utf16(&mut flags, c as u32);
                self.pos += 1;
            } else if c == '\\' {
                return Err(self.err("invalid regular expression flags"));
            } else {
                break;
            }
        }
        Ok(self.mk(Tok::Regex { pattern, flags }, start, line, nl))
    }

    pub fn slice(&self, start: usize, end: usize) -> String {
        self.src[start..end.min(self.src.len())].iter().collect()
    }
}
