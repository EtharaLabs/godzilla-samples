// Lowering: operators, control flow, matches, lambdas, statements.

use crate::ast::*;
use crate::infer::*;
use crate::lower::*;
use crate::py::*;
use crate::source::Span;
use crate::types::*;
use std::collections::HashMap;

impl<'a> Lowerer<'a> {
    pub fn binary(&mut self, op: BinOp, l: &Expr, r: &Expr, whole: &Expr) -> PE {
        match op {
            BinOp::PipeRight => {
                let (f, mut args) = Self::spine(r);
                args.push(l);
                self.apply(f, &args, whole)
            }
            BinOp::PipeLeft => {
                let (f, mut args) = Self::spine(l);
                args.push(r);
                self.apply(f, &args, whole)
            }
            BinOp::ComposeRight | BinOp::ComposeLeft => {
                let (first, second) = if op == BinOp::ComposeRight { (l, r) } else { (r, l) };
                let saved = std::mem::take(&mut self.pre);
                let outer = self.composed(first, second);
                let pre = std::mem::replace(&mut self.pre, saved);
                if pre.is_empty() {
                    return PE::Lambda(vec!["_pf_x".into()], Box::new(outer));
                }
                // stages that need statements: a def of its own
                let fname = self.new_fn();
                self.fn_stack.push(FnFrame { depth: self.depth() + 1, bound: ["_pf_x".to_string()].into_iter().collect(), ..Default::default() });
                let saved = std::mem::take(&mut self.pre);
                let outer = self.composed(first, second);
                let mut body = std::mem::replace(&mut self.pre, saved);
                body.push(PS::Return(Some(outer)));
                self.fn_stack.pop();
                self.pre.push(PS::Def { name: fname.clone(), params: vec!["_pf_x".into()], body, is_async: false, ret: None });
                name(&fname)
            }
            BinOp::And => {
                let a = self.expr(l);
                let b = self.expr(r);
                PE::And(Box::new(a), Box::new(b))
            }
            BinOp::Or => {
                let a = self.expr(l);
                let b = self.expr(r);
                PE::Or(Box::new(a), Box::new(b))
            }
            _ => {
                let a = self.expr(l);
                let b = self.expr(r);
                let o = match op {
                    BinOp::Add => Bop::Add,
                    BinOp::Sub => Bop::Sub,
                    BinOp::Mul => Bop::Mul,
                    BinOp::Div => Bop::Div,
                    BinOp::FloorDiv => Bop::FloorDiv,
                    BinOp::Mod => Bop::Mod,
                    BinOp::Pow => Bop::Pow,
                    _ => unreachable!(),
                };
                PE::Bin(Box::new(a), o, Box::new(b))
            }
        }
    }

    pub fn callee_arity_pub(&self, f: &Expr) -> Option<usize> {
        self.callee_arity_of(f)
    }

    pub fn section(&mut self, op: SectionOp, _args: &[&Expr]) -> PE {
        let body = self.section_body(op, name("a"), name("b"));
        PE::Lambda(vec!["a".into(), "b".into()], Box::new(body))
    }

    fn section_body(&self, op: SectionOp, a: PE, b: PE) -> PE {
        match op {
            SectionOp::Bin(bo) => {
                let o = match bo {
                    BinOp::Add => Bop::Add,
                    BinOp::Sub => Bop::Sub,
                    BinOp::Mul => Bop::Mul,
                    BinOp::Div => Bop::Div,
                    BinOp::FloorDiv => Bop::FloorDiv,
                    BinOp::Mod => Bop::Mod,
                    _ => Bop::Pow,
                };
                PE::Bin(Box::new(a), o, Box::new(b))
            }
            SectionOp::Cmp(c) => {
                let o = match c {
                    CmpOp::Eq => Cop::Eq,
                    CmpOp::Ne => Cop::Ne,
                    CmpOp::Lt => Cop::Lt,
                    CmpOp::Le => Cop::Le,
                    CmpOp::Gt => Cop::Gt,
                    CmpOp::Ge => Cop::Ge,
                };
                PE::Cmp(Box::new(a), vec![(o, b)])
            }
        }
    }

