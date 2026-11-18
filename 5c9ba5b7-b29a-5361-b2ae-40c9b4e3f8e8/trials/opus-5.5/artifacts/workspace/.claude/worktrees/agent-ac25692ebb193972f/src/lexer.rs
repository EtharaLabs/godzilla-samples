// Tokenizer for Lini source. The whole file is lexed up front; the first
// lexical error aborts the compile.

use crate::diag::{Diag, Span};

#[derive(Debug, Clone, PartialEq)]
pub enum Tok {
    Ident(String),
    Num(f64, String),
    Str(String),
    Hash(String),  // '#' followed by word chars (id or colour)
    Var(String),   // '--name'
    Class(String), // '.name'
    Bar,           // '|'
    BarBar,        // '||'
    LBrace,
    RBrace,
    LBrack,
    RBrack,
    LParen,
    RParen,
    Semi,
    Colon,
    DColon,
    Comma,
    Dot,
    Eq,
    Amp,
    Op(String),     // math operator: + - * / ^ % ? ! < > <= >= == != && ||
    LinkOp(String), // link operator such as '->' '-o<' '~>'
    DimOp(String),  // '(-)' or '(o)'
    Percent(f64, String),
    Newline,
    Eof,
}

#[derive(Debug, Clone)]
pub struct Token {
    pub tok: Tok,
    pub span: Span,
    pub space_before: bool,
}

#[derive(Debug, Clone)]
pub struct Comment {
    pub text: String, // including the leading '//'
    pub span: Span,
    pub own_line: bool,
}

pub struct Lexed {
    pub tokens: Vec<Token>,
    pub comments: Vec<Comment>,
}

fn is_ident_start(c: char) -> bool {
    c.is_ascii_alphabetic() || c == '_'
}
fn is_ident_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '-'
}

