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

thread_local! {
    /// Whether the most recent parse error was raised at the end of the input (the REPL treats
    /// such input as incomplete and asks for more lines).
    pub static ERR_AT_EOF: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

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
    private_refs: Vec<Vec<Rc<str>>>,
    /// number of cover-initialized names seen ({a = 1} in object literal) that are not yet converted
    cover_init_count: usize,
    pub repl_mode: bool,
}

struct SavedState {
    pos: usize,
    line: u32,
    tok: Token,
    prev_end: usize,
    prev_line: u32,
    cover: usize,
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
            cover_init_count: 0,
            repl_mode: false,
        })
    }

    // ---------- token helpers ----------

    fn err<T>(&self, msg: impl Into<String>) -> PResult<T> {
        ERR_AT_EOF.with(|c| c.set(matches!(self.tok.tok, Tok::Eof)));
        Err(ParseError { msg: msg.into(), line: self.tok.line })
    }

    fn err_line<T>(&self, msg: impl Into<String>, line: u32) -> PResult<T> {
        ERR_AT_EOF.with(|c| c.set(matches!(self.tok.tok, Tok::Eof)));
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
        Ok(old)
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
            prev_line: self.prev_line,
            cover: self.cover_init_count,
        }
    }
    fn restore(&mut self, s: SavedState) {
        self.lex.pos = s.pos;
        self.lex.line = s.line;
        self.tok = s.tok;
        self.prev_end = s.prev_end;
        self.prev_line = s.prev_line;
        self.cover_init_count = s.cover;
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
            if name == "eval" || name == "arguments" {
                return self.err_line(format!("'{}' cannot be used as a binding in strict mode", name), line);
            }
            if is_reserved_strict(name) {
                return self.err_line(format!("'{}' is a reserved word in strict mode", name), line);
            }
        }
        Ok(())
    }

    fn binding_ident(&mut self) -> PResult<Ident> {
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
        Ok(Program {
            body,
            strict,
            is_module: self.is_module,
            scope: ScopeId::new(),
            source: self.source.clone(),
            has_top_level_await: self.has_tla,
        })
    }

    pub fn into_source(&self) -> Rc<str> {
        self.source.clone()
    }

    /// Parses statements until EOF (top) or '}' (function body), handling directive prologue.
    fn parse_directives_and_body(&mut self, top: bool, mut strict: bool) -> PResult<(Vec<Stmt>, bool)> {
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
                                return self.err_line("octal escape sequences are not allowed in strict mode", l);
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
                if !self.is_kw("class") {
                    return self.err("expected 'class' after decorators");
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
                    Tok::Ident(_) => true,
                    Tok::Punct("[") | Tok::Punct("{") => true,
                    Tok::Keyword(k) => {
                        // let if ... is error; let in -> expression
                        !matches!(*k, "in" | "instanceof") && !next.nl_before
                    }
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
                let cons = self.parse_substatement()?;
                let alt = if self.eat_kw("else")? { Some(Box::new(self.parse_substatement()?)) } else { None };
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
                    return self.err("expected 'while'");
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
                let label = if !self.tok.nl_before && matches!(self.tok.tok, Tok::Ident(_)) {
                    let n = self.ident_name_of_tok().unwrap();
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
                            Some(_) => return self.err_line("undefined continue label", line),
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
                let label = if !self.tok.nl_before && matches!(self.tok.tok, Tok::Ident(_)) {
                    let n = self.ident_name_of_tok().unwrap();
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
                        if self.ctx.strict {
                            self.breakable_depth -= 1;
                            self.labels.pop();
                            return self.err("functions cannot be labelled in strict mode");
                        }
                        Stmt::Function(self.parse_function_decl(false)?)
                    } else {
                        self.parse_statement()?
                    };
                    self.breakable_depth -= 1;
                    self.labels.pop();
                    return Ok(Stmt::Labeled(name, Box::new(body)));
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

    fn parse_substatement(&mut self) -> PResult<Stmt> {
        // declarations not allowed as substatement (except sloppy function in if)
        match &self.tok.tok {
            Tok::Keyword("class") => self.unexpected(),
            Tok::Ident(n) if n == "let" => {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct("[")) {
                    return self.err("lexical declaration cannot appear in a single-statement context");
                }
                self.parse_statement()
            }
            _ => self.parse_statement(),
        }
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
        let mut body = Vec::new();
        while !self.is_punct("}") {
            if matches!(self.tok.tok, Tok::Eof) {
                return self.err("expected '}'");
            }
            body.push(self.parse_statement_list_item()?);
        }
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
            if kind != VarKind::Var {
                if let Pattern::Ident(id) = &target {
                    if &*id.name == "let" {
                        return self.err_line("'let' is disallowed as a lexically bound name", line);
                    }
                }
            }
            let init = if self.eat_punct("=")? {
                Some(self.parse_assign(no_in)?)
            } else {
                None
            };
            if init.is_none() && !no_in {
                if kind == VarKind::Const {
                    return self.err("missing initializer in const declaration");
                }
                if !matches!(target, Pattern::Ident(_)) {
                    return self.err("missing initializer in destructuring declaration");
                }
            }
            decls.push(VarDeclarator { target, init });
            if !self.eat_punct(",")? {
                break;
            }
        }
        Ok(VarDecl { kind, decls })
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
                self.expect_punct(",")?;
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
            let (key, shorthand_name) = self.parse_property_key()?;
            if self.eat_punct(":")? {
                let el = self.parse_binding_element()?;
                props.push(ObjPatProp { key, target: el.target, default: el.default });
            } else {
                let name = match shorthand_name {
                    Some(n) => n,
                    None => return self.err("expected ':'"),
                };
                // validate as binding identifier
                if matches!(name.as_str(), "yield") && (self.ctx.in_generator || self.ctx.strict) {
                    return self.err_line("expected binding identifier", line);
                }
                if name == "await" && (self.ctx.in_async || self.is_module) {
                    return self.err_line("expected binding identifier", line);
                }
                if crate::lexer::keyword_of(&name).is_some() {
                    return self.err_line("expected binding identifier", line);
                }
                self.check_binding_name(&name, line)?;
                let default = if self.eat_punct("=")? { Some(self.parse_assign(false)?) } else { None };
                props.push(ObjPatProp {
                    key,
                    target: Pattern::Ident(Ident { name: Rc::from(name.as_str()), line }),
                    default,
                });
            }
            if !self.is_punct("}") {
                self.expect_punct(",")?;
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
                    return self.err("octal escape sequences are not allowed in strict mode");
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
        }
        self.expect_punct("(")?;
        // init
        let mut init: Option<ForInit> = None;
        if self.is_punct(";") {
            // empty init
        } else {
            let is_let_decl = if self.is_ident_named("let") {
                let next = self.peek_token()?;
                matches!(next.tok, Tok::Ident(_) | Tok::Punct("[") | Tok::Punct("{"))
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
                    let mut decl = decl;
                    let d = decl.decls.pop().unwrap();
                    let mut var_init = None;
                    if let Some(i) = d.init {
                        if is_of || kind != VarKind::Var || self.ctx.strict || !matches!(d.target, Pattern::Ident(_)) {
                            return self.err(if is_of {
                                "for-of loop variable declaration may not have an initializer"
                            } else {
                                "for-in loop variable declaration may not have an initializer"
                            });
                        }
                        var_init = Some(i);
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
                for d in &decl.decls {
                    if d.init.is_none() {
                        if kind == VarKind::Const {
                            return self.err("missing initializer in const declaration");
                        }
                        if !matches!(d.target, Pattern::Ident(_)) {
                            return self.err("missing initializer in destructuring declaration");
                        }
                    }
                }
                init = Some(ForInit::Var(decl));
            } else {
                // expression or assignment target
                let start_tok_is_let = self.is_ident_named("let");
                let start_is_async = self.is_ident_named("async") && !self.tok.escaped;
                let e = self.parse_expression_no_in()?;
                if self.is_kw("in") || (self.is_ident_named("of") && !(start_is_async && matches!(e, Expr::Ident(_)))) {
                    let is_of = self.is_ident_named("of");
                    if is_of && start_tok_is_let {
                        return self.err("for-of loop left-hand side may not start with 'let'");
                    }
                    let target = self.expr_to_assign_target(e, true)?;
                    self.advance()?;
                    let right = if is_of { self.parse_assign(false)? } else { self.parse_expression(false)? };
                    self.expect_punct(")")?;
                    let body = self.parse_loop_body()?;
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
                self.check_no_cover_init()?;
                init = Some(ForInit::Expr(e));
            }
        }
        if is_await {
            return self.err("expected 'of'");
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
                    return self.err("more than one switch default");
                }
                has_default = true;
                None
            } else {
                self.breakable_depth -= 1;
                return self.err("expected 'case' or 'default'");
            };
            self.expect_punct(":")?;
            let mut body = Vec::new();
            while !self.is_punct("}") && !self.is_kw("case") && !self.is_kw("default") {
                if matches!(self.tok.tok, Tok::Eof) {
                    self.breakable_depth -= 1;
                    return self.err("expected '}'");
                }
                body.push(self.parse_statement_list_item()?);
            }
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
            let e = self.parse_assign(false)?;
            self.check_no_cover_init()?;
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
        } else {
            let saved = self.ctx;
            let id = self.binding_ident()?;
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
        } else {
            // name binding is checked in the function's own context
            let saved = self.ctx;
            self.ctx.in_generator = is_gen;
            self.ctx.in_async = is_async;
            let r = self.binding_ident();
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
            if kind == FuncKind::Getter && !params.is_empty() {
                return self.err_line("getter functions must have no arguments", line);
            }
            if kind == FuncKind::Setter && (params.len() != 1 || params[0].rest) {
                return self.err_line("setter functions must have exactly one argument", line);
            }
            self.expect_punct("{")?;
            let was_strict = self.ctx.strict;
            let (body, strict) = self.parse_directives_and_body(false, self.ctx.strict)?;
            let end = self.tok.end;
            self.expect_punct("}")?;
            let simple = params.iter().all(|p| matches!(p.pat, Pattern::Ident(_)) && p.default.is_none() && !p.rest);
            if strict && !was_strict && !simple {
                return self.err_line("'use strict' not allowed in function with non-simple parameters", line);
            }
            self.validate_params(&params, strict, simple || kind == FuncKind::Arrow, kind == FuncKind::Arrow || matches!(kind, FuncKind::Method | FuncKind::Getter | FuncKind::Setter | FuncKind::ClassConstructor | FuncKind::DerivedConstructor), line)?;
            if strict {
                if let Some(n) = &name {
                    if &*n.name == "eval" || &*n.name == "arguments" {
                        return self.err_line(format!("'{}' cannot be used as a binding in strict mode", n.name), n.line);
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

    fn validate_params(&self, params: &[Param], strict: bool, _simple: bool, no_dups: bool, line: u32) -> PResult<()> {
        let mut names: Vec<Rc<str>> = Vec::new();
        fn collect(p: &Pattern, out: &mut Vec<(Rc<str>, u32)>) {
            match p {
                Pattern::Ident(id) => out.push((id.name.clone(), id.line)),
                Pattern::Array { elems, rest } => {
                    for e in elems.iter().flatten() {
                        collect(&e.target, out);
                    }
                    if let Some(r) = rest {
                        collect(r, out);
                    }
                }
                Pattern::Object { props, rest } => {
                    for pr in props {
                        collect(&pr.target, out);
                    }
                    if let Some(r) = rest {
                        collect(r, out);
                    }
                }
                Pattern::Expr(_) => {}
            }
        }
        let mut all = Vec::new();
        for p in params {
            collect(&p.pat, &mut all);
        }
        let simple = params.iter().all(|p| matches!(p.pat, Pattern::Ident(_)) && p.default.is_none() && !p.rest);
        for (n, l) in &all {
            if strict && (&**n == "eval" || &**n == "arguments") {
                return self.err_line(format!("'{}' cannot be used as a binding in strict mode", n), *l);
            }
            if strict && is_reserved_strict(n) {
                return self.err_line(format!("'{}' is a reserved word in strict mode", n), *l);
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
                if self.is_punct("=") {
                    return self.err("rest parameter may not have a default initializer");
                }
                params.push(Param { pat, default: None, rest: true });
                if !self.is_punct(")") {
                    return self.err("expected ')'");
                }
                break;
            }
            let el = self.parse_binding_element()?;
            params.push(Param { pat: el.target, default: el.default, rest: false });
            if !self.is_punct(")") {
                self.expect_punct(",")?;
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
            Ok(p) if self.is_punct("=>") && self.tok.nl_before => {
                let _ = p;
                return self.err("unexpected line terminator before '=>'");
            }
            _ => {
                self.restore(saved);
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
                    return self.err_line("'use strict' not allowed in function with non-simple parameters", line);
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
                if !matches!(self.tok.tok, Tok::Ident(_)) {
                    return self.err("expected a decorator expression after '@'");
                }
                let mut e = Expr::Ident(self.ident_ref()?);
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
        self.advance()?; // class
        let saved_strict = self.ctx.strict;
        self.ctx.strict = true;
        let name = if self.is_binding_ident() && !self.is_ident_named("extends") {
            Some(self.binding_ident()?)
        } else if self.is_kw("extends") || self.is_punct("{") {
            let _ = require_name;
            None
        } else {
            self.ctx.strict = saved_strict;
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
            let _decorators = if self.is_punct("@") { self.parse_decorators()? } else { Vec::new() };
            let mstart = self.tok.start;
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
                }
            }
            if self.is_ident_named("async") {
                let next = self.peek_token()?;
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct("=") | Tok::Punct(";") | Tok::Punct("}")) && !next.nl_before {
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
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct("=") | Tok::Punct(";") | Tok::Punct("}")) && !(next.nl_before && false) {
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
                    return self.err_line("class members cannot be named '#constructor'", key_line);
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
                            return self.err_line(format!("private name '#{}' has already been declared", n), key_line);
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
                        return self.err_line("class constructor may not be an accessor, generator or async", line);
                    }
                    if constructor.is_some() {
                        return self.err_line("a class may only have one constructor", line);
                    }
                    let fk = if derived { FuncKind::DerivedConstructor } else { FuncKind::ClassConstructor };
                    let f = self.parse_method(fk, false, false, mstart, line)?;
                    constructor = Some(f);
                    continue;
                }
                if is_static && matches!(&key, PropKey::Ident(n) if &**n == "prototype") {
                    return self.err_line("classes may not have a static property named 'prototype'", line);
                }
                let fk = match kind {
                    MethodKind::Getter => FuncKind::Getter,
                    MethodKind::Setter => FuncKind::Setter,
                    MethodKind::Method => FuncKind::Method,
                };
                let f = self.parse_method(fk, is_async, is_gen, mstart, line)?;
                members.push(ClassMember::Method { key, func: f, kind, is_static });
            } else {
                // field
                if is_ctor_key || matches!(&key, PropKey::Ident(n) if &**n == "constructor") {
                    return self.err_line("classes may not have a field named 'constructor'", line);
                }
                if is_static && matches!(&key, PropKey::Ident(n) if &**n == "prototype") {
                    return self.err_line("classes may not have a static property named 'prototype'", line);
                }
                if kind != MethodKind::Method || is_gen || is_async {
                    return self.err("expected '('");
                }
                let value = if self.eat_punct("=")? {
                    let vstart = self.tok.start;
                    let f = self.parse_field_initializer(vstart, line)?;
                    Some(f)
                } else {
                    None
                };
                self.consume_semicolon()?;
                members.push(ClassMember::Field { key, value, is_static, is_accessor });
            }
        }
        let end = self.tok.end;
        self.advance()?; // }
        // resolve private references
        let declared = self.private_scopes.pop().unwrap();
        let refs = self.private_refs.pop().unwrap();
        for r in refs {
            if !declared.contains(&r) {
                if let Some(outer) = self.private_refs.last_mut() {
                    outer.push(r);
                } else {
                    return self.err_line(format!("reference to undeclared private name '#{}'", r), 0);
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
        let e = self.parse_assign(no_in)?;
        if self.is_punct(",") {
            let mut v = vec![e];
            while self.eat_punct(",")? {
                v.push(self.parse_assign(no_in)?);
            }
            self.check_no_cover_init()?;
            return Ok(Expr::Seq(v));
        }
        self.check_no_cover_init()?;
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

    fn check_no_cover_init(&self) -> PResult<()> {
        if self.cover_init_count > 0 {
            return self.err("invalid shorthand property initializer");
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
            if self.is_binding_ident() || (n == "yield" || n == "await") {
                let next = self.peek_token()?;
                if matches!(next.tok, Tok::Punct("=>")) {
                    if let Some(a) = self.try_parse_arrow(false, start)? {
                        return self.finish_arrow_tail(a);
                    }
                    if n == "await" || n == "yield" {
                        return self.err("expected binding identifier");
                    }
                }
            }
        }
        let cover_before = self.cover_init_count;
        let lhs_start_line = self.tok.line;
        let lhs = self.parse_conditional(no_in)?;
        if let Some(op) = self.is_assign_op() {
            let target = if op == AssignOp::Assign {
                let t = self.expr_to_assign_target(lhs, true)?;
                self.cover_init_count = cover_before;
                t
            } else {
                // compound assignment: simple target only
                match lhs.unparen() {
                    Expr::Ident(id) => {
                        if self.ctx.strict && (&*id.name == "eval" || &*id.name == "arguments") {
                            return self.err_line("invalid assignment target", lhs_start_line);
                        }
                    }
                    Expr::Member { optional: false, .. } | Expr::SuperMember(_) => {}
                    _ => return self.err_line("invalid assignment target", lhs_start_line),
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
                    return self.err_line("invalid assignment target", line);
                }
                Ok(Pattern::Ident(id))
            }
            Expr::Member { optional: false, .. } | Expr::SuperMember(_) => Ok(Pattern::Expr(Box::new(e))),
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
                            // cover-init {a = 1} is encoded as KeyValue(Ident key, Assign with marker)
                            let el = self.expr_to_pat_elem(v)?;
                            out.push(ObjPatProp { key, target: el.target, default: el.default });
                        }
                        PropDef::Proto(v) => {
                            let el = self.expr_to_pat_elem(v)?;
                            out.push(ObjPatProp { key: PropKey::Ident(Rc::from("__proto__")), target: el.target, default: el.default });
                        }
                        PropDef::Shorthand(id) => {
                            if self.ctx.strict && (&*id.name == "eval" || &*id.name == "arguments") {
                                return self.err_line("invalid destructuring assignment target", line);
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
        ) && !self.is_kw("in");
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
        // private name `#x in obj`
        let mut left = if let Tok::PrivateName(n) = &self.tok.tok {
            let n = n.clone();
            let next = self.peek_token()?;
            if matches!(next.tok, Tok::Keyword("in")) && !no_in {
                self.advance()?;
                self.note_private_ref(&n);
                self.advance()?; // in
                let right = self.parse_binary(9, no_in)?;
                Expr::PrivateIn(Rc::from(n.as_str()), Box::new(right))
            } else {
                return self.err_line(format!("private name '#{}' may only be used in a member access or 'in' expression", n), 0);
            }
        } else {
            self.parse_unary()?
        };
        let mut saw_nullish = false;
        let mut saw_andor = false;
        loop {
            let (prec, op) = match self.binop_info(no_in) {
                Some(x) => x,
                None => break,
            };
            if prec < min_prec || (prec == min_prec && prec != 12) {
                // left-assoc: stop when equal precedence (handled by recursion with prec+1)
                if prec < min_prec {
                    break;
                }
                if prec == min_prec && prec != 12 {
                    break;
                }
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
            self.advance()?;
            let next_min = if prec == 12 { 12 } else { prec + 1 };
            let right = self.parse_binary(next_min, no_in)?;
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
                return self.err("unexpected 'await' in class static block");
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
                    return self.err_line("invalid increment/decrement operand", line);
                }
                Ok(())
            }
            Expr::Member { optional: false, .. } | Expr::SuperMember(_) => Ok(()),
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
            self.check_no_cover_init()?;
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

    fn note_private_ref(&mut self, name: &str) {
        if let Some(refs) = self.private_refs.last_mut() {
            refs.push(Rc::from(name));
        }
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
                        return self.err("invalid optional chain from new expression");
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
                    return self.err("tagged template cannot appear in an optional chain");
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
                return self.err("expected 'meta'");
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
                return self.err("invalid optional chain from new expression");
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
                return self.err("invalid escape sequence in template");
            }
            quasis.push(TemplateQuasi { cooked: cooked.map(|c| Rc::from(c.as_slice())), raw: Rc::from(raw.as_slice()) });
            if tail {
                self.advance()?;
                break;
            }
            // parse expression inside ${ }
            self.advance()?;
            let e = self.parse_expression(false)?;
            exprs.push(e);
            if !self.is_punct("}") {
                return self.err("expected '}'");
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
                    return self.err("octal escape sequences are not allowed in strict mode");
                }
                self.advance()?;
                Ok(Expr::Str(Rc::from(s.as_slice())))
            }
            Tok::Template { .. } => {
                let (quasis, exprs) = self.parse_template_parts(false)?;
                Ok(Expr::Template { quasis, exprs })
            }
            Tok::Punct("/") | Tok::Punct("/=") => {
                let t = self.lex.read_regex(self.tok.start, self.tok.line, self.tok.nl_before)?;
                self.tok = t;
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
                let e = self.parse_expression(false)?;
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
                if !self.is_kw("class") {
                    return self.err("expected 'class' after decorators");
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
                    return self.err("unexpected strict mode reserved word");
                }
                if n == "await" && (self.ctx.in_async || self.is_module) && !self.tok.escaped {
                    return self.unexpected();
                }
                if self.ctx.strict && is_reserved_strict(&n) && n != "yield" {
                    return self.err("unexpected strict mode reserved word");
                }
                if n == "arguments" && (self.ctx.in_field_init || self.ctx.in_static_block) {
                    return self.err("'arguments' is not allowed in class field initializer or static initialization block");
                }
                self.advance()?;
                Ok(Expr::Ident(Ident { name: Rc::from(n.as_str()), line }))
            }
            Tok::PrivateName(n) => {
                self.err_line(format!("private name '#{}' may only be used in a member access or 'in' expression", n), 0)
            }
            _ => self.unexpected(),
        }
    }

    fn parse_array_literal(&mut self) -> PResult<Expr> {
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
            elems.push(Some(el));
            if self.is_punct("]") {
                break;
            }
            if !self.is_punct(",") {
                return self.err("expected ']'");
            }
            self.advance()?;
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
                if !matches!(next.tok, Tok::Punct("(") | Tok::Punct(":") | Tok::Punct(",") | Tok::Punct("}") | Tok::Punct("="))
                    && !next.nl_before
                {
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
                return self.err("expected property key");
            }
            let (key, shorthand) = self.parse_property_key()?;
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
                        return self.err_line("duplicate __proto__ fields are not allowed in object literals", line);
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
                            return self.unexpected_prev_keyword();
                        }
                        return self.err("expected ':'");
                    }
                };
                let _ = key_tok_escaped;
                if (name == "yield" && (self.ctx.in_generator || self.ctx.strict)) || (name == "await" && (self.ctx.in_async || self.is_module)) {
                    return self.err_line("invalid shorthand property", line);
                }
                if self.ctx.strict && is_reserved_strict(&name) {
                    return self.err_line("unexpected strict mode reserved word", line);
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
    let strict = p.ctx.strict;
    let (body, strict) = p.parse_directives_and_body(true, strict)?;
    Ok(Program {
        body,
        strict,
        is_module: o.is_module,
        scope: ScopeId::new(),
        source: p.source.clone(),
        has_top_level_await: p.has_tla,
    })
}
