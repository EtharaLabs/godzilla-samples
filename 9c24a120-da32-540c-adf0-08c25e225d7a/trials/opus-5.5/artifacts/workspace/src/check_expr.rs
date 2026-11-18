// Expression inference.

use crate::ast::*;
use crate::diag::Diag;
use crate::infer::*;
use crate::source::Span;
use crate::types::*;
use std::collections::HashMap;

type R<T> = Result<T, Diag>;

pub fn t_con(n: &str) -> Ty {
    Ty::Con(n.to_string(), vec![])
}
pub fn t_bool() -> Ty {
    t_con("bool")
}
pub fn t_string() -> Ty {
    t_con("string")
}
pub fn t_unit() -> Ty {
    t_con("unit")
}
pub fn t_int() -> Ty {
    Ty::Num(Kind::Int, Unit::one())
}
pub fn t_float() -> Ty {
    Ty::Num(Kind::Float, Unit::one())
}

pub const BUILTIN_MODULES: &[&str] = &["List", "Set", "Map", "Option", "Result", "Seq", "String", "Format", "Decode", "Async", "Task", "Encode"];

impl Checker {
    pub fn record_type(&mut self, span: Span, t: &Ty) {
        self.expr_types.insert(key(span), t.clone());
    }

    pub fn infer(&mut self, e: &Expr) -> R<Ty> {
        let t = self.infer_inner(e)?;
        self.record_type(e.span, &t);
        let doc = match &e.kind {
            ExprKind::Var(_) | ExprKind::Qual(..) => std::mem::replace(&mut self.pending_doc, crate::ide::Doc::None),
            _ => crate::ide::Doc::None,
        };
        self.ide.item(e.span, &t, doc);
        Ok(t)
    }

    fn infer_inner(&mut self, e: &Expr) -> R<Ty> {
        match &e.kind {
            ExprKind::Int(_) => {
                let k = self.st.fresh_kind();
                self.lit_kinds.insert(key(e.span), k);
                Ok(Ty::Num(k, Unit::one()))
            }
            ExprKind::Float(_) => Ok(t_float()),
            ExprKind::Str(_) => Ok(t_string()),
            ExprKind::FStr(parts) => {
                for p in parts {
                    if let FPart::Expr(x) = p {
                        self.infer(x)?;
                    }
                }
                Ok(t_string())
            }
            ExprKind::Bool(_) => Ok(t_bool()),
            ExprKind::Unit => Ok(t_unit()),
            ExprKind::Measured(lit, u) => {
                let unit = self.resolve_unit_expr(u, e.span)?;
                let kind = match lit.kind {
                    ExprKind::Float(_) => Kind::Float,
                    _ => {
                        let k = self.st.fresh_kind();
                        self.lit_kinds.insert(key(lit.span), k);
                        k
                    }
                };
                // the number itself, before its unit
                self.ide.item(lit.span, &Ty::Num(kind, Unit::one()), crate::ide::Doc::None);
                Ok(Ty::Num(kind, unit))
            }
            ExprKind::Var(n) => self.infer_var(n, e.span),
            ExprKind::Ctor(path, n) => self.infer_ctor(path, n, e.span),
            ExprKind::Qual(path, n, nspan) => self.infer_qual(path, n, e.span, nspan.lo),
            ExprKind::Field(base, f, _) => self.infer_field(base, f, e.span),
            ExprKind::App(..) => self.infer_app(e),
            ExprKind::Binary(op, l, r) => self.infer_binary(*op, l, r, e.span),
            ExprKind::Chain(first, rest) => self.infer_chain(first, rest, e.span),
            ExprKind::Neg(x) => {
                let t = self.infer(x)?;
                self.expect_num(&t, x)
            }
            ExprKind::Not(x) => {
                let t = self.infer(x)?;
                self.unify_at(&t_bool(), &t, x.span)?;
                Ok(t_bool())
            }
            ExprKind::Try(x) => {
                let t = self.infer(x)?;
                Ok(Ty::Con("Result".into(), vec![t, t_con("Exception")]))
            }
            ExprKind::If(c, a, b) => {
                let tc = self.infer(c)?;
                self.unify_at(&t_bool(), &tc, c.span)?;
                let ta = self.infer(a)?;
                let tb = self.infer(b)?;
                self.unify_at(&ta, &tb, b.span)?;
                Ok(ta)
            }
            ExprKind::Match(scrut, arms) => self.infer_match(scrut, arms, e.span),
            ExprKind::Lambda(params, body) => self.infer_lambda(params, body),
            ExprKind::Block(stmts) => self.infer_block(stmts),
            ExprKind::Tuple(items) => {
                let mut ts = Vec::new();
                for i in items {
                    ts.push(self.infer(i)?);
                }
                Ok(Ty::Tuple(ts))
            }
            ExprKind::List(items) => {
                let elem = self.st.fresh();
                let mut first: Option<Ty> = None;
                for i in items {
                    let t = self.infer(i)?;
                    match &first {
                        None => {
                            self.unify_at(&elem, &t, i.span)?;
                            first = Some(t);
                        }
                        Some(f) => {
                            let f = f.clone();
                            self.unify_at(&f, &t, i.span)?;
                        }
                    }
                }
                Ok(Ty::Con("List".into(), vec![elem]))
            }
            ExprKind::Record(path, name, cspan, fields) => self.infer_record(path, name, *cspan, fields, e.span),
            ExprKind::Update(base, fields) => self.infer_update(base, fields, e.span),
            ExprKind::Section(op) => {
                let t = self.section_type(*op);
                // a section is a two-parameter function over the whole `(op)`
                if let Ty::Fun(a, _, _) = &t {
                    self.ide.item(e.span, a, crate::ide::Doc::None);
                }
                Ok(t)
            }
            ExprKind::Assign(n, ns, v) => {
                self.infer_assign(n, *ns, v, e.span)?;
                Ok(t_unit())
            }
            ExprKind::Hole(n) => {
                let t = self.st.fresh();
                let mut scope = Vec::new();
                for g in &self.global_order {
                    if let Some(l) = self.globals.get(g) {
                        scope.push((g.clone(), l.scheme.clone()));
                    }
                }
                let mut ext: Vec<(&String, &Local)> = self.globals.iter().filter(|(k, _)| !self.global_order.contains(k)).collect();
                ext.sort_by(|a, b| a.0.cmp(b.0));
                for (k, l) in ext {
                    scope.push((k.clone(), l.scheme.clone()));
                }
                let mut mods: Vec<(&String, &ModuleExports)> = self.modules.iter().collect();
                mods.sort_by(|a, b| a.0.cmp(b.0));
                for (m, me) in mods {
                    for k in &me.order {
                        if let Some(sc) = me.values.get(k) {
                            scope.push((format!("{}.{}", m, k), sc.clone()));
                        }
                    }
                }
                for s in &self.scopes {
                    let mut v: Vec<(&String, &Local)> = s.iter().collect();
                    v.sort_by(|a, b| a.0.cmp(b.0));
                    for (k, l) in v {
                        scope.push((k.clone(), l.scheme.clone()));
                    }
                }
                self.holes.push(HoleInfo { name: n.clone(), span: e.span, ty: t.clone(), scope });
                Ok(t)
            }
            ExprKind::Ce(path, name, items) => self.infer_ce(path, name, items, e.span),
        }
    }

