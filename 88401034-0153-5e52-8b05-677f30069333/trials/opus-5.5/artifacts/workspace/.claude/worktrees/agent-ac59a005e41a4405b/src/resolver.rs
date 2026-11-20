// Scope analysis: assigns scope ids to AST nodes, records declarations and which bindings
// are captured by closures (and therefore must live in heap environments).

use crate::ast::*;
use crate::bytecode::BindKind;
use std::rc::Rc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScopeKind {
    Script,
    Module,
    Function,
    Block,
    Catch,
    Class,
    With,
    FuncName,
    Eval,
}

#[derive(Debug, Clone)]
pub struct RDecl {
    pub name: Rc<str>,
    pub kind: BindKind,
    pub captured: bool,
    pub line: u32,
}

#[derive(Debug)]
pub struct RScope {
    pub kind: ScopeKind,
    pub parent: Option<usize>,
    /// enclosing function-like scope (itself for function/script/module/eval scopes)
    pub func: usize,
    pub decls: Vec<RDecl>,
    pub strict: bool,
    pub is_arrow: bool,
    /// function contains a sloppy direct eval (all lookups crossing it are dynamic)
    pub has_eval: bool,
    /// any direct eval (strict or sloppy) somewhere inside (needs this/arguments materialized)
    pub contains_eval: bool,
    pub uses_arguments: bool,
    pub uses_this: bool,
    pub func_kind: Option<FuncKind>,
    /// body scope of a function with parameter expressions: receives the body's `var`s
    pub var_scope: bool,
    /// sloppy eval code: var names introduced only by Annex B block-level functions
    pub annexb: Vec<Rc<str>>,
}

impl RScope {
    pub fn find(&self, name: &str) -> Option<usize> {
        self.decls.iter().position(|d| &*d.name == name)
    }
}

pub struct ResolveError {
    pub msg: String,
    pub line: u32,
}

type RResult<T> = Result<T, ResolveError>;

pub struct Resolver {
    pub scopes: Vec<RScope>,
    cur: usize,
    /// top-level script mode: var/function/let at the top are global
    pub global_names_lex: Vec<(Rc<str>, u32)>,
    pub global_names_var: Vec<(Rc<str>, u32)>,
    is_eval: bool,
}

pub fn is_function_like(k: ScopeKind) -> bool {
    matches!(k, ScopeKind::Function | ScopeKind::Script | ScopeKind::Module | ScopeKind::Eval)
}

/// Does a parameter list contain expressions (defaults, computed keys)? Such functions get a
/// separate environment for the body's var declarations, and their parameters have TDZ.
pub fn has_param_expressions(f: &Function) -> bool {
    fn pat(p: &Pattern) -> bool {
        match p {
            Pattern::Ident(_) => false,
            Pattern::Array { elems, rest } => elems.iter().flatten().any(|e| e.default.is_some() || pat(&e.target)) || rest.as_ref().map_or(false, |r| pat(r)),
            Pattern::Object { props, rest } => {
                props.iter().any(|p| p.default.is_some() || matches!(p.key, PropKey::Computed(_)) || pat(&p.target)) || rest.as_ref().map_or(false, |r| pat(r))
            }
            Pattern::Expr(_) => true,
        }
    }
    f.params.iter().any(|p| p.default.is_some() || pat(&p.pat))
}

fn err<T>(msg: String, line: u32) -> RResult<T> {
    Err(ResolveError { msg, line })
}

pub fn pattern_names(p: &Pattern, out: &mut Vec<(Rc<str>, u32)>) {
    match p {
        Pattern::Ident(id) => out.push((id.name.clone(), id.line)),
        Pattern::Array { elems, rest } => {
            for e in elems.iter().flatten() {
                pattern_names(&e.target, out);
            }
            if let Some(r) = rest {
                pattern_names(r, out);
            }
        }
        Pattern::Object { props, rest } => {
            for p in props {
                pattern_names(&p.target, out);
            }
            if let Some(r) = rest {
                pattern_names(r, out);
            }
        }
        Pattern::Expr(_) => {}
    }
}

impl Resolver {
    pub fn new() -> Resolver {
        Resolver { scopes: Vec::new(), cur: 0, global_names_lex: Vec::new(), global_names_var: Vec::new(), is_eval: false }
    }

    fn push_scope(&mut self, kind: ScopeKind, strict: bool) -> usize {
        let id = self.scopes.len();
        let parent = if self.scopes.is_empty() { None } else { Some(self.cur) };
        let func = if is_function_like(kind) { id } else { self.scopes[self.cur].func };
        self.scopes.push(RScope {
            kind,
            parent,
            func,
            decls: Vec::new(),
            strict,
            is_arrow: false,
            has_eval: false,
            contains_eval: false,
            uses_arguments: false,
            uses_this: false,
            func_kind: None,
            var_scope: false,
            annexb: Vec::new(),
        });
        self.cur = id;
        id
    }

    fn pop_scope(&mut self) {
        self.cur = self.scopes[self.cur].parent.unwrap_or(0);
    }

    fn strict(&self) -> bool {
        self.scopes[self.cur].strict
    }

