// Name resolution for the language server's navigation: which definition
// each name refers to, found by walking the syntax (so it holds even where
// type checking stopped at an error).

use crate::ast::*;
use crate::builtins::BUILTINS;
use crate::source::Span;
use std::collections::{HashMap, HashSet};

#[derive(Clone, Debug)]
pub struct RDef {
    pub name: String,
    pub span: Span,
    /// a member of a `module` (its uses are not tracked)
    pub member: bool,
    /// an extern declaration
    pub external: bool,
}

#[derive(Default, Debug)]
pub struct Resolution {
    pub defs: Vec<RDef>,
    pub uses: Vec<(Span, usize)>,
    /// a top-level name defined again: (span, the first definition)
    pub redefs: Vec<(Span, usize)>,
    pub ctor_uses: Vec<(Span, String)>,
    pub type_uses: Vec<(Span, String)>,
    pub builtin_uses: Vec<(Span, String)>,
    /// qualified library names (`List.len`), for documentation
    pub qual_builtin_uses: Vec<(Span, String)>,
    pub unbound_uses: Vec<(Span, String)>,
}

struct R {
    out: Resolution,
    scopes: Vec<HashMap<String, usize>>,
    globals: HashMap<String, usize>,
    builtins: HashSet<&'static str>,
    /// top-level definitions made ahead, by the span that introduces them
    prebound: HashMap<(usize, usize), usize>,
}

/// The names a pattern introduces, with their spans (no other effect).
fn binding_sites(p: &Pat, out: &mut Vec<(String, Span)>) {
    match &p.kind {
        PatKind::Var(n) => out.push((n.clone(), p.span)),
        PatKind::Ctor(_, _, args) => args.iter().for_each(|a| binding_sites(a, out)),
        PatKind::Tuple(ps) => ps.iter().for_each(|x| binding_sites(x, out)),
        PatKind::Or(alts) => {
            if let Some(a) = alts.first() {
                binding_sites(a, out);
            }
        }
        PatKind::List(es) => {
            for e in es {
                match e {
                    ListPatElem::Pat(x) => binding_sites(x, out),
                    ListPatElem::Star(Some(n), sp) => out.push((n.clone(), *sp)),
                    ListPatElem::Star(None, _) => {}
                }
            }
        }
        PatKind::Record(_, _, _, fs) => {
            for (f, fsp, sub) in fs {
                match sub {
                    Some(x) => binding_sites(x, out),
                    None => out.push((f.clone(), *fsp)),
                }
            }
        }
        PatKind::As(x, n, nsp) => {
            binding_sites(x, out);
            out.push((n.clone(), *nsp));
        }
        _ => {}
    }
}

pub fn resolve(prog: &Program) -> Resolution {
    let mut r = R {
        out: Resolution::default(),
        scopes: Vec::new(),
        globals: HashMap::new(),
        builtins: BUILTINS.iter().filter(|b| !b.name.contains('.')).map(|b| b.name).collect(),
        prebound: HashMap::new(),
    };
    r.program(&prog.decls);
    r.out
}

impl R {
    fn def(&mut self, name: &str, span: Span, member: bool, external: bool) -> usize {
        if let Some(&d) = self.prebound.get(&(span.lo, span.hi)) {
            return d;
        }
        // at the top level a name is one symbol: a redefinition is another
        // mention of the first
        if self.scopes.is_empty() && !member {
            if let Some(&d) = self.globals.get(name) {
                self.out.redefs.push((span, d));
                return d;
            }
        }
        self.out.defs.push(RDef { name: name.to_string(), span, member, external });
        self.out.defs.len() - 1
    }

    fn bind(&mut self, name: &str, d: usize) {
        match self.scopes.last_mut() {
            Some(s) => {
                s.insert(name.to_string(), d);
            }
            None => {
                self.globals.insert(name.to_string(), d);
            }
        }
    }

    fn lookup(&self, name: &str) -> Option<usize> {
        for s in self.scopes.iter().rev() {
            if let Some(d) = s.get(name) {
                return Some(*d);
            }
        }
        self.globals.get(name).copied()
    }

