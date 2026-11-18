// Declarations: types, measures, externs, lets (with recursive groups), modules.

use crate::ast::*;
use crate::check_expr::*;
use crate::diag::Diag;
use crate::infer::*;
use crate::source::Span;
use crate::types::*;
use std::collections::{BTreeSet, HashMap, HashSet};

type R<T> = Result<T, Diag>;

impl Checker {
    /// Convert a declared type. `params` maps declared type variables; when
    /// `implicit`, unknown lowercase variables are quantified on the fly.
    pub fn conv_type(&mut self, t: &TypeExpr, params: &mut HashMap<String, Ty>, effs: &mut HashMap<String, usize>, implicit: bool) -> R<Ty> {
        match &t.kind {
            TypeKind::Var(v) => {
                if let Some(x) = params.get(v) {
                    return Ok(x.clone());
                }
                // an extern signature's own variables are lowercase words
                if implicit && v.starts_with(|c: char| c.is_ascii_lowercase()) {
                    let n = params.len();
                    params.insert(v.clone(), Ty::Gen(n));
                    return Ok(Ty::Gen(n));
                }
                Err(Diag::error(format!("unknown type `{}`", v), t.span))
            }
            TypeKind::Con(path, name, args) => {
                let full = if path.is_empty() { name.clone() } else { format!("{}.{}", path.join("."), name) };
                if path.is_empty() && name.starts_with(|c: char| c.is_ascii_uppercase()) {
                    self.ide.type_uses.push((Span::new(t.span.lo, t.span.lo + name.len()), name.clone()));
                }
                // the type itself first, then its arguments
                let arity = match full.as_str() {
                    "int" | "float" | "bool" | "string" | "unit" | "Exception" => Some(0),
                    "List" | "Set" | "Seq" | "Option" | "Async" | "Decoder" => Some(1),
                    "Map" | "Result" => Some(2),
                    _ => self.types.get(&full).map(|ti| ti.params).or_else(|| self.types.get(name).map(|ti| ti.params)),
                };
                let Some(arity) = arity else {
                    return Err(Diag::error(format!("unknown type `{}`", full), t.span));
                };
                if arity != args.len() {
                    return Err(Diag::error(format!("type `{}` expects {} argument(s), found {}", full, arity, args.len()), t.span));
                }
                let mut cargs = Vec::new();
                for a in args {
                    cargs.push(self.conv_type(a, params, effs, implicit)?);
                }
                match full.as_str() {
                    "int" | "float" => return Ok(Ty::Num(if full == "int" { Kind::Int } else { Kind::Float }, Unit::one())),
                    "bool" | "string" | "unit" => return Ok(Ty::Con(full, vec![])),
                    _ => {}
                }
                let tname = if self.types.contains_key(&full) || builtin_ty(&full) { full } else { name.clone() };
                Ok(Ty::Con(tname, cargs))
            }
            TypeKind::Fun(a, es, r) => {
                let ta = self.conv_type(a, params, effs, implicit)?;
                let tr = self.conv_type(r, params, effs, implicit)?;
                let mut eff = Eff::pure_();
                if let Some(es) = es {
                    for e in es {
                        match e.as_str() {
                            "io" | "async" | "spawn" => {
                                eff.labels.insert(self.st.label_of(e));
                            }
                            // an extern signature may leave its effect open
                            v if implicit && v.chars().next().map_or(false, |c| c.is_lowercase()) => {
                                let n = effs.len();
                                let i = *effs.entry(v.to_string()).or_insert(n);
                                eff.tail = Some(EffTail::Gen(i));
                            }
                            v => {
                                return Err(Diag::error(
                                    format!("unknown effect label `{}` (known labels: `io`, `async`; an effect variable is only allowed in an `extern` signature)", v),
                                    t.span,
                                ))
                            }
                        }
                    }
                }
                Ok(Ty::Fun(Box::new(ta), eff, Box::new(tr)))
            }
            TypeKind::Tuple(ts) => {
                let mut v = Vec::new();
                for x in ts {
                    v.push(self.conv_type(x, params, effs, implicit)?);
                }
                Ok(Ty::Tuple(v))
            }
            TypeKind::Measured(base, u) => {
                let b = self.conv_type(base, params, effs, implicit)?;
                let unit = self.resolve_unit_expr(u, t.span)?;
                match b {
                    Ty::Num(k, _) => Ok(Ty::Num(k, unit)),
                    _ => Err(Diag::error("only `int` and `float` carry units", t.span)),
                }
            }
        }
    }

    // ---- program --------------------------------------------------------