    fn declare(&mut self, scope: usize, name: &Rc<str>, kind: BindKind, line: u32) -> RResult<()> {
        let s = &mut self.scopes[scope];
        if let Some(i) = s.find(name) {
            let existing = s.decls[i].kind;
            let lexical = |k: BindKind| matches!(k, BindKind::Let | BindKind::Const | BindKind::Class);
            let conflict = match (existing, kind) {
                (BindKind::Var, BindKind::Var) => false,
                (BindKind::Param, BindKind::Var) | (BindKind::Param, BindKind::Function) => false,
                (BindKind::Var, BindKind::Function) | (BindKind::Function, BindKind::Var) => {
                    // in function scope, var + function is fine; in blocks function is lexical
                    !is_function_like(s.kind)
                }
                (BindKind::Function, BindKind::Function) => {
                    // duplicate function declarations in blocks: allowed in sloppy mode
                    !is_function_like(s.kind) && s.strict
                }
                (BindKind::Internal, _) | (_, BindKind::Internal) => false,
                (BindKind::FuncName, _) => false,
                (BindKind::CatchParam, BindKind::Var) => false,
                (a, b) => lexical(a) || lexical(b) || a == BindKind::CatchParam || b == BindKind::CatchParam || (a == BindKind::Param && lexical(b)),
            };
            if conflict {
                return err(format!("Identifier '{}' has already been declared", name), line);
            }
            if kind == BindKind::Function && existing == BindKind::Var {
                s.decls[i].kind = BindKind::Function;
            }
            return Ok(());
        }
        s.decls.push(RDecl { name: name.clone(), kind, captured: false, line });
        Ok(())
    }

    /// declare a var-scoped name from the current scope: walks up to the function scope,
    /// checking lexical conflicts in intermediate scopes.
    /// nearest scope receiving `var` declarations from scope `s`
    fn var_target(&self, mut s: usize) -> usize {
        loop {
            let sc = &self.scopes[s];
            if sc.var_scope || is_function_like(sc.kind) {
                return s;
            }
            match sc.parent {
                Some(p) => s = p,
                None => return s,
            }
        }
    }

    fn declare_var(&mut self, name: &Rc<str>, kind: BindKind, line: u32) -> RResult<()> {
        let mut s = self.cur;
        loop {
            let sc = &self.scopes[s];
            if let Some(i) = sc.find(name) {
                let k = sc.decls[i].kind;
                if matches!(k, BindKind::Let | BindKind::Const | BindKind::Class)
                    || (k == BindKind::Function && !is_function_like(sc.kind) && s != self.cur)
                {
                    return err(format!("Identifier '{}' has already been declared", name), line);
                }
                if k == BindKind::CatchParam {
                    // var redeclaring a simple catch param is allowed (annex B)
                }
            }
            if is_function_like(sc.kind) || sc.var_scope {
                break;
            }
            match sc.parent {
                Some(p) => s = p,
                None => break,
            }
        }
        let vt = self.var_target(self.cur);
        if self.scopes[vt].var_scope {
            return self.declare(vt, name, kind, line);
        }
        let fscope = self.scopes[self.cur].func;
        if self.scopes[fscope].kind == ScopeKind::Script || (self.scopes[fscope].kind == ScopeKind::Eval && !self.scopes[fscope].strict) {
            if self.scopes[fscope].kind == ScopeKind::Script {
                if self.global_names_lex.iter().any(|(n, _)| n == name) {
                    return err(format!("Identifier '{}' has already been declared", name), line);
                }
                if !self.global_names_var.iter().any(|(n, _)| n == name) {
                    self.global_names_var.push((name.clone(), line));
                }
            }
            // record in scope too for eval scopes (dynamic declaration)
            if self.scopes[fscope].kind == ScopeKind::Eval {
                let sc = &mut self.scopes[fscope];
                if sc.find(name).is_none() {
                    sc.decls.push(RDecl { name: name.clone(), kind, captured: true, line });
                }
            }
            return Ok(());
        }
        self.declare(fscope, name, kind, line)
    }

    fn declare_lexical(&mut self, name: &Rc<str>, kind: BindKind, line: u32) -> RResult<()> {
        let sc = &self.scopes[self.cur];
        if sc.kind == ScopeKind::Script {
            if self.global_names_lex.iter().any(|(n, _)| n == name) || self.global_names_var.iter().any(|(n, _)| n == name) {
                return err(format!("Identifier '{}' has already been declared", name), line);
            }
            self.global_names_lex.push((name.clone(), line));
            return Ok(());
        }
        // conflict with var declared in this same scope (function top-level)
        self.declare(self.cur, name, kind, line)
    }

    // ---------- hoisting ----------

    /// collect var declarations (and annex-B block functions) in statements, not entering functions
    fn hoist_vars(&mut self, stmts: &[Stmt], top_level: bool) -> RResult<()> {
        for s in stmts {
            self.hoist_vars_stmt(s, top_level)?;
        }
        Ok(())
    }

    fn hoist_vars_stmt(&mut self, s: &Stmt, top_level: bool) -> RResult<()> {
        match s {
            Stmt::Var(d) if d.kind == VarKind::Var => {
                for decl in &d.decls {
                    let mut names = Vec::new();
                    pattern_names(&decl.target, &mut names);
                    for (n, l) in names {
                        self.declare_var(&n, BindKind::Var, l)?;
                    }
                }
            }
            Stmt::If(_, a, b) => {
                self.hoist_vars_stmt(a, false)?;
                if let Some(b) = b {
                    self.hoist_vars_stmt(b, false)?;
                }
            }
            Stmt::Block(b) => self.hoist_vars(&b.body, false)?,
            Stmt::For(f) => {
                if let Some(ForInit::Var(d)) = &f.init {
                    if d.kind == VarKind::Var {
                        for decl in &d.decls {
                            let mut names = Vec::new();
                            pattern_names(&decl.target, &mut names);
                            for (n, l) in names {
                                self.declare_var(&n, BindKind::Var, l)?;
                            }
                        }
                    }
                }
                self.hoist_vars_stmt(&f.body, false)?;
            }
            Stmt::ForIn(f) | Stmt::ForOf(f) => {
                if let ForHead::Decl(VarKind::Var, p) = &f.head {
                    let mut names = Vec::new();
                    pattern_names(p, &mut names);
                    for (n, l) in names {
                        self.declare_var(&n, BindKind::Var, l)?;
                    }
                }
                self.hoist_vars_stmt(&f.body, false)?;
            }
            Stmt::While(_, b) | Stmt::DoWhile(b, _) => self.hoist_vars_stmt(b, false)?,
            Stmt::Try(t) => {
                self.hoist_vars(&t.block.body, false)?;
                if let Some(h) = &t.handler {
                    self.hoist_vars(&h.body, false)?;
                }
                if let Some(f) = &t.finalizer {
                    self.hoist_vars(&f.body, false)?;
                }
            }
            Stmt::Switch(sw) => {
                for c in &sw.cases {
                    self.hoist_vars(&c.body, false)?;
                }
            }
            Stmt::Labeled(_, b) => self.hoist_vars_stmt(b, top_level)?,
            Stmt::With(_, b, _) => self.hoist_vars_stmt(b, false)?,
            Stmt::Export(e) => {
                if let ExportDecl::Decl(st) = &**e {
                    self.hoist_vars_stmt(st, top_level)?;
                }
            }
            _ => {}
        }
        Ok(())
    }

