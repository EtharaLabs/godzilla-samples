// Lowering: builtin applications, externs, computation expressions.

use crate::ast::*;
use crate::builtins::BUILTINS;
use crate::lower::*;
use crate::py::*;
use crate::types::*;
use std::collections::HashMap;

fn builtin(name: &str) -> Option<&'static crate::builtins::Builtin> {
    BUILTINS.iter().find(|b| b.name == name)
}

/// Parameter types and result of a declared extern type.
pub fn fun_params(t: &Ty) -> (Vec<Ty>, Ty) {
    let mut ps = Vec::new();
    let mut cur = t.clone();
    while let Ty::Fun(a, _, r) = cur {
        ps.push(*a);
        cur = *r;
    }
    (ps, cur)
}

fn is_unit(t: &Ty) -> bool {
    matches!(t, Ty::Con(n, _) if n == "unit")
}

impl<'a> Lowerer<'a> {
    pub fn callee_arity_of(&self, f: &Expr) -> Option<usize> {
        match &f.kind {
            ExprKind::Var(n) => match self.lookup(n) {
                Some(Bind { kind: BKind::Fn(k), .. }) => Some(*k),
                Some(Bind { kind: BKind::Extern(k), .. }) => Some(*k),
                Some(_) => None,
                None => builtin(n).map(|b| sig_arity(b.sig)),
            },
            ExprKind::Qual(p, n, _) => {
                let full = format!("{}.{}", p.join("."), n);
                if let Some(b) = builtin(&full) {
                    return Some(sig_arity(b.sig));
                }
                match self.lookup(&full) {
                    Some(Bind { kind: BKind::Fn(k), .. }) => Some(*k),
                    _ => self.project_arity(&p.join("."), n),
                }
            }
            ExprKind::Ctor(p, n) => self.ck.lookup_ctor(p, n).map(|c| c.args.len()).or_else(|| self.ck.active_ctors.get(n).map(|c| c.args.len())),
            ExprKind::Lambda(ps, _) => Some(ps.len()),
            ExprKind::Section(_) => Some(2),
            _ => None,
        }
    }

    fn project_arity(&self, m: &str, n: &str) -> Option<usize> {
        self.module_arities.get(&format!("{}.{}", m, n)).copied()
    }

    // ---- builtins -----------------------------------------------------------

    pub fn apply_builtin(&mut self, bn: &str, f: &Expr, args: &[&Expr], whole: &Expr) -> Option<PE> {
        let b = builtin(bn)?;
        let arity = sig_arity(b.sig);
        if let Some(v) = self.special_builtin(bn, f, args, whole) {
            return Some(v);
        }
        if args.len() < arity {
            let fv = self.builtin_value(bn);
            let argv: Vec<PE> = args.iter().map(|a| self.expr(a)).collect();
            if argv.is_empty() {
                return Some(fv);
            }
            self.needs.functools = true;
            let mut v = vec![fv];
            v.extend(argv);
            return Some(PE::Call(Box::new(attr(name("functools"), "partial")), v, vec![]));
        }
        let argv: Vec<PE> = args[..arity].iter().map(|a| self.expr(a)).collect();
        let rest: Vec<PE> = args[arity..].iter().map(|a| self.expr(a)).collect();
        let full = self.builtin_full(b, argv);
        Some(self.call_curried(full, rest))
    }

    fn builtin_full(&mut self, b: &crate::builtins::Builtin, mut argv: Vec<PE>) -> PE {
        let app = b.app;
        if let Some(fname) = app.strip_prefix("func:") {
            if let Some(m) = fname.strip_prefix("math.") {
                self.needs.imports.insert("math".into());
                return PE::Call(Box::new(attr(name("math"), m)), argv, vec![]);
            }
            return call_n(fname, argv);
        }
        if let Some(m) = app.strip_prefix("method:") {
            let recv = argv.pop().unwrap();
            return PE::Call(Box::new(attr(recv, m)), argv, vec![]);
        }
        match app {
            "not" => PE::Not(Box::new(argv.remove(0))),
            "in" => {
                let coll = argv.pop().unwrap();
                let x = argv.pop().unwrap();
                PE::Cmp(Box::new(x), vec![(Cop::In, coll)])
            }
            "asyncsleep" => {
                self.needs.imports.insert("asyncio".into());
                self.helper("_pf_Async");
                let mut v = vec![attr(name("asyncio"), "sleep")];
                v.extend(argv);
                call_n("_pf_Async", v)
            }
            _ => {
                let fv = self.builtin_value(b.name);
                PE::Call(Box::new(fv), argv, vec![])
            }
        }
    }

