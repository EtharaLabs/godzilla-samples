// Recursive-descent parser over the token stream.

use crate::ast::*;
use crate::diag::{Diag, Span};
use crate::lexer::{Tok, Token};

pub struct Parser<'a> {
    toks: &'a [Token],
    pos: usize,
    pub src: &'a str,
}

type PResult<T> = Result<T, Diag>;

// The callee name of a space-separated run of expressions (no source name
// can start with '#').
pub const RUN: &str = "#run";

fn perr(msg: &str, span: Span) -> Diag {
    Diag::error("parse", msg, span)
}

pub const SEP_ERR: &str = "expected a newline, ';', or a closing bracket";

impl<'a> Parser<'a> {
    pub fn new(toks: &'a [Token], src: &'a str) -> Self {
        Parser { toks, pos: 0, src }
    }
    fn peek(&self) -> &Tok {
        &self.toks[self.pos].tok
    }
    fn peek_at(&self, k: usize) -> &Tok {
        let i = (self.pos + k).min(self.toks.len() - 1);
        &self.toks[i].tok
    }
    fn tok(&self) -> &Token {
        &self.toks[self.pos]
    }
    fn tok_at(&self, k: usize) -> &Token {
        let i = (self.pos + k).min(self.toks.len() - 1);
        &self.toks[i]
    }
    fn span(&self) -> Span {
        self.toks[self.pos].span
    }
    fn prev_span(&self) -> Span {
        if self.pos == 0 {
            Span::new(0, 0)
        } else {
            self.toks[self.pos - 1].span
        }
    }
    fn bump(&mut self) -> Token {
        let t = self.toks[self.pos].clone();
        if self.pos < self.toks.len() - 1 {
            self.pos += 1;
        }
        t
    }
    fn skip_newlines(&mut self) {
        while matches!(self.peek(), Tok::Newline) {
            self.bump();
        }
    }
    fn skip_seps(&mut self) {
        while matches!(self.peek(), Tok::Newline | Tok::Semi) {
            self.bump();
        }
    }

    pub fn parse_doc(&mut self) -> PResult<Doc> {
        self.skip_seps();
        let mut sheet = None;
        if matches!(self.peek(), Tok::LBrace) {
            sheet = Some(self.parse_sheet()?);
        }
        let mut stmts = Vec::new();
        loop {
            self.skip_seps();
            if matches!(self.peek(), Tok::Eof) {
                break;
            }
            if matches!(self.peek(), Tok::LBrace) {
                return Err(Diag::error(
                    "stylesheet-after-canvas",
                    "the stylesheet '{ }' must come first, before any instance",
                    self.span(),
                ));
            }
            let s = self.parse_stmt(false)?;
            stmts.push(s);
            self.expect_sep_or(&[Tok::Eof])?;
        }
        Ok(Doc { sheet, stmts })
    }

    fn expect_sep_or(&mut self, closers: &[Tok]) -> PResult<()> {
        match self.peek() {
            Tok::Newline | Tok::Semi => Ok(()),
            t if closers.iter().any(|c| c == t) => Ok(()),
            Tok::Eof => Ok(()),
            Tok::RBrack | Tok::RBrace => Ok(()),
            _ => Err(perr(SEP_ERR, self.span())),
        }
    }

    // ---------------------------------------------------------------- sheet
    fn parse_sheet(&mut self) -> PResult<Sheet> {
        let open = self.bump(); // {
        let mut items = Vec::new();
        loop {
            self.skip_seps();
            match self.peek() {
                Tok::RBrace => {
                    let close = self.bump();
                    return Ok(Sheet { items, span: open.span.to(close.span) });
                }
                Tok::Eof => return Err(perr("expected '}'", self.span())),
                _ => {}
            }
            let item = self.parse_sheet_item()?;
            let needs_semi = matches!(item, SheetItem::Decl(_) | SheetItem::Var(_));
            items.push(item);
            match self.peek() {
                Tok::Semi | Tok::Newline | Tok::RBrace => {}
                _ => {
                    if needs_semi {
                        return Err(perr("a declaration ends with ';'", self.span()));
                    }
                    return Err(perr(SEP_ERR, self.span()));
                }
            }
        }
    }