    pub fn section_partial(&mut self, op: SectionOp, args: &[&Expr]) -> PE {
        let a = self.expr(args[0]);
        let body = self.section_body(op, a, name("b"));
        PE::Lambda(vec!["b".into()], Box::new(body))
    }

    pub fn try_expr(&mut self, x: &Expr) -> PE {
        self.needs.result = true;
        self.needs.exception = true;
        let t = self.new_tmp();
        let ex = self.new_tmp();
        let saved = std::mem::take(&mut self.pre);
        let v = self.expr(x);
        let mut body = std::mem::replace(&mut self.pre, saved);
        body.push(PS::Assign(name(&t), call_n("Ok", vec![v])));
        let err = call_n(
            "Error",
            vec![call_n(
                "_Exception",
                vec![attr(call_n("type", vec![name(&ex)]), "__name__"), call_n("str", vec![name(&ex)])],
            )],
        );
        self.pre.push(PS::Try(body, vec![("Exception".into(), Some(ex), vec![PS::Assign(name(&t), err)])]));
        name(&t)
    }

    /// `second (first _pf_x)`, the body of a composition.
    fn composed(&mut self, first: &Expr, second: &Expr) -> PE {
        let x = Expr { kind: ExprKind::Var("_pf_x".into()), span: Span::new(0, 0) };
        self.scopes.push(HashMap::new());
        self.bind("_pf_x", BKind::Value, false);
        let (f1, mut a1) = Self::spine(first);
        a1.push(&x);
        let inner = self.apply(f1, &a1, first);
        // the second stage takes the first's result
        let (f2, a2) = Self::spine(second);
        let arity = self.callee_arity_pub(f2);
        let fv = self.expr(f2);
        let mut argv: Vec<PE> = a2.iter().map(|a| self.expr(a)).collect();
        argv.push(inner);
        let outer = self.call_with_arity(fv, argv, arity);
        self.scopes.pop();
        outer
    }

    pub fn if_expr(&mut self, c: &Expr, a: &Expr, b: &Expr) -> PE {
        let cv = self.expr(c);
        let saved = std::mem::take(&mut self.pre);
        let av = self.expr(a);
        let mut apre = std::mem::take(&mut self.pre);
        let bv = self.expr(b);
        let mut bpre = std::mem::replace(&mut self.pre, saved);
        if apre.is_empty() && bpre.is_empty() {
            return PE::IfExp(Box::new(cv), Box::new(av), Box::new(bv));
        }
        // statement form: each branch's statements, then a temporary
        let t = self.new_tmp();
        apre.push(PS::Assign(name(&t), av));
        bpre.push(PS::Assign(name(&t), bv));
        self.pre.push(PS::If(vec![(cv, apre)], Some(bpre)));
        name(&t)
    }

