// Match exhaustiveness with concrete missing-case witnesses.

use crate::ast::*;
use crate::diag::Diag;
use crate::infer::*;
use crate::source::Span;
use crate::types::*;

#[derive(Clone, Debug, PartialEq)]
pub enum Ctor {
    Adt { tname: String, name: String, arity: usize },
    Tuple(usize),
    Record { name: String, fields: Vec<String> },
    Bool(bool),
    Unit,
    Int(i64),
    Str(String),
    /// the empty list
    Nil,
    /// a first element and the rest of the list
    Cons,
}

#[derive(Clone, Debug)]
pub enum P {
    Wild,
    C(Ctor, Vec<P>),
    Or(Vec<P>),
    /// a list ending in these elements (`[*_, a, b]`)
    Suffix(Vec<P>),
}

#[derive(Clone, Debug)]
pub enum W {
    Wild,
    C(Ctor, Vec<W>),
}

impl Checker {
    /// An active-pattern case: a constructor-like name no type declares.
    pub fn is_active_case(&self, p: &Pat) -> bool {
        match &p.kind {
            PatKind::Ctor(path, n, _) => path.is_empty() && self.lookup_ctor(path, n).is_none() && self.active_cases.contains_key(n),
            _ => false,
        }
    }

    fn contains_active(&self, p: &Pat) -> bool {
        match &p.kind {
            PatKind::Ctor(_, _, args) => self.is_active_case(p) || args.iter().any(|a| self.contains_active(a)),
            PatKind::Tuple(ps) | PatKind::Or(ps) => ps.iter().any(|x| self.contains_active(x)),
            PatKind::List(es) => es.iter().any(|e| matches!(e, ListPatElem::Pat(x) if self.contains_active(x))),
            PatKind::Record(_, _, _, fs) => fs.iter().any(|(_, _, sub)| sub.as_ref().map_or(false, |x| self.contains_active(x))),
            PatKind::As(x, _, _) => self.contains_active(x),
            _ => false,
        }
    }

    /// Active patterns stand for a whole arm's pattern (or the alternatives
    /// of one), since the recognizer runs on the whole scrutinee.
    pub fn active_placement(&self, arms: &[Arm], span: Span) -> Result<(), Diag> {
        let nested = |c: &Self, p: &Pat| match &p.kind {
            PatKind::Ctor(_, _, args) => args.iter().any(|a| c.contains_active(a)),
            _ => false,
        };
        for a in arms {
            let p = &a.pat;
            if self.is_active_case(p) {
                if nested(self, p) {
                    return Err(Diag::error("an active pattern may only appear as the whole pattern of a `case` arm", span));
                }
                continue;
            }
            if let PatKind::Or(alts) = &p.kind {
                if alts.iter().any(|x| self.contains_active(x)) {
                    if !alts.iter().all(|x| self.is_active_case(x)) {
                        return Err(Diag::error("an or-pattern using active-pattern cases may combine only active-pattern cases", span));
                    }
                    if alts.iter().any(|x| nested(self, x)) {
                        return Err(Diag::error("an active pattern may only appear as the whole pattern of a `case` arm", span));
                    }
                    for x in alts {
                        if let PatKind::Ctor(_, n, args) = &x.kind {
                            // (a partial pattern's parameter arguments are values)
                            let extra = self.active_cases.get(n).and_then(|t| self.active_params.get(t)).copied().unwrap_or(0);
                            if args.iter().skip(extra).any(|a| !matches!(a.kind, PatKind::Wild)) {
                                return Err(Diag::error(format!("an active-pattern case in an or-pattern cannot bind — use `_` for `{}`'s fields", n), span));
                            }
                        }
                    }
                }
                continue;
            }
            if self.contains_active(p) {
                return Err(Diag::error("an active pattern may only appear as the whole pattern of a `case` arm (or as an alternative in an or-pattern of cases)", span));
            }
        }
        Ok(())
    }

    /// The active pattern an arm's cases come from, when it has only those.
    fn arm_active_tag(&self, p: &Pat) -> Option<String> {
        match &p.kind {
            PatKind::Ctor(_, n, _) if self.is_active_case(p) => self.active_cases.get(n).cloned(),
            PatKind::Or(alts) => {
                let tags: Vec<Option<String>> = alts.iter().map(|x| self.arm_active_tag(x)).collect();
                match tags.first() {
                    Some(Some(t)) if tags.iter().all(|x| x.as_deref() == Some(t.as_str())) => Some(t.clone()),
                    _ => None,
                }
            }
            _ => None,
        }
    }

