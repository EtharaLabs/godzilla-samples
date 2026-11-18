// Lowering: pattern matching.

use crate::ast::*;
use crate::infer::*;
use crate::lower::*;
use crate::py::*;
use crate::source::Span;
use crate::types::*;
use std::collections::HashMap;

fn payload_simple(p: &Pat) -> bool {
    match &p.kind {
        PatKind::Var(_) | PatKind::Wild => true,
        PatKind::Tuple(ps) => ps.iter().all(payload_simple),
        _ => false,
    }
}

/// An arm with its or-pattern alternatives spelled out separately.
struct LArm<'e> {
    pat: Pat,
    guard: Option<&'e Expr>,
    body: &'e Expr,
}

/// A pattern's alternatives when it is an or-pattern at the top.
fn or_alternatives(p: &Pat) -> Vec<Pat> {
    match &p.kind {
        PatKind::Or(alts) => alts.iter().flat_map(or_alternatives).collect(),
        _ => vec![p.clone()],
    }
}

/// A Python pattern that matches anything.
fn py_irrefutable(p: &PPat) -> bool {
    match p {
        PPat::Wild | PPat::Capture(_) => true,
        PPat::As(x, _) => py_irrefutable(x),
        PPat::Or(alts) => alts.iter().any(py_irrefutable),
        _ => false,
    }
}

/// A pattern that matches every value of its type (or-patterns through
/// any such alternative).
fn covers_all(p: &Pat) -> bool {
    match &p.kind {
        PatKind::Or(alts) => alts.iter().any(covers_all),
        PatKind::As(x, _, _) => covers_all(x),
        _ => irrefutable(p),
    }
}

pub fn irrefutable(p: &Pat) -> bool {
    match &p.kind {
        PatKind::Wild | PatKind::Var(_) => true,
        PatKind::List(es) => matches!(es.as_slice(), [ListPatElem::Star(..)]),
        PatKind::Tuple(ps) => ps.iter().all(irrefutable),
        PatKind::Record(_, _, _, fs) => fs.iter().all(|(_, _, sp)| sp.as_ref().map_or(true, irrefutable)),
        PatKind::As(x, _, _) => irrefutable(x),
        _ => false,
    }
}

impl<'a> Lowerer<'a> {
    fn ladder_ok(&self, ty: &Option<Ty>, arms: &[Arm]) -> bool {
        let Some(Ty::Con(tn, _)) = ty else { return false };
        if tn != "Option" && tn != "Result" {
            return false;
        }
        arms.iter().all(|a| match &a.pat.kind {
            PatKind::Wild | PatKind::Var(_) => true,
            PatKind::Ctor(path, n, args) => {
                path.is_empty() && matches!(n.as_str(), "Some" | "None" | "Ok" | "Error") && args.iter().all(payload_simple)
            }
            _ => false,
        })
    }

    /// Whether an arm's pattern is made of active-pattern cases.
    fn active_arm(&self, p: &Pat) -> bool {
        match &p.kind {
            PatKind::Or(alts) => alts.iter().all(|x| self.ck.is_active_case(x)),
            _ => self.ck.is_active_case(p),
        }
    }

    /// A match computed into a temporary of its own: the statements and
    /// the temporary.
    pub fn match_value(&mut self, s: &Expr, arms: &[Arm], span: Span) -> (Vec<PS>, String) {
        let depth = self.fresh_tmp.len();
        let stmts = self.match_stmt(s, arms, span, &Dest::Fresh);
        let t = if self.fresh_tmp.len() > depth { self.fresh_tmp.pop().unwrap() } else { self.new_tmp() };
        (stmts, t)
    }

    /// The destination once the scrutinee is lowered.
    fn settle(&mut self, dest: &Dest) -> Dest {
        match dest {
            Dest::Fresh => {
                let t = self.new_tmp();
                self.fresh_tmp.push(t.clone());
                Dest::Assign(t)
            }
            other => other.clone(),
        }
    }

