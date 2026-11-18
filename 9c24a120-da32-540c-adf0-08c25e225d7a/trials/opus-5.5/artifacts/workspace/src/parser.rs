// Recursive-descent parser with an offside rule driven by token columns.

use crate::ast::*;
use crate::diag::Diag;
use crate::lexer::{describe, FPiece, Tok, Token};
use crate::source::Span;

#[derive(Clone, Copy, Debug)]
enum Layout {
    /// statements of a block start at this column
    Block(usize),
    /// inside brackets: line breaks mean nothing
    NoLayout,
    /// one item of a computation expression body
    CeItem { item_col: usize, line: usize, kw: &'static str },
}

pub struct Parser {
    toks: Vec<Token>,
    pos: usize,
    layout: Vec<Layout>,
    docs: Vec<(usize, String)>,
    pub errors: Vec<Diag>,
    /// index of a token that starts a statement: never a layout boundary
    anchor: usize,
    /// language-server mode: report every declaration's error, leaving the
    /// blocks an error happened in open (they shape the recovery)
    recovering: bool,
    /// recovering from a match header left without its `:` (the arms'
    /// block is entered while skipping)
    open_arms: bool,
    /// where the last closed block ended: (token index, offset of the token
    /// that closed it). A construct ending with a block runs up to there.
    block_end: Option<(usize, usize)>,
    /// inside a module body (where active patterns are not declared)
    in_module: bool,
}

type PResult<T> = Result<T, Diag>;

fn is_continuation(t: &Tok) -> bool {
    // `in` (of `for x in xs`) continues a line like an operator would, and
    // so does a name starting with `_` (and `_` itself)
    if let Tok::Ident(n) | Tok::Upper(n) = t {
        return n == "in" || n.starts_with('_');
    }
    matches!(
        t,
        Tok::Plus
            | Tok::Minus
            | Tok::Star
            | Tok::Slash
            | Tok::SlashSlash
            | Tok::Percent
            | Tok::StarStar
            | Tok::EqEq
            | Tok::NotEq
            | Tok::Lt
            | Tok::Le
            | Tok::Gt
            | Tok::Ge
            | Tok::PipeRight
            | Tok::PipeLeft
            | Tok::ComposeRight
            | Tok::ComposeLeft
            | Tok::And
            | Tok::Or
            | Tok::Dot
            | Tok::Eq
            | Tok::Arrow
            | Tok::Colon
            | Tok::Bar
            | Tok::Then
            | Tok::Elif
            | Tok::Else
            | Tok::With
            | Tok::RParen
            | Tok::RBracket
            | Tok::RBrace
            | Tok::Comma
            | Tok::LArrow
            | Tok::Hole(_)
            | Tok::Underscore
            | Tok::Caret
    )
}

fn starts_atom(t: &Tok) -> bool {
    matches!(
        t,
        Tok::Int(_)
            | Tok::Float(_)
            | Tok::Str(_)
            | Tok::FStr(_)
            | Tok::Ident(_)
            | Tok::Upper(_)
            | Tok::Hole(_)
            | Tok::True
            | Tok::False
            | Tok::LParen
            | Tok::LBracket
            | Tok::LBrace
    )
}

/// What makes a pattern able to fail: the first part of it that can.
fn refutable_kind(p: &Pat) -> Option<&'static str> {
    match &p.kind {
        PatKind::Wild | PatKind::Var(_) => None,
        PatKind::Tuple(ps) => ps.iter().find_map(refutable_kind),
        PatKind::Record(_, _, _, fs) => fs.iter().find_map(|(_, _, sub)| sub.as_ref().and_then(refutable_kind)),
        PatKind::Int(_) | PatKind::Str(_) | PatKind::Bool(_) | PatKind::Unit => Some("a literal pattern"),
        PatKind::List(_) => Some("a list pattern"),
        PatKind::Or(_) => Some("an or-pattern"),
        PatKind::As(..) => Some("an as-pattern"),
        PatKind::Ctor(..) => Some("a constructor pattern"),
    }
}

/// Tokens that can begin an expression.
/// Punctuation that can neither start a statement nor continue one.
fn non_starter(t: &Tok) -> bool {
    matches!(t, Tok::Bang | Tok::Underscore | Tok::Caret | Tok::Ellipsis)
}

fn starts_expr(t: &Tok) -> bool {
    starts_atom(t) || matches!(t, Tok::Minus | Tok::Not | Tok::Try | Tok::If | Tok::Fun | Tok::Match | Tok::LexError)
}

#[derive(PartialEq)]
enum Boundary {
    No,
    Statement,
    Block,
}

impl Parser {
    pub fn new(toks: Vec<Token>, docs: Vec<(usize, String)>) -> Parser {
        Parser { toks, pos: 0, layout: vec![Layout::Block(1)], docs, errors: Vec::new(), anchor: usize::MAX, recovering: false, open_arms: false, block_end: None, in_module: false }
    }

    // ---- token access -------------------------------------------------

    /// Pass over what failed to lex (outside expressions it has no place).
    fn skip_lex_errors(&mut self) {
        while self.raw().tok == Tok::LexError {
            self.bump();
        }
    }

    fn raw(&self) -> &Token {
        &self.toks[self.pos.min(self.toks.len() - 1)]
    }
    fn raw_at(&self, k: usize) -> &Token {
        &self.toks[(self.pos + k).min(self.toks.len() - 1)]
    }

    /// Inside a block nested below the top level (the end of input then
    /// ends that block first).
    fn in_nested_block(&self) -> bool {
        self.layout.iter().skip(1).any(|l| matches!(l, Layout::Block(c) if *c > 0))
    }

    fn boundary_of(&self, t: &Token) -> Boundary {
        if t.tok == Tok::Eof {
            return if self.in_nested_block() { Boundary::Block } else { Boundary::Statement };
        }
        if !t.bol || t.span.lo == self.anchor {
            return Boundary::No;
        }
        // a continuation left of the top level's column continues, however
        // deep
        if let Some(Layout::Block(top)) = self.layout.first() {
            if t.col < *top && self.layout.len() > 1 && is_continuation(&t.tok) {
                return Boundary::No;
            }
        }
        match self.layout.last() {
            None | Some(Layout::NoLayout) => Boundary::No,
            Some(Layout::Block(col)) => {
                // the top level never ends: a line left of it continues
                if t.col < *col && self.layout.len() == 1 {
                    Boundary::No
                } else if t.col < *col && self.awaits_operand(t) && self.layout.iter().any(|l| matches!(l, Layout::CeItem { .. })) {
                    // (inside a computation-expression item an operand still
                    // awaited is taken from wherever its line starts)
                    Boundary::No
                } else if t.col < *col {
                    Boundary::Block
                } else if t.col == *col && !is_continuation(&t.tok) {
                    Boundary::Statement
                } else {
                    Boundary::No
                }
            }
            Some(Layout::CeItem { item_col, .. }) => {
                // a computation-expression item runs until a line starts at
                // or before the item's column (operators there continue it,
                // and an operand an operator still waits for is taken)
                // (a hole or a `_` name there is an item of its own)
                let continues = is_continuation(&t.tok) && !matches!(&t.tok, Tok::Hole(_) | Tok::Ident(_) | Tok::Upper(_));
                if t.col > *item_col || continues || self.awaits_operand(t) {
                    Boundary::No
                } else if t.col == *item_col {
                    Boundary::Statement
                } else {
                    Boundary::Block
                }
            }
        }
    }

    /// `t` is the next token and the one before it needs something after it.
    fn awaits_operand(&self, t: &Token) -> bool {
        if self.pos == 0 || t.span.lo != self.raw().span.lo {
            return false;
        }
        matches!(
            self.toks[self.pos - 1].tok,
            Tok::Plus
                | Tok::Minus
                | Tok::Star
                | Tok::Slash
                | Tok::SlashSlash
                | Tok::Percent
                | Tok::StarStar
                | Tok::EqEq
                | Tok::NotEq
                | Tok::Lt
                | Tok::Le
                | Tok::Gt
                | Tok::Ge
                | Tok::PipeRight
                | Tok::PipeLeft
                | Tok::ComposeRight
                | Tok::ComposeLeft
                | Tok::And
                | Tok::Or
                | Tok::Not
                | Tok::Dot
                | Tok::Arrow
                | Tok::Then
                | Tok::Else
                | Tok::Colon
                | Tok::LArrow
                | Tok::If
                | Tok::Elif
                | Tok::Match
                | Tok::Case
        )
    }

    fn at_boundary(&self) -> bool {
        self.boundary_of(self.raw()) != Boundary::No
    }

    /// The next token if it is not cut off by layout.
    fn peek(&self) -> Option<&Tok> {
        let t = self.raw();
        if self.boundary_of(t) != Boundary::No {
            None
        } else {
            Some(&t.tok)
        }
    }

    fn check(&self, t: &Tok) -> bool {
        self.peek() == Some(t)
    }

    fn bump(&mut self) -> Token {
        let t = self.raw().clone();
        if self.pos < self.toks.len() - 1 {
            self.pos += 1;
        }
        t
    }

    fn eat(&mut self, t: &Tok) -> bool {
        if self.check(t) {
            self.bump();
            true
        } else {
            false
        }
    }

    fn describe_next(&self) -> String {
        let t = self.raw();
        if t.tok == Tok::Eof {
            return if self.in_nested_block() { "end of block".into() } else { "end of input".into() };
        }
        if matches!(self.layout.last(), Some(Layout::CeItem { .. })) {
            return describe(&t.tok);
        }
        match self.boundary_of(t) {
            Boundary::Block => "end of block".into(),
            Boundary::Statement => "end of statement".into(),
            Boundary::No => describe(&t.tok),
        }
    }

    fn next_span(&self) -> Span {
        self.raw().span
    }

    /// `{msg}, found X` at the next token.
    fn err_expected_msg(&self, msg: &str) -> Diag {
        Diag::error(format!("{}, found {}", msg, self.describe_next()), self.err_span())
    }

    fn err_expected(&self, what: &str) -> Diag {
        Diag::error(format!("expected {}, found {}", what, self.describe_next()), self.err_span())
    }

    fn expect(&mut self, t: &Tok, what: &str) -> PResult<Token> {
        if self.check(t) {
            Ok(self.bump())
        } else {
            Err(self.err_expected(what))
        }
    }

    fn prev_end(&self) -> usize {
        if let Some((p, off)) = self.block_end {
            if p == self.pos {
                return off;
            }
        }
        if self.pos == 0 {
            0
        } else {
            self.toks[self.pos - 1].span.hi
        }
    }

    /// A block just closed: what ends with it ends where the next token starts.
    fn mark_block_end(&mut self) {
        self.block_end = Some((self.pos, self.raw().span.lo));
    }

    /// Close a block; after an error in recovery mode it stays open.
    fn pop_block<T>(&mut self, r: &PResult<T>) {
        if r.is_ok() || !self.recovering {
            self.layout.pop();
        }
        // inside a computation expression's items, blocks end at their text
        if r.is_ok() && !self.layout.iter().any(|l| matches!(l, Layout::CeItem { .. })) {
            self.mark_block_end();
        }
    }

    fn with_layout<T>(&mut self, l: Layout, f: impl FnOnce(&mut Parser) -> PResult<T>) -> PResult<T> {
        let at = self.layout.len();
        self.layout.push(l);
        let r = f(self);
        if r.is_ok() || !self.recovering {
            self.layout.pop();
        } else if at < self.layout.len() {
            // after an error (recovering) a bracket stays open: it shapes
            // where parsing can pick up again (a computation expression's
            // braces too); other layouts go, leaving what opened inside
            match l {
                Layout::NoLayout => {}
                Layout::Block(0) => self.layout[at] = Layout::NoLayout,
                _ => {
                    self.layout.remove(at);
                }
            }
        }
        r
    }

    /// The closing bracket of a bracketed construct; when it is missing the
    /// bracket is still open for recovery.
    fn close_bracket(&mut self, t: &Tok, what: &str) -> PResult<Token> {
        let r = self.expect_raw(t, what);
        if r.is_err() && self.recovering {
            self.layout.push(Layout::NoLayout);
        }
        r
    }

    // ---- program ------------------------------------------------------

    /// The top level's column is where the first declaration starts.
    fn set_top_column(&mut self) {
        let c = self.raw().col.max(1);
        self.layout[0] = Layout::Block(if self.raw().tok == Tok::Eof { 1 } else { c });
    }