    pub fn check_program(&mut self, prog: &Program) {
        self.check_extern_modules(&prog.decls);
        self.collect_types(&prog.decls, None);
        self.collect_measures(&prog.decls);
        self.collect_externs(&prog.decls, None);
        let lets: Vec<(usize, &LetDecl)> = prog
            .decls
            .iter()
            .enumerate()
            .filter_map(|(i, d)| if let Decl::Let(l) = d { Some((i, l)) } else { None })
            .collect();
        let groups = self.recursive_groups(&prog.decls);
        let mut done: HashSet<usize> = HashSet::new();
        let _ = lets;
        for (i, d) in prog.decls.iter().enumerate() {
            match d {
                Decl::Let(_) => {
                    if done.contains(&i) {
                        continue;
                    }
                    let group = groups.get(&i).cloned().unwrap_or_else(|| vec![i]);
                    for g in &group {
                        done.insert(*g);
                    }
                    let members: Vec<&LetDecl> = group
                        .iter()
                        .map(|g| match &prog.decls[*g] {
                            Decl::Let(l) => l,
                            _ => unreachable!(),
                        })
                        .collect();
                    self.check_top_lets(&members, &prog.decls, i);
                }
                Decl::Expr(e) => {
                    self.effs.push(EffAcc::default());
                    let r = self.infer(e);
                    let acc = self.effs.pop().unwrap();
                    match r {
                        Ok(_) => {
                            if let Err(d) = self.check_spawn(&acc, e.span) {
                                self.unowned_tasks.push(d);
                            }
                        }
                        Err(d) => self.errors.push(d),
                    }
                }
                Decl::Assign(n, nspan, v, whole) => {
                    if let Err(d) = self.infer_assign(n, *nspan, v, *whole) {
                        self.errors.push(d);
                    }
                }
                Decl::Module(name, _, ds) => self.check_module(name, ds),
                _ => {}
            }
        }
        self.check_autos();
        let unowned = std::mem::take(&mut self.unowned_tasks);
        self.errors.extend(unowned);
    }

    fn check_module(&mut self, name: &str, decls: &[Decl]) {
        let saved_globals = self.globals.clone();
        // the module is known inside itself, with the members so far
        self.modules.insert(name.to_string(), ModuleExports::default());
        for d in decls {
            if let Decl::Let(l) = d {
                let members = vec![l];
                self.check_top_lets(&members, decls, 0);
                if let PatKind::Var(n) = &l.pat.kind {
                    if let Some(g) = self.globals.get(n).cloned() {
                        let exports = self.modules.get_mut(name).unwrap();
                        exports.values.insert(n.clone(), g.scheme.clone());
                        exports.order.push(n.clone());
                    }
                }
            }
        }
        self.globals = saved_globals;
    }

    /// A top-level value that starts a task no scope owns (reported at the
    /// value, `at`).
    pub fn check_spawn(&mut self, acc: &EffAcc, at: Span) -> R<()> {
        let spawns = acc.labels.iter().any(|(l, _)| *l == Label::Spawn)
            || acc.tail.map_or(false, |(v, _)| self.st.eff(&Eff::var(v)).labels.contains(&Label::Spawn));
        if spawns {
            return Err(Diag::error(
                "this starts a task outside any `Task.scope`, so nothing would own it: it performs `spawn`, which only a `Task.scope` body discharges (start the task inside `Task.scope (async { ... })`)",
                at,
            ));
        }
        Ok(())
    }

    /// Groups of mutually recursive top-level functions, keyed by every member.
    fn recursive_groups(&self, decls: &[Decl]) -> HashMap<usize, Vec<usize>> {
        recursive_groups(decls)
    }
}

/// Mutually recursive top-level functions: each member's index -> its group.
pub fn recursive_groups(decls: &[Decl]) -> HashMap<usize, Vec<usize>> {
    {
        // name -> indices defining it
        let mut defs: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, d) in decls.iter().enumerate() {
            if let Decl::Let(l) = d {
                if let PatKind::Var(n) = &l.pat.kind {
                    defs.entry(n.clone()).or_default().push(i);
                }
            }
        }
        // edges
        let n = decls.len();
        let mut edges: Vec<Vec<usize>> = vec![Vec::new(); n];
        for (i, d) in decls.iter().enumerate() {
            if let Decl::Let(l) = d {
                if l.params.is_empty() {
                    continue;
                }
                let mut fv = BTreeSet::new();
                free_vars_let(l, &mut fv);
                for v in fv {
                    if let Some(ds) = defs.get(&v) {
                        // a name stands for its last definition here
                        let target = ds.iter().max().copied();
                        if let Some(j) = target {
                            if let Decl::Let(lj) = &decls[j] {
                                if !lj.params.is_empty() {
                                    edges[i].push(j);
                                }
                            }
                        }
                    }
                }
            }
        }
        // Tarjan SCC
        let mut index = 0usize;
        let mut idx = vec![usize::MAX; n];
        let mut low = vec![0usize; n];
        let mut on = vec![false; n];
        let mut stack = Vec::new();
        let mut out: HashMap<usize, Vec<usize>> = HashMap::new();
        fn strong(
            v: usize,
            edges: &Vec<Vec<usize>>,
            index: &mut usize,
            idx: &mut Vec<usize>,
            low: &mut Vec<usize>,
            on: &mut Vec<bool>,
            stack: &mut Vec<usize>,
            out: &mut HashMap<usize, Vec<usize>>,
        ) {
            idx[v] = *index;
            low[v] = *index;
            *index += 1;
            stack.push(v);
            on[v] = true;
            for &w in &edges[v] {
                if idx[w] == usize::MAX {
                    strong(w, edges, index, idx, low, on, stack, out);
                    low[v] = low[v].min(low[w]);
                } else if on[w] {
                    low[v] = low[v].min(idx[w]);
                }
            }
            if low[v] == idx[v] {
                let mut comp = Vec::new();
                loop {
                    let w = stack.pop().unwrap();
                    on[w] = false;
                    comp.push(w);
                    if w == v {
                        break;
                    }
                }
                comp.sort();
                if comp.len() > 1 {
                    for &c in &comp {
                        out.insert(c, comp.clone());
                    }
                }
            }
        }
        for v in 0..n {
            if idx[v] == usize::MAX {
                strong(v, &edges, &mut index, &mut idx, &mut low, &mut on, &mut stack, &mut out);
            }
        }
        out
    }
}