    /// Statements computing `e` into `dest`.
    pub fn dest_stmts(&mut self, e: &Expr, dest: &Dest) -> Vec<PS> {
        match &e.kind {
            ExprKind::If(c, a, b) => {
                if let Dest::Return | Dest::ReturnAwait = dest {
                    let saved = std::mem::take(&mut self.pre);
                    let cv = self.expr(c);
                    let mut out = std::mem::replace(&mut self.pre, saved);
                    let mut arms = Vec::new();
                    self.scopes.push(HashMap::new());
                    let tb = self.dest_stmts(a, dest);
                    self.scopes.pop();
                    arms.push((cv, tb));
                    let els = self.else_chain_ret(b, dest, &mut arms, &mut out);
                    out.push(PS::If(arms, els));
                    return out;
                }
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.push(self.finish(v, dest));
                out
            }
            // (a match computed into a variable gets its own, then copied)
            ExprKind::Match(s, arms) => match dest {
                Dest::Assign(t) => {
                    let (mut out, inner) = self.match_value(s, arms, e.span);
                    out.push(PS::Assign(name(t), name(&inner)));
                    out
                }
                _ => self.match_stmt(s, arms, e.span, dest),
            },
            ExprKind::Block(stmts) => {
                let mut out = Vec::new();
                self.scopes.push(HashMap::new());
                let n = stmts.len();
                for s in &stmts[..n - 1] {
                    out.extend(self.block_stmt(s));
                }
                match &stmts[n - 1] {
                    Stmt::Expr(x) => out.extend(self.dest_stmts(x, dest)),
                    other => {
                        out.extend(self.block_stmt(other));
                        // a block ending in an assignment has the value unit
                        if let Stmt::Assign(..) = other {
                            match dest {
                                Dest::Return | Dest::ReturnAwait => out.push(PS::Return(Some(PE::NoneV))),
                                Dest::Assign(t) => out.push(PS::Assign(name(t), PE::NoneV)),
                                Dest::Discard | Dest::Fresh => {}
                            }
                        }
                    }
                }
                self.scopes.pop();
                out
            }
            _ => {
                if let Dest::Return | Dest::ReturnAwait = dest {
                    if let Some(stmts) = self.tail_call(e) {
                        return stmts;
                    }
                }
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.push(self.finish(v, dest));
                out
            }
        }
    }

    /// A saturated self call in tail position: rebind the parameters and loop.
    pub fn tail_call(&mut self, e: &Expr) -> Option<Vec<PS>> {
        let (sn, params) = self.fn_stack.last()?.tce.clone()?;
        let (f, args) = tail_spine(e)?;
        match &f.kind {
            ExprKind::Var(n) if *n == sn && args.len() == params.len() => {}
            _ => return None,
        }
        // the name must still mean this function
        let saved = std::mem::take(&mut self.pre);
        let vals: Vec<PE> = args.iter().map(|a| self.expr(a)).collect();
        let mut out = std::mem::replace(&mut self.pre, saved);
        if params.len() == 1 {
            out.push(PS::Assign(name(&params[0]), vals.into_iter().next().unwrap()));
        } else {
            out.push(PS::Assign(PE::Tuple(params.iter().map(|p| name(p)).collect()), PE::Tuple(vals)));
        }
        out.push(PS::Continue);
        Some(out)
    }

    fn else_chain_ret(&mut self, b: &Expr, dest: &Dest, arms: &mut Vec<(PE, Vec<PS>)>, out: &mut Vec<PS>) -> Option<Vec<PS>> {
        if let ExprKind::If(c2, a2, b2) = &b.kind {
            let saved = std::mem::take(&mut self.pre);
            let cv = self.expr(c2);
            let mut p = std::mem::replace(&mut self.pre, saved);
            self.scopes.push(HashMap::new());
            let body = self.dest_stmts(a2, dest);
            self.scopes.pop();
            if p.is_empty() {
                arms.push((cv, body));
                return self.else_chain_ret(b2, dest, arms, out);
            }
            // a condition that needs statements starts a chain of its own
            let mut inner = vec![(cv, body)];
            let els = self.else_chain_ret(b2, dest, &mut inner, out);
            p.push(PS::If(inner, els));
            return Some(p);
        }
        self.scopes.push(HashMap::new());
        let s = self.dest_stmts(b, dest);
        self.scopes.pop();
        // an else that is one `if` (a ladder, say) continues the chain
        if let [PS::If(more, els)] = s.as_slice() {
            arms.extend(more.iter().cloned());
            return els.clone();
        }
        Some(s)
    }

    pub fn finish(&mut self, v: PE, dest: &Dest) -> PS {
        match dest {
            Dest::Return => PS::Return(Some(v)),
            Dest::ReturnAwait => PS::Return(Some(PE::Await(Box::new(v)))),
            Dest::Assign(t) => PS::Assign(name(t), v),
            // (a fresh temporary is settled before any arm is lowered)
            Dest::Discard | Dest::Fresh => PS::Expr(v),
        }
    }

    // ---- lambdas ------------------------------------------------------------

