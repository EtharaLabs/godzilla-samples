// Hindley–Milner inference with numeric kinds, units of measure and effects.

use crate::builtins::BUILTINS;
use crate::diag::Diag;
use crate::source::Span;
use crate::types::*;
use std::collections::{BTreeSet, HashMap, HashSet};

pub type SpanKey = (usize, usize);

pub fn key(s: Span) -> SpanKey {
    (s.lo, s.hi)
}

/// A type definition's part with its parameters filled in.
pub fn subst_gens(t: &Ty, args: &[Ty]) -> Ty {
    match t {
        Ty::Gen(i) => args.get(*i).cloned().unwrap_or_else(|| t.clone()),
        Ty::Con(n, xs) => Ty::Con(n.clone(), xs.iter().map(|x| subst_gens(x, args)).collect()),
        Ty::Fun(a, e, r) => Ty::Fun(Box::new(subst_gens(a, args)), e.clone(), Box::new(subst_gens(r, args))),
        Ty::Tuple(xs) => Ty::Tuple(xs.iter().map(|x| subst_gens(x, args)).collect()),
        other => other.clone(),
    }
}

#[derive(Clone, Debug)]
pub struct Local {
    pub scheme: Scheme,
    pub mutable: bool,
    /// where the name was introduced (for the language server)
    pub def: usize,
}

#[derive(Clone, Debug)]
pub enum TypeDef {
    Adt(Vec<String>),
    Record(Vec<(String, Ty)>),
    Opaque(Ty),
    Extern,
    Builtin,
}

#[derive(Clone, Debug)]
pub struct TypeInfo {
    pub name: String,
    pub params: usize,
    pub def: TypeDef,
    /// module that declares it (None: this file)
    pub module: Option<String>,
}

#[derive(Clone, Debug)]
pub struct CtorInfo {
    pub name: String,
    pub type_name: String,
    pub index: usize,
    /// argument types over Gen(0..params)
    pub args: Vec<Ty>,
    pub params: usize,
    pub module: Option<String>,
}

/// Where an effect label was first performed.
#[derive(Clone, Debug, Default)]
pub struct EffAcc {
    pub labels: Vec<(Label, Span)>,
    pub tail: Option<(EvId, Span)>,
}

#[derive(Clone, Debug)]
pub struct HoleInfo {
    pub name: Option<String>,
    pub span: Span,
    pub ty: Ty,
    /// names in scope at the hole (locals, innermost last)
    pub scope: Vec<(String, Scheme)>,
}

#[derive(Clone, Debug, Default)]
pub struct ModuleExports {
    pub values: HashMap<String, Scheme>,
    pub order: Vec<String>,
}

pub struct Checker {
    pub st: Store,
    pub scopes: Vec<HashMap<String, Local>>,
    pub globals: HashMap<String, Local>,
    pub global_order: Vec<String>,
    pub builtins: HashMap<String, Scheme>,
    pub modules: HashMap<String, ModuleExports>,
    pub types: HashMap<String, TypeInfo>,
    pub ctors: HashMap<String, CtorInfo>,
    pub fields: HashMap<String, Vec<String>>,
    pub measures: HashMap<String, Option<Unit>>,
    pub effs: Vec<EffAcc>,
    pub errors: Vec<Diag>,
    /// the text checked (when known: some messages measure it)
    pub source: String,
    /// tasks started outside any scope, reported after everything else
    pub unowned_tasks: Vec<Diag>,
    pub holes: Vec<HoleInfo>,
    /// resolved types of interesting expressions (by span)
    pub expr_types: HashMap<SpanKey, Ty>,
    /// kinds of integer literals (by span)
    pub lit_kinds: HashMap<SpanKey, Kind>,
    /// types compared with `<`-style operators (need ordering methods)
    pub ordered: Vec<Ty>,
    /// types at which Decode.auto / Encode.auto are used
    pub auto_types: Vec<(Span, Ty, bool)>,
    /// `Decode.auto` descriptors by use, and the types they reach
    pub auto_codecs: HashMap<SpanKey, crate::codec::Codec>,
    pub codecs: std::collections::BTreeMap<String, crate::codec::Codec>,
    /// the matrices the exhaustiveness search is examining
    pub useful_stack: Vec<String>,
    /// span of each pattern's type (for lowering decisions)
    pub pat_types: HashMap<SpanKey, Ty>,
    /// user CE builders seen (module names)
    pub in_module: Option<String>,
    /// declared effect labels of externs
    pub extern_effects: HashMap<String, Ty>,
    /// type of each top-level/local let binding, by name span
    pub binding_types: HashMap<SpanKey, Ty>,
    pub fn_names: Vec<String>,
    /// active pattern tag -> (case names, partial)
    pub active_patterns: HashMap<String, (Vec<String>, bool)>,
    /// active pattern case -> tag
    pub active_cases: HashMap<String, String>,
    /// a partial active pattern's parameters before the match input
    pub active_params: HashMap<String, usize>,
    /// total active pattern cases as constructors of a synthetic type
    pub active_ctors: HashMap<String, CtorInfo>,
    /// what the language server needs
    pub ide: crate::ide::Ide,
    /// documentation of the name just looked up
    pub pending_doc: crate::ide::Doc,
    /// definitions made for let-bound names, by name span
    pub let_defs: HashMap<SpanKey, usize>,
}