    fn parse_sheet_item(&mut self) -> PResult<SheetItem> {
        let start = self.span();
        match self.peek().clone() {
            Tok::Var(name) => {
                let t = self.bump();
                if !matches!(self.peek(), Tok::Colon) {
                    return Err(perr("expected ':'", self.span()));
                }
                self.bump();
                let value = self.parse_value()?;
                let span = t.span.to(value.span);
                Ok(SheetItem::Var(Decl { name, name_span: t.span, value, span }))
            }
            Tok::Ident(name) => {
                // declaration, binding, or function binding
                match self.peek_at(1) {
                    Tok::Colon => {
                        let d = self.parse_decl()?;
                        Ok(SheetItem::Decl(d))
                    }
                    Tok::Eq => {
                        self.bump();
                        self.bump();
                        let expr = self.parse_term_for_binding()?;
                        let span = start.to(expr.span());
                        Ok(SheetItem::Binding(Binding { name, params: None, expr, span }))
                    }
                    Tok::LParen => {
                        self.bump();
                        self.bump();
                        let mut params = Vec::new();
                        loop {
                            match self.peek().clone() {
                                Tok::Ident(p) => {
                                    self.bump();
                                    params.push(p);
                                }
                                Tok::RParen => {}
                                _ => return Err(perr("expected identifier", self.span())),
                            }
                            match self.peek() {
                                Tok::Comma => {
                                    self.bump();
                                }
                                Tok::RParen => {
                                    self.bump();
                                    break;
                                }
                                _ => return Err(perr("expected ')'", self.span())),
                            }
                        }
                        if !matches!(self.peek(), Tok::Eq) {
                            return Err(perr("expected '='", self.span()));
                        }
                        self.bump();
                        let expr = self.parse_term_for_binding()?;
                        let span = start.to(expr.span());
                        Ok(SheetItem::Binding(Binding { name, params: Some(params), expr, span }))
                    }
                    _ => {
                        self.bump();
                        Err(perr("expected ':'", self.span()))
                    }
                }
            }
            Tok::Bar | Tok::Class(_) | Tok::Hash(_) => self.parse_rule_or_define(),
            _ => Err(perr("expected a declaration, rule, or binding", self.span())),
        }
    }

    fn parse_term_for_binding(&mut self) -> PResult<Term> {
        let t = self.parse_term()?;
        Ok(t)
    }

    fn parse_rule_or_define(&mut self) -> PResult<SheetItem> {
        let start = self.span();
        // define: |name::base|
        if matches!(self.peek(), Tok::Bar) {
            if let (Tok::Ident(name), Tok::DColon) = (self.peek_at(1).clone(), self.peek_at(2).clone()) {
                self.bump();
                self.bump();
                self.bump();
                let base = match self.peek().clone() {
                    Tok::Ident(b) => {
                        self.bump();
                        b
                    }
                    _ => return Err(perr("expected identifier", self.span())),
                };
                if !matches!(self.peek(), Tok::Bar) {
                    return Err(perr("expected '|'", self.span()));
                }
                let bar = self.bump();
                let head_span = start.to(bar.span);
                let mut decls = Vec::new();
                if matches!(self.peek(), Tok::LBrace) {
                    decls = self.parse_style_block()?.0;
                }
                let mut body = None;
                if matches!(self.peek(), Tok::LBrack) {
                    body = Some(self.parse_children()?);
                }
                let span = start.to(self.prev_span());
                return Ok(SheetItem::Define(Define { name, base, decls, body, span, head_span }));
            }
        }
        let mut selector = Vec::new();
        loop {
            match self.peek() {
                Tok::Bar | Tok::Class(_) | Tok::Hash(_) => {
                    let c = self.parse_compound()?;
                    selector.push(c);
                }
                // `|box|.c`: a class glued to the bars (lexed as a path dot)
                // starts the next compound
                Tok::Dot if matches!(self.peek_at(1), Tok::Ident(_)) => {
                    let start = self.span();
                    self.bump();
                    let name = match self.bump().tok {
                        Tok::Ident(n) => n,
                        _ => unreachable!(),
                    };
                    selector.push(Compound { classes: vec![name], span: start.to(self.prev_span()), ..Default::default() });
                }
                Tok::LBrace => break,
                _ => return Err(perr("expected '{'", self.span())),
            }
        }
        let (decls, _) = self.parse_style_block()?;
        let span = start.to(self.prev_span());
        Ok(SheetItem::Rule(Rule { selector, decls, span }))
    }

