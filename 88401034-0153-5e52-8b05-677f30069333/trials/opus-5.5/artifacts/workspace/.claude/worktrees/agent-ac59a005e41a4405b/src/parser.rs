// Recursive-descent JavaScript parser.

use crate::ast::*;
use crate::lexer::{LexError, Lexer, Tok, Token};
use std::rc::Rc;

#[derive(Debug, Clone)]
pub struct ParseError {
    pub msg: String,
    pub line: u32,
}

impl From<LexError> for ParseError {
    fn from(e: LexError) -> Self {
        ParseError { msg: e.msg, line: e.line }
    }
}

type PResult<T> = Result<T, ParseError>;

#[derive(Clone, Copy, Default)]
struct Ctx {
    in_function: bool,
    in_generator: bool,
    in_async: bool,
    strict: bool,
    in_class_body: bool,
    allow_super_call: bool,
    allow_super_prop: bool,
    allow_new_target: bool,
    in_field_init: bool,
    in_static_block: bool,
    allow_return: bool,
    in_params: bool,
}

#[derive(Clone)]
struct Label {
    name: Rc<str>,
    is_loop: bool,
}

pub struct Parser {
    lex: Lexer,
    tok: Token,
    prev_end: usize,
    prev_line: u32,
    ctx: Ctx,
    labels: Vec<Label>,
    breakable_depth: u32,
    loop_depth: u32,
    is_module: bool,
    source: Rc<str>,
    template_counter: usize,
    has_tla: bool,
    /// private names declared in enclosing class bodies
    private_scopes: Vec<Vec<Rc<str>>>,
    /// unresolved private name references (checked when class body closes)
    private_refs: Vec<Vec<(Rc<str>, usize)>>,
    /// bare private names in expressions (position, message): reported after parsing
    bare_private: Vec<(usize, String)>,
    /// private names not declared by any enclosing class (position, message)
    undeclared_private: Vec<(usize, String)>,
    /// cover-initialized names (`{a = 1}`) consumed by a destructuring target conversion
    cover_consumed: usize,
    /// a cover-initialized name was used outside a destructuring pattern (reported after
    /// parsing and scope analysis, like the reference engine)
    cover_error: bool,
    /// number of cover-initialized names seen ({a = 1} in object literal) that are not yet converted
    cover_init_count: usize,
    pub repl_mode: bool,
    /// parsing the body of an if/loop/with statement (labelled functions are not allowed)
    in_sub_stmt: bool,
    /// the previous token was `)` (the reference engine then tokenizes `/` as division)
    prev_rparen: bool,
    /// where `using` declarations are being parsed: 1 script top level, 2 case clause
    using_ctx: u8,
    /// unresolved private names outside any class are early errors (not for direct eval code)
    strict_private: bool,
    /// start positions of array literals ending in `...x,]` (invalid as assignment patterns)
    spread_trailing_comma: Vec<usize>,
}

struct SavedState {
    pos: usize,
    line: u32,
    tok: Token,
    prev_end: usize,
    prev_line: u32,
    cover: usize,
    prev_rparen: bool,
    bare_len: usize,
    cover_error: bool,
}

fn is_prototype_key(k: &PropKey) -> bool {
    match k {
        PropKey::Ident(n) => &**n == "prototype",
        PropKey::Str(s) => String::from_utf16_lossy(s) == "prototype",
        _ => false,
    }
}

fn is_reserved_strict(name: &str) -> bool {
    matches!(
        name,
        "implements" | "interface" | "let" | "package" | "private" | "protected" | "public" | "static" | "yield"
    )
}

static TEMPLATE_ID: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(1);

impl Parser {
    pub fn new(src: &str, is_module: bool) -> PResult<Parser> {
        let mut lex = Lexer::new(src, is_module);
        let tok = lex.next_token()?;
        Ok(Parser {
            lex,
            tok,
            prev_end: 0,
            prev_line: 1,
            ctx: Ctx { allow_return: false, strict: is_module, in_async: false, ..Default::default() },
            labels: Vec::new(),
            breakable_depth: 0,
            loop_depth: 0,
            is_module,
            source: Rc::from(src),
            template_counter: 0,
            has_tla: false,
            private_scopes: Vec::new(),
            private_refs: Vec::new(),
            bare_private: Vec::new(),
            undeclared_private: Vec::new(),
            cover_consumed: 0,
            cover_error: false,
            cover_init_count: 0,
            repl_mode: false,
            in_sub_stmt: false,
            prev_rparen: false,
            using_ctx: 0,
            strict_private: true,
            spread_trailing_comma: Vec::new(),
        })
    }

    // ---------- token helpers ----------

    fn err<T>(&self, msg: impl Into<String>) -> PResult<T> {
        Err(ParseError { msg: msg.into(), line: self.tok.line })
    }

    fn err_line<T>(&self, msg: impl Into<String>, line: u32) -> PResult<T> {
        Err(ParseError { msg: msg.into(), line })
    }

    fn unexpected<T>(&self) -> PResult<T> {
        let desc = match &self.tok.tok {
            Tok::Punct(p) => format!("Punct({:?})", p),
            Tok::Keyword(k) => format!("Keyword({:?})", k),
            Tok::Eof => "Eof".to_string(),
            Tok::Ident(n) => format!("Ident({:?})", n),
            Tok::Num(n) => format!("Num({:?})", n),
            Tok::Str(s) => format!("Str({:?})", String::from_utf16_lossy(s)),
            Tok::BigInt(s) => format!("BigInt({:?})", s),
            Tok::Template { .. } => "Template".to_string(),
            Tok::Regex { .. } => "Regex".to_string(),
            Tok::PrivateName(n) => format!("PrivateName({:?})", n),
        };
        self.err(format!("unexpected token {}", desc))
    }

    fn advance(&mut self) -> PResult<Token> {
        let next = self.lex.next_token()?;
        let old = std::mem::replace(&mut self.tok, next);
        self.prev_end = old.end;
        self.prev_line = old.line;
        self.prev_rparen = matches!(old.tok, Tok::Punct(")"));
        Ok(old)
    }

    /// The reference engine tokenizes `/` without parser context: after `++`/`--` and after
    /// the identifiers `yield`/`await` it starts a regular expression.
    fn relex_slash_as_regex(&mut self) -> PResult<()> {
        if self.is_punct("/") || self.is_punct("/=") {
            let t = self.lex.read_regex(self.tok.start, self.tok.line, self.tok.nl_before)?;
            self.tok = t;
        }
        Ok(())
    }

