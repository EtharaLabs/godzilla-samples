// Tokenizer for `lini fmt`. It mirrors the compiler's lexical rules (and its
// lexical errors) and keeps what the pretty-printer needs: exact source
// offsets, whether whitespace came before a token, and the comments and blank
// lines in front of each token.

use super::cst::Triv;
use crate::diag::{Diag, Span};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum K {
    Ident,
    Num,
    Percent,
    Str,
    Hash,
    Var,
    Dot,
    Bar,
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
    Eq,
    Amp,
    Math, // + - * / ^ ? < > <= >= == != && (only inside a group)
    Link, // link operator: -> <-> -o< ~> ...
    Dim,  // (-) (o) (<)
    Newline,
    Eof,
}

#[derive(Clone, Debug)]
pub struct Tok {
    pub k: K,
    pub s: usize,
    pub e: usize,
    pub sp: bool, // whitespace (or a line start) right before the token
    pub v: f64,
    // Ident / Hash (without '#') / Var (without '--') name, decoded string,
    // operator text, or the number's source text.
    pub text: String,
    // comments and blank lines between the previous token and this one
    pub pre: Vec<Triv>,
}

pub struct Lexed {
    pub toks: Vec<Tok>,
}

fn is_ident_start(c: char) -> bool {
    c.is_ascii_alphabetic() || c == '_'
}

fn is_ident_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '-'
}

pub const MATH_ERR: &str = "math operators appear inside ( ) — e.g. padding: (8 * 2)";

fn err(msg: &str, s: usize, e: usize) -> Diag {
    let family = if msg.starts_with("unterminated string") {
        "unterminated-string"
    } else if msg.contains("escape sequence") {
        "bad-escape"
    } else if msg.starts_with("unexpected character") {
        "unexpected-char"
    } else {
        "lex"
    };
    Diag::error(family, msg, Span::new(s, e))
}