    fn parse_compound(&mut self) -> PResult<Compound> {
        let start = self.span();
        let mut c = Compound::default();
        if matches!(self.peek(), Tok::Bar) {
            self.bump();
            c.bars = true;
            match self.peek().clone() {
                Tok::Ident(t) => {
                    self.bump();
                    c.type_name = Some(t);
                }
                Tok::LinkOp(op) if op == "-" => {
                    self.bump();
                    c.type_name = Some("-".to_string());
                }
                _ => {}
            }
            if let Tok::Hash(h) = self.peek().clone() {
                self.bump();
                c.id = Some(h);
            }
            if !matches!(self.peek(), Tok::Bar) {
                if c.type_name.is_none() && c.id.is_none() {
                    return Err(perr("'| |' needs a type or an '#id'", start));
                }
                return Err(perr("expected '|'", self.span()));
            }
            self.bump();
            if c.type_name.is_none() && c.id.is_none() {
                return Err(perr("'| |' needs a type or an '#id'", start));
            }
        } else if let Tok::Hash(h) = self.peek().clone() {
            self.bump();
            c.id = Some(h);
        }
        loop {
            match self.peek().clone() {
                Tok::Class(cl) => {
                    if self.tok().space_before && (c.bars || c.id.is_some() || !c.classes.is_empty()) {
                        break;
                    }
                    self.bump();
                    c.classes.push(cl);
                }
                _ => break,
            }
        }
        c.span = start.to(self.prev_span());
        Ok(c)
    }

    // { decl; decl; } -> (decls, span)
    pub fn parse_style_block(&mut self) -> PResult<(Vec<Decl>, Span)> {
        let open = self.bump(); // {
        let mut decls = Vec::new();
        loop {
            self.skip_seps();
            match self.peek() {
                Tok::RBrace => {
                    let close = self.bump();
                    return Ok((decls, open.span.to(close.span)));
                }
                Tok::Eof => return Err(perr("expected '}'", self.span())),
                Tok::Ident(_) => {
                    let d = self.parse_decl()?;
                    decls.push(d);
                    match self.peek() {
                        Tok::Semi | Tok::RBrace | Tok::Newline => {}
                        _ => return Err(perr("a declaration ends with ';'", self.span())),
                    }
                }
                Tok::Var(_) => {
                    return Err(perr("variables are declared in the stylesheet '{ }'", self.span()));
                }
                _ => return Err(perr("expected a property name", self.span())),
            }
        }
    }

    fn parse_decl(&mut self) -> PResult<Decl> {
        let t = self.bump();
        let name = match &t.tok {
            Tok::Ident(n) => n.clone(),
            _ => unreachable!(),
        };
        if !matches!(self.peek(), Tok::Colon) {
            return Err(perr("expected ':'", self.span()));
        }
        self.bump();
        let value = self.parse_value()?;
        let span = t.span.to(value.span);
        Ok(Decl { name, name_span: t.span, value, span })
    }

    // value := group (',' group)* ; group := term+ ; newlines are ignored
    pub fn parse_value(&mut self) -> PResult<Value> {
        let start = self.span();
        let mut groups = Vec::new();
        let mut cur: Vec<Term> = Vec::new();
        loop {
            self.skip_newlines();
            match self.peek() {
                Tok::Semi | Tok::RBrace | Tok::Eof => break,
                Tok::Comma => {
                    if cur.is_empty() {
                        return Err(perr("expected a value", self.span()));
                    }
                    self.bump();
                    groups.push(std::mem::take(&mut cur));
                    continue;
                }
                Tok::Colon if !cur.is_empty() => {
                    // a term tag (draw segment name)
                    self.bump();
                    match self.peek().clone() {
                        Tok::Ident(tag) => {
                            let ts = self.bump().span;
                            let last = cur.pop().unwrap();
                            let sp = last.span().to(ts);
                            cur.push(Term::Tagged(Box::new(last), tag, sp));
                        }
                        _ => return Err(perr("expected identifier", self.span())),
                    }
                    continue;
                }
                _ => {}
            }
            let t = self.parse_term()?;
            cur.push(t);
        }
        if cur.is_empty() {
            if groups.is_empty() {
                return Err(perr("expected a value", self.span()));
            }
            return Err(perr("expected a value", self.span()));
        }
        groups.push(cur);
        let end = self.prev_span();
        Ok(Value { groups, span: start.to(end) })
    }