type R<T> = Result<T, Diag>;

pub enum UErr {
    Mismatch(Ty, Ty),
    Occurs(Ty, Ty),
    Effect,
    /// a type that must be ordered holds this function type
    NotOrdered(Ty),
}

fn builtin_type(name: &str) -> Option<usize> {
    Some(match name {
        "int" | "float" | "bool" | "string" | "unit" => 0,
        "List" | "Set" | "Seq" | "Option" | "Async" | "Decoder" => 1,
        "Map" | "Result" => 2,
        "Exception" => 0,
        _ => return None,
    })
}

impl Checker {
    pub fn new() -> Checker {
        let mut c = Checker {
            st: Store::new(),
            scopes: Vec::new(),
            globals: HashMap::new(),
            global_order: Vec::new(),
            builtins: HashMap::new(),
            modules: HashMap::new(),
            types: HashMap::new(),
            ctors: HashMap::new(),
            fields: HashMap::new(),
            measures: HashMap::new(),
            effs: vec![EffAcc::default()],
            errors: Vec::new(),
            source: String::new(),
            unowned_tasks: Vec::new(),
            holes: Vec::new(),
            expr_types: HashMap::new(),
            lit_kinds: HashMap::new(),
            ordered: Vec::new(),
            auto_types: Vec::new(),
            auto_codecs: HashMap::new(),
            useful_stack: Vec::new(),
            codecs: std::collections::BTreeMap::new(),
            pat_types: HashMap::new(),
            in_module: None,
            extern_effects: HashMap::new(),
            binding_types: HashMap::new(),
            fn_names: Vec::new(),
            active_patterns: HashMap::new(),
            active_cases: HashMap::new(),
            active_params: HashMap::new(),
            active_ctors: HashMap::new(),
            ide: Default::default(),
            pending_doc: crate::ide::Doc::None,
            let_defs: HashMap::new(),
        };
        c.install_builtins();
        c
    }