    pub fn match_stmt(&mut self, s: &Expr, arms: &[Arm], span: Span, dest: &Dest) -> Vec<PS> {
        let ty = self.ty_of(s.span);
        if arms.iter().any(|a| self.active_arm(&a.pat)) {
            return self.active_match(s, arms, dest);
        }
        // (a guard that fails falls through to the next arm, which a ladder
        // only manages when each arm returns)
        let ladders = arms.iter().all(|a| a.guard.is_none()) || matches!(dest, Dest::Return | Dest::ReturnAwait);
        if ladders && self.ladder_ok(&ty, arms) {
            return self.ladder(s, arms, true, dest);
        }
        // --native lowers every match to an isinstance/compare ladder
        if ladders && self.native {
            return self.ladder(s, arms, false, dest);
        }
        let _ = span;
        let saved = std::mem::take(&mut self.pre);
        let subj = self.expr(s);
        let mut out = std::mem::replace(&mut self.pre, saved);
        let dest = &self.settle(dest);
        // the arms up to one Python takes as always matching (it rejects
        // any after it); a fallback raise unless some arm covers everything
        let mut cases = Vec::new();
        let mut stopped = false;
        let mut covered = false;
        for a in arms {
            self.scopes.push(HashMap::new());
            let pt = self.pat_ty(a.pat.span);
            let pat = self.py_pat(&a.pat, pt.as_ref());
            let guard = a.guard.as_ref().map(|g| self.guard_expr(g));
            let body = self.dest_stmts(&a.body, dest);
            self.scopes.pop();
            let catch_all = guard.is_none() && py_irrefutable(&pat);
            if a.guard.is_none() && covers_all(&a.pat) {
                covered = true;
            }
            cases.push(Case { pat, guard, body });
            if catch_all {
                stopped = true;
                break;
            }
        }
        if !stopped && !covered {
            cases.push(Case {
                pat: PPat::Wild,
                guard: None,
                body: vec![PS::Raise(call_n("RuntimeError", vec![PE::Str("non-exhaustive match".into())]))],
            });
        }
        out.push(PS::Match(subj, cases));
        out
    }

    fn ladder(&mut self, s: &Expr, arms: &[Arm], simple: bool, dest: &Dest) -> Vec<PS> {
        // (a ladder takes its temporary before the scrutinee is lowered)
        let dest = self.settle(dest);
        let mut out = Vec::new();
        // `Map.tryFind k m` / `List.head xs` matched for its two cases:
        // test membership (non-emptiness) instead of building an Option
        let mut tryfind: Option<Probe> = None;
        if simple && probe_arms(arms) {
            if let Some((which, args)) = probe_call(s) {
                let mut vals = Vec::new();
                for a in args {
                    let saved = std::mem::take(&mut self.pre);
                    let v = self.expr(a);
                    out.extend(std::mem::replace(&mut self.pre, saved));
                    let v = match v {
                        PE::Name(_) | PE::Int(_) | PE::Str(_) | PE::Float(_) | PE::Bool(_) => v,
                        other => {
                            let t = self.new_tmp();
                            out.push(PS::Assign(name(&t), other));
                            name(&t)
                        }
                    };
                    vals.push(v);
                }
                tryfind = Some(if which == "head" { Probe::Head(vals.remove(0)) } else { Probe::Key(vals.remove(0), vals.remove(0)) });
            }
        }
        let subj: PE = if tryfind.is_some() {
            PE::NoneV
        } else {
            let saved = std::mem::take(&mut self.pre);
            let v = self.expr(s);
            out.extend(std::mem::replace(&mut self.pre, saved));
            match v {
                PE::Name(_) => v,
                other => {
                    let t = self.new_tmp();
                    out.push(PS::Assign(name(&t), other));
                    name(&t)
                }
            }
        };
        // with a membership test the present case reads first
        let reordered: Vec<Arm>;
        let arms: &[Arm] = if tryfind.is_some() && arms.len() == 2 && matches!(&arms[0].pat.kind, PatKind::Ctor(_, n, _) if n == "None") {
            reordered = vec![arms[1].clone(), arms[0].clone()];
            &reordered
        } else {
            arms
        };
        let mut larms = Vec::new();
        for a in arms {
            for p in or_alternatives(&a.pat) {
                larms.push(LArm { pat: p, guard: a.guard.as_ref(), body: &a.body });
            }
        }
        out.extend(self.ladder_chain(&larms, &subj, &tryfind, simple, &dest));
        out
    }