    fn parse_term(&mut self) -> PResult<Term> {
        let t = self.tok().clone();
        match &t.tok {
            Tok::Num(v, s) => {
                self.bump();
                Ok(Term::Num(*v, s.clone(), t.span))
            }
            Tok::Percent(v, s) => {
                self.bump();
                Ok(Term::Percent(*v, s.clone(), t.span))
            }
            Tok::Str(s) => {
                self.bump();
                Ok(Term::Str(s.clone(), t.span))
            }
            Tok::Hash(h) => {
                self.bump();
                Ok(Term::Hash(h.clone(), t.span))
            }
            Tok::Var(v) => {
                self.bump();
                Ok(Term::Var(v.clone(), t.span))
            }
            Tok::Ident(name) => {
                self.bump();
                if matches!(self.peek(), Tok::LParen) && !self.tok().space_before {
                    self.bump();
                    let args = self.parse_call_args()?;
                    let sp = t.span.to(self.prev_span());
                    return Ok(Term::Call(name.clone(), args, sp));
                }
                Ok(Term::Ident(name.clone(), t.span))
            }
            Tok::LParen => {
                self.bump();
                let e = self.parse_group_body()?;
                let sp = t.span.to(self.prev_span());
                Ok(Term::Group(e, sp))
            }
            Tok::LinkOp(_) | Tok::Op(_) => Err(perr("to compute here, wrap the math in a group — e.g. (a - b)", t.span)),
            _ => Err(perr("expected a value", t.span)),
        }
    }

    // after '(' of a call: args separated by commas until ')'
    fn parse_call_args(&mut self) -> PResult<Vec<Expr>> {
        let mut args = Vec::new();
        self.skip_newlines();
        if matches!(self.peek(), Tok::RParen) {
            self.bump();
            return Ok(args);
        }
        loop {
            self.skip_newlines();
            let e = self.parse_run_expr()?;
            args.push(e);
            self.skip_newlines();
            match self.peek() {
                Tok::Comma => {
                    self.bump();
                }
                Tok::RParen => {
                    self.bump();
                    return Ok(args);
                }
                _ => return Err(perr("expected ')'", self.span())),
            }
        }
    }

    // An expression, or a space-separated run of them (`red 20%`): a run is
    // kept as a call to `RUN` and judged where it is used.
    fn parse_run_expr(&mut self) -> PResult<Expr> {
        let e = self.parse_expr()?;
        let mut run = vec![e];
        while matches!(
            self.peek(),
            Tok::Num(..) | Tok::Percent(..) | Tok::Str(_) | Tok::Var(_) | Tok::Hash(_) | Tok::Ident(_) | Tok::LParen
        ) {
            run.push(self.parse_expr()?);
        }
        if run.len() == 1 {
            return Ok(run.pop().unwrap());
        }
        let sp = run[0].span().to(run[run.len() - 1].span());
        Ok(Expr::Call(RUN.to_string(), run, sp))
    }

    // after '(' of a group: expr, tuple, or a block of local bindings
    fn parse_group_body(&mut self) -> PResult<Expr> {
        let start = self.prev_span();
        let mut locals = Vec::new();
        loop {
            self.skip_newlines();
            if let (Tok::Ident(name), Tok::Eq) = (self.peek().clone(), self.peek_at(1).clone()) {
                self.bump();
                self.bump();
                let e = self.parse_expr()?;
                locals.push((name, e));
                self.skip_newlines();
                if matches!(self.peek(), Tok::Semi) {
                    self.bump();
                }
                continue;
            }
            break;
        }
        let first = self.parse_run_expr()?;
        self.skip_newlines();
        let mut items = vec![first];
        while matches!(self.peek(), Tok::Comma) {
            self.bump();
            self.skip_newlines();
            items.push(self.parse_run_expr()?);
            self.skip_newlines();
        }
        if !matches!(self.peek(), Tok::RParen) {
            return Err(perr("expected ')'", self.span()));
        }
        let close = self.bump();
        let sp = start.to(close.span);
        let body = if items.len() == 1 { items.pop().unwrap() } else { Expr::Tuple(items, sp) };
        if locals.is_empty() {
            Ok(body)
        } else {
            Ok(Expr::Block(locals, Box::new(body), sp))
        }
    }