    fn install_builtins(&mut self) {
        // builtin constructors
        let opt = |a: Ty| Ty::Con("Option".into(), vec![a]);
        let res = |a: Ty, b: Ty| Ty::Con("Result".into(), vec![a, b]);
        self.ctors.insert(
            "Some".into(),
            CtorInfo { name: "Some".into(), type_name: "Option".into(), index: 1, args: vec![Ty::Gen(0)], params: 1, module: None },
        );
        self.ctors.insert(
            "None".into(),
            CtorInfo { name: "None".into(), type_name: "Option".into(), index: 0, args: vec![], params: 1, module: None },
        );
        self.ctors.insert(
            "Ok".into(),
            CtorInfo { name: "Ok".into(), type_name: "Result".into(), index: 0, args: vec![Ty::Gen(0)], params: 2, module: None },
        );
        self.ctors.insert(
            "Error".into(),
            CtorInfo { name: "Error".into(), type_name: "Result".into(), index: 1, args: vec![Ty::Gen(1)], params: 2, module: None },
        );
        let _ = (opt, res);
        self.types.insert(
            "Option".into(),
            TypeInfo { name: "Option".into(), params: 1, def: TypeDef::Adt(vec!["None".into(), "Some".into()]), module: None },
        );
        self.types.insert(
            "Result".into(),
            TypeInfo { name: "Result".into(), params: 2, def: TypeDef::Adt(vec!["Ok".into(), "Error".into()]), module: None },
        );
        self.types.insert(
            "Exception".into(),
            TypeInfo {
                name: "Exception".into(),
                params: 0,
                def: TypeDef::Record(vec![("errorKind".into(), Ty::Con("string".into(), vec![])), ("errorMessage".into(), Ty::Con("string".into(), vec![]))]),
                module: None,
            },
        );
        self.fields.insert("errorKind".into(), vec!["Exception".into()]);
        self.fields.insert("errorMessage".into(), vec!["Exception".into()]);
        for b in BUILTINS {
            let ty = parse_sig(b.sig, &mut self.st);
            self.builtins.insert(b.name.to_string(), Scheme::mono(ty));
        }
    }

    // ---- effects --------------------------------------------------------

    pub fn perform(&mut self, e: &Eff, span: Span) {
        let e = self.st.eff(e);
        let mut tail_to_unify = None;
        {
            let acc = self.effs.last_mut().unwrap();
            for l in &e.labels {
                if !acc.labels.iter().any(|(x, _)| x == l) {
                    acc.labels.push((*l, span));
                }
            }
            if let Some(EffTail::Var(v)) = e.tail {
                match acc.tail {
                    None => acc.tail = Some((v, span)),
                    Some((w, _)) if w != v => tail_to_unify = Some((v, w)),
                    _ => {}
                }
            }
        }
        if let Some((v, w)) = tail_to_unify {
            // merge the two rows' tails
            let ev = self.st.eff(&Eff::var(v));
            let ew = self.st.eff(&Eff::var(w));
            if ev.tail != ew.tail {
                if let Some(EffTail::Var(vv)) = ev.tail {
                    self.st.evars[vv] = Some(Eff { labels: BTreeSet::new(), tail: ew.tail });
                }
            }
        }
    }

    /// The effect row accumulated by a body.
    pub fn acc_to_eff(&mut self, acc: &EffAcc) -> Eff {
        let mut labels = BTreeSet::new();
        for (l, _) in &acc.labels {
            labels.insert(*l);
        }
        let mut e = Eff { labels, tail: acc.tail.map(|(v, _)| EffTail::Var(v)) };
        e = self.st.eff(&e);
        e
    }

    // ---- unification ----------------------------------------------------

    pub fn unify(&mut self, a: &Ty, b: &Ty) -> Result<(), UErr> {
        let a = self.st.shallow(a);
        let b = self.st.shallow(b);
        match (&a, &b) {
            (Ty::Var(x), Ty::Var(y)) if x == y => Ok(()),
            (Ty::Var(x), _) => self.bind(*x, &b, &a, true),
            (_, Ty::Var(y)) => self.bind(*y, &a, &b, false),
            (Ty::Con(n1, a1), Ty::Con(n2, a2)) => {
                if n1 != n2 || a1.len() != a2.len() {
                    return Err(UErr::Mismatch(a.clone(), b.clone()));
                }
                for (x, y) in a1.iter().zip(a2.iter()) {
                    self.unify(x, y)?;
                }
                Ok(())
            }
            (Ty::Tuple(t1), Ty::Tuple(t2)) => {
                if t1.len() != t2.len() {
                    return Err(UErr::Mismatch(a.clone(), b.clone()));
                }
                for (x, y) in t1.iter().zip(t2.iter()) {
                    self.unify(x, y)?;
                }
                Ok(())
            }
            (Ty::Fun(a1, e1, r1), Ty::Fun(a2, e2, r2)) => {
                self.unify(a1, a2)?;
                self.unify(r1, r2)?;
                if !self.unify_eff(e1, e2) {
                    return Err(UErr::Effect);
                }
                Ok(())
            }
            (Ty::Num(k1, u1), Ty::Num(k2, u2)) => {
                // units first: a unit mismatch leaves the kinds as they were
                if !self.unify_unit(u1, u2) {
                    return Err(UErr::Mismatch(self.st.resolve(&a), self.st.resolve(&b)));
                }
                if !self.unify_kind(*k1, *k2) {
                    return Err(UErr::Mismatch(self.st.resolve(&a), self.st.resolve(&b)));
                }
                Ok(())
            }
            _ => Err(UErr::Mismatch(a.clone(), b.clone())),
        }
    }