    pub fn resolve_unit_expr(&mut self, u: &UnitExpr, span: Span) -> R<Unit> {
        let mut out = Unit::one();
        for (n, e) in &u.num {
            out = out.mul(&self.measure_unit(n, span)?.pow(*e));
        }
        for (n, e) in &u.den {
            out = out.mul(&self.measure_unit(n, span)?.pow(-*e));
        }
        Ok(out)
    }

    pub fn measure_unit(&mut self, n: &str, span: Span) -> R<Unit> {
        match self.measures.get(n) {
            Some(None) => Ok(Unit::atom(UAtom::Base(n.to_string()))),
            Some(Some(u)) => Ok(u.clone()),
            None => Err(Diag::error(format!("unknown measure `{}`", n), span)),
        }
    }

    /// Instantiate a builtin, recording comparison requirements.
    pub fn inst_builtin(&mut self, full: &str, s: &Scheme) -> Ty {
        let mut inst = Inst::default();
        let t = self.st.inst_ty(&s.ty, &mut inst);
        if let Some(g) = builtin_ord_gen(full) {
            if let Some(v) = inst.t.get(&g) {
                self.ordered.push(v.clone());
                if let Ty::Var(x) = v {
                    self.st.tord[*x] = true;
                }
            }
        }
        t
    }

    pub fn infer_var(&mut self, n: &str, span: Span) -> R<Ty> {
        self.pending_doc = crate::ide::Doc::None;
        if let Some(l) = self.lookup_local(n) {
            let s = l.scheme.clone();
            let def = l.def;
            if def != crate::ide::NO_DEF {
                self.ide.uses.push((span, def));
                self.pending_doc = crate::ide::Doc::Def(def);
            }
            return Ok(self.st.instantiate(&s));
        }
        if let Some(s) = self.builtins.get(n) {
            let s = s.clone();
            self.pending_doc = crate::ide::Doc::Builtin(n.to_string());
            self.ide.builtin_uses.push((span, n.to_string()));
            return Ok(self.inst_builtin(n, &s));
        }
        self.ide.unbound_uses.push((span, n.to_string()));
        // a Python builtin someone reached for
        let hint = match n {
            "int" => Some("`String.toInt`, which returns an `Option`"),
            "str" => Some("`String.fromInt` or `String.fromFloat` (or an f-string)"),
            "float" => Some("`String.toFloat`, which returns an `Option`"),
            "len" => Some("`List.len` for a list, `String.len` for a string"),
            "range" => Some("`List.range`"),
            "sum" => Some("`List.sum`"),
            "map" => Some("`List.map`"),
            "filter" => Some("`List.filter`"),
            "zip" => Some("`List.zip`"),
            "sorted" => Some("`List.sort`"),
            "reversed" => Some("`List.rev`"),
            "enumerate" => Some("`List.indexed`"),
            "any" => Some("`List.exists`"),
            "all" => Some("`List.forall`"),
            _ => None,
        };
        if let Some(h) = hint {
            return Err(Diag::error(format!("unbound name `{}` (Pyfun spells this {})", n, h), span));
        }
        Err(Diag::error(format!("unbound name `{}`", n), span))
    }

    pub fn ctor_type(&mut self, c: &CtorInfo) -> Ty {
        let mut inst = Inst::default();
        let params: Vec<Ty> = (0..c.params).map(|i| self.st.inst_ty(&Ty::Gen(i), &mut inst)).collect();
        let mut t = Ty::Con(c.type_name.clone(), params);
        for a in c.args.iter().rev() {
            let at = self.st.inst_ty(a, &mut inst);
            t = Ty::Fun(Box::new(at), Eff::pure_(), Box::new(t));
        }
        t
    }

    pub fn lookup_ctor(&self, path: &[String], n: &str) -> Option<CtorInfo> {
        if path.is_empty() {
            self.ctors.get(n).cloned()
        } else {
            let full = format!("{}.{}", path.join("."), n);
            self.ctors.get(&full).cloned()
        }
    }

    fn infer_ctor(&mut self, path: &[String], n: &str, span: Span) -> R<Ty> {
        if path.len() > 1 {
            return Err(self.deep_path_error(path, span, span.hi - n.len()));
        }
        match self.lookup_ctor(path, n) {
            Some(c) => {
                if path.is_empty() {
                    self.ide.ctor_uses.push((span, n.to_string()));
                }
                // opaque wrappers are identity functions on the underlying type
                Ok(self.ctor_type(&c))
            }
            None => {
                if path.is_empty() {
                    // a capitalized parameter
                    if self.lookup_local(n).is_some() {
                        return self.infer_var(n, span);
                    }
                    if BUILTIN_MODULES.contains(&n) || self.modules.contains_key(n) {
                        return Err(Diag::error(format!("`{}` is a module; use `{}.member`", n, n), span));
                    }
                    Err(Diag::error(format!("unbound name `{}`", n), span))
                } else {
                    Err(self.member_error(&path.join("."), n, span))
                }
            }
        }
    }

    /// `A.B.c`: modules do not nest, so `B` is what is missing.
    /// `A.B.x` where `A` has no member `B`; `next` is where the part after
    /// `B` starts (the report covers `A.B` as written).
    /// `A.B.c` where `A.B` is no module: reported over `A.B` as written.
    fn deep_path_error(&self, path: &[String], span: Span, next: usize) -> Diag {
        let written = self.source.get(span.lo..).and_then(|rest| {
            let b = rest.as_bytes();
            let mut i = path[0].len();
            while i < b.len() && (b[i] == b' ' || b[i] == b'\t' || b[i] == b'\n' || b[i] == b'\r' || b[i] == b'.') {
                i += 1;
            }
            rest[i..].starts_with(path[1].as_str()).then(|| span.lo + i + path[1].len())
        });
        let hi = match written {
            Some(hi) => hi,
            None if path.len() == 2 && next > span.lo => next - 1,
            None => span.lo + path[0].len() + 1 + path[1].len(),
        };
        self.member_error(&path[0], &path[1], Span::new(span.lo, hi))
    }

