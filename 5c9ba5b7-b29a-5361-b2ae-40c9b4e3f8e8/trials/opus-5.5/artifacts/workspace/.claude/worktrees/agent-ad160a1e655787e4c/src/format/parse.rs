// Recursive-descent parser for `lini fmt`. It follows the compiler's grammar
// (and its error messages) and builds the concrete tree the printer walks.

use super::cst::*;
use super::expr;
use super::lex::{Tok, K};
use crate::diag::{Diag, Span};
use std::collections::{HashMap, HashSet};

type R<T> = Result<T, Diag>;

pub const SEP_ERR: &str = "expected a newline, ';', or a closing bracket";
const NODE_ERR: &str = "a node leads with bars — write '|box#X|' (a bare name is a link endpoint)";
use super::lex::MATH_ERR;
const GROUP_ERR: &str = "to compute here, wrap the math in a group — e.g. (a - b)";
const LABEL_FIRST: &str = "a label comes before classes — write '|box| \"X\" .hot'";
const CLASS_GLUE: &str = "classes glue into a chain — write '.hot.loud', no space";
const ONE_LABEL: &str = "one inline label — put two or more in a '[ ]'";
const CLASS_FIRST: &str = "a class comes before the style block — write '|box| .hot { … }'";

fn perr(msg: &str, t: &Tok) -> Diag {
    Diag::error(family_of(msg), msg, Span::new(t.s, t.e))
}

// the diagnostic family (and so the code) a parse message belongs to
pub fn family_of(msg: &str) -> &'static str {
    if msg.starts_with("expected ") {
        "expected-token"
    } else if msg.starts_with("'| |' needs") {
        "empty-bars"
    } else if msg.contains("is not a valid id") {
        "invalid-id"
    } else if msg.starts_with("a declaration belongs in") {
        "declaration-outside-block"
    } else if msg.starts_with("the stylesheet '{ }' must come first") {
        "stylesheet-after-canvas"
    } else if msg.starts_with("text content takes no") {
        "text-carries-children"
    } else if msg.starts_with("a call's '('") {
        "spaced-call-paren"
    } else {
        "parse"
    }
}

struct Term {
    text: String,
    call: bool,
    tracks: i64,      // grid tracks this term stands for in `columns:`
    num: Option<f64>, // a plain number literal
}

#[derive(Clone, Copy, PartialEq)]
enum Ctx {
    Top,
    Children,
    Define,
    Labels,
}

pub struct Parser<'a> {
    src: &'a str,
    toks: &'a [Tok],
    pos: usize,
    defines: Vec<(String, String)>,
    // how deep inside '[ ]' blocks the parser is
    brackets: usize,
}

pub fn render_number(v: f64) -> String {
    if v == 0.0 {
        return "0".to_string();
    }
    format!("{}", v)
}