    pub fn check_exhaustive(&mut self, scrut: &Ty, arms: &[Arm], span: Span) -> Result<(), Diag> {
        // the cases of one total active pattern close the match; otherwise
        // active-pattern arms cover nothing
        let unguarded: Vec<&Arm> = arms.iter().filter(|a| a.guard.is_none()).collect();
        let tags: Vec<Option<String>> = unguarded.iter().map(|a| self.arm_active_tag(&a.pat)).collect();
        if let Some(Some(tag)) = tags.first() {
            if tags.iter().all(|t| t.as_deref() == Some(tag.as_str())) {
                if let Some((names, false)) = self.active_patterns.get(tag).cloned() {
                    let mut covered = Vec::new();
                    for a in &unguarded {
                        collect_case_names(&a.pat, &mut covered);
                    }
                    if let Some(m) = names.iter().find(|n| !covered.contains(n)) {
                        let arity = self.active_ctors.get(m).map_or(0, |c| c.args.len());
                        let shown = format!("{}{}", m, " _".repeat(arity));
                        return Err(Diag::error(format!("non-exhaustive match: `{}` is not matched", shown), span));
                    }
                    return Ok(());
                }
            }
        }
        let mut rows = Vec::new();
        for a in unguarded {
            let active = match &a.pat.kind {
                PatKind::Or(alts) => alts.iter().all(|x| self.is_active_case(x)),
                _ => self.is_active_case(&a.pat),
            };
            if active {
                continue;
            }
            rows.push(vec![self.simplify(&a.pat, scrut)]);
        }
        let t = self.st.resolve(scrut);
        if let Some(w) = self.useful(&rows, &[t]) {
            let w = &w[0];
            let msg = match w {
                W::Wild => "non-exhaustive match: add a wildcard `_` arm".to_string(),
                _ => format!("non-exhaustive match: `{}` is not matched", show_witness(w, false)),
            };
            return Err(Diag::error(msg, span));
        }
        Ok(())
    }

    fn simplify(&mut self, p: &Pat, t: &Ty) -> P {
        let t = self.st.resolve(t);
        match &p.kind {
            PatKind::Wild | PatKind::Var(_) => P::Wild,
            PatKind::As(inner, _, _) => self.simplify(inner, &t),
            PatKind::Int(n) => P::C(Ctor::Int(*n), vec![]),
            PatKind::Str(s) => P::C(Ctor::Str(s.clone()), vec![]),
            PatKind::Bool(b) => P::C(Ctor::Bool(*b), vec![]),
            PatKind::Unit => P::C(Ctor::Unit, vec![]),
            PatKind::Tuple(ps) => {
                let ts = match &t {
                    Ty::Tuple(ts) => ts.clone(),
                    _ => vec![Ty::Gen(0); ps.len()],
                };
                P::C(Ctor::Tuple(ps.len()), ps.iter().zip(ts.iter()).map(|(x, xt)| self.simplify(x, xt)).collect())
            }
            PatKind::Or(alts) => P::Or(alts.iter().map(|a| self.simplify(a, &t)).collect()),
            PatKind::List(elems) => {
                // lists are cons cells: `[a, b]` is `a :: b :: []`
                let et = match &t {
                    Ty::Con(_, a) if !a.is_empty() => a[0].clone(),
                    _ => Ty::Gen(0),
                };
                let mut pre = Vec::new();
                let mut suf = Vec::new();
                let mut star = false;
                for e in elems {
                    match e {
                        ListPatElem::Star(..) => star = true,
                        ListPatElem::Pat(x) => {
                            let sp = self.simplify(x, &et);
                            if star {
                                suf.push(sp);
                            } else {
                                pre.push(sp);
                            }
                        }
                    }
                }
                let mut tail = if !star {
                    P::C(Ctor::Nil, vec![])
                } else if suf.is_empty() {
                    P::Wild
                } else {
                    P::Suffix(suf)
                };
                for x in pre.into_iter().rev() {
                    tail = P::C(Ctor::Cons, vec![x, tail]);
                }
                tail
            }
            PatKind::Ctor(path, n, args) => {
                let c = self.lookup_ctor(path, n);
                match c {
                    Some(c) => {
                        let arg_tys = self.ctor_arg_types(&c, &t);
                        let ps = args.iter().zip(arg_tys.iter()).map(|(a, at)| self.simplify(a, at)).collect();
                        P::C(Ctor::Adt { tname: c.type_name.clone(), name: display_ctor(&c), arity: c.args.len() }, ps)
                    }
                    None => {
                        // an active-pattern case
                        if let Some(tag) = self.active_cases.get(n).cloned() {
                            let (names, partial) = self.active_patterns[&tag].clone();
                            if partial {
                                return P::C(Ctor::Adt { tname: tag.clone(), name: n.clone(), arity: 0 }, vec![]);
                            }
                            let _ = names;
                            return P::C(Ctor::Adt { tname: tag.clone(), name: n.clone(), arity: 0 }, vec![]);
                        }
                        P::Wild
                    }
                }
            }
            PatKind::Record(path, n, _, fields) => {
                let key = if path.is_empty() { n.clone() } else { format!("{}.{}", path.join("."), n) };
                let fs = match self.types.get(&key) {
                    Some(TypeInfo { def: TypeDef::Record(fs), .. }) => fs.clone(),
                    _ => vec![],
                };
                let args_t = match &t {
                    Ty::Con(_, a) => a.clone(),
                    _ => vec![],
                };
                let mut inst = Inst::default();
                for (i, a) in args_t.iter().enumerate() {
                    inst.t.insert(i, a.clone());
                }
                let mut ps = Vec::new();
                for (fname, ft) in &fs {
                    let ft = self.st.inst_ty(ft, &mut inst);
                    match fields.iter().find(|(f, _, _)| f == fname) {
                        Some((_, _, Some(sp))) => ps.push(self.simplify(sp, &ft)),
                        _ => ps.push(P::Wild),
                    }
                }
                P::C(Ctor::Record { name: n.clone(), fields: fs.iter().map(|(f, _)| f.clone()).collect() }, ps)
            }
        }
    }