pub fn lex(src: &str) -> Result<Lexed, Diag> {
    let cs: Vec<(usize, char)> = src.char_indices().collect();
    let n = cs.len();
    let at = |i: usize| -> char { if i < n { cs[i].1 } else { '\0' } };
    let off = |i: usize| -> usize { if i < n { cs[i].0 } else { src.len() } };
    let mut toks: Vec<Tok> = Vec::new();
    // a leading byte-order mark is skipped
    let mut i = if n > 0 && cs[0].1 == '\u{feff}' { 1 } else { 0 };
    let mut depth: usize = 0;
    let mut sp = true;
    let mut line_start = true;
    // a run of newlines yields one Newline token; a comment ends the run
    let mut in_nl_run = false;
    // trivia waiting for the next token, and where the last token or
    // comment ended (blank lines are counted from there)
    let mut pending: Vec<Triv> = Vec::new();
    let mut content_end = 0usize;
    let blank_between = |a: usize, b: usize| -> bool { src[a..b].matches('\n').count() >= 2 };
    while i < n {
        let c = at(i);
        match c {
            ' ' | '\t' | '\r' => {
                i += 1;
                sp = true;
                continue;
            }
            '\n' => {
                // inside ( ) a line break is plain whitespace
                if !in_nl_run && depth == 0 {
                    let pre = std::mem::take(&mut pending);
                    toks.push(Tok { k: K::Newline, s: off(i), e: off(i + 1), sp, v: 0.0, text: String::new(), pre });
                    in_nl_run = true;
                }
                i += 1;
                sp = true;
                line_start = true;
                continue;
            }
            '/' if at(i + 1) == '/' => {
                let mut j = i;
                while j < n && at(j) != '\n' {
                    j += 1;
                }
                let text: String = src[off(i)..off(j)].trim_end().to_string();
                if blank_between(content_end, off(i)) {
                    pending.push(Triv::Blank);
                }
                pending.push(Triv::Comment { text, own: line_start });
                content_end = off(j);
                in_nl_run = false;
                i = j;
                sp = true;
                continue;
            }
            _ => {}
        }
        line_start = false;
        in_nl_run = false;
        let start = i;
        let mut text = String::new();
        let mut v = 0.0;
        let k: K;
        if c == '"' {
            let mut s = String::new();
            let mut j = i + 1;
            loop {
                if j >= n {
                    return Err(err("unterminated string literal", off(i), src.len()));
                }
                let d = at(j);
                if d == '"' {
                    j += 1;
                    break;
                }
                if d == '\\' {
                    if j + 1 >= n {
                        return Err(err("unterminated escape sequence", off(j), off(j + 1)));
                    }
                    match at(j + 1) {
                        'n' => s.push('\n'),
                        't' => s.push('\t'),
                        '"' => s.push('"'),
                        '\\' => s.push('\\'),
                        e => {
                            // the message shows the byte after the backslash
                            let shown = if e.is_ascii() { e } else { char::from(src.as_bytes()[off(j + 1)]) };
                            return Err(err(
                                &format!("invalid escape sequence '\\{}'", shown),
                                off(j),
                                off(j + 2),
                            ));
                        }
                    }
                    j += 2;
                    continue;
                }
                s.push(d);
                j += 1;
            }
            k = K::Str;
            text = s;
            i = j;
        } else if c == '\'' {
            return Err(err("single quotes are not strings — use \"…\"", off(i), off(i + 1)));
        } else if c.is_ascii_digit() && depth == 0 && after_path_dot(&toks, sp) {
            // a copy index: `a.2` (digits only)
            let mut j = i;
            while at(j).is_ascii_digit() {
                j += 1;
            }
            k = K::Num;
            text = src[off(i)..off(j)].to_string();
            v = text.parse().unwrap_or(0.0);
            i = j;
        } else if c.is_ascii_digit() || (c == '.' && at(i + 1).is_ascii_digit() && !(depth == 0 && glued_to_ident(&toks, sp))) {
            let (kk, j, val) = lex_number(&cs, i, depth > 0);
            k = kk;
            v = val;
            text = src[off(i)..off(j)].to_string();
            i = j;
        } else if (c == '-' || c == '+')
            && (at(i + 1).is_ascii_digit() || (at(i + 1) == '.' && at(i + 2).is_ascii_digit()))
        {
            let (kk, j, val) = lex_number(&cs, i + 1, depth > 0);
            k = kk;
            v = if c == '-' { -val } else { val };
            text = src[off(i)..off(j)].to_string();
            i = j;
        } else if is_ident_start(c) {
            let mut j = i;
            while j < n && is_ident_char(at(j)) {
                j += 1;
            }
            k = K::Ident;
            text = src[off(i)..off(j)].to_string();
            i = j;
        } else if c == '#' {
            let mut j = i + 1;
            while j < n && is_ident_char(at(j)) {
                j += 1;
            }
            k = K::Hash;
            text = src[off(i + 1)..off(j)].to_string();
            i = j;
        } else if c == '-' && at(i + 1) == '-' && is_ident_start(at(i + 2)) {
            let mut j = i + 2;
            while j < n && is_ident_char(at(j)) {
                j += 1;
            }
            k = K::Var;
            text = src[off(i + 2)..off(j)].to_string();
            i = j;
        } else if c == '.' {
            k = K::Dot;
            i += 1;
        } else if c == '|' {
            // '||' is two bars; the parser reads glued bars as the operator
            k = K::Bar;
            i += 1;
        } else if c == '{' {
            k = K::LBrace;
            i += 1;
        } else if c == '}' {
            k = K::RBrace;
            i += 1;
        } else if c == '[' {
            k = K::LBrack;
            i += 1;
        } else if c == ']' {
            k = K::RBrack;
            i += 1;
        } else if c == '(' {
            let c1 = at(i + 1);
            // `(-)`, `(o)`, `(<)` are dimension operators unless the paren
            // belongs to what it touches
            let call_paren = !sp
                && matches!(
                    toks.last().map(|t| t.k),
                    Some(K::Ident | K::Num | K::Percent | K::Str | K::Hash | K::Var | K::RParen)
                );
            if !call_paren && at(i + 2) == ')' && (c1 == '-' || c1 == 'o' || c1 == '<') {
                k = K::Dim;
                text = format!("({})", c1);
                i += 3;
            } else if !call_paren && at(i + 2) == ')' && c1 == '>' {
                return Err(err("'(>)' is reserved — the angle op is '(<)'", off(i), off(i + 3)));
            } else {
                depth += 1;
                k = K::LParen;
                i += 1;
            }
        } else if c == ')' {
            depth = depth.saturating_sub(1);
            k = K::RParen;
            i += 1;
        } else if c == ';' {
            k = K::Semi;
            i += 1;
        } else if c == ',' {
            k = K::Comma;
            i += 1;
        } else if c == ':' {
            if at(i + 1) == ':' {
                k = K::DColon;
                i += 2;
            } else {
                k = K::Colon;
                i += 1;
            }
        } else if c == '&' {
            if depth > 0 && at(i + 1) == '&' {
                k = K::Math;
                text = "&&".into();
                i += 2;
            } else {
                k = K::Amp;
                i += 1;
            }
        } else if c == '=' {
            if at(i + 1) == '=' && depth > 0 {
                k = K::Math;
                text = "==".into();
                i += 2;
            } else {
                k = K::Eq;
                i += 1;
            }
        } else if c == '!' && at(i + 1) == '=' {
            k = K::Math;
            text = "!=".into();
            i += 2;
        } else if depth > 0 && "+-*/^?<>!".contains(c) {
            let two: String = [c, at(i + 1)].iter().collect();
            if two == "<=" || two == ">=" || two == "!=" {
                k = K::Math;
                text = two;
                i += 2;
            } else if c == '!' {
                return Err(err(&format!("unexpected character '{}'", c.escape_debug()), off(i), off(i + 1)));
            } else {
                k = K::Math;
                text = c.to_string();
                i += 1;
            }
        } else if "-<>~+*".contains(c) {
            match lex_link_op(&cs, i, src)? {
                Some(j) => {
                    k = K::Link;
                    text = src[off(i)..off(j)].to_string();
                    i = j;
                }
                None => {
                    // only '*' falls through: math outside a group
                    return Err(err(MATH_ERR, off(i), off(i + 1)));
                }
            }
        } else if c == '/' || c == '^' {
            return Err(err(MATH_ERR, off(i), off(i + 1)));
        } else {
            return Err(err(&format!("unexpected character '{}'", c.escape_debug()), off(i), off(i + 1)));
        }
        if blank_between(content_end, off(start)) {
            pending.push(Triv::Blank);
        }
        let pre = std::mem::take(&mut pending);
        content_end = off(i);
        toks.push(Tok { k, s: off(start), e: off(i), sp, v, text, pre });
        sp = false;
    }
    if blank_between(content_end, src.len()) {
        pending.push(Triv::Blank);
    }
    // the end-of-input token reports at the last real token
    let (s, e) = match toks.last() {
        Some(t) => (t.s, t.e),
        None => (0, 0),
    };
    toks.push(Tok { k: K::Eof, s, e, sp: true, v: 0.0, text: String::new(), pre: pending });
    Ok(Lexed { toks })
}