    fn special_builtin(&mut self, bn: &str, _f: &Expr, args: &[&Expr], whole: &Expr) -> Option<PE> {
        match bn {
            "Encode.auto" => {
                if let Some(t) = args.first().and_then(|a| self.ty_of(a.span)) {
                    self.register_codec(&t);
                }
                None
            }
            "Decode.decodeString" if args.len() == 2 => self.decode_string(args, whole),
            "List.fold" | "Seq.fold" if args.len() == 3 => self.fuse_fold(args[0], args[1], args[2]),
            "Task.scope" if !args.is_empty() => None,
            _ => None,
        }
    }

    pub fn register_codec(&mut self, t: &Ty) {
        let _ = t;
    }

    fn decode_string(&mut self, args: &[&Expr], _whole: &Expr) -> Option<PE> {
        let d = self.static_decoder(args[0])?;
        Some(self.inline_decode(&d, args[1]))
    }

    // ---- externs ------------------------------------------------------------

    pub fn extern_target(&mut self, e: &ExternDecl) -> PE {
        match &e.target {
            None => name(&e.name),
            Some(ExternTarget::Path(p)) => {
                // a module whose name the program also uses for a variable
                // is imported under another name
                let n = self.note_extern_import(p);
                let (mut v, rest) = match n {
                    Some(n) if self.names_variable(&p[0]) => (name(&format!("_pf_{}", p[0])), &p[n..]),
                    _ => (name(&p[0]), &p[1..]),
                };
                for s in rest {
                    v = attr(v, s);
                }
                v
            }
            Some(ExternTarget::Member(..)) => name("_pf_recv"),
        }
    }

    /// Import the module a path reaches; the number of its parts that name
    /// the module.
    fn note_extern_import(&mut self, p: &[String]) -> Option<usize> {
        if p.len() < 2 {
            return None;
        }
        // methods of Python's builtin types need no import
        if matches!(
            p[0].as_str(),
            "str" | "int" | "float" | "list" | "dict" | "set" | "tuple" | "bool" | "bytes" | "object" | "range" | "bytearray" | "frozenset" | "complex" | "memoryview" | "slice"
        ) {
            return None;
        }
        let clash = self.names_variable(&p[0]);
        let module = |m: String| if clash { format!("{} as _pf_{}", m, p[0]) } else { m };
        // an explicit `extern import` covering the path wins
        let mut best: Option<Vec<String>> = None;
        for (ip, _alias) in &self.extern_imports {
            if p.len() > ip.len() && p[..ip.len()] == ip[..] {
                if best.as_ref().map_or(true, |b| ip.len() > b.len()) {
                    best = Some(ip.clone());
                }
            }
        }
        match best {
            Some(b) => {
                self.needs.imports.insert(module(b.join(".")));
                Some(b.len())
            }
            None => {
                self.needs.imports.insert(module(p[0].clone()));
                Some(1)
            }
        }
    }

    /// Whether the program binds a variable of this name (externs, which
    /// are written out where used, do not count).
    fn names_variable(&self, n: &str) -> bool {
        self.ck.ide.defs.iter().any(|d| d.name == n && !self.externs.values().any(|e| e.decl.span == d.span || e.decl.name_span == d.span))
    }

    /// An extern as a value. Async arguments are run, and an Async result
    /// deferred, by a wrapper around the plain value.
    pub fn extern_value(&mut self, n: &str) -> PE {
        let base = self.extern_value_plain(n);
        let Some(arity) = self.externs.get(n).map(|i| i.arity) else { return base };
        let (params, result) = fun_params(&self.extern_ty(n));
        let is_async = |t: &Ty| matches!(t, Ty::Con(a, _) if a == "Async");
        let async_result = is_async(&result);
        if arity == 0 || !(async_result || params.iter().any(is_async)) {
            return base;
        }
        let ps: Vec<String> = (0..arity).map(|i| format!("_pf_p{}", i)).collect();
        let mut args = Vec::new();
        for (i, p) in ps.iter().enumerate() {
            if params.get(i).map_or(false, is_async) {
                self.helper("_pf_run");
                args.push(call_n("_pf_run", vec![name(p)]));
            } else {
                args.push(name(p));
            }
        }
        let body = if async_result {
            self.helper("_pf_Async");
            let mut v = vec![base];
            v.extend(args);
            call_n("_pf_Async", v)
        } else {
            call(base, args)
        };
        PE::Lambda(ps, Box::new(body))
    }