impl Checker {
    /// Check a group of top-level lets (one, or a mutually recursive set).
    pub fn check_top_lets(&mut self, members: &[&LetDecl], _decls: &[Decl], _at: usize) {
        if members.len() == 1 {
            let l = members[0];
            self.effs.push(EffAcc::default());
            let r = self.check_one_top_let(l);
            let acc = self.effs.pop().unwrap();
            match r {
                Ok(t) => {
                    if let Err(d) = self.check_pure(l, &t, &acc) {
                        self.errors.push(d);
                        self.bind_failed(l);
                        return;
                    }
                    if let Err(d) = self.check_spawn(&acc, l.value.span) {
                        self.unowned_tasks.push(d);
                    }
                    self.bind_global_let(l, &t);
                }
                Err(d) => {
                    self.errors.push(d);
                    self.bind_failed(l);
                }
            }
            return;
        }
        // mutually recursive functions: bind all monomorphically first
        self.enter_level();
        let mut tys = Vec::new();
        for l in members {
            let t = self.st.fresh();
            if let PatKind::Var(n) = &l.pat.kind {
                let def = self.let_def(n, l.name_span, l.doc.clone());
                self.globals.insert(n.clone(), Local { scheme: Scheme::mono(t.clone()), mutable: false, def });
            }
            tys.push(t);
        }
        // each member is checked; a failed one does not stop the others
        let mut failed = vec![false; members.len()];
        let mut accs = Vec::new();
        for (i, (l, t)) in members.iter().zip(tys.iter()).enumerate() {
            self.effs.push(EffAcc::default());
            let r = self.infer_lambda_acc(&l.params, &l.value);
            let outer = self.effs.pop().unwrap();
            match r {
                Ok((ft, acc)) => {
                    if let Err(e) = self.unify(t, &ft) {
                        let d = self.uerr_diag(e, t, &ft, l.value.span);
                        self.errors.push(d);
                        failed[i] = true;
                        continue;
                    }
                    self.binding_types.insert(key(l.name_span), ft.clone());
                    accs.push((acc, outer));
                }
                Err(d) => {
                    self.errors.push(d);
                    failed[i] = true;
                }
            }
        }
        self.leave_level();
        for (i, (l, t)) in members.iter().zip(tys.iter()).enumerate() {
            if failed[i] {
                self.bind_failed(l);
            } else {
                self.bind_global_let(l, t);
            }
        }
    }

    fn bind_failed(&mut self, l: &LetDecl) {
        // a failed binding is a monomorphic unknown: later uses constrain it
        let mut names = Vec::new();
        pat_names(&l.pat, &mut names);
        for n in names {
            let t = self.st.fresh();
            let def = if let PatKind::Var(_) = &l.pat.kind { self.let_def(&n, l.name_span, l.doc.clone()) } else { crate::ide::NO_DEF };
            if def != crate::ide::NO_DEF {
                self.ide.untyped(l.name_span, crate::ide::Doc::Def(def));
            }
            self.globals.insert(n.clone(), Local { scheme: Scheme::mono(t), mutable: l.mutable, def });
            self.global_order.push(n);
        }
    }

    fn bind_global_let(&mut self, l: &LetDecl, t: &Ty) {
        if l.active.is_some() {
            // a recognizer is not generalized: every match on it shares one type
            if let PatKind::Var(n) = &l.pat.kind {
                let lvl = self.st.level;
                self.st.adjust_levels(t, lvl);
                self.globals.insert(n.clone(), Local { scheme: Scheme::mono(t.clone()), mutable: false, def: crate::ide::NO_DEF });
            }
            return;
        }
        match &l.pat.kind {
            PatKind::Var(n) => {
                let s = if l.mutable { Scheme::mono(t.clone()) } else { self.st.generalize(t) };
                let def = self.let_def(n, l.name_span, l.doc.clone());
                self.ide.item(l.name_span, &s.ty, crate::ide::Doc::Def(def));
                self.globals.insert(n.clone(), Local { scheme: s, mutable: l.mutable, def });
                self.global_order.push(n.clone());
                if !l.params.is_empty() {
                    self.fn_names.push(n.clone());
                }
            }
            PatKind::Wild => {}
            _ => {
                // (checked a level in, so the parts stay general)
                let mut binds = Vec::new();
                self.ide.in_let_pattern = true;
                self.enter_level();
                let ok = self.check_pat_collect(&l.pat, t, &mut binds).is_ok();
                self.leave_level();
                self.ide.in_let_pattern = false;
                if ok {
                    self.ide.item(l.name_span, t, crate::ide::Doc::None);
                    for (n, bt, def) in binds {
                        let s = if l.mutable { Scheme::mono(bt) } else { self.st.generalize(&bt) };
                        self.globals.insert(n.clone(), Local { scheme: s, mutable: l.mutable, def });
                        self.global_order.push(n);
                    }
                }
            }
        }
    }

