// Shadowing in one Python scope. A Python function (or the module) has one
// namespace, so a binding in a nested block or `case` arm that reuses the
// name of an enclosing binding would overwrite it; when that enclosing
// binding is read somewhere, the nested one gets a fresh name instead.

use crate::ast::*;
use crate::source::Span;
use std::collections::{HashMap, HashSet};

pub type Key = (usize, usize);

fn key(s: Span) -> Key {
    (s.lo, s.hi)
}

/// The names a pattern binds, with the spans that define them.
pub fn pat_sites(p: &Pat, out: &mut Vec<(String, Span)>) {
    match &p.kind {
        PatKind::Var(n) => out.push((n.clone(), p.span)),
        PatKind::Tuple(ps) | PatKind::Or(ps) => ps.iter().for_each(|x| pat_sites(x, out)),
        PatKind::Ctor(_, _, args) => args.iter().for_each(|x| pat_sites(x, out)),
        PatKind::List(es) => {
            for e in es {
                match e {
                    ListPatElem::Pat(x) => pat_sites(x, out),
                    ListPatElem::Star(Some(n), sp) => out.push((n.clone(), Span::new(sp.hi - n.len(), sp.hi))),
                    ListPatElem::Star(None, _) => {}
                }
            }
        }
        PatKind::Record(_, _, _, fs) => {
            for (f, fspan, sub) in fs {
                match sub {
                    Some(x) => pat_sites(x, out),
                    None => out.push((f.clone(), *fspan)),
                }
            }
        }
        PatKind::As(x, n, nsp) => {
            out.push((n.clone(), *nsp));
            pat_sites(x, out);
        }
        _ => {}
    }
}

/// The names a `let` binds in its block.
pub fn let_sites(l: &LetDecl, out: &mut Vec<(String, Span)>) {
    if l.active.is_some() {
        return;
    }
    match &l.pat.kind {
        PatKind::Var(n) => out.push((n.clone(), l.name_span)),
        _ => pat_sites(&l.pat, out),
    }
}

pub struct Shadow<'a> {
    /// definitions read somewhere
    pub referenced: &'a HashSet<Key>,
    /// every read: where, the name, and the definition read
    pub uses: &'a [(Span, String, Key)],
    /// the binding sites that take a fresh name, and the name
    pub renamed: HashMap<Key, String>,
    /// the Python names the module defines at the top level
    pub module_names: HashSet<String>,
    /// names in use in the Python function being walked
    taken: HashSet<String>,
}

type Scope = Vec<(String, bool)>;