    // ------------------------------------------------------------- expressions
    pub fn parse_expr(&mut self) -> PResult<Expr> {
        self.parse_ternary()
    }
    fn parse_ternary(&mut self) -> PResult<Expr> {
        let c = self.parse_binary(0)?;
        self.skip_newlines();
        if matches!(self.peek(), Tok::Op(o) if o == "?") {
            self.bump();
            self.skip_newlines();
            let a = self.parse_ternary()?;
            self.skip_newlines();
            if !matches!(self.peek(), Tok::Colon) {
                return Err(perr("expected ':'", self.span()));
            }
            self.bump();
            self.skip_newlines();
            let b = self.parse_ternary()?;
            let sp = c.span().to(b.span());
            return Ok(Expr::Ternary(Box::new(c), Box::new(a), Box::new(b), sp));
        }
        Ok(c)
    }
    fn binop_prec(t: &Tok) -> Option<(&'static str, u8)> {
        match t {
            Tok::Op(o) => match o.as_str() {
                "||" => Some(("||", 1)),
                "&&" => Some(("&&", 2)),
                "==" => Some(("==", 3)),
                "!=" => Some(("!=", 3)),
                "<" => Some(("<", 4)),
                ">" => Some((">", 4)),
                "<=" => Some(("<=", 4)),
                ">=" => Some((">=", 4)),
                "+" => Some(("+", 5)),
                "-" => Some(("-", 5)),
                "*" => Some(("*", 6)),
                "/" => Some(("/", 6)),
                "%" => Some(("%", 6)),
                "^" => Some(("^", 8)),
                _ => None,
            },
            Tok::BarBar => Some(("||", 1)),
            _ => None,
        }
    }
    fn parse_binary(&mut self, min: u8) -> PResult<Expr> {
        let mut lhs = self.parse_unary()?;
        loop {
            self.skip_newlines();
            // a negative literal directly after an operand reads as subtraction
            if let Tok::Num(v, _) = self.peek().clone() {
                if v < 0.0 || self.tok().span.start < self.src.len() && self.src[self.tok().span.start..].starts_with('-') {
                    if 5 >= min && v <= 0.0 {
                        let t = self.bump();
                        let rhs_v = -v;
                        let mut rhs = Expr::Num(rhs_v, t.span);
                        // continue with higher-precedence ops binding to rhs
                        rhs = self.continue_binary(rhs, 6)?;
                        let sp = lhs.span().to(rhs.span());
                        lhs = Expr::Bin("-".into(), Box::new(lhs), Box::new(rhs), sp);
                        continue;
                    }
                }
            }
            let (op, prec) = match Self::binop_prec(self.peek()) {
                Some(x) => x,
                None => break,
            };
            if prec < min {
                break;
            }
            self.bump();
            self.skip_newlines();
            // ^ is right-associative
            let next_min = if op == "^" { prec } else { prec + 1 };
            let rhs = self.parse_binary(next_min)?;
            let sp = lhs.span().to(rhs.span());
            lhs = Expr::Bin(op.to_string(), Box::new(lhs), Box::new(rhs), sp);
        }
        Ok(lhs)
    }
    fn continue_binary(&mut self, mut lhs: Expr, min: u8) -> PResult<Expr> {
        loop {
            self.skip_newlines();
            let (op, prec) = match Self::binop_prec(self.peek()) {
                Some(x) => x,
                None => break,
            };
            if prec < min {
                break;
            }
            self.bump();
            self.skip_newlines();
            let next_min = if op == "^" { prec } else { prec + 1 };
            let rhs = self.parse_binary(next_min)?;
            let sp = lhs.span().to(rhs.span());
            lhs = Expr::Bin(op.to_string(), Box::new(lhs), Box::new(rhs), sp);
        }
        Ok(lhs)
    }
    fn parse_unary(&mut self) -> PResult<Expr> {
        let t = self.tok().clone();
        match &t.tok {
            Tok::Op(o) if o == "-" || o == "!" || o == "+" => {
                self.bump();
                let e = self.parse_unary_pow()?;
                let sp = t.span.to(e.span());
                Ok(Expr::Unary(o.clone(), Box::new(e), sp))
            }
            _ => self.parse_postfix(),
        }
    }
    // unary minus binds looser than ^ : -x^2 = -(x^2)
    fn parse_unary_pow(&mut self) -> PResult<Expr> {
        let base = self.parse_unary()?;
        self.skip_newlines();
        if matches!(self.peek(), Tok::Op(o) if o == "^") {
            self.bump();
            let rhs = self.parse_binary(8)?;
            let sp = base.span().to(rhs.span());
            return Ok(Expr::Bin("^".into(), Box::new(base), Box::new(rhs), sp));
        }
        Ok(base)
    }
    fn parse_postfix(&mut self) -> PResult<Expr> {
        let t = self.tok().clone();
        match &t.tok {
            Tok::Num(v, _) => {
                self.bump();
                Ok(Expr::Num(*v, t.span))
            }
            Tok::Percent(v, _) => {
                self.bump();
                Ok(Expr::Percent(*v, t.span))
            }
            Tok::Str(s) => {
                self.bump();
                Ok(Expr::Str(s.clone(), t.span))
            }
            Tok::Var(v) => {
                self.bump();
                Ok(Expr::Var(v.clone(), t.span))
            }
            Tok::Hash(h) => {
                self.bump();
                Ok(Expr::Hash(h.clone(), t.span))
            }
            Tok::Ident(name) => {
                self.bump();
                if matches!(self.peek(), Tok::LParen) {
                    self.bump();
                    let args = self.parse_call_args()?;
                    let sp = t.span.to(self.prev_span());
                    return Ok(Expr::Call(name.clone(), args, sp));
                }
                Ok(Expr::Ident(name.clone(), t.span))
            }
            Tok::LParen => {
                self.bump();
                let e = self.parse_group_body()?;
                Ok(e)
            }
            _ => Err(perr("expected a value", t.span)),
        }
    }

