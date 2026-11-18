// Computation expressions and active-pattern cases.

use crate::ast::*;
use crate::check_expr::*;
use crate::diag::Diag;
use crate::infer::*;
use crate::source::Span;
use crate::types::*;

type R<T> = Result<T, Diag>;

#[derive(Clone, Copy, PartialEq)]
enum CeKind {
    Async,
    Seq,
    Result,
    Option,
}

impl Checker {
    pub fn infer_ce(&mut self, path: &[String], name: &str, items: &[CeStmt], span: Span) -> R<Ty> {
        let kind = if path.is_empty() {
            match name {
                "async" => Some(CeKind::Async),
                "seq" => Some(CeKind::Seq),
                "result" => Some(CeKind::Result),
                "option" => Some(CeKind::Option),
                _ => None,
            }
        } else {
            None
        };
        let Some(kind) = kind else {
            return self.infer_user_ce(path, name, items, span);
        };
        self.push_scope();
        let r = self.infer_ce_items(kind, items, span);
        self.pop_scope();
        let t = r?;
        if kind == CeKind::Async {
            let l = self.st.label_of("async");
            self.perform(&Eff::label(l), span);
        }
        Ok(t)
    }

    fn infer_ce_items(&mut self, kind: CeKind, items: &[CeStmt], span: Span) -> R<Ty> {
        let ret = self.st.fresh();
        let err = self.st.fresh();
        let wrap = |k: CeKind, t: Ty, e: Ty| -> Ty {
            match k {
                CeKind::Async => Ty::Con("Async".into(), vec![t]),
                CeKind::Seq => Ty::Con("Seq".into(), vec![t]),
                CeKind::Result => Ty::Con("Result".into(), vec![t, e]),
                CeKind::Option => Ty::Con("Option".into(), vec![t]),
            }
        };
        let kw_name = match kind {
            CeKind::Async => "async",
            CeKind::Seq => "seq",
            CeKind::Result => "result",
            CeKind::Option => "option",
        };
        // the value of the block
        let mut has_return = false;
        self.ce_body(kind, items, &ret, &err, &mut has_return, kw_name, span, true)?;
        if kind != CeKind::Seq {
            match items.last() {
                Some(CeStmt::Return(..)) | Some(CeStmt::ReturnBang(..)) => {}
                // a block ending in a unit action produces unit
                Some(CeStmt::DoBang(..)) => {
                    self.unify_at(&ret, &t_unit(), span)?;
                }
                Some(CeStmt::Let(l)) if matches!(l.pat.kind, PatKind::Wild) => {
                    self.unify_at(&ret, &t_unit(), span)?;
                }
                _ => {
                    let article = if matches!(kind, CeKind::Async | CeKind::Option) { "an" } else { "a" };
                    return Err(Diag::error(format!("{} `{}` block must end with `return`", article, kw_name), span));
                }
            }
        }
        Ok(wrap(kind, ret, err))
    }