    /// annex B: function declarations in blocks (sloppy) also create a var binding
    fn hoist_annexb_functions(&mut self, stmts: &[Stmt], in_block: bool) {
        for s in stmts {
            self.hoist_annexb_stmt(s, in_block);
        }
    }

    fn hoist_annexb_stmt(&mut self, s: &Stmt, in_block: bool) {
        match s {
            Stmt::Function(f) if in_block => {
                if f.is_async || f.is_generator {
                    return;
                }
                if let Some(n) = &f.name {
                    // only if it wouldn't conflict with a lexical declaration
                    let fscope = self.var_target(self.cur);
                    let conflict = {
                        let sc = &self.scopes[fscope];
                        match sc.find(&n.name) {
                            Some(i) => matches!(sc.decls[i].kind, BindKind::Let | BindKind::Const | BindKind::Class),
                            None => false,
                        }
                    } || (self.scopes[fscope].kind == ScopeKind::Script
                        && self.global_names_lex.iter().any(|(x, _)| *x == n.name));
                    if !conflict {
                        if self.scopes[fscope].kind == ScopeKind::Script {
                            if !self.global_names_var.iter().any(|(x, _)| *x == n.name) {
                                self.global_names_var.push((n.name.clone(), n.line));
                            }
                        } else if self.scopes[fscope].kind == ScopeKind::Eval {
                            let sc = &mut self.scopes[fscope];
                            if sc.find(&n.name).is_none() {
                                sc.decls.push(RDecl { name: n.name.clone(), kind: BindKind::Var, captured: true, line: n.line });
                                sc.annexb.push(n.name.clone());
                            }
                        } else {
                            let sc = &mut self.scopes[fscope];
                            if sc.find(&n.name).is_none() {
                                sc.decls.push(RDecl { name: n.name.clone(), kind: BindKind::Var, captured: false, line: n.line });
                            }
                        }
                    }
                }
            }
            Stmt::If(_, a, b) => {
                self.hoist_annexb_stmt(a, true);
                if let Some(b) = b {
                    self.hoist_annexb_stmt(b, true);
                }
            }
            Stmt::Block(b) => self.hoist_annexb_functions(&b.body, true),
            Stmt::For(f) => self.hoist_annexb_stmt(&f.body, true),
            Stmt::ForIn(f) | Stmt::ForOf(f) => self.hoist_annexb_stmt(&f.body, true),
            Stmt::While(_, b) | Stmt::DoWhile(b, _) => self.hoist_annexb_stmt(b, true),
            Stmt::Try(t) => {
                self.hoist_annexb_functions(&t.block.body, true);
                if let Some(h) = &t.handler {
                    self.hoist_annexb_functions(&h.body, true);
                }
                if let Some(f) = &t.finalizer {
                    self.hoist_annexb_functions(&f.body, true);
                }
            }
            Stmt::Switch(sw) => {
                for c in &sw.cases {
                    self.hoist_annexb_functions(&c.body, true);
                }
            }
            Stmt::Labeled(_, b) => self.hoist_annexb_stmt(b, in_block),
            _ => {}
        }
    }