pub fn render_string(s: &str) -> String {
    let t = s.trim();
    let mut o = String::with_capacity(t.len() + 2);
    o.push('"');
    for c in t.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\t' => o.push_str("\\t"),
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

impl<'a> Parser<'a> {
    pub fn new(src: &'a str, toks: &'a [Tok]) -> Self {
        Parser { src, toks, pos: 0, defines: Vec::new(), brackets: 0 }
    }

    fn peek(&self) -> K {
        self.toks[self.pos].k
    }
    fn peek_at(&self, k: usize) -> K {
        let i = (self.pos + k).min(self.toks.len() - 1);
        self.toks[i].k
    }
    fn tok(&self) -> &Tok {
        &self.toks[self.pos]
    }
    fn tok_at(&self, k: usize) -> &Tok {
        let i = (self.pos + k).min(self.toks.len() - 1);
        &self.toks[i]
    }
    fn bump(&mut self) -> Tok {
        let t = self.toks[self.pos].clone();
        if self.pos < self.toks.len() - 1 {
            self.pos += 1;
        }
        t
    }
    // end offset of the last consumed token
    fn last_end(&self) -> usize {
        if self.pos == 0 {
            0
        } else {
            self.toks[self.pos - 1].e
        }
    }
    fn skip_newlines(&mut self) {
        while self.peek() == K::Newline {
            self.bump();
        }
    }
    fn err_here(&self, msg: &str) -> Diag {
        perr(msg, self.tok())
    }
    fn decl_msg(&self) -> &'static str {
        if self.brackets > 0 {
            "declarations go in '{ }', not '[ ]'"
        } else {
            "a declaration belongs in a '{ }' block"
        }
    }
    // two glued bars: the '||' (flush) operator
    fn at_barbar(&self) -> bool {
        self.peek() == K::Bar && self.peek_at(1) == K::Bar && !self.tok_at(1).sp
    }

    // ------------------------------------------------------------- trivia
    // Trivia rides on tokens (`Tok::pre`). An entry's leading trivia is all
    // the trivia from just after the previous entry's last token up to and
    // including its own first token; what falls inside an entry stays there.
    fn trivia_range(&self, after: Option<usize>, upto: usize) -> Vec<Triv> {
        let from = match after {
            Some(a) => a + 1,
            None => 0,
        };
        let mut out = Vec::new();
        for k in from..=upto.min(self.toks.len() - 1) {
            out.extend(self.toks[k].pre.iter().cloned());
        }
        out
    }

    fn any_trivia(&self, after: usize, upto: usize) -> bool {
        (after + 1..=upto.min(self.toks.len() - 1)).any(|k| !self.toks[k].pre.is_empty())
    }

    fn any_comment(&self, after: usize, upto: usize) -> bool {
        (after + 1..=upto.min(self.toks.len() - 1))
            .any(|k| self.toks[k].pre.iter().any(|t| matches!(t, Triv::Comment { .. })))
    }

    // items: (first token, last token, item)
    fn build_block<T>(&self, open: Option<usize>, items: Vec<(usize, usize, T)>, close: usize) -> Block<T> {
        let inside = self.trivia_range(open, close);
        let any_trivia = !inside.is_empty();
        let any_comment = inside.iter().any(|t| matches!(t, Triv::Comment { .. }));
        let trivia_among = match (items.first(), items.last()) {
            (Some(f), Some(l)) => self.any_trivia(f.0, l.1),
            _ => false,
        };
        let mut entries: Vec<Entry<T>> = Vec::new();
        let mut prev = open;
        for (f, l, item) in items {
            let lead = self.trivia_range(prev, f);
            entries.push(Entry { lead, item });
            prev = Some(l);
        }
        let close = self.trivia_range(prev, close);
        Block { entries, close, any_trivia, any_comment, trivia_among }
    }

    // ------------------------------------------------------------ document
    pub fn parse_doc(&mut self) -> R<Doc> {
        self.skip_newlines();
        let mut items: Vec<(usize, usize, Option<Stmt>)> = Vec::new();
        let mut sheet = None;
        if self.peek() == K::LBrace {
            let f = self.pos;
            let b = self.parse_sheet()?;
            sheet = Some(b);
            items.push((f, self.pos - 1, None));
        }
        loop {
            self.skip_newlines();
            if self.peek() == K::Eof {
                break;
            }
            if self.peek() == K::LBrace {
                return Err(Diag::error(
                    "stylesheet-after-canvas",
                    "the stylesheet '{ }' must come first, before any instance",
                    Span::new(self.tok().s, self.tok().e),
                ));
            }
            let f = self.pos;
            let st = self.parse_stmt(Ctx::Top)?;
            items.push((f, self.pos - 1, Some(st)));
            self.after_stmt()?;
        }
        let eof = self.pos;
        let blk = self.build_block(None, items, eof);
        let mut entries = blk.entries.into_iter();
        let mut sheet_lead = Vec::new();
        let mut stmts = Vec::new();
        if sheet.is_some() {
            let e = entries.next().unwrap();
            sheet_lead = e.lead;
        }
        for e in entries {
            stmts.push(Entry { lead: e.lead, item: e.item.unwrap() });
        }
        let stmts = Block {
            entries: stmts,
            close: blk.close,
            any_trivia: blk.any_trivia,
            any_comment: blk.any_comment,
            trivia_among: blk.trivia_among,
        };
        let types = resolve_types(&self.defines);
        Ok(Doc { sheet, sheet_lead, stmts, types })
    }

    // separator after a statement: ';' (then more may follow on the line),
    // a newline, a closing bracket, or the end; bare strings share a line
    fn after_stmt(&mut self) -> R<()> {
        match self.peek() {
            K::Semi => {
                self.bump();
                Ok(())
            }
            K::Newline | K::Eof | K::RBrack | K::RBrace => Ok(()),
            K::Str => Ok(()),
            _ => Err(self.err_here(SEP_ERR)),
        }
    }

    // ------------------------------------------------------------- sheet
    fn parse_sheet(&mut self) -> R<Block<SheetItem>> {
        let open_idx = self.pos;
        self.bump();
        let mut items = Vec::new();
        loop {
            self.skip_newlines();
            match self.peek() {
                K::RBrace => break,
                K::Eof => return Err(self.err_here("expected '}'")),
                _ => {}
            }
            let f = self.pos;
            let (item, l) = self.parse_sheet_item()?;
            items.push((f, l, item));
            if self.toks[self.pos - 1].k == K::Semi {
                continue;
            }
            match self.peek() {
                K::Semi => {
                    self.bump();
                }
                K::Newline | K::RBrace | K::Str => {}
                K::Eof => {}
                _ => return Err(self.err_here(SEP_ERR)),
            }
        }
        let close = self.pos;
        self.bump();
        Ok(self.build_block(Some(open_idx), items, close))
    }

    // -> (item, index of its last token; a closing ';' is not part of it)
    fn parse_sheet_item(&mut self) -> R<(SheetItem, usize)> {
        match self.peek() {
            K::Var => {
                let t = self.bump();
                if self.peek() != K::Colon {
                    return Err(self.err_here(&format!("expected ':' after '--{}'", t.text)));
                }
                self.bump();
                let (d, l) = self.parse_decl_rest(format!("--{}", t.text))?;
                Ok((SheetItem::Var(d), l))
            }
            K::Ident => match self.peek_at(1) {
                K::Colon => {
                    let (d, l) = self.parse_decl()?;
                    Ok((SheetItem::Decl(d), l))
                }
                K::Eq => self.parse_binding(),
                K::LParen => self.parse_binding(),
                _ => Err(self.err_here("a type only appears in bars — write '|box| { }' to style every box")),
            },
            K::Bar | K::Dot | K::Hash | K::Dim => {
                let it = self.parse_rule_or_define()?;
                Ok((it, self.pos - 1))
            }
            K::Link => Err(self.err_here(
                "'->' draws a link on the canvas — style every link with '|-| { stroke: … }' in a '{ }' block",
            )),
            _ => Err(self.err_here("the stylesheet holds declarations, rules, and defines")),
        }
    }

    fn parse_binding(&mut self) -> R<(SheetItem, usize)> {
        let name = self.bump().text;
        let mut params: Option<Vec<String>> = None;
        if self.peek() == K::LParen {
            self.bump();
            let mut ps = Vec::new();
            loop {
                match self.peek() {
                    K::Ident => {
                        ps.push(self.bump().text);
                    }
                    K::RParen if ps.is_empty() => {}
                    _ => return Err(self.err_here("expected identifier")),
                }
                match self.peek() {
                    K::Comma => {
                        self.bump();
                    }
                    K::RParen => {
                        self.bump();
                        break;
                    }
                    _ => return Err(self.err_here("expected ')'")),
                }
            }
            params = Some(ps);
        }
        if self.peek() != K::Eq {
            return Err(self.err_here("expected '=' — a binding is 'name = value'"));
        }
        self.bump();
        let rhs = self.parse_binding_rhs()?;
        let last = self.pos - 1;
        if self.peek() == K::Semi {
            self.bump();
        }
        let head = match params {
            Some(ps) if !ps.is_empty() => format!("{}({})", name, ps.join(", ")),
            _ => name,
        };
        Ok((SheetItem::Binding(format!("{} = {};", head, rhs)), last))
    }

    fn parse_binding_rhs(&mut self) -> R<String> {
        match self.peek() {
            K::Semi | K::Newline | K::RBrace | K::Eof => {
                return Err(self.err_here("a binding needs a value — 'name = value'"));
            }
            _ => {}
        }
        if self.peek() == K::LParen {
            let open = self.bump();
            let close_end = self.skip_group(&open)?;
            match self.peek() {
                K::Semi | K::Newline | K::RBrace | K::Eof | K::Str => {}
                _ => return Err(self.err_here(SEP_ERR)),
            }
            let inner = self.src[open.e..close_end - 1].trim();
            return Ok(expr::binding_group(inner));
        }
        let start = self.tok().s;
        let mut end = start;
        let mut depth = 0usize;
        loop {
            match self.peek() {
                K::Semi | K::Eof => break,
                K::Newline | K::RBrace if depth == 0 => break,
                K::Math if depth == 0 && self.tok().text != "!=" => return Err(self.err_here(MATH_ERR)),
                K::LParen => depth += 1,
                K::RParen => depth = depth.saturating_sub(1),
                _ => {}
            }
            end = self.bump().e;
        }
        let text = &self.src[start..end];
        Ok(expr::binding_bare(text))
    }

    fn parse_rule_or_define(&mut self) -> R<SheetItem> {
        // define: |name::base|
        if self.peek() == K::Bar
            && ((self.peek_at(1) == K::Ident && self.peek_at(2) == K::DColon) || self.peek_at(1) == K::DColon)
        {
            self.bump();
            if self.peek() == K::DColon {
                return Err(self.err_here("'| |' needs a type or an '#id'"));
            }
            let name = self.bump().text;
            self.bump(); // ::
            if self.peek() != K::Ident {
                return Err(self.err_here("expected identifier"));
            }
            let base = self.bump().text;
            if self.peek() != K::Bar {
                return Err(self.err_here("expected '|'"));
            }
            self.bump();
            self.defines.push((name.clone(), base.clone()));
            let mut style = None;
            let mut anchor = self.pos - 1;
            if self.peek() == K::LBrace {
                let before = self.pos - 1;
                let b = self.parse_style_block()?;
                anchor = if b.entries.is_empty() { before } else { self.pos - 1 };
                style = Some(b);
            }
            let body = if self.peek() == K::LBrack {
                self.parse_children(Ctx::Define, Some(anchor))?
            } else {
                // no body: a comment left in an empty style block still
                // brings one into being
                let end = self.pos - 1;
                Block {
                    entries: Vec::new(),
                    close: self.trivia_range(Some(anchor), end),
                    any_trivia: self.any_trivia(anchor, end),
                    any_comment: self.any_comment(anchor, end),
                    trivia_among: false,
                }
            };
            let style = style.filter(|b| !b.entries.is_empty());
            let body = if !body.entries.is_empty() || body.close.iter().any(|t| matches!(t, Triv::Comment { .. })) {
                Some(body)
            } else {
                None
            };
            return Ok(SheetItem::Define { head: format!("|{}::{}|", name, base), style, body });
        }
        let mut parts: Vec<String> = Vec::new();
        loop {
            match self.peek() {
                K::LBrace => break,
                K::Bar => {
                    parts.push(self.parse_selector_bars()?);
                }
                K::Dot => {
                    self.bump();
                    if self.peek() != K::Ident {
                        return Err(self.err_here("expected identifier"));
                    }
                    parts.push(format!(".{}", self.bump().text));
                }
                K::Hash => {
                    let h = self.bump();
                    if !valid_id(&h.text) {
                        return Err(perr(&format!("'#{}' is not a valid id — an id starts with a letter or '_'", h.text), &h));
                    }
                    parts.push(format!("#{}", h.text));
                }
                K::Dim if !parts.is_empty() && self.tok().text != "(-)" => {
                    return Err(self.err_here("expected '{'"))
                }
                K::Dim => {
                    let t = self.bump();
                    if t.text != "(-)" {
                        return Err(perr(
                            "'(-)' selects every dimension — per-kind '(o)' / '(<)' selectors are deferred (SPEC 24)",
                            &t,
                        ));
                    }
                    parts.push(t.text);
                }
                _ => return Err(self.err_here("expected '{'")),
            }
        }
        let block = self.parse_style_block()?;
        Ok(SheetItem::Rule { selector: parts.join(" "), block })
    }

    fn parse_selector_bars(&mut self) -> R<String> {
        self.bump();
        let mut ty = None;
        if self.peek() == K::Dot {
            return Err(self.err_here(
                "a selector unit can't glue a type and a class — space them (descendant) or style '.hot'",
            ));
        }
        match self.peek() {
            K::Ident => ty = Some(self.bump().text),
            K::Link if self.tok().text == "-" && self.peek_at(1) == K::Bar => {
                self.bump();
                ty = Some("-".to_string());
            }
            _ => {}
        }
        let mut id = None;
        if self.peek() == K::Hash && !(ty.is_some() && self.tok().sp) {
            let h = self.bump();
            if !valid_id(&h.text) {
                return Err(perr(&format!("'#{}' is not a valid id — an id starts with a letter or '_'", h.text), &h));
            }
            id = Some(h.text);
        }
        if ty.is_none() && id.is_none() {
            return Err(self.err_here("'| |' needs a type or an '#id'"));
        }
        if self.peek() == K::Dot && !self.tok().sp {
            return Err(self.err_here(
                "a selector unit can't glue a type and a class — space them (descendant) or style '.hot'",
            ));
        }
        if self.peek() != K::Bar {
            return Err(self.err_here("expected '|'"));
        }
        self.bump();
        let mut s = String::from("|");
        if let Some(t) = ty {
            s.push_str(&t);
        }
        if let Some(i) = id {
            s.push('#');
            s.push_str(&i);
        }
        s.push('|');
        Ok(s)
    }

    // ------------------------------------------------------- style blocks
    fn parse_style_block(&mut self) -> R<Block<Decl>> {
        let open_idx = self.pos;
        self.bump(); // {
        let mut items = Vec::new();
        loop {
            self.skip_newlines();
            match self.peek() {
                K::RBrace => break,
                K::Eof => return Err(self.err_here("expected '}'")),
                K::Ident if self.peek_at(1) == K::Colon => {
                    let f = self.pos;
                    let (d, l) = self.parse_decl()?;
                    items.push((f, l, d));
                }
                _ => return Err(self.err_here("a '{ }' style block holds only declarations")),
            }
        }
        let close = self.pos;
        self.bump();
        Ok(self.build_block(Some(open_idx), items, close))
    }

    fn parse_decl(&mut self) -> R<(Decl, usize)> {
        let t = self.bump();
        self.bump(); // ':'
        self.parse_decl_rest(t.text.clone())
    }

    // after 'name:' — the value, then ';' or a closing '}'. Returns the
    // declaration and its last token (the value's; the ';' stands apart).
    fn parse_decl_rest(&mut self, name: String) -> R<(Decl, usize)> {
        let draw = name == "draw";
        let (groups, tracks) = self.parse_value(draw)?;
        let last = self.pos - 1;
        match self.peek() {
            K::Semi => {
                self.bump();
            }
            K::Colon => return Err(self.err_here("a declaration ends with ';'")),
            _ => {}
        }
        Ok((Decl { name, groups, draw, tracks }, last))
    }

    fn parse_value(&mut self, draw: bool) -> R<(Vec<Vec<String>>, i64)> {
        let mut groups: Vec<Vec<String>> = vec![Vec::new()];
        let mut any = false;
        let mut prev_call = false;
        let mut tracks: i64 = 0;
        loop {
            self.skip_newlines();
            match self.peek() {
                K::Semi | K::RBrace | K::RBrack | K::Eof => break,
                K::Comma => {
                    self.bump();
                    groups.push(Vec::new());
                    prev_call = false;
                    continue;
                }
                K::Colon => {
                    if draw && self.peek_at(1) == K::Ident && !self.tok_at(1).sp {
                        let glued = prev_call && !self.tok().sp;
                        if !glued {
                            return Err(self.err_here("a ':segment' glues to its call — name a station with point():v"));
                        }
                        self.bump();
                        let tag = self.bump().text;
                        let g = groups.last_mut().unwrap();
                        let last = g.pop().unwrap();
                        g.push(format!("{}:{}", last, tag));
                        prev_call = false;
                        continue;
                    }
                    break;
                }
                _ => {}
            }
            let term = self.parse_term()?;
            groups.last_mut().unwrap().push(term.text);
            any = true;
            prev_call = term.call;
            tracks += term.tracks;
        }
        if !any && self.peek() != K::Colon {
            return Err(self.err_here("declaration needs a value"));
        }
        Ok((groups, tracks))
    }

    // one value term, rendered canonically
    fn parse_term(&mut self) -> R<Term> {
        let t = self.tok().clone();
        let plain = |text: String| Term { text, call: false, tracks: 1, num: None };
        match t.k {
            K::Num => {
                self.bump();
                Ok(Term { text: render_number(t.v), call: false, tracks: 1, num: Some(t.v) })
            }
            K::Percent => {
                self.bump();
                Ok(plain(format!("{}%", render_number(t.v))))
            }
            K::Str => {
                self.bump();
                Ok(plain(render_string(&t.text)))
            }
            K::Hash => {
                self.bump();
                let n = t.text.len();
                if !matches!(n, 3 | 4 | 6 | 8) || !t.text.chars().all(|c| c.is_ascii_hexdigit()) {
                    return Err(perr(&format!("invalid hex color '#{}'", t.text), &t));
                }
                Ok(plain(format!("#{}", t.text)))
            }
            K::Var => {
                self.bump();
                Ok(plain(format!("--{}", t.text)))
            }
            K::Ident => {
                self.bump();
                if self.peek() == K::LParen && self.tok().sp && FUNCTIONS.contains(&t.text.as_str()) {
                    return Err(self.err_here("a call's '(' glues to its name — write 'rgb(…)'"));
                }
                if self.peek() == K::LParen && !self.tok().sp {
                    let open = self.bump();
                    let (args, first_num) = self.parse_call_args(&open)?;
                    let mut tracks = 1;
                    if t.text == "repeat" {
                        if let Some(v) = first_num {
                            if v.is_nan() || v < 1.0 {
                                tracks = 1;
                            } else if v.is_infinite() || v > 1e15 {
                                tracks = 1_000_000_000_000_000;
                            } else {
                                tracks = v.trunc() as i64;
                            }
                        }
                    }
                    return Ok(Term { text: format!("{}({})", t.text, args.join(", ")), call: true, tracks, num: None });
                }
                Ok(plain(t.text.clone()))
            }
            K::LParen => {
                let open = self.bump();
                let close_end = self.skip_group(&open)?;
                let inner = self.src[open.e..close_end - 1].trim();
                Ok(plain(format!("({})", inner)))
            }
            K::Link => Err(perr(GROUP_ERR, &t)),
            K::Math => {
                if t.text == "-" || t.text == "+" {
                    Err(perr(GROUP_ERR, &t))
                } else if t.text == "!=" {
                    Err(perr("expected a value", &t))
                } else {
                    Err(perr(MATH_ERR, &t))
                }
            }
            _ => Err(perr("expected a value", &t)),
        }
    }

    // skip a '( … )' group (the '(' already consumed); returns the end
    // offset of the matching ')'
    fn skip_group(&mut self, open: &Tok) -> R<usize> {
        let mut depth = 1usize;
        loop {
            match self.peek() {
                K::Eof => {
                    return Err(perr("unterminated '(' group", open));
                }
                K::LParen => depth += 1,
                K::RParen => {
                    depth -= 1;
                    if depth == 0 {
                        return Ok(self.bump().e);
                    }
                }
                _ => {}
            }
            self.bump();
        }
    }

    // call arguments after '(' : comma-separated groups of terms. Once an
    // operator shows up, the rest of that group is kept verbatim; otherwise
    // each term is rendered (a lone '( … )' group sheds its parens).
    fn parse_call_args(&mut self, _open: &Tok) -> R<(Vec<String>, Option<f64>)> {
        let mut args: Vec<String> = Vec::new();
        // (rendered, start, end, is_group)
        let mut cur: Vec<(String, usize, usize, bool)> = Vec::new();
        let mut first_num: Option<f64> = None;
        loop {
            self.skip_newlines();
            if cur.is_empty() && self.arg_has_op() {
                // an operator anywhere in the argument: keep it verbatim
                let start = self.tok().s;
                let mut end = start;
                let mut depth = 0usize;
                loop {
                    match self.peek() {
                        K::Eof => return Err(self.err_here("expected ')'")),
                        K::LParen => depth += 1,
                        K::RParen if depth == 0 => break,
                        K::RParen => depth -= 1,
                        K::Comma if depth == 0 => break,
                        K::Newline => {
                            self.bump();
                            continue;
                        }
                        _ => {}
                    }
                    end = self.bump().e;
                }
                if args.is_empty() {
                    first_num = None;
                }
                args.push(self.src[start..end].to_string());
                if self.peek() == K::Comma {
                    self.bump();
                    continue;
                }
                self.bump(); // ')'
                return Ok((args, first_num));
            }
            let t = self.tok().clone();
            match t.k {
                K::RParen if !(cur.is_empty() && !args.is_empty()) => {
                    self.bump();
                    if !cur.is_empty() {
                        if args.is_empty() {
                            first_num = single_num(&cur, first_num);
                        }
                        args.push(self.finish_arg(&mut cur));
                    }
                    return Ok((args, first_num));
                }
                K::Comma if !cur.is_empty() => {
                    self.bump();
                    if args.is_empty() {
                        first_num = single_num(&cur, first_num);
                    }
                    args.push(self.finish_arg(&mut cur));
                    continue;
                }
                K::Eof if !cur.is_empty() => return Err(self.err_here("expected ')'")),
                K::Colon => return Err(perr("a declaration ends with ';'", &t)),
                _ => {}
            }
            let s = t.s;
            let is_group = t.k == K::LParen;
            let term = self.parse_term()?;
            let e = self.last_end();
            if args.is_empty() && cur.is_empty() {
                first_num = term.num;
            }
            cur.push((term.text, s, e, is_group));
        }
    }

    // does the argument starting here hold an operator at its own level?
    fn arg_has_op(&self) -> bool {
        let mut depth = 0usize;
        for t in &self.toks[self.pos..] {
            match t.k {
                K::Eof => return false,
                K::LParen => depth += 1,
                K::RParen if depth == 0 => return false,
                K::RParen => depth -= 1,
                K::Comma if depth == 0 => return false,
                K::Math | K::Eq if depth == 0 => return true,
                _ => {}
            }
        }
        false
    }

    fn finish_arg(&self, cur: &mut Vec<(String, usize, usize, bool)>) -> String {
        let out = if cur.len() == 1 && cur[0].3 {
            let (s, e) = (cur[0].1, cur[0].2);
            self.src[s + 1..e - 1].trim().to_string()
        } else {
            cur.iter().map(|x| x.0.clone()).collect::<Vec<_>>().join(" ")
        };
        cur.clear();
        out
    }

    // ----------------------------------------------------------- statements
    // `anchor`: where leading trivia starts counting (the '[' itself unless an
    // empty style block before it was dropped)
    fn parse_children(&mut self, ctx: Ctx, anchor: Option<usize>) -> R<Block<Stmt>> {
        let open_idx = anchor.unwrap_or(self.pos);
        self.bump(); // [
        let mut items = Vec::new();
        loop {
            self.skip_newlines();
            match self.peek() {
                K::RBrack => break,
                K::Eof if ctx != Ctx::Labels => return Err(self.err_here("expected ']'")),
                _ => {}
            }
            let f = self.pos;
            self.brackets += 1;
            let st = self.parse_stmt(ctx);
            self.brackets -= 1;
            let st = st?;
            items.push((f, self.pos - 1, st));
            if ctx == Ctx::Labels {
                // labels and annotation nodes may share a line
                match self.peek() {
                    K::Newline | K::RBrack | K::RBrace | K::Str | K::Bar => {}
                    _ => return Err(self.err_here("a link's '[ ]' holds labels (text) and annotation nodes")),
                }
                continue;
            }
            self.after_stmt()?;
        }
        let close = self.pos;
        self.bump();
        Ok(self.build_block(Some(open_idx), items, close))
    }

    fn parse_stmt(&mut self, ctx: Ctx) -> R<Stmt> {
        match self.peek() {
            K::Bar => {
                let start = self.pos;
                let head = self.parse_node_head()?;
                if matches!(self.peek(), K::Link | K::Dim | K::Amp) || self.at_barbar() || self.capsule_path_ahead() {
                    if ctx == Ctx::Labels {
                        return Err(self.err_here("a link's '[ ]' holds labels (text) and annotation nodes"));
                    }
                    self.pos = start;
                    return self.parse_link();
                }
                let node = self.parse_node_tail(head)?;
                Ok(Stmt::Node(node))
            }
            K::Str => {
                let t = self.bump();
                let text = render_string(&t.text);
                let classes = self.parse_classes()?;
                let mut style = None;
                if self.peek() == K::LBrace {
                    style = Some(self.parse_style_block()?);
                    if self.peek() == K::Dot {
                        return Err(self.err_here(CLASS_FIRST));
                    }
                }
                if self.peek() == K::LBrack {
                    return Err(self.err_here(
                        "text content takes no '[ ]' — wrap it in '|block|' to give it children",
                    ));
                }
                Ok(Stmt::Text(Text { text, classes, style: style.filter(|b| !b.entries.is_empty()) }))
            }
            K::Ident => {
                if ctx == Ctx::Labels {
                    return Err(self.err_here("a link's '[ ]' holds labels (text) and annotation nodes"));
                }
                self.parse_link()
            }
            _ if ctx == Ctx::Labels => Err(self.err_here("a link's '[ ]' holds labels (text) and annotation nodes")),
            K::Var => Err(self.err_here("variables are declared in the stylesheet '{ }'")),
            _ => Err(self.err_here(NODE_ERR)),
        }
    }

    // '|type#id|' -> (rendered head, type name)
    fn parse_node_head(&mut self) -> R<(String, Option<String>)> {
        if self.peek_at(1) == K::Link && self.tok_at(1).text == "-" {
            if self.peek_at(2) == K::Bar {
                return Err(self.err_here("a link is drawn by an operator — '|-|' only styles links (write 'a -> b')"));
            }
            return Err(perr("'| |' needs a type or an '#id'", self.tok_at(1)));
        }
        self.bump(); // |
        let mut ty = None;
        if self.peek() == K::Ident {
            ty = Some(self.bump().text);
            if self.peek() == K::DColon {
                return Err(self.err_here("a define belongs in the stylesheet"));
            }
        }
        let mut id = None;
        if self.peek() == K::Hash && !(ty.is_some() && self.tok().sp) {
            let h = self.bump();
            if !valid_id(&h.text) {
                return Err(perr(&format!("'#{}' is not a valid id — an id starts with a letter or '_'", h.text), &h));
            }
            id = Some(h.text);
        }
        if self.peek() == K::Dot && (!self.tok().sp || (ty.is_none() && id.is_none())) {
            return Err(self.err_here("a class follows the bars — write '|box| .hot', not '|box.hot|'"));
        }
        if ty.is_none() && id.is_none() {
            return Err(self.err_here("'| |' needs a type or an '#id'"));
        }
        if self.peek() != K::Bar {
            return Err(self.err_here("expected '|'"));
        }
        self.bump();
        let mut s = String::from("|");
        if let Some(t) = &ty {
            s.push_str(t);
        }
        if let Some(i) = &id {
            s.push('#');
            s.push_str(i);
        }
        s.push('|');
        Ok((s, ty))
    }

    fn parse_classes(&mut self) -> R<String> {
        let mut out = String::new();
        while self.peek() == K::Dot {
            if self.tok().sp && !out.is_empty() {
                return Err(self.err_here(CLASS_GLUE));
            }
            self.bump();
            if self.peek() != K::Ident {
                return Err(self.err_here("expected identifier"));
            }
            out.push('.');
            out.push_str(&self.bump().text);
        }
        Ok(out)
    }

    fn parse_node_tail(&mut self, head: (String, Option<String>)) -> R<Node> {
        let mut label = None;
        if self.peek() == K::Str {
            let t = self.bump();
            label = Some(render_string(&t.text));
            if self.peek() == K::Str {
                return Err(self.err_here(ONE_LABEL));
            }
        }
        let classes = self.parse_classes()?;
        if self.peek() == K::Str {
            return Err(self.err_here(LABEL_FIRST));
        }
        let mut style = None;
        let mut anchor = None;
        if self.peek() == K::LBrace {
            let before = self.pos - 1;
            let b = self.parse_style_block()?;
            if b.entries.is_empty() {
                anchor = Some(before);
            }
            style = Some(b);
            if self.peek() == K::Str {
                return Err(self.err_here(LABEL_FIRST));
            }
            if self.peek() == K::Dot {
                return Err(self.err_here(CLASS_FIRST));
            }
        }
        let mut children = None;
        if self.peek() == K::LBrack {
            children = Some(self.parse_children(Ctx::Children, anchor)?);
        }
        let columns = style
            .as_ref()
            .and_then(|b| b.entries.iter().rev().find(|e| e.item.name == "columns"))
            .map(|d| d.item.tracks);
        Ok(Node {
            head: head.0,
            ty: head.1,
            label,
            classes,
            style: style.filter(|b| !b.entries.is_empty()),
            children: children.filter(|b| !b.entries.is_empty()),
            columns,
        })
    }

    // ---------------------------------------------------------------- links
    // `lead` is set for the statement's first endpoint: a bare `name:` there
    // reads as a misplaced declaration.
    fn parse_endpoint(&mut self, in_fan: bool, lead: Option<&Tok>) -> R<(String, bool)> {
        match self.peek() {
            K::Ident => self.parse_path(lead),
            K::Bar => {
                let (mut h, _) = self.parse_node_head()?;
                // a capsule may reach inside: |group#g|.child:left
                let dotted = self.path_tail(&mut h, None, false)?;
                Ok((h, dotted))
            }
            K::Str if !in_fan => {
                let t = self.bump();
                Ok((render_string(&t.text), false))
            }
            _ => Err(self.err_here("expected identifier")),
        }
    }

    // a.b.c[.2][:anchor] -> (rendered, has_dots)
    fn parse_path(&mut self, lead: Option<&Tok>) -> R<(String, bool)> {
        let mut s = self.bump().text;
        let dotted = self.path_tail(&mut s, lead, true)?;
        Ok((s, dotted))
    }

    // the `.part.2:anchor` that may follow a name or a capsule
    fn path_tail(&mut self, s: &mut String, lead: Option<&Tok>, bare: bool) -> R<bool> {
        let mut dotted = false;
        loop {
            if !(self.peek() == K::Dot && !self.tok().sp) {
                break;
            }
            if self.peek_at(1) == K::Ident && !self.tok_at(1).sp {
                self.bump();
                s.push('.');
                s.push_str(&self.bump().text);
                dotted = true;
                continue;
            }
            if self.peek_at(1) == K::Num && !self.tok_at(1).sp {
                self.bump();
                let n = self.bump();
                s.push('.');
                s.push_str(&render_index(&n.text));
                dotted = true;
                if self.peek() == K::Dot && !self.tok().sp {
                    return Err(self.err_here("the copy index ends an endpoint path"));
                }
                break;
            }
            if self.tok_at(1).sp {
                return Err(perr("endpoint '.' must have no whitespace after it", self.tok_at(1)));
            }
            return Err(perr("expected identifier", self.tok_at(1)));
        }
        let msg = self.decl_msg();
        let decl_err = |t: &Tok| Diag::error(family_of(msg), msg, Span::new(t.s, t.e));
        if self.peek() == K::Colon {
            self.bump();
            if self.peek() != K::Ident {
                if let (Some(t), false, true) = (lead, dotted, bare) {
                    return Err(decl_err(t));
                }
                return Err(self.err_here("expected identifier"));
            }
            s.push(':');
            s.push_str(&self.bump().text);
            if let (Some(t), false, true) = (lead, dotted, bare) {
                if self.peek() == K::Colon {
                    return Err(decl_err(t));
                }
            }
        }
        Ok(dotted)
    }

    // after a statement's leading capsule: `.part` glued on, then a link op?
    fn capsule_path_ahead(&self) -> bool {
        let t = self.toks;
        let mut j = self.pos;
        if !(matches!(t[j].k, K::Dot | K::Colon) && !t[j].sp) {
            return false;
        }
        while t[j].k == K::Dot {
            j += 1;
            if matches!(t[j].k, K::Ident | K::Num) {
                j += 1;
            } else {
                return false;
            }
        }
        if t[j].k == K::Colon {
            j += 1;
            if t[j].k != K::Ident {
                return false;
            }
            j += 1;
        }
        matches!(t[j].k, K::Link | K::Dim | K::Amp)
            || (t[j].k == K::Bar && t.get(j + 1).map_or(false, |n| n.k == K::Bar && !n.sp))
    }

    fn parse_fan(&mut self, lead: Option<&Tok>) -> R<(Vec<String>, bool)> {
        let (first, dotted) = self.parse_endpoint(false, lead)?;
        let mut eps = vec![first];
        let mut complex = dotted;
        while self.peek() == K::Amp {
            self.bump();
            let (e, _) = self.parse_endpoint(true, None)?;
            eps.push(e);
            complex = true;
        }
        Ok((eps, complex))
    }

    fn parse_link(&mut self) -> R<Stmt> {
        let start_idx = self.pos;
        let start_tok = self.tok().clone();
        let (first, complex) = self.parse_fan(Some(&start_tok))?;
        let mut head = first.join(" & ");
        let mut first_op: Option<String> = None;
        let mut nops = 0;
        loop {
            let op = match self.peek() {
                K::Link | K::Dim => self.tok().text.clone(),
                K::Bar if self.at_barbar() => "||".to_string(),
                _ => break,
            };
            match &first_op {
                None => first_op = Some(op.clone()),
                Some(f) => {
                    if op_class(f) != op_class(&op) {
                        return Err(self.err_here(&format!("link chain mixes operators '{}' and '{}'", f, op)));
                    }
                }
            }
            let chained = nops > 0;
            nops += 1;
            if op == "||" {
                self.bump();
            }
            self.bump();
            head.push(' ');
            head.push_str(&op);
            match self.peek() {
                K::Ident | K::Bar => {
                    let (eps, _) = self.parse_fan(None)?;
                    head.push(' ');
                    head.push_str(&eps.join(" & "));
                }
                _ => {
                    if chained {
                        return Err(self.err_here("a text callout ends its statement — chain before it"));
                    }
                    // one-ended: `a (o)`, `a <- "text"`
                    break;
                }
            }
        }
        if first_op.is_none() {
            if complex {
                return Err(self.err_here("expected a link operator"));
            }
            if self.peek() == K::Colon || head.contains(':') {
                return Err(Diag::error(
                    family_of(self.decl_msg()),
                    self.decl_msg(),
                    Span::new(start_tok.s, start_tok.e),
                ));
            }
            return Err(perr(NODE_ERR, &start_tok));
        }
        let mut label: Option<(usize, Stmt)> = None;
        if self.peek() == K::Str {
            let idx = self.pos;
            let t = self.bump();
            label = Some((idx, Stmt::Text(Text { text: render_string(&t.text), classes: String::new(), style: None })));
            if self.peek() == K::Str {
                return Err(self.err_here(ONE_LABEL));
            }
        }
        let classes = self.parse_classes()?;
        if self.peek() == K::Str {
            return Err(self.err_here(LABEL_FIRST));
        }
        let mut style = None;
        let mut anchor = None;
        if self.peek() == K::LBrace {
            let before = self.pos - 1;
            let b = self.parse_style_block()?;
            if b.entries.is_empty() {
                anchor = Some(before);
            }
            style = Some(b);
            if self.peek() == K::Str {
                return Err(self.err_here(LABEL_FIRST));
            }
            if self.peek() == K::Dot {
                return Err(self.err_here(CLASS_FIRST));
            }
        }
        let mut first_label_tok: Option<usize> = None;
        let has_block = self.peek() == K::LBrack;
        let mut labels = match self.peek() {
            K::LBrack => {
                if self.peek_at(1) != K::RBrack {
                    first_label_tok = Some(self.pos + 1);
                }
                self.parse_children(Ctx::Labels, anchor)?
            }
            _ => Block::empty(),
        };
        if let Some((idx, st)) = label {
            // the inline label joins the list; whatever lies between it and
            // the first bracketed label becomes that label's leading trivia
            if let Some(first) = labels.entries.first_mut() {
                let mut f = first_label_tok.unwrap_or(idx);
                while self.toks[f].k == K::Newline && f + 1 < self.toks.len() {
                    f += 1;
                }
                first.lead = self.trivia_range(Some(idx), f);
            }
            if !has_block {
                // a dropped empty style block leaves its trivia to the label
                let open = if anchor.is_some() || style.is_none() { idx } else { self.pos - 1 };
                let end = self.pos - 1;
                labels.close = self.trivia_range(Some(open), end);
                labels.any_trivia = self.any_trivia(open, end);
                labels.any_comment = self.any_comment(open, end);
            }
            labels.entries.insert(0, Entry { lead: Vec::new(), item: st });
        }
        let has_comment = self.any_comment(start_idx, self.pos - 1);
        Ok(Stmt::Link(Link { head, labels, classes, style: style.filter(|b| !b.entries.is_empty()), has_comment }))
    }
}