    pub fn lambda(&mut self, ps: &[Pat], body: &Expr) -> PE {
        let simple = ps.iter().all(|p| matches!(p.kind, PatKind::Var(_)));
        if simple {
            let saved = std::mem::take(&mut self.pre);
            self.scopes.push(HashMap::new());
            let mut names = Vec::new();
            for p in ps {
                if let PatKind::Var(n) = &p.kind {
                    names.push(self.bind(n, BKind::Value, false));
                }
            }
            self.fn_stack.push(FnFrame { depth: self.depth(), bound: crate::shadow::fn_bound(ps, body), ..Default::default() });
            let b = self.expr(body);
            self.fn_stack.pop();
            self.scopes.pop();
            let p = std::mem::replace(&mut self.pre, saved);
            if p.is_empty() {
                return PE::Lambda(names, Box::new(b));
            }
        }
        // lift to a def
        let fname = self.new_fn();
        let def = self.def_stmt(&fname, ps, body, None);
        self.pre.push(def);
        name(&fname)
    }

    /// Build `def name(params): body` (params may be patterns).
    pub fn def_stmt(&mut self, fname: &str, ps: &[Pat], body: &Expr, self_name: Option<&str>) -> PS {
        // a `let` function's signature is annotated for mypyc: at the top
        // level (not in a module or a block run there) and inside functions
        let annotate = self.native && self_name.is_some() && (!self.fn_stack.is_empty() || self.annotate_top);
        let d = self.def_stmt_inner(fname, ps, body, self_name);
        if !annotate {
            return d;
        }
        match d {
            PS::Def { name: n, params, body: b, is_async, .. } => {
                let mut annotated = Vec::new();
                for (p, py) in ps.iter().zip(params.iter()) {
                    let ann = self.pat_ty(p.span).and_then(|t| self.native_ann(&t, false));
                    annotated.push(match ann {
                        Some(a) => format!("{}{}", py, crate::native::annotation(": ", &a)),
                        None => py.clone(),
                    });
                }
                let ret = match self.ty_of(body.span) {
                    Some(Ty::Con(u, _)) if u == "unit" => None,
                    Some(t) => self.native_ann(&t, false).map(|a| crate::native::annotation(" -> ", &a)),
                    None => None,
                };
                PS::Def { name: n, params: annotated, body: b, is_async, ret }
            }
            other => other,
        }
    }