    fn is_punct(&self, p: &str) -> bool {
        matches!(&self.tok.tok, Tok::Punct(q) if *q == p)
    }
    fn is_kw(&self, k: &str) -> bool {
        matches!(&self.tok.tok, Tok::Keyword(q) if *q == k)
    }
    fn is_ident_named(&self, n: &str) -> bool {
        matches!(&self.tok.tok, Tok::Ident(q) if q == n) && !self.tok.escaped
    }
    fn eat_punct(&mut self, p: &str) -> PResult<bool> {
        if self.is_punct(p) {
            self.advance()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }
    fn expect_punct(&mut self, p: &str) -> PResult<()> {
        if self.is_punct(p) {
            self.advance()?;
            Ok(())
        } else {
            self.err(format!("expected '{}'", p))
        }
    }
    fn eat_kw(&mut self, k: &str) -> PResult<bool> {
        if self.is_kw(k) {
            self.advance()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    fn save(&self) -> SavedState {
        SavedState {
            pos: self.lex.pos,
            line: self.lex.line,
            tok: self.tok.clone(),
            prev_end: self.prev_end,
            prev_rparen: self.prev_rparen,
            prev_line: self.prev_line,
            cover: self.cover_init_count,
            bare_len: self.bare_private.len(),
            cover_error: self.cover_error,
        }
    }
    fn restore(&mut self, s: SavedState) {
        self.lex.pos = s.pos;
        self.lex.line = s.line;
        self.tok = s.tok;
        self.prev_end = s.prev_end;
        self.prev_line = s.prev_line;
        self.cover_init_count = s.cover;
        self.prev_rparen = s.prev_rparen;
        self.bare_private.truncate(s.bare_len);
        self.cover_error = s.cover_error;
    }

    /// the first (in source order) deferred private-name error
    fn take_deferred_private(&mut self) -> Option<String> {
        if self.cover_error {
            return Some("invalid shorthand property initializer".into());
        }
        let mut all: Vec<(usize, String)> = std::mem::take(&mut self.bare_private);
        all.extend(std::mem::take(&mut self.undeclared_private));
        all.into_iter().min_by_key(|(p, _)| *p).map(|(_, m)| m)
    }

    fn consume_semicolon(&mut self) -> PResult<()> {
        if self.is_punct(";") {
            self.advance()?;
            return Ok(());
        }
        if self.is_punct("}") || matches!(self.tok.tok, Tok::Eof) || self.tok.nl_before {
            return Ok(());
        }
        self.err("expected ';'")
    }

    fn peek_token(&mut self) -> PResult<Token> {
        let s = self.save();
        self.advance()?;
        let t = self.tok.clone();
        self.restore(s);
        Ok(t)
    }

    fn ident_name_of_tok(&self) -> Option<String> {
        match &self.tok.tok {
            Tok::Ident(n) => Some(n.clone()),
            Tok::Keyword(k) => Some(k.to_string()),
            _ => None,
        }
    }

    /// current token is a binding identifier in the current context?
    fn is_binding_ident(&self) -> bool {
        match &self.tok.tok {
            Tok::Ident(n) => {
                if n == "yield" && (self.ctx.in_generator || self.ctx.strict) {
                    return false;
                }
                if n == "await" && (self.ctx.in_async || self.is_module || self.ctx.in_static_block) {
                    return false;
                }
                true
            }
            _ => false,
        }
    }

    fn check_binding_name(&self, name: &str, line: u32) -> PResult<()> {
        if self.ctx.strict {
            if name == "eval" || name == "arguments" || is_reserved_strict(name) {
                return self.err_line(format!("'{}' cannot be used as a binding in strict mode", name), line);
            }
        }
        Ok(())
    }

    fn binding_ident(&mut self) -> PResult<Ident> {
        if let Tok::PrivateName(_) = &self.tok.tok {
            return self.err("private names cannot be used as binding identifiers");
        }
        if let Tok::Ident(n) = &self.tok.tok {
            if self.tok.escaped && crate::lexer::keyword_of(n).is_some() {
                return self.err("expected binding identifier");
            }
            if n == "yield" {
                if self.ctx.strict {
                    return self.err("'yield' cannot be used as a binding in strict mode");
                }
                if self.ctx.in_generator {
                    return self.err("'yield' cannot be used as a binding here");
                }
            }
            if n == "await" && (self.ctx.in_async || self.is_module || self.ctx.in_static_block) {
                return self.err("'await' cannot be used as a binding here");
            }
        }
        if !self.is_binding_ident() {
            return self.err("expected binding identifier");
        }
        let line = self.tok.line;
        let name = match self.advance()?.tok {
            Tok::Ident(n) => n,
            _ => unreachable!(),
        };
        self.check_binding_name(&name, line)?;
        Ok(Ident { name: Rc::from(name.as_str()), line })
    }

    // ---------- program ----------

    pub fn parse_program(mut self) -> PResult<Program> {
        let strict = self.is_module;
        self.ctx.strict = strict;
        if self.is_module {
            self.ctx.in_async = false;
        }
        let (body, strict) = self.parse_directives_and_body(true, strict)?;
        let deferred_error = self.take_deferred_private();
        Ok(Program {
            body,
            strict,
            is_module: self.is_module,
            scope: ScopeId::new(),
            source: self.source.clone(),
            has_top_level_await: self.has_tla,
            deferred_error,
        })
    }

    pub fn into_source(&self) -> Rc<str> {
        self.source.clone()
    }

    /// Parses statements until EOF (top) or '}' (function body), handling directive prologue.
    fn parse_directives_and_body(&mut self, top: bool, strict: bool) -> PResult<(Vec<Stmt>, bool)> {
        let saved = self.in_sub_stmt;
        self.in_sub_stmt = false;
        let saved_using = self.using_ctx;
        self.using_ctx = if top && !self.is_module && !self.ctx.in_function { 1 } else { 0 };
        let r = self.parse_directives_and_body_inner(top, strict);
        self.in_sub_stmt = saved;
        self.using_ctx = saved_using;
        r
    }

    fn check_using_allowed(&self) -> PResult<()> {
        match self.using_ctx {
            1 => self.err("'using' declaration is not allowed at the top level of a script"),
            2 => self.err("'using' declaration is not allowed directly in a case clause"),
            _ => Ok(()),
        }
    }

    fn parse_directives_and_body_inner(&mut self, top: bool, mut strict: bool) -> PResult<(Vec<Stmt>, bool)> {
        let mut body = Vec::new();
        let mut in_prologue = true;
        let mut octal_before: Option<u32> = None;
        loop {
            if top {
                if matches!(self.tok.tok, Tok::Eof) {
                    break;
                }
            } else if self.is_punct("}") {
                break;
            } else if matches!(self.tok.tok, Tok::Eof) {
                return self.err("expected '}'");
            }
            if in_prologue {
                if let Tok::Str(s) = &self.tok.tok {
                    let raw = self.lex.slice(self.tok.start, self.tok.end);
                    let is_use_strict = raw == "\"use strict\"" || raw == "'use strict'";
                    let s = s.clone();
                    let had_octal = self.tok.octal_escape;
                    let line = self.tok.line;
                    // check it's an expression statement consisting only of the string
                    let next = self.peek_token()?;
                    let ends = matches!(next.tok, Tok::Punct(";") | Tok::Punct("}") | Tok::Eof) || next.nl_before;
                    let continues_expr = matches!(&next.tok, Tok::Punct(p) if *p != ";" && *p != "}")
                        && !next.nl_before;
                    if ends && !continues_expr {
                        if had_octal && octal_before.is_none() {
                            octal_before = Some(line);
                        }
                        if is_use_strict {
                            strict = true;
                            self.ctx.strict = true;
                            if let Some(l) = octal_before {
                                return self.err_line("legacy octal literals are not allowed in strict mode", l);
                            }
                        }
                        let _ = s;
                        let st = self.parse_statement_list_item()?;
                        body.push(st);
                        continue;
                    }
                }
                in_prologue = false;
            }
            let st = self.parse_statement_list_item()?;
            body.push(st);
        }
        Ok((body, strict))
    }

    // ---------- statements ----------

    fn parse_statement_list_item(&mut self) -> PResult<Stmt> {
        match &self.tok.tok {
            Tok::Keyword("function") => {
                let f = self.parse_function_decl(false)?;
                Ok(Stmt::Function(f))
            }
            Tok::Keyword("class") => {
                let c = self.parse_class(true)?;
                Ok(Stmt::Class(c))
            }
            Tok::Punct("@") => {
                let decorators = self.parse_decorators()?;
                if self.is_kw("export") && self.is_module {
                    return self.parse_export(decorators);
                }
                // (the reference engine also accepts a decorated class without the `class`
                // keyword)
                if !self.is_kw("class") && !self.is_punct("{") && !self.is_kw("extends") {
                    return self.err("expected '{'");
                }
                let mut c = self.parse_class(true)?;
                if let Some(cm) = Rc::get_mut(&mut c) {
                    cm.decorators = decorators;
                }
                Ok(Stmt::Class(c))
            }
            Tok::Keyword("const") => {
                let d = self.parse_var_decl(VarKind::Const, false)?;
                self.consume_semicolon()?;
                Ok(Stmt::Var(d))
            }
            Tok::Ident(n) if n == "let" && !self.tok.escaped => {
                // `let` as declaration if followed by identifier, [ or {
                let next = self.peek_token()?;
                let is_decl = match &next.tok {
                    Tok::Ident(_) | Tok::PrivateName(_) => true,
                    Tok::Punct("[") | Tok::Punct("{") => true,
                    // `let` followed by a reserved word is an identifier expression
                    _ => false,
                };
                if is_decl {
                    let d = self.parse_var_decl(VarKind::Let, false)?;
                    self.consume_semicolon()?;
                    Ok(Stmt::Var(d))
                } else {
                    self.parse_statement()
                }
            }
            Tok::Ident(n) if n == "async" && !self.tok.escaped => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Keyword("function")) && !next.nl_before {
                    let f = self.parse_function_decl(true)?;
                    Ok(Stmt::Function(f))
                } else {
                    self.parse_statement()
                }
            }
            Tok::Ident(n) if n == "using" && !self.tok.escaped => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Ident(ref m) if m != "in" && m != "of") && !next.nl_before {
                    self.check_using_allowed()?;
                    let d = self.parse_var_decl(VarKind::Using, false)?;
                    self.consume_semicolon()?;
                    Ok(Stmt::Var(d))
                } else {
                    self.parse_statement()
                }
            }
            Tok::Ident(n) if n == "await" && !self.tok.escaped && (self.ctx.in_async || self.is_module) => {
                // await using x = ...
                let s = self.save();
                self.advance()?;
                if self.is_ident_named("using") && !self.tok.nl_before {
                    let next = self.peek_token()?;
                    if matches!(next.tok, Tok::Ident(_)) && !next.nl_before {
                        if !self.ctx.in_function {
                            self.has_tla = true;
                        }
                        self.restore(s);
                        self.check_using_allowed()?;
                        let d = self.parse_var_decl(VarKind::AwaitUsing, false)?;
                        self.consume_semicolon()?;
                        return Ok(Stmt::Var(d));
                    }
                }
                self.restore(s);
                self.parse_statement()
            }
            Tok::Keyword("import") if self.is_module => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct("(") | Tok::Punct(".")) {
                    return self.parse_statement();
                }
                self.parse_import()
            }
            Tok::Keyword("export") => {
                if !self.is_module {
                    return self.err("'export' declaration may only appear at the top level of a module");
                }
                self.parse_export(Vec::new())
            }
            _ => self.parse_statement(),
        }
    }

    fn parse_statement(&mut self) -> PResult<Stmt> {
        let line = self.tok.line;
        match self.tok.tok.clone() {
            Tok::Punct("{") => Ok(Stmt::Block(self.parse_block()?)),
            Tok::Punct(";") => {
                self.advance()?;
                Ok(Stmt::Empty)
            }
            Tok::Keyword("var") => {
                let d = self.parse_var_decl(VarKind::Var, false)?;
                self.consume_semicolon()?;
                Ok(Stmt::Var(d))
            }
            Tok::Keyword("if") => {
                self.advance()?;
                self.expect_punct("(")?;
                let test = self.parse_expression(false)?;
                self.expect_punct(")")?;
                let cons = self.parse_substatement_kind(true)?;
                let alt = if self.eat_kw("else")? { Some(Box::new(self.parse_substatement_kind(true)?)) } else { None };
                Ok(Stmt::If(test, Box::new(cons), alt))
            }
            Tok::Keyword("for") => self.parse_for(),
            Tok::Keyword("while") => {
                self.advance()?;
                self.expect_punct("(")?;
                let test = self.parse_expression(false)?;
                self.expect_punct(")")?;
                let body = self.parse_loop_body()?;
                Ok(Stmt::While(test, Box::new(body)))
            }
            Tok::Keyword("do") => {
                self.advance()?;
                let body = self.parse_loop_body()?;
                if !self.is_kw("while") {
                    return self.err("expected 'while' after do-body");
                }
                self.advance()?;
                self.expect_punct("(")?;
                let test = self.parse_expression(false)?;
                self.expect_punct(")")?;
                // semicolon optional after do-while
                self.eat_punct(";")?;
                Ok(Stmt::DoWhile(Box::new(body), test))
            }
            Tok::Keyword("continue") => {
                self.advance()?;
                let label = if !self.tok.nl_before && matches!(self.tok.tok, Tok::Ident(_) | Tok::PrivateName(_)) {
                    let n = match &self.tok.tok {
                        Tok::PrivateName(p) => format!("#{}", p),
                        _ => self.ident_name_of_tok().unwrap(),
                    };
                    self.advance()?;
                    Some(Rc::from(n.as_str()))
                } else {
                    None
                };
                match &label {
                    Some(l) => {
                        let found = self.labels.iter().rev().find(|x| x.name == *l).cloned();
                        match found {
                            Some(lab) if lab.is_loop => {}
                            Some(_) => return self.err_line("continue label does not target an iteration statement", line),
                            None => return self.err_line("undefined continue label", line),
                        }
                    }
                    None => {
                        if self.loop_depth == 0 {
                            return self.err_line("illegal 'continue' statement", line);
                        }
                    }
                }
                self.consume_semicolon()?;
                Ok(Stmt::Continue(label))
            }
            Tok::Keyword("break") => {
                self.advance()?;
                let label = if !self.tok.nl_before && matches!(self.tok.tok, Tok::Ident(_) | Tok::PrivateName(_)) {
                    let n = match &self.tok.tok {
                        Tok::PrivateName(p) => format!("#{}", p),
                        _ => self.ident_name_of_tok().unwrap(),
                    };
                    self.advance()?;
                    Some(Rc::from(n.as_str()))
                } else {
                    None
                };
                match &label {
                    Some(l) => {
                        if !self.labels.iter().any(|x| x.name == *l) {
                            return self.err_line("undefined break label", line);
                        }
                    }
                    None => {
                        if self.breakable_depth == 0 {
                            return self.err_line("illegal 'break' statement", line);
                        }
                    }
                }
                self.consume_semicolon()?;
                Ok(Stmt::Break(label))
            }
            Tok::Keyword("return") => {
                if !self.ctx.allow_return {
                    if self.ctx.in_static_block {
                        return self.err("'return' is not allowed directly in a class static block");
                    }
                    return self.err("'return' outside of a function");
                }
                self.advance()?;
                let arg = if self.is_punct(";") || self.is_punct("}") || matches!(self.tok.tok, Tok::Eof) || self.tok.nl_before
                {
                    None
                } else {
                    Some(self.parse_expression(false)?)
                };
                self.consume_semicolon()?;
                Ok(Stmt::Return(arg))
            }
            Tok::Keyword("throw") => {
                self.advance()?;
                if self.tok.nl_before {
                    return self.err("illegal newline after throw");
                }
                let e = self.parse_expression(false)?;
                self.consume_semicolon()?;
                Ok(Stmt::Throw(e))
            }
            Tok::Keyword("try") => self.parse_try(),
            Tok::Keyword("switch") => self.parse_switch(),
            Tok::Keyword("with") => {
                if self.ctx.strict {
                    return self.err("'with' statements are not allowed in strict mode");
                }
                self.advance()?;
                self.expect_punct("(")?;
                let obj = self.parse_expression(false)?;
                self.expect_punct(")")?;
                let body = self.parse_substatement()?;
                Ok(Stmt::With(obj, Box::new(body), ScopeId::new()))
            }
            Tok::Keyword("debugger") => {
                self.advance()?;
                self.consume_semicolon()?;
                Ok(Stmt::Debugger)
            }
            Tok::Keyword("function") => {
                // function declaration in statement position (sloppy: allowed in if bodies, labels)
                let f = self.parse_function_decl(false)?;
                Ok(Stmt::Function(f))
            }
            Tok::Keyword("class") => self.unexpected(),
            Tok::Keyword("const") => {
                let d = self.parse_var_decl(VarKind::Const, false)?;
                self.consume_semicolon()?;
                Ok(Stmt::Var(d))
            }
            Tok::Ident(name) if !self.tok.escaped || true => {
                // labeled statement?
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct(":")) && self.is_binding_ident_or_keyword_label() {
                    self.advance()?;
                    self.advance()?;
                    let name: Rc<str> = Rc::from(name.as_str());
                    if self.labels.iter().any(|l| l.name == name) {
                        return self.err_line(format!("label '{}' has already been declared", name), line);
                    }
                    let is_loop = matches!(self.tok.tok, Tok::Keyword("for") | Tok::Keyword("while") | Tok::Keyword("do"));
                    self.labels.push(Label { name: name.clone(), is_loop });
                    // a labeled non-loop statement can be the target of break
                    self.breakable_depth += 1;
                    let body = if self.is_kw("function") {
                        if self.ctx.strict || self.in_sub_stmt {
                            let fline = self.tok.line;
                            let r = self.parse_function_decl(false);
                            self.breakable_depth -= 1;
                            self.labels.pop();
                            r?;
                            return self.err_line("function declaration cannot appear in a single-statement context", fline);
                        }
                        let f = self.parse_function_decl(false)?;
                        if f.is_generator || f.is_async {
                            self.breakable_depth -= 1;
                            self.labels.pop();
                            return self.err_line("a labelled function declaration must be a plain function", f.line);
                        }
                        Stmt::Function(f)
                    } else {
                        if let Some(e) = self.check_declaration_in_substatement()? {
                            let r = self.parse_statement_list_item();
                            self.breakable_depth -= 1;
                            self.labels.pop();
                            r?;
                            return Err(e);
                        }
                        self.parse_statement()?
                    };
                    self.breakable_depth -= 1;
                    self.labels.pop();
                    return Ok(Stmt::Labeled(name, Box::new(body)));
                }
                self.parse_expression_statement()
            }
            Tok::PrivateName(_) => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct(":")) {
                    return self.err("private names cannot be used as labels");
                }
                self.parse_expression_statement()
            }
            _ => self.parse_expression_statement(),
        }
    }

    fn is_binding_ident_or_keyword_label(&self) -> bool {
        match &self.tok.tok {
            Tok::Ident(n) => {
                if n == "yield" && (self.ctx.in_generator || self.ctx.strict) {
                    return false;
                }
                if n == "await" && (self.ctx.in_async || self.is_module) {
                    return false;
                }
                true
            }
            _ => false,
        }
    }

    /// errors for declarations used where only a statement is allowed
    fn check_declaration_in_substatement(&mut self) -> PResult<Option<ParseError>> {
        match &self.tok.tok {
            Tok::Keyword("class") | Tok::Keyword("const") => {
                return Ok(Some(ParseError { msg: "lexical declaration cannot appear in a single-statement context".into(), line: self.tok.line }));
            }
            Tok::Ident(n) if n == "let" && !self.tok.escaped => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct("[")) {
                    return Ok(Some(ParseError { msg: "lexical declaration cannot appear in a single-statement context".into(), line: self.tok.line }));
                }
            }
            Tok::Ident(n) if n == "async" && !self.tok.escaped => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Keyword("function")) && !next.nl_before {
                    return Ok(Some(ParseError { msg: "function declaration cannot appear in a single-statement context".into(), line: self.tok.line }));
                }
            }
            _ => {}
        }
        Ok(None)
    }

    /// body of if (`is_if`), loops and with: declarations are not allowed (except a plain
    /// sloppy-mode function declaration as an if body, Annex B)
    fn parse_substatement_kind(&mut self, is_if: bool) -> PResult<Stmt> {
        // (a declaration is parsed before it is rejected: syntax errors inside it come first,
        // like the reference engine)
        if let Some(e) = self.check_declaration_in_substatement()? {
            self.parse_statement_list_item()?;
            return Err(e);
        }
        if self.is_kw("function") {
            if !is_if || self.ctx.strict {
                let line = self.tok.line;
                self.parse_function_decl(false)?;
                return self.err_line("function declaration cannot appear in a single-statement context", line);
            }
            let line = self.tok.line;
            let f = self.parse_function_decl(false)?;
            if f.is_generator || f.is_async {
                return self.err_line("function declaration cannot appear in a single-statement context", line);
            }
            return Ok(Stmt::Function(f));
        }
        let saved = self.in_sub_stmt;
        self.in_sub_stmt = true;
        let r = self.parse_statement();
        self.in_sub_stmt = saved;
        r
    }

    fn parse_substatement(&mut self) -> PResult<Stmt> {
        self.parse_substatement_kind(false)
    }

    fn parse_loop_body(&mut self) -> PResult<Stmt> {
        self.loop_depth += 1;
        self.breakable_depth += 1;
        // labels directly preceding this loop already marked is_loop
        let r = self.parse_substatement();
        self.loop_depth -= 1;
        self.breakable_depth -= 1;
        r
    }

    fn parse_expression_statement(&mut self) -> PResult<Stmt> {
        let e = self.parse_expression(false)?;
        self.consume_semicolon()?;
        Ok(Stmt::Expr(e))
    }

    fn parse_block(&mut self) -> PResult<Block> {
        self.expect_punct("{")?;
        let saved = self.in_sub_stmt;
        self.in_sub_stmt = false;
        let saved_using = self.using_ctx;
        self.using_ctx = 0;
        let mut body = Vec::new();
        while !self.is_punct("}") {
            if matches!(self.tok.tok, Tok::Eof) {
                return self.err("expected '}'");
            }
            body.push(self.parse_statement_list_item()?);
        }
        self.in_sub_stmt = saved;
        self.using_ctx = saved_using;
        self.advance()?;
        Ok(Block { body, scope: ScopeId::new() })
    }

    fn parse_var_decl(&mut self, kind: VarKind, no_in: bool) -> PResult<VarDecl> {
        self.advance()?; // var/let/const/using
        if kind == VarKind::AwaitUsing {
            self.advance()?; // 'using' after 'await'
        }
        let mut decls = Vec::new();
        loop {
            let line = self.tok.line;
            let target = if kind == VarKind::Using || kind == VarKind::AwaitUsing {
                Pattern::Ident(self.binding_ident()?)
            } else {
                self.parse_binding_target()?
            };
            if kind == VarKind::Const && !no_in && !self.is_punct("=") {
                return self.err("missing initializer in const declaration");
            }
            let _ = line;
            let init = if self.eat_punct("=")? {
                Some(self.parse_assign(no_in)?)
            } else {
                None
            };
            if kind != VarKind::Var && !no_in {
                Self::check_let_bound(&target)?;
            }
            // (destructuring declarations without initializer are accepted; they fail at
            // runtime like the reference engine)
            decls.push(VarDeclarator { target, init });
            if !self.eat_punct(",")? {
                break;
            }
        }
        Ok(VarDecl { kind, decls })
    }

    /// lexical declarations cannot bind `let`
    fn check_let_bound(target: &Pattern) -> PResult<()> {
        let mut names = Vec::new();
        crate::resolver::pattern_names(target, &mut names);
        if let Some((_, l)) = names.iter().find(|(n, _)| &**n == "let") {
            return Err(ParseError { msg: "'let' is disallowed as a lexically bound name".into(), line: *l });
        }
        Ok(())
    }

    fn check_let_bound_decl(decl: &VarDecl) -> PResult<()> {
        if decl.kind != VarKind::Var {
            for d in &decl.decls {
                Self::check_let_bound(&d.target)?;
            }
        }
        Ok(())
    }

    // binding patterns (declarations / params)
    fn parse_binding_target(&mut self) -> PResult<Pattern> {
        if self.is_punct("[") {
            self.parse_array_binding()
        } else if self.is_punct("{") {
            self.parse_object_binding()
        } else {
            Ok(Pattern::Ident(self.binding_ident()?))
        }
    }

    fn parse_binding_element(&mut self) -> PResult<PatElem> {
        let target = self.parse_binding_target()?;
        let default = if self.eat_punct("=")? { Some(self.parse_assign(false)?) } else { None };
        Ok(PatElem { target, default })
    }

    fn parse_array_binding(&mut self) -> PResult<Pattern> {
        self.expect_punct("[")?;
        let mut elems = Vec::new();
        let mut rest = None;
        loop {
            if self.is_punct("]") {
                break;
            }
            if self.is_punct(",") {
                self.advance()?;
                elems.push(None);
                continue;
            }
            if self.is_punct("...") {
                self.advance()?;
                rest = Some(Box::new(self.parse_binding_target()?));
                break;
            }
            elems.push(Some(self.parse_binding_element()?));
            if !self.is_punct("]") {
                if !self.is_punct(",") {
                    return self.err("expected ']'");
                }
                self.advance()?;
            }
        }
        self.expect_punct("]")?;
        Ok(Pattern::Array { elems, rest })
    }

    fn parse_object_binding(&mut self) -> PResult<Pattern> {
        self.expect_punct("{")?;
        let mut props = Vec::new();
        let mut rest = None;
        while !self.is_punct("}") {
            if self.is_punct("...") {
                self.advance()?;
                rest = Some(Box::new(Pattern::Ident(self.binding_ident()?)));
                break;
            }
            let line = self.tok.line;
            if let Tok::PrivateName(_) = self.tok.tok {
                return self.err("private names are only allowed in class bodies");
            }
            let key_kw = match &self.tok.tok {
                Tok::Keyword(k) => Some(*k),
                _ => None,
            };
            let (key, shorthand_name) = self.parse_property_key()?;
            if let Some(k) = key_kw {
                if !self.is_punct(":") {
                    return self.err(format!("'{}' is a reserved word and cannot be a shorthand property", k));
                }
            }
            if self.eat_punct(":")? {
                let el = self.parse_binding_element()?;
                props.push(ObjPatProp { key, target: el.target, default: el.default });
            } else {
                let name = match shorthand_name {
                    Some(n) => n,
                    None => return self.err("invalid shorthand destructuring target"),
                };
                if name == "await" && (self.ctx.in_async || self.is_module) {
                    return self.err_line("'await' cannot be used as a shorthand property here", line);
                }
                if name == "yield" && self.ctx.in_generator {
                    return self.err_line("'yield' cannot be used as a shorthand property here", line);
                }
                // validate as binding identifier
                if self.ctx.strict && is_reserved_strict(&name) {
                    return self.err_line(format!("'{}' cannot be used as a shorthand property in strict mode", name), line);
                }
                if matches!(name.as_str(), "yield") && (self.ctx.in_generator || self.ctx.strict) {
                    return self.err_line("expected binding identifier", line);
                }
                if name == "await" && (self.ctx.in_async || self.is_module) {
                    return self.err_line("expected binding identifier", line);
                }
                if crate::lexer::keyword_of(&name).is_some() {
                    return self.err_line("expected binding identifier", line);
                }
                // (the reference engine does not check shorthand bindings for eval/arguments)
                let default = if self.eat_punct("=")? { Some(self.parse_assign(false)?) } else { None };
                props.push(ObjPatProp {
                    key,
                    target: Pattern::Ident(Ident { name: Rc::from(name.as_str()), line }),
                    default,
                });
            }
            if !self.is_punct("}") {
                if !self.is_punct(",") {
                    return self.err("expected '}'");
                }
                self.advance()?;
            }
        }
        self.expect_punct("}")?;
        Ok(Pattern::Object { props, rest })
    }

    /// Returns (key, Some(name) if it was a plain identifier usable as shorthand)
    fn parse_property_key(&mut self) -> PResult<(PropKey, Option<String>)> {
        match self.tok.tok.clone() {
            Tok::Ident(n) => {
                self.advance()?;
                Ok((PropKey::Ident(Rc::from(n.as_str())), Some(n)))
            }
            Tok::Keyword(k) => {
                self.advance()?;
                Ok((PropKey::Ident(Rc::from(k)), Some(k.to_string())))
            }
            Tok::Str(s) => {
                if self.ctx.strict && self.tok.octal_escape {
                    return self.err("legacy octal literals are not allowed in strict mode");
                }
                self.advance()?;
                Ok((PropKey::Str(Rc::from(s.as_slice())), None))
            }
            Tok::Num(n) => {
                if self.ctx.strict && self.tok.legacy_octal {
                    return self.err("legacy octal literals are not allowed in strict mode");
                }
                self.advance()?;
                Ok((PropKey::Num(n), None))
            }
            Tok::BigInt(s) => {
                self.advance()?;
                let b = crate::bigint::BigInt::parse(&s.encode_utf16().collect::<Vec<u16>>())
                    .unwrap_or_else(crate::bigint::BigInt::zero);
                let st = b.to_string_radix(10);
                Ok((PropKey::Str(Rc::from(st.encode_utf16().collect::<Vec<u16>>().as_slice())), None))
            }
            Tok::Punct("[") => {
                self.advance()?;
                let e = self.parse_assign(false)?;
                self.expect_punct("]")?;
                Ok((PropKey::Computed(Box::new(e)), None))
            }
            Tok::PrivateName(n) => {
                self.advance()?;
                Ok((PropKey::Private(Rc::from(n.as_str())), None))
            }
            _ => self.err("expected property key"),
        }
    }

    fn parse_for(&mut self) -> PResult<Stmt> {
        self.advance()?; // for
        let mut is_await = false;
        if self.is_ident_named("await") && (self.ctx.in_async || (self.is_module && !self.ctx.in_function)) {
            self.advance()?;
            is_await = true;
            if !self.ctx.in_function {
                self.has_tla = true;
            }
        } else if self.is_ident_named("await") {
            let next = self.peek_token()?;
            if matches!(next.tok, Tok::Punct("(")) {
                return self.err("'for await' is only valid in an async context");
            }
        }
        self.expect_punct("(")?;
        // init
        let mut init: Option<ForInit> = None;
        if self.is_punct(";") {
            // empty init
        } else {
            let is_let_decl = if self.is_ident_named("let") {
                let next = self.peek_token()?;
                matches!(next.tok, Tok::Ident(_) | Tok::PrivateName(_) | Tok::Punct("[") | Tok::Punct("{"))
                    && !(matches!(&next.tok, Tok::Ident(n) if n == "in" || n == "of"))
            } else {
                false
            };
            let is_using = if self.is_ident_named("using") {
                let next = self.peek_token()?;
                matches!(&next.tok, Tok::Ident(n) if n != "of" && n != "in")
            } else {
                false
            };
            let is_await_using = if self.is_ident_named("await") && (self.ctx.in_async || self.is_module) {
                let s = self.save();
                self.advance()?;
                let r = self.is_ident_named("using");
                self.restore(s);
                r
            } else {
                false
            };
            if self.is_kw("var") || self.is_kw("const") || is_let_decl || is_using || is_await_using {
                let kind = if self.is_kw("var") {
                    VarKind::Var
                } else if self.is_kw("const") {
                    VarKind::Const
                } else if is_using {
                    VarKind::Using
                } else if is_await_using {
                    VarKind::AwaitUsing
                } else {
                    VarKind::Let
                };
                let decl = self.parse_var_decl(kind, true)?;
                if (self.is_kw("in") || self.is_ident_named("of")) && decl.decls.len() == 1 {
                    let is_of = self.is_ident_named("of");
                    if is_await && !is_of {
                        return self.err("'for await' is only valid with a for-of head");
                    }
                    let mut decl = decl;
                    let d = decl.decls.pop().unwrap();
                    let mut var_init = None;
                    if let Some(i) = d.init {
                        if is_of || kind != VarKind::Var || self.ctx.strict || !matches!(d.target, Pattern::Ident(_)) {
                            return self.err("expected ';'");
                        }
                        var_init = Some(i);
                    }
                    if kind != VarKind::Var {
                        Self::check_let_bound(&d.target)?;
                    }
                    self.advance()?;
                    let right = if is_of { self.parse_assign(false)? } else { self.parse_expression(false)? };
                    self.expect_punct(")")?;
                    let body = self.parse_loop_body()?;
                    let f = ForInOf {
                        head: ForHead::Decl(kind, d.target),
                        right,
                        body,
                        is_await,
                        scope: ScopeId::new(),
                        var_init,
                    };
                    return Ok(if is_of { Stmt::ForOf(Box::new(f)) } else { Stmt::ForIn(Box::new(f)) });
                }
                // regular for: check const initializers
                if !self.is_punct(";") {
                    return self.err("expected ';'");
                }
                for d in &decl.decls {
                    if d.init.is_none() && kind == VarKind::Const {
                        return self.err("missing initializer in for-loop declaration");
                    }
                }
                Self::check_let_bound_decl(&decl)?;
                init = Some(ForInit::Var(decl));
            } else {
                // expression or assignment target
                let start_tok_is_let = self.is_ident_named("let");
                let start_is_async = self.is_ident_named("async") && !self.tok.escaped;
                let cover_before_head = self.cover_init_count;
                let head_start_pos = self.tok.start;
                let e = self.parse_expression_no_in()?;
                if start_is_async && !is_await && self.is_ident_named("of") && matches!(&e, Expr::Ident(id) if &*id.name == "async") {
                    return self.err("'async' as a for-of left side must be parenthesized");
                }
                if self.is_kw("in") || (self.is_ident_named("of") && !(start_is_async && matches!(e, Expr::Ident(_)))) {
                    let is_of = self.is_ident_named("of");
                    if is_await && !is_of {
                        return self.err("'for await' is only valid with a for-of head");
                    }
                    if is_of && start_tok_is_let && matches!(e, Expr::Ident(_)) {
                        return self.err("expected ';'");
                    }
                    // an invalid target is reported after the whole statement has been parsed
                    let head_line = self.tok.line;
                    let is_pattern = matches!(e, Expr::Array(_) | Expr::Object(_));
                    let trailing = matches!(e, Expr::Array(_)) && self.spread_trailing_comma.contains(&head_start_pos);
                    let mut deferred: Option<ParseError> = None;
                    let target = match self.expr_to_assign_target(e, true) {
                        Ok(Pattern::Ident(id)) if id.name.starts_with('#') => {
                            deferred = Some(ParseError { msg: "invalid for-in/of target".into(), line: head_line });
                            Pattern::Ident(id)
                        }
                        Ok(t) => {
                            if trailing {
                                deferred = Some(ParseError { msg: "invalid for-in/of target".into(), line: head_line });
                            }
                            t
                        }
                        Err(mut err) => {
                            if !err.msg.starts_with("cannot assign to") {
                                err.msg = "invalid for-in/of target".into();
                            }
                            deferred = Some(err);
                            Pattern::Ident(Ident { name: Rc::from("_"), line: head_line })
                        }
                    };
                    if is_pattern {
                        self.cover_init_count = cover_before_head;
                    }
                    self.advance()?;
                    let right = if is_of { self.parse_assign(false)? } else { self.parse_expression(false)? };
                    self.expect_punct(")")?;
                    let body = self.parse_loop_body()?;
                    if let Some(err) = deferred {
                        return Err(err);
                    }
                    let f = ForInOf {
                        head: ForHead::Target(target),
                        right,
                        body,
                        is_await,
                        scope: ScopeId::new(),
                        var_init: None,
                    };
                    return Ok(if is_of { Stmt::ForOf(Box::new(f)) } else { Stmt::ForIn(Box::new(f)) });
                }
                self.check_no_cover_init_since(cover_before_head)?;
                init = Some(ForInit::Expr(e));
            }
        }
        if is_await {
            return self.err("'for await' is only valid with a for-of head");
        }
        self.expect_punct(";")?;
        let test = if self.is_punct(";") { None } else { Some(self.parse_expression(false)?) };
        self.expect_punct(";")?;
        let update = if self.is_punct(")") { None } else { Some(self.parse_expression(false)?) };
        self.expect_punct(")")?;
        let body = self.parse_loop_body()?;
        Ok(Stmt::For(Box::new(ForStmt { init, test, update, body, scope: ScopeId::new() })))
    }

    fn parse_try(&mut self) -> PResult<Stmt> {
        self.advance()?;
        let block = self.parse_block()?;
        let mut param = None;
        let mut handler = None;
        let mut finalizer = None;
        if self.eat_kw("catch")? {
            if self.eat_punct("(")? {
                param = Some(self.parse_binding_target()?);
                self.expect_punct(")")?;
            }
            handler = Some(self.parse_block()?);
        }
        if self.eat_kw("finally")? {
            finalizer = Some(self.parse_block()?);
        }
        if handler.is_none() && finalizer.is_none() {
            return self.err("missing catch or finally after try");
        }
        Ok(Stmt::Try(Box::new(TryStmt { block, param, handler, catch_scope: ScopeId::new(), finalizer })))
    }

    fn parse_switch(&mut self) -> PResult<Stmt> {
        self.advance()?;
        self.expect_punct("(")?;
        let disc = self.parse_expression(false)?;
        self.expect_punct(")")?;
        self.expect_punct("{")?;
        let mut cases = Vec::new();
        let mut has_default = false;
        self.breakable_depth += 1;
        while !self.is_punct("}") {
            let test = if self.eat_kw("case")? {
                Some(self.parse_expression(false)?)
            } else if self.eat_kw("default")? {
                if has_default {
                    self.breakable_depth -= 1;
                    return self.err("more than one default clause in switch statement");
                }
                has_default = true;
                None
            } else {
                self.breakable_depth -= 1;
                return self.err("expected 'case' or 'default'");
            };
            self.expect_punct(":")?;
            let mut body = Vec::new();
            let saved_using = self.using_ctx;
            self.using_ctx = 2;
            while !self.is_punct("}") && !self.is_kw("case") && !self.is_kw("default") {
                if matches!(self.tok.tok, Tok::Eof) {
                    self.breakable_depth -= 1;
                    return self.err("expected '}'");
                }
                body.push(self.parse_statement_list_item()?);
            }
            self.using_ctx = saved_using;
            cases.push(SwitchCase { test, body });
        }
        self.breakable_depth -= 1;
        self.advance()?;
        Ok(Stmt::Switch(Box::new(SwitchStmt { disc, cases, scope: ScopeId::new() })))
    }

    // ---------- modules ----------

    fn parse_module_specifier(&mut self) -> PResult<Rc<str>> {
        match self.tok.tok.clone() {
            Tok::Str(s) => {
                self.advance()?;
                Ok(Rc::from(String::from_utf16_lossy(&s).as_str()))
            }
            _ => self.err("expected module specifier"),
        }
    }

    fn parse_import_attributes(&mut self) -> PResult<Vec<(Rc<str>, Rc<str>)>> {
        let mut attrs = Vec::new();
        if (self.is_kw("with") || (self.is_ident_named("assert") && !self.tok.nl_before)) && true {
            self.advance()?;
            self.expect_punct("{")?;
            while !self.is_punct("}") {
                let key = match self.tok.tok.clone() {
                    Tok::Ident(n) => n,
                    Tok::Keyword(k) => k.to_string(),
                    Tok::Str(s) => String::from_utf16_lossy(&s),
                    _ => return self.err("expected attribute key"),
                };
                self.advance()?;
                self.expect_punct(":")?;
                let val = match self.tok.tok.clone() {
                    Tok::Str(s) => String::from_utf16_lossy(&s),
                    _ => return self.err("expected attribute value string"),
                };
                self.advance()?;
                attrs.push((Rc::from(key.as_str()), Rc::from(val.as_str())));
                if !self.is_punct("}") {
                    self.expect_punct(",")?;
                }
            }
            self.advance()?;
        }
        Ok(attrs)
    }

    fn module_export_name(&mut self) -> PResult<Rc<str>> {
        match self.tok.tok.clone() {
            Tok::Ident(n) => {
                self.advance()?;
                Ok(Rc::from(n.as_str()))
            }
            Tok::Keyword(k) => {
                self.advance()?;
                Ok(Rc::from(k))
            }
            Tok::Str(s) => {
                self.advance()?;
                Ok(Rc::from(String::from_utf16_lossy(&s).as_str()))
            }
            _ => self.err("expected identifier"),
        }
    }

    fn parse_import(&mut self) -> PResult<Stmt> {
        self.advance()?; // import
        let mut decl = ImportDecl {
            specifier: Rc::from(""),
            default: None,
            namespace: None,
            named: Vec::new(),
            phase: ImportPhase::Evaluation,
            attributes: Vec::new(),
        };
        if let Tok::Str(_) = self.tok.tok {
            decl.specifier = self.parse_module_specifier()?;
            decl.attributes = self.parse_import_attributes()?;
            self.consume_semicolon()?;
            return Ok(Stmt::Import(Box::new(decl)));
        }
        // import defer * as ns / import source x
        if self.is_ident_named("defer") {
            let next = self.peek_token()?;
            if matches!(next.tok, Tok::Punct("*")) {
                self.advance()?;
                decl.phase = ImportPhase::Defer;
            }
        } else if self.is_ident_named("source") {
            let next = self.peek_token()?;
            if matches!(next.tok, Tok::Ident(ref n) if n != "from") {
                self.advance()?;
                decl.phase = ImportPhase::Source;
            }
        }
        if self.is_binding_ident() {
            decl.default = Some(self.binding_ident()?);
            if self.eat_punct(",")? {
            } else {
                if !self.is_ident_named("from") {
                    return self.err("expected 'from'");
                }
            }
        }
        if self.is_punct("*") {
            self.advance()?;
            if !self.is_ident_named("as") {
                return self.err("expected 'as'");
            }
            self.advance()?;
            decl.namespace = Some(self.binding_ident()?);
        } else if self.is_punct("{") {
            self.advance()?;
            while !self.is_punct("}") {
                let line = self.tok.line;
                let is_str = matches!(self.tok.tok, Tok::Str(_));
                let imported = self.module_export_name()?;
                let local = if self.is_ident_named("as") {
                    self.advance()?;
                    self.binding_ident()?
                } else {
                    if is_str || crate::lexer::keyword_of(&imported).is_some() {
                        return self.err("expected 'as'");
                    }
                    self.check_binding_name(&imported, line)?;
                    Ident { name: imported.clone(), line }
                };
                decl.named.push((imported, local));
                if !self.is_punct("}") {
                    self.expect_punct(",")?;
                }
            }
            self.advance()?;
        }
        if !self.is_ident_named("from") {
            return self.err("expected 'from'");
        }
        self.advance()?;
        decl.specifier = self.parse_module_specifier()?;
        decl.attributes = self.parse_import_attributes()?;
        self.consume_semicolon()?;
        Ok(Stmt::Import(Box::new(decl)))
    }

    fn parse_export(&mut self, decorators: Vec<Expr>) -> PResult<Stmt> {
        self.advance()?; // export
        if self.is_punct("@") {
            let decs = self.parse_decorators()?;
            let mut c = self.parse_class(true)?;
            if let Some(cm) = Rc::get_mut(&mut c) {
                cm.decorators = decs;
            }
            return Ok(Stmt::Export(Box::new(ExportDecl::Decl(Stmt::Class(c)))));
        }
        if self.eat_kw("default")? {
            if self.is_punct("@") {
                let decs = self.parse_decorators()?;
                let mut c = self.parse_class(false)?;
                if let Some(cm) = Rc::get_mut(&mut c) {
                    cm.decorators = decs;
                }
                return Ok(Stmt::Export(Box::new(ExportDecl::DefaultClass(c))));
            }
            if self.is_kw("function") {
                let f = self.parse_function_decl_opt_name(false)?;
                return Ok(Stmt::Export(Box::new(ExportDecl::DefaultFunc(f))));
            }
            if self.is_ident_named("async") {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Keyword("function")) && !next.nl_before {
                    let f = self.parse_function_decl_opt_name(true)?;
                    return Ok(Stmt::Export(Box::new(ExportDecl::DefaultFunc(f))));
                }
            }
            if self.is_kw("class") {
                let mut c = self.parse_class(false)?;
                if !decorators.is_empty() {
                    if let Some(cm) = Rc::get_mut(&mut c) {
                        cm.decorators = decorators;
                    }
                }
                return Ok(Stmt::Export(Box::new(ExportDecl::DefaultClass(c))));
            }
            let before = self.cover_init_count;
            let e = self.parse_assign(false)?;
            self.check_no_cover_init_since(before)?;
            self.consume_semicolon()?;
            return Ok(Stmt::Export(Box::new(ExportDecl::DefaultExpr(e))));
        }
        if self.is_punct("*") {
            self.advance()?;
            if self.is_ident_named("as") {
                self.advance()?;
                let name = self.module_export_name()?;
                if !self.is_ident_named("from") {
                    return self.err("expected 'from'");
                }
                self.advance()?;
                let specifier = self.parse_module_specifier()?;
                self.parse_import_attributes()?;
                self.consume_semicolon()?;
                return Ok(Stmt::Export(Box::new(ExportDecl::AllAs { specifier, name })));
            }
            if !self.is_ident_named("from") {
                return self.err("expected 'from'");
            }
            self.advance()?;
            let specifier = self.parse_module_specifier()?;
            self.parse_import_attributes()?;
            self.consume_semicolon()?;
            return Ok(Stmt::Export(Box::new(ExportDecl::All { specifier })));
        }
        if self.is_punct("{") {
            self.advance()?;
            let mut names = Vec::new();
            let mut has_str_local = false;
            while !self.is_punct("}") {
                if matches!(self.tok.tok, Tok::Str(_)) {
                    has_str_local = true;
                }
                let local = self.module_export_name()?;
                let exported = if self.is_ident_named("as") {
                    self.advance()?;
                    self.module_export_name()?
                } else {
                    local.clone()
                };
                names.push((local, exported));
                if !self.is_punct("}") {
                    self.expect_punct(",")?;
                }
            }
            self.advance()?;
            if self.is_ident_named("from") {
                self.advance()?;
                let specifier = self.parse_module_specifier()?;
                self.parse_import_attributes()?;
                self.consume_semicolon()?;
                return Ok(Stmt::Export(Box::new(ExportDecl::From { specifier, names })));
            }
            if has_str_local {
                return self.err("expected 'from'");
            }
            self.consume_semicolon()?;
            return Ok(Stmt::Export(Box::new(ExportDecl::Named(names))));
        }
        // declarations
        let st = match &self.tok.tok {
            Tok::Keyword("var") => {
                let d = self.parse_var_decl(VarKind::Var, false)?;
                self.consume_semicolon()?;
                Stmt::Var(d)
            }
            Tok::Keyword("const") => {
                let d = self.parse_var_decl(VarKind::Const, false)?;
                self.consume_semicolon()?;
                Stmt::Var(d)
            }
            Tok::Ident(n) if n == "let" => {
                let d = self.parse_var_decl(VarKind::Let, false)?;
                self.consume_semicolon()?;
                Stmt::Var(d)
            }
            Tok::Keyword("function") => Stmt::Function(self.parse_function_decl(false)?),
            Tok::Ident(n) if n == "async" => Stmt::Function(self.parse_function_decl(true)?),
            Tok::Keyword("class") => {
                let mut c = self.parse_class(true)?;
                if !decorators.is_empty() {
                    if let Some(cm) = Rc::get_mut(&mut c) {
                        cm.decorators = decorators;
                    }
                }
                Stmt::Class(c)
            }
            _ => return self.unexpected(),
        };
        Ok(Stmt::Export(Box::new(ExportDecl::Decl(st))))
    }

    // ---------- functions ----------

    /// binding identifier of a function declaration (messages mention function names)
    fn function_name_ident(&mut self, is_expr: bool) -> PResult<Ident> {
        if let Tok::Ident(n) = &self.tok.tok {
            if !self.tok.escaped {
                let n = n.clone();
                if is_expr && ((n == "yield" && self.ctx.in_generator) || (n == "await" && self.ctx.in_async)) {
                    return self.err(format!("'{}' cannot name this function expression", n));
                }
                if !is_expr && n == "yield" && (self.ctx.in_generator || self.ctx.strict) {
                    return self.err("'yield' cannot be used as a function name here");
                }
                if self.ctx.strict && (n == "eval" || n == "arguments" || is_reserved_strict(&n)) {
                    return self.err(format!("'{}' can't be a function name in strict mode", n));
                }
            }
        }
        match self.binding_ident() {
            Ok(id) => Ok(id),
            Err(mut e) => {
                if e.msg.ends_with("cannot be used as a binding here") {
                    e.msg = e.msg.replace("cannot be used as a binding here", "cannot be used as a function name here");
                } else if e.msg == "'eval' cannot be used as a binding in strict mode" || e.msg == "'arguments' cannot be used as a binding in strict mode" {
                    e.msg = e.msg.replace("cannot be used as a binding in strict mode", "can't be a function name in strict mode");
                }
                Err(e)
            }
        }
    }

    fn parse_function_decl(&mut self, is_async: bool) -> PResult<Rc<Function>> {
        let start = self.tok.start;
        let line = self.tok.line;
        if is_async {
            self.advance()?;
        }
        self.advance()?; // function
        let is_gen = self.eat_punct("*")?;
        // name: in generator/async context the name rules follow the enclosing context
        let name = if self.is_punct("(") {
            // anonymous function declaration (accepted leniently)
            None
        } else if !matches!(self.tok.tok, Tok::Ident(_) | Tok::PrivateName(_)) {
            return self.err("expected '('");
        } else {
            let saved = self.ctx;
            let id = self.function_name_ident(false)?;
            self.ctx = saved;
            Some(id)
        };
        let f = self.parse_function_rest(name, start, line, FuncKind::Normal, is_async, is_gen, false, true)?;
        Ok(f)
    }

    fn parse_function_decl_opt_name(&mut self, is_async: bool) -> PResult<Rc<Function>> {
        self.parse_function_decl(is_async)
    }

    fn parse_function_expr(&mut self, is_async: bool, start: usize) -> PResult<Rc<Function>> {
        let line = self.tok.line;
        self.advance()?; // function
        let is_gen = self.eat_punct("*")?;
        let name = if self.is_punct("(") {
            None
        } else if !matches!(self.tok.tok, Tok::Ident(_) | Tok::PrivateName(_)) {
            return self.err("expected '('");
        } else {
            // name binding is checked in the function's own context
            let saved = self.ctx;
            self.ctx.in_generator = is_gen;
            self.ctx.in_async = is_async;
            let r = self.function_name_ident(true);
            self.ctx = saved;
            Some(r?)
        };
        self.parse_function_rest(name, start, line, FuncKind::Normal, is_async, is_gen, true, false)
    }

    #[allow(clippy::too_many_arguments)]
    fn parse_function_rest(
        &mut self,
        name: Option<Ident>,
        start: usize,
        line: u32,
        kind: FuncKind,
        is_async: bool,
        is_gen: bool,
        is_expr: bool,
        is_decl: bool,
    ) -> PResult<Rc<Function>> {
        let saved_ctx = self.ctx;
        let saved_labels = std::mem::take(&mut self.labels);
        let saved_break = self.breakable_depth;
        let saved_loop = self.loop_depth;
        self.breakable_depth = 0;
        self.loop_depth = 0;
        self.ctx.in_function = true;
        self.ctx.in_generator = is_gen;
        self.ctx.in_async = is_async;
        self.ctx.allow_return = true;
        self.ctx.allow_new_target = true;
        self.ctx.in_field_init = false;
        self.ctx.in_static_block = false;
        match kind {
            FuncKind::Normal => {
                self.ctx.allow_super_call = false;
                self.ctx.allow_super_prop = false;
            }
            FuncKind::Method | FuncKind::Getter | FuncKind::Setter | FuncKind::ClassConstructor => {
                self.ctx.allow_super_prop = true;
                self.ctx.allow_super_call = false;
            }
            FuncKind::DerivedConstructor => {
                self.ctx.allow_super_prop = true;
                self.ctx.allow_super_call = true;
            }
            _ => {}
        }
        let res = (|| -> PResult<Rc<Function>> {
            self.ctx.in_params = true;
            let params = self.parse_formal_params()?;
            self.ctx.in_params = false;
            self.expect_punct("{")?;
            let was_strict = self.ctx.strict;
            let (body, strict) = self.parse_directives_and_body(false, self.ctx.strict)?;
            let end = self.tok.end;
            self.expect_punct("}")?;
            if kind == FuncKind::Getter && !params.is_empty() {
                return self.err_line("getter functions must have no arguments", line);
            }
            if kind == FuncKind::Setter && (params.len() != 1 || params[0].rest) {
                return self.err_line("setter functions must have exactly one argument", line);
            }
            let simple = params.iter().all(|p| matches!(p.pat, Pattern::Ident(_)) && p.default.is_none() && !p.rest);
            if strict && !was_strict && !simple {
                return self.err_line("illegal 'use strict' directive in a function with a non-simple parameter list", line);
            }
            self.validate_params_kind(&params, strict, simple || kind == FuncKind::Arrow, kind == FuncKind::Arrow || matches!(kind, FuncKind::Method | FuncKind::Getter | FuncKind::Setter | FuncKind::ClassConstructor | FuncKind::DerivedConstructor), line, kind == FuncKind::Normal)?;
            if strict {
                if let Some(n) = &name {
                    if &*n.name == "eval" || &*n.name == "arguments" || (!was_strict && is_reserved_strict(&n.name)) {
                        return self.err_line(format!("'{}' can't be a function name in strict mode", n.name), n.line);
                    }
                }
            }
            Ok(Rc::new(Function {
                name: name.clone(),
                params,
                body,
                expr_body: false,
                kind,
                is_async,
                is_generator: is_gen,
                strict,
                simple_params: simple,
                src_start: start,
                src_end: end,
                scope: ScopeId::new(),
                body_scope: ScopeId::new(),
                is_expr,
                is_decl,
                line,
                has_use_strict_directive: strict && !was_strict,
            }))
        })();
        self.ctx = saved_ctx;
        self.labels = saved_labels;
        self.breakable_depth = saved_break;
        self.loop_depth = saved_loop;
        res
    }

    fn validate_params(&self, params: &[Param], strict: bool, simple: bool, no_dups: bool, line: u32) -> PResult<()> {
        self.validate_params_kind(params, strict, simple, no_dups, line, false)
    }

    /// `plain_fn`: a function declaration/expression (its parameter names are all checked, with
    /// the reference engine's "parameter name" message); otherwise shorthand object pattern
    /// bindings are not checked for eval/arguments.
    fn validate_params_kind(&self, params: &[Param], strict: bool, _simple: bool, no_dups: bool, line: u32, plain_fn: bool) -> PResult<()> {
        let mut names: Vec<Rc<str>> = Vec::new();
        fn collect(p: &Pattern, out: &mut Vec<(Rc<str>, u32, bool)>, shorthand: bool) {
            match p {
                Pattern::Ident(id) => out.push((id.name.clone(), id.line, shorthand)),
                Pattern::Array { elems, rest } => {
                    for e in elems.iter().flatten() {
                        collect(&e.target, out, false);
                    }
                    if let Some(r) = rest {
                        collect(r, out, false);
                    }
                }
                Pattern::Object { props, rest } => {
                    for pr in props {
                        let sh = matches!((&pr.key, &pr.target), (PropKey::Ident(k), Pattern::Ident(t)) if *k == t.name);
                        collect(&pr.target, out, sh);
                    }
                    if let Some(r) = rest {
                        collect(r, out, false);
                    }
                }
                Pattern::Expr(_) => {}
            }
        }
        let mut all = Vec::new();
        for p in params {
            collect(&p.pat, &mut all, false);
        }
        let simple = params.iter().all(|p| matches!(p.pat, Pattern::Ident(_)) && p.default.is_none() && !p.rest);
        for (n, l, sh) in &all {
            let restricted = &**n == "eval" || &**n == "arguments";
            if strict && plain_fn && (restricted || is_reserved_strict(n)) {
                return self.err_line(format!("'{}' can't be a parameter name in strict mode", n), *l);
            }
            if strict && ((restricted && !*sh) || is_reserved_strict(n)) {
                return self.err_line(format!("'{}' cannot be used as a binding in strict mode", n), *l);
            }
            if names.contains(n) && (strict || !simple || no_dups) {
                return self.err_line(format!("duplicate parameter name '{}'", n), line);
            }
            names.push(n.clone());
        }
        Ok(())
    }

    fn parse_formal_params(&mut self) -> PResult<Vec<Param>> {
        self.expect_punct("(")?;
        let mut params = Vec::new();
        while !self.is_punct(")") {
            if self.is_punct("...") {
                self.advance()?;
                let pat = self.parse_binding_target()?;
                params.push(Param { pat, default: None, rest: true });
                if !self.is_punct(")") {
                    return self.err("expected ')'");
                }
                break;
            }
            let el = self.parse_binding_element()?;
            params.push(Param { pat: el.target, default: el.default, rest: false });
            if !self.is_punct(")") {
                if !self.eat_punct(",")? {
                    return self.err("expected ')'");
                }
            }
        }
        self.expect_punct(")")?;
        Ok(params)
    }

    /// Try to parse an arrow function starting at the current token (which is '(' or an identifier).
    fn try_parse_arrow(&mut self, is_async: bool, start: usize) -> PResult<Option<Expr>> {
        let line = self.tok.line;
        let saved = self.save();
        let saved_ctx = self.ctx;
        // parameters are parsed in the arrow's own async context
        if is_async {
            self.ctx.in_async = true;
        }
        let params_res: PResult<Vec<Param>> = if self.is_punct("(") {
            self.parse_formal_params()
        } else {
            match self.binding_ident() {
                Ok(id) => Ok(vec![Param { pat: Pattern::Ident(id), default: None, rest: false }]),
                Err(e) => Err(e),
            }
        };
        self.ctx = saved_ctx;
        let params = match params_res {
            Ok(p) if self.is_punct("=>") && !self.tok.nl_before => p,
            Ok(_) => {
                // (a line terminator before '=>' makes this an ordinary expression)
                self.restore(saved);
                return Ok(None);
            }
            Err(e) => {
                // a parenthesized head followed by '=>' is an arrow: report the parameter error
                self.restore(saved);
                if self.is_punct("(") && self.paren_head_followed_by_arrow()? {
                    return Err(e);
                }
                return Ok(None);
            }
        };
        // check await in async arrow params
        if is_async {
            fn has_await(p: &Pattern) -> bool {
                match p {
                    Pattern::Ident(id) => &*id.name == "await",
                    Pattern::Array { elems, rest } => {
                        elems.iter().flatten().any(|e| has_await(&e.target)) || rest.as_ref().map_or(false, |r| has_await(r))
                    }
                    Pattern::Object { props, rest } => {
                        props.iter().any(|e| has_await(&e.target)) || rest.as_ref().map_or(false, |r| has_await(r))
                    }
                    _ => false,
                }
            }
            if params.iter().any(|p| has_await(&p.pat)) {
                return self.err("'await' is not a valid identifier here");
            }
        }
        self.advance()?; // =>
        let f = self.parse_arrow_body(params, is_async, start, line)?;
        Ok(Some(Expr::Arrow(f)))
    }

    /// at '(': does the balanced parenthesized group end with ") =>" on the same line?
    fn paren_head_followed_by_arrow(&mut self) -> PResult<bool> {
        let saved = self.save();
        let mut depth = 0i32;
        let r = (|| -> PResult<bool> {
            loop {
                match &self.tok.tok {
                    Tok::Eof => return Ok(false),
                    Tok::Punct("(") | Tok::Punct("[") | Tok::Punct("{") => depth += 1,
                    Tok::Punct(")") | Tok::Punct("]") | Tok::Punct("}") => {
                        depth -= 1;
                        if depth == 0 {
                            self.advance()?;
                            return Ok(self.is_punct("=>") && !self.tok.nl_before);
                        }
                    }
                    _ => {}
                }
                self.advance()?;
            }
        })();
        self.restore(saved);
        Ok(r.unwrap_or(false))
    }

    fn parse_arrow_body(&mut self, params: Vec<Param>, is_async: bool, start: usize, line: u32) -> PResult<Rc<Function>> {
        let saved_ctx = self.ctx;
        let saved_labels = std::mem::take(&mut self.labels);
        let saved_break = self.breakable_depth;
        let saved_loop = self.loop_depth;
        self.breakable_depth = 0;
        self.loop_depth = 0;
        self.ctx.in_function = true;
        self.ctx.in_async = is_async;
        self.ctx.in_generator = false;
        self.ctx.allow_return = true;
        let res = (|| -> PResult<Rc<Function>> {
            let simple = params.iter().all(|p| matches!(p.pat, Pattern::Ident(_)) && p.default.is_none() && !p.rest);
            if self.is_punct("{") {
                self.advance()?;
                let was_strict = self.ctx.strict;
                let (body, strict) = self.parse_directives_and_body(false, self.ctx.strict)?;
                let end = self.tok.end;
                self.expect_punct("}")?;
                if strict && !was_strict && !simple {
                    return self.err_line("illegal 'use strict' directive in a function with a non-simple parameter list", line);
                }
                self.validate_params(&params, strict, simple, true, line)?;
                Ok(Rc::new(Function {
                    name: None,
                    params,
                    body,
                    expr_body: false,
                    kind: FuncKind::Arrow,
                    is_async,
                    is_generator: false,
                    strict,
                    simple_params: simple,
                    src_start: start,
                    src_end: end,
                    scope: ScopeId::new(),
                    body_scope: ScopeId::new(),
                    is_expr: true,
                    is_decl: false,
                    line,
                    has_use_strict_directive: strict && !was_strict,
                }))
            } else {
                let no_in = false;
                let e = self.parse_assign(no_in)?;
                let end = self.prev_end;
                self.validate_params(&params, self.ctx.strict, simple, true, line)?;
                Ok(Rc::new(Function {
                    name: None,
                    params,
                    body: vec![Stmt::Return(Some(e))],
                    expr_body: true,
                    kind: FuncKind::Arrow,
                    is_async,
                    is_generator: false,
                    strict: self.ctx.strict,
                    simple_params: simple,
                    src_start: start,
                    src_end: end,
                    scope: ScopeId::new(),
                    body_scope: ScopeId::new(),
                    is_expr: true,
                    is_decl: false,
                    line,
                    has_use_strict_directive: false,
                }))
            }
        })();
        self.ctx = saved_ctx;
        self.labels = saved_labels;
        self.breakable_depth = saved_break;
        self.loop_depth = saved_loop;
        res
    }

    fn parse_method(&mut self, kind: FuncKind, is_async: bool, is_gen: bool, start: usize, line: u32) -> PResult<Rc<Function>> {
        self.parse_function_rest(None, start, line, kind, is_async, is_gen, true, false)
    }

    // ---------- classes ----------

    fn parse_decorators(&mut self) -> PResult<Vec<Expr>> {
        let mut decs = Vec::new();
        while self.is_punct("@") {
            self.advance()?;
            let e = if self.is_punct("(") {
                self.advance()?;
                let e = self.parse_expression(false)?;
                self.expect_punct(")")?;
                e
            } else {
                // (any identifier name, including reserved words, like the reference engine)
                let mut e = match &self.tok.tok {
                    Tok::Ident(_) => Expr::Ident(self.ident_ref()?),
                    Tok::Keyword(k) => {
                        let id = Ident { name: Rc::from(*k), line: self.tok.line };
                        self.advance()?;
                        Expr::Ident(id)
                    }
                    _ => return self.err("expected a decorator expression after '@'"),
                };
                while self.is_punct(".") {
                    self.advance()?;
                    let n = match self.ident_name_of_tok() {
                        Some(n) => n,
                        None => return self.err("expected property name"),
                    };
                    self.advance()?;
                    e = Expr::Member { obj: Box::new(e), prop: MemberProp::Name(Rc::from(n.as_str())), optional: false };
                }
                if self.is_punct("(") {
                    let args = self.parse_arguments()?;
                    e = Expr::Call { callee: Box::new(e), args, optional: false };
                }
                e
            };
            decs.push(e);
        }
        Ok(decs)
    }

    fn parse_class(&mut self, require_name: bool) -> PResult<Rc<Class>> {
        let start = self.tok.start;
        if self.is_kw("class") {
            self.advance()?;
        }
        let saved_strict = self.ctx.strict;
        self.ctx.strict = true;
        if let Tok::Ident(n) = &self.tok.tok {
            if !self.tok.escaped && (is_reserved_strict(n) || n == "yield" || n == "let" || n == "static") {
                let msg = format!("'{}' cannot be used as a class name", n);
                self.ctx.strict = saved_strict;
                return self.err(msg);
            }
        }
        let name = if self.is_binding_ident() && !self.is_ident_named("extends") {
            Some(self.binding_ident()?)
        } else if self.is_kw("extends") || self.is_punct("{") {
            let _ = require_name;
            None
        } else {
            self.ctx.strict = saved_strict;
            if !matches!(self.tok.tok, Tok::Ident(_)) {
                return self.err("expected '{'");
            }
            return self.err("expected binding identifier");
        };
        let extends = if self.eat_kw("extends")? {
            Some(Box::new(self.parse_lhs_expression()?))
        } else {
            None
        };
        let r = self.parse_class_body(name, extends, start);
        self.ctx.strict = saved_strict;
        r
    }

    fn parse_class_body(&mut self, name: Option<Ident>, extends: Option<P<Expr>>, start: usize) -> PResult<Rc<Class>> {
        self.expect_punct("{")?;
        let derived = extends.is_some();
        let mut members = Vec::new();
        let mut constructor: Option<Rc<Function>> = None;
        self.private_scopes.push(Vec::new());
        self.private_refs.push(Vec::new());
        let mut declared_private: Vec<(Rc<str>, &'static str, bool)> = Vec::new();
        while !self.is_punct("}") {
            if self.eat_punct(";")? {
                continue;
            }
            if matches!(self.tok.tok, Tok::Eof) {
                return self.err("expected '}'");
            }
            let decorators = if self.is_punct("@") { self.parse_decorators()? } else { Vec::new() };
            let mut mstart = self.tok.start;
            let line = self.tok.line;
            let mut is_static = false;
            let mut is_async = false;
            let mut is_gen = false;
            let mut kind = MethodKind::Method;
            let mut is_accessor = false;
            // 'static'
            if self.is_ident_named("static") {
                let next = self.peek_token()?;
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct("=") | Tok::Punct(";") | Tok::Punct("}"))
                    && !(next.nl_before && false)
                {
                    self.advance()?;
                    is_static = true;
                    if self.is_punct("{") {
                        // static block
                        let f = self.parse_static_block(mstart, line)?;
                        members.push(ClassMember::StaticBlock(f));
                        continue;
                    }
                    // the source text of a static method excludes `static`
                    mstart = self.tok.start;
                }
            }
            if self.is_ident_named("async") {
                let next = self.peek_token()?;
                // (unlike object literals, the reference engine accepts a line break after
                // `async` in class bodies)
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct("=") | Tok::Punct(";") | Tok::Punct("}")) {
                    self.advance()?;
                    is_async = true;
                }
            }
            if self.is_punct("*") {
                self.advance()?;
                is_gen = true;
            }
            if !is_async && !is_gen && (self.is_ident_named("get") || self.is_ident_named("set")) {
                let next = self.peek_token()?;
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct("=") | Tok::Punct(";") | Tok::Punct("}") | Tok::Punct("*")) {
                    kind = if self.is_ident_named("get") { MethodKind::Getter } else { MethodKind::Setter };
                    self.advance()?;
                }
            }
            if !is_async && !is_gen && kind == MethodKind::Method && self.is_ident_named("accessor") {
                let next = self.peek_token()?;
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct("=") | Tok::Punct(";") | Tok::Punct("}")) && !next.nl_before {
                    self.advance()?;
                    is_accessor = true;
                }
            }
            let key_line = self.tok.line;
            let (key, _) = self.parse_property_key()?;
            let is_ctor_key = !is_static && matches!(&key, PropKey::Ident(n) if &**n == "constructor")
                || !is_static && matches!(&key, PropKey::Str(s) if String::from_utf16_lossy(s) == "constructor");
            if let PropKey::Private(n) = &key {
                if &**n == "constructor" {
                    return self.err_line("'#constructor' is a reserved private name", key_line);
                }
                let kstr: &'static str = match kind {
                    MethodKind::Getter => "get",
                    MethodKind::Setter => "set",
                    _ => "other",
                };
                // duplicates allowed only for getter+setter pair with same staticness
                for (dn, dk, ds) in &declared_private {
                    if dn == n {
                        let ok = (*dk == "get" && kstr == "set" || *dk == "set" && kstr == "get") && *ds == is_static;
                        if !ok {
                            return self.err_line(format!("duplicate private name '#{}'", n), key_line);
                        }
                    }
                }
                declared_private.push((n.clone(), kstr, is_static));
                self.private_scopes.last_mut().unwrap().push(n.clone());
            }
            if self.is_punct("(") {
                // method
                if is_ctor_key {
                    if kind != MethodKind::Method || is_gen || is_async {
                        return self.err_line("class constructor can't be a generator, async, or accessor", line);
                    }
                    if constructor.is_some() {
                        return self.err_line("a class may only have one constructor", line);
                    }
                    let fk = if derived { FuncKind::DerivedConstructor } else { FuncKind::ClassConstructor };
                    let f = self.parse_method(fk, false, false, mstart, line)?;
                    constructor = Some(f);
                    continue;
                }
                if is_static && is_prototype_key(&key) {
                    return self.err_line("classes may not have a static method named 'prototype'", line);
                }
                let fk = match kind {
                    MethodKind::Getter => FuncKind::Getter,
                    MethodKind::Setter => FuncKind::Setter,
                    MethodKind::Method => FuncKind::Method,
                };
                let f = self.parse_method(fk, is_async, is_gen, mstart, line)?;
                members.push(ClassMember::Method { key, func: f, kind, is_static, decorators });
            } else {
                // field
                if is_ctor_key || matches!(&key, PropKey::Ident(n) if &**n == "constructor") {
                    return self.err_line("classes may not have a field named 'constructor'", line);
                }
                if is_static && is_prototype_key(&key) {
                    return self.err_line("classes may not have a static field named 'prototype'", line);
                }
                // (`get x;`, `*x = 1`, `async x`: the reference engine ignores the modifiers
                // and defines a field)
                let value = if self.eat_punct("=")? {
                    let vstart = self.tok.start;
                    let f = self.parse_field_initializer(vstart, line)?;
                    Some(f)
                } else {
                    None
                };
                self.consume_semicolon()?;
                members.push(ClassMember::Field { key, value, is_static, is_accessor, decorators });
            }
        }
        let end = self.tok.end;
        self.advance()?; // }
        // resolve private references
        let declared = self.private_scopes.pop().unwrap();
        let refs = self.private_refs.pop().unwrap();
        for (r, pos) in refs {
            if !declared.contains(&r) {
                if let Some(outer) = self.private_refs.last_mut() {
                    outer.push((r, pos));
                } else {
                    self.undeclared_private.push((pos, format!("Private name '#{}' is not declared in an enclosing class", r)));
                }
            }
        }
        Ok(Rc::new(Class {
            name,
            extends,
            members,
            constructor,
            src_start: start,
            src_end: end,
            scope: ScopeId::new(),
            decorators: Vec::new(),
        }))
    }

    fn parse_field_initializer(&mut self, start: usize, line: u32) -> PResult<Rc<Function>> {
        let saved_ctx = self.ctx;
        self.ctx.in_function = true;
        self.ctx.in_generator = false;
        self.ctx.in_async = false;
        self.ctx.allow_super_prop = true;
        self.ctx.allow_super_call = false;
        self.ctx.allow_new_target = true;
        self.ctx.in_field_init = true;
        self.ctx.allow_return = false;
        let r = self.parse_assign(false);
        self.ctx = saved_ctx;
        let e = r?;
        let end = self.prev_end;
        Ok(Rc::new(Function {
            name: None,
            params: Vec::new(),
            body: vec![Stmt::Return(Some(e))],
            expr_body: true,
            kind: FuncKind::ClassFieldInit,
            is_async: false,
            is_generator: false,
            strict: true,
            simple_params: true,
            src_start: start,
            src_end: end,
            scope: ScopeId::new(),
            body_scope: ScopeId::new(),
            is_expr: true,
            is_decl: false,
            line,
            has_use_strict_directive: false,
        }))
    }

    fn parse_static_block(&mut self, start: usize, line: u32) -> PResult<Rc<Function>> {
        let saved_ctx = self.ctx;
        let saved_labels = std::mem::take(&mut self.labels);
        let saved_break = self.breakable_depth;
        let saved_loop = self.loop_depth;
        self.breakable_depth = 0;
        self.loop_depth = 0;
        self.ctx.in_function = true;
        self.ctx.in_generator = false;
        self.ctx.in_async = false;
        self.ctx.allow_super_prop = true;
        self.ctx.allow_super_call = false;
        self.ctx.allow_new_target = true;
        self.ctx.allow_return = false;
        self.ctx.in_static_block = true;
        let r = self.parse_block();
        self.ctx = saved_ctx;
        self.labels = saved_labels;
        self.breakable_depth = saved_break;
        self.loop_depth = saved_loop;
        let b = r?;
        let end = self.prev_end;
        Ok(Rc::new(Function {
            name: None,
            params: Vec::new(),
            body: b.body,
            expr_body: false,
            kind: FuncKind::StaticBlock,
            is_async: false,
            is_generator: false,
            strict: true,
            simple_params: true,
            src_start: start,
            src_end: end,
            scope: ScopeId::new(),
            body_scope: ScopeId::new(),
            is_expr: false,
            is_decl: false,
            line,
            has_use_strict_directive: false,
        }))
    }

    // ---------- expressions ----------

    pub fn parse_expression(&mut self, no_in: bool) -> PResult<Expr> {
        let before = self.cover_init_count;
        let e = self.parse_expression_unchecked(no_in)?;
        self.check_no_cover_init_since(before)?;
        Ok(e)
    }

    /// expression whose cover-initialized names (`{a = 1}`) are left to the enclosing
    /// expression (parenthesized expressions)
    fn parse_expression_unchecked(&mut self, no_in: bool) -> PResult<Expr> {
        let e = self.parse_assign(no_in)?;
        if self.is_punct(",") {
            let mut v = vec![e];
            while self.eat_punct(",")? {
                v.push(self.parse_assign(no_in)?);
            }
            return Ok(Expr::Seq(v));
        }
        Ok(e)
    }

    fn parse_expression_no_in(&mut self) -> PResult<Expr> {
        let e = self.parse_assign(true)?;
        if self.is_punct(",") {
            let mut v = vec![e];
            while self.eat_punct(",")? {
                v.push(self.parse_assign(true)?);
            }
            return Ok(Expr::Seq(v));
        }
        Ok(e)
    }

    /// cover-initialized names seen since the count was `before` are errors (reported
    /// after parsing)
    fn check_no_cover_init_since(&mut self, before: usize) -> PResult<()> {
        if self.cover_init_count > before {
            self.cover_error = true;
            self.cover_init_count = before;
        }
        Ok(())
    }

    fn is_assign_op(&self) -> Option<AssignOp> {
        if let Tok::Punct(p) = &self.tok.tok {
            Some(match *p {
                "=" => AssignOp::Assign,
                "+=" => AssignOp::Bin(BinOp::Add),
                "-=" => AssignOp::Bin(BinOp::Sub),
                "*=" => AssignOp::Bin(BinOp::Mul),
                "/=" => AssignOp::Bin(BinOp::Div),
                "%=" => AssignOp::Bin(BinOp::Mod),
                "**=" => AssignOp::Bin(BinOp::Exp),
                "<<=" => AssignOp::Bin(BinOp::Shl),
                ">>=" => AssignOp::Bin(BinOp::Shr),
                ">>>=" => AssignOp::Bin(BinOp::UShr),
                "&=" => AssignOp::Bin(BinOp::BitAnd),
                "|=" => AssignOp::Bin(BinOp::BitOr),
                "^=" => AssignOp::Bin(BinOp::BitXor),
                "&&=" => AssignOp::Logical(LogicalOp::And),
                "||=" => AssignOp::Logical(LogicalOp::Or),
                "??=" => AssignOp::Logical(LogicalOp::Nullish),
                _ => return None,
            })
        } else {
            None
        }
    }

    pub fn parse_assign(&mut self, no_in: bool) -> PResult<Expr> {
        let start = self.tok.start;
        // arrow functions
        if self.is_punct("(") {
            if let Some(a) = self.try_parse_arrow(false, start)? {
                return self.finish_arrow_tail(a);
            }
        } else if let Tok::Ident(n) = &self.tok.tok {
            let n = n.clone();
            if n == "async" && !self.tok.escaped {
                let next = self.peek_token()?;
                if !next.nl_before {
                    if matches!(next.tok, Tok::Ident(_)) || matches!(next.tok, Tok::Punct("(")) {
                        let s = self.save();
                        self.advance()?; // async
                        if let Some(a) = self.try_parse_arrow(true, start)? {
                            return self.finish_arrow_tail(a);
                        }
                        self.restore(s);
                    }
                }
            }
            if n == "yield" && self.ctx.in_generator && !self.tok.escaped {
                return self.parse_yield();
            }
            let strict_restricted = self.ctx.strict && (n == "eval" || n == "arguments");
            if self.is_binding_ident() || (n == "yield" || n == "await") || strict_restricted {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct("=>")) {
                    if strict_restricted {
                        return self.err(format!("'{}' cannot be used as a binding in strict mode", n));
                    }
                    if let Some(a) = self.try_parse_arrow(false, start)? {
                        return self.finish_arrow_tail(a);
                    }
                    if n == "await" && (self.ctx.in_async || self.is_module) {
                        return self.err("'await' cannot be used as a binding here");
                    }
                    if n == "await" || n == "yield" {
                        return self.err("expected binding identifier");
                    }
                }
            }
        }
        let cover_before = self.cover_init_count;
        let lhs_start_line = self.tok.line;
        let lhs_start_pos = self.tok.start;
        let lhs = self.parse_conditional(no_in)?;
        if let Some(op) = self.is_assign_op() {
            // (like the reference engine, an invalid target is reported after the right-hand
            // side has been parsed)
            let mut deferred: Option<ParseError> = None;
            let lhs_is_pattern = op == AssignOp::Assign && matches!(lhs, Expr::Array(_) | Expr::Object(_));
            let target = if op == AssignOp::Assign {
                if matches!(lhs, Expr::Array(_)) && self.spread_trailing_comma.contains(&lhs_start_pos) {
                    deferred = Some(ParseError { msg: "invalid destructuring assignment target".into(), line: lhs_start_line });
                }
                let lhs_covers = self.cover_init_count.saturating_sub(cover_before);
                let consumed_before = self.cover_consumed;
                match self.expr_to_assign_target(lhs, true) {
                    Ok(t) => {
                        if lhs_is_pattern {
                            if deferred.is_none() && self.cover_consumed - consumed_before < lhs_covers {
                                deferred = Some(ParseError {
                                    msg: "invalid shorthand property initializer outside a pattern position".into(),
                                    line: lhs_start_line,
                                });
                            }
                            self.cover_init_count = cover_before;
                        }
                        t
                    }
                    Err(e) => {
                        if deferred.is_none() {
                            deferred = Some(e);
                        }
                        Pattern::Ident(Ident { name: Rc::from("_"), line: lhs_start_line })
                    }
                }
            } else {
                // compound assignment: simple target only
                match lhs.unparen() {
                    Expr::Ident(id) => {
                        if self.ctx.strict && (&*id.name == "eval" || &*id.name == "arguments") {
                            deferred = Some(ParseError {
                                msg: "cannot assign to 'eval' or 'arguments' in strict mode".into(),
                                line: lhs_start_line,
                            });
                        }
                    }
                    Expr::Member { optional: false, .. } | Expr::SuperMember(_) => {}
                    Expr::Call { optional: false, .. } => {}
                    _ => deferred = Some(ParseError { msg: "invalid assignment target".into(), line: lhs_start_line }),
                }
                if let Expr::Paren(_) = lhs {
                    let inner = Self::strip_paren(lhs);
                    Pattern::Expr(Box::new(inner))
                } else {
                    match lhs {
                        Expr::Ident(id) => Pattern::Ident(id),
                        other => Pattern::Expr(Box::new(other)),
                    }
                }
            };
            self.advance()?;
            let value = self.parse_assign(no_in)?;
            if let Some(e) = deferred {
                return Err(e);
            }
            if lhs_is_pattern {
                // (the reference engine forgets cover-initialized names of the whole
                // destructuring assignment, including its right-hand side)
                self.cover_init_count = cover_before;
            }
            return Ok(Expr::Assign { op, target: Box::new(target), value: Box::new(value) });
        }
        Ok(lhs)
    }

    fn finish_arrow_tail(&mut self, a: Expr) -> PResult<Expr> {
        // An arrow function cannot be followed directly by call/member etc. (handled by caller)
        Ok(a)
    }

    fn strip_paren(e: Expr) -> Expr {
        match e {
            Expr::Paren(inner) => Self::strip_paren(*inner),
            other => other,
        }
    }

    /// Convert an expression (parsed as such) into an assignment target pattern.
    fn expr_to_assign_target(&mut self, e: Expr, top: bool) -> PResult<Pattern> {
        let line = self.tok.line;
        match e {
            Expr::Ident(id) => {
                if self.ctx.strict && (&*id.name == "eval" || &*id.name == "arguments") {
                    return self.err_line("cannot assign to 'eval' or 'arguments' in strict mode", line);
                }
                Ok(Pattern::Ident(id))
            }
            Expr::Member { optional: false, .. } | Expr::SuperMember(_) => Ok(Pattern::Expr(Box::new(e))),
            // web-compat: `f() = v` is a runtime ReferenceError, not an early error
            Expr::Call { optional: false, .. } if top => Ok(Pattern::Expr(Box::new(e))),
            Expr::Paren(inner) => {
                // only simple targets allowed in parens
                match inner.unparen() {
                    Expr::Ident(_) | Expr::Member { optional: false, .. } | Expr::SuperMember(_) => {
                        let inner = Self::strip_paren(*inner);
                        self.expr_to_assign_target(inner, false)
                    }
                    _ => {
                        if top {
                            self.err_line("invalid assignment target", line)
                        } else {
                            self.err_line("invalid destructuring assignment target", line)
                        }
                    }
                }
            }
            Expr::Array(elems) => {
                let mut out = Vec::new();
                let mut rest = None;
                let n = elems.len();
                for (i, el) in elems.into_iter().enumerate() {
                    match el {
                        None => out.push(None),
                        Some(ArrayElem::Spread(e)) => {
                            if i != n - 1 {
                                return self.err_line("invalid destructuring assignment target", line);
                            }
                            if let Expr::Assign { .. } = e {
                                return self.err_line("invalid destructuring assignment target", line);
                            }
                            rest = Some(Box::new(self.expr_to_assign_target(e, false)?));
                        }
                        Some(ArrayElem::Expr(e)) => out.push(Some(self.expr_to_pat_elem(e)?)),
                    }
                }
                Ok(Pattern::Array { elems: out, rest })
            }
            Expr::Object(props) => {
                let mut out = Vec::new();
                let mut rest = None;
                let n = props.len();
                for (i, p) in props.into_iter().enumerate() {
                    match p {
                        PropDef::KeyValue(key, v) => {
                            // cover-init {a = 1} is encoded as KeyValue(Ident key, Assign to an
                            // identifier sharing the key's name)
                            if let (PropKey::Ident(k), Expr::Assign { op: AssignOp::Assign, target, .. }) = (&key, &v) {
                                if let Pattern::Ident(id) = &**target {
                                    if Rc::ptr_eq(k, &id.name) {
                                        self.cover_consumed += 1;
                                    }
                                }
                            }
                            let el = self.expr_to_pat_elem(v)?;
                            out.push(ObjPatProp { key, target: el.target, default: el.default });
                        }
                        PropDef::Proto(v) => {
                            let el = self.expr_to_pat_elem(v)?;
                            out.push(ObjPatProp { key: PropKey::Ident(Rc::from("__proto__")), target: el.target, default: el.default });
                        }
                        PropDef::Shorthand(id) => {
                            if self.ctx.strict && (&*id.name == "eval" || &*id.name == "arguments") {
                                return self.err_line("cannot assign to 'eval' or 'arguments' in strict mode", line);
                            }
                            out.push(ObjPatProp { key: PropKey::Ident(id.name.clone()), target: Pattern::Ident(id), default: None });
                        }
                        PropDef::Spread(e) => {
                            if i != n - 1 {
                                return self.err_line("invalid destructuring assignment target", line);
                            }
                            match e.unparen() {
                                Expr::Ident(_) | Expr::Member { .. } => {}
                                _ => return self.err_line("invalid destructuring assignment target", line),
                            }
                            rest = Some(Box::new(self.expr_to_assign_target(e, false)?));
                        }
                        PropDef::Method { .. } => return self.err_line("invalid destructuring assignment target", line),
                    }
                }
                Ok(Pattern::Object { props: out, rest })
            }
            Expr::Assign { .. } => self.err_line("invalid destructuring assignment target", line),
            _ => {
                if top {
                    self.err_line("invalid assignment target", line)
                } else {
                    self.err_line("invalid destructuring assignment target", line)
                }
            }
        }
    }

    fn expr_to_pat_elem(&mut self, e: Expr) -> PResult<PatElem> {
        match e {
            Expr::Assign { op: AssignOp::Assign, target, value } => {
                if let Pattern::Expr(ref inner) = *target {
                    // a = 1 where target was converted already
                    let _ = inner;
                }
                Ok(PatElem { target: *target, default: Some(*value) })
            }
            other => Ok(PatElem { target: self.expr_to_assign_target(other, false)?, default: None }),
        }
    }

    fn parse_yield(&mut self) -> PResult<Expr> {
        if self.ctx.in_params {
            return self.err("yield expression not allowed in formal parameter");
        }
        self.advance()?; // yield
        if self.tok.nl_before {
            return Ok(Expr::Yield { arg: None, delegate: false });
        }
        let delegate = self.eat_punct("*")?;
        let starts_expr = !matches!(
            &self.tok.tok,
            Tok::Punct(")") | Tok::Punct("]") | Tok::Punct("}") | Tok::Punct(",") | Tok::Punct(";") | Tok::Punct(":") | Tok::Eof
        );
        if !starts_expr {
            return Ok(Expr::Yield { arg: None, delegate });
        }
        let arg = self.parse_assign(false)?;
        Ok(Expr::Yield { arg: Some(Box::new(arg)), delegate })
    }

    fn parse_conditional(&mut self, no_in: bool) -> PResult<Expr> {
        let test = self.parse_binary(0, no_in)?;
        if self.is_punct("?") {
            self.advance()?;
            let cons = self.parse_assign(false)?;
            self.expect_punct(":")?;
            let alt = self.parse_assign(no_in)?;
            return Ok(Expr::Cond(Box::new(test), Box::new(cons), Box::new(alt)));
        }
        Ok(test)
    }

    fn binop_info(&self, no_in: bool) -> Option<(u8, Result<BinOp, LogicalOp>)> {
        match &self.tok.tok {
            Tok::Punct(p) => Some(match *p {
                "??" => (1, Err(LogicalOp::Nullish)),
                "||" => (2, Err(LogicalOp::Or)),
                "&&" => (3, Err(LogicalOp::And)),
                "|" => (4, Ok(BinOp::BitOr)),
                "^" => (5, Ok(BinOp::BitXor)),
                "&" => (6, Ok(BinOp::BitAnd)),
                "==" => (7, Ok(BinOp::Eq)),
                "!=" => (7, Ok(BinOp::Ne)),
                "===" => (7, Ok(BinOp::StrictEq)),
                "!==" => (7, Ok(BinOp::StrictNe)),
                "<" => (8, Ok(BinOp::Lt)),
                ">" => (8, Ok(BinOp::Gt)),
                "<=" => (8, Ok(BinOp::Le)),
                ">=" => (8, Ok(BinOp::Ge)),
                "<<" => (9, Ok(BinOp::Shl)),
                ">>" => (9, Ok(BinOp::Shr)),
                ">>>" => (9, Ok(BinOp::UShr)),
                "+" => (10, Ok(BinOp::Add)),
                "-" => (10, Ok(BinOp::Sub)),
                "*" => (11, Ok(BinOp::Mul)),
                "/" => (11, Ok(BinOp::Div)),
                "%" => (11, Ok(BinOp::Mod)),
                "**" => (12, Ok(BinOp::Exp)),
                _ => return None,
            }),
            Tok::Keyword("instanceof") => Some((8, Ok(BinOp::InstanceOf))),
            Tok::Keyword("in") if !no_in => Some((8, Ok(BinOp::In))),
            _ => None,
        }
    }

    fn parse_binary(&mut self, min_prec: u8, no_in: bool) -> PResult<Expr> {
        // (a private name `#x` is parsed as a placeholder identifier; `#x in obj` is formed
        // by the operator loop)
        let mut left = self.parse_unary()?;
        let mut saw_nullish = false;
        let mut saw_andor = false;
        loop {
            let (prec, op) = match self.binop_info(no_in) {
                Some(x) => x,
                None => break,
            };
            // left-associative operators recurse with `prec + 1`, so an operator of the same
            // precedence ends the right operand; `**` (right-associative) recurses with 12
            if prec < min_prec {
                break;
            }
            if prec == 12 {
                // right assoc; check unary base
                if let Expr::Unary(..) = left {
                    return self.err("a unary expression cannot be the base of '**' (use parentheses)");
                }
                if let Expr::Await(_) = left {
                    return self.err("a unary expression cannot be the base of '**' (use parentheses)");
                }
            }
            match op {
                Err(LogicalOp::Nullish) => {
                    if saw_andor {
                        return self.err("cannot mix '??' with '&&' or '||' without parentheses");
                    }
                    saw_nullish = true;
                }
                Err(_) => {
                    if saw_nullish {
                        return self.err("cannot mix '??' with '&&' or '||' without parentheses");
                    }
                    saw_andor = true;
                }
                _ => {}
            }
            let private_left = match (&op, left.unparen()) {
                (Ok(BinOp::In), Expr::Ident(id)) if id.name.starts_with('#') => {
                    let name: Rc<str> = Rc::from(&id.name[1..]);
                    let pos = self.bare_private.pop().map(|(p, _)| p).unwrap_or(self.prev_end);
                    self.note_private_ref_at(&name, pos);
                    Some(name)
                }
                _ => None,
            };
            self.advance()?;
            let next_min = if prec == 12 { 12 } else { prec + 1 };
            let right = self.parse_binary(next_min, no_in)?;
            if let Ok(BinOp::In) = op {
                if let Expr::Ident(id) = right.unparen() {
                    if id.name.starts_with('#') {
                        return self.err("a private name may only appear to the left of 'in'");
                    }
                }
            }
            if let Some(name) = private_left {
                left = Expr::PrivateIn(name, Box::new(right));
                continue;
            }
            // check mixing within right operand
            if let Err(LogicalOp::Nullish) = op {
                if let Expr::Logical(LogicalOp::And | LogicalOp::Or, ..) = right {
                    return self.err("cannot mix '??' with '&&' or '||' without parentheses");
                }
            }
            if let Err(LogicalOp::And | LogicalOp::Or) = op {
                if let Expr::Logical(LogicalOp::Nullish, ..) = right {
                    return self.err("cannot mix '??' with '&&' or '||' without parentheses");
                }
            }
            left = match op {
                Ok(b) => Expr::Binary(b, Box::new(left), Box::new(right)),
                Err(l) => {
                    if l == LogicalOp::Nullish {
                        if let Expr::Logical(LogicalOp::And | LogicalOp::Or, ..) = left {
                            return self.err("cannot mix '??' with '&&' or '||' without parentheses");
                        }
                    }
                    Expr::Logical(l, Box::new(left), Box::new(right))
                }
            };
        }
        Ok(left)
    }

    fn parse_unary(&mut self) -> PResult<Expr> {
        let line = self.tok.line;
        let op = match &self.tok.tok {
            Tok::Punct("!") => Some(UnaryOp::Not),
            Tok::Punct("-") => Some(UnaryOp::Neg),
            Tok::Punct("+") => Some(UnaryOp::Plus),
            Tok::Punct("~") => Some(UnaryOp::BitNot),
            Tok::Keyword("typeof") => Some(UnaryOp::Typeof),
            Tok::Keyword("void") => Some(UnaryOp::Void),
            Tok::Keyword("delete") => Some(UnaryOp::Delete),
            _ => None,
        };
        if let Some(op) = op {
            self.advance()?;
            let arg = self.parse_unary()?;
            if op == UnaryOp::Delete {
                if self.ctx.strict {
                    if let Expr::Ident(_) = arg.unparen() {
                        return self.err_line("delete of an unqualified identifier in strict mode", line);
                    }
                }
                if let Expr::Member { prop: MemberProp::Private(_), .. } = arg.unparen() {
                    return self.err_line("private fields cannot be deleted", line);
                }
            }
            return Ok(Expr::Unary(op, Box::new(arg)));
        }
        if self.is_punct("++") || self.is_punct("--") {
            let inc = self.is_punct("++");
            self.advance()?;
            let arg = self.parse_unary()?;
            self.check_update_target(&arg, line)?;
            return Ok(Expr::Update { inc, prefix: true, target: Box::new(arg) });
        }
        if self.is_ident_named("await") && (self.ctx.in_async || (self.is_module && !self.ctx.in_function) || (self.repl_mode && !self.ctx.in_function)) {
            if self.ctx.in_params {
                return self.err("await expression not allowed in formal parameter");
            }
            if self.ctx.in_static_block {
                return self.err("'await' is not a valid identifier here");
            }
            self.advance()?;
            if !self.ctx.in_function {
                self.has_tla = true;
            }
            let arg = self.parse_unary()?;
            return Ok(Expr::Await(Box::new(arg)));
        }
        let e = self.parse_postfix()?;
        Ok(e)
    }

    fn check_update_target(&self, e: &Expr, line: u32) -> PResult<()> {
        match e.unparen() {
            Expr::Ident(id) => {
                if self.ctx.strict && (&*id.name == "eval" || &*id.name == "arguments") {
                    return self.err_line("cannot increment/decrement 'eval' or 'arguments' in strict mode", line);
                }
                Ok(())
            }
            Expr::Member { optional: false, .. } | Expr::SuperMember(_) => Ok(()),
            Expr::Call { optional: false, .. } => Ok(()),
            _ => self.err_line("invalid increment/decrement operand", line),
        }
    }

    fn parse_postfix(&mut self) -> PResult<Expr> {
        let line = self.tok.line;
        let e = self.parse_lhs_expression_full(true)?;
        if (self.is_punct("++") || self.is_punct("--")) && !self.tok.nl_before {
            let inc = self.is_punct("++");
            self.check_update_target(&e, line)?;
            self.advance()?;
            self.relex_slash_as_regex()?;
            return Ok(Expr::Update { inc, prefix: false, target: Box::new(e) });
        }
        Ok(e)
    }

    fn parse_lhs_expression(&mut self) -> PResult<Expr> {
        self.parse_lhs_expression_full(true)
    }

    fn parse_arguments(&mut self) -> PResult<Vec<ArrayElem>> {
        self.expect_punct("(")?;
        let mut args = Vec::new();
        while !self.is_punct(")") {
            if self.eat_punct("...")? {
                args.push(ArrayElem::Spread(self.parse_assign(false)?));
            } else {
                args.push(ArrayElem::Expr(self.parse_assign(false)?));
            }
            if !self.is_punct(")") {
                if !self.is_punct(",") {
                    return self.err("expected ')'");
                }
                self.advance()?;
            }
        }
        self.advance()?;
        Ok(args)
    }

    /// a reference to private name `#name` ending at `pos`
    fn note_private_ref_at(&mut self, name: &str, pos: usize) {
        if let Some(refs) = self.private_refs.last_mut() {
            refs.push((Rc::from(name), pos));
        } else if self.strict_private {
            self.undeclared_private.push((pos, format!("Private name '#{}' is not declared in an enclosing class", name)));
        }
    }

    fn note_private_ref(&mut self, name: &str) {
        let pos = self.prev_end;
        self.note_private_ref_at(name, pos);
    }

    fn parse_lhs_expression_full(&mut self, allow_call: bool) -> PResult<Expr> {
        let start = self.tok.start;
        let mut e = if self.is_kw("new") {
            self.parse_new()?
        } else if self.is_kw("super") {
            self.parse_super()?
        } else if self.is_kw("import") {
            self.parse_import_expr()?
        } else {
            self.parse_primary()?
        };
        let _ = start;
        let mut in_chain = false;
        loop {
            if self.is_punct(".") {
                self.advance()?;
                if let Tok::PrivateName(n) = &self.tok.tok {
                    let n = n.clone();
                    self.advance()?;
                    self.note_private_ref(&n);
                    e = Expr::Member { obj: Box::new(e), prop: MemberProp::Private(Rc::from(n.as_str())), optional: false };
                    continue;
                }
                let name = match self.ident_name_of_tok() {
                    Some(n) => n,
                    None => return self.err("expected property name"),
                };
                self.advance()?;
                e = Expr::Member { obj: Box::new(e), prop: MemberProp::Name(Rc::from(name.as_str())), optional: false };
            } else if self.is_punct("?.") {
                self.advance()?;
                in_chain = true;
                if self.is_punct("(") {
                    if !allow_call {
                        return self.err("an optional chain cannot follow 'new' without arguments");
                    }
                    let args = self.parse_arguments()?;
                    e = Expr::Call { callee: Box::new(e), args, optional: true };
                } else if self.is_punct("[") {
                    self.advance()?;
                    let p = self.parse_expression(false)?;
                    self.expect_punct("]")?;
                    e = Expr::Member { obj: Box::new(e), prop: MemberProp::Computed(Box::new(p)), optional: true };
                } else if let Tok::PrivateName(n) = &self.tok.tok {
                    let n = n.clone();
                    self.advance()?;
                    self.note_private_ref(&n);
                    e = Expr::Member { obj: Box::new(e), prop: MemberProp::Private(Rc::from(n.as_str())), optional: true };
                } else if matches!(self.tok.tok, Tok::Template { .. }) {
                    return self.err("expected property name");
                } else {
                    let name = match self.ident_name_of_tok() {
                        Some(n) => n,
                        None => return self.err("expected property name"),
                    };
                    self.advance()?;
                    e = Expr::Member { obj: Box::new(e), prop: MemberProp::Name(Rc::from(name.as_str())), optional: true };
                }
            } else if self.is_punct("[") {
                self.advance()?;
                let p = self.parse_expression(false)?;
                self.expect_punct("]")?;
                e = Expr::Member { obj: Box::new(e), prop: MemberProp::Computed(Box::new(p)), optional: false };
            } else if self.is_punct("(") && allow_call {
                let args = self.parse_arguments()?;
                e = Expr::Call { callee: Box::new(e), args, optional: false };
            } else if let Tok::Template { .. } = &self.tok.tok {
                if in_chain {
                    return self.err("tagged template cannot appear in an optional chain");
                }
                let (quasis, exprs) = self.parse_template_parts(true)?;
                let id = TEMPLATE_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                self.template_counter += 1;
                e = Expr::TaggedTemplate { tag: Box::new(e), quasis: Rc::new(quasis), exprs, id };
            } else {
                break;
            }
        }
        if in_chain {
            e = Expr::OptChain(Box::new(e));
        }
        Ok(e)
    }

    fn parse_super(&mut self) -> PResult<Expr> {
        let line = self.tok.line;
        self.advance()?; // super
        if self.is_punct("(") {
            if !self.ctx.allow_super_call {
                return self.err_line("'super' call unexpected here", line);
            }
            let args = self.parse_arguments()?;
            return Ok(Expr::SuperCall(args));
        }
        if !self.ctx.allow_super_prop {
            return self.err_line("'super' keyword unexpected here", line);
        }
        if self.eat_punct(".")? {
            if let Tok::PrivateName(_) = self.tok.tok {
                return self.err("cannot access a private member through 'super'");
            }
            let name = match self.ident_name_of_tok() {
                Some(n) => n,
                None => return self.err("expected property name"),
            };
            self.advance()?;
            return Ok(Expr::SuperMember(MemberProp::Name(Rc::from(name.as_str()))));
        }
        if self.eat_punct("[")? {
            let p = self.parse_expression(false)?;
            self.expect_punct("]")?;
            return Ok(Expr::SuperMember(MemberProp::Computed(Box::new(p))));
        }
        self.err_line("'super' keyword unexpected here", line)
    }

    fn parse_import_expr(&mut self) -> PResult<Expr> {
        self.advance()?; // import
        if self.eat_punct(".")? {
            if self.is_ident_named("meta") {
                if !self.is_module {
                    return self.err("'import.meta' is only valid in a module");
                }
                self.advance()?;
                return Ok(Expr::ImportMeta);
            }
            // import.defer(...) / import.source(...)
            if self.is_ident_named("defer") || self.is_ident_named("source") {
                self.advance()?;
            } else {
                return self.err("expected 'meta', 'source', or 'defer' after 'import.'");
            }
        }
        if !self.is_punct("(") {
            return self.err("expected '('");
        }
        self.advance()?;
        let spec = self.parse_assign(false)?;
        let mut opts = None;
        if self.eat_punct(",")? {
            if !self.is_punct(")") {
                opts = Some(Box::new(self.parse_assign(false)?));
                self.eat_punct(",")?;
            }
        }
        self.expect_punct(")")?;
        Ok(Expr::ImportCall(Box::new(spec), opts))
    }

    fn parse_new(&mut self) -> PResult<Expr> {
        let line = self.tok.line;
        self.advance()?; // new
        if self.is_punct(".") {
            self.advance()?;
            if self.is_ident_named("target") {
                if !self.ctx.allow_new_target && !self.ctx.in_function {
                    return self.err_line("new.target is only valid inside a function", line);
                }
                self.advance()?;
                return Ok(Expr::NewTarget);
            }
            return self.err("expected 'target' after 'new.'");
        }
        // callee: MemberExpression (no call)
        let callee = if self.is_kw("new") {
            self.parse_new()?
        } else if self.is_kw("super") {
            self.parse_super()?
        } else if self.is_kw("import") {
            return self.err("cannot use new with import");
        } else {
            self.parse_primary()?
        };
        // member accesses
        let mut callee = callee;
        loop {
            if self.is_punct(".") {
                self.advance()?;
                if let Tok::PrivateName(n) = &self.tok.tok {
                    let n = n.clone();
                    self.advance()?;
                    self.note_private_ref(&n);
                    callee = Expr::Member { obj: Box::new(callee), prop: MemberProp::Private(Rc::from(n.as_str())), optional: false };
                    continue;
                }
                let name = match self.ident_name_of_tok() {
                    Some(n) => n,
                    None => return self.err("expected property name"),
                };
                self.advance()?;
                callee = Expr::Member { obj: Box::new(callee), prop: MemberProp::Name(Rc::from(name.as_str())), optional: false };
            } else if self.is_punct("[") {
                self.advance()?;
                let p = self.parse_expression(false)?;
                self.expect_punct("]")?;
                callee = Expr::Member { obj: Box::new(callee), prop: MemberProp::Computed(Box::new(p)), optional: false };
            } else if let Tok::Template { .. } = &self.tok.tok {
                let (quasis, exprs) = self.parse_template_parts(true)?;
                let id = TEMPLATE_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                callee = Expr::TaggedTemplate { tag: Box::new(callee), quasis: Rc::new(quasis), exprs, id };
            } else if self.is_punct("?.") {
                return self.err("an optional chain cannot follow 'new' without arguments");
            } else {
                break;
            }
        }
        let args = if self.is_punct("(") { self.parse_arguments()? } else { Vec::new() };
        Ok(Expr::New { callee: Box::new(callee), args })
    }

    fn ident_ref(&mut self) -> PResult<Ident> {
        let line = self.tok.line;
        match self.advance()?.tok {
            Tok::Ident(n) => Ok(Ident { name: Rc::from(n.as_str()), line }),
            _ => unreachable!(),
        }
    }

    fn parse_template_parts(&mut self, tagged: bool) -> PResult<(Vec<TemplateQuasi>, Vec<Expr>)> {
        let mut quasis = Vec::new();
        let mut exprs = Vec::new();
        loop {
            let (cooked, raw, tail) = match &self.tok.tok {
                Tok::Template { cooked, raw, tail } => (cooked.clone(), raw.clone(), *tail),
                _ => return self.err("expected template continuation"),
            };
            if cooked.is_none() && !tagged {
                return self.err("invalid escape sequence in template literal");
            }
            quasis.push(TemplateQuasi { cooked: cooked.map(|c| Rc::from(c.as_slice())), raw: Rc::from(raw.as_slice()) });
            if tail {
                self.advance()?;
                break;
            }
            // parse expression inside ${ }
            match self.advance() {
                Ok(_) => {}
                Err(e) if e.msg == "unterminated template literal" => return self.err("unterminated nested template"),
                Err(e) => return Err(e),
            }
            if self.is_punct("}") {
                // empty substitution
                return self.err("unexpected token Eof");
            }
            let e = match self.parse_expression(false) {
                Ok(e) => e,
                Err(e) if e.msg == "unterminated template literal" => return self.err_line("unterminated nested template", e.line),
                Err(e) => return Err(e),
            };
            exprs.push(e);
            if !self.is_punct("}") {
                // (the reference engine ignores anything else up to the closing brace)
                let mut depth = 0usize;
                loop {
                    match &self.tok.tok {
                        Tok::Eof => return self.err("expected '}'"),
                        Tok::Punct("{") | Tok::Punct("${") => depth += 1,
                        Tok::Punct("}") if depth == 0 => break,
                        Tok::Punct("}") => depth -= 1,
                        _ => {}
                    }
                    self.advance()?;
                }
            }
            // rescan template continuation
            let start = self.tok.start;
            let line = self.tok.line;
            self.lex.pos = start + 1;
            self.lex.line = line;
            let t = self.lex.read_template(start, line, false)?;
            self.tok = t;
        }
        Ok((quasis, exprs))
    }

    fn parse_primary(&mut self) -> PResult<Expr> {
        let start = self.tok.start;
        let line = self.tok.line;
        match self.tok.tok.clone() {
            Tok::Num(n) => {
                if self.ctx.strict && self.tok.legacy_octal {
                    return self.err("legacy octal literals are not allowed in strict mode");
                }
                self.advance()?;
                Ok(Expr::Num(n))
            }
            Tok::BigInt(s) => {
                self.advance()?;
                Ok(Expr::BigInt(Rc::from(s.as_str())))
            }
            Tok::Str(s) => {
                if self.ctx.strict && self.tok.octal_escape {
                    return self.err("legacy octal literals are not allowed in strict mode");
                }
                self.advance()?;
                Ok(Expr::Str(Rc::from(s.as_slice())))
            }
            Tok::Template { .. } => {
                let (quasis, exprs) = self.parse_template_parts(false)?;
                Ok(Expr::Template { quasis, exprs })
            }
            Tok::Punct("/") | Tok::Punct("/=") | Tok::Regex { .. } if !self.prev_rparen || matches!(self.tok.tok, Tok::Regex { .. }) => {
                if !matches!(self.tok.tok, Tok::Regex { .. }) {
                    let t = self.lex.read_regex(self.tok.start, self.tok.line, self.tok.nl_before)?;
                    self.tok = t;
                }
                let (pattern, flags) = match &self.tok.tok {
                    Tok::Regex { pattern, flags } => (pattern.clone(), flags.clone()),
                    _ => unreachable!(),
                };
                // validate
                match crate::regexp::parse_flags(&flags) {
                    Ok(fl) => {
                        if let Err(m) = crate::regexp::compile(&pattern, fl) {
                            return self.err(m);
                        }
                    }
                    Err(m) => return self.err(m),
                }
                self.advance()?;
                Ok(Expr::Regex { pattern: Rc::from(pattern.as_slice()), flags: Rc::from(flags.as_slice()) })
            }
            Tok::Punct("(") => {
                self.advance()?;
                let e = self.parse_expression_unchecked(false)?;
                self.expect_punct(")")?;
                Ok(Expr::Paren(Box::new(e)))
            }
            Tok::Punct("[") => self.parse_array_literal(),
            Tok::Punct("{") => self.parse_object_literal(),
            Tok::Keyword("function") => Ok(Expr::Function(self.parse_function_expr(false, start)?)),
            Tok::Keyword("class") => {
                let c = self.parse_class(false)?;
                Ok(Expr::Class(c))
            }
            Tok::Punct("@") => {
                let decs = self.parse_decorators()?;
                if !self.is_kw("class") && !self.is_punct("{") && !self.is_kw("extends") {
                    return self.err("expected '{'");
                }
                let mut c = self.parse_class(false)?;
                if let Some(cm) = Rc::get_mut(&mut c) {
                    cm.decorators = decs;
                }
                Ok(Expr::Class(c))
            }
            Tok::Keyword("this") => {
                self.advance()?;
                Ok(Expr::This)
            }
            Tok::Keyword("null") => {
                self.advance()?;
                Ok(Expr::Null)
            }
            Tok::Keyword("true") => {
                self.advance()?;
                Ok(Expr::Bool(true))
            }
            Tok::Keyword("false") => {
                self.advance()?;
                Ok(Expr::Bool(false))
            }
            Tok::Ident(n) => {
                if n == "async" && !self.tok.escaped {
                    let next = self.peek_token()?;
                    if matches!(next.tok, Tok::Keyword("function")) && !next.nl_before {
                        self.advance()?;
                        return Ok(Expr::Function(self.parse_function_expr(true, start)?));
                    }
                }
                if n == "yield" && (self.ctx.in_generator || self.ctx.strict) {
                    if self.ctx.in_generator {
                        return self.unexpected();
                    }
                    return self.err("'yield' is a reserved word in strict mode");
                }
                if n == "await" && (self.ctx.in_async || self.is_module) && !self.tok.escaped {
                    return self.unexpected();
                }
                if n == "await" && self.ctx.in_static_block {
                    return self.err("'await' is not a valid identifier here");
                }
                if self.ctx.strict && is_reserved_strict(&n) && n != "yield" {
                    return self.err(format!("'{}' is a reserved word in strict mode", n));
                }
                if n == "arguments" && self.ctx.in_static_block {
                    return self.err("'arguments' is not allowed in a class static block");
                }
                if n == "arguments" && self.ctx.in_field_init {
                    return self.err("'arguments' is not allowed in a class field initializer");
                }
                let kw_like = (n == "yield" || n == "await") && !self.tok.escaped;
                self.advance()?;
                if kw_like {
                    self.relex_slash_as_regex()?;
                }
                Ok(Expr::Ident(Ident { name: Rc::from(n.as_str()), line }))
            }
            Tok::PrivateName(n) => {
                // reported after parsing unless it turns out to be the left operand of `in`
                let line = self.tok.line;
                self.advance()?;
                self.bare_private.push((self.prev_end, format!("private name '#{}' may only be used in a member access or 'in' expression", n)));
                Ok(Expr::Ident(Ident { name: Rc::from(format!("#{}", n).as_str()), line }))
            }
            Tok::Punct("#") => self.err("private name '#' may only be used in a member access or 'in' expression"),
            _ => self.unexpected(),
        }
    }

    fn parse_array_literal(&mut self) -> PResult<Expr> {
        let arr_start = self.tok.start;
        self.advance()?; // [
        let mut elems = Vec::new();
        loop {
            if self.is_punct("]") {
                break;
            }
            if self.is_punct(",") {
                self.advance()?;
                elems.push(None);
                continue;
            }
            let el = if self.eat_punct("...")? {
                ArrayElem::Spread(self.parse_assign(false)?)
            } else {
                ArrayElem::Expr(self.parse_assign(false)?)
            };
            let is_spread = matches!(el, ArrayElem::Spread(_));
            elems.push(Some(el));
            if self.is_punct("]") {
                break;
            }
            if !self.is_punct(",") {
                return self.err("expected ']'");
            }
            self.advance()?;
            if is_spread && self.is_punct("]") {
                self.spread_trailing_comma.push(arr_start);
            }
        }
        self.advance()?; // ]
        Ok(Expr::Array(elems))
    }

    fn parse_object_literal(&mut self) -> PResult<Expr> {
        self.advance()?; // {
        let mut props = Vec::new();
        let mut has_proto = false;
        while !self.is_punct("}") {
            if self.eat_punct("...")? {
                props.push(PropDef::Spread(self.parse_assign(false)?));
                if !self.is_punct("}") {
                    if !self.is_punct(",") {
                        return self.err("expected '}'");
                    }
                    self.advance()?;
                }
                continue;
            }
            let pstart = self.tok.start;
            let line = self.tok.line;
            let mut is_async = false;
            let mut is_gen = false;
            let mut kind = MethodKind::Method;
            if self.is_ident_named("async") {
                let next = self.peek_token()?;
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct(":") | Tok::Punct(",") | Tok::Punct("}") | Tok::Punct("=")) {
                    if next.nl_before && !matches!(next.tok, Tok::Punct("*")) {
                        return self.err_line("line terminator not allowed after 'async' in a method", next.line);
                    }
                    self.advance()?;
                    is_async = true;
                }
            }
            if self.is_punct("*") {
                self.advance()?;
                is_gen = true;
            }
            if !is_async && !is_gen && (self.is_ident_named("get") || self.is_ident_named("set")) {
                let next = self.peek_token()?;
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct(":") | Tok::Punct(",") | Tok::Punct("}") | Tok::Punct("=")) {
                    kind = if self.is_ident_named("get") { MethodKind::Getter } else { MethodKind::Setter };
                    self.advance()?;
                }
            }
            let key_tok_is_ident = matches!(self.tok.tok, Tok::Ident(_));
            let key_tok_escaped = self.tok.escaped;
            let key_is_kw = matches!(self.tok.tok, Tok::Keyword(_));
            if let Tok::PrivateName(_) = self.tok.tok {
                return self.err("private names are only allowed in class bodies");
            }
            let (key, shorthand) = self.parse_property_key()?;
            if (is_async || is_gen) && !self.is_punct("(") {
                return self.err("expected a method after 'async'/'*' in an object literal");
            }
            if self.is_punct("(") || is_async || is_gen || kind != MethodKind::Method {
                let fk = match kind {
                    MethodKind::Getter => FuncKind::Getter,
                    MethodKind::Setter => FuncKind::Setter,
                    MethodKind::Method => FuncKind::Method,
                };
                let f = self.parse_method(fk, is_async, is_gen, pstart, line)?;
                props.push(PropDef::Method { key, func: f, kind });
            } else if self.eat_punct(":")? {
                let v = self.parse_assign(false)?;
                let is_proto = match &key {
                    PropKey::Ident(n) => &**n == "__proto__",
                    PropKey::Str(s) => String::from_utf16_lossy(s) == "__proto__",
                    _ => false,
                };
                if is_proto {
                    if has_proto {
                        return self.err_line("duplicate __proto__ property in object literal", line);
                    }
                    has_proto = true;
                    props.push(PropDef::Proto(v));
                } else {
                    props.push(PropDef::KeyValue(key, v));
                }
            } else {
                // shorthand
                let name = match shorthand {
                    Some(n) if key_tok_is_ident || (key_is_kw && false) => n,
                    _ => {
                        if key_is_kw {
                            if let PropKey::Ident(k) = &key {
                                return self.err(format!("'{}' is a reserved word and cannot be a shorthand property", k));
                            }
                            return self.unexpected_prev_keyword();
                        }
                        return self.err("expected ':' after property key");
                    }
                };
                let _ = key_tok_escaped;
                if self.ctx.strict && is_reserved_strict(&name) {
                    return self.err_line(format!("'{}' cannot be used as a shorthand property in strict mode", name), line);
                }
                if (name == "yield" && self.ctx.in_generator) || (name == "await" && (self.ctx.in_async || self.is_module)) {
                    return self.err_line(format!("'{}' cannot be used as a shorthand property here", name), line);
                }
                let id = Ident { name: Rc::from(name.as_str()), line };
                if self.is_punct("=") {
                    // cover initialized name
                    self.advance()?;
                    let def = self.parse_assign(false)?;
                    self.cover_init_count += 1;
                    props.push(PropDef::KeyValue(
                        PropKey::Ident(id.name.clone()),
                        Expr::Assign { op: AssignOp::Assign, target: Box::new(Pattern::Ident(id)), value: Box::new(def) },
                    ));
                } else {
                    props.push(PropDef::Shorthand(id));
                }
            }
            if !self.is_punct("}") {
                if !self.is_punct(",") {
                    return self.err("expected '}'");
                }
                self.advance()?;
            }
        }
        self.advance()?;
        Ok(Expr::Object(props))
    }

    fn unexpected_prev_keyword<T>(&self) -> PResult<T> {
        self.err("expected ':'")
    }
}