// operators that may share a chain
fn op_class(op: &str) -> String {
    if op.starts_with('(') || op == "||" {
        op.to_string()
    } else {
        "link".to_string()
    }
}

// the first argument is exactly one number literal
fn single_num(cur: &[(String, usize, usize, bool)], first: Option<f64>) -> Option<f64> {
    if cur.len() == 1 {
        first
    } else {
        None
    }
}

fn valid_id(s: &str) -> bool {
    match s.chars().next() {
        Some(c) => c.is_ascii_alphabetic() || c == '_',
        None => false,
    }
}

fn render_index(text: &str) -> String {
    let digits: String = text.chars().filter(|c| c.is_ascii_digit()).collect();
    match digits.parse::<u64>() {
        Ok(v) => v.to_string(),
        Err(_) => digits,
    }
}

// Built-in type names a define may not reuse; all but the last few may also
// serve as a define's base.
const BUILTIN_TYPES: &[&str] = &[
    "alt", "appliance", "area", "axis", "badge", "balloon", "band", "bars", "bath", "bed", "block", "box", "bubble",
    "caption", "cell", "centerline", "chart", "column", "component", "control", "cyl", "datum", "diamond", "dining",
    "door", "dots", "drawing", "else", "entity", "feature-control", "field", "floorplan", "footer", "footnote",
    "frame", "gnd", "grid", "group", "header", "hex", "hidden", "hole", "icon", "image", "junction", "label", "line",
    "loop", "magnifier", "mark", "mindmap", "nc", "note", "opamp", "opt", "oval", "page", "partition", "path", "pie",
    "pin", "pitch-circle", "plane", "poly", "rect", "row", "schematic", "sequence", "shoulder", "sign", "sketch",
    "slant", "slice", "sofa", "space", "stack", "stairs", "surface-finish", "table", "tick", "title-block", "topic",
    "wall", "window", "zone", "BT", "BZ", "C", "D", "F", "FB", "I", "J", "L", "LED", "M", "Q", "R", "SW", "TP", "V",
    "Y",
];
const RESERVED_NOT_BASE: &[&str] = &["text", "canvas", "cut", "link", "marker", "node", "scene"];