    fn def_stmt_inner(&mut self, fname: &str, ps: &[Pat], body: &Expr, self_name: Option<&str>) -> PS {
        if self_name.is_some() {
            self.fn_asts.insert(fname.to_string(), std::rc::Rc::new((ps.to_vec(), body.clone())));
        }
        self.scopes.push(HashMap::new());
        let mut params = Vec::new();
        let mut destructure = Vec::new();
        let mut used_underscore = false;
        for (i, p) in ps.iter().enumerate() {
            match &p.kind {
                PatKind::Var(n) => params.push(self.bind(n, BKind::Value, false)),
                PatKind::Wild => {
                    if used_underscore {
                        params.push(format!("_pf_arg{}", i));
                    } else {
                        used_underscore = true;
                        params.push("_".into());
                    }
                }
                _ => {
                    let a = format!("_pf_arg{}", i);
                    params.push(a.clone());
                    destructure.push((p.clone(), a));
                }
            }
        }
        if let (Some(sn), ExprKind::Ce(cp, cn, items)) = (self_name, &body.kind) {
            let tail_in_return = items.iter().any(|it| matches!(it, CeStmt::ReturnBang(e, _) if has_tail_self_call(e, sn, ps.len())));
            if cp.is_empty() && cn == "async" && destructure.is_empty() && tail_in_return {
                let outer = FnFrame { depth: self.depth(), self_name: Some(sn.to_string()), bound: crate::shadow::fn_bound(ps, body), ..Default::default() };
                self.fn_stack.push(outer);
                self.scopes.push(HashMap::new());
                let inner = FnFrame { depth: self.depth(), self_name: Some(sn.to_string()), tce: Some((sn.to_string(), params.clone())), bound: crate::shadow::ce_bound(items), ..Default::default() };
                self.fn_stack.push(inner);
                let stmts = self.async_items_pub(items);
                let iframe = self.fn_stack.pop().unwrap();
                self.scopes.pop();
                let oframe = self.fn_stack.pop().unwrap();
                self.scopes.pop();
                let afn = self.new_fn();
                let mut abody = crate::lower4::frame_decls(&iframe);
                abody.push(PS::While(PE::Bool(true), stmts));
                let mut outb = crate::lower4::frame_decls(&oframe);
                outb.push(PS::Def { name: afn.clone(), params: params.clone(), body: abody, is_async: true, ret: None });
                self.helper("_pf_Async");
                let mut args = vec![name(&afn)];
                args.extend(params.iter().map(|p| name(p)));
                outb.push(PS::Return(Some(call_n("_pf_Async", args))));
                return PS::Def { name: fname.to_string(), params, body: outb, is_async: false, ret: None };
            }
        }
        let mut frame = FnFrame { depth: self.depth(), bound: crate::shadow::fn_bound(ps, body), ..Default::default() };
        frame.self_name = self_name.map(|s| s.to_string());
        let tce = match self_name {
            Some(sn) if destructure.is_empty() && has_tail_self_call(body, sn, ps.len()) => Some((sn.to_string(), params.clone())),
            _ => None,
        };
        frame.tce = tce.clone();
        self.fn_stack.push(frame);
        let mut out = Vec::new();
        for (p, a) in destructure {
            out.extend(self.destructure_from(&p, &a, Some(a.clone())));
        }
        let saved = std::mem::take(&mut self.pre);
        out.extend(self.dest_stmts(body, &Dest::Return));
        self.pre = saved;
        if tce.is_some() {
            out = vec![PS::While(PE::Bool(true), out)];
        }
        let frame = self.fn_stack.pop().unwrap();
        self.scopes.pop();
        let mut decls = Vec::new();
        if !frame.globals.is_empty() {
            decls.push(PS::Global(frame.globals.clone()));
        }
        if !frame.nonlocals.is_empty() {
            decls.push(PS::Nonlocal(frame.nonlocals.clone()));
        }
        decls.extend(out);
        PS::Def { name: fname.to_string(), params, body: decls, is_async: false, ret: None }
    }

    /// `let (a, b) = v` style binding.
    pub fn destructure(&mut self, p: &Pat, v: PE) -> Vec<PS> {
        match &p.kind {
            PatKind::Var(n) => {
                let py = self.bind_site(n, p.span);
                vec![PS::Assign(name(&py), v)]
            }
            PatKind::Wild => vec![PS::Assign(name("_"), v)],
            PatKind::Tuple(ps) if ps.iter().all(|x| matches!(x.kind, PatKind::Var(_) | PatKind::Wild)) => {
                let target = self.tuple_target(p);
                vec![PS::Assign(target, v)]
            }
            _ => {
                let mut out = Vec::new();
                let src = match v {
                    PE::Name(n) => n,
                    other => {
                        let t = self.new_tmp();
                        out.push(PS::Assign(name(&t), other));
                        t
                    }
                };
                out.extend(self.destructure_from(p, &src, None));
                out
            }
        }
    }