    fn ctor_arg_types(&mut self, c: &CtorInfo, t: &Ty) -> Vec<Ty> {
        let args_t = match t {
            Ty::Con(_, a) => a.clone(),
            _ => vec![],
        };
        let mut inst = Inst::default();
        for (i, a) in args_t.iter().enumerate() {
            inst.t.insert(i, a.clone());
        }
        let mut out = Vec::new();
        for a in &c.args {
            let x = self.st.inst_ty(a, &mut inst);
            out.push(self.st.resolve(&x));
        }
        out
    }

    /// All constructors of a type, or None when the domain is open.
    fn all_ctors(&mut self, t: &Ty, col: &[&P]) -> Option<Vec<(Ctor, Vec<Ty>)>> {
        for p in col {
            if let P::C(Ctor::Adt { tname, .. }, _) = p {
                if let Some((names, partial)) = self.active_patterns.get(tname).cloned() {
                    if partial {
                        return None;
                    }
                    return Some(names.iter().map(|n| (Ctor::Adt { tname: tname.clone(), name: n.clone(), arity: 0 }, vec![])).collect());
                }
            }
        }
        match t {
            Ty::Con(n, args) if n == "bool" => {
                let _ = args;
                Some(vec![(Ctor::Bool(true), vec![]), (Ctor::Bool(false), vec![])])
            }
            Ty::Con(n, _) if n == "unit" => Some(vec![(Ctor::Unit, vec![])]),
            Ty::Tuple(ts) => Some(vec![(Ctor::Tuple(ts.len()), ts.clone())]),
            Ty::Con(n, args) if n == "List" && args.len() == 1 => Some(vec![(Ctor::Nil, vec![]), (Ctor::Cons, vec![args[0].clone(), t.clone()])]),
            Ty::Con(n, args) => {
                let ti = self.types.get(n).cloned()?;
                match &ti.def {
                    TypeDef::Adt(names) => {
                        let mut out = Vec::new();
                        for cn in names {
                            let c = self.ctor_by_type(n, cn)?;
                            let ats = self.ctor_arg_types(&c, &Ty::Con(n.clone(), args.clone()));
                            out.push((Ctor::Adt { tname: n.clone(), name: display_ctor(&c), arity: c.args.len() }, ats));
                        }
                        Some(out)
                    }
                    TypeDef::Record(fs) => {
                        let mut inst = Inst::default();
                        for (i, a) in args.iter().enumerate() {
                            inst.t.insert(i, a.clone());
                        }
                        let fts: Vec<Ty> = fs.iter().map(|(_, ft)| self.st.inst_ty(ft, &mut inst)).collect();
                        Some(vec![(Ctor::Record { name: n.clone(), fields: fs.iter().map(|(f, _)| f.clone()).collect() }, fts)])
                    }
                    TypeDef::Opaque(u) => {
                        let mut inst = Inst::default();
                        for (i, a) in args.iter().enumerate() {
                            inst.t.insert(i, a.clone());
                        }
                        let ut = self.st.inst_ty(u, &mut inst);
                        Some(vec![(Ctor::Adt { tname: n.clone(), name: n.clone(), arity: 1 }, vec![ut])])
                    }
                    _ => None,
                }
            }
            _ => {
                // active patterns: the scrutinee is matched through a recognizer
                for p in col {
                    if let P::C(Ctor::Adt { tname, .. }, _) = p {
                        if let Some((names, partial)) = self.active_patterns.get(tname).cloned() {
                            if partial {
                                return None;
                            }
                            return Some(names.iter().map(|n| (Ctor::Adt { tname: tname.clone(), name: n.clone(), arity: 0 }, vec![])).collect());
                        }
                    }
                }
                None
            }
        }
    }

