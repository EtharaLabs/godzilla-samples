#![allow(dead_code)]
// A structural reading of a document for `lini desugar`. It runs over the
// formatter's tokens after `format::syntax_check` accepted the file, so it
// does no error reporting of its own; declaration values come out in the
// formatter's canonical rendering (the desugared text prints through the same
// rules as `lini fmt`).

use crate::diag::Span;
use crate::format::expr;
use crate::format::lex::{Tok, K};
use crate::format::parse::{render_number, render_string};

#[derive(Clone, Debug)]
pub struct Decl {
    pub name: String, // with a leading '--' for variables
    pub groups: Vec<Vec<String>>,
    pub span: Span, // where the name starts (generated decls: empty)
}

impl PartialEq for Decl {
    fn eq(&self, o: &Decl) -> bool {
        self.name == o.name && self.groups == o.groups
    }
}

impl Decl {
    pub fn new(name: &str, value: &str) -> Decl {
        Decl { name: name.to_string(), groups: vec![vec![value.to_string()]], span: Span::default() }
    }
    pub fn groups(name: &str, groups: Vec<Vec<String>>) -> Decl {
        Decl { name: name.to_string(), groups, span: Span::default() }
    }
    // a value written out in canonical text: groups split at top-level
    // commas, terms at top-level spaces
    pub fn val(name: &str, text: &str) -> Decl {
        let mut groups: Vec<Vec<String>> = vec![Vec::new()];
        let mut cur = String::new();
        let mut depth = 0i32;
        let mut quote = false;
        let mut chars = text.chars().peekable();
        while let Some(c) = chars.next() {
            if quote {
                cur.push(c);
                if c == '\\' {
                    if let Some(n) = chars.next() {
                        cur.push(n);
                    }
                } else if c == '"' {
                    quote = false;
                }
                continue;
            }
            match c {
                '"' => {
                    quote = true;
                    cur.push(c);
                }
                '(' => {
                    depth += 1;
                    cur.push(c);
                }
                ')' => {
                    depth -= 1;
                    cur.push(c);
                }
                ',' if depth == 0 => {
                    if !cur.is_empty() {
                        groups.last_mut().unwrap().push(std::mem::take(&mut cur));
                    }
                    groups.push(Vec::new());
                    while chars.peek() == Some(&' ') {
                        chars.next();
                    }
                }
                ' ' if depth == 0 => {
                    if !cur.is_empty() {
                        groups.last_mut().unwrap().push(std::mem::take(&mut cur));
                    }
                }
                c => cur.push(c),
            }
        }
        if !cur.is_empty() {
            groups.last_mut().unwrap().push(cur);
        }
        Decl { name: name.to_string(), groups, span: Span::default() }
    }
    // parse a rule's default text ("a: 1; b: 2 3;")
    pub fn list(text: &str) -> Vec<Decl> {
        let mut out = Vec::new();
        let mut cur = String::new();
        let mut quote = false;
        for c in text.chars() {
            if c == '"' {
                quote = !quote;
            }
            if c == ';' && !quote {
                let s = cur.trim().to_string();
                cur.clear();
                if let Some((n, v)) = s.split_once(':') {
                    out.push(Decl::val(n.trim(), v.trim()));
                }
                continue;
            }
            cur.push(c);
        }
        out
    }
    pub fn value_text(&self) -> String {
        self.groups.iter().map(|g| g.join(" ")).collect::<Vec<_>>().join(", ")
    }
    pub fn text(&self) -> String {
        format!("{}: {};", self.name, self.value_text())
    }
    pub fn is_draw(&self) -> bool {
        self.name == "draw"
    }
    // the first term of the value, if any
    pub fn first(&self) -> Option<&str> {
        self.groups.first().and_then(|g| g.first()).map(|s| s.as_str())
    }
}

#[derive(Clone, Debug)]
pub enum Comp {
    Bars { ty: Option<String>, id: Option<String> },
    Class(String),
    Id(String),
    Dim(String),
}

#[derive(Clone, Debug)]
pub struct Rule {
    pub sel: Vec<(Comp, Span)>,
    pub decls: Vec<Decl>,
    pub span: Span,
}

#[derive(Clone, Debug)]
pub struct Define {
    pub name: String,
    pub base: String,
    pub decls: Vec<Decl>,
    pub body: Option<Vec<Stmt>>,
    pub span: Span,
    pub base_span: Span,
}

#[derive(Clone, Debug)]
pub enum SItem {
    Decl(Decl),
    Var(Decl),
    Binding(String),
    Rule(Rule),
    Define(Define),
}