    pub fn program(&mut self) -> PResult<Program> {
        self.set_top_column();
        let mut decls = Vec::new();
        let mut last_line = 0usize;
        while self.raw().tok != Tok::Eof {
            let doc = self.take_doc(last_line, self.raw().line);
            if self.raw().tok == Tok::Bar && self.raw_at(1).tok == Tok::Bar {
                return Err(Diag::error("use `or` instead of `||`", self.raw().span));
            }
            let d = self.decl(doc)?;
            decls.push(d);
            last_line = self.toks[self.pos.saturating_sub(1)].line;
            let _ = last_line;
            last_line = self.line_before();
        }
        Ok(Program { decls })
    }

    /// Parse every declaration that parses, collecting each one's error and
    /// skipping to where the next can start (the language server's view).
    pub fn program_recover(&mut self) -> (Program, Vec<Diag>) {
        self.recovering = true;
        self.set_top_column();
        let mut decls = Vec::new();
        let mut errors = Vec::new();
        let mut last_line = 0usize;
        loop {
            if self.raw().tok == Tok::Eof && !self.in_nested_block() {
                break;
            }
            // (what failed to lex where a declaration starts is passed over)
            if self.raw().tok == Tok::LexError {
                self.bump();
                continue;
            }
            let doc = self.take_doc(last_line, self.raw().line);
            let r = if self.raw().tok == Tok::Bar && self.raw_at(1).tok == Tok::Bar {
                Err(Diag::error("use `or` instead of `||`", self.raw().span))
            } else {
                self.decl(doc)
            };
            match r {
                Ok(d) => decls.push(d),
                Err(e) => {
                    let sp = e.span;
                    errors.push(e);
                    self.recover(sp);
                }
            }
            last_line = self.line_before();
        }
        (Program { decls }, errors)
    }

    /// Skip to the next statement start, closing blocks the input leaves.
    fn recover(&mut self, at: Span) {
        // brackets opened while skipping hide everything until they close
        let mut depth = 0usize;
        // (after a match header without its `:`, the block the first
        // skipped line ending in `:` opens is entered)
        let mut entered = !std::mem::replace(&mut self.open_arms, false);
        // the token the error is about goes (an error about where a
        // statement ends points between tokens, and keeps the next one)
        if self.raw().tok != Tok::Eof && at.hi > at.lo && self.raw().span.lo == at.lo {
            self.skip_token(&mut depth);
        }
        loop {
            let t = self.raw().clone();
            if t.tok == Tok::Eof {
                self.layout.truncate(1);
                return;
            }
            if depth > 0 {
                self.skip_token(&mut depth);
                continue;
            }
            // a line starting at the top level's column begins a declaration
            let top = match self.layout[0] {
                Layout::Block(c) => c,
                _ => 1,
            };
            let in_brackets = self.layout.iter().any(|l| matches!(l, Layout::NoLayout));
            if t.bol && t.col == top && !is_continuation(&t.tok) && !in_brackets {
                self.layout.truncate(1);
                return;
            }
            match self.boundary_of(&t) {
                Boundary::Statement => return,
                Boundary::Block => {
                    if self.layout.len() > 1 {
                        self.layout.pop();
                    } else {
                        return;
                    }
                }
                Boundary::No => {
                    self.skip_token(&mut depth);
                    // a `:` ending its line opens the block indented after
                    // it, whose lines are statements again
                    let n = self.raw().clone();
                    if t.tok == Tok::Colon && depth == 0 && n.bol && n.tok != Tok::Eof && !entered {
                        if let Some(Layout::Block(c)) = self.layout.last() {
                            if n.col > *c {
                                self.layout.push(Layout::Block(n.col));
                                self.anchor = n.span.lo;
                                entered = true;
                            }
                        }
                    }
                }
            }
        }
    }

    /// Skip a token while recovering, keeping track of brackets; a closing
    /// bracket with none open closes one the error left open.
    fn skip_token(&mut self, depth: &mut usize) {
        let t = self.bump();
        match t.tok {
            Tok::LParen | Tok::LBracket | Tok::LBrace => *depth += 1,
            Tok::RParen | Tok::RBracket | Tok::RBrace => {
                if *depth > 0 {
                    *depth -= 1;
                } else if matches!(self.layout.last(), Some(Layout::NoLayout)) {
                    self.layout.pop();
                }
            }
            _ => {}
        }
    }

    fn line_before(&self) -> usize {
        if self.pos == 0 {
            0
        } else {
            // the line on which the previous token ends
            let t = &self.toks[self.pos - 1];
            t.line + 0
        }
    }

    fn take_doc(&mut self, after_line: usize, line: usize) -> Option<String> {
        let mut lines = Vec::new();
        for (l, text) in &self.docs {
            if *l > after_line && *l < line {
                lines.push(text.clone());
            }
        }
        if lines.is_empty() {
            None
        } else {
            Some(lines.join("\n"))
        }
    }

    fn decl(&mut self, doc: Option<String>) -> PResult<Decl> {
        if self.boundary_of(self.raw()) == Boundary::Block {
            return Err(self.err_expected("an expression"));
        }
        let start = self.raw().span.lo;
        self.anchor = start;
        if let Some(e) = self.python_def() {
            return Err(e);
        }
        match self.raw().tok.clone() {
            Tok::Let => {
                let top = !self.in_module;
                let l = self.let_decl(doc, top)?;
                Ok(Decl::Let(l))
            }
            Tok::Type => self.type_decl(doc, false),
            // (`opaque type` on one line, or with `type` continuing it)
            Tok::Ident(ref s) if s == "opaque" && self.raw_at(1).tok == Tok::Type && self.boundary_of(self.raw_at(1)) == Boundary::No => {
                self.bump();
                let mut d = self.type_decl(doc, true)?;
                // the declaration starts at `opaque`
                if let Decl::Type(t) = &mut d {
                    t.span = Span::new(start, t.span.hi);
                }
                Ok(d)
            }
            Tok::Measure => self.measure_decl(),
            Tok::Extern => self.extern_decl(doc),
            Tok::Import => {
                let kw = self.bump();
                match self.peek().cloned() {
                    Some(Tok::Upper(n)) => {
                        let t = self.bump();
                        Ok(Decl::Import(n, kw.span.to(t.span)))
                    }
                    _ => Err(self.err_expected("an imported module name")),
                }
            }
            Tok::Module => self.module_decl(),
            _ => {
                // expression statement (or assignment)
                let _ = start;
                let e = self.expr()?;
                Ok(match e.kind {
                    ExprKind::Assign(n, ns, v) => Decl::Assign(n, ns, *v, e.span),
                    kind => Decl::Expr(Expr { kind, span: e.span }),
                })
            }
        }
    }

    fn module_decl(&mut self) -> PResult<Decl> {
        let kw = self.bump();
        let (name, nspan) = match self.peek().cloned() {
            Some(Tok::Upper(n)) => {
                let t = self.bump();
                (n, t.span)
            }
            _ => return Err(self.err_expected("module name")),
        };
        self.expect(&Tok::Eq, "`=`")?;
        let first = self.raw().clone();
        // (indented past the declaration's own line)
        if first.tok == Tok::Eof || !first.bol || self.boundary_of(&first) != Boundary::No || first.col <= kw.col || !self.indented_block_start(&first) {
            return Err(self.err_expected("an indented module body"));
        }
        let col = first.col;
        let mut decls = Vec::new();
        self.layout.push(Layout::Block(col));
        let outer = std::mem::replace(&mut self.in_module, true);
        let r = (|| -> PResult<()> {
            loop {
                let doc_line = self.raw().line;
                let doc = self.take_doc(self.line_before(), doc_line);
                if self.raw().tok != Tok::Let {
                    self.anchor = self.raw().span.lo;
                    return Err(Diag::error(format!("a module body may only contain `let` bindings, found {}", self.raw_describe()), self.raw_span()));
                }
                let d = self.decl(doc)?;
                decls.push(d);
                let t = self.raw().clone();
                if t.tok == Tok::Eof || (t.bol && t.col < col) {
                    break;
                }
                if self.boundary_of(&t) == Boundary::Statement {
                    if non_starter(&t.tok) {
                        return Err(Diag::error(format!("expected end of the module body, found {}", self.raw_describe()), self.raw_span()));
                    }
                    continue;
                }
                return Err(self.err_expected("end of the module body"));
            }
            Ok(())
        })();
        self.in_module = outer;
        self.pop_block(&r);
        r?;
        let _ = kw;
        Ok(Decl::Module(name, nspan, decls))
    }

    // ---- let ----------------------------------------------------------