    // ------------------------------------------------------------- statements
    fn parse_children(&mut self) -> PResult<Vec<Stmt>> {
        self.bump(); // [
        let mut out = Vec::new();
        loop {
            self.skip_seps();
            match self.peek() {
                Tok::RBrack => {
                    self.bump();
                    return Ok(out);
                }
                Tok::Eof => return Err(perr("expected ']'", self.span())),
                _ => {}
            }
            let s = self.parse_stmt(true)?;
            out.push(s);
            match self.peek() {
                Tok::Newline | Tok::Semi | Tok::RBrack => {}
                // several bare strings may share a line inside [ ]
                Tok::Str(_) if matches!(out.last(), Some(Stmt::Text(_))) => {}
                _ => return Err(perr(SEP_ERR, self.span())),
            }
        }
    }

    fn parse_stmt(&mut self, _in_children: bool) -> PResult<Stmt> {
        let start = self.span();
        match self.peek().clone() {
            Tok::Bar => {
                let node = self.parse_node()?;
                if matches!(self.peek(), Tok::LinkOp(_) | Tok::Amp | Tok::DimOp(_) | Tok::BarBar) {
                    return Err(perr(SEP_ERR, self.span()));
                }
                Ok(Stmt::Node(node))
            }
            Tok::Str(s) => {
                self.bump();
                let mut classes = Vec::new();
                while let Tok::Class(c) = self.peek().clone() {
                    self.bump();
                    classes.push(c);
                }
                let mut style = None;
                if matches!(self.peek(), Tok::LBrace) {
                    style = Some(self.parse_style_block()?.0);
                }
                Ok(Stmt::Text(TextStmt { text: s, classes, style, span: start.to(self.prev_span()) }))
            }
            Tok::Ident(_) => self.parse_link(),
            Tok::Var(_) => Err(perr("variables are declared in the stylesheet '{ }'", start)),
            _ => Err(perr("a node leads with bars — write '|box#X|' (a bare name is a link endpoint)", start)),
        }
    }