    fn extern_value_plain(&mut self, n: &str) -> PE {
        let info = self.externs.get(n).map(|i| (i.decl.clone(), i.arity));
        let Some((d, arity)) = info else { return name(n) };
        let (params, _) = fun_params(&self.extern_ty(n));
        // a unit among several parameters is taken and dropped
        let member = matches!(d.target, Some(ExternTarget::Member(..)));
        if arity >= 2 && params.iter().take(arity).any(is_unit) && !matches!(d.target, Some(ExternTarget::Member(_, false))) {
            let ps: Vec<String> = (0..arity).map(|i| if i == 0 && member { "_pf_recv".to_string() } else { format!("_pf_a{}", i) }).collect();
            let argv = ps.iter().map(|p| name(p)).collect();
            let body = self.extern_call(&d, &params, argv, false);
            return PE::Lambda(ps, Box::new(body));
        }
        match &d.target {
            Some(ExternTarget::Member(m, call)) => {
                // (an attribute, not a call, takes the receiver alone)
                let mut ps = vec!["_pf_recv".to_string()];
                let mut args = Vec::new();
                for i in 1..if *call { arity } else { 1 } {
                    if params.get(i).map_or(false, is_unit) {
                        continue;
                    }
                    ps.push(format!("_pf_a{}", i));
                    args.push(name(&format!("_pf_a{}", i)));
                }
                let body = if *call {
                    let kws = self.pinned_kwargs(&d);
                    PE::Call(Box::new(attr(name("_pf_recv"), m)), args, kws)
                } else {
                    attr(name("_pf_recv"), m)
                };
                PE::Lambda(ps, Box::new(body))
            }
            _ => {
                let target = self.extern_target(&d);
                // a function of no arguments takes (and drops) whatever it is
                // called with
                if arity == 1 && params.first().map_or(false, is_unit) && self.slot_names(&d).is_empty() {
                    let kws = self.pinned_kwargs(&d);
                    return PE::Lambda(vec!["*_pf_a".to_string()], Box::new(PE::Call(Box::new(target), vec![], kws)));
                }
                let slots = self.slot_names(&d);
                if !slots.is_empty() {
                    let npos = arity - slots.len();
                    let mut ps = Vec::new();
                    let mut pos = Vec::new();
                    for i in 0..npos {
                        ps.push(format!("_pf_k{}", i));
                        pos.push(name(&format!("_pf_k{}", i)));
                    }
                    let mut kws = Vec::new();
                    let mut si = npos;
                    for (k, v) in d.kwargs.clone().unwrap_or_default() {
                        match v {
                            KwValue::Slot => {
                                ps.push(format!("_pf_k{}", si));
                                kws.push((k, name(&format!("_pf_k{}", si))));
                                si += 1;
                            }
                            other => kws.push((k, kw_value(&other))),
                        }
                    }
                    return PE::Lambda(ps, Box::new(PE::Call(Box::new(target), pos, kws)));
                }
                let kws = self.pinned_kwargs(&d);
                if !kws.is_empty() {
                    self.needs.functools = true;
                    return PE::Call(Box::new(attr(name("functools"), "partial")), vec![target], kws);
                }
                target
            }
        }
    }

    pub fn extern_ty(&self, n: &str) -> Ty {
        self.ck.extern_effects.get(n).cloned().unwrap_or(Ty::Con("unit".into(), vec![]))
    }

    fn slot_names(&self, d: &ExternDecl) -> Vec<String> {
        d.kwargs.as_ref().map(|k| k.iter().filter(|(_, v)| matches!(v, KwValue::Slot)).map(|(k, _)| k.clone()).collect()).unwrap_or_default()
    }

    fn pinned_kwargs(&self, d: &ExternDecl) -> Vec<(String, PE)> {
        d.kwargs.as_ref().map(|k| k.iter().filter(|(_, v)| !matches!(v, KwValue::Slot)).map(|(k, v)| (k.clone(), kw_value(v))).collect()).unwrap_or_default()
    }