    fn ce_body(&mut self, kind: CeKind, items: &[CeStmt], ret: &Ty, err: &Ty, has_return: &mut bool, kw: &str, ce_span: Span, top: bool) -> R<()> {
        let wrap1 = |k: CeKind, t: Ty, e: Ty| -> Ty {
            match k {
                CeKind::Async => Ty::Con("Async".into(), vec![t]),
                CeKind::Seq => Ty::Con("Seq".into(), vec![t]),
                CeKind::Result => Ty::Con("Result".into(), vec![t, e]),
                CeKind::Option => Ty::Con("Option".into(), vec![t]),
            }
        };
        for it in items {
            // `return` ends a block (found as the items are read)
            if top && matches!(it, CeStmt::Return(..) | CeStmt::ReturnBang(..)) && !std::ptr::eq(it, items.last().unwrap()) {
                let which = if matches!(it, CeStmt::ReturnBang(..)) { "return!" } else { "return" };
                return Err(Diag::error(format!("`{}` must be the final item", which), ce_span));
            }
            match it {
                CeStmt::LetBang(..) | CeStmt::DoBang(..) if kind == CeKind::Seq => {
                    return Err(Diag::error("only `yield`, `yield!`, `let`, and `for` are allowed in a `seq` block", ce_span));
                }
                CeStmt::LetBang(p, e, _) => {
                    let te = self.infer(e)?;
                    let a = self.st.fresh();
                    let want = wrap1(kind, a.clone(), err.clone());
                    self.unify_at(&want, &te, e.span)?;
                    self.check_pat(p, &a, false)?;
                }
                // (what an action produces is dropped, unless it ends the
                // block, which then produces unit)
                CeStmt::DoBang(e, _) => {
                    let te = self.infer(e)?;
                    let a = self.st.fresh();
                    let want = wrap1(kind, a.clone(), err.clone());
                    self.unify_at(&want, &te, e.span)?;
                    if top && std::ptr::eq(it, items.last().unwrap()) {
                        self.unify_at(&a, &t_unit(), e.span)?;
                    }
                }
                // the final action of a block that does not `return` is unit
                // (it is read as an item first, then again as that action)
                CeStmt::Let(l) if top && kind != CeKind::Seq && matches!(l.pat.kind, PatKind::Wild) && std::ptr::eq(it, items.last().unwrap()) => {
                    let t = self.infer_let_value(l)?;
                    self.bind_let_pattern_as(l, &t, true)?;
                    let t = self.infer_let_value(l)?;
                    self.unify_at(&t_unit(), &t, l.value.span)?;
                }
                // (a builder's `let` binds one type, as a lambda would)
                CeStmt::Let(l) => {
                    let t = self.infer_let_value(l)?;
                    self.bind_let_pattern_as(l, &t, true)?;
                }
                CeStmt::Assign(n, nspan, v) => {
                    self.infer_assign(n, *nspan, v, nspan.to(v.span))?;
                }
                CeStmt::Return(e, _) => {
                    if kind == CeKind::Seq {
                        return Err(Diag::error("only `yield`, `yield!`, `let`, and `for` are allowed in a `seq` block", ce_span));
                    }
                    let te = self.infer(e)?;
                    self.unify_at(ret, &te, e.span)?;
                    *has_return = true;
                }
                CeStmt::ReturnBang(e, _) => {
                    if kind == CeKind::Seq {
                        return Err(Diag::error("only `yield`, `yield!`, `let`, and `for` are allowed in a `seq` block", ce_span));
                    }
                    let te = self.infer(e)?;
                    let want = wrap1(kind, ret.clone(), err.clone());
                    self.unify_at(&want, &te, e.span)?;
                    *has_return = true;
                }
                CeStmt::Yield(e, _) => {
                    if kind != CeKind::Seq {
                        let article = if matches!(kind, CeKind::Async | CeKind::Option) { "an" } else { "a" };
                        return Err(Diag::error(format!("`yield` is not allowed in {} `{}` block", article, kw), ce_span));
                    }
                    let te = self.infer(e)?;
                    self.unify_at(ret, &te, e.span)?;
                }
                CeStmt::YieldBang(e, _) => {
                    if kind != CeKind::Seq {
                        let article = if matches!(kind, CeKind::Async | CeKind::Option) { "an" } else { "a" };
                        return Err(Diag::error(format!("`yield` is not allowed in {} `{}` block", article, kw), ce_span));
                    }
                    let te = self.infer(e)?;
                    let want = Ty::Con("Seq".into(), vec![ret.clone()]);
                    self.unify_at(&want, &te, e.span)?;
                }
                CeStmt::For(p, src, body, _) => {
                    let ts = self.infer(src)?;
                    let elem = self.st.fresh();
                    let rs = self.st.shallow(&ts);
                    let coll = match &rs {
                        Ty::Con(n, _) if n == "Seq" || n == "Set" => n.clone(),
                        _ => "List".to_string(),
                    };
                    let want = Ty::Con(coll, vec![elem.clone()]);
                    self.unify_at(&want, &ts, src.span)?;
                    self.push_scope();
                    let r = (|| -> R<()> {
                        self.check_pat(p, &elem, false)?;
                        self.ce_body(kind, body, ret, err, has_return, kw, ce_span, false)
                    })();
                    self.pop_scope();
                    r?;
                }
            }
        }
        Ok(())
    }

    /// A user builder module: desugar to `M.bind`/`M.return_` calls.
    fn infer_user_ce(&mut self, path: &[String], name: &str, items: &[CeStmt], span: Span) -> R<Ty> {
        // the block's shape: binders lead somewhere, `return` comes last
        let n = items.len();
        for (i, it) in items.iter().enumerate() {
            let last = i + 1 == n;
            match it {
                CeStmt::LetBang(_, e, _) if last => return Err(Diag::error("`let!` must be followed by another item", e.span)),
                // (an expression item is a `let _` too)
                CeStmt::Let(l) if last => return Err(Diag::error("a `let` must be followed by another item", l.value.span)),
                CeStmt::Return(e, _) if !last => return Err(Diag::error("`return` must be the final item", e.span)),
                _ => {}
            }
        }
        let mut full = path.to_vec();
        full.push(name.to_string());
        let e = desugar_user_ce(&full, items, span);
        self.infer(&e)
    }