#[derive(Clone, Debug)]
pub struct Node {
    pub ty: Option<String>,
    pub id: Option<String>,
    pub label: Option<String>, // decoded
    pub classes: Vec<String>,
    pub style: Vec<Decl>,
    pub children: Option<Vec<Stmt>>,
    pub span: Span,
    pub head_span: Span,
    pub ty_span: Span,
}

#[derive(Clone, Debug)]
pub struct Text {
    pub text: String, // decoded
    pub classes: Vec<String>,
    pub style: Vec<Decl>,
    pub span: Span,
}

#[derive(Clone, Debug)]
pub enum Endpoint {
    // a.b.2:anchor — `text` is the rendered path, `parts` the names
    Path { text: String, parts: Vec<String>, span: Span },
    // |type#id| optionally reaching inside: |g#x|.c:left
    Capsule { node: Node, tail: String },
    Text(String),
}

#[derive(Clone, Debug)]
pub struct Link {
    pub groups: Vec<Vec<Endpoint>>,
    pub ops: Vec<String>,
    pub label: Option<String>,
    // the label's string token
    pub label_span: Span,
    pub classes: Vec<String>,
    pub style: Vec<Decl>,
    pub labels: Vec<Stmt>,
    pub span: Span,
}

#[derive(Clone, Debug)]
pub enum Stmt {
    Node(Node),
    Text(Text),
    Link(Link),
}

pub struct Doc {
    pub sheet: Vec<(SItem, Span)>,
    pub stmts: Vec<Stmt>,
}

pub struct P<'a> {
    src: &'a str,
    toks: &'a [Tok],
    pos: usize,
}

pub fn parse(src: &str) -> Result<Doc, crate::diag::Diag> {
    let lexed = crate::format::lex::lex(src)?;
    let mut p = P { src, toks: &lexed.toks, pos: 0 };
    Ok(p.doc())
}

impl<'a> P<'a> {
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
    fn skip_seps(&mut self) {
        while matches!(self.peek(), K::Newline | K::Semi) {
            self.bump();
        }
    }
    fn at_barbar(&self) -> bool {
        self.peek() == K::Bar && self.peek_at(1) == K::Bar && !self.tok_at(1).sp
    }
    fn span_from(&self, s: usize) -> Span {
        Span::new(s, self.last_end().max(s))
    }

    fn doc(&mut self) -> Doc {
        self.skip_seps();
        let mut sheet = Vec::new();
        if self.peek() == K::LBrace {
            sheet = self.sheet();
        }
        let mut stmts = Vec::new();
        loop {
            self.skip_seps();
            if matches!(self.peek(), K::Eof | K::RBrack | K::RBrace) {
                break;
            }
            let before = self.pos;
            stmts.push(self.stmt());
            if self.pos == before {
                self.bump();
            }
        }
        Doc { sheet, stmts }
    }

    // ---------------------------------------------------------------- sheet
    fn sheet(&mut self) -> Vec<(SItem, Span)> {
        self.bump(); // {
        let mut items = Vec::new();
        loop {
            self.skip_seps();
            if matches!(self.peek(), K::RBrace | K::Eof) {
                self.bump();
                break;
            }
            let s = self.tok().s;
            let before = self.pos;
            if let Some(it) = self.sheet_item() {
                items.push((it, self.span_from(s)));
            }
            if self.pos == before {
                self.bump();
            }
        }
        items
    }

    fn sheet_item(&mut self) -> Option<SItem> {
        match self.peek() {
            K::Var => {
                let t = self.bump();
                self.bump(); // :
                let d = self.decl_rest(format!("--{}", t.text), t.s);
                Some(SItem::Var(d))
            }
            K::Ident => match self.peek_at(1) {
                K::Colon => Some(SItem::Decl(self.decl())),
                _ => Some(SItem::Binding(self.binding())),
            },
            K::Bar | K::Dot | K::Hash | K::Dim => Some(self.rule_or_define()),
            _ => None,
        }
    }