    /// The arms from here on: each refutable arm opens a branch whose `else`
    /// holds the rest; a guarded arm stands alone and the rest follows it.
    fn ladder_chain(&mut self, arms: &[LArm], subj: &PE, tryfind: &Option<Probe>, simple: bool, dest: &Dest) -> Vec<PS> {
        let Some(a) = arms.first() else { return vec![] };
        self.scopes.push(HashMap::new());
        let (cond, mut body) = if simple {
            self.ladder_arm(&a.pat, subj, tryfind)
        } else {
            let mut conds = Vec::new();
            let mut binds = Vec::new();
            self.ladder_test(&a.pat, subj, &mut conds, &mut binds);
            let cond = conds.into_iter().reduce(|x, y| PE::And(Box::new(x), Box::new(y)));
            (cond, binds)
        };
        let inner = self.dest_stmts(a.body, dest);
        match a.guard {
            Some(g) => {
                let gv = self.guard_expr(g);
                body.push(PS::If(vec![(gv, inner)], None));
            }
            None => body.extend(inner),
        }
        self.scopes.pop();
        if a.guard.is_some() {
            let mut out = match cond {
                Some(c) => vec![PS::If(vec![(c, body)], None)],
                None => body,
            };
            out.extend(self.ladder_chain(&arms[1..], subj, tryfind, simple, dest));
            return out;
        }
        let Some(cond) = cond.filter(|_| arms.len() > 1) else { return body };
        let rest = self.ladder_chain(&arms[1..], subj, tryfind, simple, dest);
        match rest.as_slice() {
            [PS::If(more, els)] => {
                let mut ifs = vec![(cond, body)];
                ifs.extend(more.iter().cloned());
                vec![PS::If(ifs, els.clone())]
            }
            [] => vec![PS::If(vec![(cond, body)], None)],
            _ => vec![PS::If(vec![(cond, body)], Some(rest))],
        }
    }

    /// The tests and bindings of a pattern against `subj` (`--native`).
    fn ladder_test(&mut self, p: &Pat, subj: &PE, conds: &mut Vec<PE>, binds: &mut Vec<PS>) {
        let index = |i: i64| PE::Index(Box::new(subj.clone()), Box::new(PE::Int(i)));
        match &p.kind {
            PatKind::Wild | PatKind::Unit | PatKind::Or(_) => {}
            PatKind::Var(n) => {
                let py = self.bind_site(n, p.span);
                binds.push(PS::Assign(name(&py), subj.clone()));
            }
            PatKind::Int(n) => conds.push(PE::Cmp(Box::new(subj.clone()), vec![(Cop::Eq, PE::Int(*n))])),
            PatKind::Str(t) => conds.push(PE::Cmp(Box::new(subj.clone()), vec![(Cop::Eq, PE::Str(t.clone()))])),
            PatKind::Bool(b) => conds.push(PE::Cmp(Box::new(subj.clone()), vec![(Cop::Is, PE::Bool(*b))])),
            PatKind::Tuple(ps) => {
                for (i, x) in ps.iter().enumerate() {
                    self.ladder_test(x, &index(i as i64), conds, binds);
                }
            }
            PatKind::List(es) => {
                let star = es.iter().position(|e| matches!(e, ListPatElem::Star(..)));
                let before = star.unwrap_or(es.len());
                let after = star.map_or(0, |k| es.len() - k - 1);
                let len = call_n("len", vec![subj.clone()]);
                let op = if star.is_some() { Cop::Ge } else { Cop::Eq };
                conds.push(PE::Cmp(Box::new(len), vec![(op, PE::Int((before + after) as i64))]));
                for (i, e) in es.iter().enumerate() {
                    if let ListPatElem::Pat(x) = e {
                        let at = if i < before { i as i64 } else { -((es.len() - i) as i64) };
                        self.ladder_test(x, &index(at), conds, binds);
                    }
                }
                if let Some(k) = star {
                    if let ListPatElem::Star(Some(n), sp) = &es[k] {
                        let py = self.bind_site(n, Span::new(sp.hi - n.len(), sp.hi));
                        let sv = Printer { py311: false }.expr(subj);
                        let end = if after == 0 { format!("len({})", sv) } else { format!("len({}) - {}", sv, after) };
                        binds.push(PS::Assign(name(&py), PE::Raw(format!("{}[{}:{}]", sv, before, end))));
                    }
                }
            }
            PatKind::Ctor(path, n, args) => {
                let Some(c) = self.ck.lookup_ctor(path, n) else { return };
                if let Some(TypeInfo { def: TypeDef::Opaque(_), .. }) = self.ck.types.get(&c.type_name) {
                    if let Some(a) = args.first() {
                        self.ladder_test(a, subj, conds, binds);
                    }
                    return;
                }
                self.note_ctor_type(&c.type_name);
                let prefix = self.pattern_prefix(path, c.module.as_deref());
                conds.push(call_n("isinstance", vec![subj.clone(), name(&format!("{}{}", prefix, ctor_py(n)))]));
                for (i, a) in args.iter().enumerate() {
                    self.ladder_test(a, &attr(subj.clone(), &format!("_{}", i)), conds, binds);
                }
            }
            PatKind::Record(path, n, _, fields) => {
                let prefix = self.pattern_prefix(path, None);
                conds.push(call_n("isinstance", vec![subj.clone(), name(&format!("{}{}", prefix, n))]));
                for (f, fspan, sub) in fields {
                    let fv = attr(subj.clone(), &mangle(f));
                    match sub {
                        Some(x) => self.ladder_test(x, &fv, conds, binds),
                        None => {
                            let py = self.bind_site(f, *fspan);
                            binds.push(PS::Assign(name(&py), fv));
                        }
                    }
                }
            }
            PatKind::As(x, n, nsp) => {
                let py = self.bind_site(n, *nsp);
                binds.push(PS::Assign(name(&py), subj.clone()));
                self.ladder_test(x, subj, conds, binds);
            }
        }
    }