    pub fn apply_extern(&mut self, n: &str, args: &[&Expr], _whole: &Expr) -> PE {
        let info = self.externs.get(n).map(|i| (i.decl.clone(), i.arity));
        let Some((d, arity)) = info else { return name(n) };
        let ety = self.extern_ty(n);
        let (params, result) = fun_params(&ety);
        let async_result = matches!(&result, Ty::Con(r, _) if r == "Async");
        let argv: Vec<PE> = args
            .iter()
            .enumerate()
            .map(|(i, a)| {
                let v = self.expr(a);
                // a thunk parameter is called by Python with no arguments
                match params.get(i) {
                    Some(Ty::Fun(pa, _, _)) if is_unit(pa) => PE::Lambda(vec![], Box::new(call(v, vec![PE::NoneV]))),
                    // Python wants a coroutine where Pyfun has an Async value
                    Some(Ty::Con(an, _)) if an == "Async" => {
                        self.helper("_pf_run");
                        call_n("_pf_run", vec![v])
                    }
                    _ => v,
                }
            })
            .collect();
        if argv.len() < arity {
            return self.extern_partial(&d, arity, &params, argv);
        }
        let mut argv = argv;
        let rest = argv.split_off(arity);
        let full = self.extern_call(&d, &params, argv, async_result && !self.awaiting);
        self.call_curried(full, rest)
    }

    fn extern_partial(&mut self, d: &ExternDecl, arity: usize, params: &[Ty], argv: Vec<PE>) -> PE {
        // only units left to give: a lambda taking them makes the call
        let given = argv.len();
        if (given..arity).all(|i| params.get(i).map_or(false, is_unit)) {
            let ps: Vec<String> = (given..arity).map(|i| format!("_pf_k{}", i - given)).collect();
            let mut all = argv;
            all.extend(ps.iter().map(|p| name(p)));
            let call = self.extern_call(d, params, all, false);
            return PE::Lambda(ps, Box::new(call));
        }
        match &d.target {
            Some(ExternTarget::Member(m, _)) if argv.len() == 1 && self.slot_names(d).is_empty() => {
                let recv = argv.into_iter().next().unwrap();
                attr(recv, m)
            }
            _ => {
                let slots = self.slot_names(d);
                if !slots.is_empty() || params.iter().take(arity).any(is_unit) {
                    // fill the remaining positions from a lambda; the given
                    // arguments are evaluated now (literals aside)
                    let given = argv.len();
                    let mut ps = Vec::new();
                    let mut all = Vec::new();
                    for v in argv {
                        let literal = matches!(v, PE::Int(n) if n >= 0) || matches!(v, PE::Float(f) if f >= 0.0) || matches!(v, PE::Str(_) | PE::Bool(_) | PE::NoneV);
                        if literal {
                            all.push(v);
                        } else {
                            let t = self.new_tmp();
                            self.pre.push(PS::Assign(name(&t), v));
                            all.push(name(&t));
                        }
                    }
                    for i in given..arity {
                        let k = format!("_pf_k{}", i - given);
                        ps.push(k.clone());
                        all.push(name(&k));
                    }
                    let call = self.extern_call(d, params, all, false);
                    return PE::Lambda(ps, Box::new(call));
                }
                // (pinned keywords go in the same partial)
                let kws = self.pinned_kwargs(d);
                let target = if kws.is_empty() { self.extern_value(&d.name) } else { self.extern_target(d) };
                self.needs.functools = true;
                let mut v = vec![target];
                v.extend(argv);
                PE::Call(Box::new(attr(name("functools"), "partial")), v, kws)
            }
        }
    }