    /// `top`: a declaration of the program itself (not of a block or module).
    fn let_decl(&mut self, doc: Option<String>, top: bool) -> PResult<LetDecl> {
        let kw = self.bump(); // let
        let mut mutable = false;
        let mut pure_ = false;
        // (the modifiers may come in any number and order)
        loop {
            if self.check(&Tok::Mut) {
                self.bump();
                mutable = true;
            } else if self.check(&Tok::Pure) {
                self.bump();
                pure_ = true;
            } else {
                break;
            }
        }
        // active pattern `(|A|B|)`
        if self.check(&Tok::LParen) && self.raw_at(1).tok == Tok::Bar {
            if !top || mutable || pure_ {
                return Err(Diag::error(
                    format!("an active pattern is declared as a plain top-level `let (|A|B|) …` (no `mut`/`pure`, not inside a block or module), found {}", self.raw_describe()),
                    self.raw_span(),
                ));
            }
            let lp = self.bump();
            self.bump();
            let (cases, case_spans) = self.with_layout(Layout::NoLayout, |p| {
                let mut cases = Vec::new();
                let mut case_spans = Vec::new();
                loop {
                    match p.raw().tok.clone() {
                        Tok::Upper(n) => {
                            let t = p.bump();
                            cases.push(n);
                            case_spans.push(t.span);
                        }
                        Tok::Underscore => {
                            let t = p.bump();
                            cases.push("_".into());
                            case_spans.push(t.span);
                        }
                        _ => return Err(p.err_expected("an active-pattern case name")),
                    }
                    p.expect(&Tok::Bar, "`|`")?;
                    if p.check(&Tok::RParen) {
                        break;
                    }
                    // a partial pattern's `_` is its last case
                    if cases.last().map_or(false, |c| c == "_") {
                        return Err(p.err_expected("`)` closing the active pattern"));
                    }
                }
                Ok((cases, case_spans))
            })?;
            let rp = self.close_bracket(&Tok::RParen, "`)`")?;
            let name_span = lp.span.to(rp.span);
            let pat = Pat { kind: PatKind::Var(format!("(|{}|)", cases.join("|"))), span: name_span };
            let mut params = Vec::new();
            while matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Upper(_)) | Some(Tok::Underscore) | Some(Tok::LParen)) {
                params.push(self.param_pat()?);
            }
            if params.is_empty() {
                return Err(self.err_expected_msg("an active pattern needs a parameter (the match input)"));
            }
            // (parameters before the input are a partial pattern's alone)
            if params.len() > 1 && cases.last().map_or(false, |c| c != "_") {
                return Err(Diag::error(
                    "a total active pattern takes exactly one parameter (the match input); only a partial active pattern (`(|A|_|)`) can take extra parameters",
                    Span::new(kw.span.lo, self.prev_end()),
                ));
            }
            self.expect(&Tok::Eq, "`=`")?;
            let value = self.body()?;
            let span = kw.span.to(value.span);
            return Ok(LetDecl { pat, params, mutable, pure_, value, doc, name_span, span, active: Some(cases), case_spans });
        }
        let t = self.raw().clone();
        let (pat, params) = match &t.tok {
            Tok::Ident(n) if self.boundary_of(&t) == Boundary::No => {
                self.bump();
                let pat = Pat { kind: PatKind::Var(n.clone()), span: t.span };
                let mut params = Vec::new();
                while matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Upper(_)) | Some(Tok::Underscore) | Some(Tok::LParen)) {
                    params.push(self.param_pat()?);
                }
                if n == "rec" && !params.is_empty() {
                    return Err(Diag::error(
                        "`rec` is not a keyword in Pyfun — a `let` function is already recursive in its own body, so drop `rec` (write `let f x = …`)",
                        t.span,
                    ));
                }
                (pat, params)
            }
            Tok::Underscore if self.boundary_of(&t) == Boundary::No => {
                self.bump();
                let mut params = Vec::new();
                while matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Upper(_)) | Some(Tok::Underscore) | Some(Tok::LParen)) {
                    params.push(self.param_pat()?);
                }
                if !params.is_empty() {
                    return Err(self.err_expected_msg("a discard binding `_` cannot take parameters"));
                }
                (Pat { kind: PatKind::Wild, span: t.span }, Vec::new())
            }
            Tok::LParen if self.boundary_of(&t) == Boundary::No => {
                let p = self.pattern()?;
                self.check_let_pattern(&p)?;
                self.no_destructuring_params(&p)?;
                (p, Vec::new())
            }
            Tok::Upper(n) if self.boundary_of(&t) == Boundary::No => {
                // a record pattern `P { x, y }` binds; a constructor does not
                if self.raw_at(1).tok == Tok::LBrace && self.boundary_of(self.raw_at(1)) == Boundary::No {
                    let p = self.pattern()?;
                    self.check_let_pattern(&p)?;
                    self.no_destructuring_params(&p)?;
                    (p, Vec::new())
                } else {
                    return Err(Diag::error(
                        format!("`{}` starts with a capital letter, so it reads as a constructor, not a name to bind; name a value in lowercase, and take a value apart with `match`, which has somewhere to fall through to", n),
                        t.span,
                    ));
                }
            }
            _ => return Err(self.err_expected("binding name")),
        };
        let name_span = pat.span;
        self.expect(&Tok::Eq, "`=`")?;
        let value = self.body()?;
        let span = kw.span.to(value.span);
        Ok(LetDecl { pat, params, mutable, pure_, value, doc, name_span, span, active: None, case_spans: Vec::new() })
    }

    /// Parameters after a destructuring pattern are parsed, then refused.
    fn no_destructuring_params(&mut self, p: &Pat) -> PResult<()> {
        let mut any = false;
        while matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Upper(_)) | Some(Tok::Underscore) | Some(Tok::LParen)) {
            self.param_pat()?;
            any = true;
        }
        if any {
            return Err(Diag::error("a function binding needs a name, so it cannot destructure (bind the value first, then take it apart)", p.span));
        }
        Ok(())
    }

    /// A binding written with a capitalized name (not a record pattern).
    fn capital_binding(&self) -> Option<Diag> {
        let t = self.raw();
        match &t.tok {
            // (a record pattern's `{` cut off by a line end does not count)
            Tok::Upper(n) if self.raw_at(1).tok != Tok::LBrace || self.boundary_of(self.raw_at(1)) != Boundary::No => Some(Diag::error(
                format!("`{}` starts with a capital letter, so it reads as a constructor, not a name to bind; name a value in lowercase, and take a value apart with `match`, which has somewhere to fall through to", n),
                t.span,
            )),
            _ => None,
        }
    }

    fn check_let_pattern(&self, p: &Pat) -> PResult<()> {
        match refutable_kind(p) {
            None => Ok(()),
            Some(k) => Err(Diag::error(
                format!("a `let` binding must always match, so it takes a name, `_`, or a tuple or record of those, not {} (use `match` instead, which has somewhere to fall through to)", k),
                p.span,
            )),
        }
    }

    /// A function parameter: a name, `_`, or a bracketed pattern.
    fn param_pat(&mut self) -> PResult<Pat> {
        let t = self.raw().clone();
        match &t.tok {
            // a capitalized parameter is still just a name
            Tok::Ident(n) | Tok::Upper(n) => {
                self.bump();
                Ok(Pat { kind: PatKind::Var(n.clone()), span: t.span })
            }
            Tok::Underscore => {
                self.bump();
                Ok(Pat { kind: PatKind::Wild, span: t.span })
            }
            Tok::LParen => {
                let p = self.atom_pattern()?;
                if let Some(k) = refutable_kind(&p) {
                    return Err(Diag::error(
                        format!("a parameter must always match, so it takes a name, `_`, or a tuple or record of those, not {} (match on the value in the body instead)", k),
                        p.span,
                    ));
                }
                Ok(p)
            }
            _ => Err(self.err_expected("a parameter")),
        }
    }

    /// The value after `=`, `->`, `then`, `else`, `case P:` — an indented
    /// block when the next token starts a new line, else an expression.
    fn body(&mut self) -> PResult<Expr> {
        let t = self.raw().clone();
        // a block opens on a line indented past the enclosing block (a line
        // left of the top level's column only continues the expression)
        let deeper = match self.layout.last() {
            Some(Layout::Block(c)) => t.col > *c,
            Some(Layout::CeItem { item_col, .. }) => t.col > *item_col,
            _ => true,
        };
        if t.tok != Tok::Eof && t.bol && self.boundary_of(&t) == Boundary::No && self.layout_allows_blocks() && deeper {
            return self.block(t.col);
        }
        self.expr()
    }

    /// Inside brackets, a closing bracket may end a block.
    fn in_brackets(&self) -> bool {
        self.layout.iter().any(|l| matches!(l, Layout::NoLayout | Layout::Block(0)))
    }

    /// A builder's `{` on the line after its name: taken unless the layout
    /// ends the expression there (inside a computation-expression item it
    /// is always taken).
    fn brace_continues(&self, t: &Token) -> bool {
        matches!(self.layout.last(), Some(Layout::CeItem { .. })) || self.boundary_of(t) == Boundary::No
    }

    /// A line-starting token that is not left of the top level (which
    /// would continue the line before).
    fn indented_block_start(&self, t: &Token) -> bool {
        match self.layout.first() {
            Some(Layout::Block(c)) => t.col >= *c,
            _ => true,
        }
    }

    /// No block opens inside brackets or a computation-expression item.
    fn layout_allows_blocks(&self) -> bool {
        !matches!(self.layout.last(), Some(Layout::NoLayout)) && self.ce_item_ctx().is_none()
    }

    /// The computation-expression item being read (through the arms of
    /// matches inside it), as (column, line, kind).
    fn ce_item_ctx(&self) -> Option<(usize, usize, &'static str)> {
        for l in self.layout.iter().rev() {
            match l {
                Layout::CeItem { item_col, line, kw } => return Some((*item_col, *line, *kw)),
                Layout::Block(c) if *c > 0 => continue,
                _ => return None,
            }
        }
        None
    }

    fn block(&mut self, col: usize) -> PResult<Expr> {
        let start = self.raw().span.lo;
        self.layout.push(Layout::Block(col));
        let r = self.block_inner(col);
        self.pop_block(&r);
        let stmts = r?;
        // what ends the block is described from the enclosing layout
        if !matches!(stmts.last(), Some(Stmt::Expr(_)) | Some(Stmt::Assign(..))) {
            return Err(Diag::error(format!("a block must end with an expression, found {}", self.describe_next()), self.err_span()));
        }
        if stmts.len() == 1 {
            match &stmts[0] {
                Stmt::Expr(e) => return Ok(e.clone()),
                Stmt::Assign(n, ns, v, whole) => {
                    return Ok(Expr { kind: ExprKind::Assign(n.clone(), *ns, Box::new(v.clone())), span: *whole });
                }
                _ => {}
            }
        }
        let end = self.prev_end();
        Ok(Expr { kind: ExprKind::Block(stmts), span: Span::new(start, end) })
    }

    fn block_inner(&mut self, col: usize) -> PResult<Vec<Stmt>> {
        let mut stmts = Vec::new();
        loop {
            // (what failed to lex where a statement starts is passed over)
            self.skip_lex_errors();
            let s = self.stmt()?;
            stmts.push(s);
            let t = self.raw().clone();
            let ends = t.tok == Tok::Eof || (t.bol && t.col < col) || (!t.bol && self.in_brackets() && matches!(t.tok, Tok::RParen | Tok::RBracket | Tok::RBrace));
            if t.bol && t.col == col && !is_continuation(&t.tok) && t.tok != Tok::Eof && !non_starter(&t.tok) {
                continue;
            }
            if ends || (t.bol && t.col < col) {
                return Ok(stmts);
            }
            if !matches!(stmts.last(), Some(Stmt::Expr(_))) && t.bol && t.col < col {
                return Err(self.err_expected("an expression"));
            }
            return Err(Diag::error(format!("expected end of the block, found {}", self.raw_describe()), self.raw_span()));
        }
    }

    /// A statement written as a Python `def f(x):` header: the message
    /// spells out the `let` with the parameters it names.
    fn python_def(&self) -> Option<Diag> {
        let def = self.raw();
        if !matches!(&def.tok, Tok::Ident(d) if d == "def") {
            return None;
        }
        let inside = |t: &Token| self.boundary_of(t) == Boundary::No;
        let mut i = self.pos + 1;
        let name = match &self.toks[i].tok {
            Tok::Ident(n) | Tok::Upper(n) if inside(&self.toks[i]) => n.clone(),
            _ => return None,
        };
        i += 1;
        let mut params: Vec<String> = Vec::new();
        loop {
            let t = &self.toks[i];
            if !inside(t) {
                return None;
            }
            match &t.tok {
                Tok::Colon | Tok::Eq | Tok::Arrow => break,
                Tok::Ident(n) | Tok::Upper(n) => {
                    params.push(n.clone());
                    i += 1;
                }
                // (a stray closing bracket is passed over)
                Tok::RParen | Tok::RBracket | Tok::RBrace => i += 1,
                Tok::LParen | Tok::LBracket | Tok::LBrace => {
                    // a bracketed group: the first name of each element
                    let mut depth = 0usize;
                    let mut names = Vec::new();
                    let mut taken = false;
                    loop {
                        match &self.toks[i].tok {
                            Tok::LParen | Tok::LBracket | Tok::LBrace => depth += 1,
                            Tok::RParen | Tok::RBracket | Tok::RBrace => {
                                depth -= 1;
                                if depth == 0 {
                                    break;
                                }
                            }
                            Tok::Comma if depth == 1 => taken = false,
                            Tok::Ident(n) | Tok::Upper(n) if depth == 1 && !taken => {
                                names.push(n.clone());
                                taken = true;
                            }
                            Tok::Eof => return None,
                            _ => {}
                        }
                        i += 1;
                    }
                    i += 1;
                    if names.is_empty() {
                        params.push("_".to_string());
                    } else {
                        params.extend(names);
                    }
                }
                _ => return None,
            }
        }
        let mut spelled = format!("let {}", name);
        for p in &params {
            spelled.push(' ');
            spelled.push_str(p);
        }
        Some(Diag::error(format!("Pyfun defines functions with `let`: write `{} = …`", spelled), def.span))
    }

    fn stmt(&mut self) -> PResult<Stmt> {
        self.anchor = self.raw().span.lo;
        if let Some(e) = self.python_def() {
            return Err(e);
        }
        match self.raw().tok.clone() {
            Tok::Let => Ok(Stmt::Let(self.let_decl(None, false)?)),
            _ => {
                let e = self.expr()?;
                Ok(match e.kind {
                    ExprKind::Assign(n, ns, v) => Stmt::Assign(n, ns, *v, e.span),
                    kind => Stmt::Expr(Expr { kind, span: e.span }),
                })
            }
        }
    }

    // ---- expressions --------------------------------------------------

    pub fn expr(&mut self) -> PResult<Expr> {
        let e = match self.peek() {
            Some(Tok::If) => self.if_expr()?,
            Some(Tok::Fun) => self.lambda()?,
            Some(Tok::Match) => self.match_expr()?,
            _ => self.pipe_left()?,
        };
        if !self.check(&Tok::LArrow) {
            return Ok(e);
        }
        // `x <- e`: assignment, the loosest form, grouping to the right
        self.bump();
        let v = self.expr()?;
        match e.kind {
            // (a capitalized name is a target too: the checker says why not)
            ExprKind::Var(n) | ExprKind::Ctor(_, n) if !matches!(&e.kind, ExprKind::Ctor(p, _) if !p.is_empty()) => {
                // (the statement runs to its last token: a closing paren too)
                let span = Span::new(e.span.lo, self.prev_end().max(v.span.hi));
                Ok(Expr { kind: ExprKind::Assign(n, e.span, Box::new(v)), span })
            }
            _ => Err(Diag::error("the target of `<-` must be a variable", e.span)),
        }
    }

    fn if_expr(&mut self) -> PResult<Expr> {
        let kw = self.bump();
        let cond = self.expr()?;
        self.expect(&Tok::Then, "`then`")?;
        let then = self.body()?;
        let els = if self.check(&Tok::Elif) {
            self.elif_chain()?
        } else if self.check(&Tok::Else) {
            self.bump();
            self.body()?
        } else {
            return Err(self.err_expected("`else` or `elif`"));
        };
        let span = Span::new(kw.span.lo, self.prev_end());
        Ok(Expr { kind: ExprKind::If(Box::new(cond), Box::new(then), Box::new(els)), span })
    }

    fn elif_chain(&mut self) -> PResult<Expr> {
        let kw = self.bump(); // elif
        let cond = self.expr()?;
        self.expect(&Tok::Then, "`then`")?;
        let then = self.body()?;
        let els = if self.check(&Tok::Elif) {
            self.elif_chain()?
        } else if self.check(&Tok::Else) {
            self.bump();
            self.body()?
        } else {
            return Err(self.err_expected("`else` or `elif`"));
        };
        let span = Span::new(kw.span.lo, self.prev_end());
        Ok(Expr { kind: ExprKind::If(Box::new(cond), Box::new(then), Box::new(els)), span })
    }

    fn lambda(&mut self) -> PResult<Expr> {
        let kw = self.bump();
        let mut params = Vec::new();
        while matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Upper(_)) | Some(Tok::Underscore) | Some(Tok::LParen)) {
            params.push(self.param_pat()?);
        }
        if params.is_empty() {
            return Err(self.err_expected("parameter name"));
        }
        self.expect(&Tok::Arrow, "`->`")?;
        let body = self.body()?;
        // (to its last token: a parenthesized body's `)` too)
        let span = Span::new(kw.span.lo, self.prev_end().max(body.span.hi));
        Ok(Expr { kind: ExprKind::Lambda(params, Box::new(body)), span })
    }

    fn match_expr(&mut self) -> PResult<Expr> {
        let kw = self.bump();
        let scrut = self.expr()?;
        if !self.check(&Tok::Colon) {
            if self.check(&Tok::With) {
                return Err(self.err_expected_msg("match now uses `match e:` with `case pattern: body` arms, not `with | pattern -> body` (DESIGN.md §7.2)"));
            }
            // (a header the line ends leaves its arms to be read)
            self.open_arms = self.at_boundary();
            return Err(self.err_expected("`:` after the match scrutinee"));
        }
        self.bump();
        let t = self.raw().clone();
        let mut arms = Vec::new();
        let in_ce_item = self.ce_item_ctx().is_some();
        // in a computation expression's item, arms on the next lines need `case`
        // (arms left of the top level's column only continue its line)
        let arms_block = if in_ce_item { t.tok == Tok::Case && t.bol } else { t.tok != Tok::Eof && t.bol && self.layout_allows_blocks() && self.boundary_of(&t) == Boundary::No && self.indented_block_start(&t) };
        if arms_block && in_ce_item {
            // (the arms have no layout of their own in a computation
            // expression's item: any `case` is the next arm, and what else
            // follows ends them)
            loop {
                arms.push(self.arm()?);
                if self.raw().tok != Tok::Case {
                    break;
                }
            }
        } else if arms_block {
            let col = t.col;
            self.layout.push(Layout::Block(col));
            let r = (|| -> PResult<()> {
                // (what failed to lex where the arms start is passed over; a
                // line after it starts no arm)
                let lexed_badly = self.raw().tok == Tok::LexError;
                self.skip_lex_errors();
                if lexed_badly && self.raw().bol {
                    return Err(Diag::error(format!("expected end of the match arms, found {}", self.describe_next()), self.err_span()));
                }
                loop {
                    if self.raw().tok != Tok::Case {
                        return Err(Diag::error(format!("expected end of the match arms, found {}", self.raw_describe()), self.raw_span()));
                    }
                    arms.push(self.arm()?);
                    let t = self.raw();
                    // (in a computation expression's item any `case` is
                    // the next arm, wherever it stands)
                    if t.tok == Tok::Case && ((t.bol && t.col == col) || in_ce_item) {
                        continue;
                    }
                    let closer = matches!(t.tok, Tok::RParen | Tok::RBracket | Tok::RBrace) || (!t.bol && t.tok == Tok::Comma);
                    if t.tok == Tok::Eof || (t.bol && t.col < col) || (self.in_brackets() && closer) {
                        return Ok(());
                    }
                    // in a computation expression the next item may follow
                    // (a line not starting an arm ends the arms)
                    if !t.bol && self.layout.iter().any(|l| matches!(l, Layout::CeItem { .. })) {
                        return Ok(());
                    }
                    if t.bol && in_ce_item {
                        return Ok(());
                    }
                    return Err(Diag::error(format!("expected end of the match arms, found {}", self.raw_describe()), self.raw_span()));
                }
            })();
            self.pop_block(&r);
            r?;
        } else if self.check(&Tok::Case) {
            while self.check(&Tok::Case) {
                arms.push(self.arm()?);
            }
        } else {
            return Err(Diag::error(
                format!("a match needs at least one `case pattern: body` arm, found {}", self.describe_next()),
                self.err_span(),
            ));
        }
        let span = Span::new(kw.span.lo, self.prev_end());
        Ok(Expr { kind: ExprKind::Match(Box::new(scrut), arms), span })
    }

    fn err_span(&self) -> Span {
        let t = self.raw();
        if t.tok == Tok::Eof || (self.boundary_of(t) != Boundary::No && !matches!(self.layout.last(), Some(Layout::CeItem { .. }))) {
            Span::new(t.span.lo, t.span.lo)
        } else {
            t.span
        }
    }

    fn raw_describe(&self) -> String {
        let t = self.raw();
        if t.tok == Tok::Eof {
            "end of input".into()
        } else {
            describe(&t.tok)
        }
    }

    fn raw_span(&self) -> Span {
        let t = self.raw();
        if t.tok == Tok::Eof {
            Span::new(t.span.lo, t.span.lo)
        } else {
            t.span
        }
    }

    fn arm(&mut self) -> PResult<Arm> {
        let kw = self.bump(); // case
        // (inside a computation expression's item an arm's head runs on
        // whatever its lines are, up to its `:`)
        let head = |p: &mut Parser| -> PResult<(Pat, Option<Expr>)> {
            let pat = p.pattern()?;
            let guard = if p.check(&Tok::If) {
                p.bump();
                Some(p.expr()?)
            } else {
                None
            };
            if !p.check(&Tok::Colon) {
                return Err(p.err_expected("`:` after the case pattern"));
            }
            p.bump();
            Ok((pat, guard))
        };
        let (pat, guard) = if self.ce_item_ctx().is_some() { self.with_layout(Layout::NoLayout, head)? } else { head(self)? };
        let body = self.body()?;
        let span = kw.span.to(body.span);
        Ok(Arm { pat, guard, body, span })
    }

    fn pipe_left(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let lhs = self.pipe_right()?;
        if self.check(&Tok::PipeLeft) {
            self.bump();
            let rhs = self.pipe_left()?;
            let span = Span::new(start, self.prev_end());
            return Ok(Expr { kind: ExprKind::Binary(BinOp::PipeLeft, Box::new(lhs), Box::new(rhs)), span });
        }
        Ok(lhs)
    }

    fn pipe_right(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut lhs = self.compose()?;
        while self.check(&Tok::PipeRight) {
            self.bump();
            let rhs = self.compose()?;
            let span = Span::new(start, self.prev_end());
            lhs = Expr { kind: ExprKind::Binary(BinOp::PipeRight, Box::new(lhs), Box::new(rhs)), span };
        }
        Ok(lhs)
    }

    fn compose(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut lhs = self.or_expr()?;
        loop {
            let op = match self.peek() {
                Some(Tok::ComposeRight) => BinOp::ComposeRight,
                Some(Tok::ComposeLeft) => BinOp::ComposeLeft,
                _ => break,
            };
            self.bump();
            let rhs = self.or_expr()?;
            let span = Span::new(start, self.prev_end());
            lhs = Expr { kind: ExprKind::Binary(op, Box::new(lhs), Box::new(rhs)), span };
        }
        Ok(lhs)
    }

    fn or_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut lhs = self.and_expr()?;
        while self.check(&Tok::Or) {
            self.bump();
            let rhs = self.and_expr()?;
            let span = Span::new(start, self.prev_end());
            lhs = Expr { kind: ExprKind::Binary(BinOp::Or, Box::new(lhs), Box::new(rhs)), span };
        }
        Ok(lhs)
    }

    fn and_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut lhs = self.not_expr()?;
        while self.check(&Tok::And) {
            self.bump();
            let rhs = self.not_expr()?;
            let span = Span::new(start, self.prev_end());
            lhs = Expr { kind: ExprKind::Binary(BinOp::And, Box::new(lhs), Box::new(rhs)), span };
        }
        Ok(lhs)
    }

    fn not_expr(&mut self) -> PResult<Expr> {
        match self.peek() {
            Some(Tok::Not) => {
                let kw = self.bump();
                let e = self.not_expr()?;
                let span = Span::new(kw.span.lo, self.prev_end());
                Ok(Expr { kind: ExprKind::Not(Box::new(e)), span })
            }
            Some(Tok::Try) => {
                let kw = self.bump();
                let e = self.not_expr()?;
                let span = Span::new(kw.span.lo, self.prev_end());
                Ok(Expr { kind: ExprKind::Try(Box::new(e)), span })
            }
            _ => self.cmp_expr(),
        }
    }

    fn cmp_op(&self) -> Option<CmpOp> {
        Some(match self.peek()? {
            Tok::EqEq => CmpOp::Eq,
            Tok::NotEq => CmpOp::Ne,
            Tok::Lt => CmpOp::Lt,
            Tok::Le => CmpOp::Le,
            Tok::Gt => CmpOp::Gt,
            Tok::Ge => CmpOp::Ge,
            _ => return None,
        })
    }

    fn cmp_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let lhs = self.add_expr()?;
        let mut rest = Vec::new();
        while let Some(op) = self.cmp_op() {
            self.bump();
            let rhs = self.add_expr()?;
            rest.push((op, rhs));
        }
        if rest.is_empty() {
            return Ok(lhs);
        }
        let span = Span::new(start, self.prev_end());
        Ok(Expr { kind: ExprKind::Chain(Box::new(lhs), rest), span })
    }

    fn add_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut lhs = self.mul_expr()?;
        loop {
            let op = match self.peek() {
                Some(Tok::Plus) => BinOp::Add,
                Some(Tok::Minus) => BinOp::Sub,
                _ => break,
            };
            self.bump();
            let rhs = self.mul_expr()?;
            let span = Span::new(start, self.prev_end());
            lhs = Expr { kind: ExprKind::Binary(op, Box::new(lhs), Box::new(rhs)), span };
        }
        Ok(lhs)
    }

    fn mul_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut lhs = self.unary_expr()?;
        loop {
            let op = match self.peek() {
                Some(Tok::Star) => BinOp::Mul,
                Some(Tok::Slash) => BinOp::Div,
                Some(Tok::SlashSlash) => BinOp::FloorDiv,
                Some(Tok::Percent) => BinOp::Mod,
                _ => break,
            };
            self.bump();
            let rhs = self.unary_expr()?;
            let span = Span::new(start, self.prev_end());
            lhs = Expr { kind: ExprKind::Binary(op, Box::new(lhs), Box::new(rhs)), span };
        }
        Ok(lhs)
    }

    fn unary_expr(&mut self) -> PResult<Expr> {
        if self.check(&Tok::Minus) {
            let kw = self.bump();
            let e = self.unary_expr()?;
            let span = Span::new(kw.span.lo, self.prev_end());
            return Ok(Expr { kind: ExprKind::Neg(Box::new(e)), span });
        }
        self.pow_expr()
    }

    fn pow_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let lhs = self.app_expr()?;
        if self.check(&Tok::StarStar) {
            self.bump();
            let rhs = self.unary_expr()?;
            let span = Span::new(start, self.prev_end());
            return Ok(Expr { kind: ExprKind::Binary(BinOp::Pow, Box::new(lhs), Box::new(rhs)), span });
        }
        Ok(lhs)
    }

    fn app_expr(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let head_col = self.raw().col;
        let mut f = self.postfix()?;
        loop {
            let t = self.raw().clone();
            if !starts_atom(&t.tok) {
                break;
            }
            // in a computation expression `for` starts the next item
            if matches!(&t.tok, Tok::Ident(s) if s == "for") && self.layout.iter().any(|l| matches!(l, Layout::CeItem { .. })) {
                break;
            }
            // inside a computation-expression item, a line left of the
            // application's start is no argument of it
            if let Some((item_col, line, kw)) = self.ce_item_ctx() {
                if t.bol && t.col > item_col && t.col < head_col && t.span.lo != self.anchor {
                    return Err(Diag::error(
                        format!("{} is indented as a continuation of the `{}` item on line {}, where it can only be an argument to that item's expression; to make it a new item, align it with that item, or indent it past the start of the expression to continue it", describe(&t.tok), kw, line),
                        t.span,
                    ));
                }
            }
            if self.boundary_of(&t) != Boundary::No {
                break;
            }
            let a = self.postfix()?;
            let span = Span::new(start, self.prev_end());
            f = Expr { kind: ExprKind::App(Box::new(f), Box::new(a)), span };
        }
        Ok(f)
    }

    fn postfix(&mut self) -> PResult<Expr> {
        let start = self.raw().span.lo;
        let mut e = self.atom()?;
        while self.check(&Tok::Dot) {
            self.bump();
            let t = self.raw().clone();
            match self.peek() {
                Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                    let n = n.clone();
                    self.bump();
                    let span = Span::new(start, self.prev_end());
                    e = Expr { kind: ExprKind::Field(Box::new(e), n.clone(), t.span), span };
                }
                _ => return Err(self.err_expected("field name")),
            }
        }
        Ok(e)
    }

    fn atom(&mut self) -> PResult<Expr> {
        let t = match self.peek() {
            Some(_) => self.raw().clone(),
            None => return Err(self.err_expected("an expression")),
        };
        match &t.tok {
            // (what failed to lex was reported already)
            Tok::LexError => {
                self.bump();
                self.atom()
            }
            Tok::Int(n) => {
                self.bump();
                let lit = Expr { kind: ExprKind::Int(*n), span: t.span };
                self.maybe_unit(lit)
            }
            Tok::Float(f) => {
                self.bump();
                let lit = Expr { kind: ExprKind::Float(*f), span: t.span };
                self.maybe_unit(lit)
            }
            Tok::Str(s) => {
                self.bump();
                Ok(Expr { kind: ExprKind::Str(s.clone()), span: t.span })
            }
            Tok::FStr(pieces) => {
                self.bump();
                let mut parts = Vec::new();
                for p in pieces {
                    match p {
                        FPiece::Text(s) => parts.push(FPart::Text(s.clone())),
                        FPiece::Hole { toks, span: _, debug } => {
                            if let Some(d) = debug {
                                match parts.last_mut() {
                                    Some(FPart::Text(prev)) => prev.push_str(d),
                                    _ => parts.push(FPart::Text(d.clone())),
                                }
                            }
                            let mut sub = Parser::new(toks.clone(), Vec::new());
                            sub.layout = vec![Layout::NoLayout];
                            let e = sub.expr()?;
                            if sub.raw().tok != Tok::Eof {
                                return Err(Diag::error(
                                    format!("unexpected token after f-string hole expression, found {}", describe(&sub.raw().tok)),
                                    sub.raw().span,
                                ));
                            }
                            parts.push(FPart::Expr(e));
                        }
                    }
                }
                Ok(Expr { kind: ExprKind::FStr(parts), span: t.span })
            }
            Tok::True => {
                self.bump();
                Ok(Expr { kind: ExprKind::Bool(true), span: t.span })
            }
            Tok::False => {
                self.bump();
                Ok(Expr { kind: ExprKind::Bool(false), span: t.span })
            }
            Tok::Hole(n) => {
                self.bump();
                Ok(Expr { kind: ExprKind::Hole(n.clone()), span: t.span })
            }
            Tok::Ident(n) => {
                // (the brace opens the block only where it continues the line)
                if matches!(n.as_str(), "async" | "seq" | "result" | "option") && self.raw_at(1).tok == Tok::LBrace && self.brace_continues(self.raw_at(1)) {
                    self.bump();
                    return self.ce_body(Vec::new(), n.clone(), t.span);
                }
                self.bump();
                Ok(Expr { kind: ExprKind::Var(n.clone()), span: t.span })
            }
            Tok::Upper(_) => self.upper_atom(),
            Tok::LParen => self.paren(),
            Tok::LBracket => self.list(),
            Tok::LBrace => self.update(),
            // (inside a computation expression `return` is just misplaced)
            Tok::Return if !self.layout.iter().any(|l| matches!(l, Layout::CeItem { .. } | Layout::Block(0))) => Err(Diag::error(
                "`return` is only valid inside a computation expression; a function's value is its last expression, so drop `return`",
                t.span,
            )),
            Tok::Bar if self.raw_at(1).tok == Tok::Bar => Err(Diag::error("use `or` instead of `||`", t.span)),
            _ => Err(self.err_expected("an expression")),
        }
    }

    fn maybe_unit(&mut self, lit: Expr) -> PResult<Expr> {
        let t = self.raw();
        if t.tok == Tok::Lt && !t.space_before && t.span.lo == lit.span.hi {
            self.bump();
            let u = self.unit_expr()?;
            // the `>` closes wherever it stands short of a dedent; anything
            // else is described as the layout sees it
            if self.raw().tok != Tok::Gt || self.boundary_of(self.raw()) == Boundary::Block {
                return Err(self.err_expected("`>`"));
            }
            let gt = self.bump();
            let span = lit.span.to(gt.span);
            return Ok(Expr { kind: ExprKind::Measured(Box::new(lit), u), span });
        }
        Ok(lit)
    }

    fn expect_raw(&mut self, t: &Tok, what: &str) -> PResult<Token> {
        // the token as it is, wherever it stands
        self.layout.push(Layout::NoLayout);
        let r = self.expect(t, what);
        self.layout.pop();
        r
    }

    /// `kg m / s^2`, `1/s`, `1`
    pub fn unit_expr(&mut self) -> PResult<UnitExpr> {
        let start = self.raw().span.lo;
        let mut num = Vec::new();
        let mut den = Vec::new();
        match self.peek().cloned() {
            Some(Tok::Int(1)) => {
                self.bump();
            }
            Some(Tok::Ident(_)) | Some(Tok::Upper(_)) => {
                self.unit_factors(&mut num)?;
            }
            _ => return Err(self.err_expected("a unit (e.g. `m`, `m/s`, or `1`)")),
        }
        if self.check(&Tok::Slash) {
            self.bump();
            self.unit_factors(&mut den)?;
        }
        Ok(UnitExpr { num, den, span: Span::new(start, self.prev_end()) })
    }

    fn unit_factors(&mut self, out: &mut Vec<(String, i64)>) -> PResult<()> {
        loop {
            let name = match self.peek() {
                Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => n.clone(),
                _ => break,
            };
            self.bump();
            let mut exp = 1;
            if self.check(&Tok::Caret) {
                self.bump();
                match self.peek().cloned() {
                    Some(Tok::Int(n)) => {
                        self.bump();
                        exp = n;
                    }
                    _ => return Err(self.err_expected("an integer exponent after `^`")),
                }
            }
            // (a zero power still names a measure that must exist)
            out.push((name, exp));
        }
        Ok(())
    }

    fn upper_atom(&mut self) -> PResult<Expr> {
        let first = self.bump();
        let mut path = Vec::new();
        let mut name = match &first.tok {
            Tok::Upper(n) => n.clone(),
            _ => unreachable!(),
        };
        let mut last_span = first.span;
        // A.B.c / A.B
        while self.check(&Tok::Dot) {
            self.bump();
            match self.peek().cloned() {
                Some(Tok::Upper(n)) => {
                    let t = self.bump();
                    path.push(std::mem::replace(&mut name, n));
                    last_span = t.span;
                }
                Some(Tok::Ident(n)) => {
                    let t = self.bump();
                    path.push(name);
                    let span = first.span.to(t.span);
                    let _ = last_span;
                    return Ok(Expr { kind: ExprKind::Qual(path, n, t.span), span });
                }
                _ => return Err(self.err_expected("field name")),
            }
        }
        let ctor_span = last_span;
        // (a deeper path is no record type: the braces stand on their own)
        if self.check(&Tok::LBrace) && path.len() <= 1 {
            // record construction, or a user CE builder `Maybe { ... }`
            let next = self.raw_at(1).tok.clone();
            if let Tok::Ident(field) | Tok::Upper(field) = &next {
                // `T { x = ...`: a record; `T { x y ...`: neither (`for`
                // starts a builder block)
                if path.is_empty() && field != "for" && !matches!(self.raw_at(2).tok, Tok::Eq | Tok::RBrace | Tok::Comma) {
                    let sp = self.raw_at(1).span;
                    return Err(Diag::error(
                        format!(
                            "`{}` is not a computation-expression item: a `{} {{ … }}` block takes `let!`, `let`, `do!`, `return`, `yield`, `for`, or an expression, and a `{} {{ … }}` record literal takes `field = value` pairs",
                            field, name, name
                        ),
                        sp,
                    ));
                }
            }
            // a builder block starts with one of its keywords
            let ce_start = matches!(next, Tok::Let | Tok::Do | Tok::Return | Tok::Yield) || matches!(&next, Tok::Ident(s) if s == "for");
            let is_record = !path.is_empty() || !ce_start;
            if is_record {
                return self.record(path, name, first.span, ctor_span);
            }
            self.bump_back_to_brace();
            return self.ce_body(path, name, first.span);
        }
        let span = first.span.to(ctor_span);
        Ok(Expr { kind: ExprKind::Ctor(path, name), span })
    }

    fn bump_back_to_brace(&mut self) {}

    fn at_boundary_tok(&self, _k: usize) -> bool {
        false
    }

    fn record(&mut self, path: Vec<String>, name: String, start: Span, ctor_span: Span) -> PResult<Expr> {
        self.bump(); // {
        let fields = self.with_layout(Layout::NoLayout, |p| {
            let mut fields = Vec::new();
            if p.check(&Tok::RBrace) {
                return Err(Diag::error(format!("a record needs at least one field, found {}", p.describe_next()), p.err_span()));
            }
            loop {
                let t = p.raw().clone();
                let fname = match &t.tok {
                    Tok::Ident(n) | Tok::Upper(n) => n.clone(),
                    _ => return Err(p.err_expected("field name")),
                };
                p.bump();
                p.expect(&Tok::Eq, "`=`")?;
                let v = p.expr()?;
                fields.push((fname, t.span, v));
                if p.eat(&Tok::Comma) {
                    if p.check(&Tok::RBrace) {
                        break;
                    }
                    continue;
                }
                break;
            }
            Ok(fields)
        })?;
        let close = self.close_bracket(&Tok::RBrace, "`}`")?;
        Ok(Expr { kind: ExprKind::Record(path, name, ctor_span, fields), span: start.to(close.span) })
    }

    fn update(&mut self) -> PResult<Expr> {
        let open = self.bump();
        let (base, fields) = self.with_layout(Layout::NoLayout, |p| {
            if p.check(&Tok::RBrace) {
                return Err(p.err_expected("an expression"));
            }
            // `{ x = ... }` without the record's name
            if let (Tok::Ident(_) | Tok::Upper(_), Tok::Eq) = (&p.raw().tok, &p.raw_at(1).tok) {
                return Err(p.err_expected_msg("record literals are now constructor-tagged: write `T { x = … }` naming the record type (DESIGN.md §8.3)"));
            }
            let base = p.expr()?;
            p.expect(&Tok::With, "`with`")?;
            let mut fields = Vec::new();
            loop {
                let mut path = Vec::new();
                loop {
                    let t = p.raw().clone();
                    match &t.tok {
                        Tok::Ident(n) | Tok::Upper(n) => {
                            p.bump();
                            path.push((n.clone(), t.span));
                        }
                        _ => return Err(p.err_expected("field name")),
                    }
                    if p.check(&Tok::Dot) {
                        p.bump();
                        continue;
                    }
                    break;
                }
                p.expect(&Tok::Eq, "`=`")?;
                let v = p.expr()?;
                fields.push((path, v));
                if p.eat(&Tok::Comma) {
                    if p.check(&Tok::RBrace) {
                        break;
                    }
                    continue;
                }
                break;
            }
            Ok((base, fields))
        })?;
        let close = self.close_bracket(&Tok::RBrace, "`}`")?;
        Ok(Expr { kind: ExprKind::Update(Box::new(base), fields), span: open.span.to(close.span) })
    }

    fn paren(&mut self) -> PResult<Expr> {
        let open = self.bump();
        self.layout.push(Layout::NoLayout);
        let r = self.paren_inner(open.span);
        if r.is_ok() || !self.recovering {
            self.layout.pop();
        }
        let (kind, close, inner) = r?;
        // parentheses only group: the expression keeps its own span
        if let Some(sp) = inner {
            return Ok(Expr { kind, span: sp });
        }
        Ok(Expr { kind, span: open.span.to(close) })
    }

    fn paren_inner(&mut self, _open: Span) -> PResult<(ExprKind, Span, Option<Span>)> {
        if self.check(&Tok::RParen) {
            let c = self.bump();
            return Ok((ExprKind::Unit, c.span, None));
        }
        // operator section
        let sec = match self.raw().tok {
            Tok::Plus => Some(SectionOp::Bin(BinOp::Add)),
            Tok::Minus => Some(SectionOp::Bin(BinOp::Sub)),
            Tok::Star => Some(SectionOp::Bin(BinOp::Mul)),
            Tok::Slash => Some(SectionOp::Bin(BinOp::Div)),
            Tok::SlashSlash => Some(SectionOp::Bin(BinOp::FloorDiv)),
            Tok::Percent => Some(SectionOp::Bin(BinOp::Mod)),
            Tok::StarStar => Some(SectionOp::Bin(BinOp::Pow)),
            Tok::EqEq => Some(SectionOp::Cmp(CmpOp::Eq)),
            Tok::NotEq => Some(SectionOp::Cmp(CmpOp::Ne)),
            Tok::Lt => Some(SectionOp::Cmp(CmpOp::Lt)),
            Tok::Le => Some(SectionOp::Cmp(CmpOp::Le)),
            Tok::Gt => Some(SectionOp::Cmp(CmpOp::Gt)),
            Tok::Ge => Some(SectionOp::Cmp(CmpOp::Ge)),
            _ => None,
        };
        if let Some(op) = sec {
            if self.raw_at(1).tok == Tok::RParen {
                self.bump();
                let c = self.bump();
                return Ok((ExprKind::Section(op), c.span, None));
            }
        }
        let first = self.expr()?;
        if self.check(&Tok::Comma) {
            let mut items = vec![first];
            while self.eat(&Tok::Comma) {
                items.push(self.expr()?);
            }
            let c = self.expect(&Tok::RParen, "`)`")?;
            return Ok((ExprKind::Tuple(items), c.span, None));
        }
        let c = self.expect(&Tok::RParen, "`)`")?;
        // parentheses only group
        Ok((first.kind, c.span, Some(first.span)))
    }

    fn list(&mut self) -> PResult<Expr> {
        let open = self.bump();
        let items = self.with_layout(Layout::NoLayout, |p| {
            let mut items = Vec::new();
            while !p.check(&Tok::RBracket) {
                items.push(p.expr()?);
                if !p.eat(&Tok::Comma) {
                    break;
                }
            }
            Ok(items)
        })?;
        let close = self.close_bracket(&Tok::RBracket, "`]`")?;
        Ok(Expr { kind: ExprKind::List(items), span: open.span.to(close.span) })
    }

    // ---- computation expressions -------------------------------------

    fn ce_body(&mut self, path: Vec<String>, name: String, start: Span) -> PResult<Expr> {
        let open = self.bump(); // {
        let _ = open;
        let stmts = self.with_layout(Layout::Block(0), |p| p.ce_items(&Tok::RBrace))?;
        if self.raw().tok == Tok::Eof {
            return Err(self.err_expected_msg("unterminated computation expression"));
        }
        let close = self.expect_raw(&Tok::RBrace, "`}`")?;
        Ok(Expr { kind: ExprKind::Ce(path, name, stmts), span: start.to(close.span) })
    }

    /// Items until `end` (exclusive) or a dedent below `min_col`.
    fn ce_items(&mut self, end: &Tok) -> PResult<Vec<CeStmt>> {
        let mut items = Vec::new();
        loop {
            let t = self.raw().clone();
            if &t.tok == end {
                break;
            }
            if t.tok == Tok::Eof && !self.in_nested_block() {
                return Err(self.err_expected_msg("unterminated computation expression"));
            }
            items.push(self.ce_item()?);
        }
        Ok(items)
    }

    fn ce_item(&mut self) -> PResult<CeStmt> {
        let t = self.raw().clone();
        self.anchor = t.span.lo;
        let item_col = t.col;
        let line = t.line;
        let bang = self.raw_at(1).tok == Tok::Bang;
        let kw: &'static str = match &t.tok {
            Tok::Let if bang => "let!",
            Tok::Let => "let",
            Tok::Do if bang => "do!",
            Tok::Do => "do",
            Tok::Return if bang => "return!",
            Tok::Return => "return",
            Tok::Yield if bang => "yield!",
            Tok::Yield => "yield",
            Tok::Ident(s) if s == "for" => "for",
            _ => "expression",
        };
        let item = self.ce_item_inner(&t, item_col, line, kw, bang)?;
        // a line indented past the item that could only be an argument of
        // its expression, but is not one
        let n = self.raw().clone();
        if n.bol && n.col > item_col && starts_atom(&n.tok) && !matches!(&n.tok, Tok::Ident(s) if s == "for") && n.span.lo != self.anchor {
            return Err(Diag::error(
                format!("{} is indented as a continuation of the `{}` item on line {}, where it can only be an argument to that item's expression; to make it a new item, align it with that item, or indent it past the start of the expression to continue it", describe(&n.tok), kw, line),
                n.span,
            ));
        }
        Ok(item)
    }

    fn ce_item_inner(&mut self, t: &Token, item_col: usize, line: usize, kw: &'static str, bang: bool) -> PResult<CeStmt> {
        let _ = bang;
        let t = t.clone();
        match &t.tok {
            Tok::Let if self.raw_at(1).tok == Tok::Bang => {
                self.bump();
                self.bump();
                if !matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Underscore) | Some(Tok::LParen) | Some(Tok::Upper(_))) {
                    return Err(self.err_expected("binding name"));
                }
                if let Some(d) = self.capital_binding() {
                    return Err(d);
                }
                // (a name or `_` is the whole pattern, as for `let`)
                let n = self.raw().clone();
                let pat = match &n.tok {
                    Tok::Ident(v) => {
                        self.bump();
                        Pat { kind: PatKind::Var(v.clone()), span: n.span }
                    }
                    Tok::Underscore => {
                        self.bump();
                        Pat { kind: PatKind::Wild, span: n.span }
                    }
                    _ => {
                        let pat = self.pattern()?;
                        self.check_let_pattern(&pat)?;
                        pat
                    }
                };
                self.expect(&Tok::Eq, "`=`")?;
                let e = self.ce_expr(item_col, line, kw)?;
                Ok(CeStmt::LetBang(pat, e, t.span))
            }
            Tok::Let => {
                let col = self.raw_at(0).col;
                let _ = col;
                let l = self.with_layout(Layout::CeItem { item_col, line, kw }, |p| p.let_decl_ce(item_col, line))?;
                Ok(CeStmt::Let(l))
            }
            Tok::Do if self.raw_at(1).tok == Tok::Bang => {
                self.bump();
                self.bump();
                let e = self.ce_expr(item_col, line, kw)?;
                Ok(CeStmt::DoBang(e, t.span))
            }
            Tok::Do => {
                self.bump();
                Err(self.err_expected("`!`"))
            }
            Tok::Return => {
                self.bump();
                if self.raw().tok == Tok::Bang {
                    self.bump();
                    let e = self.ce_expr(item_col, line, kw)?;
                    return Ok(CeStmt::ReturnBang(e, t.span));
                }
                let e = self.ce_expr(item_col, line, kw)?;
                Ok(CeStmt::Return(e, t.span))
            }
            Tok::Yield => {
                self.bump();
                if self.raw().tok == Tok::Bang {
                    self.bump();
                    let e = self.ce_expr(item_col, line, kw)?;
                    return Ok(CeStmt::YieldBang(e, t.span));
                }
                let e = self.ce_expr(item_col, line, kw)?;
                Ok(CeStmt::Yield(e, t.span))
            }
            Tok::Ident(s) if s == "for" => {
                self.bump();
                if !matches!(self.peek(), Some(Tok::Ident(_)) | Some(Tok::Underscore) | Some(Tok::LParen) | Some(Tok::Upper(_))) {
                    return Err(self.err_expected("binding name"));
                }
                let pat = self.pattern()?;
                match self.raw().tok.clone() {
                    Tok::Ident(s) if s == "in" => {
                        self.bump();
                    }
                    _ => return Err(self.err_expected("`in` after the `for` target")),
                }
                self.anchor = self.raw().span.lo;
                let src = self.with_layout(Layout::CeItem { item_col, line, kw }, |p| p.expr())?;
                self.expect(&Tok::Colon, "`:` after the `for` source")?;
                let nt = self.raw().clone();
                if nt.tok == Tok::RBrace || (nt.tok == Tok::Eof && !self.in_nested_block()) || (nt.bol && nt.col <= item_col) {
                    return Err(self.err_expected_msg("a `for` needs at least one item in its body"));
                }
                let body = if nt.bol {
                    let mut body = vec![self.ce_item()?];
                    // (any line indented past the `for` is part of it, and
                    // so is an item following on the same line)
                    while self.raw().tok != Tok::Eof && self.raw().tok != Tok::RBrace && (!self.raw().bol || self.raw().col > item_col) {
                        body.push(self.ce_item()?);
                    }
                    body
                } else {
                    vec![self.ce_item()?]
                };
                if body.is_empty() {
                    return Err(self.err_expected_msg("a `for` needs at least one item in its body"));
                }
                Ok(CeStmt::For(pat, src, body, t.span))
            }
            _ => {
                if t.tok == Tok::Eof || !starts_expr(&t.tok) || t.tok == Tok::Try {
                    return Err(self.err_expected("`let!`, `let`, `do!`, `return`, `yield`, `for`, or an expression"));
                }
                // (an assignment is an expression item like any other)
                let e = self.ce_expr(item_col, line, kw)?;
                let span = e.span;
                Ok(CeStmt::Let(LetDecl {
                    pat: Pat { kind: PatKind::Wild, span: Span::new(span.lo, span.lo) },
                    params: Vec::new(),
                    mutable: false,
                    pure_: false,
                    value: e,
                    doc: None,
                    name_span: Span::new(span.lo, span.lo),
                    span,
                    active: None,
                    case_spans: Vec::new(),
                }))
            }
        }
    }

    fn ce_expr(&mut self, item_col: usize, line: usize, kw: &'static str) -> PResult<Expr> {
        let t = self.raw().clone();
        // the item's expression may start on the next line, wherever it
        // stands (it is an expression there too, not a block)
        self.anchor = t.span.lo;
        self.with_layout(Layout::CeItem { item_col, line, kw }, |p| p.expr())
    }

    fn let_decl_ce(&mut self, item_col: usize, line: usize) -> PResult<LetDecl> {
        // like let_decl, but the value is laid out as a CE item expression
        // a plain binding: no parameters, no `mut`
        let kw = self.bump();
        let (mutable, pure_) = (false, false);
        let t = self.raw().clone();
        let (pat, params) = match &t.tok {
            Tok::Ident(n) => {
                self.bump();
                let pat = Pat { kind: PatKind::Var(n.clone()), span: t.span };
                (pat, Vec::new())
            }
            Tok::Underscore => {
                self.bump();
                (Pat { kind: PatKind::Wild, span: t.span }, Vec::new())
            }
            Tok::LParen | Tok::Upper(_) => {
                if let Some(d) = self.capital_binding() {
                    return Err(d);
                }
                let p = self.pattern()?;
                self.check_let_pattern(&p)?;
                (p, Vec::new())
            }
            _ => return Err(self.err_expected("binding name")),
        };
        let name_span = pat.span;
        self.expect(&Tok::Eq, "`=`")?;
        // (the item's layout is set aside while the value is read, and put
        // back where it stood, below what an error leaves open)
        let at = self.layout.len() - 1;
        self.layout.pop();
        let value = self.ce_expr(item_col, line, "let");
        self.layout.insert(at.min(self.layout.len()), Layout::CeItem { item_col, line, kw: "let" });
        let value = value?;
        let span = kw.span.to(value.span);
        Ok(LetDecl { pat, params, mutable, pure_, value, doc: None, name_span, span, active: None, case_spans: Vec::new() })
    }

    // ---- patterns -----------------------------------------------------

    pub fn pattern(&mut self) -> PResult<Pat> {
        let p = self.or_pattern()?;
        if self.check(&Tok::As) {
            self.bump();
            let t = self.raw().clone();
            match self.peek() {
                Some(Tok::Ident(n)) => {
                    let n = n.clone();
                    self.bump();
                    let span = p.span.to(t.span);
                    return Ok(Pat { kind: PatKind::As(Box::new(p), n, t.span), span });
                }
                _ => return Err(self.err_expected("a name after `as`")),
            }
        }
        Ok(p)
    }

    fn or_pattern(&mut self) -> PResult<Pat> {
        let first = self.app_pattern()?;
        if !self.check(&Tok::Bar) {
            return Ok(first);
        }
        let mut alts = vec![first];
        while self.eat(&Tok::Bar) {
            alts.push(self.app_pattern()?);
        }
        let span = alts[0].span.to(alts.last().unwrap().span);
        Ok(Pat { kind: PatKind::Or(alts), span })
    }

    fn app_pattern(&mut self) -> PResult<Pat> {
        if let Some(Tok::Upper(_)) = self.peek() {
            let (path, name, span) = self.pattern_ctor_path()?;
            if self.check(&Tok::LBrace) {
                return self.record_pattern(path, name, span);
            }
            let mut args = Vec::new();
            while let Some(t) = self.peek() {
                if !matches!(t, Tok::Int(_) | Tok::Str(_) | Tok::Ident(_) | Tok::Upper(_) | Tok::True | Tok::False | Tok::Underscore | Tok::LParen | Tok::LBracket) {
                    break;
                }
                args.push(self.atom_pattern()?);
            }
            let full = match args.last() {
                Some(a) => span.to(a.span),
                None => span,
            };
            return Ok(Pat { kind: PatKind::Ctor(path, name, args), span: full });
        }
        self.atom_pattern()
    }

    /// `C` or `M.C` in a pattern (one module level).
    fn pattern_ctor_path(&mut self) -> PResult<(Vec<String>, String, Span)> {
        let first = self.bump();
        let Tok::Upper(m) = first.tok else { unreachable!() };
        if !self.check(&Tok::Dot) {
            return Ok((Vec::new(), m, first.span));
        }
        self.bump();
        match self.peek().cloned() {
            Some(Tok::Upper(n)) => {
                let t = self.bump();
                Ok((vec![m], n, first.span.to(t.span)))
            }
            _ => Err(self.err_expected("a constructor name after `.`")),
        }
    }

    fn ctor_path(&mut self) -> PResult<(Vec<String>, String, Span)> {
        let first = self.bump();
        let mut name = match first.tok {
            Tok::Upper(n) => n,
            _ => unreachable!(),
        };
        let mut path = Vec::new();
        let mut span = first.span;
        while self.raw().tok == Tok::Dot {
            if let Tok::Upper(n) = self.raw_at(1).tok.clone() {
                self.bump();
                let t = self.bump();
                path.push(std::mem::replace(&mut name, n));
                span = span.to(t.span);
            } else {
                break;
            }
        }
        Ok((path, name, span))
    }

    fn record_pattern(&mut self, path: Vec<String>, name: String, start: Span) -> PResult<Pat> {
        self.bump(); // {
        let fields = self.with_layout(Layout::NoLayout, |p| {
            let mut fields = Vec::new();
            loop {
                let t = p.raw().clone();
                let fname = match &t.tok {
                    Tok::Ident(n) | Tok::Upper(n) => n.clone(),
                    _ => return Err(p.err_expected("field name")),
                };
                p.bump();
                let sub = if p.eat(&Tok::Eq) { Some(p.pattern()?) } else { None };
                fields.push((fname, t.span, sub));
                if p.eat(&Tok::Comma) {
                    if p.check(&Tok::RBrace) {
                        break;
                    }
                    continue;
                }
                break;
            }
            Ok(fields)
        })?;
        let close = self.close_bracket(&Tok::RBrace, "`}`")?;
        Ok(Pat { kind: PatKind::Record(path, name, start, fields), span: start.to(close.span) })
    }

    fn atom_pattern(&mut self) -> PResult<Pat> {
        self.skip_lex_errors();
        let t = match self.peek() {
            Some(_) => self.raw().clone(),
            None => return Err(self.err_expected("a pattern")),
        };
        match &t.tok {
            Tok::Underscore => {
                self.bump();
                Ok(Pat { kind: PatKind::Wild, span: t.span })
            }
            Tok::Ident(n) => {
                self.bump();
                Ok(Pat { kind: PatKind::Var(n.clone()), span: t.span })
            }
            Tok::Int(n) => {
                self.bump();
                Ok(Pat { kind: PatKind::Int(*n), span: t.span })
            }
            // a negative number; `-` before anything else is no pattern
            Tok::Minus if matches!(self.raw_at(1).tok, Tok::Int(_) | Tok::Float(_)) => {
                let m = self.bump();
                let t2 = self.raw().clone();
                match t2.tok {
                    Tok::Int(n) => {
                        self.bump();
                        Ok(Pat { kind: PatKind::Int(-n), span: m.span.to(t2.span) })
                    }
                    _ => Err(Diag::error(
                        "float literals can't be matched — float equality is unreliable; bind a variable and use a guard instead, e.g. `case x if x == 1.5:`",
                        m.span,
                    )),
                }
            }
            Tok::Float(_) => Err(Diag::error(
                "float literals can't be matched — float equality is unreliable; bind a variable and use a guard instead, e.g. `case x if x == 1.5:`",
                t.span,
            )),
            Tok::Str(s) => {
                self.bump();
                Ok(Pat { kind: PatKind::Str(s.clone()), span: t.span })
            }
            Tok::True => {
                self.bump();
                Ok(Pat { kind: PatKind::Bool(true), span: t.span })
            }
            Tok::False => {
                self.bump();
                Ok(Pat { kind: PatKind::Bool(false), span: t.span })
            }
            Tok::Upper(_) => {
                let (path, name, span) = self.pattern_ctor_path()?;
                if self.check(&Tok::LBrace) {
                    return self.record_pattern(path, name, span);
                }
                Ok(Pat { kind: PatKind::Ctor(path, name, Vec::new()), span })
            }
            Tok::LParen => {
                let open = self.bump();
                let r = self.with_layout(Layout::NoLayout, |p| {
                    let first = p.pattern()?;
                    if p.check(&Tok::Comma) {
                        let mut items = vec![first];
                        while p.eat(&Tok::Comma) {
                            items.push(p.pattern()?);
                        }
                        let c = p.expect(&Tok::RParen, "`)`")?;
                        return Ok((PatKind::Tuple(items), c.span));
                    }
                    let c = p.expect(&Tok::RParen, "`)`")?;
                    Ok((first.kind, c.span))
                })?;
                Ok(Pat { kind: r.0, span: open.span.to(r.1) })
            }
            Tok::LBracket => {
                let open = self.bump();
                let elems = self.with_layout(Layout::NoLayout, |p| {
                    let mut elems = Vec::new();
                    let mut star = false;
                    while !p.check(&Tok::RBracket) {
                        if p.check(&Tok::Star) {
                            let st = p.bump();
                            let t = p.raw().clone();
                            if star {
                                return Err(Diag::error(format!("a list pattern can have at most one `*` rest element, found {}", describe(&t.tok)), t.span));
                            }
                            star = true;
                            match &t.tok {
                                Tok::Ident(n) => {
                                    p.bump();
                                    elems.push(ListPatElem::Star(Some(n.clone()), st.span.to(t.span)));
                                }
                                Tok::Underscore => {
                                    p.bump();
                                    elems.push(ListPatElem::Star(None, st.span.to(t.span)));
                                }
                                _ => return Err(Diag::error(format!("the `*` rest binder must be a variable or `_`, found {}", describe(&t.tok)), t.span)),
                            }
                        } else {
                            elems.push(ListPatElem::Pat(p.pattern()?));
                        }
                        if !p.eat(&Tok::Comma) {
                            break;
                        }
                    }
                    Ok(elems)
                })?;
                let close = self.close_bracket(&Tok::RBracket, "`]`")?;
                Ok(Pat { kind: PatKind::List(elems), span: open.span.to(close.span) })
            }
            _ => Err(self.err_expected("a pattern")),
        }
    }

    // ---- types --------------------------------------------------------

    fn type_decl(&mut self, doc: Option<String>, opaque: bool) -> PResult<Decl> {
        let kw = self.bump(); // type
        let t = self.raw().clone();
        let name = match self.peek() {
            Some(Tok::Upper(n)) => {
                let n = n.clone();
                self.bump();
                n
            }
            _ => return Err(self.err_expected("type name")),
        };
        let mut params = Vec::new();
        while let Some(Tok::Ident(p)) | Some(Tok::Upper(p)) = self.peek().cloned() {
            self.bump();
            params.push(p);
        }
        self.expect(&Tok::Eq, "`=`")?;
        let nt = self.raw().clone();
        // (an indented body: a line further in than the declaration's block;
        // a `|` at its column only continues the declaration)
        let deeper = match self.layout.last() {
            Some(Layout::Block(c)) => nt.col > *c,
            _ => true,
        };
        // (an opaque type's own type does not start a block)
        let block_col = if !opaque && nt.bol && deeper && self.boundary_of(&nt) == Boundary::No && nt.tok != Tok::Eof { Some(nt.col) } else { None };
        if let Some(c) = block_col {
            self.layout.push(Layout::Block(c));
            self.anchor = nt.span.lo;
        }
        let body = (|| -> PResult<TypeBody> {
            if opaque {
                return Ok(TypeBody::Opaque(self.type_expr()?));
            }
            if self.check(&Tok::LBrace) {
                self.bump();
                let fields = self.with_layout(Layout::NoLayout, |p| {
                    let mut fields = Vec::new();
                    loop {
                        let t = p.raw().clone();
                        let fname = match &t.tok {
                            Tok::Ident(n) | Tok::Upper(n) => n.clone(),
                            _ => return Err(p.err_expected("field name")),
                        };
                        p.bump();
                        p.expect(&Tok::Colon, "`:`")?;
                        let ty = p.type_expr()?;
                        fields.push((fname, t.span, ty));
                        if p.eat(&Tok::Comma) {
                            if p.check(&Tok::RBrace) {
                                break;
                            }
                            continue;
                        }
                        break;
                    }
                    Ok(fields)
                })?;
                self.close_bracket(&Tok::RBrace, "`}`")?;
                return Ok(TypeBody::Record(fields));
            }
            let mut variants = Vec::new();
            self.eat(&Tok::Bar);
            loop {
                self.skip_lex_errors();
                let t = self.raw().clone();
                let vname = match &t.tok {
                    Tok::Upper(n) if self.boundary_of(&t) == Boundary::No => n.clone(),
                    _ => return Err(self.err_expected("constructor name")),
                };
                self.bump();
                let mut args = Vec::new();
                while let Some(tk) = self.peek() {
                    if matches!(tk, Tok::Ident(_) | Tok::Upper(_) | Tok::LParen) {
                        args.push(self.atom_type()?);
                    } else {
                        break;
                    }
                }
                variants.push(Variant { name: vname, span: t.span, args });
                if self.eat(&Tok::Bar) {
                    continue;
                }
                // in an indented body each line is a constructor (`|` optional)
                let nt = self.raw().clone();
                if block_col.is_some() && nt.tok != Tok::Eof && self.boundary_of(&nt) == Boundary::Statement {
                    self.anchor = nt.span.lo;
                    self.eat(&Tok::Bar);
                    continue;
                }
                break;
            }
            Ok(TypeBody::Sum(variants))
        })();
        // nothing may follow an indented declaration on its lines
        let body = body.and_then(|b| match self.peek() {
            Some(_) if block_col.is_some() => Err(Diag::error(format!("expected end of the type declaration, found {}", self.raw_describe()), self.raw_span())),
            _ => Ok(b),
        });
        if block_col.is_some() {
            self.pop_block(&body);
        }
        let body = body?;
        let span = Span::new(kw.span.lo, self.prev_end());
        Ok(Decl::Type(TypeDecl { name, name_span: t.span, params, body, doc, span }))
    }

    pub fn type_expr(&mut self) -> PResult<TypeExpr> {
        self.skip_lex_errors();
        self.type_on_its_line()?;
        self.type_expr_rest()
    }

    /// A type does not start on a line of its own (nor do an arrow's
    /// effects; the result after them may).
    fn type_on_its_line(&self) -> PResult<()> {
        let t = self.raw();
        // (a line at the block's column that continues is no indented one)
        let indented = match self.layout.last() {
            Some(Layout::Block(c)) => t.col > *c,
            _ => true,
        };
        if t.tok != Tok::Eof && t.bol && indented && self.layout_allows_blocks() && self.boundary_of(t) == Boundary::No && self.indented_block_start(t) {
            return Err(Diag::error("expected a type, found start of an indented block", Span::new(t.span.lo, t.span.lo)));
        }
        Ok(())
    }

    fn type_expr_rest(&mut self) -> PResult<TypeExpr> {
        let lhs = self.app_type()?;
        if self.check(&Tok::Arrow) {
            self.bump();
            self.skip_lex_errors();
            self.type_on_its_line()?;
            let mut effs = None;
            if self.check(&Tok::LBrace) {
                self.bump();
                let v = self.with_layout(Layout::NoLayout, |p| {
                    let mut v = Vec::new();
                    loop {
                        match p.raw().tok.clone() {
                            Tok::Ident(n) | Tok::Upper(n) => {
                                p.bump();
                                v.push(n);
                            }
                            _ => return Err(p.err_expected("effect label")),
                        }
                        if !p.eat(&Tok::Comma) {
                            break;
                        }
                    }
                    Ok(v)
                })?;
                self.close_bracket(&Tok::RBrace, "`}`")?;
                effs = Some(v);
            }
            self.skip_lex_errors();
            let rhs = self.type_expr_rest()?;
            let span = lhs.span.to(rhs.span);
            return Ok(TypeExpr { kind: TypeKind::Fun(Box::new(lhs), effs, Box::new(rhs)), span });
        }
        Ok(lhs)
    }

    fn app_type(&mut self) -> PResult<TypeExpr> {
        if let Some(Tok::Upper(_)) | Some(Tok::Ident(_)) = self.peek() {
            let t = self.raw().clone();
            if let Tok::Ident(_) = t.tok {
                return self.atom_type();
            }
            let (path, name, span) = self.type_name()?;
            let mut args = Vec::new();
            while let Some(tk) = self.peek() {
                if matches!(tk, Tok::Ident(_) | Tok::Upper(_) | Tok::LParen) {
                    args.push(self.atom_type()?);
                } else {
                    break;
                }
            }
            let full = match args.last() {
                Some(a) => span.to(a.span),
                None => span,
            };
            let ty = TypeExpr { kind: TypeKind::Con(path, name, args), span: full };
            return self.maybe_type_unit(ty);
        }
        self.atom_type()
    }

    fn type_name(&mut self) -> PResult<(Vec<String>, String, Span)> {
        let t = self.bump();
        let mut name = match t.tok {
            Tok::Upper(n) | Tok::Ident(n) => n,
            _ => unreachable!(),
        };
        let mut path = Vec::new();
        let mut span = t.span;
        while self.raw().tok == Tok::Dot {
            if let Tok::Upper(n) = self.raw_at(1).tok.clone() {
                self.bump();
                let t2 = self.bump();
                path.push(std::mem::replace(&mut name, n));
                span = span.to(t2.span);
            } else {
                break;
            }
        }
        Ok((path, name, span))
    }

    fn maybe_type_unit(&mut self, ty: TypeExpr) -> PResult<TypeExpr> {
        // units are never written in declared types: `float<m>` is inferred
        let t = self.raw();
        if false && t.tok == Tok::Lt && !t.space_before {
            self.bump();
            let u = self.with_layout(Layout::NoLayout, |p| p.type_unit_expr())?;
            let gt = self.expect_raw(&Tok::Gt, "`>`")?;
            let span = ty.span.to(gt.span);
            return Ok(TypeExpr { kind: TypeKind::Measured(Box::new(ty), u), span });
        }
        Ok(ty)
    }

    /// Units inside types may also name unit variables `'u` — the lexer
    /// rejects `'`, so they are written as plain lowercase names here.
    fn type_unit_expr(&mut self) -> PResult<UnitExpr> {
        self.unit_expr()
    }

    fn atom_type(&mut self) -> PResult<TypeExpr> {
        let t = match self.peek() {
            Some(_) => self.raw().clone(),
            None => return Err(self.err_expected("a type")),
        };
        match &t.tok {
            Tok::Ident(n) => {
                self.bump();
                // builtin lowercase type names
                if matches!(n.as_str(), "int" | "float" | "bool" | "string" | "unit") {
                    let ty = TypeExpr { kind: TypeKind::Con(Vec::new(), n.clone(), Vec::new()), span: t.span };
                    return self.maybe_type_unit(ty);
                }
                Ok(TypeExpr { kind: TypeKind::Var(n.clone()), span: t.span })
            }
            Tok::Upper(_) => {
                let (path, name, span) = self.type_name()?;
                let ty = TypeExpr { kind: TypeKind::Con(path, name, Vec::new()), span };
                self.maybe_type_unit(ty)
            }
            Tok::LParen => {
                let open = self.bump();
                let r = self.with_layout(Layout::NoLayout, |p| {
                    if p.check(&Tok::RParen) {
                        let c = p.bump();
                        return Ok((TypeKind::Con(Vec::new(), "unit".into(), Vec::new()), c.span, None));
                    }
                    let first = p.type_expr()?;
                    if p.check(&Tok::Comma) {
                        let mut items = vec![first];
                        while p.eat(&Tok::Comma) {
                            items.push(p.type_expr()?);
                        }
                        let c = p.expect(&Tok::RParen, "`)`")?;
                        return Ok((TypeKind::Tuple(items), c.span, None));
                    }
                    let c = p.expect(&Tok::RParen, "`)`")?;
                    Ok((first.kind, c.span, Some(first.span)))
                })?;
                // parentheses only group: the type keeps its own span
                let span = match r.2 {
                    Some(inner) => inner,
                    None => open.span.to(r.1),
                };
                Ok(TypeExpr { kind: r.0, span })
            }
            _ => Err(self.err_expected("a type")),
        }
    }

    // ---- measure / extern ---------------------------------------------

    fn measure_decl(&mut self) -> PResult<Decl> {
        let kw = self.bump();
        let name = match self.peek().cloned() {
            Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                self.bump();
                n
            }
            _ => return Err(self.err_expected("measure name")),
        };
        if self.check(&Tok::Eq) {
            self.bump();
            // a unit does not start on a line of its own
            let t = self.raw();
            if t.tok != Tok::Eof && t.bol && self.boundary_of(t) == Boundary::No && self.indented_block_start(t) {
                return Err(Diag::error("expected a unit (e.g. `m`, `m/s`, or `1`), found start of an indented block", Span::new(t.span.lo, t.span.lo)));
            }
            let u = self.unit_expr()?;
            let span = kw.span.to(u.span);
            return Ok(Decl::Measure(name, Some(u), span));
        }
        Ok(Decl::Measure(name, None, Span::new(kw.span.lo, self.prev_end())))
    }

    fn extern_decl(&mut self, doc: Option<String>) -> PResult<Decl> {
        let kw = self.bump();
        if self.check(&Tok::Type) {
            self.bump();
            let t = self.raw().clone();
            let name = match self.peek() {
                Some(Tok::Upper(n)) => {
                    let n = n.clone();
                    self.bump();
                    n
                }
                _ => return Err(self.err_expected("type name")),
            };
            let mut params = Vec::new();
            while let Some(Tok::Ident(p)) = self.peek().cloned() {
                self.bump();
                params.push(p);
            }
            return Ok(Decl::ExternType(name, params, Span::new(kw.span.lo, self.prev_end()), doc));
        }
        if self.check(&Tok::Import) {
            self.bump();
            let mut path = Vec::new();
            loop {
                match self.peek().cloned() {
                    Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                        self.bump();
                        path.push(n);
                    }
                    _ => return Err(self.err_expected("Python module")),
                }
                if self.check(&Tok::Dot) {
                    self.bump();
                    continue;
                }
                break;
            }
            let mut alias = None;
            if self.check(&Tok::As) {
                self.bump();
                match self.peek().cloned() {
                    Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                        self.bump();
                        alias = Some(n);
                    }
                    _ => return Err(self.err_expected("import alias")),
                }
            }
            return Ok(Decl::ExternImport(path, alias, Span::new(kw.span.lo, self.prev_end())));
        }
        let mut pure_ = false;
        if self.check(&Tok::Pure) {
            self.bump();
            pure_ = true;
        }
        let t = self.raw().clone();
        let name = match self.peek() {
            Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                let n = n.clone();
                self.bump();
                n
            }
            _ => return Err(self.err_expected("extern name")),
        };
        self.expect(&Tok::Colon, "`:`")?;
        let ty = self.type_expr()?;
        let mut target = None;
        let mut kwargs = None;
        let mut target_span = t.span;
        if self.check(&Tok::Eq) {
            self.bump();
            let nt = self.raw();
            // (a line indented past the declaration's block; a `.` at its
            // column only continues it)
            let indented = match self.layout.last() {
                Some(Layout::Block(c)) => nt.col > *c,
                _ => true,
            };
            if nt.tok != Tok::Eof && nt.bol && self.boundary_of(nt) == Boundary::No && indented {
                return Err(Diag::error("expected Python target, found start of an indented block", Span::new(nt.span.lo, nt.span.lo)));
            }
            let ts = self.raw().span.lo;
            if self.check(&Tok::Dot) {
                self.bump();
                let mut n = match self.peek().cloned() {
                    Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                        self.bump();
                        n
                    }
                    _ => return Err(self.err_expected("Python target")),
                };
                // `.a.b`: an attribute path on the receiver
                while self.raw().tok == Tok::Dot {
                    self.bump();
                    match self.peek().cloned() {
                        Some(Tok::Ident(m)) | Some(Tok::Upper(m)) => {
                            self.bump();
                            n.push('.');
                            n.push_str(&m);
                        }
                        _ => return Err(self.err_expected("Python attribute")),
                    }
                }
                let call = self.check(&Tok::LParen);
                target = Some(ExternTarget::Member(n, call));
            } else {
                let mut path = Vec::new();
                loop {
                    match self.peek().cloned() {
                        Some(Tok::Ident(n)) | Some(Tok::Upper(n)) => {
                            self.bump();
                            path.push(n);
                        }
                        _ => return Err(self.err_expected(if path.is_empty() { "Python target" } else { "Python attribute" })),
                    }
                    if self.raw().tok == Tok::Dot {
                        self.bump();
                        continue;
                    }
                    break;
                }
                target = Some(ExternTarget::Path(path));
            }
            target_span = Span::new(ts, self.prev_end());
            if self.check(&Tok::LParen) {
                self.bump();
                let kws = self.with_layout(Layout::NoLayout, |p| {
                    let mut kws = Vec::new();
                    while !p.check(&Tok::RParen) {
                        let k = match p.raw().tok.clone() {
                            Tok::Ident(n) | Tok::Upper(n) => {
                                p.bump();
                                n
                            }
                            _ => return Err(p.err_expected("keyword-argument name")),
                        };
                        p.expect(&Tok::Eq, "`=`")?;
                        let neg = p.eat(&Tok::Minus);
                        let v = match p.raw().tok.clone() {
                            Tok::Ellipsis => KwValue::Slot,
                            Tok::Int(n) => KwValue::Int(if neg { -n } else { n }),
                            Tok::Float(f) => KwValue::Float(if neg { -f } else { f }),
                            Tok::Str(s) => KwValue::Str(s),
                            Tok::True => KwValue::Bool(true),
                            Tok::False => KwValue::Bool(false),
                            _ => return Err(p.err_expected("`...` or a string, number, or bool literal")),
                        };
                        p.bump();
                        kws.push((k, v));
                        if !p.eat(&Tok::Comma) {
                            break;
                        }
                    }
                    Ok(kws)
                })?;
                self.close_bracket(&Tok::RParen, "`)`")?;
                if let Some(ExternTarget::Member(_, call)) = &mut target {
                    *call = true;
                }
                kwargs = Some(kws);
            }
        }
        let span = Span::new(kw.span.lo, self.prev_end());
        Ok(Decl::Extern(ExternDecl { name, name_span: t.span, pure_, ty, target, kwargs, target_span, doc, span }))
    }
}

/// The language server's parse: every lexer error, every declaration's
/// parse error, and the declarations that parsed.
pub fn parse_program_recover(src: &str) -> (Program, Vec<Diag>, Vec<Diag>) {
    let (lexed, lex_errors) = crate::lexer::lex_all(src);
    let mut p = Parser::new(lexed.toks, lexed.docs);
    let (prog, errors) = p.program_recover();
    (prog, lex_errors, errors)
}

pub fn parse_program(src: &str) -> Result<Program, Diag> {
    let lexed = crate::lexer::lex(src);
    if let Some(e) = lexed.error {
        return Err(e);
    }
    let mut p = Parser::new(lexed.toks, lexed.docs);
    p.program()
}
