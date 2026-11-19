// Types, kinds, units of measure and effect rows, with union-find variables.

use std::collections::{BTreeMap, BTreeSet, HashMap};

pub type TvId = usize;
pub type KvId = usize;
pub type UvId = usize;
pub type EvId = usize;

#[derive(Clone, Debug, PartialEq)]
pub enum Ty {
    Var(TvId),
    /// generic variable inside a scheme
    Gen(usize),
    Con(String, Vec<Ty>),
    Num(Kind, Unit),
    Fun(Box<Ty>, Eff, Box<Ty>),
    Tuple(Vec<Ty>),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Kind {
    Int,
    Float,
    Var(KvId),
    Gen(usize),
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum UAtom {
    Base(String),
    Var(UvId),
    Gen(usize),
}

/// A unit of measure: a product of atoms raised to integer powers.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Unit(pub BTreeMap<UAtom, i64>);

impl Unit {
    pub fn one() -> Unit {
        Unit(BTreeMap::new())
    }
    pub fn atom(a: UAtom) -> Unit {
        let mut m = BTreeMap::new();
        m.insert(a, 1);
        Unit(m)
    }
    pub fn is_one(&self) -> bool {
        self.0.is_empty()
    }
    pub fn mul(&self, o: &Unit) -> Unit {
        let mut m = self.0.clone();
        for (a, e) in &o.0 {
            let v = m.entry(a.clone()).or_insert(0);
            *v += e;
            if *v == 0 {
                m.remove(a);
            }
        }
        Unit(m)
    }
    pub fn pow(&self, k: i64) -> Unit {
        if k == 0 {
            return Unit::one();
        }
        Unit(self.0.iter().map(|(a, e)| (a.clone(), e * k)).collect())
    }
    pub fn inv(&self) -> Unit {
        self.pow(-1)
    }
    pub fn div(&self, o: &Unit) -> Unit {
        self.mul(&o.inv())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Label {
    Io,
    Async,
    Spawn,
    Other(u32),
}

/// An effect row: concrete labels plus an optional tail variable.
#[derive(Clone, Debug, PartialEq)]
pub struct Eff {
    pub labels: BTreeSet<Label>,
    pub tail: Option<EffTail>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum EffTail {
    Var(EvId),
    Gen(usize),
}

impl Eff {
    pub fn pure_() -> Eff {
        Eff { labels: BTreeSet::new(), tail: None }
    }
    pub fn label(l: Label) -> Eff {
        let mut s = BTreeSet::new();
        s.insert(l);
        Eff { labels: s, tail: None }
    }
    pub fn var(v: EvId) -> Eff {
        Eff { labels: BTreeSet::new(), tail: Some(EffTail::Var(v)) }
    }
}

pub fn label_name(l: Label, others: &[String]) -> String {
    match l {
        Label::Io => "io".into(),
        Label::Async => "async".into(),
        Label::Spawn => "spawn".into(),
        Label::Other(i) => others.get(i as usize).cloned().unwrap_or_default(),
    }
}

// ---------------------------------------------------------------------------
// The variable store

#[derive(Clone, Debug)]
pub struct Store {
    pub tvars: Vec<(Option<Ty>, u32)>,
    /// type variables that must support comparison (sorting, `<`)
    pub tord: Vec<bool>,
    pub kvars: Vec<Option<Kind>>,
    pub uvars: Vec<Option<Unit>>,
    pub evars: Vec<Option<Eff>>,
    /// level of each kind/unit/effect var for generalization
    pub klevel: Vec<u32>,
    pub ulevel: Vec<u32>,
    pub elevel: Vec<u32>,
    pub level: u32,
    pub other_labels: Vec<String>,
}

impl Store {
    pub fn new() -> Store {
        Store {
            tvars: Vec::new(),
            tord: Vec::new(),
            kvars: Vec::new(),
            uvars: Vec::new(),
            evars: Vec::new(),
            klevel: Vec::new(),
            ulevel: Vec::new(),
            elevel: Vec::new(),
            level: 1,
            other_labels: Vec::new(),
        }
    }

    pub fn fresh(&mut self) -> Ty {
        self.tvars.push((None, self.level));
        self.tord.push(false);
        Ty::Var(self.tvars.len() - 1)
    }
    pub fn fresh_kind(&mut self) -> Kind {
        self.kvars.push(None);
        self.klevel.push(self.level);
        Kind::Var(self.kvars.len() - 1)
    }
    pub fn fresh_unit(&mut self) -> Unit {
        self.uvars.push(None);
        self.ulevel.push(self.level);
        Unit::atom(UAtom::Var(self.uvars.len() - 1))
    }
    pub fn fresh_uvar(&mut self) -> UvId {
        self.uvars.push(None);
        self.ulevel.push(self.level);
        self.uvars.len() - 1
    }
    pub fn fresh_evar(&mut self) -> EvId {
        self.evars.push(None);
        self.elevel.push(self.level);
        self.evars.len() - 1
    }
    pub fn fresh_eff(&mut self) -> Eff {
        Eff::var(self.fresh_evar())
    }
    pub fn fresh_num(&mut self) -> Ty {
        let k = self.fresh_kind();
        Ty::Num(k, Unit::one())
    }

    pub fn label_of(&mut self, name: &str) -> Label {
        match name {
            "io" => Label::Io,
            "async" => Label::Async,
            "spawn" => Label::Spawn,
            other => {
                if let Some(i) = self.other_labels.iter().position(|x| x == other) {
                    Label::Other(i as u32)
                } else {
                    self.other_labels.push(other.to_string());
                    Label::Other((self.other_labels.len() - 1) as u32)
                }
            }
        }
    }

    // ---- resolution ----

    pub fn kind(&self, k: Kind) -> Kind {
        let mut k = k;
        while let Kind::Var(v) = k {
            match self.kvars[v] {
                Some(k2) => k = k2,
                None => return k,
            }
        }
        k
    }

    pub fn unit(&self, u: &Unit) -> Unit {
        let mut out = Unit::one();
        for (a, e) in &u.0 {
            match a {
                UAtom::Var(v) => match &self.uvars[*v] {
                    Some(b) => {
                        let r = self.unit(b);
                        out = out.mul(&r.pow(*e));
                    }
                    None => out = out.mul(&Unit::atom(a.clone()).pow(*e)),
                },
                _ => out = out.mul(&Unit::atom(a.clone()).pow(*e)),
            }
        }
        out
    }

    pub fn eff(&self, e: &Eff) -> Eff {
        let mut labels = e.labels.clone();
        let mut tail = e.tail;
        while let Some(EffTail::Var(v)) = tail {
            match &self.evars[v] {
                Some(b) => {
                    labels.extend(b.labels.iter().cloned());
                    tail = b.tail;
                }
                None => break,
            }
        }
        Eff { labels, tail }
    }

    /// Shallow resolution of a type variable.
    pub fn shallow(&self, t: &Ty) -> Ty {
        let mut t = t.clone();
        loop {
            match t {
                Ty::Var(v) => match &self.tvars[v].0 {
                    Some(b) => t = b.clone(),
                    None => return t,
                },
                Ty::Num(k, u) => return Ty::Num(self.kind(k), self.unit(&u)),
                _ => return t,
            }
        }
    }

    /// Full resolution.
    pub fn resolve(&self, t: &Ty) -> Ty {
        match self.shallow(t) {
            Ty::Con(n, args) => Ty::Con(n, args.iter().map(|a| self.resolve(a)).collect()),
            Ty::Fun(a, e, r) => Ty::Fun(Box::new(self.resolve(&a)), self.eff(&e), Box::new(self.resolve(&r))),
            Ty::Tuple(ts) => Ty::Tuple(ts.iter().map(|a| self.resolve(a)).collect()),
            other => other,
        }
    }

    pub fn occurs(&self, v: TvId, t: &Ty) -> bool {
        match self.shallow(t) {
            Ty::Var(w) => w == v,
            Ty::Con(_, args) => args.iter().any(|a| self.occurs(v, a)),
            Ty::Fun(a, _, r) => self.occurs(v, &a) || self.occurs(v, &r),
            Ty::Tuple(ts) => ts.iter().any(|a| self.occurs(v, a)),
            _ => false,
        }
    }

    /// Lower the level of every variable in `t` to at most `lvl`.
    pub fn adjust_levels(&mut self, t: &Ty, lvl: u32) {
        match self.shallow(t) {
            Ty::Var(w) => {
                if self.tvars[w].1 > lvl {
                    self.tvars[w].1 = lvl;
                }
            }
            Ty::Con(_, args) => {
                for a in args {
                    self.adjust_levels(&a, lvl);
                }
            }
            Ty::Fun(a, e, r) => {
                self.adjust_levels(&a, lvl);
                self.adjust_eff_levels(&e, lvl);
                self.adjust_levels(&r, lvl);
            }
            Ty::Tuple(ts) => {
                for a in ts {
                    self.adjust_levels(&a, lvl);
                }
            }
            Ty::Num(k, u) => {
                if let Kind::Var(kv) = self.kind(k) {
                    if self.klevel[kv] > lvl {
                        self.klevel[kv] = lvl;
                    }
                }
                for a in self.unit(&u).0.keys() {
                    if let UAtom::Var(uv) = a {
                        if self.ulevel[*uv] > lvl {
                            self.ulevel[*uv] = lvl;
                        }
                    }
                }
            }
            Ty::Gen(_) => {}
        }
    }

    pub fn adjust_eff_levels(&mut self, e: &Eff, lvl: u32) {
        let e = self.eff(e);
        if let Some(EffTail::Var(v)) = e.tail {
            if self.elevel[v] > lvl {
                self.elevel[v] = lvl;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Schemes

#[derive(Clone, Debug)]
pub struct Scheme {
    pub ty: Ty,
    /// generic variables that must support comparison
    pub ord: Vec<usize>,
}

impl Scheme {
    pub fn mono(ty: Ty) -> Scheme {
        Scheme { ty, ord: Vec::new() }
    }
}

#[derive(Default)]
pub struct Inst {
    pub t: HashMap<usize, Ty>,
    pub k: HashMap<usize, Kind>,
    pub u: HashMap<usize, Unit>,
    pub e: HashMap<usize, Eff>,
}

impl Store {
    pub fn instantiate(&mut self, s: &Scheme) -> Ty {
        let mut inst = Inst::default();
        let t = self.inst_ty(&s.ty, &mut inst);
        for i in &s.ord {
            if let Some(Ty::Var(v)) = inst.t.get(i) {
                self.tord[*v] = true;
            }
        }
        t
    }

    pub fn inst_ty(&mut self, t: &Ty, m: &mut Inst) -> Ty {
        match t {
            Ty::Gen(i) => {
                if let Some(x) = m.t.get(i) {
                    return x.clone();
                }
                let v = self.fresh();
                m.t.insert(*i, v.clone());
                v
            }
            Ty::Var(_) => t.clone(),
            Ty::Con(n, args) => Ty::Con(n.clone(), args.iter().map(|a| self.inst_ty(a, m)).collect()),
            Ty::Fun(a, e, r) => {
                let a = self.inst_ty(a, m);
                let e = self.inst_eff(e, m);
                let r = self.inst_ty(r, m);
                Ty::Fun(Box::new(a), e, Box::new(r))
            }
            Ty::Tuple(ts) => Ty::Tuple(ts.iter().map(|a| self.inst_ty(a, m)).collect()),
            Ty::Num(k, u) => {
                let k = match k {
                    Kind::Gen(i) => {
                        if let Some(x) = m.k.get(i) {
                            *x
                        } else {
                            let v = self.fresh_kind();
                            m.k.insert(*i, v);
                            v
                        }
                    }
                    other => *other,
                };
                let u = self.inst_unit(u, m);
                Ty::Num(k, u)
            }
        }
    }

    pub fn inst_unit(&mut self, u: &Unit, m: &mut Inst) -> Unit {
        let mut out = Unit::one();
        for (a, e) in &u.0 {
            let base = match a {
                UAtom::Gen(i) => {
                    if let Some(x) = m.u.get(i) {
                        x.clone()
                    } else {
                        let v = self.fresh_unit();
                        m.u.insert(*i, v.clone());
                        v
                    }
                }
                other => Unit::atom(other.clone()),
            };
            out = out.mul(&base.pow(*e));
        }
        out
    }

    pub fn inst_eff(&mut self, e: &Eff, m: &mut Inst) -> Eff {
        match e.tail {
            Some(EffTail::Gen(i)) => {
                let tail = if let Some(x) = m.e.get(&i) {
                    x.clone()
                } else {
                    let v = self.fresh_eff();
                    m.e.insert(i, v.clone());
                    v
                };
                let mut labels = e.labels.clone();
                labels.extend(tail.labels.iter().cloned());
                Eff { labels, tail: tail.tail }
            }
            _ => e.clone(),
        }
    }

    /// Generalize variables above the current level.
    pub fn generalize(&mut self, t: &Ty) -> Scheme {
        let mut g = Gener::default();
        let ty = self.gen_ty(t, &mut g);
        let mut ord: Vec<usize> = g.t.iter().filter(|(v, _)| self.tord[**v]).map(|(_, i)| *i).collect();
        ord.sort();
        Scheme { ty, ord }
    }

    fn gen_ty(&mut self, t: &Ty, g: &mut Gener) -> Ty {
        match self.shallow(t) {
            Ty::Var(v) => {
                if self.tvars[v].1 > self.level {
                    let n = g.t.len();
                    let i = *g.t.entry(v).or_insert(n);
                    Ty::Gen(i)
                } else {
                    Ty::Var(v)
                }
            }
            Ty::Con(n, args) => Ty::Con(n, args.iter().map(|a| self.gen_ty(a, g)).collect()),
            Ty::Fun(a, e, r) => {
                let a = self.gen_ty(&a, g);
                let e = self.gen_eff(&e, g);
                let r = self.gen_ty(&r, g);
                Ty::Fun(Box::new(a), e, Box::new(r))
            }
            Ty::Tuple(ts) => Ty::Tuple(ts.iter().map(|a| self.gen_ty(a, g)).collect()),
            Ty::Num(k, u) => {
                let k = match self.kind(k) {
                    Kind::Var(kv) if self.klevel[kv] > self.level => {
                        let n = g.k.len();
                        Kind::Gen(*g.k.entry(kv).or_insert(n))
                    }
                    other => other,
                };
                let u = self.unit(&u);
                let mut out = Unit::one();
                for (a, e) in &u.0 {
                    let na = match a {
                        UAtom::Var(uv) if self.ulevel[*uv] > self.level => {
                            let n = g.u.len();
                            UAtom::Gen(*g.u.entry(*uv).or_insert(n))
                        }
                        other => other.clone(),
                    };
                    out = out.mul(&Unit::atom(na).pow(*e));
                }
                Ty::Num(k, out)
            }
            Ty::Gen(i) => Ty::Gen(i),
        }
    }

    fn gen_eff(&mut self, e: &Eff, g: &mut Gener) -> Eff {
        let e = self.eff(e);
        match e.tail {
            Some(EffTail::Var(v)) if self.elevel[v] > self.level => {
                let n = g.e.len();
                let i = *g.e.entry(v).or_insert(n);
                Eff { labels: e.labels, tail: Some(EffTail::Gen(i)) }
            }
            _ => e,
        }
    }
}

#[derive(Default)]
struct Gener {
    t: HashMap<TvId, usize>,
    k: HashMap<KvId, usize>,
    u: HashMap<UvId, usize>,
    e: HashMap<EvId, usize>,
}

// ---------------------------------------------------------------------------
// Printing

/// Names type/unit variables 'a, 'b, ... in order of first appearance.
#[derive(Default)]
pub struct Namer {
    names: HashMap<String, String>,
    count: usize,
    /// unit variables are lettered on their own
    ucount: usize,
}

impl Namer {
    fn name(&mut self, key: String) -> String {
        if let Some(n) = self.names.get(&key) {
            return n.clone();
        }
        let i = self.count;
        self.count += 1;
        let n = var_name(i);
        self.names.insert(key, n.clone());
        n
    }

    fn unit_name(&mut self, key: String) -> String {
        if let Some(n) = self.names.get(&key) {
            return n.clone();
        }
        let i = self.ucount;
        self.ucount += 1;
        let n = var_name(i);
        self.names.insert(key, n.clone());
        n
    }
}

pub fn var_name(i: usize) -> String {
    let letter = (b'a' + (i % 26) as u8) as char;
    if i < 26 {
        format!("'{}", letter)
    } else {
        format!("'{}{}", letter, i / 26)
    }
}

impl Store {
    pub fn show(&self, t: &Ty) -> String {
        let mut n = Namer::default();
        self.show_with(t, &mut n)
    }

    pub fn show_with(&self, t: &Ty, n: &mut Namer) -> String {
        let t = self.resolve(t);
        self.fmt_ty(&t, n)
    }

    fn fmt_ty(&self, t: &Ty, n: &mut Namer) -> String {
        match t {
            Ty::Var(v) => n.name(format!("t{}", v)),
            Ty::Gen(i) => n.name(format!("g{}", i)),
            // an active pattern's result is shown by its cases alone
            Ty::Con(name, _) if name.starts_with("(|") => name.clone(),
            Ty::Con(name, args) => {
                let mut s = name.clone();
                for a in args {
                    s.push(' ');
                    s.push_str(&self.fmt_atom(a, n));
                }
                s
            }
            Ty::Num(k, u) => {
                let base = match k {
                    Kind::Float => "float",
                    _ => "int",
                };
                let u = self.unit(u);
                if u.is_one() {
                    base.to_string()
                } else {
                    format!("{}<{}>", base, self.fmt_unit(&u, n))
                }
            }
            Ty::Fun(a, e, r) => {
                let arg = match **a {
                    Ty::Fun(..) => format!("({})", self.fmt_ty(a, n)),
                    Ty::Con(ref name, ref args) if !args.is_empty() && !name.starts_with("(|") => format!("({})", self.fmt_ty(a, n)),
                    _ => self.fmt_ty(a, n),
                };
                let e = self.eff(e);
                let arrow = if e.labels.is_empty() {
                    "->".to_string()
                } else {
                    let ls: Vec<String> = e.labels.iter().map(|l| label_name(*l, &self.other_labels)).collect();
                    format!("->{{{}}}", ls.join(", "))
                };
                format!("{} {} {}", arg, arrow, self.fmt_ty(r, n))
            }
            Ty::Tuple(ts) => {
                let v: Vec<String> = ts.iter().map(|x| self.fmt_ty(x, n)).collect();
                format!("({})", v.join(", "))
            }
        }
    }

    fn fmt_atom(&self, t: &Ty, n: &mut Namer) -> String {
        match t {
            Ty::Fun(..) => format!("({})", self.fmt_ty(t, n)),
            Ty::Con(_, args) if !args.is_empty() => format!("({})", self.fmt_ty(t, n)),
            _ => self.fmt_ty(t, n),
        }
    }

    pub fn fmt_unit(&self, u: &Unit, n: &mut Namer) -> String {
        // variables first (in order of appearance), then base units
        let mut num: Vec<String> = Vec::new();
        let mut den: Vec<String> = Vec::new();
        let mut items: Vec<(String, i64, bool)> = Vec::new();
        for (a, e) in &u.0 {
            match a {
                UAtom::Var(v) => items.push((format!("u{}", v), *e, true)),
                UAtom::Gen(i) => items.push((format!("ug{}", i), *e, true)),
                UAtom::Base(b) => items.push((b.clone(), *e, false)),
            }
        }
        for (key, e, is_var) in items {
            let name = if is_var { n.unit_name(key) } else { key };
            let s = |p: i64| if p == 1 { name.clone() } else { format!("{}^{}", name, p) };
            if e > 0 {
                num.push(s(e));
            } else {
                den.push(s(-e));
            }
        }
        if den.is_empty() {
            num.join(" ")
        } else if num.is_empty() {
            format!("1/{}", den.join(" "))
        } else {
            format!("{}/{}", num.join(" "), den.join(" "))
        }
    }
}

pub fn unit_vars(u: &Unit) -> BTreeSet<UvId> {
    u.0.keys()
        .filter_map(|a| match a {
            UAtom::Var(v) => Some(*v),
            _ => None,
        })
        .collect()
}