    fn program(&mut self, decls: &[Decl]) {
        // externs and types are known everywhere
        for d in decls {
            if let Decl::Extern(e) = d {
                let id = self.def(&e.name, e.span, false, true);
                self.globals.insert(e.name.clone(), id);
            }
        }
        for d in decls {
            match d {
                Decl::Type(t) => self.type_body(&t.body),
                Decl::Extern(e) => self.type_expr(&e.ty),
                _ => {}
            }
        }
        // every top-level name is in scope everywhere at the top level
        for d in decls {
            if let Decl::Let(l) = d {
                if l.active.is_some() {
                    continue;
                }
                let mut sites = Vec::new();
                match &l.pat.kind {
                    PatKind::Var(n) => sites.push((n.clone(), l.name_span)),
                    _ => binding_sites(&l.pat, &mut sites),
                }
                for (n, sp) in sites {
                    let id = self.def(&n, sp, false, false);
                    self.globals.entry(n).or_insert(id);
                    self.prebound.insert((sp.lo, sp.hi), id);
                }
            }
        }
        let groups = crate::check_decl::recursive_groups(decls);
        let mut done: HashSet<usize> = HashSet::new();
        for (i, d) in decls.iter().enumerate() {
            match d {
                Decl::Let(l) => {
                    if done.contains(&i) {
                        continue;
                    }
                    match groups.get(&i) {
                        Some(g) => {
                            // a recursive group: all its names first
                            let mut ids = Vec::new();
                            for &j in g {
                                done.insert(j);
                                if let Decl::Let(lj) = &decls[j] {
                                    if let PatKind::Var(n) = &lj.pat.kind {
                                        let id = self.def(n, lj.name_span, false, false);
                                        self.globals.insert(n.clone(), id);
                                        ids.push(Some(id));
                                        continue;
                                    }
                                }
                                ids.push(None);
                            }
                            for &j in g {
                                if let Decl::Let(lj) = &decls[j] {
                                    self.let_body(lj);
                                }
                            }
                        }
                        None => self.let_decl(l, false),
                    }
                }
                Decl::Expr(e) => self.expr(e),
                Decl::Assign(_, _, e, _) => self.expr(e),
                Decl::Module(_, _, ds) => {
                    // members are reached as `M.x`, not by their bare names
                    for d in ds {
                        if let Decl::Let(l) = d {
                            self.let_parts(l, true);
                        }
                    }
                }
                _ => {}
            }
        }
    }

    /// A `let`: its value, then its names (a function sees itself).
    fn let_decl(&mut self, l: &LetDecl, member: bool) {
        self.let_parts(l, member);
    }

    fn let_parts(&mut self, l: &LetDecl, member: bool) {
        if l.active.is_some() {
            self.let_body(l);
            return;
        }
        match &l.pat.kind {
            PatKind::Var(n) if !l.params.is_empty() => {
                let id = self.def(n, l.name_span, member, false);
                if !member {
                    self.bind(n, id);
                }
                self.let_body(l);
            }
            PatKind::Var(n) => {
                self.let_body(l);
                let id = self.def(n, l.name_span, member, false);
                if !member {
                    self.bind(n, id);
                }
            }
            _ => {
                self.let_body(l);
                let mut binds = Vec::new();
                self.pattern(&l.pat, &mut binds, true);
                for (n, id) in binds {
                    self.bind(&n, id);
                }
            }
        }
    }

    fn let_body(&mut self, l: &LetDecl) {
        self.scopes.push(HashMap::new());
        for p in &l.params {
            let mut binds = Vec::new();
            self.pattern(p, &mut binds, true);
            for (n, id) in binds {
                self.bind(&n, id);
            }
        }
        self.expr(&l.value);
        self.scopes.pop();
    }