    fn parse_node(&mut self) -> PResult<NodeStmt> {
        let start = self.span();
        self.bump(); // |
        let mut type_name = None;
        let mut id = None;
        if let Tok::Ident(t) = self.peek().clone() {
            self.bump();
            type_name = Some(t);
        }
        if let Tok::Hash(h) = self.peek().clone() {
            self.bump();
            id = Some(h);
        }
        if !matches!(self.peek(), Tok::Bar) {
            if type_name.is_none() && id.is_none() {
                return Err(perr("'| |' needs a type or an '#id'", start));
            }
            return Err(perr("expected '|'", self.span()));
        }
        let bar = self.bump();
        if type_name.is_none() && id.is_none() {
            return Err(perr("'| |' needs a type or an '#id'", start));
        }
        let head_span = start.to(bar.span);
        let mut node = NodeStmt {
            type_name,
            id,
            label: None,
            classes: vec![],
            classes_span: None,
            style: None,
            style_span: None,
            children: None,
            span: head_span,
            head_span,
        };
        self.parse_node_tail(&mut node)?;
        node.span = start.to(self.prev_span());
        Ok(node)
    }

    fn parse_node_tail(&mut self, node: &mut NodeStmt) -> PResult<()> {
        if let Tok::Str(s) = self.peek().clone() {
            let t = self.bump();
            node.label = Some((s, t.span));
            if matches!(self.peek(), Tok::Str(_)) {
                return Err(perr("one inline label — put two or more in a '[ ]'", self.span()));
            }
        }
        if let Tok::Class(_) = self.peek() {
            let cs = self.span();
            while let Tok::Class(c) = self.peek().clone() {
                if self.tok().space_before && !node.classes.is_empty() {
                    return Err(perr("classes glue into a chain — write '.hot.loud', no space", self.span()));
                }
                self.bump();
                node.classes.push(c);
            }
            node.classes_span = Some(cs.to(self.prev_span()));
            if matches!(self.peek(), Tok::Str(_)) {
                return Err(perr("a label comes before classes — write '|box| \"X\" .hot'", self.span()));
            }
        }
        if matches!(self.peek(), Tok::LBrace) {
            let (d, sp) = self.parse_style_block()?;
            node.style = Some(d);
            node.style_span = Some(sp);
            if matches!(self.peek(), Tok::Str(_)) {
                return Err(perr("a label comes before classes — write '|box| \"X\" .hot'", self.span()));
            }
        }
        if matches!(self.peek(), Tok::LBrack) {
            node.children = Some(self.parse_children()?);
        }
        Ok(())
    }

    fn parse_path(&mut self) -> PResult<PathRef> {
        let start = self.span();
        let mut parts = Vec::new();
        match self.peek().clone() {
            Tok::Ident(n) => {
                self.bump();
                parts.push(n);
            }
            _ => return Err(perr("expected identifier", self.span())),
        }
        let mut index = None;
        loop {
            match self.peek().clone() {
                Tok::Dot => {
                    self.bump();
                    match self.peek().clone() {
                        Tok::Ident(n) => {
                            self.bump();
                            parts.push(n);
                        }
                        Tok::Num(v, _) => {
                            self.bump();
                            index = Some(v as u32);
                            break;
                        }
                        _ => return Err(perr("expected identifier", self.span())),
                    }
                }
                Tok::Num(v, s) if s.starts_with('.') && !self.tok().space_before => {
                    self.bump();
                    let digits = &s[1..];
                    index = Some(digits.parse::<u32>().unwrap_or(v as u32));
                    break;
                }
                _ => break,
            }
        }
        let mut anchor = None;
        if matches!(self.peek(), Tok::Colon) {
            self.bump();
            match self.peek().clone() {
                Tok::Ident(a) => {
                    self.bump();
                    anchor = Some(a);
                }
                _ => return Err(perr("expected identifier", self.span())),
            }
        }
        Ok(PathRef { parts, index, anchor, span: start.to(self.prev_span()) })
    }