    fn bind(&mut self, v: TvId, t: &Ty, var: &Ty, var_is_expected: bool) -> Result<(), UErr> {
        if self.st.occurs(v, t) {
            return Err(if var_is_expected { UErr::Occurs(var.clone(), t.clone()) } else { UErr::Occurs(t.clone(), var.clone()) });
        }
        let lvl = self.st.tvars[v].1;
        self.st.adjust_levels(t, lvl);
        self.st.tvars[v].0 = Some(t.clone());
        if self.st.tord[v] {
            self.require_ord(t)?;
        }
        Ok(())
    }

    /// `t` must support comparison: its variables inherit the requirement,
    /// and a function anywhere in it (or in the types it names) is an
    /// error. The types reached are remembered for the ordering methods.
    pub fn require_ord(&mut self, t: &Ty) -> Result<(), UErr> {
        let mut seen = HashSet::new();
        self.ord_walk(t, &mut seen)
    }

    fn ord_walk(&mut self, t: &Ty, seen: &mut HashSet<String>) -> Result<(), UErr> {
        match self.st.shallow(t) {
            Ty::Var(w) => {
                self.st.tord[w] = true;
                Ok(())
            }
            Ty::Fun(..) => Err(UErr::NotOrdered(self.st.resolve(t))),
            // truth values and unit have no order, nor have collections
            // without one, effects, decoders, or Python's own types
            Ty::Con(n, args) if args.is_empty() && (n == "bool" || n == "unit") => Err(UErr::NotOrdered(Ty::Con(n, args))),
            Ty::Con(n, args) if matches!(n.as_str(), "Set" | "Map" | "Seq" | "Async" | "Decoder") || matches!(self.types.get(&n).map(|i| &i.def), Some(TypeDef::Extern)) => Err(UErr::NotOrdered(Ty::Con(n, args))),
            Ty::Tuple(ts) => {
                for x in &ts {
                    self.ord_walk(x, seen)?;
                }
                Ok(())
            }
            Ty::Con(n, args) => {
                for a in &args {
                    self.ord_walk(a, seen)?;
                }
                if !seen.insert(n.clone()) {
                    return Ok(());
                }
                self.ordered.push(Ty::Con(n.clone(), args.clone()));
                let parts: Vec<Ty> = match self.types.get(&n).map(|i| i.def.clone()) {
                    Some(TypeDef::Record(fs)) => fs.into_iter().map(|(_, ft)| ft).collect(),
                    Some(TypeDef::Adt(cs)) => cs
                        .iter()
                        .filter_map(|c| self.ctors.values().find(|ci| &ci.type_name == &n && &ci.name == c))
                        .flat_map(|ci| ci.args.clone())
                        .collect(),
                    _ => Vec::new(),
                };
                for p in parts {
                    let p = subst_gens(&p, &args);
                    self.ord_walk(&p, seen)?;
                }
                Ok(())
            }
            _ => Ok(()),
        }
    }