    fn check_one_top_let(&mut self, l: &LetDecl) -> R<Ty> {
        if let Some(cases) = &l.active {
            return self.check_active_pattern(l, cases);
        }
        let is_fn = !l.params.is_empty();
        self.enter_level();
        let r = (|| -> R<(Ty, Option<EffAcc>)> {
            if is_fn {
                let self_t = self.st.fresh();
                self.push_scope();
                if let PatKind::Var(n) = &l.pat.kind {
                    let def = self.let_def(n, l.name_span, l.doc.clone());
                    self.bind_local_def(n, Scheme::mono(self_t.clone()), false, def);
                }
                let r = self.infer_lambda_acc(&l.params, &l.value);
                self.pop_scope();
                let (t, acc) = r?;
                self.unify_at(&self_t, &t, l.value.span)?;
                Ok((t, Some(acc)))
            } else {
                let t = self.infer(&l.value)?;
                if !matches!(l.pat.kind, PatKind::Var(_) | PatKind::Wild) {
                    let mut binds = Vec::new();
                    self.ide.in_let_pattern = true;
                    let r = self.check_pat_collect(&l.pat, &t, &mut binds);
                    self.ide.in_let_pattern = false;
                    r?;
                }
                Ok((t, None))
            }
        })();
        self.leave_level();
        let (t, acc) = r?;
        if let Some(acc) = acc {
            if l.pure_ {
                self.check_pure_acc(l, &acc)?;
            }
        }
        // (the body is checked before the binding's form is)
        mutable_params(l)?;
        self.binding_types.insert(key(l.name_span), t.clone());
        Ok(t)
    }

    fn check_pure_acc(&mut self, l: &LetDecl, acc: &EffAcc) -> R<()> {
        if let Some((lab, _)) = self.first_label(acc) {
            // reported at the body
            let sp = l.value.span;
            let name = match &l.pat.kind {
                PatKind::Var(n) => n.clone(),
                _ => "_".into(),
            };
            return Err(Diag::error(format!("`{}` is declared `pure` but performs `{}`", name, label_name(lab, &self.st.other_labels)), sp));
        }
        Ok(())
    }

    pub fn first_label(&mut self, acc: &EffAcc) -> Option<(Label, Span)> {
        if let Some((l, sp)) = acc.labels.first() {
            return Some((*l, *sp));
        }
        if let Some((v, sp)) = acc.tail {
            let e = self.st.eff(&Eff::var(v));
            if let Some(l) = e.labels.iter().next() {
                return Some((*l, sp));
            }
        }
        None
    }

    /// `let pure` on a value: nothing may be performed while computing it.
    fn check_pure(&mut self, l: &LetDecl, _t: &Ty, acc: &EffAcc) -> R<()> {
        if l.pure_ && l.params.is_empty() {
            self.check_pure_acc(l, acc)?;
        }
        Ok(())
    }

    pub fn infer_lambda_acc(&mut self, params: &[Pat], body: &Expr) -> R<(Ty, EffAcc)> {
        self.push_scope();
        self.effs.push(EffAcc::default());
        let r = (|| -> R<(Vec<Ty>, Ty)> {
            let mut pts = Vec::new();
            for p in params {
                let t = self.st.fresh();
                self.check_pat(p, &t, true)?;
                pts.push(t);
            }
            let tb = self.infer(body)?;
            Ok((pts, tb))
        })();
        let acc = self.effs.pop().unwrap();
        self.pop_scope();
        let (pts, mut t) = r?;
        let eff = self.acc_to_eff(&acc);
        let n = pts.len();
        for (i, pt) in pts.into_iter().enumerate().rev() {
            let e = if i == n - 1 { eff.clone() } else { Eff::pure_() };
            t = Ty::Fun(Box::new(pt), e, Box::new(t));
        }
        Ok((t, acc))
    }

    // ---- types ----------------------------------------------------------

    pub fn collect_types(&mut self, decls: &[Decl], module: Option<&str>) {
        for d in decls {
            match d {
                Decl::Type(t) => {
                    self.ide.user_types.insert(t.name.clone());
                }
                Decl::ExternType(n, _, _, _) => {
                    self.ide.user_types.insert(n.clone());
                }
                _ => {}
            }
        }
        // first the names
        for d in decls {
            match d {
                Decl::Type(t) => {
                    if matches!(t.name.as_str(), "List" | "Map" | "Set" | "Seq" | "Async" | "Decoder") {
                        self.errors.push(Diag::error(format!("type `{}` is already defined", t.name), t.span));
                        continue;
                    }
                    if self.types.contains_key(&t.name) && !matches!(self.types[&t.name].def, TypeDef::Builtin) {
                        // reported, and the later definition replaces the earlier
                        self.errors.push(Diag::error(format!("type `{}` is already defined", t.name), t.span));
                    }
                    let def = match &t.body {
                        TypeBody::Sum(vs) => TypeDef::Adt(vs.iter().map(|v| v.name.clone()).collect()),
                        // a record until its fields check
                        TypeBody::Record(_) => TypeDef::Adt(Vec::new()),
                        TypeBody::Opaque(_) => TypeDef::Opaque(t_unit()),
                    };
                    self.types.insert(t.name.clone(), TypeInfo { name: t.name.clone(), params: t.params.len(), def, module: module.map(|s| s.to_string()) });
                }
                Decl::ExternType(n, ps, sp, _) => {
                    let builtin = matches!(n.as_str(), "List" | "Map" | "Set" | "Seq" | "Async" | "Decoder");
                    if builtin || (self.types.contains_key(n) && !matches!(self.types[n].def, TypeDef::Builtin)) {
                        self.errors.push(Diag::error(format!("type `{}` is already defined", n), *sp));
                        continue;
                    }
                    self.types.insert(n.clone(), TypeInfo { name: n.clone(), params: ps.len(), def: TypeDef::Extern, module: module.map(|s| s.to_string()) });
                }
                _ => {}
            }
        }
        // then the bodies
        for d in decls {
            if let Decl::Type(t) = d {
                if matches!(t.name.as_str(), "List" | "Map" | "Set" | "Seq" | "Async" | "Decoder") {
                    continue;
                }
                if let Err(e) = self.type_body(t, module) {
                    self.errors.push(e);
                }
            }
        }
    }