    /// A full call of an extern with its declared argument shape.
    pub fn extern_call(&mut self, d: &ExternDecl, params: &[Ty], argv: Vec<PE>, wrap_async: bool) -> PE {
        let slots = self.slot_names(d);
        let nslots = slots.len();
        // (unit arguments are dropped before the slots take the last ones)
        let given: Vec<PE> = argv.into_iter().enumerate().filter(|(i, _)| !params.get(*i).map_or(false, is_unit)).map(|(_, a)| a).collect();
        let npos = given.len().saturating_sub(nslots);
        let mut pos = Vec::new();
        let mut slot_vals = Vec::new();
        for (i, a) in given.into_iter().enumerate() {
            if i < npos {
                pos.push(a);
            } else {
                slot_vals.push(a);
            }
        }
        let mut kws = Vec::new();
        let mut si = 0;
        for (k, v) in d.kwargs.clone().unwrap_or_default() {
            match v {
                KwValue::Slot => {
                    if si < slot_vals.len() {
                        kws.push((k, slot_vals[si].clone()));
                    }
                    si += 1;
                }
                other => kws.push((k, kw_value(&other))),
            }
        }
        match &d.target {
            Some(ExternTarget::Member(m, is_call)) => {
                let recv = if pos.is_empty() { PE::NoneV } else { pos.remove(0) };
                // a member taking more than the receiver is a method
                if *is_call || params.len() > 1 {
                    if wrap_async && kws.is_empty() {
                        self.helper("_pf_Async");
                        let mut v = vec![attr(recv, m)];
                        v.extend(pos);
                        return call_n("_pf_Async", v);
                    }
                    PE::Call(Box::new(attr(recv, m)), pos, kws)
                } else {
                    attr(recv, m)
                }
            }
            _ => {
                let target = self.extern_target(d);
                if wrap_async && kws.is_empty() {
                    self.helper("_pf_Async");
                    let mut v = vec![target];
                    v.extend(pos);
                    return call_n("_pf_Async", v);
                }
                PE::Call(Box::new(target), pos, kws)
            }
        }
    }

    // ---- computation expressions -------------------------------------------

    pub fn ce(&mut self, path: &[String], n: &str, items: &[CeStmt], whole: &Expr) -> PE {
        if !path.is_empty() || !matches!(n, "async" | "seq" | "result" | "option") {
            let mut full = path.to_vec();
            full.push(n.to_string());
            let e = crate::check_ce::desugar_user_ce(&full, items, whole.span);
            return self.expr(&e);
        }
        match n {
            "async" => {
                let (fname, def) = self.async_def(items, None);
                self.pre.push(def);
                self.helper("_pf_Async");
                call_n("_pf_Async", vec![name(&fname)])
            }
            "seq" => {
                self.scopes.push(HashMap::new());
                self.fn_stack.push(FnFrame { depth: self.depth(), bound: crate::shadow::ce_bound(items), ..Default::default() });
                let body = self.seq_items(items);
                let frame = self.fn_stack.pop().unwrap();
                self.scopes.pop();
                let fname = self.new_fn();
                let mut b = frame_decls(&frame);
                b.extend(body);
                // without a `yield` the function is no generator: it hands
                // back an empty iterator instead
                if !seq_yields(items) {
                    b.push(PS::Return(Some(call_n("iter", vec![call_n("tuple", vec![])]))));
                }
                self.pre.push(PS::Def { name: fname.clone(), params: vec![], body: b, is_async: false, ret: None });
                call_n(&fname, vec![])
            }
            _ => {
                let is_result = n == "result";
                if is_result {
                    self.needs.result = true;
                } else {
                    self.needs.option = true;
                }
                self.scopes.push(HashMap::new());
                self.fn_stack.push(FnFrame { depth: self.depth(), bound: crate::shadow::ce_bound(items), ..Default::default() });
                let body = self.railway(items, is_result);
                let frame = self.fn_stack.pop().unwrap();
                self.scopes.pop();
                let fname = self.new_fn();
                let mut b = frame_decls(&frame);
                b.extend(body);
                self.pre.push(PS::Def { name: fname.clone(), params: vec![], body: b, is_async: false, ret: None });
                call_n(&fname, vec![])
            }
        }
    }

    /// `async def` for an async block; returns its name.
    pub fn async_def(&mut self, items: &[CeStmt], params: Option<Vec<String>>) -> (String, PS) {
        self.scopes.push(HashMap::new());
        let mut bound = crate::shadow::ce_bound(items);
        bound.extend(params.iter().flatten().cloned());
        self.fn_stack.push(FnFrame { depth: self.depth(), bound, ..Default::default() });
        let body = self.async_items(items);
        let frame = self.fn_stack.pop().unwrap();
        self.scopes.pop();
        let fname = self.new_fn();
        let mut b = frame_decls(&frame);
        b.extend(body);
        (fname.clone(), PS::Def { name: fname, params: params.unwrap_or_default(), body: b, is_async: true, ret: None })
    }