    pub fn unify_kind(&mut self, a: Kind, b: Kind) -> bool {
        let a = self.st.kind(a);
        let b = self.st.kind(b);
        match (a, b) {
            (Kind::Var(x), Kind::Var(y)) if x == y => true,
            (Kind::Var(x), _) => {
                if let Kind::Var(y) = b {
                    let l = self.st.klevel[x].min(self.st.klevel[y]);
                    self.st.klevel[y] = l;
                }
                self.st.kvars[x] = Some(b);
                true
            }
            (_, Kind::Var(y)) => {
                self.st.kvars[y] = Some(a);
                true
            }
            (x, y) => x == y,
        }
    }

    pub fn unify_unit(&mut self, a: &Unit, b: &Unit) -> bool {
        let a = self.st.unit(a);
        let b = self.st.unit(b);
        // solve a / b = 1, all or nothing
        let d = a.div(&b);
        let saved = (self.st.uvars.clone(), self.st.ulevel.clone());
        if self.solve_unit(&d) {
            true
        } else {
            self.st.uvars = saved.0;
            self.st.ulevel = saved.1;
            false
        }
    }

    fn solve_unit(&mut self, d: &Unit) -> bool {
        let d = self.st.unit(d);
        if d.is_one() {
            return true;
        }
        // pick the variable with the smallest |exponent|
        let mut best: Option<(UvId, i64)> = None;
        for (a, e) in &d.0 {
            if let UAtom::Var(v) = a {
                if best.map_or(true, |(_, be)| e.abs() < be.abs()) {
                    best = Some((*v, *e));
                }
            }
        }
        let Some((v, e)) = best else { return false };
        // v^e * rest = 1  =>  v = rest^(-1/e) when divisible
        let mut rest = d.clone();
        rest.0.remove(&UAtom::Var(v));
        if rest.0.values().all(|x| x % e == 0) {
            let sol = Unit(rest.0.iter().map(|(a, x)| (a.clone(), -x / e)).collect());
            let lvl = self.st.ulevel[v];
            for a in sol.0.keys() {
                if let UAtom::Var(w) = a {
                    if self.st.ulevel[*w] > lvl {
                        self.st.ulevel[*w] = lvl;
                    }
                }
            }
            self.st.uvars[v] = Some(sol);
            return true;
        }
        // partial step: v = v' * rest^(-(x div e))
        if rest.0.values().all(|x| x.div_euclid(e) == 0) {
            return false;
        }
        let nv = self.st.fresh_uvar();
        let mut sol = Unit::atom(UAtom::Var(nv));
        for (a, x) in &rest.0 {
            let q = x.div_euclid(e);
            if q != 0 {
                sol = sol.mul(&Unit::atom(a.clone()).pow(-q));
            }
        }
        self.st.uvars[v] = Some(sol);
        self.solve_unit(&d)
    }

    pub fn unify_eff(&mut self, a: &Eff, b: &Eff) -> bool {
        let a = self.st.eff(a);
        let b = self.st.eff(b);
        match (a.tail, b.tail) {
            (None, None) => a.labels == b.labels,
            (Some(EffTail::Var(va)), None) => {
                if !a.labels.is_subset(&b.labels) {
                    return false;
                }
                let extra: BTreeSet<Label> = b.labels.difference(&a.labels).cloned().collect();
                self.st.evars[va] = Some(Eff { labels: extra, tail: None });
                true
            }
            (None, Some(EffTail::Var(vb))) => {
                if !b.labels.is_subset(&a.labels) {
                    return false;
                }
                let extra: BTreeSet<Label> = a.labels.difference(&b.labels).cloned().collect();
                self.st.evars[vb] = Some(Eff { labels: extra, tail: None });
                true
            }
            (Some(EffTail::Var(va)), Some(EffTail::Var(vb))) => {
                if va == vb {
                    if a.labels == b.labels {
                        return true;
                    }
                    // a row recursive in its own tail (a recursive function's
                    // effect): the tail absorbs every label
                    let all: BTreeSet<Label> = a.labels.union(&b.labels).cloned().collect();
                    let r = self.st.fresh_evar();
                    self.st.elevel[r] = self.st.elevel[va];
                    self.st.evars[va] = Some(Eff { labels: all, tail: Some(EffTail::Var(r)) });
                    return true;
                }
                let r = self.st.fresh_evar();
                let lvl = self.st.elevel[va].min(self.st.elevel[vb]);
                self.st.elevel[r] = lvl;
                let a_extra: BTreeSet<Label> = b.labels.difference(&a.labels).cloned().collect();
                let b_extra: BTreeSet<Label> = a.labels.difference(&b.labels).cloned().collect();
                self.st.evars[va] = Some(Eff { labels: a_extra, tail: Some(EffTail::Var(r)) });
                self.st.evars[vb] = Some(Eff { labels: b_extra, tail: Some(EffTail::Var(r)) });
                true
            }
            _ => a.labels == b.labels,
        }
    }