    /// The module qualifier a pattern's class is reached through.
    fn pattern_prefix(&self, path: &[String], module: Option<&str>) -> String {
        match self.module_alias(&path.join(".")) {
            Some(py) if !path.is_empty() => format!("{}.", py),
            _ => match module {
                Some(m) if path.is_empty() => self.module_alias(m).map(|py| format!("{}.", py)).unwrap_or_default(),
                _ => String::new(),
            },
        }
    }

    /// Condition and bindings for one ladder arm.
    fn ladder_arm(&mut self, p: &Pat, subj: &PE, tryfind: &Option<Probe>) -> (Option<PE>, Vec<PS>) {
        match &p.kind {
            PatKind::Wild => (None, vec![]),
            PatKind::Var(n) => {
                let py = self.bind_site(n, p.span);
                (None, vec![PS::Assign(name(&py), subj.clone())])
            }
            PatKind::Ctor(_, c, args) => {
                let cls = ctor_py(c);
                if tryfind.is_none() {
                    self.note_ctor_type(if matches!(c.as_str(), "Some" | "None") { "Option" } else { "Result" });
                }
                let payload = || -> PE { attr(subj.clone(), "_0") };
                let cond = match tryfind {
                    Some(pr) => {
                        let inn = pr.present();
                        if c == "None" {
                            PE::Not(Box::new(inn))
                        } else {
                            inn
                        }
                    }
                    None => call_n("isinstance", vec![subj.clone(), name(&cls)]),
                };
                let mut binds = Vec::new();
                if let Some(a) = args.first() {
                    let val = match tryfind {
                        Some(pr) => pr.value(),
                        None => payload(),
                    };
                    match &a.kind {
                        PatKind::Var(n) => {
                            let py = self.bind_site(n, a.span);
                            binds.push(PS::Assign(name(&py), val));
                        }
                        PatKind::Tuple(ps) if ps.iter().all(|x| matches!(x.kind, PatKind::Var(_) | PatKind::Wild)) => {
                            let t = self.tuple_target(a);
                            binds.push(PS::Assign(t, val));
                        }
                        PatKind::Tuple(_) => {
                            let src = Printer { py311: false }.expr(&val);
                            let base = format!("{}_0", src.replace('.', "_").trim_end_matches("__0").to_string());
                            binds.extend(self.destructure_from(a, &src, Some(base)));
                        }
                        _ => {}
                    }
                }
                (Some(cond), binds)
            }
            _ => (None, vec![]),
        }
    }