    fn parse_endpoint(&mut self) -> PResult<Endpoint> {
        match self.peek().clone() {
            Tok::Ident(_) => Ok(Endpoint::Path(self.parse_path()?)),
            Tok::Bar => {
                let start = self.span();
                self.bump();
                let mut type_name = None;
                let mut id = None;
                if let Tok::Ident(t) = self.peek().clone() {
                    self.bump();
                    type_name = Some(t);
                }
                if let Tok::Hash(h) = self.peek().clone() {
                    self.bump();
                    id = Some(h);
                }
                if !matches!(self.peek(), Tok::Bar) {
                    if type_name.is_none() && id.is_none() {
                        return Err(perr("'| |' needs a type or an '#id'", start));
                    }
                    return Err(perr("expected '|'", self.span()));
                }
                let bar = self.bump();
                if type_name.is_none() && id.is_none() {
                    return Err(perr("'| |' needs a type or an '#id'", start));
                }
                let head_span = start.to(bar.span);
                Ok(Endpoint::Node(Box::new(NodeStmt {
                    type_name,
                    id,
                    label: None,
                    classes: vec![],
                    classes_span: None,
                    style: None,
                    style_span: None,
                    children: None,
                    span: head_span,
                    head_span,
                })))
            }
            Tok::Str(s) => {
                let t = self.bump();
                Ok(Endpoint::Text(s, t.span))
            }
            _ => Err(perr("expected identifier", self.span())),
        }
    }

    fn parse_fan(&mut self) -> PResult<Vec<Endpoint>> {
        let mut eps = vec![self.parse_endpoint()?];
        while matches!(self.peek(), Tok::Amp) {
            self.bump();
            eps.push(self.parse_endpoint()?);
        }
        Ok(eps)
    }

    fn parse_link(&mut self) -> PResult<Stmt> {
        let start = self.span();
        let first = self.parse_fan()?;
        let mut groups = vec![first];
        let mut ops = Vec::new();
        loop {
            match self.peek().clone() {
                Tok::LinkOp(op) | Tok::DimOp(op) => {
                    let t = self.bump();
                    ops.push((op, t.span));
                }
                Tok::BarBar => {
                    let t = self.bump();
                    ops.push(("||".to_string(), t.span));
                }
                _ => break,
            }
            // one-ended forms: 'a (o)' or 'a <- "text"'
            match self.peek() {
                Tok::Ident(_) | Tok::Bar => {
                    groups.push(self.parse_fan()?);
                }
                _ => break,
            }
        }
        if ops.is_empty() {
            // a bare endpoint, or something that looks like a declaration
            let had_colon = groups[0].iter().any(|e| matches!(e, Endpoint::Path(p) if p.anchor.is_some()));
            if had_colon || matches!(self.peek(), Tok::Colon) {
                return Err(Diag::error("declaration-outside-block", "a declaration belongs in a '{ }' block", start));
            }
            return Err(perr("a node leads with bars — write '|box#X|' (a bare name is a link endpoint)", start));
        }
        let mut link = LinkStmt {
            groups,
            ops,
            label: None,
            classes: vec![],
            style: None,
            labels: None,
            span: start,
        };
        if let Tok::Str(s) = self.peek().clone() {
            let t = self.bump();
            link.label = Some((s, t.span));
            if matches!(self.peek(), Tok::Str(_)) {
                return Err(perr("one inline label — put two or more in a '[ ]'", self.span()));
            }
        }
        while let Tok::Class(c) = self.peek().clone() {
            if self.tok().space_before && !link.classes.is_empty() {
                return Err(perr("classes glue into a chain — write '.hot.loud', no space", self.span()));
            }
            self.bump();
            link.classes.push(c);
        }
        if matches!(self.peek(), Tok::Str(_)) {
            return Err(perr("a label comes before classes — write '|box| \"X\" .hot'", self.span()));
        }
        if matches!(self.peek(), Tok::LBrace) {
            link.style = Some(self.parse_style_block()?.0);
            if matches!(self.peek(), Tok::Str(_)) {
                return Err(perr("a label comes before classes — write '|box| \"X\" .hot'", self.span()));
            }
        }
        if matches!(self.peek(), Tok::LBrack) {
            link.labels = Some(self.parse_children()?);
        }
        link.span = start.to(self.prev_span());
        Ok(Stmt::Link(link))
    }
}

pub fn parse(src: &str) -> Result<(Doc, Vec<crate::lexer::Comment>), Diag> {
    // the first syntax error exactly as the reference reports it (shared with fmt)
    crate::format::syntax_check(src)?;
    let lexed = crate::lexer::lex(src)?;
    let mut p = Parser::new(&lexed.tokens, src);
    let doc = p.parse_doc()?;
    Ok((doc, lexed.comments))
}