/// Parse a full script/module.
pub fn parse(src: &str, is_module: bool) -> Result<Program, ParseError> {
    let p = Parser::new(src, is_module)?;
    p.parse_program()
}

pub fn parse_repl(src: &str) -> Result<Program, ParseError> {
    let mut p = Parser::new(src, false)?;
    p.repl_mode = true;
    p.parse_program()
}

/// Parse with options for eval / Function constructor
pub struct ParseOptions {
    pub is_module: bool,
    pub strict: bool,
    pub in_function: bool,
    pub allow_super_prop: bool,
    pub allow_super_call: bool,
    pub allow_new_target: bool,
    pub in_field_init: bool,
    pub allow_return: bool,
    pub in_async: bool,
    pub in_generator: bool,
    pub repl: bool,
}

pub fn parse_with(src: &str, o: &ParseOptions) -> Result<Program, ParseError> {
    let mut p = Parser::new(src, o.is_module)?;
    p.repl_mode = o.repl;
    p.ctx.strict = o.strict || o.is_module;
    p.ctx.in_function = o.in_function;
    p.ctx.allow_super_prop = o.allow_super_prop;
    p.ctx.allow_super_call = o.allow_super_call;
    p.ctx.allow_new_target = o.allow_new_target;
    p.ctx.in_field_init = o.in_field_init;
    p.ctx.allow_return = o.allow_return;
    p.ctx.in_async = o.in_async;
    p.ctx.in_generator = o.in_generator;
    // direct eval code may reference private names of an enclosing class
    p.strict_private = !o.in_function;
    let strict = p.ctx.strict;
    let (body, strict) = p.parse_directives_and_body(true, strict)?;
    let deferred_error = p.take_deferred_private();
    Ok(Program {
        body,
        strict,
        is_module: o.is_module,
        scope: ScopeId::new(),
        source: p.source.clone(),
        has_top_level_await: p.has_tla,
        deferred_error,
    })
}