    fn type_body(&mut self, b: &TypeBody) {
        match b {
            TypeBody::Sum(vs) => {
                for v in vs {
                    for a in &v.args {
                        self.type_expr(a);
                    }
                }
            }
            TypeBody::Record(fs) => {
                for (_, _, t) in fs {
                    self.type_expr(t);
                }
            }
            TypeBody::Opaque(t) => self.type_expr(t),
        }
    }

    fn type_expr(&mut self, t: &TypeExpr) {
        match &t.kind {
            TypeKind::Con(path, name, args) => {
                if name.starts_with(|c: char| c.is_ascii_uppercase()) {
                    let full = if path.is_empty() { name.clone() } else { format!("{}.{}", path.join("."), name) };
                    self.out.type_uses.push((Span::new(t.span.lo, t.span.lo + full.len()), full));
                }
                for a in args {
                    self.type_expr(a);
                }
            }
            TypeKind::Fun(a, _, r) => {
                self.type_expr(a);
                self.type_expr(r);
            }
            TypeKind::Tuple(ts) => {
                for x in ts {
                    self.type_expr(x);
                }
            }
            TypeKind::Measured(b, _) => self.type_expr(b),
            TypeKind::Var(_) => {}
        }
    }

    /// The names a pattern binds (as new definitions), recording what it mentions.
    fn pattern(&mut self, p: &Pat, binds: &mut Vec<(String, usize)>, in_let: bool) {
        match &p.kind {
            PatKind::Var(n) => {
                let id = self.def(n, p.span, false, false);
                binds.push((n.clone(), id));
            }
            PatKind::Ctor(path, n, args) => {
                if path.is_empty() {
                    self.out.ctor_uses.push((Span::new(p.span.lo, p.span.lo + n.len()), n.clone()));
                }
                for a in args {
                    self.pattern(a, binds, in_let);
                }
            }
            PatKind::Tuple(ps) => {
                for x in ps {
                    self.pattern(x, binds, in_let);
                }
            }
            PatKind::Or(alts) => {
                // the first alternative's names are the ones in scope
                for (i, a) in alts.iter().enumerate() {
                    let mut b = Vec::new();
                    self.pattern(a, &mut b, in_let);
                    if i == 0 {
                        binds.extend(b);
                    }
                }
            }
            PatKind::List(es) => {
                for e in es {
                    match e {
                        ListPatElem::Pat(x) => self.pattern(x, binds, in_let),
                        ListPatElem::Star(Some(n), sp) => {
                            let id = self.def(n, Span::new(sp.hi - n.len(), sp.hi), false, false);
                            binds.push((n.clone(), id));
                        }
                        ListPatElem::Star(None, _) => {}
                    }
                }
            }
            PatKind::Record(path, n, nsp, fields) => {
                if path.is_empty() && !in_let {
                    self.out.type_uses.push((*nsp, n.clone()));
                }
                for (f, fsp, sub) in fields {
                    match sub {
                        Some(x) => self.pattern(x, binds, in_let),
                        None => {
                            let id = self.def(f, *fsp, false, false);
                            binds.push((f.clone(), id));
                        }
                    }
                }
            }
            PatKind::As(inner, n, nsp) => {
                let id = self.def(n, *nsp, false, false);
                binds.push((n.clone(), id));
                self.pattern(inner, binds, in_let);
            }
            _ => {}
        }
    }

    fn with_binds(&mut self, binds: Vec<(String, usize)>) {
        for (n, id) in binds {
            self.bind(&n, id);
        }
    }