impl<'a> Shadow<'a> {
    pub fn new(referenced: &'a HashSet<Key>, uses: &'a [(Span, String, Key)]) -> Shadow<'a> {
        Shadow { referenced, uses, renamed: HashMap::new(), module_names: HashSet::new(), taken: HashSet::new() }
    }

    fn scope(&self, sites: &[(String, Span)]) -> Scope {
        sites.iter().map(|(n, s)| (n.clone(), self.referenced.contains(&key(*s)))).collect()
    }

    /// Rename the sites whose names an enclosing scope still needs (the
    /// alternatives of an or-pattern share a name).
    fn check(&mut self, sites: &[(String, Span)], stack: &[Scope]) {
        let mut given: Vec<(String, String)> = Vec::new();
        for (n, s) in sites {
            if !stack.iter().any(|sc| sc.iter().any(|(m, r)| m == n && *r)) {
                continue;
            }
            let py = match given.iter().find(|(m, _)| m == n) {
                Some((_, py)) => py.clone(),
                None => {
                    let py = self.fresh(n);
                    given.push((n.clone(), py.clone()));
                    py
                }
            };
            self.renamed.insert(key(*s), py);
        }
    }

    /// `_name`, `_name2`, … : the first not in use.
    fn fresh(&mut self, n: &str) -> String {
        let base = format!("_{}", crate::lower::mangle(n));
        let mut k = 1;
        loop {
            let cand = if k == 1 { base.clone() } else { format!("{}{}", base, k) };
            if !self.taken.contains(&cand) && !self.module_names.contains(&cand) {
                self.taken.insert(cand.clone());
                return cand;
            }
            k += 1;
        }
    }

    /// The module: its top-level names make the outermost scope.
    pub fn program(&mut self, decls: &[Decl]) {
        let mut sites = Vec::new();
        top_sites(decls, &mut sites);
        self.module_names = sites.iter().map(|(n, _)| crate::lower::mangle(n)).collect();
        let mut taken = HashSet::new();
        module_bound(decls, &mut taken);
        self.taken = taken;
        let mut stack = vec![self.scope(&sites)];
        self.decls(decls, &mut stack);
    }

    fn decls(&mut self, decls: &[Decl], stack: &mut Vec<Scope>) {
        for d in decls {
            match d {
                Decl::Let(l) if l.active.is_some() || !l.params.is_empty() => self.function(&l.params, &l.value),
                Decl::Let(l) => {
                    if self.lifted(l, stack) {
                        self.function(&[], &l.value);
                    } else {
                        self.expr(&l.value, stack);
                    }
                }
                Decl::Expr(e) => self.expr(e, stack),
                Decl::Assign(_, _, e, _) => self.expr(e, stack),
                Decl::Module(_, _, ds) => self.decls(ds, stack),
                _ => {}
            }
        }
    }

    /// A top-level value whose evaluation binds a top-level name runs in a
    /// function of its own.
    fn lifted(&self, l: &LetDecl, stack: &[Scope]) -> bool {
        let mut names = Vec::new();
        inner_sites(&l.value, &mut names);
        names.iter().any(|(n, _)| stack[0].iter().any(|(m, _)| m == n))
    }

    /// A Python function: its parameters and body (a body block shares the
    /// parameters' scope).
    pub fn function(&mut self, params: &[Pat], body: &Expr) {
        let mut sites = Vec::new();
        for p in params {
            pat_sites(p, &mut sites);
        }
        // the variables it reads from outside: a binding of that name
        // here would make Python take them for its own
        let lo = params.iter().map(|p| p.span.lo).min().unwrap_or(body.span.lo).min(body.span.lo);
        let hi = body.span.hi;
        let mut outer: Scope = Vec::new();
        for (u, n, d) in self.uses {
            if u.lo >= body.span.lo && u.hi <= hi && !(d.0 >= lo && d.1 <= hi) && !outer.iter().any(|(m, _)| m == n) {
                outer.push((n.clone(), true));
            }
        }
        // the names this function binds are in use in it
        let mut bound = sites.clone();
        inner_sites(body, &mut bound);
        let saved = std::mem::replace(&mut self.taken, bound.iter().map(|(n, _)| crate::lower::mangle(n)).collect());
        match &body.kind {
            ExprKind::Block(stmts) => {
                for s in stmts {
                    if let Stmt::Let(l) = s {
                        let_sites(l, &mut sites);
                    }
                }
                let mut base = self.scope(&sites);
                base.extend(outer.clone());
                let mut stack = vec![base];
                for s in stmts {
                    // (a `let` of the body taking the name of a variable it
                    // reads from outside renames too)
                    if let Stmt::Let(l) = s {
                        let mut lets = Vec::new();
                        let_sites(l, &mut lets);
                        self.check(&lets, &[outer.clone()]);
                    }
                    self.stmt(s, &mut stack);
                }
            }
            _ => {
                let mut base = self.scope(&sites);
                base.extend(outer);
                let mut stack = vec![base];
                self.expr(body, &mut stack);
            }
        }
        self.taken = saved;
    }

    fn stmt(&mut self, s: &Stmt, stack: &mut Vec<Scope>) {
        match s {
            Stmt::Let(l) if !l.params.is_empty() => self.function(&l.params, &l.value),
            Stmt::Let(l) => self.expr(&l.value, stack),
            Stmt::Assign(_, _, e, _) | Stmt::Expr(e) => self.expr(e, stack),
        }
    }

    fn expr(&mut self, e: &Expr, stack: &mut Vec<Scope>) {
        match &e.kind {
            ExprKind::Block(stmts) => {
                let mut sites = Vec::new();
                for s in stmts {
                    if let Stmt::Let(l) = s {
                        let_sites(l, &mut sites);
                    }
                }
                let n = stack.len();
                stack.push(self.scope(&sites));
                for s in stmts {
                    if let Stmt::Let(l) = s {
                        let mut lets = Vec::new();
                        let_sites(l, &mut lets);
                        self.check(&lets, &stack[..n]);
                    }
                    self.stmt(s, stack);
                }
                stack.pop();
            }
            ExprKind::Match(s, arms) => {
                self.expr(s, stack);
                for a in arms {
                    let mut sites = Vec::new();
                    pat_sites(&a.pat, &mut sites);
                    self.check(&sites, stack);
                    stack.push(self.scope(&sites));
                    if let Some(g) = &a.guard {
                        self.expr(g, stack);
                    }
                    self.expr(&a.body, stack);
                    stack.pop();
                }
            }
            ExprKind::Lambda(ps, b) => self.function(ps, b),
            _ => each_child(e, &mut |c| self.expr(c, stack)),
        }
    }
}

/// The names bound at the module's own level: top-level declarations and
/// what their statements bind.
fn module_bound(decls: &[Decl], out: &mut HashSet<String>) {
    for d in decls {
        match d {
            Decl::Let(l) => {
                let mut sites = Vec::new();
                let_sites(l, &mut sites);
                if l.params.is_empty() && l.active.is_none() {
                    inner_sites(&l.value, &mut sites);
                }
                out.extend(sites.into_iter().map(|(n, _)| crate::lower::mangle(&n)));
            }
            Decl::Expr(e) | Decl::Assign(_, _, e, _) => {
                let mut sites = Vec::new();
                inner_sites(e, &mut sites);
                out.extend(sites.into_iter().map(|(n, _)| crate::lower::mangle(&n)));
            }
            Decl::Module(_, _, ds) => module_bound(ds, out),
            _ => {}
        }
    }
}