    /// A match with active patterns: each recognizer runs once on the
    /// scrutinee. Without guards and with only tests the arms make an
    /// if/elif chain; otherwise each arm is tried in turn (one-case `match`
    /// statements for structural patterns), returning from the function or,
    /// elsewhere, setting a flag the later arms check.
    fn active_match(&mut self, s: &Expr, arms: &[Arm], dest: &Dest) -> Vec<PS> {
        let dest = &self.settle(dest);
        let saved = std::mem::take(&mut self.pre);
        let sv = self.expr(s);
        let mut out = std::mem::replace(&mut self.pre, saved);
        let subj = match sv {
            PE::Name(_) => sv,
            other => {
                let t = self.new_tmp();
                out.push(PS::Assign(name(&t), other));
                name(&t)
            }
        };
        let kinds: Vec<ApArm> = arms.iter().map(|a| self.ap_arm(&a.pat)).collect();
        let mut recog: Vec<(String, String)> = Vec::new();
        let chain = arms.iter().all(|a| a.guard.is_none()) && !kinds.iter().any(|k| matches!(k, ApArm::Stmt));
        if chain {
            let reach = kinds.iter().position(|k| matches!(k, ApArm::Bind(..) | ApArm::Wild)).map_or(arms.len(), |i| i + 1);
            for k in &kinds[..reach] {
                self.recognizers(k, &subj, &mut recog, &mut out);
            }
            let mut ifarms = Vec::new();
            let mut els = None;
            for (a, k) in arms[..reach].iter().zip(kinds.iter()) {
                self.scopes.push(HashMap::new());
                let (cond, mut body) = self.ap_test(k, &subj, &recog);
                body.extend(self.dest_stmts(&a.body, dest));
                self.scopes.pop();
                match cond {
                    Some(c) => ifarms.push((c, body)),
                    None => {
                        els = Some(body);
                        break;
                    }
                }
            }
            if ifarms.is_empty() {
                out.extend(els.unwrap_or_default());
            } else {
                let els = els.unwrap_or_else(|| vec![PS::Raise(call_n("RuntimeError", vec![PE::Str("non-exhaustive match".into())]))]);
                out.push(PS::If(ifarms, Some(els)));
            }
            return out;
        }
        let returns = matches!(dest, Dest::Return | Dest::ReturnAwait);
        let flag = if returns {
            None
        } else {
            let f = self.new_tmp();
            out.push(PS::Assign(name(&f), PE::Bool(false)));
            Some(f)
        };
        let mut done = false;
        for (a, k) in arms.iter().zip(kinds.iter()) {
            let mut block = Vec::new();
            self.recognizers(k, &subj, &mut recog, &mut block);
            self.scopes.push(HashMap::new());
            let stmt_pat = match k {
                ApArm::Stmt => {
                    let pt = self.pat_ty(a.pat.span);
                    Some(self.py_pat(&a.pat, pt.as_ref()))
                }
                _ => None,
            };
            let (cond, binds) = self.ap_test(k, &subj, &recog);
            let guard = a.guard.as_ref().map(|g| self.guard_expr(g));
            let mut inner = self.dest_stmts(&a.body, dest);
            self.scopes.pop();
            if let Some(f) = &flag {
                inner.push(PS::Assign(name(f), PE::Bool(true)));
            }
            match stmt_pat {
                Some(pat) => block.push(PS::Match(subj.clone(), vec![Case { pat, guard, body: inner }])),
                None => {
                    let unguarded = guard.is_none();
                    let mut body = binds;
                    match guard {
                        Some(g) => body.push(PS::If(vec![(g, inner)], None)),
                        None => body.extend(inner),
                    }
                    match cond {
                        Some(c) => block.push(PS::If(vec![(c, body)], None)),
                        None => {
                            block.extend(body);
                            done = unguarded;
                        }
                    }
                }
            }
            match &flag {
                Some(f) => out.push(PS::If(vec![(PE::Not(Box::new(name(f))), block)], None)),
                None => out.extend(block),
            }
            // (with a flag every arm is written out)
            if done && returns {
                break;
            }
        }
        if !done && returns {
            out.push(PS::Raise(call_n("RuntimeError", vec![PE::Str("non-exhaustive match".into())])));
        }
        out
    }