    fn ctor_by_type(&self, tname: &str, cname: &str) -> Option<CtorInfo> {
        if let Some(c) = self.ctors.get(cname) {
            if c.type_name == tname {
                return Some(c.clone());
            }
        }
        self.ctors.values().find(|c| c.type_name == tname && c.name == cname).cloned()
    }

    fn useful(&mut self, rows: &[Vec<P>], tys: &[Ty]) -> Option<Vec<W>> {
        // a list suffix pattern can bring the search back to a matrix it is
        // already examining: nothing new is found that way
        // (rows are a set: the same row twice changes nothing)
        let mut keyed: Vec<(String, &Vec<P>)> = rows.iter().map(|r| (format!("{:?}", r), r)).collect();
        keyed.sort_by(|a, b| a.0.cmp(&b.0));
        keyed.dedup_by(|a, b| a.0 == b.0);
        let key = format!("{}{:?}", keyed.iter().map(|(k, _)| k.as_str()).collect::<Vec<_>>().join("|"), tys);
        if self.useful_stack.contains(&key) {
            return None;
        }
        let rows: Vec<Vec<P>> = keyed.into_iter().map(|(_, r)| r.clone()).collect();
        self.useful_stack.push(key);
        let r = self.useful_inner(&rows, tys);
        self.useful_stack.pop();
        r
    }

    fn useful_inner(&mut self, rows: &[Vec<P>], tys: &[Ty]) -> Option<Vec<W>> {
        // expand or-patterns in the first column
        let mut expanded: Vec<Vec<P>> = Vec::new();
        for r in rows {
            expand_or(r, &mut expanded);
        }
        let rows = expanded;
        if tys.is_empty() {
            return if rows.is_empty() { Some(vec![]) } else { None };
        }
        let t = self.st.resolve(&tys[0]);
        let col: Vec<&P> = rows.iter().map(|r| &r[0]).collect();
        let present: Vec<Ctor> = present_ctors(&col);
        let all = self.all_ctors(&t, &col);
        if let Some(all) = &all {
            let complete = all.iter().all(|(c, _)| present.iter().any(|p| covers(p, c)));
            if complete && !all.is_empty() {
                for (c, ats) in all {
                    let spec = specialize(&rows, c);
                    let mut ntys = ats.clone();
                    ntys.extend_from_slice(&tys[1..]);
                    if let Some(w) = self.useful(&spec, &ntys) {
                        let n = ats.len();
                        let head = W::C(c.clone(), w[..n].to_vec());
                        let mut out = vec![head];
                        out.extend_from_slice(&w[n..]);
                        return Some(out);
                    }
                }
                return None;
            }
        }
        // default matrix
        let def: Vec<Vec<P>> = rows.iter().filter(|r| matches!(r[0], P::Wild)).map(|r| r[1..].to_vec()).collect();
        let w = self.useful(&def, &tys[1..])?;
        let head = match &all {
            // nothing to go by: the type's first constructor, if it has some
            Some(all) if present.is_empty() => match all.first() {
                Some((c, ats)) if !matches!(c, Ctor::Unit) => {
                    // (`Some` is Option's first case)
                    let first = all.iter().find(|(c, _)| matches!(c, Ctor::Adt { tname, name, .. } if tname == "Option" && name == "Some"));
                    match first {
                        Some((c, ats)) => W::C(c.clone(), vec![W::Wild; ats.len()]),
                        None => W::C(c.clone(), vec![W::Wild; ats.len()]),
                    }
                }
                _ => W::Wild,
            },
            Some(all) => match all.iter().find(|(c, _)| !present.iter().any(|p| covers(p, c))) {
                Some((c, ats)) => W::C(c.clone(), vec![W::Wild; ats.len()]),
                None => W::Wild,
            },
            None => W::Wild,
        };
        let mut out = vec![head];
        out.extend(w);
        Some(out)
    }
}