    /// Bind the parts of `p` from the variable `src`; nested parts go through
    /// temporaries named after `prefix` (allocated when none is given).
    pub fn destructure_from(&mut self, p: &Pat, src: &str, prefix: Option<String>) -> Vec<PS> {
        match &p.kind {
            PatKind::Var(n) => {
                let py = self.bind_site(n, p.span);
                vec![PS::Assign(name(&py), name(src))]
            }
            PatKind::Wild => vec![],
            PatKind::Tuple(ps) => {
                if ps.iter().all(|x| matches!(x.kind, PatKind::Var(_) | PatKind::Wild)) {
                    let target = self.tuple_target(p);
                    return vec![PS::Assign(target, name(src))];
                }
                let base = prefix.unwrap_or_else(|| self.new_tmp());
                let mut targets = Vec::new();
                let mut nested = Vec::new();
                for (i, x) in ps.iter().enumerate() {
                    match &x.kind {
                        PatKind::Var(n) => targets.push(name(&self.bind_site(n, x.span))),
                        PatKind::Wild => targets.push(name("_")),
                        _ => {
                            let sub = format!("{}_{}", base, i);
                            targets.push(name(&sub));
                            nested.push((x, sub));
                        }
                    }
                }
                let mut out = vec![PS::Assign(PE::Tuple(targets), name(src))];
                for (x, sub) in nested {
                    out.extend(self.destructure_from(x, &sub, Some(sub.clone())));
                }
                out
            }
            PatKind::Record(_, _, _, fields) => {
                let base = prefix.unwrap_or_else(|| self.new_tmp());
                let mut out = Vec::new();
                for (i, (f, fspan, sub)) in fields.iter().enumerate() {
                    let val = attr(name(src), &mangle(f));
                    match sub {
                        None => {
                            let py = self.bind_site(f, *fspan);
                            out.push(PS::Assign(name(&py), val));
                        }
                        Some(sp) => match &sp.kind {
                            PatKind::Var(n) => {
                                let py = self.bind_site(n, sp.span);
                                out.push(PS::Assign(name(&py), val));
                            }
                            PatKind::Wild => {}
                            _ => {
                                let subn = format!("{}_{}", base, i);
                                out.push(PS::Assign(name(&subn), val));
                                out.extend(self.destructure_from(sp, &subn, Some(subn.clone())));
                            }
                        },
                    }
                }
                out
            }
            _ => vec![],
        }
    }

    pub fn tuple_target(&mut self, p: &Pat) -> PE {
        match &p.kind {
            PatKind::Var(n) => name(&self.bind_site(n, p.span)),
            PatKind::Wild => name("_"),
            PatKind::Tuple(ps) => PE::Tuple(ps.iter().map(|x| self.tuple_target(x)).collect()),
            _ => name("_"),
        }
    }

    // ---- statements ---------------------------------------------------------

    pub fn block_stmt(&mut self, s: &Stmt) -> Vec<PS> {
        match s {
            Stmt::Let(l) => self.let_stmt(l),
            Stmt::Assign(n, _, v, _) => {
                let saved = std::mem::take(&mut self.pre);
                let val = self.expr(v);
                let mut out = std::mem::replace(&mut self.pre, saved);
                let py = self.assign_target(n);
                out.push(PS::Assign(name(&py), val));
                out
            }
            Stmt::Expr(e) => self.expr_stmt(e),
        }
    }

    /// The Python name for an assignment, declaring it global/nonlocal as needed.
    /// The variable `x <- v` writes. Python decides by name whose variable
    /// that is: the function's own if it binds the name anywhere, else the
    /// nearest enclosing function's that does (`nonlocal`), else the
    /// module's (`global`).
    pub fn assign_target(&mut self, n: &str) -> String {
        let b = self.lookup(n).cloned();
        let Some(b) = b else { return mangle(n) };
        let len = self.fn_stack.len();
        if len == 0 || self.fn_stack[len - 1].bound.contains(n) {
            return b.py;
        }
        let enclosing = self.fn_stack[..len - 1].iter().any(|f| f.bound.contains(n));
        let frame = self.fn_stack.last_mut().unwrap();
        if enclosing {
            if !frame.nonlocals.contains(&b.py) {
                frame.nonlocals.push(b.py.clone());
            }
        } else if !frame.globals.contains(&b.py) {
            frame.globals.push(b.py.clone());
        }
        b.py
    }

    pub fn expr_stmt(&mut self, e: &Expr) -> Vec<PS> {
        // a match whose value is dropped: a ladder runs its arms for their
        // effects alone
        if let (true, ExprKind::Match(s, arms)) = (self.native, &e.kind) {
            let (mut out, t) = self.match_value(s, arms, e.span);
            if matches!(out.last(), Some(PS::If(..))) {
                for st in out.iter_mut() {
                    if let PS::If(..) = st {
                        drop_assign(st, &t);
                    }
                }
            } else {
                out.push(PS::Expr(name(&t)));
            }
            return out;
        }
        let saved = std::mem::take(&mut self.pre);
        let v = self.expr(e);
        let mut out = std::mem::replace(&mut self.pre, saved);
        out.push(PS::Expr(v));
        out
    }