    fn ap_arm(&self, p: &Pat) -> ApArm {
        let alt = |x: &Pat| match &x.kind {
            PatKind::Ctor(_, n, args) => (self.ck.active_cases.get(n).cloned().unwrap_or_default(), n.clone(), args.clone(), x.span.lo),
            _ => unreachable!(),
        };
        match &p.kind {
            _ if self.active_arm(p) => match &p.kind {
                PatKind::Or(alts) => ApArm::Active(alts.iter().map(alt).collect()),
                _ => ApArm::Active(vec![alt(p)]),
            },
            PatKind::Int(n) => ApArm::Lit(PE::Int(*n)),
            PatKind::Str(t) => ApArm::Lit(PE::Str(t.clone())),
            PatKind::Var(v) => ApArm::Bind(v.clone(), p.span),
            PatKind::Wild => ApArm::Wild,
            _ => ApArm::Stmt,
        }
    }

    /// The parameters a case passes its recognizer before the input.
    fn ap_extra(&self, tag: &str) -> usize {
        self.ck.active_params.get(tag).copied().unwrap_or(0)
    }

    /// What tells one run of a recognizer from another: the recognizer
    /// and the values its parameters are given.
    fn ap_key(&self, tag: &str, args: &[Pat]) -> String {
        let mut key = tag.to_string();
        for a in args.iter().take(self.ap_extra(tag)) {
            key.push('\u{0}');
            key.push_str(&match &a.kind {
                PatKind::Var(v) => format!("v{}", self.renamed.get(&(a.span.lo, a.span.hi)).cloned().unwrap_or_else(|| mangle(v))),
                PatKind::Int(i) => format!("i{}", i),
                PatKind::Str(t) => format!("s{}", t),
                PatKind::Bool(b) => format!("b{}", b),
                _ => String::new(),
            });
        }
        key
    }

    /// Run the recognizers an arm needs that have not run yet.
    fn recognizers(&mut self, k: &ApArm, subj: &PE, recog: &mut Vec<(String, String)>, out: &mut Vec<PS>) {
        let ApArm::Active(alts) = k else { return };
        for (tag, case, args, at) in alts {
            let key = self.ap_key(tag, args);
            if recog.iter().any(|(t, _)| *t == key) {
                continue;
            }
            let (names, _) = self.ck.active_patterns.get(tag).cloned().unwrap_or_default();
            // (a variable given to a parameter goes by the name its site
            // has as a binding of the arm)
            let mut call_args = Vec::new();
            for a in args.iter().take(self.ap_extra(tag)) {
                match &a.kind {
                    PatKind::Var(v) => {
                        let py = self.renamed.get(&(a.span.lo, a.span.hi)).cloned().unwrap_or_else(|| mangle(v));
                        call_args.push(name(&py));
                    }
                    _ => {
                        let name_span = Span::new(*at, *at + case.len());
                        if let Some(e) = crate::check_ce::active_param_expr(a, name_span) {
                            let v = self.expr(&e);
                            call_args.push(v);
                        }
                    }
                }
            }
            call_args.push(subj.clone());
            let t = self.new_tmp();
            out.push(PS::Assign(name(&t), call_n(&ap_name(&names), call_args)));
            recog.push((key, t));
        }
    }

