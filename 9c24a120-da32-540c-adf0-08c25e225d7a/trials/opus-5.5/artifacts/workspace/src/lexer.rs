// Lexer: bytes -> tokens with positions. Layout is decided by the parser from
// each token's column and whether it starts a line.

use crate::diag::Diag;
use crate::source::Span;

#[derive(Clone, Debug, PartialEq)]
pub enum Tok {
    Int(i64),
    Float(f64),
    Str(String),
    FStr(Vec<FPiece>),
    Ident(String),
    Upper(String),
    Hole(Option<String>),
    // keywords
    Let,
    Mut,
    Pure,
    Type,
    Measure,
    Extern,
    Import,
    Module,
    If,
    Then,
    Elif,
    Else,
    Match,
    Case,
    Fun,
    And,
    Or,
    Not,
    True,
    False,
    Return,
    With,
    As,
    Yield,
    Do,
    Try,
    // punctuation
    LParen,
    RParen,
    LBracket,
    RBracket,
    LBrace,
    RBrace,
    Comma,
    Dot,
    Ellipsis,
    Colon,
    Eq,
    Arrow,
    LArrow,
    Bar,
    Underscore,
    Bang,
    Caret,
    // operators
    Plus,
    Minus,
    Star,
    Slash,
    SlashSlash,
    Percent,
    StarStar,
    EqEq,
    NotEq,
    Lt,
    Le,
    Gt,
    Ge,
    PipeRight,
    PipeLeft,
    ComposeRight,
    ComposeLeft,
    /// (recovering) where a token failed to lex: it takes its place in the
    /// layout, and an expression simply skips it
    LexError,
    Eof,
}

#[derive(Clone, Debug, PartialEq)]
pub enum FPiece {
    Text(String),
    /// A `{...}` hole: its tokens (ending in Eof), the span of the content, and
    /// for `{expr=}` the source text echoed before the value.
    Hole { toks: Vec<Token>, span: Span, debug: Option<String> },
}

#[derive(Clone, Debug, PartialEq)]
pub struct Token {
    pub tok: Tok,
    pub span: Span,
    pub line: usize,
    pub col: usize,
    /// first token on its line
    pub bol: bool,
    /// whitespace (or a comment) right before this token
    pub space_before: bool,
}

pub fn describe(t: &Tok) -> String {
    match t {
        Tok::Int(n) => format!("integer `{}`", n),
        Tok::Float(f) => format!("float `{}`", f),
        Tok::Str(_) => "string literal".to_string(),
        Tok::Ident(s) | Tok::Upper(s) => format!("identifier `{}`", s),
        Tok::Eof => "end of input".to_string(),
        other => format!("`{}`", tok_text(other)),
    }
}

pub fn tok_text(t: &Tok) -> &'static str {
    match t {
        Tok::Let => "let",
        Tok::Mut => "mut",
        Tok::Pure => "pure",
        Tok::Type => "type",
        Tok::Measure => "measure",
        Tok::Extern => "extern",
        Tok::Import => "import",
        Tok::Module => "module",
        Tok::If => "if",
        Tok::Then => "then",
        Tok::Else => "else",
        Tok::Match => "match",
        Tok::Fun => "fun",
        Tok::And => "and",
        Tok::Or => "or",
        Tok::Not => "not",
        Tok::True => "true",
        Tok::False => "false",
        Tok::Return => "return",
        Tok::With => "with",
        Tok::Yield => "yield",
        Tok::Do => "do",
        Tok::LParen => "(",
        Tok::RParen => ")",
        Tok::LBracket => "[",
        Tok::RBracket => "]",
        Tok::LBrace => "{",
        Tok::RBrace => "}",
        Tok::Comma => ",",
        Tok::Dot => ".",
        Tok::Ellipsis => "...",
        Tok::Colon => ":",
        Tok::Eq => "=",
        Tok::Arrow => "->",
        Tok::LArrow => "<-",
        Tok::Bar => "|",
        Tok::Underscore => "_",
        Tok::Bang => "!",
        Tok::Caret => "^",
        Tok::Plus => "+",
        Tok::Minus => "-",
        Tok::Star => "*",
        Tok::Slash => "/",
        Tok::SlashSlash => "//",
        Tok::EqEq => "==",
        Tok::NotEq => "!=",
        Tok::Lt => "<",
        Tok::Le => "<=",
        Tok::Gt => ">",
        Tok::Ge => ">=",
        Tok::PipeRight => "|>",
        Tok::PipeLeft => "<|",
        Tok::ComposeRight => ">>",
        Tok::ComposeLeft => "<<",
        // the original's token display falls back to this for newer tokens
        _ => "token",
    }
}