    fn expr(&mut self, e: &Expr) {
        match &e.kind {
            ExprKind::Var(n) => match self.lookup(n) {
                Some(d) => {
                    if !self.out.defs[d].member {
                        self.out.uses.push((e.span, d));
                    }
                }
                None => {
                    if self.builtins.contains(n.as_str()) {
                        self.out.builtin_uses.push((e.span, n.clone()));
                    } else {
                        self.out.unbound_uses.push((e.span, n.clone()));
                    }
                }
            },
            ExprKind::Ctor(path, n) => {
                if path.is_empty() {
                    self.out.ctor_uses.push((e.span, n.clone()));
                }
            }
            ExprKind::Qual(path, n, _) => {
                let full = format!("{}.{}", path.join("."), n);
                if crate::builtins::BUILTINS.iter().any(|b| b.name == full) {
                    self.out.qual_builtin_uses.push((e.span, full));
                }
            }
            ExprKind::FStr(parts) => {
                for p in parts {
                    if let FPart::Expr(x) = p {
                        self.expr(x);
                    }
                }
            }
            ExprKind::Field(b, _, _) => self.expr(b),
            ExprKind::App(f, a) => {
                self.expr(f);
                self.expr(a);
            }
            ExprKind::Binary(_, l, r) => {
                self.expr(l);
                self.expr(r);
            }
            ExprKind::Chain(first, rest) => {
                self.expr(first);
                for (_, x) in rest {
                    self.expr(x);
                }
            }
            ExprKind::Neg(x) | ExprKind::Not(x) | ExprKind::Try(x) => self.expr(x),
            ExprKind::If(c, a, b) => {
                self.expr(c);
                self.expr(a);
                self.expr(b);
            }
            ExprKind::Match(s, arms) => {
                self.expr(s);
                for a in arms {
                    self.scopes.push(HashMap::new());
                    let mut binds = Vec::new();
                    self.pattern(&a.pat, &mut binds, false);
                    self.with_binds(binds);
                    if let Some(g) = &a.guard {
                        self.expr(g);
                    }
                    self.expr(&a.body);
                    self.scopes.pop();
                }
            }
            ExprKind::Lambda(ps, body) => {
                self.scopes.push(HashMap::new());
                for p in ps {
                    let mut binds = Vec::new();
                    self.pattern(p, &mut binds, true);
                    self.with_binds(binds);
                }
                self.expr(body);
                self.scopes.pop();
            }
            ExprKind::Block(stmts) => {
                self.scopes.push(HashMap::new());
                for s in stmts {
                    match s {
                        Stmt::Let(l) => self.let_decl(l, false),
                        Stmt::Assign(_, _, v, _) => self.expr(v),
                        Stmt::Expr(x) => self.expr(x),
                    }
                }
                self.scopes.pop();
            }
            ExprKind::Tuple(xs) | ExprKind::List(xs) => {
                for x in xs {
                    self.expr(x);
                }
            }
            ExprKind::Record(path, name, cspan, fields) => {
                if path.is_empty() {
                    self.out.type_uses.push((*cspan, name.clone()));
                }
                for (_, _, v) in fields {
                    self.expr(v);
                }
            }
            ExprKind::Update(b, fields) => {
                self.expr(b);
                for (_, v) in fields {
                    self.expr(v);
                }
            }
            ExprKind::Assign(_, _, v) => self.expr(v),
            ExprKind::Measured(x, _) => self.expr(x),
            ExprKind::Ce(_, _, items) => {
                self.scopes.push(HashMap::new());
                self.ce_items(items);
                self.scopes.pop();
            }
            _ => {}
        }
    }

    fn ce_items(&mut self, items: &[CeStmt]) {
        for it in items {
            match it {
                CeStmt::LetBang(p, e, _) => {
                    self.expr(e);
                    let mut binds = Vec::new();
                    self.pattern(p, &mut binds, false);
                    self.with_binds(binds);
                }
                CeStmt::Let(l) => self.let_decl(l, false),
                CeStmt::For(p, src, body, _) => {
                    self.expr(src);
                    self.scopes.push(HashMap::new());
                    let mut binds = Vec::new();
                    self.pattern(p, &mut binds, false);
                    self.with_binds(binds);
                    self.ce_items(body);
                    self.scopes.pop();
                }
                CeStmt::Assign(_, _, v) => self.expr(v),
                CeStmt::DoBang(e, _) | CeStmt::Return(e, _) | CeStmt::ReturnBang(e, _) | CeStmt::Yield(e, _) | CeStmt::YieldBang(e, _) => self.expr(e),
            }
        }
    }
}