    /// An arm's test (none when it always matches) and its bindings.
    fn ap_test(&mut self, k: &ApArm, subj: &PE, recog: &[(String, String)]) -> (Option<PE>, Vec<PS>) {
        match k {
            ApArm::Active(alts) => {
                let mut cond: Option<PE> = None;
                let mut binds = Vec::new();
                for (tag, case, args, _) in alts {
                    let key = self.ap_key(tag, args);
                    let t = recog.iter().find(|(x, _)| *x == key).map(|(_, t)| t.clone()).unwrap_or_default();
                    let (_, partial) = self.ck.active_patterns.get(tag).cloned().unwrap_or_default();
                    let extra = self.ap_extra(tag);
                    for a in args.iter().take(extra) {
                        if let PatKind::Var(v) = &a.kind {
                            self.bind_site(v, a.span);
                        }
                    }
                    let c = if partial {
                        // predicate form: the recognizer returns bool
                        let mut rt = self.ck.globals.get(tag).map(|l| self.ck.st.resolve(&l.scheme.ty));
                        for _ in 0..=extra {
                            rt = match rt {
                                Some(Ty::Fun(_, _, r)) => Some(self.ck.st.resolve(&r)),
                                _ => None,
                            };
                        }
                        if matches!(rt, Some(Ty::Con(ref n, _)) if n == "bool") {
                            name(&t)
                        } else {
                            self.needs.option = true;
                            if let Some(a) = args.get(extra) {
                                if let PatKind::Var(v) = &a.kind {
                                    let py = self.bind_site(v, a.span);
                                    binds.push(PS::Assign(name(&py), attr(name(&t), "_0")));
                                }
                            }
                            call_n("isinstance", vec![name(&t), name("Some")])
                        }
                    } else {
                        for (j, arg) in args.iter().enumerate() {
                            if let PatKind::Var(v) = &arg.kind {
                                let py = self.bind_site(v, arg.span);
                                binds.push(PS::Assign(name(&py), attr(name(&t), &format!("_{}", j))));
                            }
                        }
                        call_n("isinstance", vec![name(&t), name(&format!("_{}", case))])
                    };
                    cond = Some(match cond {
                        Some(prev) => PE::Or(Box::new(prev), Box::new(c)),
                        None => c,
                    });
                }
                (cond, binds)
            }
            ApArm::Lit(v) => (Some(PE::Cmp(Box::new(subj.clone()), vec![(Cop::Eq, v.clone())])), vec![]),
            ApArm::Bind(v, sp) => {
                let py = self.bind_site(v, *sp);
                (None, vec![PS::Assign(name(&py), subj.clone())])
            }
            ApArm::Wild | ApArm::Stmt => (None, vec![]),
        }
    }

    // ---- python patterns ----------------------------------------------------

    pub fn py_pat(&mut self, p: &Pat, t: Option<&Ty>) -> PPat {
        match &p.kind {
            PatKind::Wild => PPat::Wild,
            PatKind::Var(n) => PPat::Capture(self.bind_site(n, p.span)),
            PatKind::Int(n) => PPat::Value(PE::Int(*n)),
            PatKind::Str(s) => PPat::Value(PE::Str(s.clone())),
            PatKind::Bool(b) => PPat::Value(PE::Bool(*b)),
            PatKind::Unit => PPat::Value(PE::NoneV),
            PatKind::Tuple(ps) => {
                let ts: Vec<Option<Ty>> = match t {
                    Some(Ty::Tuple(ts)) => ts.iter().cloned().map(Some).collect(),
                    _ => vec![None; ps.len()],
                };
                PPat::Tuple(ps.iter().zip(ts.iter()).map(|(x, xt)| self.py_pat(x, xt.as_ref())).collect())
            }
            PatKind::List(es) => {
                let et = match t {
                    Some(Ty::Con(_, a)) if !a.is_empty() => Some(a[0].clone()),
                    _ => None,
                };
                let v = es
                    .iter()
                    .map(|e| match e {
                        ListPatElem::Pat(x) => self.py_pat(x, et.as_ref()),
                        ListPatElem::Star(Some(n), sp) => PPat::Star(Some(self.bind_site(n, Span::new(sp.hi - n.len(), sp.hi)))),
                        ListPatElem::Star(None, _) => PPat::Star(None),
                    })
                    .collect();
                PPat::Seq(v)
            }
            PatKind::Ctor(path, n, args) => {
                let c = self.ck.lookup_ctor(path, n);
                let Some(c) = c else { return PPat::Wild };
                self.note_ctor_type(&c.type_name);
                if let Some(TypeInfo { def: TypeDef::Opaque(_), .. }) = self.ck.types.get(&c.type_name) {
                    return self.py_pat(&args[0], None);
                }
                let prefix = match self.module_alias(&path.join(".")) {
                    Some(py) if !path.is_empty() => format!("{}.", py),
                    _ => match &c.module {
                        Some(m) if path.is_empty() => self.module_alias(m).map(|py| format!("{}.", py)).unwrap_or_default(),
                        _ => String::new(),
                    },
                };
                let ats: Vec<Option<Ty>> = match t {
                    Some(Ty::Con(_, targs)) => c.args.iter().map(|a| Some(crate::lower2::subst_gen(a, targs))).collect(),
                    _ => vec![None; args.len()],
                };
                let sub = args.iter().zip(ats.iter()).map(|(a, at)| self.py_pat(a, at.as_ref())).collect();
                PPat::Class(format!("{}{}", prefix, ctor_py(n)), sub, vec![])
            }
            PatKind::Record(path, n, _, fields) => {
                let key = if path.is_empty() { n.clone() } else { format!("{}.{}", path.join("."), n) };
                let fts: Vec<(String, Ty)> = match self.ck.types.get(&key) {
                    Some(TypeInfo { def: TypeDef::Record(fs), .. }) => fs.clone(),
                    _ => vec![],
                };
                let mut kws = Vec::new();
                for (f, fspan, sub) in fields {
                    let ft = fts.iter().find(|(x, _)| x == f).map(|(_, t)| t.clone());
                    let sp = match sub {
                        Some(x) => self.py_pat(x, ft.as_ref()),
                        None => PPat::Capture(self.bind_site(f, *fspan)),
                    };
                    kws.push((mangle(f), sp));
                }
                let prefix = match self.module_alias(&path.join(".")) {
                    Some(py) if !path.is_empty() => format!("{}.", py),
                    _ => String::new(),
                };
                PPat::Class(format!("{}{}", prefix, n), vec![], kws)
            }
            PatKind::Or(alts) => PPat::Or(alts.iter().map(|a| self.py_pat(a, t)).collect()),
            PatKind::As(x, n, nsp) => {
                let inner = self.py_pat(x, t);
                PPat::As(Box::new(inner), self.bind_site(n, *nsp))
            }
        }
    }
}