/// The names bound at the top level.
fn top_sites(decls: &[Decl], out: &mut Vec<(String, Span)>) {
    for d in decls {
        if let Decl::Let(l) = d {
            let_sites(l, out);
        }
    }
}

/// The names an expression binds in its own Python scope: lets of its
/// blocks (a nested function by its name) and `case` variables, not the
/// insides of functions.
pub fn inner_sites(e: &Expr, out: &mut Vec<(String, Span)>) {
    match &e.kind {
        ExprKind::Block(stmts) => {
            for s in stmts {
                match s {
                    Stmt::Let(l) => {
                        let_sites(l, out);
                        if l.params.is_empty() {
                            inner_sites(&l.value, out);
                        }
                    }
                    Stmt::Assign(_, _, x, _) | Stmt::Expr(x) => inner_sites(x, out),
                }
            }
        }
        ExprKind::Match(s, arms) => {
            inner_sites(s, out);
            for a in arms {
                pat_sites(&a.pat, out);
                if let Some(g) = &a.guard {
                    inner_sites(g, out);
                }
                inner_sites(&a.body, out);
            }
        }
        ExprKind::Lambda(..) => {}
        _ => each_child(e, &mut |c| inner_sites(c, out)),
    }
}

/// Each direct subexpression (computation expressions not entered).
pub fn each_child(e: &Expr, f: &mut dyn FnMut(&Expr)) {
    match &e.kind {
        ExprKind::FStr(parts) => {
            for p in parts {
                if let FPart::Expr(x) = p {
                    f(x);
                }
            }
        }
        ExprKind::Field(x, _, _) | ExprKind::Neg(x) | ExprKind::Not(x) | ExprKind::Try(x) | ExprKind::Measured(x, _) | ExprKind::Assign(_, _, x) => f(x),
        ExprKind::App(a, b) | ExprKind::Binary(_, a, b) => {
            f(a);
            f(b);
        }
        ExprKind::Chain(a, rest) => {
            f(a);
            for (_, x) in rest {
                f(x);
            }
        }
        ExprKind::If(c, a, b) => {
            f(c);
            f(a);
            f(b);
        }
        ExprKind::Match(s, arms) => {
            f(s);
            for a in arms {
                if let Some(g) = &a.guard {
                    f(g);
                }
                f(&a.body);
            }
        }
        ExprKind::Lambda(_, b) => f(b),
        ExprKind::Block(stmts) => {
            for s in stmts {
                match s {
                    Stmt::Let(l) => f(&l.value),
                    Stmt::Assign(_, _, x, _) | Stmt::Expr(x) => f(x),
                }
            }
        }
        ExprKind::Tuple(xs) | ExprKind::List(xs) => xs.iter().for_each(|x| f(x)),
        ExprKind::Record(_, _, _, fs) => fs.iter().for_each(|(_, _, x)| f(x)),
        ExprKind::Update(b, fs) => {
            f(b);
            for (_, x) in fs {
                f(x);
            }
        }
        _ => {}
    }
}

/// The names a function binds by parameter or `let` (`case` variables
/// left out).
pub fn fn_bound(params: &[Pat], body: &Expr) -> HashSet<String> {
    let mut sites = Vec::new();
    for p in params {
        pat_sites(p, &mut sites);
    }
    let_names(body, &mut sites);
    sites.into_iter().map(|(n, _)| n).collect()
}

/// The names the `let`s of an expression's blocks bind (not inside
/// functions).
fn let_names(e: &Expr, out: &mut Vec<(String, Span)>) {
    match &e.kind {
        ExprKind::Block(stmts) => {
            for s in stmts {
                match s {
                    Stmt::Let(l) => {
                        let_sites(l, out);
                        if l.params.is_empty() {
                            let_names(&l.value, out);
                        }
                    }
                    Stmt::Assign(_, _, x, _) | Stmt::Expr(x) => let_names(x, out),
                }
            }
        }
        ExprKind::Lambda(..) => {}
        _ => each_child(e, &mut |c| let_names(c, out)),
    }
}

/// The names a computation expression's items bind.
pub fn ce_bound(items: &[CeStmt]) -> HashSet<String> {
    fn walk(items: &[CeStmt], out: &mut Vec<(String, Span)>) {
        for it in items {
            match it {
                CeStmt::LetBang(p, e, _) => {
                    pat_sites(p, out);
                    let_names(e, out);
                }
                CeStmt::Let(l) => {
                    let_sites(l, out);
                    if l.params.is_empty() {
                        let_names(&l.value, out);
                    }
                }
                CeStmt::For(p, e, body, _) => {
                    pat_sites(p, out);
                    let_names(e, out);
                    walk(body, out);
                }
                CeStmt::DoBang(e, _) | CeStmt::Return(e, _) | CeStmt::ReturnBang(e, _) | CeStmt::Yield(e, _) | CeStmt::YieldBang(e, _) | CeStmt::Assign(_, _, e) => let_names(e, out),
            }
        }
    }
    let mut sites = Vec::new();
    walk(items, &mut sites);
    sites.into_iter().map(|(n, _)| n).collect()
}