fn collect_case_names(p: &Pat, out: &mut Vec<String>) {
    match &p.kind {
        PatKind::Ctor(_, n, _) => out.push(n.clone()),
        PatKind::Or(alts) => alts.iter().for_each(|x| collect_case_names(x, out)),
        _ => {}
    }
}

fn display_ctor(c: &CtorInfo) -> String {
    c.name.clone()
}

fn expand_or(r: &[P], out: &mut Vec<Vec<P>>) {
    if r.is_empty() {
        out.push(vec![]);
        return;
    }
    match &r[0] {
        P::Or(alts) => {
            for a in alts {
                let mut nr = vec![a.clone()];
                nr.extend_from_slice(&r[1..]);
                expand_or(&nr, out);
            }
        }
        _ => out.push(r.to_vec()),
    }
}

fn present_ctors(col: &[&P]) -> Vec<Ctor> {
    let mut out = Vec::new();
    for p in col {
        let c = match p {
            P::C(c, _) => c.clone(),
            P::Suffix(_) => Ctor::Cons,
            _ => continue,
        };
        if !out.contains(&c) {
            out.push(c);
        }
    }
    out
}

fn covers(p: &Ctor, c: &Ctor) -> bool {
    match (p, c) {
        (Ctor::Adt { name: a, tname: ta, .. }, Ctor::Adt { name: b, tname: tb, .. }) => a == b && ta == tb,
        (Ctor::Record { .. }, Ctor::Record { .. }) => true,
        (Ctor::Tuple(_), Ctor::Tuple(_)) => true,
        _ => p == c,
    }
}

/// An exact list of these elements.
fn exact_list(xs: &[P]) -> P {
    let mut tail = P::C(Ctor::Nil, vec![]);
    for x in xs.iter().rev() {
        tail = P::C(Ctor::Cons, vec![x.clone(), tail]);
    }
    tail
}

fn specialize(rows: &[Vec<P>], c: &Ctor) -> Vec<Vec<P>> {
    let arity = match c {
        Ctor::Adt { arity, .. } => *arity,
        Ctor::Tuple(n) => *n,
        Ctor::Record { fields, .. } => fields.len(),
        Ctor::Cons => 2,
        _ => 0,
    };
    let mut out = Vec::new();
    for r in rows {
        let rest = &r[1..];
        let mut push = |mut s: Vec<P>| {
            s.extend_from_slice(rest);
            out.push(s);
        };
        match &r[0] {
            P::Wild => push(vec![P::Wild; arity]),
            P::C(pc, args) => {
                if covers(pc, c) {
                    push(args.clone());
                }
            }
            // `[*_, a, b]` on a cons cell: either `a` starts it and `[b]`
            // follows, or the cell belongs to the star and the pattern
            // applies to the rest
            P::Suffix(suf) => {
                if *c == Ctor::Cons {
                    push(vec![suf[0].clone(), exact_list(&suf[1..])]);
                    push(vec![P::Wild, P::Suffix(suf.clone())]);
                }
            }
            P::Or(_) => {}
        }
    }
    out
}

pub fn show_witness(w: &W, nested: bool) -> String {
    match w {
        W::Wild => "_".into(),
        W::C(c, args) => match c {
            Ctor::Adt { name, .. } => {
                if args.is_empty() {
                    name.clone()
                } else {
                    let a: Vec<String> = args.iter().map(|x| show_witness(x, true)).collect();
                    let s = format!("{} {}", name, a.join(" "));
                    if nested {
                        format!("({})", s)
                    } else {
                        s
                    }
                }
            }
            Ctor::Tuple(_) => {
                let a: Vec<String> = args.iter().map(|x| show_witness(x, false)).collect();
                format!("({})", a.join(", "))
            }
            Ctor::Record { name, fields } => {
                let a: Vec<String> = fields.iter().zip(args.iter()).map(|(f, x)| format!("{} = {}", f, show_witness(x, false))).collect();
                format!("{} {{ {} }}", name, a.join(", "))
            }
            Ctor::Bool(b) => b.to_string(),
            Ctor::Unit => "()".into(),
            Ctor::Int(n) => n.to_string(),
            Ctor::Str(s) => format!("{:?}", s),
            Ctor::Nil => "[]".into(),
            Ctor::Cons => {
                let mut items = Vec::new();
                let mut cur = w;
                loop {
                    match cur {
                        W::C(Ctor::Cons, a) => {
                            items.push(show_witness(&a[0], false));
                            cur = &a[1];
                        }
                        W::C(Ctor::Nil, _) => break,
                        _ => {
                            items.push("*_".to_string());
                            break;
                        }
                    }
                }
                format!("[{}]", items.join(", "))
            }
        },
    }
}