    fn infer_qual(&mut self, path: &[String], n: &str, span: Span, nlo: usize) -> R<Ty> {
        self.pending_doc = crate::ide::Doc::None;
        if path.len() > 1 {
            return Err(self.deep_path_error(path, span, nlo));
        }
        let m = path.join(".");
        if BUILTIN_MODULES.contains(&m.as_str()) {
            let full = format!("{}.{}", m, n);
            if let Some(s) = self.builtins.get(&full) {
                let s = s.clone();
                self.pending_doc = crate::ide::Doc::Builtin(full.clone());
                let t = self.inst_builtin(&full, &s);
                if full == "Decode.auto" {
                    // never generalized: a later use may be what fixes it
                    self.st.adjust_levels(&t, 0);
                    self.auto_types.push((span, t.clone(), false));
                }
                return Ok(t);
            }
            return Err(self.member_error(&m, n, span));
        }
        if let Some(me) = self.modules.get(&m) {
            if let Some(s) = me.values.get(n) {
                let s = s.clone();
                return Ok(self.st.instantiate(&s));
            }
        }
        Err(self.member_error(&m, n, span))
    }

    fn member_error(&self, m: &str, n: &str, span: Span) -> Diag {
        Diag::error(
            match self.suggest_member(m, n) {
                Some(s) => format!("`{}` is not a member of `{}` (did you mean `{}.{}`?)", n, m, m, s),
                None => format!("`{}` is not a member of `{}`", n, m),
            },
            span,
        )
    }

    fn suggest_member(&self, m: &str, n: &str) -> Option<String> {
        let members: Vec<String> = if BUILTIN_MODULES.contains(&m) {
            let prefix = format!("{}.", m);
            crate::builtins::BUILTINS.iter().filter_map(|b| b.name.strip_prefix(&prefix)).map(|x| x.to_string()).collect()
        } else if let Some(me) = self.modules.get(m) {
            // its values, then its constructors
            let mut v = me.order.clone();
            let prefix = format!("{}.", m);
            let mut ctors: Vec<String> = self.ctors.keys().filter_map(|k| k.strip_prefix(&prefix)).map(|k| k.to_string()).collect();
            ctors.sort();
            v.extend(ctors);
            v
        } else {
            Vec::new()
        };
        // the same name in another case
        if let Some(c) = members.iter().find(|c| c.to_lowercase() == n.to_lowercase()) {
            return Some(c.clone());
        }
        // the closest; close enough within a third of the longer name (at
        // least 2 edits), or when one name starts the other. Among
        // equally close members the pick is arbitrary: when any of them would
        // not be offered, offering none is the likeliest outcome
        let dists: Vec<usize> = members.iter().map(|c| levenshtein(n, c)).collect();
        let best = *dists.iter().min()?;
        let offered = |c: &String| {
            let limit = 2usize.max(n.chars().count().max(c.chars().count()) / 3);
            // (a start of three letters or more)
            best <= limit || (c.chars().count() >= 3 && n.starts_with(c.as_str())) || (n.chars().count() >= 3 && c.starts_with(n))
        };
        let tied: Vec<&String> = members.iter().zip(dists.iter()).filter(|(_, d)| **d == best).map(|(c, _)| c).collect();
        if tied.iter().all(|c| offered(c)) {
            tied.first().map(|c| c.to_string())
        } else {
            None
        }
    }

    pub fn expect_num(&mut self, t: &Ty, operand: &Expr) -> R<Ty> {
        let r = self.st.shallow(t);
        match r {
            Ty::Num(..) => Ok(r),
            Ty::Var(_) => {
                let n = self.st.fresh_num();
                let n = Ty::Num(
                    match n {
                        Ty::Num(k, _) => k,
                        _ => unreachable!(),
                    },
                    self.st.fresh_unit(),
                );
                let _ = self.unify(t, &n);
                Ok(self.st.shallow(&n))
            }
            _ => Err(Diag::error(format!("expected int, found {}", self.st.show(t)), operand.span)),
        }
    }

    fn infer_binary(&mut self, op: BinOp, l: &Expr, r: &Expr, span: Span) -> R<Ty> {
        match op {
            BinOp::And | BinOp::Or => {
                let tl = self.infer(l)?;
                self.unify_at(&t_bool(), &tl, l.span)?;
                let tr = self.infer(r)?;
                self.unify_at(&t_bool(), &tr, r.span)?;
                Ok(t_bool())
            }
            BinOp::PipeRight => {
                // x |> f  ==  f x: the function is checked first (an
                // application piped into takes the value as its last argument)
                let tf = match &r.kind {
                    ExprKind::App(..) => {
                        let t = self.infer_spine(r, true)?;
                        self.record_type(r.span, &t);
                        self.ide.item(r.span, &t, crate::ide::Doc::None);
                        t
                    }
                    _ => self.infer(r)?,
                };
                let tx = self.infer(l)?;
                self.apply_type(&tf, &tx, r, l, span)
            }
            BinOp::PipeLeft => {
                let tf = self.infer(l)?;
                let tx = self.infer(r)?;
                self.apply_type(&tf, &tx, l, r, span)
            }
            BinOp::ComposeRight | BinOp::ComposeLeft => {
                // f >> g  ==  fun _pf_x -> g (f _pf_x)
                let (first, second) = if op == BinOp::ComposeRight { (l, r) } else { (r, l) };
                let x = Expr { kind: ExprKind::Var("_pf_x".into()), span };
                let inner = Expr { kind: ExprKind::App(Box::new(first.clone()), Box::new(x)), span };
                let body = Expr { kind: ExprKind::App(Box::new(second.clone()), Box::new(inner)), span };
                let param = Pat { kind: PatKind::Var("_pf_x".into()), span };
                self.infer_lambda(&[param], &body)
            }
            BinOp::Pow => {
                let tl = self.infer(l)?;
                self.unify_at(&t_float(), &tl, l.span)?;
                let tr = self.infer(r)?;
                self.unify_at(&t_float(), &tr, r.span)?;
                Ok(t_float())
            }
            _ => {
                // each operand is checked to be a number before the next
                let tl = self.infer(l)?;
                self.check_arith_operand(op, &tl, l)?;
                let nl = self.expect_num(&tl, l)?;
                let tr = self.infer(r)?;
                self.check_arith_operand(op, &tr, r)?;
                let nr = self.expect_num(&tr, r)?;
                let (Ty::Num(kl, ul), Ty::Num(kr, ur)) = (nl.clone(), nr.clone()) else { unreachable!() };
                let mismatch = |c: &mut Checker| {
                    let a = c.st.show(&tl);
                    let b = c.st.show(&tr);
                    Diag::error(format!("type mismatch: expected {}, found {}", a, b), span)
                };
                if !self.unify_kind(kl, kr) {
                    return Err(mismatch(self));
                }
                match op {
                    BinOp::Add | BinOp::Sub | BinOp::Mod => {
                        if !self.unify_unit(&ul, &ur) {
                            return Err(mismatch(self));
                        }
                        Ok(self.st.shallow(&Ty::Num(kl, ul)))
                    }
                    BinOp::Mul => Ok(Ty::Num(kl, self.st.unit(&ul).mul(&self.st.unit(&ur)))),
                    BinOp::Div => Ok(Ty::Num(Kind::Float, self.st.unit(&ul).div(&self.st.unit(&ur)))),
                    BinOp::FloorDiv => Ok(Ty::Num(kl, self.st.unit(&ul).div(&self.st.unit(&ur)))),
                    _ => unreachable!(),
                }
            }
        }
    }