    pub fn let_stmt(&mut self, l: &LetDecl) -> Vec<PS> {
        let saved = std::mem::take(&mut self.pre);
        let mut out = Vec::new();
        if !l.params.is_empty() {
            if let PatKind::Var(n) = &l.pat.kind {
                let py = self.bind_site_as(n, l.name_span, BKind::Fn(l.params.len()), false);
                let d = self.def_stmt(&py, &l.params, &l.value, Some(n));
                out.extend(std::mem::replace(&mut self.pre, saved));
                out.push(d);
                return out;
            }
        }
        match &l.pat.kind {
            PatKind::Var(n) => {
                let kind = match &l.value.kind {
                    ExprKind::Lambda(ps, _) => BKind::Fn(ps.len()),
                    _ => BKind::Value,
                };
                let v = self.expr(&l.value);
                out.extend(std::mem::replace(&mut self.pre, saved));
                let py = self.bind_site_as(n, l.name_span, kind, l.mutable);
                out.push(PS::Assign(name(&py), v));
            }
            _ => {
                let v = self.expr(&l.value);
                out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                out.extend(self.destructure(&l.pat, v));
                out.extend(std::mem::replace(&mut self.pre, saved));
            }
        }
        out
    }

    // ---- records ------------------------------------------------------------

    pub fn record(&mut self, path: &[String], n: &str, fields: &[(String, Span, Expr)]) -> PE {
        let key = if path.is_empty() { n.to_string() } else { format!("{}.{}", path.join("."), n) };
        let order: Vec<String> = match self.ck.types.get(&key) {
            Some(TypeInfo { def: TypeDef::Record(fs), .. }) => fs.iter().map(|(f, _)| f.clone()).collect(),
            _ => fields.iter().map(|(f, _, _)| f.clone()).collect(),
        };
        let mut vals: HashMap<String, PE> = HashMap::new();
        for (f, _, v) in fields {
            let pv = self.expr(v);
            vals.insert(f.clone(), pv);
        }
        let args: Vec<PE> = order.iter().map(|f| vals.remove(f).unwrap_or(PE::NoneV)).collect();
        let cls = match self.module_alias(&path.join(".")) {
            Some(py) if !path.is_empty() => format!("{}.{}", py, n),
            _ => n.to_string(),
        };
        self.needs.dataclass = true;
        call_n(&cls, args)
    }

    pub fn update(&mut self, b: &Expr, fields: &[(Vec<(String, Span)>, Expr)]) -> PE {
        let bv = self.expr(b);
        let t = self.new_tmp();
        self.pre.push(PS::Assign(name(&t), bv));
        let rt = self.ty_of(b.span);
        let mut vals: Vec<(Vec<String>, PE)> = Vec::new();
        for (path, v) in fields {
            let pv = self.expr(v);
            vals.push((path.iter().map(|(n, _)| n.clone()).collect(), pv));
        }
        self.rebuild(name(&t), rt, &vals, &[])
    }

