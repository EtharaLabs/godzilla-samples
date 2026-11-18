// Typed holes: the type a hole expects, and fitting suggestions.

use crate::builtins::BUILTINS;
use crate::infer::{Checker, HoleInfo};
use crate::types::*;
use std::collections::HashSet;

struct Cand {
    name: String,
    scheme: Scheme,
    user: bool,
    base: usize,
}

fn count_vars(t: &Ty, seen: &mut HashSet<String>) {
    match t {
        Ty::Gen(i) => {
            seen.insert(format!("t{}", i));
        }
        Ty::Var(v) => {
            seen.insert(format!("v{}", v));
        }
        Ty::Con(_, args) => {
            for a in args {
                count_vars(a, seen);
            }
        }
        Ty::Tuple(ts) => {
            for a in ts {
                count_vars(a, seen);
            }
        }
        Ty::Fun(a, e, r) => {
            count_vars(a, seen);
            if let Some(EffTail::Gen(i)) = e.tail {
                seen.insert(format!("e{}", i));
            }
            count_vars(r, seen);
        }
        Ty::Num(k, u) => {
            if let Kind::Gen(i) = k {
                seen.insert(format!("k{}", i));
            }
            for a in u.0.keys() {
                if let UAtom::Gen(i) = a {
                    seen.insert(format!("u{}", i));
                }
            }
        }
    }
}

/// Quantified variables of a scheme.
fn scheme_vars(s: &Scheme) -> usize {
    let mut seen = HashSet::new();
    count_vars_gen(&s.ty, &mut seen);
    seen.len()
}

fn count_vars_gen(t: &Ty, seen: &mut HashSet<String>) {
    // only quantified variables count; a monomorphic variable is a fixed type
    let mut all = HashSet::new();
    count_vars(t, &mut all);
    for x in all {
        if !x.starts_with('v') {
            seen.insert(x);
        }
    }
}

fn camel_words(name: &str) -> Vec<String> {
    let member = name.rsplit('.').next().unwrap_or(name);
    let mut words = Vec::new();
    let mut cur = String::new();
    for c in member.chars() {
        if c.is_uppercase() && !cur.is_empty() {
            words.push(cur.to_lowercase());
            cur.clear();
        }
        if c == '_' {
            if !cur.is_empty() {
                words.push(cur.to_lowercase());
                cur.clear();
            }
            continue;
        }
        cur.push(c);
    }
    if !cur.is_empty() {
        words.push(cur.to_lowercase());
    }
    words
}

fn name_matches(hole: &Option<String>, name: &str) -> bool {
    let Some(h) = hole else { return false };
    let h = h.to_lowercase();
    let member = name.rsplit('.').next().unwrap_or(name).to_lowercase();
    // (a name shorter than three letters only matches itself)
    if h.chars().count() < 3 {
        return member == h;
    }
    member.contains(&h) || (member.chars().count() >= 3 && h.contains(&member))
}

fn is_bare_var(c: &Checker, t: &Ty) -> bool {
    matches!(c.st.shallow(t), Ty::Var(_) | Ty::Gen(_))
}

impl Checker {
    /// Every name a hole could be filled with, in enumeration order: the
    /// prelude, constructors (by name), names in scope (by name), library
    /// module members, then members of the program's own modules.
    fn candidates(&self, h: &HoleInfo) -> Vec<Cand> {
        let mut scope: Vec<(String, Scheme)> = Vec::new();
        let mut members: Vec<(String, Scheme)> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for (n, s) in h.scope.iter().rev() {
            if seen.contains(n) {
                continue;
            }
            seen.insert(n.clone());
            if n.contains('.') {
                members.push((n.clone(), s.clone()));
            } else {
                scope.push((n.clone(), s.clone()));
            }
        }
        scope.sort_by(|a, b| a.0.cmp(&b.0));
        members.sort_by(|a, b| a.0.cmp(&b.0));
        let mut out = Vec::new();
        let mut base = 0;
        let mut push = |out: &mut Vec<Cand>, name: &str, scheme: Scheme, user: bool| {
            out.push(Cand { name: name.to_string(), scheme, user, base });
            base += 1;
        };
        for b in BUILTINS {
            if b.name.contains('.') {
                continue;
            }
            // a prelude name the program rebinds keeps its place, with the
            // binding in scope
            if seen.contains(b.name) {
                if let Some(i) = scope.iter().position(|(n, _)| n == b.name) {
                    let (n, sc) = scope.remove(i);
                    push(&mut out, &n, sc, true);
                }
                continue;
            }
            push(&mut out, b.name, builtin_scheme(self, b.name), false);
        }
        let mut ctor_names: Vec<&String> = self.ctors.keys().collect();
        ctor_names.sort();
        for cn in ctor_names {
            let c = &self.ctors[cn];
            let mut st = self.st.clone();
            let t = ctor_scheme(&mut st, c);
            push(&mut out, cn, t, false);
        }
        for (n, sc) in scope {
            push(&mut out, &n, sc, true);
        }
        for b in BUILTINS {
            if !b.name.contains('.') {
                continue;
            }
            push(&mut out, b.name, builtin_scheme(self, b.name), false);
        }
        for (n, sc) in members {
            push(&mut out, &n, sc, true);
        }
        out
    }