// '.5' right after a word ('a.5') is a path index, not a number
fn glued_to_ident(toks: &[Tok], sp: bool) -> bool {
    !sp && matches!(toks.last().map(|t| t.k), Some(K::Ident))
}

// right after `name.` (no spaces)
fn after_path_dot(toks: &[Tok], sp: bool) -> bool {
    if sp || toks.len() < 2 {
        return false;
    }
    let (a, b) = (&toks[toks.len() - 2], &toks[toks.len() - 1]);
    b.k == K::Dot && !b.sp && a.k == K::Ident
}

// digits ['.' digits] | '.' digits, then an optional '%'. Inside ( ) an
// exponent may follow: 1e3, 2.5E-2.
fn lex_number(cs: &[(usize, char)], digits_at: usize, exp: bool) -> (K, usize, f64) {
    let n = cs.len();
    let at = |k: usize| -> char { if k < n { cs[k].1 } else { '\0' } };
    let mut j = digits_at;
    let mut body = String::new();
    while at(j).is_ascii_digit() {
        body.push(at(j));
        j += 1;
    }
    if at(j) == '.' && at(j + 1).is_ascii_digit() {
        body.push('.');
        j += 1;
        while at(j).is_ascii_digit() {
            body.push(at(j));
            j += 1;
        }
    }
    if exp && (at(j) == 'e' || at(j) == 'E') {
        let mut k = j + 1;
        let mut e = String::from("e");
        if at(k) == '+' || at(k) == '-' {
            e.push(at(k));
            k += 1;
        }
        if at(k).is_ascii_digit() {
            while at(k).is_ascii_digit() {
                e.push(at(k));
                k += 1;
            }
            body.push_str(&e);
            j = k;
        }
    }
    let v: f64 = body.parse().unwrap_or(0.0);
    if at(j) == '%' {
        return (K::Percent, j + 1, v);
    }
    (K::Num, j, v)
}

// Link operators: [left end] line [right end]. Returns the end index, or None
// when a lone '*' is not followed by a line.
fn lex_link_op(cs: &[(usize, char)], i: usize, src: &str) -> Result<Option<usize>, Diag> {
    let n = cs.len();
    let at = |k: usize| -> char { if k < n { cs[k].1 } else { '\0' } };
    let off = |k: usize| -> usize { if k < n { cs[k].0 } else { src.len() } };
    let mut j = i;
    let mut left = String::new();
    match at(j) {
        '<' | '*' => {
            left.push(at(j));
            j += 1;
            if left == "<" && at(j) == '>' {
                left.push('>');
                j += 1;
            }
        }
        '>' => {
            left.push('>');
            j += 1;
            if at(j) == 'o' || at(j) == '+' {
                left.push(at(j));
                j += 1;
            }
        }
        '+' => {
            left.push('+');
            j += 1;
            if at(j) == 'o' || at(j) == '+' {
                left.push(at(j));
                j += 1;
            }
        }
        _ => {}
    }
    let line_start = j;
    // `--name` is a variable, not a line
    let var_next = at(j) == '-' && at(j + 1) == '-' && is_ident_start(at(j + 2));
    if at(j) == '-' && !var_next {
        while at(j) == '-' && j - line_start < 3 {
            j += 1;
        }
    } else if at(j) == '~' {
        j += 1;
    }
    if j == line_start {
        if left == "*" && at(line_start) != '-' {
            return Ok(None);
        }
        return Err(err(&format!("expected link-op line after '{}'", left), off(i), off(j)));
    }
    let line_end = j;
    match at(j) {
        '>' | '*' => {
            j += 1;
        }
        '<' => {
            j += 1;
            if at(j) == '>' {
                j += 1;
            }
        }
        '+' => {
            j += 1;
            if at(j) == '<' || at(j) == '+' {
                j += 1;
            }
        }
        'o' => {
            if at(j + 1) == '<' || at(j + 1) == '+' {
                j += 2;
            } else {
                return Err(err(
                    "'-o' needs a max glyph — write '-o<' or '-o+'; the hollow ring is an ER component only",
                    off(line_end - 1),
                    off(line_end + 1),
                ));
            }
        }
        _ => {}
    }
    Ok(Some(j))
}