pub fn lex(src: &str) -> Result<Lexed, Diag> {
    let chars: Vec<(usize, char)> = src.char_indices().collect();
    let n = chars.len();
    let byte_at = |i: usize| -> usize { if i < n { chars[i].0 } else { src.len() } };
    let ch = |i: usize| -> char { if i < n { chars[i].1 } else { '\0' } };
    let mut toks: Vec<Token> = Vec::new();
    let mut comments = Vec::new();
    let mut i = 0usize;
    let mut paren_depth: i32 = 0;
    let mut space_before = true;
    let mut line_start = true;
    while i < n {
        let c = ch(i);
        let start = i;
        let sp = |a: usize, b: usize| Span::new(byte_at(a), byte_at(b));
        match c {
            ' ' | '\t' | '\r' => {
                i += 1;
                space_before = true;
                continue;
            }
            '\n' => {
                toks.push(Token { tok: Tok::Newline, span: sp(i, i + 1), space_before });
                i += 1;
                space_before = true;
                line_start = true;
                continue;
            }
            '/' if ch(i + 1) == '/' => {
                let mut j = i;
                while j < n && ch(j) != '\n' {
                    j += 1;
                }
                let text: String = chars[i..j].iter().map(|x| x.1).collect();
                comments.push(Comment { text, span: sp(i, j), own_line: line_start });
                i = j;
                space_before = true;
                continue;
            }
            _ => {}
        }
        line_start = false;
        let tok: Tok;
        if c == '"' {
            let mut s = String::new();
            let mut j = i + 1;
            loop {
                if j >= n {
                    return Err(Diag::error("unterminated-string", "unterminated string literal", sp(i, j)));
                }
                let d = ch(j);
                if d == '"' {
                    j += 1;
                    break;
                }
                if d == '\\' {
                    let e = ch(j + 1);
                    match e {
                        'n' => s.push('\n'),
                        't' => s.push('\t'),
                        '"' => s.push('"'),
                        '\\' => s.push('\\'),
                        _ => {
                            let shown: String = if j + 1 < n { format!("\\{}", e) } else { "\\".to_string() };
                            return Err(Diag::error(
                                "bad-escape",
                                &format!("invalid escape sequence '{}'", shown),
                                sp(j, (j + 2).min(n)),
                            ));
                        }
                    }
                    j += 2;
                    continue;
                }
                s.push(d);
                j += 1;
            }
            tok = Tok::Str(s);
            i = j;
        } else if c == '\'' {
            return Err(Diag::error("single-quote", "single quotes are not strings — use \"…\"", sp(i, i + 1)));
        } else if c.is_ascii_digit() || (c == '.' && ch(i + 1).is_ascii_digit()) {
            let (t, j) = lex_number(&chars, i, false);
            tok = t;
            i = j;
        } else if c == '-' && (ch(i + 1).is_ascii_digit() || (ch(i + 1) == '.' && ch(i + 2).is_ascii_digit()))
            && neg_allowed(&toks, space_before)
        {
            let (t, j) = lex_number(&chars, i, true);
            tok = t;
            i = j;
        } else if c == '+' && (ch(i + 1).is_ascii_digit() || (ch(i + 1) == '.' && ch(i + 2).is_ascii_digit()))
            && neg_allowed(&toks, space_before)
        {
            // an explicit plus sign: the number itself (`tol: +0.1 0`)
            let (t, j) = lex_number(&chars, i + 1, false);
            tok = t;
            i = j;
        } else if is_ident_start(c) {
            let mut j = i;
            // inside ( ) a '-' is subtraction, never part of a name
            while j < n && is_ident_char(ch(j)) && !(paren_depth > 0 && ch(j) == '-') {
                j += 1;
            }
            tok = Tok::Ident(chars[i..j].iter().map(|x| x.1).collect());
            i = j;
        } else if c == '#' {
            let mut j = i + 1;
            while j < n && is_ident_char(ch(j)) {
                j += 1;
            }
            tok = Tok::Hash(chars[i + 1..j].iter().map(|x| x.1).collect());
            i = j;
        } else if c == '.' {
            if is_ident_start(ch(i + 1)) {
                let mut j = i + 1;
                while j < n && is_ident_char(ch(j)) {
                    j += 1;
                }
                let name: String = chars[i + 1..j].iter().map(|x| x.1).collect();
                if space_before || toks.is_empty() || !prev_is_word(&toks) {
                    tok = Tok::Class(name);
                } else {
                    // path separator: emit Dot and continue lexing the name next round
                    toks.push(Token { tok: Tok::Dot, span: sp(i, i + 1), space_before });
                    space_before = false;
                    tok = Tok::Ident(name);
                    toks.push(Token { tok, span: sp(i + 1, j), space_before: false });
                    i = j;
                    continue;
                }
                i = j;
            } else {
                tok = Tok::Dot;
                i += 1;
            }
        } else if c == '|' {
            if ch(i + 1) == '|' {
                tok = Tok::BarBar;
                i += 2;
            } else {
                tok = Tok::Bar;
                i += 1;
            }
        } else if c == '{' {
            tok = Tok::LBrace;
            i += 1;
        } else if c == '}' {
            tok = Tok::RBrace;
            i += 1;
        } else if c == '[' {
            tok = Tok::LBrack;
            i += 1;
        } else if c == ']' {
            tok = Tok::RBrack;
            i += 1;
        } else if c == '(' {
            if paren_depth == 0 && (ch(i + 1) == '-' || ch(i + 1) == 'o' || ch(i + 1) == '<') && ch(i + 2) == ')' {
                tok = Tok::DimOp(format!("({})", ch(i + 1)));
                i += 3;
            } else {
                paren_depth += 1;
                tok = Tok::LParen;
                i += 1;
            }
        } else if c == ')' {
            paren_depth -= 1;
            tok = Tok::RParen;
            i += 1;
        } else if c == ';' {
            tok = Tok::Semi;
            i += 1;
        } else if c == ',' {
            tok = Tok::Comma;
            i += 1;
        } else if c == ':' {
            if ch(i + 1) == ':' {
                tok = Tok::DColon;
                i += 2;
            } else {
                tok = Tok::Colon;
                i += 1;
            }
        } else if c == '&' {
            if paren_depth > 0 && ch(i + 1) == '&' {
                tok = Tok::Op("&&".into());
                i += 2;
            } else {
                tok = Tok::Amp;
                i += 1;
            }
        } else if c == '=' {
            if ch(i + 1) == '=' {
                tok = Tok::Op("==".into());
                i += 2;
            } else if paren_depth == 0 && ch(i + 1) == '>' {
                // '=' then '>' : '>' starts a link op that needs a line
                tok = Tok::Eq;
                i += 1;
            } else {
                tok = Tok::Eq;
                i += 1;
            }
        } else if c == '-' && ch(i + 1) == '-' && is_ident_start(ch(i + 2)) && paren_depth >= 0 && !link_context(&toks) {
            let mut j = i + 2;
            while j < n && is_ident_char(ch(j)) {
                j += 1;
            }
            tok = Tok::Var(chars[i + 2..j].iter().map(|x| x.1).collect());
            i = j;
        } else if paren_depth > 0 && "+-*/^%?!<>".contains(c) {
            let two: String = [c, ch(i + 1)].iter().collect();
            if two == "<=" || two == ">=" || two == "!=" {
                tok = Tok::Op(two);
                i += 2;
            } else {
                tok = Tok::Op(c.to_string());
                i += 1;
            }
        } else if "-<>~+*".contains(c) || (c == 'o' && false) {
            match lex_link_op(&chars, i)? {
                Some((op, j)) => {
                    tok = Tok::LinkOp(op);
                    i = j;
                }
                None => {
                    tok = Tok::Op(c.to_string());
                    i += 1;
                }
            }
        } else if "/^%?!".contains(c) {
            tok = Tok::Op(c.to_string());
            i += 1;
        } else {
            return Err(Diag::error("unexpected-char", &format!("unexpected character '{}'", c), sp(i, i + 1)));
        }
        toks.push(Token { tok, span: Span::new(byte_at(start), byte_at(i)), space_before });
        space_before = false;
    }
    toks.push(Token { tok: Tok::Eof, span: Span::new(src.len(), src.len()), space_before: true });
    Ok(Lexed { tokens: toks, comments })
}