    /// Does an instance of `s`, applied to `k` arguments, fit `hole`?
    fn fits(&mut self, s: &Scheme, k: usize, hole: &Ty) -> bool {
        let saved = self.st.clone();
        let mut t = self.st.instantiate(s);
        let mut ok = true;
        for _ in 0..k {
            match self.st.shallow(&t) {
                Ty::Fun(_, _, r) => t = *r,
                _ => {
                    ok = false;
                    break;
                }
            }
        }
        if ok && k > 0 && is_bare_var(self, &t) {
            ok = false;
        }
        if ok {
            ok = self.unify(hole, &t).is_ok();
        }
        self.st = saved;
        ok
    }

    pub fn hole_suggestions(&mut self, h: &HoleInfo) -> (Vec<String>, usize, Vec<String>, usize) {
        let ht = self.st.resolve(&h.ty);
        if is_bare_var(self, &ht) {
            return (vec![], 0, vec![], 0);
        }
        let cands = self.candidates(h);
        // ordered by arguments still needed, then quantified variables
        // (the most specific first), then enumeration order
        let mut tries: Vec<(usize, usize, usize, String)> = Vec::new();
        let mut ors: Vec<(usize, usize, usize, String)> = Vec::new();
        for c in &cands {
            // (the sums by a key rank as if one variable more)
            let vars = scheme_vars(&c.scheme) + usize::from(!c.user && matches!(c.name.as_str(), "List.sumBy" | "Seq.sumBy"));
            if self.fits(&c.scheme, 0, &ht) {
                tries.push((0, vars, c.base, c.name.clone()));
            }
            for k in 1..=2 {
                if self.fits(&c.scheme, k, &ht) {
                    let shown = format!("{}{}", c.name, " ?".repeat(k));
                    ors.push((k, vars, c.base, shown));
                    break;
                }
            }
        }
        tries.sort();
        ors.sort();
        // (the hole's own name first, then names sharing part of it)
        let promote = |v: Vec<(usize, usize, usize, String)>| -> Vec<String> {
            let member = |x: &(usize, usize, usize, String)| -> String {
                let n = x.3.trim_end_matches(" ?").trim_end_matches(" ?");
                n.rsplit('.').next().unwrap_or(n).to_lowercase()
            };
            let own = h.name.as_ref().map(|n| n.to_lowercase());
            let (exact, v): (Vec<_>, Vec<_>) = v.into_iter().partition(|x| own.as_deref() == Some(member(x).as_str()));
            let (m, rest): (Vec<_>, Vec<_>) = v.into_iter().partition(|x| {
                let n = x.3.trim_end_matches(" ?").trim_end_matches(" ?");
                name_matches(&h.name, n)
            });
            exact.into_iter().chain(m).chain(rest).map(|x| x.3).collect()
        };
        let tries = promote(tries);
        let shown: Vec<String> = tries.iter().take(6).cloned().collect();
        let ors: Vec<String> = promote(ors).into_iter().filter(|o| !shown.contains(&o.trim_end_matches(" ?").trim_end_matches(" ?").to_string())).collect();
        let tn = tries.len();
        let on = ors.len();
        (tries, tn, ors, on)
    }
}

/// A builtin's scheme with what must support comparison marked.
fn builtin_scheme(c: &Checker, name: &str) -> Scheme {
    let mut s = c.builtins[name].clone();
    if let Some(g) = crate::check_expr::builtin_ord_gen(name) {
        s.ord.push(g);
    }
    s
}

fn ctor_scheme(st: &mut Store, c: &crate::infer::CtorInfo) -> Scheme {
    let params: Vec<Ty> = (0..c.params).map(Ty::Gen).collect();
    let mut t = Ty::Con(c.type_name.clone(), params);
    for a in c.args.iter().rev() {
        t = Ty::Fun(Box::new(a.clone()), Eff::pure_(), Box::new(t));
    }
    let _ = st;
    Scheme::mono(t)
}

/// The ` — try: … — or: …` suffix for a hole message.
pub fn suggest_text(c: &Checker, h: &HoleInfo) -> String {
    let mut c2 = clone_checker(c);
    let (tries, tn, ors, on) = c2.hole_suggestions(h);
    let mut s = String::new();
    if !tries.is_empty() {
        s.push_str(" — try: ");
        s.push_str(&tries.iter().take(6).cloned().collect::<Vec<_>>().join(", "));
        if tn > 6 {
            s.push_str(&format!(", and {} more", tn - 6));
        }
    }
    if !ors.is_empty() {
        s.push_str(" — or: ");
        s.push_str(&ors.iter().take(4).cloned().collect::<Vec<_>>().join(", "));
        if on > 4 {
            s.push_str(&format!(", and {} more", on - 4));
        }
    }
    s
}

fn clone_checker(c: &Checker) -> Checker {
    let mut n = Checker::new();
    n.st = c.st.clone();
    n.types = c.types.clone();
    n.ctors = c.ctors.clone();
    n.fields = c.fields.clone();
    n.measures = c.measures.clone();
    n.builtins = c.builtins.clone();
    n.modules = c.modules.clone();
    n
}

/// The note text for a hole.
pub fn hole_message(c: &Checker, h: &HoleInfo) -> String {
    let t = c.st.show(&h.ty);
    let name = match &h.name {
        Some(n) => format!("?{}", n),
        None => "?".to_string(),
    };
    format!("hole `{}` has type `{}`{}", name, t, suggest_text(c, h))
}