fn keyword(s: &str) -> Option<Tok> {
    Some(match s {
        "let" => Tok::Let,
        "mut" => Tok::Mut,
        "pure" => Tok::Pure,
        "type" => Tok::Type,
        "measure" => Tok::Measure,
        "extern" => Tok::Extern,
        "import" => Tok::Import,
        "module" => Tok::Module,
        "if" => Tok::If,
        "then" => Tok::Then,
        "elif" => Tok::Elif,
        "else" => Tok::Else,
        "match" => Tok::Match,
        "case" => Tok::Case,
        "fun" => Tok::Fun,
        "and" => Tok::And,
        "or" => Tok::Or,
        "not" => Tok::Not,
        "true" => Tok::True,
        "false" => Tok::False,
        "return" => Tok::Return,
        "with" => Tok::With,
        "as" => Tok::As,
        "yield" => Tok::Yield,
        "do" => Tok::Do,
        "try" => Tok::Try,
        _ => return None,
    })
}

pub struct Lexed {
    pub toks: Vec<Token>,
    /// `##` doc lines: (line number, text)
    pub docs: Vec<(usize, String)>,
    pub error: Option<Diag>,
}

pub struct Lexer<'a> {
    src: &'a [u8],
    pos: usize,
    end: usize,
    line: usize,
    line_start: usize,
    toks: Vec<Token>,
    docs: Vec<(usize, String)>,
    last_line_with_token: usize,
    space: bool,
    tok_line: usize,
    tok_ls: usize,
    /// keep going after an error (the language server wants them all)
    recover: bool,
    errors: Vec<Diag>,
}

fn is_ident_start(c: u8) -> bool {
    c.is_ascii_alphabetic() || c == b'_'
}
fn is_ident_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

pub fn lex(src: &str) -> Lexed {
    lex_mode(src, false).0
}

/// Lex everything, recovering after each error.
pub fn lex_all(src: &str) -> (Lexed, Vec<Diag>) {
    lex_mode(src, true)
}

fn lex_mode(src: &str, recover: bool) -> (Lexed, Vec<Diag>) {
    let mut lx = Lexer::new(src.as_bytes(), 0, src.len(), 1, 0);
    lx.recover = recover;
    let error = lx.run().err();
    let errors = std::mem::take(&mut lx.errors);
    let error = error.or_else(|| errors.first().cloned());
    let eof = lx.pos.min(src.len());
    let (line, col) = (lx.line, eof - lx.line_start + 1);
    lx.toks.push(Token {
        tok: Tok::Eof,
        span: Span::new(src.len(), src.len()),
        line,
        col,
        bol: true,
        space_before: true,
    });
    // the Eof token sits at the very end of the file
    if let Some(last) = lx.toks.last_mut() {
        let (l, c) = line_col(src.as_bytes(), src.len());
        last.line = l;
        last.col = c;
    }
    (Lexed { toks: lx.toks, docs: lx.docs, error }, errors)
}

pub fn line_col(src: &[u8], off: usize) -> (usize, usize) {
    let mut line = 1;
    let mut ls = 0;
    for (i, &b) in src.iter().enumerate().take(off) {
        if b == b'\n' {
            line += 1;
            ls = i + 1;
        }
    }
    (line, off - ls + 1)
}

impl<'a> Lexer<'a> {
    fn new(src: &'a [u8], pos: usize, end: usize, line: usize, line_start: usize) -> Self {
        Lexer {
            src,
            pos,
            end,
            line,
            line_start,
            toks: Vec::new(),
            docs: Vec::new(),
            last_line_with_token: 0,
            space: true,
            tok_line: line,
            tok_ls: line_start,
            recover: false,
            errors: Vec::new(),
        }
    }

    fn peek(&self, k: usize) -> u8 {
        let p = self.pos + k;
        if p < self.end {
            self.src[p]
        } else {
            0
        }
    }

    fn err(&self, msg: impl Into<String>, lo: usize, hi: usize) -> Diag {
        Diag::error(msg.into(), Span::new(lo, hi))
    }