    pub fn check_active_case(&mut self, n: &str, args: &[Pat], t: &Ty, span: Span, binds: &mut Vec<(String, Ty, usize)>) -> Option<R<()>> {
        let tag = self.active_cases.get(n)?.clone();
        let info = self.active_patterns.get(&tag)?.clone();
        let name_span = Span::new(span.lo, span.lo + n.len());
        Some((|| -> R<()> {
            let recog = self.lookup_local(&tag).map(|l| l.scheme.clone());
            let Some(recog) = recog else { return Ok(()) };
            let mut rt = self.st.instantiate(&recog);
            // (a partial pattern's parameters come before the match input)
            let extra = if info.1 { self.active_params.get(&tag).copied().unwrap_or(0) } else { 0 };
            let mut param_tys = Vec::new();
            for _ in 0..extra {
                if let Ty::Fun(a, _, r) = self.st.resolve(&rt) {
                    param_tys.push(*a);
                    rt = *r;
                }
            }
            let mut failed = false;
            let (input, res) = match self.st.resolve(&rt) {
                Ty::Fun(a, _, r) => (*a, *r),
                // a recognizer that did not check: its cases are read
                // straight off the value, as its choice type
                other => match self.active_ctors.get(n).cloned() {
                    Some(c) if !info.1 => {
                        failed = true;
                        let mut inst = Inst::default();
                        let params: Vec<Ty> = (0..c.params).map(|i| self.st.inst_ty(&Ty::Gen(i), &mut inst)).collect();
                        let choice = Ty::Con(c.type_name.clone(), params);
                        (choice.clone(), choice)
                    }
                    _ => (self.st.fresh(), other),
                },
            };
            let res = self.st.resolve(&res);
            // the case's arity
            let (arity, why) = if info.1 {
                match &res {
                    Ty::Con(o, _) if o == "Option" => (extra + 1, if args.len() < extra + 1 { " (an Option active pattern binds its payload — add a binder)" } else { "" }),
                    _ => (extra, if args.len() > extra { " (a bool active pattern is a predicate and binds nothing)" } else { "" }),
                }
            } else {
                (self.active_ctors.get(n).map_or(0, |c| c.args.len()), "")
            };
            if args.len() != arity {
                return Err(Diag::error(format!("active pattern `{}` expects {} argument(s) here, found {}{}", n, arity, args.len(), why), name_span));
            }
            for a in &args[..extra] {
                if !matches!(a.kind, PatKind::Var(_) | PatKind::Int(_) | PatKind::Str(_) | PatKind::Bool(_)) {
                    return Err(Diag::error(format!("an active-pattern parameter argument must be a literal or a variable (in `{}`)", n), name_span));
                }
            }
            for a in &args[extra..] {
                if !matches!(a.kind, PatKind::Var(_) | PatKind::Wild) {
                    return Err(Diag::error(format!("an active-pattern case argument must be a variable or `_` (in `{}`)", n), name_span));
                }
            }
            // the parameters' arguments are values, read like expressions
            for (a, pt) in args[..extra].iter().zip(param_tys.iter()) {
                // (read where the case's name stands)
                let Some(e) = active_param_expr(a, name_span) else { continue };
                // (the variable read there counts as no use of it: the arm
                // binds the name anew, to the value given)
                let uses = self.ide.uses.len();
                let at = self.infer(&e);
                self.ide.uses.truncate(uses);
                let at = at?;
                if let Err(err) = self.unify(pt, &at) {
                    let d = self.uerr_diag(err, pt, &at, name_span);
                    return Err(Diag::error(format!("in active pattern `{}`: {}", n, d.msg), name_span));
                }
                if let PatKind::Var(v) = &a.kind {
                    let (def, _) = self.ide.def(v, a.span, None);
                    binds.push((v.clone(), pt.clone(), def));
                }
            }
            let args = &args[extra..];
            if let Err(e) = self.unify(&input, t) {
                let d = self.uerr_diag(e, &input, t, name_span);
                // (cases read off the value mismatch like a constructor's)
                if failed {
                    return Err(d);
                }
                return Err(Diag::error(format!("in active pattern `{}`: {}", n, d.msg), name_span));
            }
            // a value nothing says more of than the recognizer does is taken
            // for its choice already made
            if !info.1 && matches!(self.st.shallow(t), Ty::Var(_)) {
                if let Ty::Con(..) = &res {
                    let _ = self.unify(t, &res);
                }
            }
            if info.1 {
                if let Ty::Con(o, targs) = &res {
                    if o == "Option" {
                        if let PatKind::Var(v) = &args[0].kind {
                            let (def, new) = self.ide.def(v, args[0].span, None);
                            if new {
                                self.ide.item(args[0].span, &targs[0], crate::ide::Doc::Def(def));
                            }
                            binds.push((v.clone(), targs[0].clone(), def));
                        }
                    }
                }
            } else if let Some(c) = self.active_ctors.get(n).cloned() {
                if let Ty::Con(_, targs) = &res {
                    let mut inst = Inst::default();
                    for (i, a) in targs.iter().enumerate() {
                        inst.t.insert(i, a.clone());
                    }
                    for (a, at) in args.iter().zip(c.args.iter()) {
                        if let PatKind::Var(v) = &a.kind {
                            let at = self.st.inst_ty(at, &mut inst);
                            let (def, new) = self.ide.def(v, a.span, None);
                            if new {
                                self.ide.item(a.span, &at, crate::ide::Doc::Def(def));
                            }
                            binds.push((v.clone(), at, def));
                        }
                    }
                }
            }
            Ok(())
        })())
    }
}