fn prev_is_word(toks: &[Token]) -> bool {
    match toks.last().map(|t| &t.tok) {
        Some(Tok::Ident(_)) | Some(Tok::Bar) | Some(Tok::RParen) | Some(Tok::Hash(_)) => true,
        _ => false,
    }
}

fn link_context(_toks: &[Token]) -> bool {
    false
}

fn neg_allowed(toks: &[Token], space_before: bool) -> bool {
    if space_before {
        return true;
    }
    match toks.last().map(|t| &t.tok) {
        Some(Tok::Ident(_)) | Some(Tok::Num(..)) | Some(Tok::RParen) | Some(Tok::Str(_)) => false,
        _ => true,
    }
}

fn lex_number(chars: &[(usize, char)], i: usize, neg: bool) -> (Tok, usize) {
    let n = chars.len();
    let ch = |k: usize| -> char { if k < n { chars[k].1 } else { '\0' } };
    let mut j = if neg { i + 1 } else { i };
    while j < n && ch(j).is_ascii_digit() {
        j += 1;
    }
    if ch(j) == '.' && ch(j + 1).is_ascii_digit() {
        j += 1;
        while j < n && ch(j).is_ascii_digit() {
            j += 1;
        }
    }
    let text: String = chars[i..j].iter().map(|x| x.1).collect();
    let v: f64 = text.parse().unwrap_or(0.0);
    if ch(j) == '%' {
        let t2: String = chars[i..j + 1].iter().map(|x| x.1).collect();
        return (Tok::Percent(v, t2), j + 1);
    }
    (Tok::Num(v, text), j)
}

// Link operators: [left end] line [right end].
fn lex_link_op(chars: &[(usize, char)], i: usize) -> Result<Option<(String, usize)>, Diag> {
    let n = chars.len();
    let ch = |k: usize| -> char { if k < n { chars[k].1 } else { '\0' } };
    let byte_at = |k: usize| -> usize { if k < n { chars[k].0 } else { chars.last().map(|x| x.0 + x.1.len_utf8()).unwrap_or(0) } };
    let mut j = i;
    // left end
    let c = ch(j);
    let mut left = String::new();
    match c {
        '<' | '*' => {
            left.push(c);
            j += 1;
        }
        '>' => {
            left.push(c);
            j += 1;
            if ch(j) == 'o' || ch(j) == '+' {
                left.push(ch(j));
                j += 1;
            }
        }
        '+' => {
            left.push(c);
            j += 1;
            if ch(j) == 'o' {
                left.push('o');
                j += 1;
            }
        }
        _ => {}
    }
    // line
    let line_start = j;
    if ch(j) == '-' {
        while ch(j) == '-' && j - line_start < 3 {
            j += 1;
        }
    } else if ch(j) == '~' {
        j += 1;
    }
    if j == line_start {
        if !left.is_empty() {
            let last = left.chars().last().unwrap();
            return Err(Diag::error(
                "bad-link-op",
                &format!("expected link-op line after '{}'", last),
                Span::new(byte_at(i), byte_at(j)),
            ));
        }
        return Ok(None);
    }
    // right end
    let mut right = String::new();
    match ch(j) {
        '>' | '*' => {
            right.push(ch(j));
            j += 1;
        }
        '<' => {
            right.push('<');
            j += 1;
        }
        '+' => {
            right.push('+');
            j += 1;
            if ch(j) == '<' {
                right.push('<');
                j += 1;
            }
        }
        'o' if ch(j + 1) == '<' || ch(j + 1) == '+' => {
            right.push('o');
            right.push(ch(j + 1));
            j += 2;
        }
        _ => {}
    }
    let line: String = chars[line_start..j - right.chars().count()].iter().map(|x| x.1).collect();
    Ok(Some((format!("{}{}{}", left, line, right), j)))
}