    fn push(&mut self, tok: Tok, lo: usize) {
        let line = self.tok_line;
        let col = lo - self.tok_ls + 1;
        let bol = self.last_line_with_token != line;
        self.last_line_with_token = self.line;
        self.toks.push(Token { tok, span: Span::new(lo, self.pos), line, col, bol, space_before: self.space });
        self.space = false;
    }

    fn newline(&mut self) {
        // self.pos points just past a '\n'
        self.line += 1;
        self.line_start = self.pos;
    }

    fn run(&mut self) -> Result<(), Diag> {
        while self.pos < self.end {
            let start = self.pos;
            if let Err(e) = self.step() {
                if !self.recover {
                    return Err(e);
                }
                // resume after the bad text: past an unexpected character,
                // at a stray `}` (which then lexes as itself), else at the
                // end of the error's span
                let resume = if e.msg.starts_with("unexpected character") {
                    let c = self.src[start];
                    start + if c < 0x80 { 1 } else if c >= 0xF0 { 4 } else if c >= 0xE0 { 3 } else if c >= 0xC0 { 2 } else { 1 }
                } else if e.msg.starts_with("single `}`") {
                    e.span.lo
                } else {
                    e.span.hi.max(start + 1)
                };
                self.errors.push(e);
                // a stand-in for a failed token that starts its line (it
                // shapes the layout); one further along simply goes
                let line = self.tok_line;
                let col = start - self.tok_ls + 1;
                let bol = self.last_line_with_token != line;
                self.last_line_with_token = line;
                if bol {
                    self.toks.push(Token { tok: Tok::LexError, span: Span::new(start, start), line, col, bol, space_before: self.space });
                }
                self.pos = resume.min(self.end);
                let (l, _) = line_col(self.src, self.pos);
                let mut ls = self.pos;
                while ls > 0 && self.src[ls - 1] != b'\n' {
                    ls -= 1;
                }
                self.line = l;
                self.line_start = ls;
                self.space = true;
            }
        }
        Ok(())
    }

    fn step(&mut self) -> Result<(), Diag> {
        {
            let c = self.src[self.pos];
            self.tok_line = self.line;
            self.tok_ls = self.line_start;
            match c {
                b' ' | b'\t' | b'\r' => {
                    self.pos += 1;
                    self.space = true;
                }
                b'\n' => {
                    self.pos += 1;
                    self.newline();
                    self.space = true;
                }
                b'#' => {
                    let start = self.pos;
                    while self.pos < self.end && self.src[self.pos] != b'\n' {
                        self.pos += 1;
                    }
                    if start == self.line_start && self.src.get(start + 1) == Some(&b'#') && start + 1 < self.end {
                        let text = String::from_utf8_lossy(&self.src[start + 2..self.pos]).to_string();
                        // (one space after `##` is the marker's; the rest is the text's)
                        let text = text.strip_prefix(' ').unwrap_or(&text).trim_end().to_string();
                        self.docs.push((self.line, text));
                    }
                    self.space = true;
                }
                b'0'..=b'9' => self.number()?,
                b'"' => self.string(self.pos, false, false)?,
                b'f' if self.peek(1) == b'"' => self.string(self.pos, false, true)?,
                b'r' if self.peek(1) == b'"' => self.string(self.pos, true, false)?,
                c if is_ident_start(c) => {
                    let start = self.pos;
                    while self.pos < self.end && is_ident_char(self.src[self.pos]) {
                        self.pos += 1;
                    }
                    let s = std::str::from_utf8(&self.src[start..self.pos]).unwrap().to_string();
                    let tok = if s == "_" {
                        Tok::Underscore
                    } else if let Some(k) = keyword(&s) {
                        k
                    } else if s.as_bytes()[0].is_ascii_uppercase() {
                        Tok::Upper(s)
                    } else {
                        Tok::Ident(s)
                    };
                    self.push(tok, start);
                }
                b'?' => {
                    let start = self.pos;
                    self.pos += 1;
                    if self.pos < self.end && is_ident_start(self.src[self.pos]) {
                        let ns = self.pos;
                        while self.pos < self.end && is_ident_char(self.src[self.pos]) {
                            self.pos += 1;
                        }
                        let s = std::str::from_utf8(&self.src[ns..self.pos]).unwrap().to_string();
                        self.push(Tok::Hole(Some(s)), start);
                    } else {
                        self.push(Tok::Hole(None), start);
                    }
                }
                _ => self.punct()?,
            }
        }
        Ok(())
    }