/// A lookup matched for its two cases: `k in m` / `m[k]`, or a list's
/// non-emptiness / `xs[0]`.
#[derive(Clone)]
pub enum Probe {
    Key(PE, PE),
    Head(PE),
}

impl Probe {
    fn present(&self) -> PE {
        match self {
            Probe::Key(k, m) => PE::Cmp(Box::new(k.clone()), vec![(Cop::In, m.clone())]),
            Probe::Head(xs) => xs.clone(),
        }
    }

    fn value(&self) -> PE {
        match self {
            Probe::Key(k, m) => PE::Index(Box::new(m.clone()), Box::new(k.clone())),
            Probe::Head(xs) => PE::Index(Box::new(xs.clone()), Box::new(PE::Int(0))),
        }
    }
}

/// `Map.tryFind k m` or `List.head xs`, applied or piped: which, and the
/// arguments.
fn probe_call(s: &Expr) -> Option<(&'static str, Vec<&Expr>)> {
    let (f, args) = match &s.kind {
        ExprKind::Binary(BinOp::PipeRight, l, r) => {
            let (f, mut a) = Lowerer::spine(r);
            a.push(l);
            (f, a)
        }
        ExprKind::App(..) => Lowerer::spine(s),
        _ => return None,
    };
    match &f.kind {
        ExprKind::Qual(p, n, _) if p.len() == 1 && p[0] == "Map" && n == "tryFind" && args.len() == 2 => Some(("tryFind", args)),
        ExprKind::Qual(p, n, _) if p.len() == 1 && p[0] == "List" && n == "head" && args.len() == 1 => Some(("head", args)),
        _ => None,
    }
}

/// Exactly a `Some` case and a `None` case, unguarded.
fn probe_arms(arms: &[Arm]) -> bool {
    let is = |a: &Arm, c: &str| a.guard.is_none() && matches!(&a.pat.kind, PatKind::Ctor(p, n, _) if p.is_empty() && n == c);
    arms.len() == 2 && ((is(&arms[0], "Some") && is(&arms[1], "None")) || (is(&arms[0], "None") && is(&arms[1], "Some")))
}

/// How an arm of a match with active patterns is tested.
enum ApArm {
    /// active-pattern cases: (pattern, case, arguments) per alternative
    /// (recognizer, case, arguments, where the case's name starts)
    Active(Vec<(String, String, Vec<Pat>, usize)>),
    /// a literal compared for equality
    Lit(PE),
    Bind(String, Span),
    Wild,
    /// any other pattern: a one-case `match` statement
    Stmt,
}

pub fn ap_name(cases: &[String]) -> String {
    format!("_ap_{}", cases.join("_"))
}