    fn binding(&mut self) -> String {
        let name = self.bump().text;
        let mut params: Option<Vec<String>> = None;
        if self.peek() == K::LParen {
            self.bump();
            let mut ps = Vec::new();
            loop {
                match self.peek() {
                    K::Ident => ps.push(self.bump().text),
                    K::Comma => {
                        self.bump();
                    }
                    K::RParen => {
                        self.bump();
                        break;
                    }
                    _ => break,
                }
            }
            params = Some(ps);
        }
        self.bump(); // =
        let rhs = if self.peek() == K::LParen {
            let open = self.bump();
            let close_end = self.skip_group();
            let inner = self.src[open.e..close_end.saturating_sub(1).max(open.e)].trim();
            expr::binding_group(inner)
        } else {
            let start = self.tok().s;
            let mut end = start;
            let mut depth = 0usize;
            loop {
                match self.peek() {
                    K::Semi | K::Eof => break,
                    K::Newline | K::RBrace if depth == 0 => break,
                    K::LParen => depth += 1,
                    K::RParen => depth = depth.saturating_sub(1),
                    _ => {}
                }
                end = self.bump().e;
            }
            expr::binding_bare(&self.src[start..end])
        };
        if self.peek() == K::Semi {
            self.bump();
        }
        let head = match params {
            Some(ps) if !ps.is_empty() => format!("{}({})", name, ps.join(", ")),
            _ => name,
        };
        format!("{} = {};", head, rhs)
    }

    fn rule_or_define(&mut self) -> SItem {
        let start = self.tok().s;
        if self.peek() == K::Bar && self.peek_at(1) == K::Ident && self.peek_at(2) == K::DColon {
            self.bump();
            let name = self.bump().text;
            self.bump(); // ::
            let bt = self.bump();
            let base = bt.text.clone();
            let base_span = Span::new(bt.s, bt.e);
            self.bump(); // |
            let mut decls = Vec::new();
            if self.peek() == K::LBrace {
                decls = self.style_block();
            }
            let mut body = None;
            if self.peek() == K::LBrack {
                body = Some(self.children(false));
            }
            return SItem::Define(Define { name, base, decls, body, span: self.span_from(start), base_span });
        }
        let mut sel = Vec::new();
        loop {
            let s = self.tok().s;
            match self.peek() {
                K::LBrace | K::Eof => break,
                K::Bar => {
                    self.bump();
                    let mut ty = None;
                    let mut id = None;
                    match self.peek() {
                        K::Ident => ty = Some(self.bump().text),
                        K::Link if self.tok().text == "-" => {
                            self.bump();
                            ty = Some("-".to_string());
                        }
                        _ => {}
                    }
                    if self.peek() == K::Hash {
                        id = Some(self.bump().text);
                    }
                    if self.peek() == K::Bar {
                        self.bump();
                    }
                    sel.push((Comp::Bars { ty, id }, self.span_from(s)));
                }
                K::Dot => {
                    self.bump();
                    let n = self.bump().text;
                    sel.push((Comp::Class(n), self.span_from(s)));
                }
                K::Hash => {
                    let h = self.bump();
                    sel.push((Comp::Id(h.text), self.span_from(s)));
                }
                K::Dim => {
                    let t = self.bump();
                    sel.push((Comp::Dim(t.text), self.span_from(s)));
                }
                _ => {
                    self.bump();
                }
            }
        }
        let decls = if self.peek() == K::LBrace { self.style_block() } else { Vec::new() };
        SItem::Rule(Rule { sel, decls, span: self.span_from(start) })
    }

    // ------------------------------------------------------- style blocks
    fn style_block(&mut self) -> Vec<Decl> {
        self.bump(); // {
        let mut out = Vec::new();
        loop {
            self.skip_seps();
            match self.peek() {
                K::RBrace => {
                    self.bump();
                    break;
                }
                K::Eof => break,
                K::Ident if self.peek_at(1) == K::Colon => out.push(self.decl()),
                _ => {
                    self.bump();
                }
            }
        }
        out
    }

    fn decl(&mut self) -> Decl {
        let t = self.bump();
        self.bump(); // :
        self.decl_rest(t.text, t.s)
    }

    fn decl_rest(&mut self, name: String, start: usize) -> Decl {
        let draw = name == "draw";
        let groups = self.value(draw);
        let span = Span::new(start, self.last_end().max(start));
        if self.peek() == K::Semi {
            self.bump();
        }
        Decl { name, groups, span }
    }