    fn type_body(&mut self, t: &TypeDecl, module: Option<&str>) -> R<()> {
        if let Some(d) = &t.doc {
            self.ide.untyped(t.name_span, crate::ide::Doc::Text(d.clone()));
        }
        let mut params: HashMap<String, Ty> = HashMap::new();
        for (i, p) in t.params.iter().enumerate() {
            params.insert(p.clone(), Ty::Gen(i));
        }
        let mut effs = HashMap::new();
        match &t.body {
            TypeBody::Sum(vs) => {
                for (i, v) in vs.iter().enumerate() {
                    if self.ctors.contains_key(&v.name) || vs[..i].iter().any(|w| w.name == v.name) {
                        self.errors.push(Diag::error(format!("constructor `{}` is already defined", v.name), t.span));
                        continue;
                    }
                    // a case whose argument types do not check is left out;
                    // the others stand
                    // (each argument that does not check is reported)
                    let mut args = Vec::new();
                    let mut bad = false;
                    for a in &v.args {
                        match self.conv_type(a, &mut params, &mut effs, false) {
                            Ok(x) => args.push(x),
                            Err(d) => {
                                self.errors.push(at(d, t.span));
                                bad = true;
                            }
                        }
                    }
                    if bad {
                        continue;
                    }
                    self.ctors.insert(
                        v.name.clone(),
                        CtorInfo { name: v.name.clone(), type_name: t.name.clone(), index: i, args, params: t.params.len(), module: module.map(|s| s.to_string()) },
                    );
                }
            }
            TypeBody::Record(fs) => {
                // (each field that does not check is reported; the record
                // stands only when they all do)
                let mut fields = Vec::new();
                let mut seen: Vec<&String> = Vec::new();
                let mut bad = false;
                for (n, _, ft) in fs {
                    if seen.contains(&n) {
                        self.errors.push(Diag::error(format!("field `{}` is declared twice in record `{}`", n, t.name), t.span));
                        bad = true;
                        continue;
                    }
                    seen.push(n);
                    match self.conv_type(ft, &mut params, &mut effs, false) {
                        Ok(ty) => fields.push((n.clone(), ty)),
                        Err(d) => {
                            self.errors.push(at(d, t.span));
                            bad = true;
                        }
                    }
                }
                if bad {
                    return Ok(());
                }
                for (n, _) in &fields {
                    // (this module's records come before imported ones)
                    let at = {
                        let owners = self.fields.get(n).cloned().unwrap_or_default();
                        owners.iter().position(|o| self.types.get(o).map_or(false, |ti| ti.module.is_some())).unwrap_or(owners.len())
                    };
                    self.fields.entry(n.clone()).or_default().insert(at, t.name.clone());
                }
                if let Some(ti) = self.types.get_mut(&t.name) {
                    ti.def = TypeDef::Record(fields);
                }
            }
            TypeBody::Opaque(under) => {
                if self.ctors.contains_key(&t.name) {
                    return Err(Diag::error(format!("constructor `{}` is already defined", t.name), t.span));
                }
                let ty = self.conv_type(under, &mut params, &mut effs, false).map_err(|d| at(d, t.span))?;
                if let Some(ti) = self.types.get_mut(&t.name) {
                    ti.def = TypeDef::Opaque(ty.clone());
                }
                self.ctors.insert(
                    t.name.clone(),
                    CtorInfo { name: t.name.clone(), type_name: t.name.clone(), index: 0, args: vec![ty], params: t.params.len(), module: module.map(|s| s.to_string()) },
                );
            }
        }
        Ok(())
    }

    // ---- measures -------------------------------------------------------

    fn collect_measures(&mut self, decls: &[Decl]) {
        for d in decls {
            if let Decl::Measure(n, None, sp) = d {
                if self.measures.contains_key(n) {
                    self.errors.push(Diag::error(format!("measure `{}` is already defined", n), *sp));
                    continue;
                }
                self.measures.insert(n.clone(), None);
            }
        }
        for d in decls {
            if let Decl::Measure(n, Some(u), sp) = d {
                if self.measures.contains_key(n) {
                    self.errors.push(Diag::error(format!("measure `{}` is already defined", n), *sp));
                    continue;
                }
                match self.resolve_unit_expr(u, *sp) {
                    Ok(unit) => {
                        self.measures.insert(n.clone(), Some(unit));
                    }
                    Err(e) => self.errors.push(e),
                }
            }
        }
    }