// The define table, when it holds together (unique names that shadow no
// built-in, bases that exist, no cycles); None otherwise.
fn resolve_types(defines: &[(String, String)]) -> Option<HashMap<String, String>> {
    let mut map: HashMap<String, String> = HashMap::new();
    for (n, b) in defines {
        if BUILTIN_TYPES.contains(&n.as_str()) || RESERVED_NOT_BASE.contains(&n.as_str()) || map.contains_key(n) {
            return None;
        }
        map.insert(n.clone(), b.clone());
    }
    for (n, _) in defines {
        let mut seen: HashSet<&str> = HashSet::new();
        let mut t: &str = n;
        loop {
            if !seen.insert(t) {
                return None;
            }
            match map.get(t) {
                Some(b) => t = b,
                None => {
                    if !BUILTIN_TYPES.contains(&t) {
                        return None;
                    }
                    break;
                }
            }
        }
    }
    Some(map)
}

// Built-in functions: their '(' must touch the name.
const FUNCTIONS: &[&str] = &[
    "abs", "clamp", "cos", "exp", "floor", "gradient", "hatch", "hsl", "hsla", "linear-gradient", "ln", "log", "max",
    "min", "oklch", "pow", "radial-gradient", "repeat", "rgb", "rgba", "round", "sin", "sqrt", "tan",
];