    fn punct(&mut self) -> Result<(), Diag> {
        let start = self.pos;
        let c = self.src[self.pos];
        let n1 = self.peek(1);
        let n2 = self.peek(2);
        let (tok, len) = match c {
            b'(' => (Tok::LParen, 1),
            b')' => (Tok::RParen, 1),
            b'[' => (Tok::LBracket, 1),
            b']' => (Tok::RBracket, 1),
            b'{' => (Tok::LBrace, 1),
            b'}' => (Tok::RBrace, 1),
            b',' => (Tok::Comma, 1),
            b'.' if n1 == b'.' && n2 == b'.' => (Tok::Ellipsis, 3),
            b'.' => (Tok::Dot, 1),
            b':' => (Tok::Colon, 1),
            b'=' if n1 == b'=' => (Tok::EqEq, 2),
            b'=' => (Tok::Eq, 1),
            b'-' if n1 == b'>' => (Tok::Arrow, 2),
            b'-' => (Tok::Minus, 1),
            b'<' if n1 == b'-' => (Tok::LArrow, 2),
            b'<' if n1 == b'|' => (Tok::PipeLeft, 2),
            b'<' if n1 == b'<' => (Tok::ComposeLeft, 2),
            b'<' if n1 == b'=' => (Tok::Le, 2),
            b'<' => (Tok::Lt, 1),
            b'>' if n1 == b'>' => (Tok::ComposeRight, 2),
            b'>' if n1 == b'=' => (Tok::Ge, 2),
            b'>' => (Tok::Gt, 1),
            b'|' if n1 == b'>' => (Tok::PipeRight, 2),
            b'|' => (Tok::Bar, 1),
            b'&' if n1 == b'&' => return Err(self.err("use `and` instead of `&&`", start, start + 2)),
            b'!' if n1 == b'=' => (Tok::NotEq, 2),
            b'!' => (Tok::Bang, 1),
            b'^' => (Tok::Caret, 1),
            b'+' => (Tok::Plus, 1),
            b'*' if n1 == b'*' => (Tok::StarStar, 2),
            b'*' => (Tok::Star, 1),
            b'/' if n1 == b'/' => (Tok::SlashSlash, 2),
            b'/' => (Tok::Slash, 1),
            b'%' => (Tok::Percent, 1),
            _ => {
                let ch = c as char;
                return Err(self.err(format!("unexpected character {:?}", ch), start, start));
            }
        };
        self.pos += len;
        self.push(tok, start);
        Ok(())
    }

    fn number(&mut self) -> Result<(), Diag> {
        let start = self.pos;
        let c1 = self.peek(1);
        if self.src[self.pos] == b'0' && matches!(c1, b'x' | b'X' | b'o' | b'O' | b'b' | b'B') {
            let radix = match c1 {
                b'x' | b'X' => 16,
                b'o' | b'O' => 8,
                _ => 2,
            };
            self.pos += 2;
            let mut digits = String::new();
            loop {
                let c = self.peek(0);
                if (c as char).is_digit(radix) {
                    digits.push(c as char);
                    self.pos += 1;
                } else if c == b'_' && (self.peek(1) as char).is_digit(radix) && !digits.is_empty() {
                    self.pos += 1;
                } else {
                    break;
                }
            }
            match i64::from_str_radix(&digits, radix) {
                Ok(v) if !digits.is_empty() => {
                    self.push(Tok::Int(v), start);
                    Ok(())
                }
                _ => Err(self.err("invalid integer literal", start, self.pos)),
            }
        } else {
            let mut text = String::new();
            self.digits(&mut text);
            let mut is_float = false;
            if self.peek(0) == b'.' && self.peek(1).is_ascii_digit() {
                is_float = true;
                text.push('.');
                self.pos += 1;
                self.digits(&mut text);
            }
            if matches!(self.peek(0), b'e' | b'E') {
                let (s, d) = (self.peek(1), self.peek(2));
                if s.is_ascii_digit() || ((s == b'+' || s == b'-') && d.is_ascii_digit()) {
                    is_float = true;
                    text.push('e');
                    self.pos += 1;
                    if s == b'+' || s == b'-' {
                        text.push(s as char);
                        self.pos += 1;
                    }
                    self.digits(&mut text);
                }
            }
            if is_float {
                let v: f64 = text.parse().unwrap_or(f64::INFINITY);
                self.push(Tok::Float(v), start);
                Ok(())
            } else {
                match text.parse::<i64>() {
                    Ok(v) => {
                        self.push(Tok::Int(v), start);
                        Ok(())
                    }
                    Err(_) => Err(self.err("invalid integer literal", start, self.pos)),
                }
            }
        }
    }