    /// Unify, turning a failure into a "type mismatch" diagnostic at `span`.
    pub fn unify_at(&mut self, expected: &Ty, found: &Ty, span: Span) -> R<()> {
        match self.unify(expected, found) {
            Ok(()) => Ok(()),
            Err(e) => Err(self.uerr_diag(e, expected, found, span)),
        }
    }

    pub fn uerr_diag(&mut self, e: UErr, expected: &Ty, found: &Ty, span: Span) -> Diag {
        match e {
            UErr::Mismatch(a, b) => Diag::error(format!("type mismatch: expected {}, found {}", self.st.show(&a), self.st.show(&b)), span),
            UErr::Occurs(a, b) => {
                // each side is named on its own
                let sa = self.st.show_with(&a, &mut Namer::default());
                let sb = self.st.show_with(&b, &mut Namer::default());
                Diag::error(format!("cannot construct the infinite type {} = {}", sa, sb), span)
            }
            UErr::Effect => {
                let mut n = Namer::default();
                let es = self.st.show_with(expected, &mut n);
                let fs = self.st.show_with(found, &mut n);
                Diag::error(format!("effect mismatch: cannot unify {} with {}", es, fs), span)
            }
            UErr::NotOrdered(f) => Diag::error(format!("type {} does not support comparison (`<`)", self.st.show(&f)), span),
        }
    }

    // ---- scopes ---------------------------------------------------------

    pub fn push_scope(&mut self) {
        self.scopes.push(HashMap::new());
    }
    pub fn pop_scope(&mut self) {
        self.scopes.pop();
    }
    pub fn bind_local(&mut self, name: &str, scheme: Scheme, mutable: bool) {
        self.bind_local_def(name, scheme, mutable, crate::ide::NO_DEF);
    }

    pub fn bind_local_def(&mut self, name: &str, scheme: Scheme, mutable: bool, def: usize) {
        self.scopes.last_mut().unwrap().insert(name.to_string(), Local { scheme, mutable, def });
    }

    /// The definition of a let-bound name (made once per declaration).
    pub fn let_def(&mut self, name: &str, span: Span, doc: Option<String>) -> usize {
        if let Some(&d) = self.let_defs.get(&key(span)) {
            return d;
        }
        let (d, _) = self.ide.def(name, span, doc);
        self.let_defs.insert(key(span), d);
        d
    }

    pub fn lookup_local(&self, name: &str) -> Option<&Local> {
        for s in self.scopes.iter().rev() {
            if let Some(l) = s.get(name) {
                return Some(l);
            }
        }
        self.globals.get(name)
    }

    pub fn enter_level(&mut self) {
        self.st.level += 1;
    }
    pub fn leave_level(&mut self) {
        self.st.level -= 1;
    }
}

// ---------------------------------------------------------------------------
// Builtin signature mini-language

struct SigParser<'a> {
    toks: Vec<&'a str>,
    pos: usize,
    tvars: HashMap<String, usize>,
    uvars: HashMap<String, usize>,
    evars: HashMap<String, usize>,
    kvar: bool,
}

fn sig_tokens(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        if c == b' ' {
            i += 1;
            continue;
        }
        if c == b'-' && i + 1 < b.len() && b[i + 1] == b'>' {
            out.push(&s[i..i + 2]);
            i += 2;
            continue;
        }
        if c.is_ascii_alphanumeric() || c == b'\'' || c == b'_' {
            let st = i;
            i += 1;
            while i < b.len() && (b[i].is_ascii_alphanumeric() || b[i] == b'_') {
                i += 1;
            }
            out.push(&s[st..i]);
            continue;
        }
        out.push(&s[i..i + 1]);
        i += 1;
    }
    out
}