    // ---- externs --------------------------------------------------------

    /// A dotted extern target must say which part is the Python module:
    /// `a.b.c` could be module `a` with attribute path `b.c`, or module `a.b`.
    pub fn check_extern_modules(&mut self, decls: &[Decl]) {
        let imports: Vec<(&Vec<String>, &Option<String>)> = decls
            .iter()
            .filter_map(|d| if let Decl::ExternImport(p, a, _) = d { Some((p, a)) } else { None })
            .collect();
        for d in decls {
            let Decl::Extern(e) = d else { continue };
            let Some(ExternTarget::Path(path)) = &e.target else { continue };
            if path.len() < 3 {
                continue;
            }
            let declared = imports.iter().any(|(p, a)| match a {
                Some(a) => &path[0] == a,
                None => path.len() >= p.len() && path[..p.len()] == p[..],
            });
            if declared {
                continue;
            }
            let Some(i) = (1..path.len() - 1).find(|&i| path[i].chars().next().map_or(false, |c| c.is_lowercase())) else { continue };
            let full = path.join(".");
            self.errors.push(Diag::error(
                format!(
                    "cannot tell which part of `{}` names the module: `{}` is lowercase, so it could be a submodule (like `os.path`) or an object (like `sys.stdout`), and only the running environment knows which; declare it with `extern import {}` — or `extern import {}` if `{}` really is a module",
                    full,
                    path[i],
                    path[0],
                    path[..=i].join("."),
                    path[i]
                ),
                e.span,
            ));
        }
    }

    pub fn collect_externs(&mut self, decls: &[Decl], _module: Option<&str>) {
        let mut seen: HashSet<&str> = HashSet::new();
        for d in decls {
            if let Decl::Extern(e) = d {
                // a library name or an earlier extern's cannot be taken again
                let library = crate::builtins::BUILTINS.iter().any(|b| b.name == e.name) || self.ctors.contains_key(&e.name);
                if library || !seen.insert(e.name.as_str()) {
                    self.errors.push(Diag::error(format!("`{}` is already defined", e.name), e.span));
                    continue;
                }
                match self.extern_type(e) {
                    Ok(t) => {
                        let def = self.let_def(&e.name, e.span, e.doc.clone());
                        self.globals.insert(e.name.clone(), Local { scheme: Scheme::mono(t.clone()), mutable: false, def });
                        self.extern_effects.insert(e.name.clone(), t);
                    }
                    // an extern whose type does not check is not bound
                    Err(d) => self.errors.push(d),
                }
            }
        }
    }

    pub fn extern_type(&mut self, e: &ExternDecl) -> R<Ty> {
        let mut params = HashMap::new();
        let mut effs = HashMap::new();
        let t = self.conv_type(&e.ty, &mut params, &mut effs, true).map_err(|d| at(d, e.span))?;
        // explicit effects anywhere?
        let explicit = has_explicit_effects(&e.ty);
        let t = if e.pure_ || explicit {
            t
        } else {
            // a bare extern is `io` at full application
            let io = self.st.label_of("io");
            add_final_label(&t, io)
        };
        // `->{async}` must return Async
        if let Some(bad) = async_without_async(&t) {
            let rt = self.st.show(&bad);
            return Err(Diag::error(
                format!(
                    "`{}` is declared `->{{async}}` but returns `{}`, which cannot be awaited: an async Python function returns a coroutine, so declare the result as `Async {}` (`… -> Async {}`) and bind it with `let!` inside an `async {{ }}` block",
                    e.name, rt, rt, rt
                ),
                e.span,
            ));
        }
        Ok(t)
    }

    // ---- active patterns ------------------------------------------------