    fn digits(&mut self, out: &mut String) {
        loop {
            let c = self.peek(0);
            if c.is_ascii_digit() {
                out.push(c as char);
                self.pos += 1;
            } else if c == b'_' && self.peek(1).is_ascii_digit() {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    /// Scan a string literal starting at `start` (which points at `f`/`r` or the quote).
    fn string(&mut self, start: usize, raw: bool, fstr: bool) -> Result<(), Diag> {
        if raw || fstr {
            self.pos += 1;
        }
        let triple = self.peek(0) == b'"' && self.peek(1) == b'"' && self.peek(2) == b'"';
        self.pos += if triple { 3 } else { 1 };
        let mut text: Vec<u8> = Vec::new();
        let mut pieces: Vec<FPiece> = Vec::new();
        loop {
            if self.pos >= self.end {
                return Err(if fstr {
                    self.err("unterminated f-string", start, self.end)
                } else if raw {
                    self.err("unterminated raw string literal", start, self.end)
                } else {
                    self.unterminated(start, triple, false)
                });
            }
            let c = self.src[self.pos];
            if c == b'"' {
                if triple {
                    if self.peek(1) == b'"' && self.peek(2) == b'"' {
                        self.pos += 3;
                        break;
                    }
                    text.push(b'"');
                    self.pos += 1;
                    continue;
                }
                self.pos += 1;
                break;
            }
            if c == b'\n' {
                text.push(b'\n');
                self.pos += 1;
                self.newline();
                continue;
            }
            if c == b'\\' {
                if raw {
                    text.push(b'\\');
                    self.pos += 1;
                    if self.pos < self.end && (self.src[self.pos] == b'"' || self.src[self.pos] == b'\\') {
                        text.push(self.src[self.pos]);
                        self.pos += 1;
                    }
                    continue;
                }
                self.escape(&mut text)?;
                continue;
            }
            if fstr && c == b'{' {
                if self.peek(1) == b'{' {
                    text.push(b'{');
                    self.pos += 2;
                    continue;
                }
                if !text.is_empty() {
                    pieces.push(FPiece::Text(String::from_utf8_lossy(&text).to_string()));
                    text.clear();
                }
                let hole = self.fhole(start)?;
                pieces.push(hole);
                continue;
            }
            if fstr && c == b'}' {
                if self.peek(1) == b'}' {
                    text.push(b'}');
                    self.pos += 2;
                    continue;
                }
                return Err(self.err("single `}` in f-string; write `}}` for a literal brace", self.pos, self.pos));
            }
            text.push(c);
            self.pos += 1;
        }
        let tok = if fstr {
            if !text.is_empty() {
                pieces.push(FPiece::Text(String::from_utf8_lossy(&text).to_string()));
            }
            Tok::FStr(pieces)
        } else {
            Tok::Str(String::from_utf8_lossy(&text).to_string())
        };
        self.push(tok, start);
        Ok(())
    }

    fn unterminated(&self, start: usize, triple: bool, in_f: bool) -> Diag {
        // the literal runs to the end of the input
        let e = self.end;
        let msg = if in_f {
            "unterminated string literal in f-string"
        } else if triple {
            "unterminated triple-quoted string literal"
        } else {
            "unterminated string literal"
        };
        self.err(msg, start, e)
    }

    fn escape(&mut self, text: &mut Vec<u8>) -> Result<(), Diag> {
        let bs = self.pos;
        let c = self.peek(1);
        match c {
            b'n' => text.push(b'\n'),
            b't' => text.push(b'\t'),
            b'r' => text.push(b'\r'),
            b'"' => text.push(b'"'),
            b'\\' => text.push(b'\\'),
            b'u' => {
                if self.peek(2) != b'{' {
                    return Err(self.err("expected `{` after `\\u` (write `\\u{1F600}`)", bs, bs + 2));
                }
                let mut p = bs + 3;
                let mut hex = String::new();
                while p < self.end && (self.src[p] as char).is_ascii_hexdigit() {
                    hex.push(self.src[p] as char);
                    p += 1;
                }
                if p >= self.end || self.src[p] != b'}' {
                    return Err(self.err("expected `}` to close `\\u{...}`", bs, p));
                }
                p += 1;
                if hex.is_empty() || hex.len() > 6 {
                    return Err(self.err("invalid `\\u{...}` escape", bs, p));
                }
                let v = u32::from_str_radix(&hex, 16).unwrap();
                match char::from_u32(v) {
                    Some(ch) => {
                        let mut buf = [0u8; 4];
                        text.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                    }
                    None => return Err(self.err("invalid Unicode code point in `\\u{...}`", bs, p)),
                }
                self.pos = p;
                return Ok(());
            }
            _ => return Err(self.err("invalid escape sequence", bs, bs + 1)),
        }
        self.pos += 2;
        Ok(())
    }

    /// At a `{` inside an f-string: find the hole's extent, lex its content.
    fn fhole(&mut self, fstart: usize) -> Result<FPiece, Diag> {
        let open = self.pos;
        self.pos += 1;
        let cstart = self.pos;
        let mut depth = 0usize;
        // scan to the matching close brace, skipping nested strings
        loop {
            if self.pos >= self.end {
                // ran out: the enclosing literal is unterminated
                return Err(self.err("unterminated f-string (missing `}`)", fstart, self.end));
            }
            let c = self.src[self.pos];
            match c {
                b'{' => {
                    depth += 1;
                    self.pos += 1;
                }
                b'}' => {
                    if depth == 0 {
                        break;
                    }
                    depth -= 1;
                    self.pos += 1;
                }
                b'"' => {
                    // nested string: must close before the hole does
                    let s = self.pos;
                    let triple = self.peek(1) == b'"' && self.peek(2) == b'"';
                    self.pos += if triple { 3 } else { 1 };
                    loop {
                        // (a string may run over lines here too)
                        if self.pos >= self.end {
                            return Err(self.unterminated(s, triple, true));
                        }
                        let d = self.src[self.pos];
                        if d == b'\\' {
                            self.pos += 2;
                            continue;
                        }
                        if d == b'"' {
                            if triple {
                                if self.peek(1) == b'"' && self.peek(2) == b'"' {
                                    self.pos += 3;
                                    break;
                                }
                            } else {
                                self.pos += 1;
                                break;
                            }
                        }
                        if d == b'\n' {
                            self.pos += 1;
                            self.newline();
                            continue;
                        }
                        self.pos += 1;
                    }
                }
                b'#' => {
                    while self.pos < self.end && self.src[self.pos] != b'}' && self.src[self.pos] != b'\n' {
                        self.pos += 1;
                    }
                }
                b'\n' => {
                    self.pos += 1;
                    self.newline();
                }
                _ => self.pos += 1,
            }
        }
        let cend = self.pos;
        self.pos += 1; // the closing brace
        let content = &self.src[cstart..cend];
        if cstart == cend {
            return Err(self.err("empty f-string hole `{}`", cstart, cend + 1));
        }
        // `{expr=}`: echo the source text before the value
        let mut expr_end = cend;
        let mut debug = None;
        {
            let mut e = cend;
            while e > cstart && (self.src[e - 1] == b' ' || self.src[e - 1] == b'\t') {
                e -= 1;
            }
            if e > cstart && self.src[e - 1] == b'=' {
                let prev = if e >= cstart + 2 { self.src[e - 2] } else { 0 };
                if !matches!(prev, b'=' | b'!' | b'<' | b'>') {
                    debug = Some(String::from_utf8_lossy(content).to_string());
                    expr_end = e - 1;
                }
            }
        }
        let (line, ls) = {
            let (l, _) = line_col(self.src, cstart);
            let mut s = cstart;
            while s > 0 && self.src[s - 1] != b'\n' {
                s -= 1;
            }
            (l, s)
        };
        let mut sub = Lexer::new(self.src, cstart, expr_end, line, ls);
        sub.last_line_with_token = line;
        sub.recover = self.recover;
        sub.run()?;
        self.errors.append(&mut sub.errors);
        let mut toks = sub.toks;
        let (el, ec) = line_col(self.src, expr_end);
        toks.push(Token { tok: Tok::Eof, span: Span::new(expr_end, expr_end), line: el, col: ec, bol: false, space_before: true });
        let _ = open;
        Ok(FPiece::Hole { toks, span: Span::new(cstart, cend), debug })
    }
}