/// `M { let! x = a; return e }` => `M.bind a (fun x -> M.return_ e)`
pub fn desugar_user_ce(m: &[String], items: &[CeStmt], span: Span) -> Expr {
    // everything the desugaring makes spans the whole block
    let (path, name) = (m[..m.len() - 1].to_vec(), m[m.len() - 1].clone());
    let member = |mem: &str| -> Expr {
        let mut p = path.clone();
        p.push(name.clone());
        Expr { kind: ExprKind::Qual(p, mem.to_string(), span), span }
    };
    fn go(items: &[CeStmt], member: &dyn Fn(&str) -> Expr, span: Span) -> Expr {
        let Some(first) = items.first() else {
            return Expr { kind: ExprKind::Unit, span };
        };
        let rest = &items[1..];
        let app = |f: Expr, a: Expr| -> Expr { Expr { kind: ExprKind::App(Box::new(f), Box::new(a)), span } };
        let lambda = |p: Pat, body: Expr| -> Expr { Expr { kind: ExprKind::Lambda(vec![p], Box::new(body)), span } };
        // (the continuation's ignored argument is a parameter named `_`)
        let wild = Pat { kind: PatKind::Var("_".into()), span };
        match first {
            CeStmt::LetBang(p, e, _) => {
                let k = go(rest, member, span);
                app(app(member("bind"), e.clone()), lambda(p.clone(), k))
            }
            CeStmt::DoBang(e, _) => {
                let k = go(rest, member, span);
                app(app(member("bind"), e.clone()), lambda(wild, k))
            }
            CeStmt::Return(e, _) => app(member("return_"), e.clone()),
            CeStmt::ReturnBang(e, _) => app(member("returnFrom"), e.clone()),
            CeStmt::Yield(e, _) => {
                let y = app(member("yield_"), e.clone());
                if rest.is_empty() {
                    y
                } else {
                    let k = go(rest, member, span);
                    let d = app(member("delay"), lambda(wild, k));
                    app(app(member("combine"), y), d)
                }
            }
            CeStmt::YieldBang(e, _) => {
                let y = app(member("yieldFrom"), e.clone());
                if rest.is_empty() {
                    y
                } else {
                    let k = go(rest, member, span);
                    let d = app(member("delay"), lambda(wild, k));
                    app(app(member("combine"), y), d)
                }
            }
            // `let p = v` binds through a function applied to the value
            CeStmt::Let(l) => {
                let k = go(rest, member, span);
                app(lambda(l.pat.clone(), k), l.value.clone())
            }
            CeStmt::For(p, src, body, _) => {
                let b = go(body, member, span);
                let f = app(app(member("for_"), src.clone()), lambda(p.clone(), b));
                if rest.is_empty() {
                    f
                } else {
                    let k = go(rest, member, span);
                    let d = app(member("delay"), lambda(wild, k));
                    app(app(member("combine"), f), d)
                }
            }
            CeStmt::Assign(n, nsp, v) => {
                let k = go(rest, member, span);
                Expr { kind: ExprKind::Block(vec![Stmt::Assign(n.clone(), *nsp, v.clone(), nsp.to(v.span)), Stmt::Expr(k)]), span }
            }
        }
    }
    go(items, &member, span)
}

/// A parameter argument of an active-pattern case, as the expression it is
/// (placed at `span`).
pub fn active_param_expr(p: &Pat, span: Span) -> Option<Expr> {
    let kind = match &p.kind {
        PatKind::Var(v) => ExprKind::Var(v.clone()),
        PatKind::Int(i) => ExprKind::Int(*i),
        PatKind::Str(t) => ExprKind::Str(t.clone()),
        PatKind::Bool(b) => ExprKind::Bool(*b),
        _ => return None,
    };
    Some(Expr { kind, span })
}