    fn check_active_pattern(&mut self, l: &LetDecl, cases: &[String]) -> R<Ty> {
        let partial = cases.last().map_or(false, |c| c == "_");
        let names: Vec<String> = cases.iter().filter(|c| *c != "_").cloned().collect();
        let tag = format!("(|{}|)", cases.join("|"));
        let mut temp = Vec::new();
        if !partial {
            // each case's shape comes from how the body constructs it
            let mut arities: Vec<Option<usize>> = vec![None; names.len()];
            scan_case_arities(&l.value, &names, &mut arities);
            for (i, n) in names.iter().enumerate() {
                if arities[i].is_none() {
                    return Err(Diag::error(format!("active-pattern case `{}` is never constructed in the body, so its shape cannot be inferred", n), l.span));
                }
            }
            let total: usize = arities.iter().map(|a| a.unwrap()).sum();
            self.types.insert(tag.clone(), TypeInfo { name: tag.clone(), params: total, def: TypeDef::Adt(names.clone()), module: None });
            let mut off = 0;
            for (i, n) in names.iter().enumerate() {
                let k = arities[i].unwrap();
                let c = CtorInfo { name: n.clone(), type_name: tag.clone(), index: i, args: (off..off + k).map(Ty::Gen).collect(), params: total, module: None };
                off += k;
                temp.push((n.clone(), self.ctors.insert(n.clone(), c.clone())));
                self.active_ctors.insert(n.clone(), c);
            }
        }
        self.enter_level();
        let r = self.infer_lambda_acc(&l.params, &l.value);
        self.leave_level();
        for (n, old) in temp {
            match old {
                Some(o) => {
                    self.ctors.insert(n, o);
                }
                None => {
                    self.ctors.remove(&n);
                }
            }
        }
        // a total pattern's cases are known even when the body does not
        // check (a partial one's shape comes from its body)
        if !partial {
            self.active_patterns.insert(tag.clone(), (names.clone(), partial));
            for n in &names {
                self.active_cases.insert(n.clone(), tag.clone());
            }
        }
        let (t, _) = r?;
        if partial {
            // the body is an Option (binding the payload) or a bool (a predicate)
            let mut res = self.st.resolve(&t);
            for _ in 0..l.params.len() {
                if let Ty::Fun(_, _, r) = res {
                    res = self.st.resolve(&r);
                }
            }
            let ok = matches!(&res, Ty::Con(n, _) if n == "Option" || n == "bool");
            if !ok {
                let shown = self.st.show_with(&res, &mut Namer::default());
                return Err(Diag::error(format!("a partial active pattern's body must return `Option a` (a binding case) or `bool` (a predicate), found {}", shown), l.value.span));
            }
        }
        if !partial {
            // each case named in the header is a constructor of the result
            let mut res = self.st.resolve(&t);
            for _ in 0..l.params.len() {
                if let Ty::Fun(_, _, r) = res {
                    res = self.st.resolve(&r);
                }
            }
            if let Ty::Con(_, args) = &res {
                let mut off = 0;
                for (n, sp) in cases.iter().zip(&l.case_spans) {
                    let Some(c) = self.active_ctors.get(n).cloned() else { continue };
                    let k = c.args.len();
                    let mut ct = res.clone();
                    for a in args.iter().skip(off).take(k).rev() {
                        ct = Ty::Fun(Box::new(a.clone()), Eff::pure_(), Box::new(ct));
                    }
                    off += k;
                    self.ide.item(*sp, &ct, crate::ide::Doc::None);
                }
            }
        }
        self.active_patterns.insert(tag.clone(), (names.clone(), partial));
        for n in &names {
            self.active_cases.insert(n.clone(), tag.clone());
        }
        if partial {
            self.active_params.insert(tag.clone(), l.params.len().saturating_sub(1));
        }
        Ok(t)
    }
}

fn scan_case_arities(e: &Expr, names: &[String], out: &mut Vec<Option<usize>>) {
    // find `Case a b` applications and bare `Case`
    let mut args = 0;
    let mut f = e;
    while let ExprKind::App(g, a) = &f.kind {
        scan_case_arities(a, names, out);
        args += 1;
        f = g;
    }
    if let ExprKind::Ctor(p, n) = &f.kind {
        if p.is_empty() {
            if let Some(i) = names.iter().position(|x| x == n) {
                if out[i].is_none() {
                    out[i] = Some(args);
                }
            }
        }
        return;
    }
    if args > 0 {
        scan_case_arities(f, names, out);
        return;
    }
    crate::shadow::each_child(e, &mut |c| scan_case_arities(c, names, out));
}

pub fn builtin_ty(n: &str) -> bool {
    matches!(n, "List" | "Set" | "Seq" | "Option" | "Async" | "Decoder" | "Map" | "Result" | "Exception")
}

fn has_explicit_effects(t: &TypeExpr) -> bool {
    match &t.kind {
        TypeKind::Fun(a, es, r) => es.is_some() || has_explicit_effects(a) || has_explicit_effects(r),
        _ => false,
    }
}

fn add_final_label(t: &Ty, l: Label) -> Ty {
    match t {
        Ty::Fun(a, e, r) => {
            if let Ty::Fun(..) = **r {
                Ty::Fun(a.clone(), e.clone(), Box::new(add_final_label(r, l)))
            } else {
                let mut e = e.clone();
                e.labels.insert(l);
                Ty::Fun(a.clone(), e, r.clone())
            }
        }
        other => other.clone(),
    }
}

fn async_without_async(t: &Ty) -> Option<Ty> {
    match t {
        Ty::Fun(_, e, r) => {
            if e.labels.contains(&Label::Async) {
                if let Ty::Fun(..) = **r {
                    return async_without_async(r);
                }
                match &**r {
                    Ty::Con(n, _) if n == "Async" => None,
                    other => Some(other.clone()),
                }
            } else {
                async_without_async(r)
            }
        }
        _ => None,
    }
}

pub fn pat_names(p: &Pat, out: &mut Vec<String>) {
    match &p.kind {
        PatKind::Var(n) => out.push(n.clone()),
        PatKind::Tuple(ps) | PatKind::Or(ps) => {
            for x in ps {
                pat_names(x, out);
            }
        }
        PatKind::Ctor(_, _, ps) => {
            for x in ps {
                pat_names(x, out);
            }
        }
        PatKind::List(es) => {
            for e in es {
                match e {
                    ListPatElem::Pat(x) => pat_names(x, out),
                    ListPatElem::Star(Some(n), _) => out.push(n.clone()),
                    _ => {}
                }
            }
        }
        PatKind::Record(_, _, _, fs) => {
            for (f, _, sp) in fs {
                match sp {
                    Some(x) => pat_names(x, out),
                    None => out.push(f.clone()),
                }
            }
        }
        PatKind::As(x, n, _) => {
            pat_names(x, out);
            out.push(n.clone());
        }
        _ => {}
    }
}