    /// The awaited form of an expression inside an async block.
    pub fn awaited(&mut self, e: &Expr) -> PE {
        if let ExprKind::Ce(p, n, items) = &e.kind {
            if p.is_empty() && n == "async" {
                let (fname, def) = self.async_def(items, None);
                self.pre.push(def);
                return PE::Await(Box::new(call_n(&fname, vec![])));
            }
        }
        // Async.sleep awaits the coroutine directly
        if let ExprKind::App(..) = &e.kind {
            let (f, args) = Self::spine(e);
            if let ExprKind::Qual(p, n, _) = &f.kind {
                if p.len() == 1 && p[0] == "Async" && n == "sleep" && args.len() == 1 {
                    self.needs.imports.insert("asyncio".into());
                    let a = self.expr(args[0]);
                    return PE::Await(Box::new(PE::Call(Box::new(attr(name("asyncio"), "sleep")), vec![a], vec![])));
                }
            }
        }
        let saved = self.awaiting;
        self.awaiting = true;
        let v = self.expr(e);
        self.awaiting = saved;
        PE::Await(Box::new(v))
    }

    pub fn async_items_pub(&mut self, items: &[CeStmt]) -> Vec<PS> {
        self.async_items(items)
    }

    fn async_items(&mut self, items: &[CeStmt]) -> Vec<PS> {
        let mut out = Vec::new();
        for it in items {
            let saved = std::mem::take(&mut self.pre);
            match it {
                CeStmt::LetBang(p, e, _) => {
                    let v = self.awaited(e);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    out.extend(self.destructure(p, v));
                }
                CeStmt::DoBang(e, _) => {
                    let v = self.awaited(e);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    out.push(PS::Expr(v));
                }
                CeStmt::Return(e, _) => {
                    out.extend(self.dest_stmts(e, &Dest::Return));
                }
                CeStmt::ReturnBang(e, _) => {
                    if self.fn_stack.last().map_or(false, |f| f.tce.is_some()) {
                        out.extend(self.dest_stmts(e, &Dest::ReturnAwait));
                    } else {
                        let v = self.awaited(e);
                        out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                        out.push(PS::Return(Some(v)));
                    }
                }
                CeStmt::Let(l) => out.extend(self.let_stmt(l)),
                CeStmt::Assign(n, _, v) => {
                    let val = self.expr(v);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    let py = self.assign_target(n);
                    out.push(PS::Assign(name(&py), val));
                }
                CeStmt::For(p, src, body, _) => {
                    let s = self.expr(src);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    self.scopes.push(HashMap::new());
                    let target = self.tuple_target(p);
                    let b = self.async_items(body);
                    self.scopes.pop();
                    out.push(PS::For(target, s, b));
                }
                CeStmt::Yield(..) | CeStmt::YieldBang(..) => {}
            }
            let p = std::mem::replace(&mut self.pre, saved);
            out.extend(p);
        }
        out
    }

    fn seq_items(&mut self, items: &[CeStmt]) -> Vec<PS> {
        let mut out = Vec::new();
        for it in items {
            let saved = std::mem::take(&mut self.pre);
            match it {
                CeStmt::Yield(e, _) => {
                    let v = self.expr(e);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    out.push(PS::Raw(format!("yield {}", Printer { py311: false }.expr(&v))));
                }
                CeStmt::YieldBang(e, _) => {
                    let v = self.expr(e);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    out.push(PS::Raw(format!("yield from {}", Printer { py311: false }.expr(&v))));
                }
                CeStmt::Let(l) => out.extend(self.let_stmt(l)),
                CeStmt::For(p, src, body, _) => {
                    let s = self.expr(src);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    self.scopes.push(HashMap::new());
                    let target = self.tuple_target(p);
                    let b = self.seq_items(body);
                    self.scopes.pop();
                    out.push(PS::For(target, s, b));
                }
                CeStmt::Assign(n, _, v) => {
                    let val = self.expr(v);
                    out.extend(std::mem::replace(&mut self.pre, Vec::new()));
                    let py = self.assign_target(n);
                    out.push(PS::Assign(name(&py), val));
                }
                _ => {}
            }
            let p = std::mem::replace(&mut self.pre, saved);
            out.extend(p);
        }
        out
    }