    fn value(&mut self, draw: bool) -> Vec<Vec<String>> {
        let mut groups: Vec<Vec<String>> = vec![Vec::new()];
        let mut prev_call = false;
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
                    if draw && self.peek_at(1) == K::Ident && !self.tok_at(1).sp && prev_call && !self.tok().sp {
                        self.bump();
                        let tag = self.bump().text;
                        let g = groups.last_mut().unwrap();
                        if let Some(last) = g.pop() {
                            g.push(format!("{}:{}", last, tag));
                        }
                        prev_call = false;
                        continue;
                    }
                    break;
                }
                _ => {}
            }
            let before = self.pos;
            let (text, call) = self.term();
            if self.pos == before {
                break;
            }
            groups.last_mut().unwrap().push(text);
            prev_call = call;
        }
        groups
    }

    // one value term, rendered canonically -> (text, is a call)
    fn term(&mut self) -> (String, bool) {
        let t = self.tok().clone();
        match t.k {
            K::Num => {
                self.bump();
                (render_number(t.v), false)
            }
            K::Percent => {
                self.bump();
                (format!("{}%", render_number(t.v)), false)
            }
            K::Str => {
                self.bump();
                (render_string(&t.text), false)
            }
            K::Hash => {
                self.bump();
                (format!("#{}", t.text), false)
            }
            K::Var => {
                self.bump();
                (format!("--{}", t.text), false)
            }
            K::Ident => {
                self.bump();
                if self.peek() == K::LParen && !self.tok().sp {
                    self.bump();
                    let args = self.call_args();
                    return (format!("{}({})", t.text, args.join(", ")), true);
                }
                (t.text.clone(), false)
            }
            K::LParen => {
                let open = self.bump();
                let close_end = self.skip_group();
                let inner = self.src[open.e..close_end.saturating_sub(1).max(open.e)].trim();
                (format!("({})", inner), false)
            }
            _ => (String::new(), false),
        }
    }

    // after '(' : returns the end offset of the matching ')'
    fn skip_group(&mut self) -> usize {
        let mut depth = 1usize;
        loop {
            match self.peek() {
                K::Eof => return self.tok().e,
                K::LParen => depth += 1,
                K::RParen => {
                    depth -= 1;
                    if depth == 0 {
                        return self.bump().e;
                    }
                }
                _ => {}
            }
            self.bump();
        }
    }

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

    fn call_args(&mut self) -> Vec<String> {
        let mut args: Vec<String> = Vec::new();
        // (rendered, start, end, is_group)
        let mut cur: Vec<(String, usize, usize, bool)> = Vec::new();
        loop {
            self.skip_newlines();
            if cur.is_empty() && self.arg_has_op() {
                let start = self.tok().s;
                let mut end = start;
                let mut depth = 0usize;
                loop {
                    match self.peek() {
                        K::Eof => break,
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
                args.push(self.src[start..end].to_string());
                if self.peek() == K::Comma {
                    self.bump();
                    continue;
                }
                self.bump(); // ')'
                return args;
            }
            let t = self.tok().clone();
            match t.k {
                K::RParen if !(cur.is_empty() && !args.is_empty()) => {
                    self.bump();
                    if !cur.is_empty() {
                        args.push(self.finish_arg(&mut cur));
                    }
                    return args;
                }
                K::Comma if !cur.is_empty() => {
                    self.bump();
                    args.push(self.finish_arg(&mut cur));
                    continue;
                }
                K::Eof => return args,
                _ => {}
            }
            let s = t.s;
            let is_group = t.k == K::LParen;
            let before = self.pos;
            let (text, _) = self.term();
            if self.pos == before {
                self.bump();
                continue;
            }
            let e = self.last_end();
            cur.push((text, s, e, is_group));
        }
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
    fn children(&mut self, labels: bool) -> Vec<Stmt> {
        self.bump(); // [
        let mut out = Vec::new();
        loop {
            self.skip_seps();
            match self.peek() {
                K::RBrack => {
                    self.bump();
                    break;
                }
                K::Eof => break,
                _ => {}
            }
            let before = self.pos;
            out.push(self.stmt());
            let _ = labels;
            if self.pos == before {
                self.bump();
            }
        }
        out
    }

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

    fn stmt(&mut self) -> Stmt {
        match self.peek() {
            K::Bar => {
                let start = self.pos;
                let _ = self.node_head();
                if matches!(self.peek(), K::Link | K::Dim | K::Amp) || self.at_barbar() || self.capsule_path_ahead() {
                    self.pos = start;
                    return self.link();
                }
                self.pos = start;
                Stmt::Node(self.node())
            }
            K::Str => {
                let t = self.bump();
                let classes = self.classes();
                let mut style = Vec::new();
                if self.peek() == K::LBrace {
                    style = self.style_block();
                }
                Stmt::Text(Text { text: t.text.clone(), classes, style, span: self.span_from(t.s) })
            }
            _ => self.link(),
        }
    }

    // '|type#id|' -> (type, id, type span)
    fn node_head(&mut self) -> (Option<String>, Option<String>, Span) {
        let s = self.tok().s;
        self.bump(); // |
        let mut ty = None;
        let mut ty_span = Span::new(s, s);
        if self.peek() == K::Ident {
            let t = self.bump();
            ty_span = Span::new(t.s, t.e);
            ty = Some(t.text);
        }
        let mut id = None;
        if self.peek() == K::Hash {
            id = Some(self.bump().text);
        }
        if self.peek() == K::Bar {
            self.bump();
        }
        (ty, id, ty_span)
    }

    fn classes(&mut self) -> Vec<String> {
        let mut out = Vec::new();
        while self.peek() == K::Dot && self.peek_at(1) == K::Ident {
            self.bump();
            out.push(self.bump().text);
        }
        out
    }

    fn node(&mut self) -> Node {
        let s = self.tok().s;
        let (ty, id, ty_span) = self.node_head();
        let head_span = self.span_from(s);
        let mut label = None;
        if self.peek() == K::Str {
            label = Some(self.bump().text);
        }
        let classes = self.classes();
        let mut style = Vec::new();
        if self.peek() == K::LBrace {
            style = self.style_block();
        }
        let mut children = None;
        if self.peek() == K::LBrack {
            children = Some(self.children(false));
        }
        Node { ty, id, label, classes, style, children, span: self.span_from(s), head_span, ty_span }
    }

    // the `.part.2:anchor` that may follow a name or a capsule
    fn path_tail(&mut self, s: &mut String, parts: &mut Vec<String>) {
        loop {
            if !(self.peek() == K::Dot && !self.tok().sp) {
                break;
            }
            if self.peek_at(1) == K::Ident && !self.tok_at(1).sp {
                self.bump();
                let n = self.bump().text;
                s.push('.');
                s.push_str(&n);
                parts.push(n);
                continue;
            }
            if self.peek_at(1) == K::Num && !self.tok_at(1).sp {
                self.bump();
                let n = self.bump();
                let digits: String = n.text.chars().filter(|c| c.is_ascii_digit()).collect();
                let idx = match digits.parse::<u64>() {
                    Ok(v) => v.to_string(),
                    Err(_) => digits,
                };
                s.push('.');
                s.push_str(&idx);
                break;
            }
            break;
        }
        if self.peek() == K::Colon && self.peek_at(1) == K::Ident {
            self.bump();
            s.push(':');
            s.push_str(&self.bump().text);
        }
    }

    fn endpoint(&mut self) -> Endpoint {
        match self.peek() {
            K::Ident => {
                let t = self.bump();
                let mut s = t.text.clone();
                let mut parts = vec![t.text.clone()];
                self.path_tail(&mut s, &mut parts);
                Endpoint::Path { text: s, parts, span: self.span_from(t.s) }
            }
            K::Bar => {
                let st = self.tok().s;
                let (ty, id, ty_span) = self.node_head();
                let head_span = self.span_from(st);
                let mut tail = String::new();
                let mut parts = Vec::new();
                self.path_tail(&mut tail, &mut parts);
                let node = Node {
                    ty,
                    id,
                    label: None,
                    classes: vec![],
                    style: vec![],
                    children: None,
                    span: head_span,
                    head_span,
                    ty_span,
                };
                Endpoint::Capsule { node, tail }
            }
            K::Str => {
                let t = self.bump();
                Endpoint::Text(t.text)
            }
            _ => {
                self.bump();
                Endpoint::Text(String::new())
            }
        }
    }

    fn fan(&mut self) -> Vec<Endpoint> {
        let mut eps = vec![self.endpoint()];
        while self.peek() == K::Amp {
            self.bump();
            eps.push(self.endpoint());
        }
        eps
    }

    fn link(&mut self) -> Stmt {
        let s = self.tok().s;
        let first = self.fan();
        let mut groups = vec![first];
        let mut ops = Vec::new();
        loop {
            let op = match self.peek() {
                K::Link | K::Dim => self.tok().text.clone(),
                K::Bar if self.at_barbar() => "||".to_string(),
                _ => break,
            };
            if op == "||" {
                self.bump();
            }
            self.bump();
            ops.push(op);
            match self.peek() {
                K::Ident | K::Bar => groups.push(self.fan()),
                K::Str => {
                    // one-ended: `a <- "text"` — the text is a label
                    break;
                }
                _ => break,
            }
        }
        let mut label = None;
        let mut label_span = Span::default();
        if self.peek() == K::Str {
            let t = self.bump();
            label_span = Span::new(t.s, t.e);
            label = Some(t.text);
        }
        let classes = self.classes();
        let mut style = Vec::new();
        if self.peek() == K::LBrace {
            style = self.style_block();
        }
        let mut labels = Vec::new();
        if self.peek() == K::LBrack {
            labels = self.children(true);
        }
        Stmt::Link(Link { groups, ops, label, label_span, classes, style, labels, span: self.span_from(s) })
    }
}