    fn rebuild(&mut self, base: PE, t: Option<Ty>, vals: &[(Vec<String>, PE)], prefix: &[String]) -> PE {
        let tname = match &t {
            Some(Ty::Con(n, _)) => n.clone(),
            _ => String::new(),
        };
        let fs: Vec<(String, Ty)> = match self.ck.types.get(&tname) {
            Some(TypeInfo { def: TypeDef::Record(fs), .. }) => fs.clone(),
            _ => vec![],
        };
        let mut args = Vec::new();
        for (f, ft) in &fs {
            let mut path = prefix.to_vec();
            path.push(f.clone());
            if let Some((_, v)) = vals.iter().find(|(p, _)| *p == path) {
                args.push(v.clone());
            } else if vals.iter().any(|(p, _)| p.len() > path.len() && p[..path.len()] == path[..]) {
                let inner_t = match &t {
                    Some(Ty::Con(_, targs)) => {
                        let mut ft2 = ft.clone();
                        if !targs.is_empty() {
                            ft2 = subst_gen(ft, targs);
                        }
                        Some(ft2)
                    }
                    _ => Some(ft.clone()),
                };
                args.push(self.rebuild(base.clone(), inner_t, vals, &path));
            } else {
                let mut v = base.clone();
                for p in &path {
                    v = attr(v, &mangle(p));
                }
                args.push(v);
            }
        }
        // a type of an imported module goes through that module
        let module = self.ck.types.get(&tname).and_then(|ti| ti.module.clone());
        let short = tname.rsplit('.').next().unwrap_or(&tname).to_string();
        let cls = match module.as_deref().and_then(|m| self.module_alias(m).cloned()) {
            Some(py) => format!("{}.{}", py, short),
            None => tname.clone(),
        };
        call_n(&cls, args)
    }
}

/// The head and arguments of a call written directly or through pipes.
pub fn tail_spine(e: &Expr) -> Option<(&Expr, Vec<&Expr>)> {
    match &e.kind {
        ExprKind::App(..) => Some(Lowerer::spine(e)),
        ExprKind::Binary(BinOp::PipeRight, l, r) => {
            let (f, mut a) = Lowerer::spine(r);
            a.push(l);
            Some((f, a))
        }
        ExprKind::Binary(BinOp::PipeLeft, l, r) => {
            let (f, mut a) = Lowerer::spine(l);
            a.push(r);
            Some((f, a))
        }
        _ => None,
    }
}

/// Does `body` call `name` with `arity` arguments in a tail position?
pub fn has_tail_self_call(body: &Expr, name: &str, arity: usize) -> bool {
    match &body.kind {
        ExprKind::If(_, a, b) => has_tail_self_call(a, name, arity) || has_tail_self_call(b, name, arity),
        ExprKind::Match(_, arms) => arms.iter().any(|a| has_tail_self_call(&a.body, name, arity)),
        ExprKind::Block(stmts) => {
            // a local rebinding of the name hides the function
            for s in stmts {
                if let Stmt::Let(l) = s {
                    if let PatKind::Var(n) = &l.pat.kind {
                        if n == name {
                            return false;
                        }
                    }
                }
            }
            match stmts.last() {
                Some(Stmt::Expr(x)) => has_tail_self_call(x, name, arity),
                _ => false,
            }
        }
        _ => match tail_spine(body) {
            Some((f, args)) => matches!(&f.kind, ExprKind::Var(n) if n == name) && args.len() == arity,
            None => false,
        },
    }
}

pub fn subst_gen(t: &Ty, args: &[Ty]) -> Ty {
    match t {
        Ty::Gen(i) => args.get(*i).cloned().unwrap_or(t.clone()),
        Ty::Con(n, a) => Ty::Con(n.clone(), a.iter().map(|x| subst_gen(x, args)).collect()),
        Ty::Fun(a, e, r) => Ty::Fun(Box::new(subst_gen(a, args)), e.clone(), Box::new(subst_gen(r, args))),
        Ty::Tuple(ts) => Ty::Tuple(ts.iter().map(|x| subst_gen(x, args)).collect()),
        other => other.clone(),
    }
}

/// Inside a ladder, `t = value` becomes the bare `value`.
fn drop_assign(st: &mut PS, t: &str) {
    match st {
        PS::If(arms, els) => {
            for (_, body) in arms.iter_mut() {
                for x in body.iter_mut() {
                    drop_assign(x, t);
                }
            }
            if let Some(body) = els {
                for x in body.iter_mut() {
                    drop_assign(x, t);
                }
            }
        }
        PS::Assign(PE::Name(n), v) if n == t => *st = PS::Expr(v.clone()),
        _ => {}
    }
}