    fn check_arith_operand(&mut self, op: BinOp, t: &Ty, e: &Expr) -> R<()> {
        let r = self.st.shallow(t);
        if let Ty::Con(n, _) = &r {
            match (op, n.as_str()) {
                (BinOp::Add, "string") => {
                    return Err(Diag::error("`+` is numeric and does not concatenate strings — use `String.concat a b`", e.span));
                }
                (BinOp::Add, "List") => {
                    return Err(Diag::error("`+` is numeric and does not concatenate lists — use `List.concat xs ys`", e.span));
                }
                (BinOp::Mul, "string") => {
                    return Err(Diag::error("`*` is numeric and does not repeat strings — use `String.repeat count string`", e.span));
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn infer_chain(&mut self, first: &Expr, rest: &[(CmpOp, Expr)], span: Span) -> R<Ty> {
        let t0 = self.infer(first)?;
        if rest.len() == 1 {
            let t1 = self.infer(&rest[0].1)?;
            self.unify_at(&t0, &t1, span)?;
            self.check_comparison(rest[0].0, &t0, span)?;
        } else {
            for (op, e) in rest {
                let t = self.infer(e)?;
                self.unify_at(&t0, &t, e.span)?;
                self.check_comparison(*op, &t0, e.span)?;
            }
        }
        Ok(t_bool())
    }

    fn check_comparison(&mut self, op: CmpOp, t: &Ty, span: Span) -> R<()> {
        if matches!(op, CmpOp::Eq | CmpOp::Ne) {
            return Ok(());
        }
        self.require_ordering(t, op.text(), span)
    }

    pub fn require_ordering(&mut self, t: &Ty, _op: &str, span: Span) -> R<()> {
        self.ordered.push(t.clone());
        match self.require_ord(t) {
            Ok(()) => Ok(()),
            Err(e) => Err(self.uerr_diag(e, t, t, span)),
        }
    }

    fn section_type(&mut self, op: SectionOp) -> Ty {
        let sig = match op {
            SectionOp::Bin(BinOp::Add) | SectionOp::Bin(BinOp::Sub) | SectionOp::Bin(BinOp::Mod) => "num<'u> -> num<'u> -> num<'u>",
            SectionOp::Bin(BinOp::Mul) => "num<'u> -> num<'v> -> num<'u 'v>",
            SectionOp::Bin(BinOp::Div) => "num<'u> -> num<'v> -> float<'u/'v>",
            SectionOp::Bin(BinOp::FloorDiv) => "num<'u> -> num<'v> -> num<'u/'v>",
            SectionOp::Bin(BinOp::Pow) => "float -> float -> float",
            SectionOp::Cmp(_) => "'a -> 'a -> bool",
            _ => "'a -> 'a -> 'a",
        };
        let t = parse_sig(sig, &mut self.st);
        let t = self.st.instantiate(&Scheme::mono(t));
        // an ordering comparison needs an ordered operand
        if let SectionOp::Cmp(c) = op {
            if !matches!(c, CmpOp::Eq | CmpOp::Ne) {
                if let Ty::Fun(a, _, _) = self.st.resolve(&t) {
                    if let Ty::Var(v) = *a {
                        self.st.tord[v] = true;
                        self.ordered.push(Ty::Var(v));
                    }
                }
            }
        }
        t
    }

    /// Apply a function type to an argument type.
    pub fn apply_type(&mut self, tf: &Ty, ta: &Ty, fexpr: &Expr, aexpr: &Expr, span: Span) -> R<Ty> {
        let r = self.st.fresh();
        let e = self.st.fresh_eff();
        let want = Ty::Fun(Box::new(ta.clone()), e.clone(), Box::new(r.clone()));
        match self.unify(tf, &want) {
            Ok(()) => {}
            Err(UErr::Effect) => return Err(self.callback_effect_error(tf, ta, fexpr, aexpr, span)),
            Err(err) => return Err(self.uerr_diag(err, tf, &want, span)),
        }
        self.perform(&e, span);
        Ok(r)
    }

    fn callback_effect_error(&mut self, tf: &Ty, ta: &Ty, fexpr: &Expr, aexpr: &Expr, span: Span) -> Diag {
        let param = match self.st.shallow(tf) {
            Ty::Fun(p, _, _) => *p,
            _ => {
                return Diag::error(format!("effect mismatch: cannot unify {} with {}", self.st.show(tf), self.st.show(ta)), span);
            }
        };
        let performs = match self.st.resolve(ta) {
            Ty::Fun(..) => {
                let mut t = self.st.resolve(ta);
                let mut labels = std::collections::BTreeSet::new();
                while let Ty::Fun(_, e, r) = t {
                    labels.extend(e.labels.iter().cloned());
                    t = *r;
                }
                let v: Vec<String> = labels.iter().map(|l| label_name(*l, &self.st.other_labels)).collect();
                v.join(", ")
            }
            _ => String::new(),
        };
        let subject = match &aexpr.kind {
            ExprKind::Var(n) => format!("`{}`", n),
            ExprKind::Qual(p, n, _) => format!("`{}.{}`", p.join("."), n),
            _ => "this function".to_string(),
        };
        let callee = head_name(fexpr).unwrap_or_else(|| "this function".into());
        let pshow = self.st.show(&param);
        let with_var = add_effect_var(&pshow);
        Diag::error(
            format!(
                "{} performs {{{}}}, but `{}` takes this callback as `{}`, which performs nothing; to accept a callback whatever it does, give that arrow an effect variable in the extern that declares it: `{}`",
                subject, performs, callee, pshow, with_var
            ),
            aexpr.span,
        )
    }

    fn infer_app(&mut self, e: &Expr) -> R<Ty> {
        self.infer_spine(e, false)
    }

    /// `piped`: a value piped in follows as one more argument.
    fn infer_spine(&mut self, e: &Expr, piped: bool) -> R<Ty> {
        // flatten the spine
        let mut args = Vec::new();
        let mut spans = Vec::new();
        let mut f = e;
        while let ExprKind::App(g, a) = &f.kind {
            args.push(&**a);
            spans.push(f.span);
            f = g;
        }
        args.reverse();
        spans.reverse();
        // Task.scope discharges `spawn` performed by its body
        if let ExprKind::Qual(p, n, _) = &f.kind {
            if p.len() == 1 && p[0] == "Task" && n == "scope" && !args.is_empty() {
                return self.infer_task_scope(f, &args, &spans);
            }
        }
        let mut tf = self.infer(f)?;
        let n = args.len();
        let more = if piped { 1 } else { 0 };
        // (the arrows before an unknown function's last argument perform
        // nothing, once the application is through)
        let mut inner_effs = Vec::new();
        for (i, a) in args.iter().enumerate() {
            let ta = self.infer(a)?;
            let cur_span = spans[i];
            if i + 1 < n + more && matches!(self.st.shallow(&tf), Ty::Var(_)) {
                // an unknown function applied to several arguments: only the
                // saturating arrow carries an effect
                let r = self.st.fresh();
                let e = self.st.fresh_eff();
                inner_effs.push(e.clone());
                let want = Ty::Fun(Box::new(ta.clone()), e, Box::new(r.clone()));
                if let Err(err) = self.unify(&tf, &want) {
                    return Err(self.uerr_diag(err, &tf, &want, cur_span));
                }
                tf = r;
            } else {
                tf = self.apply_type(&tf, &ta, f, a, cur_span)?;
            }
            self.record_type(cur_span, &tf);
            // a partial application is an expression of its own
            if i + 1 < n {
                self.ide.item(cur_span, &tf, crate::ide::Doc::None);
            }
        }
        for e in inner_effs {
            self.unify_eff(&e, &Eff::pure_());
        }
        Ok(tf)
    }

    fn infer_task_scope(&mut self, f: &Expr, args: &[&Expr], spans: &[Span]) -> R<Ty> {
        let tf = self.infer(f)?;
        self.effs.push(EffAcc::default());
        let ta = self.infer(args[0]);
        let acc = self.effs.pop().unwrap();
        let ta = ta?;
        for (l, sp) in &acc.labels {
            if *l != Label::Spawn {
                let mut s = std::collections::BTreeSet::new();
                s.insert(*l);
                self.perform(&Eff { labels: s, tail: None }, *sp);
            }
        }
        if let Some((v, sp)) = acc.tail {
            self.perform(&Eff::var(v), sp);
        }
        let mut t = self.apply_type(&tf, &ta, f, args[0], spans[0])?;
        for (a, sp) in args[1..].iter().zip(&spans[1..]) {
            let ta = self.infer(a)?;
            t = self.apply_type(&t, &ta, f, a, *sp)?;
        }
        Ok(t)
    }

    // ---- records ----------------------------------------------------------

    pub fn record_fields(&mut self, tname: &str) -> Option<(usize, Vec<(String, Ty)>)> {
        match self.types.get(tname) {
            Some(TypeInfo { params, def: TypeDef::Record(fs), .. }) => Some((*params, fs.clone())),
            _ => None,
        }
    }

    /// Instantiate a record type: (the type, field types)
    pub fn inst_record(&mut self, tname: &str) -> Option<(Ty, Vec<(String, Ty)>)> {
        let (params, fs) = self.record_fields(tname)?;
        let mut inst = Inst::default();
        let args: Vec<Ty> = (0..params).map(|i| self.st.inst_ty(&Ty::Gen(i), &mut inst)).collect();
        let fts = fs.iter().map(|(n, t)| (n.clone(), self.st.inst_ty(t, &mut inst))).collect();
        // (an imported record goes by its own name, however it is reached)
        let name = self.types.get(tname).map_or(tname.to_string(), |ti| ti.name.clone());
        Some((Ty::Con(name, args), fts))
    }

    fn type_key(&self, path: &[String], name: &str) -> String {
        if path.is_empty() {
            name.to_string()
        } else {
            format!("{}.{}", path.join("."), name)
        }
    }

    fn infer_record(&mut self, path: &[String], name: &str, cspan: Span, fields: &[(String, Span, Expr)], span: Span) -> R<Ty> {
        let tkey = self.type_key(path, name);
        if path.is_empty() {
            self.ide.type_uses.push((cspan, name.to_string()));
        }
        let Some((rt, fts)) = self.inst_record(&tkey) else {
            if !path.is_empty() {
                return Err(Diag::error(format!("`{}` is not a member of `{}`", name, path.join(".")), Span::new(span.lo, cspan.hi)));
            }
            return Err(Diag::error(format!("`{}` is not a record type", name), cspan));
        };
        let mut seen: Vec<&str> = Vec::new();
        for (f, _, v) in fields {
            if seen.contains(&f.as_str()) {
                return Err(Diag::error(format!("field `{}` is set twice", f), v.span));
            }
            seen.push(f);
            let Some((_, ft)) = fts.iter().find(|(n, _)| n == f) else {
                return Err(Diag::error(format!("record `{}` has no field `{}`", name, f), v.span));
            };
            let ft = ft.clone();
            let tv = self.infer(v)?;
            self.unify_at(&ft, &tv, v.span)?;
        }
        let missing: Vec<String> = fts.iter().filter(|(n, _)| !seen.contains(&n.as_str())).map(|(n, _)| format!("`{}`", n)).collect();
        if !missing.is_empty() {
            return Err(Diag::error(format!("record `{}` is missing field(s) {}", name, missing.join(", ")), span));
        }
        Ok(rt)
    }

    fn ambiguous_field(&self, field: &str, owners: &[String], span: Span) -> Diag {
        let names: Vec<String> = owners.iter().map(|o| format!("`{}`", o)).collect();
        let list = if names.len() == 2 { format!("{} and {}", names[0], names[1]) } else { names.join(", ") };
        Diag::error(
            format!("field `{}` is ambiguous here: nothing says what this value is, and `{}` is declared by records {}. Name the record where the value arrives — in a parameter (`fun ({} {{ {} }}) -> …`) or in a pattern (`case {} {{ {} }}:`) — or give it a type some other way", field, field, list, owners[0], field, owners[0], field),
            span,
        )
    }

    /// The fields of a record type, instantiated at its arguments.
    fn fields_of(&mut self, t: &Ty) -> Option<(String, Vec<(String, Ty)>)> {
        let Ty::Con(n, args) = self.st.shallow(t) else { return None };
        let (_, fs) = self.record_fields(&n)?;
        let mut inst = Inst::default();
        for (i, a) in args.iter().enumerate() {
            inst.t.insert(i, a.clone());
        }
        let fts = fs.iter().map(|(fname, ft)| (fname.clone(), self.st.inst_ty(ft, &mut inst))).collect();
        Some((n, fts))
    }

    /// Resolve `base.field`: the record a value of type `t` is, and the
    /// field's type. Errors about the field are reported at `span`, a
    /// value that is not a record at `base_span`.
    fn record_of(&mut self, t: &Ty, field: &str, span: Span, base_span: Span) -> R<(String, Vec<(String, Ty)>, Ty)> {
        if let Some((n, fts)) = self.fields_of(t) {
            return match fts.iter().find(|(x, _)| x == field) {
                Some((_, ft)) => {
                    let ft = ft.clone();
                    Ok((n, fts, ft))
                }
                None => {
                    let sugg = fts
                        .iter()
                        .map(|(x, _)| x)
                        .min_by_key(|x| levenshtein(x, field))
                        .filter(|x| levenshtein(x, field) <= 2usize.max(x.chars().count().max(field.chars().count()) / 3));
                    Err(Diag::error(
                        match sugg {
                            Some(x) => format!("record `{}` has no field `{}` (did you mean `{}`?)", n, field, x),
                            None => format!("record `{}` has no field `{}`", n, field),
                        },
                        span,
                    ))
                }
            };
        }
        let owners = self.fields.get(field).cloned().unwrap_or_default();
        if owners.is_empty() {
            return Err(Diag::error(format!("unknown record field `{}`", field), span));
        }
        if owners.len() > 1 {
            return Err(self.ambiguous_field(field, &owners, span));
        }
        let (rt, fts) = self.inst_record(&owners[0]).unwrap();
        if let Err(e) = self.unify(&rt, t) {
            return Err(self.uerr_diag(e, &rt, t, base_span));
        }
        let ft = fts.iter().find(|(x, _)| x == field).unwrap().1.clone();
        Ok((owners[0].clone(), fts, ft))
    }

    fn infer_field(&mut self, base: &Expr, f: &str, span: Span) -> R<Ty> {
        let tb = self.infer(base)?;
        let (_, _, ft) = self.record_of(&tb, f, span, base.span)?;
        Ok(ft)
    }

    fn infer_update(&mut self, base: &Expr, fields: &[(Vec<(String, Span)>, Expr)], span: Span) -> R<Ty> {
        let tb = self.infer(base)?;
        // the first field decides the record
        let (rname, rfts, _) = self.record_of(&tb, &fields[0].0[0].0, span, base.span)?;
        // a field is updated once, directly or through its sub-fields
        for (i, (path, v)) in fields.iter().enumerate() {
            let clash = fields[..i].iter().any(|(q, _)| {
                let n = q.len().min(path.len());
                q[..n].iter().zip(&path[..n]).all(|(a, b)| a.0 == b.0)
            });
            if clash {
                return Err(Diag::error(format!("field `{}` is updated both directly and through a sub-field", path[0].0), v.span));
            }
        }
        for (path, v) in fields {
            let mut cur_name = rname.clone();
            let mut cur_fts = rfts.clone();
            let mut ft = tb.clone();
            for (i, (fname, _)) in path.iter().enumerate() {
                if i > 0 {
                    let Some((n, fts)) = self.fields_of(&ft) else {
                        return Err(Diag::error(format!("field `{}` is not a record, so `.{}` cannot be updated through it", path[i - 1].0, fname), v.span));
                    };
                    cur_name = n;
                    cur_fts = fts;
                }
                let Some((_, t)) = cur_fts.iter().find(|(n, _)| n == fname) else {
                    return Err(Diag::error(format!("record `{}` has no field `{}`", cur_name, fname), v.span));
                };
                ft = t.clone();
            }
            let tv = self.infer(v)?;
            self.unify_at(&ft, &tv, v.span)?;
        }
        Ok(tb)
    }

    // ---- functions --------------------------------------------------------

    pub fn infer_lambda(&mut self, params: &[Pat], body: &Expr) -> R<Ty> {
        self.push_scope();
        self.effs.push(EffAcc::default());
        let r = (|| -> R<Ty> {
            let mut pts = Vec::new();
            for p in params {
                let t = self.st.fresh();
                self.check_pat(p, &t, true)?;
                pts.push(t);
            }
            let tb = self.infer(body)?;
            Ok(Ty::Tuple(vec![Ty::Tuple(pts), tb]))
        })();
        let acc = self.effs.pop().unwrap();
        self.pop_scope();
        let Ty::Tuple(v) = r? else { unreachable!() };
        let Ty::Tuple(pts) = v[0].clone() else { unreachable!() };
        let mut t = v[1].clone();
        let eff = self.acc_to_eff(&acc);
        for (i, pt) in pts.into_iter().enumerate().rev() {
            let e = if i == params.len() - 1 { eff.clone() } else { Eff::pure_() };
            t = Ty::Fun(Box::new(pt), e, Box::new(t));
        }
        Ok(t)
    }

    pub fn infer_block(&mut self, stmts: &[Stmt]) -> R<Ty> {
        self.push_scope();
        let r = (|| -> R<Ty> {
            let mut last = t_unit();
            let n = stmts.len();
            for (i, s) in stmts.iter().enumerate() {
                match s {
                    Stmt::Let(l) => {
                        self.infer_local_let(l)?;
                        last = t_unit();
                    }
                    Stmt::Assign(n, nspan, v, whole) => {
                        self.infer_assign(n, *nspan, v, *whole)?;
                        last = t_unit();
                    }
                    Stmt::Expr(e) => {
                        last = self.infer(e)?;
                        if i + 1 < n && self.unify(&last, &t_unit()).is_err() {
                            let shown = self.st.show(&last);
                            return Err(Diag::error(
                                format!("this statement has type {} but must be `unit`; bind it with `let` or make it the block's final expression", shown),
                                e.span,
                            ));
                        }
                    }
                }
            }
            Ok(last)
        })();
        self.pop_scope();
        r
    }

    /// `x <- v`; `whole` is the statement as written.
    pub fn infer_assign(&mut self, n: &str, nspan: Span, v: &Expr, whole: Span) -> R<()> {
        let _ = nspan;
        let Some(l) = self.lookup_local(n).cloned() else {
            if self.builtins.contains_key(n) || self.ctors.contains_key(n) {
                return Err(Diag::error(format!("cannot assign to `{}`: it is immutable (declare it with `let mut`)", n), whole));
            }
            return Err(Diag::error(format!("unbound name `{}`", n), whole));
        };
        if !l.mutable {
            return Err(Diag::error(format!("cannot assign to `{}`: it is immutable (declare it with `let mut`)", n), whole));
        }
        let tv = self.infer(v)?;
        let t = l.scheme.ty.clone();
        self.unify_at(&t, &tv, v.span)?;
        // reassignment is a side effect
        let io = self.st.label_of("io");
        let mut labels = std::collections::BTreeSet::new();
        labels.insert(io);
        self.perform(&Eff { labels, tail: None }, nspan.to(v.span));
        self.ide.item(nspan.to(v.span), &t_unit(), crate::ide::Doc::None);
        Ok(())
    }

    /// A `let` inside a block: generalize and bind.
    pub fn infer_local_let(&mut self, l: &LetDecl) -> R<()> {
        let t = self.infer_let_value(l)?;
        self.bind_let_pattern(l, &t)?;
        Ok(())
    }

    /// Infer the value of a let (function or value), generalizing as needed.
    pub fn infer_let_value(&mut self, l: &LetDecl) -> R<Ty> {
        let is_fn = !l.params.is_empty();
        self.enter_level();
        let r = (|| -> R<Ty> {
            if is_fn {
                // recursive: the name is in scope in its own body
                let self_t = self.st.fresh();
                self.push_scope();
                if let PatKind::Var(n) = &l.pat.kind {
                    let def = self.let_def(n, l.name_span, l.doc.clone());
                    self.bind_local_def(n, Scheme::mono(self_t.clone()), false, def);
                }
                let t = self.infer_lambda(&l.params, &l.value);
                self.pop_scope();
                let t = t?;
                self.unify_at(&self_t, &t, l.value.span)?;
                Ok(t)
            } else {
                self.infer(&l.value)
            }
        })();
        self.leave_level();
        let t = r?;
        crate::check_decl::mutable_params(l)?;
        self.binding_types.insert(key(l.name_span), t.clone());
        Ok(t)
    }

    pub fn bind_let_pattern(&mut self, l: &LetDecl, t: &Ty) -> R<()> {
        self.bind_let_pattern_as(l, t, l.mutable)
    }

    /// `mono`: the names keep the value's own type (a mutable binding, or a
    /// builder's `let`).
    pub fn bind_let_pattern_as(&mut self, l: &LetDecl, t: &Ty, mono: bool) -> R<()> {
        match &l.pat.kind {
            PatKind::Var(n) => {
                let s = if mono { Scheme::mono(t.clone()) } else { self.st.generalize(t) };
                let def = self.let_def(n, l.name_span, l.doc.clone());
                self.ide.item(l.name_span, &s.ty, crate::ide::Doc::Def(def));
                self.bind_local_def(n, s, l.mutable, def);
                Ok(())
            }
            PatKind::Wild => Ok(()),
            _ => {
                // destructuring: bind monomorphically then generalize each
                // (the pattern is checked a level in, like the value, so
                // what it meets stays general)
                let mut binds = Vec::new();
                self.ide.in_let_pattern = true;
                self.enter_level();
                let r = self.check_pat_collect(&l.pat, t, &mut binds);
                self.leave_level();
                self.ide.in_let_pattern = false;
                r?;
                self.ide.item(l.name_span, t, crate::ide::Doc::None);
                for (n, bt, def) in binds {
                    let s = if mono { Scheme::mono(bt) } else { self.st.generalize(&bt) };
                    self.bind_local_def(&n, s, l.mutable, def);
                }
                Ok(())
            }
        }
    }

    // ---- match ----------------------------------------------------------

    fn infer_match(&mut self, scrut: &Expr, arms: &[Arm], span: Span) -> R<Ty> {
        let ts = self.infer(scrut)?;
        self.active_placement(arms, span)?;
        let scrut_span = scrut.span;
        let result = self.st.fresh();
        let mut first = true;
        for a in arms {
            self.push_scope();
            let r = (|| -> R<()> {
                self.check_pat_at(&a.pat, &ts, scrut_span)?;
                if let Some(g) = &a.guard {
                    let tg = self.infer(g)?;
                    self.unify_at(&t_bool(), &tg, g.span)?;
                }
                let tb = self.infer(&a.body)?;
                if first {
                    self.unify_at(&result, &tb, a.body.span)?;
                } else {
                    let rr = result.clone();
                    self.unify_at(&rr, &tb, a.body.span)?;
                }
                Ok(())
            })();
            self.pop_scope();
            r?;
            first = false;
        }
        self.check_exhaustive(&ts, arms, span)?;
        Ok(result)
    }

    // ---- patterns -------------------------------------------------------

    pub fn check_pat(&mut self, p: &Pat, t: &Ty, _param: bool) -> R<()> {
        self.check_pat_at(p, t, p.span)
    }

    /// Check a pattern; its errors are reported at `at` (the scrutinee of a
    /// `match`, or the whole pattern), except those naming a part of it.
    pub fn check_pat_at(&mut self, p: &Pat, t: &Ty, at: Span) -> R<()> {
        let mut binds = Vec::new();
        if let Err(mut d) = self.check_pat_collect(p, t, &mut binds) {
            let own = d.msg.ends_with("is not a record type") || d.msg.contains("is not a member of") || d.msg.starts_with("active pattern") || d.msg.starts_with("an active-pattern") || d.msg.starts_with("in active pattern") || d.msg.starts_with("unbound name");
            if !own {
                d.span = at;
            }
            return Err(d);
        }
        for (n, bt, def) in binds {
            self.bind_local_def(&n, Scheme::mono(bt), false, def);
        }
        Ok(())
    }

    /// A name bound by a pattern: a definition, hoverable with its type.
    fn pat_bind(&mut self, n: &str, span: Span, t: &Ty, binds: &mut Vec<(String, Ty, usize)>) {
        let (def, new) = self.ide.def(n, span, None);
        if new {
            self.ide.item(span, t, crate::ide::Doc::Def(def));
        }
        binds.push((n.to_string(), t.clone(), def));
    }

    pub fn check_pat_collect(&mut self, p: &Pat, t: &Ty, binds: &mut Vec<(String, Ty, usize)>) -> R<()> {
        self.pat_types.insert(key(p.span), t.clone());
        match &p.kind {
            PatKind::Wild => Ok(()),
            // (a builder continuation's ignored argument)
            PatKind::Var(n) if n == "_" => Ok(()),
            PatKind::Var(n) => {
                self.pat_bind(n, p.span, t, binds);
                Ok(())
            }
            // (an integer pattern matches integers only)
            PatKind::Int(_) => self.unify_at(t, &Ty::Num(Kind::Int, Unit::one()), p.span),
            PatKind::Str(_) => self.unify_at(t, &t_string(), p.span),
            PatKind::Bool(_) => self.unify_at(t, &t_bool(), p.span),
            PatKind::Unit => self.unify_at(t, &t_unit(), p.span),
            PatKind::Tuple(ps) => {
                let ts: Vec<Ty> = ps.iter().map(|_| self.st.fresh()).collect();
                let pt = Ty::Tuple(ts.clone());
                if let Err(e) = self.unify(&pt, t) {
                    return Err(self.uerr_diag(e, &pt, t, p.span));
                }
                for (sp, st) in ps.iter().zip(ts.iter()) {
                    self.check_pat_collect(sp, st, binds)?;
                }
                Ok(())
            }
            PatKind::List(elems) => {
                let et = self.st.fresh();
                let pt = Ty::Con("List".into(), vec![et.clone()]);
                if let Err(e) = self.unify(&pt, t) {
                    return Err(self.uerr_diag(e, &pt, t, p.span));
                }
                for e in elems {
                    match e {
                        ListPatElem::Pat(sp) => self.check_pat_collect(sp, &et, binds)?,
                        ListPatElem::Star(Some(n), sp) => {
                            let lt = Ty::Con("List".into(), vec![et.clone()]);
                            let nspan = Span::new(sp.hi - n.len(), sp.hi);
                            self.pat_bind(n, nspan, &lt, binds);
                        }
                        ListPatElem::Star(None, _) => {}
                    }
                }
                Ok(())
            }
            PatKind::Ctor(path, n, args) => {
                if path.is_empty() {
                    self.ide.ctor_uses.push((Span::new(p.span.lo, p.span.lo + n.len()), n.clone()));
                }
                let Some(c) = self.lookup_ctor(path, n) else {
                    // an active pattern case?
                    if let Some(r) = self.check_active_case(n, args, t, p.span, binds) {
                        return r;
                    }
                    let full = if path.is_empty() { n.clone() } else { format!("{}.{}", path.join("."), n) };
                    return Err(Diag::error(format!("unknown constructor `{}`", full), p.span));
                };
                if c.args.len() != args.len() {
                    return Err(Diag::error(format!("constructor `{}` expects {} argument(s), found {}", n, c.args.len(), args.len()), p.span));
                }
                let mut inst = Inst::default();
                let params: Vec<Ty> = (0..c.params).map(|i| self.st.inst_ty(&Ty::Gen(i), &mut inst)).collect();
                let ct = Ty::Con(c.type_name.clone(), params);
                if let Err(e) = self.unify(&ct, t) {
                    return Err(self.uerr_diag(e, &ct, t, p.span));
                }
                for (a, at) in args.iter().zip(c.args.iter()) {
                    let at = self.st.inst_ty(at, &mut inst);
                    self.check_pat_collect(a, &at, binds)?;
                }
                Ok(())
            }
            PatKind::Record(path, n, nsp, fields) => {
                let tkey = self.type_key(path, n);
                if path.is_empty() && !self.ide.in_let_pattern {
                    self.ide.type_uses.push((*nsp, n.clone()));
                }
                let Some((rt, fts)) = self.inst_record(&tkey) else {
                    if !path.is_empty() {
                        return Err(Diag::error(format!("`{}` is not a member of `{}`", n, path.join(".")), *nsp));
                    }
                    return Err(Diag::error(format!("`{}` is not a record type", n), *nsp));
                };
                if let Err(e) = self.unify(&rt, t) {
                    return Err(self.uerr_diag(e, &rt, t, p.span));
                }
                let mut seen: Vec<&String> = Vec::new();
                for (f, fspan, sub) in fields {
                    if seen.contains(&f) {
                        return Err(Diag::error(format!("field `{}` is matched twice", f), *fspan));
                    }
                    seen.push(f);
                    let Some((_, ft)) = fts.iter().find(|(x, _)| x == f) else {
                        return Err(Diag::error(format!("record `{}` has no field `{}`", n, f), *fspan));
                    };
                    let ft = ft.clone();
                    match sub {
                        Some(sp) => {
                            self.ide.item(*fspan, &ft, crate::ide::Doc::None);
                            self.check_pat_collect(sp, &ft, binds)?
                        }
                        None => self.pat_bind(f, *fspan, &ft, binds),
                    }
                }
                Ok(())
            }
            PatKind::Or(alts) => {
                let mut first_binds: Option<Vec<(String, Ty, usize)>> = None;
                for a in alts {
                    let mut b = Vec::new();
                    self.check_pat_collect(a, t, &mut b)?;
                    match &first_binds {
                        None => first_binds = Some(b),
                        Some(fb) => {
                            for (n, _, _) in fb {
                                if !b.iter().any(|(x, _, _)| x == n) {
                                    return Err(Diag::error(format!("variable `{}` is bound in only some alternatives of the or-pattern", n), p.span));
                                }
                            }
                            for (n, _, _) in &b {
                                if !fb.iter().any(|(x, _, _)| x == n) {
                                    return Err(Diag::error(format!("variable `{}` is bound in only some alternatives of the or-pattern", n), p.span));
                                }
                            }
                            for (n, bt, _) in &b {
                                let ft = fb.iter().find(|(x, _, _)| x == n).unwrap().1.clone();
                                self.unify_at(&ft, bt, p.span)?;
                            }
                        }
                    }
                }
                binds.extend(first_binds.unwrap_or_default());
                Ok(())
            }
            PatKind::As(inner, n, nspan) => {
                self.pat_bind(n, *nspan, t, binds);
                self.check_pat_collect(inner, t, binds)
            }
        }
    }
}

pub fn contains_fun(t: &Ty) -> bool {
    match t {
        Ty::Fun(..) => true,
        Ty::Con(_, args) => args.iter().any(contains_fun),
        Ty::Tuple(ts) => ts.iter().any(contains_fun),
        _ => false,
    }
}

pub fn head_name(e: &Expr) -> Option<String> {
    let mut f = e;
    while let ExprKind::App(g, _) = &f.kind {
        f = g;
    }
    match &f.kind {
        ExprKind::Var(n) => Some(n.clone()),
        ExprKind::Qual(p, n, _) => Some(format!("{}.{}", p.join("."), n)),
        ExprKind::Ctor(p, n) => Some(if p.is_empty() { n.clone() } else { format!("{}.{}", p.join("."), n) }),
        _ => None,
    }
}

/// `'a -> 'a` becomes `'a ->{e} 'a` (the last arrow gains an effect variable).
fn add_effect_var(s: &str) -> String {
    match s.rfind(" -> ") {
        Some(i) => format!("{} ->{{e}} {}", &s[..i], &s[i + 4..]),
        None => s.to_string(),
    }
}

pub fn levenshtein(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    for i in 1..=a.len() {
        let mut cur = vec![i; b.len() + 1];
        for j in 1..=b.len() {
            let cost = if a[i - 1] == b[j - 1] { 0 } else { 1 };
            cur[j] = (prev[j] + 1).min(cur[j - 1] + 1).min(prev[j - 1] + cost);
        }
        prev = cur;
    }
    prev[b.len()]
}

#[allow(dead_code)]
pub fn unused(_: &HashMap<String, String>) {}

/// The variable of a builtin's signature that must support comparison.
pub fn builtin_ord_gen(full: &str) -> Option<usize> {
    match full {
        "List.sort" | "List.sortDescending" | "List.max" | "List.min" | "Set.max" | "Set.min" | "Seq.max" | "Seq.min" => Some(0),
        "List.sortBy" | "List.sortByDescending" | "List.maxBy" | "List.minBy" => Some(1),
        _ => None,
    }
}