pub fn parse_sig(s: &str, st: &mut Store) -> Ty {
    let mut p = SigParser { toks: sig_tokens(s), pos: 0, tvars: HashMap::new(), uvars: HashMap::new(), evars: HashMap::new(), kvar: false };
    let t = p.arrow(st);
    let _ = st;
    t
}

impl<'a> SigParser<'a> {
    fn peek(&self) -> &str {
        self.toks.get(self.pos).copied().unwrap_or("")
    }
    fn next(&mut self) -> &'a str {
        let t = self.toks.get(self.pos).copied().unwrap_or("");
        self.pos += 1;
        t
    }
    fn arrow(&mut self, st: &mut Store) -> Ty {
        let lhs = self.app(st);
        if self.peek() == "->" {
            self.next();
            let mut eff = Eff::pure_();
            if self.peek() == "{" {
                self.next();
                loop {
                    let l = self.next();
                    if l == "}" {
                        break;
                    }
                    if l == "," {
                        continue;
                    }
                    match l {
                        "io" | "async" | "spawn" => {
                            eff.labels.insert(st.label_of(l));
                        }
                        v => {
                            let n = self.evars.len();
                            let i = *self.evars.entry(v.to_string()).or_insert(n);
                            eff.tail = Some(EffTail::Gen(i));
                        }
                    }
                }
            }
            let rhs = self.arrow(st);
            return Ty::Fun(Box::new(lhs), eff, Box::new(rhs));
        }
        lhs
    }
    fn app(&mut self, st: &mut Store) -> Ty {
        let t = self.peek().to_string();
        if t.chars().next().map_or(false, |c| c.is_ascii_uppercase()) {
            self.next();
            let mut args = Vec::new();
            loop {
                let n = self.peek();
                if n == "(" || n.starts_with('\'') || n.chars().next().map_or(false, |c| c.is_ascii_alphabetic()) {
                    args.push(self.atom(st));
                } else {
                    break;
                }
            }
            return Ty::Con(t, args);
        }
        self.atom(st)
    }
    fn atom(&mut self, st: &mut Store) -> Ty {
        let t = self.next();
        if t == "(" {
            let first = self.arrow(st);
            if self.peek() == "," {
                let mut items = vec![first];
                while self.peek() == "," {
                    self.next();
                    items.push(self.arrow(st));
                }
                self.next();
                return Ty::Tuple(items);
            }
            self.next();
            return first;
        }
        if let Some(v) = t.strip_prefix('\'') {
            let n = self.tvars.len();
            let i = *self.tvars.entry(v.to_string()).or_insert(n);
            return Ty::Gen(i);
        }
        match t {
            "int" | "float" | "num" => {
                let kind = match t {
                    "int" => Kind::Int,
                    "float" => Kind::Float,
                    _ => {
                        self.kvar = true;
                        Kind::Gen(0)
                    }
                };
                let mut unit = Unit::one();
                if self.peek() == "<" {
                    self.next();
                    let mut den = false;
                    loop {
                        let u = self.next();
                        if u == ">" {
                            break;
                        }
                        if u == "/" {
                            den = true;
                            continue;
                        }
                        let name = u.trim_start_matches('\'').to_string();
                        let n = self.uvars.len();
                        let i = *self.uvars.entry(name).or_insert(n);
                        let mut e = 1;
                        if self.peek() == "^" {
                            self.next();
                            e = self.next().parse().unwrap();
                        }
                        if den {
                            e = -e;
                        }
                        unit = unit.mul(&Unit::atom(UAtom::Gen(i)).pow(e));
                    }
                }
                Ty::Num(kind, unit)
            }
            "bool" | "string" | "unit" => Ty::Con(t.to_string(), vec![]),
            other => Ty::Con(other.to_string(), vec![]),
        }
    }
}