    /// declare lexical bindings (let/const/class and block-level functions) of a statement list
    fn hoist_lexical(&mut self, stmts: &[Stmt], function_top: bool) -> RResult<()> {
        for s in stmts {
            let s = if let Stmt::Export(e) = s {
                match &**e {
                    ExportDecl::Decl(st) => st,
                    ExportDecl::DefaultFunc(f) => {
                        let name: Rc<str> = match &f.name {
                            Some(n) => n.name.clone(),
                            None => Rc::from("*default*"),
                        };
                        self.declare(self.cur, &name, BindKind::Function, f.line)?;
                        continue;
                    }
                    ExportDecl::DefaultClass(c) => {
                        let name: Rc<str> = match &c.name {
                            Some(n) => n.name.clone(),
                            None => Rc::from("*default*"),
                        };
                        self.declare(self.cur, &name, BindKind::Class, 0)?;
                        continue;
                    }
                    ExportDecl::DefaultExpr(_) => {
                        self.declare(self.cur, &Rc::from("*default*"), BindKind::Const, 0)?;
                        continue;
                    }
                    _ => continue,
                }
            } else {
                s
            };
            let s = if let Stmt::Labeled(_, inner) = s {
                let mut x: &Stmt = inner;
                while let Stmt::Labeled(_, i2) = x {
                    x = i2;
                }
                if let Stmt::Function(_) = x {
                    x
                } else {
                    continue;
                }
            } else {
                s
            };
            match s {
                Stmt::Var(d) if d.kind != VarKind::Var => {
                    let k = if d.kind == VarKind::Let { BindKind::Let } else { BindKind::Const };
                    for decl in &d.decls {
                        let mut names = Vec::new();
                        pattern_names(&decl.target, &mut names);
                        for (n, l) in names {
                            self.declare_lexical(&n, k, l)?;
                        }
                    }
                }
                Stmt::Class(c) => {
                    if let Some(n) = &c.name {
                        self.declare_lexical(&n.name, BindKind::Class, n.line)?;
                    }
                }
                Stmt::Function(f) => {
                    if let Some(n) = &f.name {
                        if function_top {
                            if self.scopes[self.cur].kind == ScopeKind::Script {
                                if self.global_names_lex.iter().any(|(x, _)| *x == n.name) {
                                    return err(format!("Identifier '{}' has already been declared", n.name), n.line);
                                }
                                if !self.global_names_var.iter().any(|(x, _)| *x == n.name) {
                                    self.global_names_var.push((n.name.clone(), n.line));
                                }
                            } else if self.scopes[self.cur].kind == ScopeKind::Eval && !self.scopes[self.cur].strict {
                                let sc = &mut self.scopes[self.cur];
                                if sc.find(&n.name).is_none() {
                                    sc.decls.push(RDecl { name: n.name.clone(), kind: BindKind::Function, captured: true, line: n.line });
                                }
                            } else {
                                self.declare(self.cur, &n.name, BindKind::Function, n.line)?;
                            }
                        } else {
                            self.declare(self.cur, &n.name, BindKind::Function, n.line)?;
                        }
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }

    // ---------- references ----------

    /// Resolve a reference from the current scope; marks captured if crossing functions.
    fn reference(&mut self, name: &str) {
        let mut s = self.cur;
        let my_func = self.scopes[s].func;
        let mut crossed_function = false;
        let mut dynamic = false;
        loop {
            let sc = &self.scopes[s];
            if let Some(i) = sc.find(name) {
                if crossed_function || dynamic {
                    self.scopes[s].decls[i].captured = true;
                }
                return;
            }
            if sc.kind == ScopeKind::With {
                dynamic = true;
            }
            if (is_function_like(sc.kind) || sc.var_scope) && sc.has_eval {
                dynamic = true;
            }
            if is_function_like(sc.kind) && s != my_func {
                // crossed into an outer function
            }
            match sc.parent {
                Some(p) => {
                    if is_function_like(sc.kind) {
                        crossed_function = true;
                    }
                    s = p;
                }
                None => return,
            }
        }
    }

    /// references to this/arguments/new.target/home from arrows walk up to the nearest non-arrow function
    fn reference_internal(&mut self, name: &str) {
        let mut s = self.scopes[self.cur].func;
        let mut crossed = false;
        loop {
            let sc = &self.scopes[s];
            if matches!(sc.kind, ScopeKind::Function) && !sc.is_arrow {
                break;
            }
            if matches!(sc.kind, ScopeKind::Script | ScopeKind::Module | ScopeKind::Eval) {
                if name == "arguments" {
                    // eval code sees the calling function's `arguments` (looked up dynamically);
                    // global and module code have none
                    return;
                }
                break;
            }
            crossed = true;
            match sc.parent {
                Some(p) => s = self.scopes[p].func,
                None => break,
            }
        }
        let target = s;
        if name == "this" {
            self.scopes[target].uses_this = true;
        }
        if name == "arguments" {
            self.scopes[target].uses_arguments = true;
        }
        let rname: Rc<str> = Rc::from(name);
        let sc = &mut self.scopes[target];
        let idx = match sc.find(name) {
            Some(i) => i,
            None => {
                sc.decls.push(RDecl { name: rname, kind: BindKind::Internal, captured: false, line: 0 });
                sc.decls.len() - 1
            }
        };
        if crossed {
            sc.decls[idx].captured = true;
        }
    }

    fn mark_all_captured_upwards(&mut self) {
        let mut s = Some(self.cur);
        while let Some(i) = s {
            for d in self.scopes[i].decls.iter_mut() {
                d.captured = true;
            }
            s = self.scopes[i].parent;
        }
    }

    // ---------- entry points ----------

    pub fn resolve_program(&mut self, p: &Program, kind: ScopeKind) -> RResult<()> {
        self.resolve_program_inner(p, kind)?;
        if let Some(m) = &p.deferred_error {
            return err(m.clone(), 0);
        }
        Ok(())
    }

    fn resolve_program_inner(&mut self, p: &Program, kind: ScopeKind) -> RResult<()> {
        let id = self.push_scope(kind, p.strict);
        p.scope.set(id as u32);
        self.is_eval = kind == ScopeKind::Eval;
        if kind == ScopeKind::Module {
            // imports
            for s in &p.body {
                if let Stmt::Import(imp) = s {
                    if let Some(d) = &imp.default {
                        self.declare(id, &d.name, BindKind::Import, d.line)?;
                    }
                    if let Some(ns) = &imp.namespace {
                        self.declare(id, &ns.name, BindKind::Import, ns.line)?;
                    }
                    for (_, local) in &imp.named {
                        self.declare(id, &local.name, BindKind::Import, local.line)?;
                    }
                }
            }
        }
        if kind == ScopeKind::Eval && p.strict {
            // strict eval: vars are local
        }
        self.hoist_lexical(&p.body, true)?;
        self.hoist_vars(&p.body, true)?;
        if !p.strict {
            self.hoist_annexb_functions(&p.body, false);
        }
        self.walk_stmts(&p.body)?;
        self.pop_scope();
        Ok(())
    }

    /// prepare an eval scope chain: eval code inside a function with arguments etc.
    pub fn set_eval_flags(&mut self) {}

    fn walk_stmts(&mut self, stmts: &[Stmt]) -> RResult<()> {
        for s in stmts {
            self.walk_stmt(s)?;
        }
        Ok(())
    }

    fn walk_block(&mut self, b: &Block) -> RResult<()> {
        let id = self.push_scope(ScopeKind::Block, self.strict());
        b.scope.set(id as u32);
        self.hoist_lexical(&b.body, false)?;
        self.walk_stmts(&b.body)?;
        self.pop_scope();
        Ok(())
    }

    /// a `var` declared inside blocks conflicts with lexical declarations of those blocks
    fn check_var_against_blocks(&self, name: &Rc<str>, line: u32) -> RResult<()> {
        let target = self.var_target(self.cur);
        let mut s = self.cur;
        while s != target {
            let sc = &self.scopes[s];
            if let Some(i) = sc.find(name) {
                if matches!(sc.decls[i].kind, BindKind::Let | BindKind::Const | BindKind::Class | BindKind::Function) {
                    return err(format!("Identifier '{}' has already been declared", name), line);
                }
            }
            match sc.parent {
                Some(p) => s = p,
                None => break,
            }
        }
        Ok(())
    }

    fn walk_stmt(&mut self, s: &Stmt) -> RResult<()> {
        match s {
            Stmt::Expr(e) => self.walk_expr(e),
            Stmt::Var(d) if d.kind == VarKind::Var && self.cur != self.var_target(self.cur) => {
                for decl in &d.decls {
                    let mut names = Vec::new();
                    pattern_names(&decl.target, &mut names);
                    for (n, l) in names {
                        self.check_var_against_blocks(&n, l)?;
                    }
                    self.walk_pattern(&decl.target)?;
                    if let Some(i) = &decl.init {
                        self.walk_expr(i)?;
                    }
                }
                Ok(())
            }
            Stmt::Var(d) => {
                for decl in &d.decls {
                    self.walk_pattern(&decl.target)?;
                    if let Some(i) = &decl.init {
                        self.walk_expr(i)?;
                    }
                }
                Ok(())
            }
            Stmt::Function(f) => {
                if let Some(n) = &f.name {
                    self.reference(&n.name);
                }
                self.walk_function(f)
            }
            Stmt::Class(c) => {
                if let Some(n) = &c.name {
                    self.reference(&n.name);
                }
                self.walk_class(c)
            }
            Stmt::Return(e) => {
                if let Some(e) = e {
                    self.walk_expr(e)?;
                }
                Ok(())
            }
            Stmt::If(t, a, b) => {
                self.walk_expr(t)?;
                self.walk_sub_stmt(a)?;
                if let Some(b) = b {
                    self.walk_sub_stmt(b)?;
                }
                Ok(())
            }
            Stmt::Block(b) => self.walk_block(b),
            Stmt::For(f) => {
                let id = self.push_scope(ScopeKind::Block, self.strict());
                f.scope.set(id as u32);
                if let Some(init) = &f.init {
                    match init {
                        ForInit::Var(d) => {
                            if d.kind != VarKind::Var {
                                let k = if d.kind == VarKind::Const { BindKind::Const } else { BindKind::Let };
                                for decl in &d.decls {
                                    let mut names = Vec::new();
                                    pattern_names(&decl.target, &mut names);
                                    for (n, l) in names {
                                        self.declare(id, &n, k, l)?;
                                    }
                                }
                            }
                            for decl in &d.decls {
                                self.walk_pattern(&decl.target)?;
                                if let Some(i) = &decl.init {
                                    self.walk_expr(i)?;
                                }
                            }
                        }
                        ForInit::Expr(e) => self.walk_expr(e)?,
                    }
                }
                if let Some(t) = &f.test {
                    self.walk_expr(t)?;
                }
                if let Some(u) = &f.update {
                    self.walk_expr(u)?;
                }
                self.walk_sub_stmt(&f.body)?;
                self.pop_scope();
                Ok(())
            }
            Stmt::ForIn(f) | Stmt::ForOf(f) => {
                // right side evaluated in a scope with TDZ bindings for let/const names
                let id = self.push_scope(ScopeKind::Block, self.strict());
                f.scope.set(id as u32);
                if let ForHead::Decl(k, p) = &f.head {
                    if *k != VarKind::Var {
                        let bk = if *k == VarKind::Let { BindKind::Let } else { BindKind::Const };
                        let mut names = Vec::new();
                        pattern_names(p, &mut names);
                        for (n, l) in names {
                            self.declare(id, &n, bk, l)?;
                        }
                    }
                }
                if let Some(vi) = &f.var_init {
                    self.walk_expr(vi)?;
                }
                self.walk_expr(&f.right)?;
                match &f.head {
                    ForHead::Decl(_, p) => self.walk_pattern(p)?,
                    ForHead::Target(p) => self.walk_pattern(p)?,
                }
                self.walk_sub_stmt(&f.body)?;
                self.pop_scope();
                Ok(())
            }
            Stmt::While(t, b) => {
                self.walk_expr(t)?;
                self.walk_sub_stmt(b)
            }
            Stmt::DoWhile(b, t) => {
                self.walk_sub_stmt(b)?;
                self.walk_expr(t)
            }
            Stmt::Break(_) | Stmt::Continue(_) | Stmt::Empty | Stmt::Debugger => Ok(()),
            Stmt::Throw(e) => self.walk_expr(e),
            Stmt::Try(t) => {
                self.walk_block(&t.block)?;
                if let Some(h) = &t.handler {
                    let id = self.push_scope(ScopeKind::Catch, self.strict());
                    t.catch_scope.set(id as u32);
                    if let Some(p) = &t.param {
                        let mut names = Vec::new();
                        pattern_names(p, &mut names);
                        let simple = matches!(p, Pattern::Ident(_));
                        for (n, l) in &names {
                            if names.iter().filter(|(m, _)| m == n).count() > 1 {
                                return err(format!("Identifier '{}' has already been declared", n), *l);
                            }
                            self.declare(id, n, BindKind::CatchParam, *l)?;
                        }
                        self.walk_pattern(p)?;
                        // catch body lexical conflicts with params
                        for st in &h.body {
                            let mut lex = Vec::new();
                            match st {
                                Stmt::Var(d) if d.kind != VarKind::Var => {
                                    for decl in &d.decls {
                                        pattern_names(&decl.target, &mut lex);
                                    }
                                }
                                Stmt::Class(c) => {
                                    if let Some(n) = &c.name {
                                        lex.push((n.name.clone(), n.line));
                                    }
                                }
                                Stmt::Function(f) => {
                                    if let Some(n) = &f.name {
                                        lex.push((n.name.clone(), n.line));
                                    }
                                }
                                Stmt::Var(d) if d.kind == VarKind::Var && !simple => {
                                    // var redeclaring a destructured catch param is an error
                                    for decl in &d.decls {
                                        let mut vn = Vec::new();
                                        pattern_names(&decl.target, &mut vn);
                                        for (v, l) in vn {
                                            if names.iter().any(|(m, _)| *m == v) {
                                                return err(format!("Identifier '{}' has already been declared", v), l);
                                            }
                                        }
                                    }
                                }
                                _ => {}
                            }
                            for (n, l) in lex {
                                if names.iter().any(|(m, _)| *m == n) {
                                    return err(format!("Identifier '{}' has already been declared", n), l);
                                }
                            }
                        }
                    }
                    self.walk_block(h)?;
                    self.pop_scope();
                }
                if let Some(f) = &t.finalizer {
                    self.walk_block(f)?;
                }
                Ok(())
            }
            Stmt::Switch(sw) => {
                self.walk_expr(&sw.disc)?;
                let id = self.push_scope(ScopeKind::Block, self.strict());
                sw.scope.set(id as u32);
                for c in &sw.cases {
                    self.hoist_lexical(&c.body, false)?;
                }
                for c in &sw.cases {
                    if let Some(t) = &c.test {
                        self.walk_expr(t)?;
                    }
                    self.walk_stmts(&c.body)?;
                }
                self.pop_scope();
                Ok(())
            }
            Stmt::Labeled(_, b) => self.walk_stmt(b),
            Stmt::With(obj, body, sid) => {
                self.walk_expr(obj)?;
                let id = self.push_scope(ScopeKind::With, self.strict());
                sid.set(id as u32);
                // everything visible from inside a with must be addressable by name
                self.mark_all_captured_upwards();
                self.walk_sub_stmt(body)?;
                self.pop_scope();
                Ok(())
            }
            Stmt::Import(_) => Ok(()),
            Stmt::Export(e) => match &**e {
                ExportDecl::Decl(s) => self.walk_stmt(s),
                ExportDecl::DefaultExpr(e) => self.walk_expr(e),
                ExportDecl::DefaultFunc(f) => self.walk_function(f),
                ExportDecl::DefaultClass(c) => self.walk_class(c),
                ExportDecl::Named(names) => {
                    for (local, _) in names {
                        self.reference(local);
                        // exported bindings are read by importers: keep them in the env
                        let mut s = self.cur;
                        loop {
                            if let Some(i) = self.scopes[s].find(local) {
                                self.scopes[s].decls[i].captured = true;
                                break;
                            }
                            match self.scopes[s].parent {
                                Some(p) => s = p,
                                None => break,
                            }
                        }
                    }
                    Ok(())
                }
                _ => Ok(()),
            },
        }
    }

    fn walk_sub_stmt(&mut self, s: &Stmt) -> RResult<()> {
        // a function declaration as the body of if/label (sloppy) binds via annex B var hoisting
        self.walk_stmt(s)
    }

    fn walk_pattern(&mut self, p: &Pattern) -> RResult<()> {
        match p {
            Pattern::Ident(id) => {
                self.reference(&id.name);
                Ok(())
            }
            Pattern::Array { elems, rest } => {
                for e in elems.iter().flatten() {
                    self.walk_pattern(&e.target)?;
                    if let Some(d) = &e.default {
                        self.walk_expr(d)?;
                    }
                }
                if let Some(r) = rest {
                    self.walk_pattern(r)?;
                }
                Ok(())
            }
            Pattern::Object { props, rest } => {
                for p in props {
                    if let PropKey::Computed(e) = &p.key {
                        self.walk_expr(e)?;
                    }
                    self.walk_pattern(&p.target)?;
                    if let Some(d) = &p.default {
                        self.walk_expr(d)?;
                    }
                }
                if let Some(r) = rest {
                    self.walk_pattern(r)?;
                }
                Ok(())
            }
            Pattern::Expr(e) => self.walk_expr(e),
        }
    }

    pub fn walk_function(&mut self, f: &Function) -> RResult<()> {
        // named function expression: own scope holding the name
        let has_name_scope = f.is_expr && f.name.is_some() && f.kind == FuncKind::Normal;
        if has_name_scope {
            let id = self.push_scope(ScopeKind::FuncName, f.strict);
            let n = f.name.as_ref().unwrap();
            self.declare(id, &n.name, BindKind::FuncName, n.line)?;
        }
        let id = self.push_scope(ScopeKind::Function, f.strict);
        f.scope.set(id as u32);
        self.scopes[id].is_arrow = f.kind == FuncKind::Arrow;
        self.scopes[id].func_kind = Some(f.kind);
        let param_exprs = has_param_expressions(f);
        // params (with parameter expressions they have TDZ: declared like `let`)
        let param_kind = if param_exprs { BindKind::Let } else { BindKind::Param };
        for p in &f.params {
            let mut names = Vec::new();
            pattern_names(&p.pat, &mut names);
            for (n, l) in names {
                if self.scopes[id].find(&n).is_none() {
                    self.scopes[id].decls.push(RDecl { name: n, kind: param_kind, captured: false, line: l });
                }
            }
        }
        if param_exprs {
            for p in &f.params {
                self.walk_pattern(&p.pat)?;
                if let Some(d) = &p.default {
                    self.walk_expr(d)?;
                }
            }
            // separate scope for the body's var and lexical declarations
            let bid = self.push_scope(ScopeKind::Block, f.strict);
            f.body_scope.set(bid as u32);
            self.scopes[bid].var_scope = true;
            self.hoist_lexical(&f.body, true)?;
            for d in self.scopes[bid].decls.clone() {
                if matches!(d.kind, BindKind::Let | BindKind::Const | BindKind::Class) && self.scopes[id].find(&d.name).is_some() {
                    return err(format!("Identifier '{}' has already been declared", d.name), d.line);
                }
            }
            self.hoist_vars(&f.body, true)?;
            if !f.strict {
                self.hoist_annexb_functions(&f.body, false);
            }
            // vars that share a parameter's name start with the parameter's value
            for d in self.scopes[bid].decls.clone() {
                if matches!(d.kind, BindKind::Var | BindKind::Function) {
                    if let Some(i) = self.scopes[id].find(&d.name) {
                        self.scopes[id].decls[i].captured |= false;
                    }
                }
            }
            self.walk_stmts(&f.body)?;
            self.pop_scope();
            self.pop_scope();
            if has_name_scope {
                self.pop_scope();
            }
            return Ok(());
        }
        self.hoist_lexical(&f.body, true)?;
        // params conflicting with lexical declarations
        for d in self.scopes[id].decls.clone() {
            if matches!(d.kind, BindKind::Let | BindKind::Const | BindKind::Class) {
                if f.params.iter().any(|p| {
                    let mut ns = Vec::new();
                    pattern_names(&p.pat, &mut ns);
                    ns.iter().any(|(n, _)| *n == d.name)
                }) {
                    return err(format!("Identifier '{}' has already been declared", d.name), d.line);
                }
            }
        }
        self.hoist_vars(&f.body, true)?;
        if !f.strict {
            self.hoist_annexb_functions(&f.body, false);
        }
        for p in &f.params {
            self.walk_pattern(&p.pat)?;
            if let Some(d) = &p.default {
                self.walk_expr(d)?;
            }
        }
        self.walk_stmts(&f.body)?;
        // sloppy functions with simple parameter lists that use `arguments` get a mapped
        // arguments object: keep the parameters in the environment so they can alias it
        if !f.strict && f.simple_params && f.kind != FuncKind::Arrow && self.scopes[id].uses_arguments {
            for d in self.scopes[id].decls.iter_mut() {
                if d.kind == BindKind::Param {
                    d.captured = true;
                }
            }
        }
        self.pop_scope();
        if has_name_scope {
            self.pop_scope();
        }
        Ok(())
    }

    fn walk_class(&mut self, c: &Class) -> RResult<()> {
        let id = self.push_scope(ScopeKind::Class, true);
        c.scope.set(id as u32);
        if let Some(n) = &c.name {
            self.declare(id, &n.name, BindKind::Const, n.line)?;
        }
        // private names
        for m in &c.members {
            let key = match m {
                ClassMember::Method { key, .. } => key,
                ClassMember::Field { key, .. } => key,
                _ => continue,
            };
            if let PropKey::Private(n) = key {
                let pn: Rc<str> = Rc::from(format!("#{}", n).as_str());
                if self.scopes[id].find(&pn).is_none() {
                    self.scopes[id].decls.push(RDecl { name: pn, kind: BindKind::Internal, captured: false, line: 0 });
                }
            }
        }
        if let Some(e) = &c.extends {
            self.walk_expr(e)?;
        }
        if let Some(ctor) = &c.constructor {
            self.walk_function(ctor)?;
        }
        for m in &c.members {
            match m {
                ClassMember::Method { key, func, decorators, .. } => {
                    self.walk_key(key)?;
                    for d in decorators {
                        self.walk_expr(d)?;
                    }
                    self.walk_function(func)?;
                }
                ClassMember::Field { key, value, decorators, .. } => {
                    self.walk_key(key)?;
                    for d in decorators {
                        self.walk_expr(d)?;
                    }
                    if let Some(v) = value {
                        self.walk_function(v)?;
                    }
                }
                ClassMember::StaticBlock(f) => self.walk_function(f)?,
            }
        }
        // class decorators are evaluated in the class scope (the class binding is initialized)
        for d in &c.decorators {
            self.walk_expr(d)?;
        }
        self.pop_scope();
        Ok(())
    }

    fn walk_key(&mut self, k: &PropKey) -> RResult<()> {
        match k {
            PropKey::Computed(e) => self.walk_expr(e),
            PropKey::Private(n) => {
                self.reference(&format!("#{}", n));
                Ok(())
            }
            _ => Ok(()),
        }
    }

    fn walk_member_prop(&mut self, p: &MemberProp) -> RResult<()> {
        match p {
            MemberProp::Computed(e) => self.walk_expr(e),
            MemberProp::Private(n) => {
                self.reference(&format!("#{}", n));
                Ok(())
            }
            MemberProp::Name(_) => Ok(()),
        }
    }

    fn walk_args(&mut self, args: &[ArrayElem]) -> RResult<()> {
        for a in args {
            match a {
                ArrayElem::Expr(e) | ArrayElem::Spread(e) => self.walk_expr(e)?,
            }
        }
        Ok(())
    }

    fn walk_expr(&mut self, e: &Expr) -> RResult<()> {
        match e {
            Expr::Num(_) | Expr::Str(_) | Expr::BigInt(_) | Expr::Regex { .. } | Expr::Bool(_) | Expr::Null => Ok(()),
            Expr::Template { exprs, .. } => {
                for x in exprs {
                    self.walk_expr(x)?;
                }
                Ok(())
            }
            Expr::TaggedTemplate { tag, exprs, .. } => {
                self.walk_expr(tag)?;
                for x in exprs {
                    self.walk_expr(x)?;
                }
                Ok(())
            }
            Expr::Ident(id) => {
                if &*id.name == "arguments" {
                    // arguments resolves to a declared binding if any, else the implicit one
                    if !self.declared_in_function_chain("arguments") {
                        self.reference_internal("arguments");
                        return Ok(());
                    }
                }
                self.reference(&id.name);
                Ok(())
            }
            Expr::This => {
                self.reference_internal("this");
                Ok(())
            }
            Expr::NewTarget => {
                self.reference_internal("new.target");
                Ok(())
            }
            Expr::SuperMember(p) => {
                self.reference_internal("this");
                self.reference_internal("%home");
                self.walk_member_prop(p)
            }
            Expr::SuperCall(args) => {
                self.reference_internal("this");
                self.reference_internal("new.target");
                self.reference_internal("%home");
                self.reference_internal("%func");
                self.walk_args(args)
            }
            Expr::ImportMeta => Ok(()),
            Expr::Array(elems) => {
                for el in elems.iter().flatten() {
                    match el {
                        ArrayElem::Expr(e) | ArrayElem::Spread(e) => self.walk_expr(e)?,
                    }
                }
                Ok(())
            }
            Expr::Object(props) => {
                for p in props {
                    match p {
                        PropDef::KeyValue(k, v) => {
                            self.walk_key(k)?;
                            self.walk_expr(v)?;
                        }
                        PropDef::Shorthand(id) => self.reference(&id.name),
                        PropDef::Method { key, func, .. } => {
                            self.walk_key(key)?;
                            self.walk_function(func)?;
                        }
                        PropDef::Spread(e) | PropDef::Proto(e) => self.walk_expr(e)?,
                    }
                }
                Ok(())
            }
            Expr::Function(f) | Expr::Arrow(f) => self.walk_function(f),
            Expr::Class(c) => self.walk_class(c),
            Expr::Unary(_, a) => self.walk_expr(a),
            Expr::Update { target, .. } => self.walk_expr(target),
            Expr::Binary(_, a, b) | Expr::Logical(_, a, b) => {
                self.walk_expr(a)?;
                self.walk_expr(b)
            }
            Expr::Assign { target, value, .. } => {
                self.walk_pattern(target)?;
                self.walk_expr(value)
            }
            Expr::Cond(a, b, c) => {
                self.walk_expr(a)?;
                self.walk_expr(b)?;
                self.walk_expr(c)
            }
            Expr::Call { callee, args, .. } => {
                if let Expr::Ident(id) = &**callee {
                    if &*id.name == "eval" {
                        // direct eval
                        let f = self.scopes[self.cur].func;
                        if !self.scopes[self.cur].strict {
                            self.scopes[f].has_eval = true;
                            // body scope of a function with parameter expressions: the eval's
                            // vars are created there
                            let vt = self.var_target(self.cur);
                            if vt != f {
                                self.scopes[vt].has_eval = true;
                            }
                        }
                        self.scopes[f].contains_eval = true;
                        self.mark_all_captured_upwards();
                        self.reference_internal("this");
                        self.reference_internal("new.target");
                        self.reference_internal("%home");
                        if !self.declared_in_function_chain("arguments") {
                            self.reference_internal("arguments");
                        }
                        self.mark_all_captured_upwards();
                    }
                }
                self.walk_expr(callee)?;
                self.walk_args(args)
            }
            Expr::New { callee, args } => {
                self.walk_expr(callee)?;
                self.walk_args(args)
            }
            Expr::Member { obj, prop, .. } => {
                self.walk_expr(obj)?;
                self.walk_member_prop(prop)
            }
            Expr::OptChain(e) | Expr::Paren(e) | Expr::Await(e) => self.walk_expr(e),
            Expr::Seq(v) => {
                for x in v {
                    self.walk_expr(x)?;
                }
                Ok(())
            }
            Expr::Yield { arg, .. } => {
                if let Some(a) = arg {
                    self.walk_expr(a)?;
                }
                Ok(())
            }
            Expr::PrivateIn(n, e) => {
                self.reference(&format!("#{}", n));
                self.walk_expr(e)
            }
            Expr::ImportCall(a, b) => {
                self.walk_expr(a)?;
                if let Some(b) = b {
                    self.walk_expr(b)?;
                }
                Ok(())
            }
        }
    }

    /// is `name` declared (non-internally) in some scope up to and including the nearest non-arrow function?
    fn declared_in_function_chain(&self, name: &str) -> bool {
        let mut s = self.cur;
        loop {
            let sc = &self.scopes[s];
            if let Some(i) = sc.find(name) {
                if sc.decls[i].kind != BindKind::Internal {
                    return true;
                }
            }
            if sc.kind == ScopeKind::Function && !sc.is_arrow {
                return false;
            }
            if matches!(sc.kind, ScopeKind::Script | ScopeKind::Module | ScopeKind::Eval) {
                return false;
            }
            match sc.parent {
                Some(p) => s = p,
                None => return false,
            }
        }
    }
}