    /// result/option blocks: flat isinstance tests with early returns.
    fn railway(&mut self, items: &[CeStmt], is_result: bool) -> Vec<PS> {
        let Some(first) = items.first() else { return vec![] };
        let rest = &items[1..];
        let (ok_cls, wrap) = if is_result { ("Ok", "Ok") } else { ("Some", "Some") };
        match first {
            // a final unit action is the block's value
            CeStmt::DoBang(e, _) if rest.is_empty() => {
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.push(PS::Return(Some(v)));
                out
            }
            CeStmt::LetBang(_, e, _) | CeStmt::DoBang(e, _) => {
                let pat = match first {
                    CeStmt::LetBang(p, _, _) => Some(p),
                    _ => None,
                };
                let _ = p_unused(pat);
                self.scopes.push(HashMap::new());
                let mut binds = Vec::new();
                // the rest is lowered first (inner temporaries number first)
                let t_placeholder = "\u{0}";
                if let Some(p) = pat {
                    binds = self.destructure(p, attr(name(t_placeholder), "_0"));
                }
                let mut inner = binds;
                inner.extend(self.railway(rest, is_result));
                self.scopes.pop();
                let mut t = self.new_tmp();
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                match v {
                    // a plain name is tested in place
                    PE::Name(n) if out.is_empty() => {
                        self.tmp -= 1;
                        t = n;
                    }
                    v => out.push(PS::Assign(name(&t), v)),
                }
                let inner = rename_placeholder(inner, &t);
                out.push(PS::If(vec![(call_n("isinstance", vec![name(&t), name(ok_cls)]), inner)], Some(vec![PS::Return(Some(name(&t)))])));
                out
            }
            CeStmt::Return(e, _) => {
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.push(PS::Return(Some(call_n(wrap, vec![v]))));
                out
            }
            CeStmt::ReturnBang(e, _) => {
                let saved = std::mem::take(&mut self.pre);
                let v = self.expr(e);
                let mut out = std::mem::replace(&mut self.pre, saved);
                out.push(PS::Return(Some(v)));
                out
            }
            CeStmt::Let(l) => {
                let mut out = self.let_stmt(l);
                if rest.is_empty() {
                    out.push(PS::Return(Some(call_n(wrap, vec![PE::NoneV]))));
                }
                out.extend(self.railway(rest, is_result));
                out
            }
            CeStmt::Assign(n, _, v) => {
                let saved = std::mem::take(&mut self.pre);
                let val = self.expr(v);
                let mut out = std::mem::replace(&mut self.pre, saved);
                let py = self.assign_target(n);
                out.push(PS::Assign(name(&py), val));
                out.extend(self.railway(rest, is_result));
                out
            }
            _ => self.railway(rest, is_result),
        }
    }
}

fn p_unused<T>(_: T) {}

/// Whether a seq block yields anywhere (in its loops too).
fn seq_yields(items: &[CeStmt]) -> bool {
    items.iter().any(|it| match it {
        CeStmt::Yield(..) | CeStmt::YieldBang(..) => true,
        CeStmt::For(_, _, body, _) => seq_yields(body),
        _ => false,
    })
}

pub fn frame_decls(frame: &FnFrame) -> Vec<PS> {
    let mut v = Vec::new();
    if !frame.globals.is_empty() {
        v.push(PS::Global(frame.globals.clone()));
    }
    if !frame.nonlocals.is_empty() {
        v.push(PS::Nonlocal(frame.nonlocals.clone()));
    }
    v
}

pub fn kw_value(v: &KwValue) -> PE {
    match v {
        KwValue::Int(n) => PE::Int(*n),
        KwValue::Float(f) => PE::Float(*f),
        KwValue::Str(s) => PE::Str(s.clone()),
        KwValue::Bool(b) => PE::Bool(*b),
        KwValue::Slot => PE::NoneV,
    }
}

fn rename_placeholder(stmts: Vec<PS>, t: &str) -> Vec<PS> {
    stmts.into_iter().map(|s| rename_stmt(s, t)).collect()
}

fn rename_stmt(s: PS, t: &str) -> PS {
    match s {
        PS::Assign(a, b) => PS::Assign(rename_expr(a, t), rename_expr(b, t)),
        other => other,
    }
}

fn rename_expr(e: PE, t: &str) -> PE {
    match e {
        PE::Name(n) if n == "\u{0}" => PE::Name(t.to_string()),
        PE::Attr(b, a) => PE::Attr(Box::new(rename_expr(*b, t)), a),
        other => other,
    }
}