/// Free variables of a let's body (names not bound inside it).
pub fn free_vars_let(l: &LetDecl, out: &mut BTreeSet<String>) {
    let mut bound: Vec<String> = Vec::new();
    for p in &l.params {
        pat_names(p, &mut bound);
    }
    fv_expr(&l.value, &mut bound, out);
}

fn fv_expr(e: &Expr, bound: &mut Vec<String>, out: &mut BTreeSet<String>) {
    match &e.kind {
        ExprKind::Var(n) => {
            if !bound.contains(n) {
                out.insert(n.clone());
            }
        }
        ExprKind::FStr(parts) => {
            for p in parts {
                if let FPart::Expr(x) = p {
                    fv_expr(x, bound, out);
                }
            }
        }
        ExprKind::Field(b, _, _) => fv_expr(b, bound, out),
        ExprKind::App(f, a) => {
            fv_expr(f, bound, out);
            fv_expr(a, bound, out);
        }
        ExprKind::Binary(_, l, r) => {
            fv_expr(l, bound, out);
            fv_expr(r, bound, out);
        }
        ExprKind::Chain(f, rest) => {
            fv_expr(f, bound, out);
            for (_, x) in rest {
                fv_expr(x, bound, out);
            }
        }
        ExprKind::Neg(x) | ExprKind::Not(x) | ExprKind::Try(x) | ExprKind::Measured(x, _) => fv_expr(x, bound, out),
        ExprKind::If(c, a, b) => {
            fv_expr(c, bound, out);
            fv_expr(a, bound, out);
            fv_expr(b, bound, out);
        }
        ExprKind::Match(s, arms) => {
            fv_expr(s, bound, out);
            for a in arms {
                let n = bound.len();
                pat_names(&a.pat, bound);
                if let Some(g) = &a.guard {
                    fv_expr(g, bound, out);
                }
                fv_expr(&a.body, bound, out);
                bound.truncate(n);
            }
        }
        ExprKind::Lambda(ps, b) => {
            let n = bound.len();
            for p in ps {
                pat_names(p, bound);
            }
            fv_expr(b, bound, out);
            bound.truncate(n);
        }
        ExprKind::Block(stmts) => {
            let n = bound.len();
            for s in stmts {
                match s {
                    Stmt::Let(l) => {
                        let m = bound.len();
                        if !l.params.is_empty() {
                            pat_names(&l.pat, bound);
                        }
                        for p in &l.params {
                            pat_names(p, bound);
                        }
                        fv_expr(&l.value, bound, out);
                        bound.truncate(m);
                        pat_names(&l.pat, bound);
                    }
                    Stmt::Assign(n2, _, v, _) => {
                        if !bound.contains(n2) {
                            out.insert(n2.clone());
                        }
                        fv_expr(v, bound, out);
                    }
                    Stmt::Expr(x) => fv_expr(x, bound, out),
                }
            }
            bound.truncate(n);
        }
        ExprKind::Tuple(xs) | ExprKind::List(xs) => {
            for x in xs {
                fv_expr(x, bound, out);
            }
        }
        ExprKind::Record(_, _, _, fs) => {
            for (_, _, x) in fs {
                fv_expr(x, bound, out);
            }
        }
        ExprKind::Update(b, fs) => {
            fv_expr(b, bound, out);
            for (_, x) in fs {
                fv_expr(x, bound, out);
            }
        }
        ExprKind::Ce(_, _, items) => {
            let n = bound.len();
            fv_ce(items, bound, out);
            bound.truncate(n);
        }
        _ => {}
    }
}

fn fv_ce(items: &[CeStmt], bound: &mut Vec<String>, out: &mut BTreeSet<String>) {
    for it in items {
        match it {
            CeStmt::LetBang(p, e, _) => {
                fv_expr(e, bound, out);
                pat_names(p, bound);
            }
            CeStmt::Let(l) => {
                let m = bound.len();
                for p in &l.params {
                    pat_names(p, bound);
                }
                fv_expr(&l.value, bound, out);
                bound.truncate(m);
                pat_names(&l.pat, bound);
            }
            CeStmt::DoBang(e, _) | CeStmt::Return(e, _) | CeStmt::ReturnBang(e, _) | CeStmt::Yield(e, _) | CeStmt::YieldBang(e, _) => fv_expr(e, bound, out),
            CeStmt::For(p, src, body, _) => {
                fv_expr(src, bound, out);
                let m = bound.len();
                pat_names(p, bound);
                fv_ce(body, bound, out);
                bound.truncate(m);
            }
            CeStmt::Assign(n, _, v) => {
                if !bound.contains(n) {
                    out.insert(n.clone());
                }
                fv_expr(v, bound, out);
            }
        }
    }
}

/// A diagnostic moved to the declaration it belongs to.
fn at(mut d: Diag, span: Span) -> Diag {
    d.span = span;
    d
}

/// `let mut f x = ...` is not a thing.
pub fn mutable_params(l: &LetDecl) -> Result<(), Diag> {
    if l.mutable && !l.params.is_empty() {
        if let PatKind::Var(n) = &l.pat.kind {
            return Err(Diag::error(format!("a mutable binding cannot take parameters (`{}` is `let mut`)", n), l.value.span));
        }
    }
    Ok(())
}
