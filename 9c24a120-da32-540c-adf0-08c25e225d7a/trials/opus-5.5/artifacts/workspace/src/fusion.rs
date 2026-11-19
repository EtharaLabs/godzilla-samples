// Fold fusion: `List.fold`/`Seq.fold` that build a collection lower to an
// in-place loop with the step function inlined.

use crate::ast::*;
use crate::lower::*;
use crate::py::*;
use std::collections::HashMap;

/// The accumulator: one collection, or a tuple destructured by the step.
#[derive(Clone)]
enum Acc {
    One(String),
    Tuple(String, Vec<String>),
}

fn is_var(e: &Expr, n: &str) -> bool {
    matches!(&e.kind, ExprKind::Var(x) if x == n)
}

/// An update of collection `c`: Map.add k v c | List.concat c x | Set.add x c
fn update_of<'e>(e: &'e Expr, c: &str) -> Option<(&'static str, Vec<&'e Expr>)> {
    let (f, args) = crate::lower2::tail_spine(e)?;
    let ExprKind::Qual(p, n, _) = &f.kind else { return None };
    if p.len() != 1 || args.len() != 3 && !(args.len() == 2) {
        return None;
    }
    match (p[0].as_str(), n.as_str()) {
        ("Map", "add") if args.len() == 3 && is_var(args[2], c) => Some(("mapadd", vec![args[0], args[1]])),
        ("List", "concat") if args.len() == 2 && is_var(args[0], c) => {
            if let ExprKind::List(items) = &args[1].kind {
                if items.len() == 1 {
                    return Some(("append", vec![&items[0]]));
                }
            }
            Some(("extend", vec![args[1]]))
        }
        ("Set", "add") if args.len() == 2 && is_var(args[1], c) => Some(("setadd", vec![args[0]])),
        _ => None,
    }
}

fn result_ok(e: &Expr, acc: &Acc) -> bool {
    match &e.kind {
        ExprKind::If(_, a, b) => result_ok(a, acc) && result_ok(b, acc),
        ExprKind::Match(_, arms) => arms.iter().all(|a| result_ok(&a.body, acc)),
        ExprKind::Block(stmts) => match stmts.last() {
            Some(Stmt::Expr(x)) => stmts[..stmts.len() - 1].iter().all(|s| matches!(s, Stmt::Let(_))) && result_ok(x, acc),
            _ => false,
        },
        _ => match acc {
            Acc::One(c) => is_var(e, c) || update_of(e, c).is_some(),
            Acc::Tuple(whole, comps) => {
                if is_var(e, whole) {
                    return true;
                }
                match &e.kind {
                    ExprKind::Tuple(items) if items.len() == comps.len() => {
                        items.iter().zip(comps.iter()).all(|(x, c)| is_var(x, c) || update_of(x, c).is_some())
                    }
                    _ => false,
                }
            }
        },
    }
}

fn atomic(e: &PE) -> bool {
    match e {
        PE::Name(_) | PE::Int(_) | PE::Float(_) | PE::Str(_) | PE::Bool(_) | PE::NoneV => true,
        PE::Attr(b, _) => atomic(b),
        _ => false,
    }
}

impl<'a> Lowerer<'a> {
    /// Try to fuse `fold step init coll`; returns the fold's value.
    pub fn fuse_fold(&mut self, step: &Expr, init: &Expr, coll: &Expr) -> Option<PE> {
        let (params, body) = match &step.kind {
            ExprKind::Lambda(ps, b) => (ps.clone(), (**b).clone()),
            ExprKind::Var(n) => {
                let b = self.lookup(n)?;
                let def = self.fn_asts.get(&b.py)?;
                (def.0.clone(), def.1.clone())
            }
            _ => return None,
        };
        if params.len() != 2 {
            return None;
        }
        let PatKind::Var(acc_name) = &params[0].kind else { return None };
        // the accumulator: a tuple destructured at the top of the body?
        let (acc, inner) = match &body.kind {
            ExprKind::Match(s, arms) if arms.len() == 1 && is_var(s, acc_name) && arms[0].guard.is_none() => match &arms[0].pat.kind {
                PatKind::Tuple(ps) if ps.iter().all(|p| matches!(p.kind, PatKind::Var(_))) => {
                    let comps: Vec<String> = ps
                        .iter()
                        .map(|p| match &p.kind {
                            PatKind::Var(n) => n.clone(),
                            _ => unreachable!(),
                        })
                        .collect();
                    (Acc::Tuple(acc_name.clone(), comps), arms[0].body.clone())
                }
                _ => (Acc::One(acc_name.clone()), body.clone()),
            },
            _ => (Acc::One(acc_name.clone()), body.clone()),
        };
        if !result_ok(&inner, &acc) {
            return None;
        }
        // initial values
        let inits: Vec<&Expr> = match (&acc, &init.kind) {
            (Acc::One(_), _) => vec![init],
            (Acc::Tuple(_, comps), ExprKind::Tuple(items)) if items.len() == comps.len() => items.iter().collect(),
            _ => return None,
        };
        let names: Vec<String> = match &acc {
            Acc::One(c) => vec![c.clone()],
            Acc::Tuple(_, comps) => comps.clone(),
        };
        let mut init_vals = Vec::new();
        for (i, e) in inits.iter().enumerate() {
            let v = self.fold_init(e);
            init_vals.push((names[i].clone(), v));
        }
        let cv = self.expr(coll);
        // the loop
        self.scopes.push(HashMap::new());
        let mut pys = Vec::new();
        for (n, v) in init_vals {
            let py = mangle(&n);
            self.pre.push(PS::Assign(name(&py), v));
            pys.push(py);
        }
        self.scopes.pop();
        for n in &names {
            self.bind(n, BKind::Value, true);
        }
        if let Acc::Tuple(whole, _) = &acc {
            // `acc` itself means "unchanged"
            self.bind(whole, BKind::Value, false);
        }
        self.scopes.push(HashMap::new());
        let target = match &params[1].kind {
            PatKind::Var(n) => name(&self.bind(n, BKind::Value, false)),
            PatKind::Wild => name("_"),
            _ => {
                let t = self.tuple_target(&params[1]);
                PE::Raw(Printer { py311: false }.expr(&t))
            }
        };
        self.fold_depth += 1;
        let saved = std::mem::take(&mut self.pre);
        let body_stmts = self.fold_body(&inner, &acc);
        self.pre = saved;
        self.fold_depth -= 1;
        self.scopes.pop();
        let body_stmts = if body_stmts.is_empty() { vec![PS::Pass] } else { body_stmts };
        self.pre.push(PS::For(target, cv, body_stmts));
        Some(match &acc {
            Acc::One(_) => name(&pys[0]),
            Acc::Tuple(..) => PE::Tuple(pys.iter().map(|p| name(p)).collect()),
        })
    }

    fn fold_init(&mut self, e: &Expr) -> PE {
        match &e.kind {
            ExprKind::List(_) => self.expr(e),
            ExprKind::Qual(p, n, _) if p.len() == 1 && n == "empty" => self.expr(e),
            _ => {
                let v = self.expr(e);
                let ty = self.ty_of(e.span);
                let f = match ty {
                    Some(crate::types::Ty::Con(t, _)) => match t.as_str() {
                        "Map" => "dict",
                        "Set" => "set",
                        _ => "list",
                    },
                    _ => "list",
                };
                call_n(f, vec![v])
            }
        }
    }

    /// Statements for a step body: results become in-place updates.
    fn fold_body(&mut self, e: &Expr, acc: &Acc) -> Vec<PS> {
        match &e.kind {
            ExprKind::If(c, a, b) => {
                let saved = std::mem::take(&mut self.pre);
                let cv = self.expr(c);
                let mut out = std::mem::replace(&mut self.pre, saved);
                let mut arms = Vec::new();
                let tb = self.fold_body(a, acc);
                arms.push((cv, if tb.is_empty() { vec![PS::Pass] } else { tb }));
                let mut cur = &**b;
                let els;
                loop {
                    if let ExprKind::If(c2, a2, b2) = &cur.kind {
                        let saved = std::mem::take(&mut self.pre);
                        let cv2 = self.expr(c2);
                        let p = std::mem::replace(&mut self.pre, saved);
                        if p.is_empty() {
                            let tb2 = self.fold_body(a2, acc);
                            arms.push((cv2, if tb2.is_empty() { vec![PS::Pass] } else { tb2 }));
                            cur = b2;
                            continue;
                        }
                    }
                    let eb = self.fold_body(cur, acc);
                    els = if eb.is_empty() { None } else { Some(eb) };
                    break;
                }
                out.push(PS::If(arms, els));
                out
            }
            ExprKind::Match(s, arms) => {
                let saved = std::mem::take(&mut self.pre);
                let subj = self.expr(s);
                let mut out = std::mem::replace(&mut self.pre, saved);
                let mut cases = Vec::new();
                for a in arms {
                    self.scopes.push(HashMap::new());
                    let pt = self.pat_ty(a.pat.span);
                    let pat = self.py_pat(&a.pat, pt.as_ref());
                    let guard = a.guard.as_ref().map(|g| self.expr(g));
                    let body = self.fold_body(&a.body, acc);
                    self.scopes.pop();
                    cases.push(Case { pat, guard, body: if body.is_empty() { vec![PS::Pass] } else { body } });
                }
                let last_irref = arms.last().map_or(false, |a| a.guard.is_none() && crate::lower3::irrefutable(&a.pat));
                if !last_irref {
                    cases.push(Case {
                        pat: PPat::Wild,
                        guard: None,
                        body: vec![PS::Raise(call_n("RuntimeError", vec![PE::Str("non-exhaustive match".into())]))],
                    });
                }
                out.push(PS::Match(subj, cases));
                out
            }
            ExprKind::Block(stmts) => {
                let mut out = Vec::new();
                for s in &stmts[..stmts.len() - 1] {
                    out.extend(self.block_stmt(s));
                }
                if let Some(Stmt::Expr(x)) = stmts.last() {
                    out.extend(self.fold_body(x, acc));
                }
                out
            }
            _ => match acc {
                Acc::One(c) => self.fold_update(e, c),
                Acc::Tuple(_, comps) => match &e.kind {
                    ExprKind::Tuple(items) => {
                        let mut out = Vec::new();
                        for (x, c) in items.iter().zip(comps.iter()) {
                            out.extend(self.fold_update(x, c));
                        }
                        out
                    }
                    _ => vec![],
                },
            },
        }
    }

    fn fold_update(&mut self, e: &Expr, c: &str) -> Vec<PS> {
        let Some((kind, args)) = update_of(e, c) else { return vec![] };
        let saved = std::mem::take(&mut self.pre);
        let mut vals = Vec::new();
        for a in &args {
            let v = self.expr(a);
            vals.push(v);
        }
        let mut out = std::mem::replace(&mut self.pre, saved);
        let vals: Vec<PE> = vals
            .into_iter()
            .map(|v| {
                if atomic(&v) {
                    v
                } else {
                    let t = self.new_tmp();
                    out.push(PS::Assign(name(&t), v));
                    name(&t)
                }
            })
            .collect();
        let cn = name(&mangle(c));
        match kind {
            "mapadd" => out.push(PS::Assign(PE::Index(Box::new(cn), Box::new(vals[0].clone())), vals[1].clone())),
            "append" => out.push(PS::Expr(PE::Call(Box::new(attr(cn, "append")), vec![vals[0].clone()], vec![]))),
            "extend" => out.push(PS::Expr(PE::Call(Box::new(attr(cn, "extend")), vec![vals[0].clone()], vec![]))),
            "setadd" => out.push(PS::Expr(PE::Call(Box::new(attr(cn, "add")), vec![vals[0].clone()], vec![]))),
            _ => {}
        }
        out
    }
}

// ---------------------------------------------------------------------------
// Decoder fusion: `Decode.decodeString d s` with a statically known decoder
// becomes straight-line checks inside one try block.

#[derive(Clone)]
pub enum Dec {
    Int,
    Float,
    Str,
    Bool,
    Field(Expr, Box<Dec>),
    List(Box<Dec>),
    Nullable(Box<Dec>),
    Map(Expr, Vec<Dec>),
    Succeed(Expr),
    Fail(Expr),
    OneOf(Vec<Dec>),
}

impl<'a> Lowerer<'a> {
    pub fn static_decoder(&self, e: &Expr) -> Option<Dec> {
        match &e.kind {
            ExprKind::Qual(p, n, _) if p.len() == 1 && p[0] == "Decode" => match n.as_str() {
                "int" => Some(Dec::Int),
                "float" => Some(Dec::Float),
                "string" => Some(Dec::Str),
                "bool" => Some(Dec::Bool),
                _ => None,
            },
            ExprKind::Var(n) => {
                let b = self.lookup(n)?;
                let v = self.value_asts.get(&b.py)?;
                self.static_decoder(&v.clone())
            }
            ExprKind::App(..) => {
                let (f, args) = Lowerer::spine(e);
                let ExprKind::Qual(p, n, _) = &f.kind else { return None };
                if p.len() != 1 || p[0] != "Decode" {
                    return None;
                }
                match (n.as_str(), args.len()) {
                    ("field", 2) => Some(Dec::Field(args[0].clone(), Box::new(self.static_decoder(args[1])?))),
                    ("list", 1) => Some(Dec::List(Box::new(self.static_decoder(args[0])?))),
                    ("nullable", 1) => Some(Dec::Nullable(Box::new(self.static_decoder(args[0])?))),
                    ("map", 2) | ("map2", 3) | ("map3", 4) | ("map4", 5) => {
                        let mut ds = Vec::new();
                        for a in &args[1..] {
                            ds.push(self.static_decoder(a)?);
                        }
                        Some(Dec::Map(args[0].clone(), ds))
                    }
                    ("succeed", 1) => Some(Dec::Succeed(args[0].clone())),
                    ("fail", 1) => Some(Dec::Fail(args[0].clone())),
                    ("oneOf", 1) => match &args[0].kind {
                        ExprKind::List(items) => {
                            let mut ds = Vec::new();
                            for i in items {
                                ds.push(self.static_decoder(i)?);
                            }
                            Some(Dec::OneOf(ds))
                        }
                        _ => None,
                    },
                    _ => None,
                }
            }
            _ => None,
        }
    }

    /// Lower mapper functions first: a lambda goes to a temporary.
    fn dec_mappers(&mut self, d: &Dec, out: &mut HashMap<usize, PE>, counter: &mut usize) {
        match d {
            Dec::Map(f, ds) => {
                let id = *counter;
                *counter += 1;
                let v = self.expr(f);
                let v = match v {
                    PE::Lambda(..) => {
                        let t = self.new_tmp();
                        self.pre.push(PS::Assign(name(&t), v));
                        name(&t)
                    }
                    other => other,
                };
                out.insert(id, v);
                for x in ds {
                    self.dec_mappers(x, out, counter);
                }
            }
            Dec::Field(_, x) | Dec::List(x) | Dec::Nullable(x) => self.dec_mappers(x, out, counter),
            Dec::OneOf(ds) => {
                for x in ds {
                    self.dec_mappers(x, out, counter);
                }
            }
            _ => {}
        }
    }

    pub fn inline_decode(&mut self, d: &Dec, s: &Expr) -> PE {
        self.needs.result = true;
        self.needs.exception = true;
        self.needs.imports.insert("json".into());
        let mut mappers = HashMap::new();
        let mut counter = 0;
        self.dec_mappers(d, &mut mappers, &mut counter);
        let tin = self.new_tmp();
        let saved = std::mem::take(&mut self.pre);
        let sv = self.expr(s);
        let mut body = std::mem::replace(&mut self.pre, saved);
        body.push(PS::Assign(name(&tin), PE::Call(Box::new(attr(name("json"), "loads")), vec![sv], vec![])));
        let mut counter = 0;
        let r = self.dec_gen(d, name(&tin), &mut body, &mappers, &mut counter);
        let tres = self.new_tmp();
        body.push(PS::Assign(name(&tres), call_n("Ok", vec![r])));
        let err = call_n(
            "Error",
            vec![call_n("_Exception", vec![attr(call_n("type", vec![name("e")]), "__name__"), call_n("str", vec![name("e")])])],
        );
        self.pre.push(PS::Try(body, vec![("Exception".into(), Some("e".into()), vec![PS::Assign(name(&tres), err)])]));
        name(&tres)
    }

    fn type_check(&self, v: &PE, cond: PE, msg_expected: &str, out: &mut Vec<PS>) {
        let msg = PE::Bin(
            Box::new(PE::Str(format!("expected {}, got ", msg_expected))),
            Bop::Add,
            Box::new(attr(call_n("type", vec![v.clone()]), "__name__")),
        );
        out.push(PS::If(vec![(PE::Not(Box::new(cond)), vec![PS::Raise(call_n("ValueError", vec![msg]))])], None));
    }

    fn dec_gen(&mut self, d: &Dec, v: PE, out: &mut Vec<PS>, mappers: &HashMap<usize, PE>, counter: &mut usize) -> PE {
        let isinst = |v: &PE, t: PE| call_n("isinstance", vec![v.clone(), t]);
        match d {
            Dec::Int => {
                let c = PE::And(Box::new(isinst(&v, name("int"))), Box::new(PE::Not(Box::new(isinst(&v, name("bool"))))));
                self.type_check(&v, c, "an int", out);
                v
            }
            Dec::Float => {
                let c = PE::And(
                    Box::new(isinst(&v, PE::Tuple(vec![name("int"), name("float")]))),
                    Box::new(PE::Not(Box::new(isinst(&v, name("bool"))))),
                );
                self.type_check(&v, c, "a float", out);
                call_n("float", vec![v])
            }
            Dec::Str => {
                let c = isinst(&v, name("str"));
                self.type_check(&v, c, "a string", out);
                v
            }
            Dec::Bool => {
                let c = isinst(&v, name("bool"));
                self.type_check(&v, c, "a bool", out);
                v
            }
            Dec::Field(k, inner) => {
                out.push(PS::If(
                    vec![(PE::Not(Box::new(isinst(&v, name("dict")))), vec![PS::Raise(call_n("ValueError", vec![PE::Str("expected a JSON object".into())]))])],
                    None,
                ));
                let kv = self.expr(k);
                let t = self.new_tmp();
                out.push(PS::Assign(name(&t), PE::Index(Box::new(v), Box::new(kv))));
                self.dec_gen(inner, name(&t), out, mappers, counter)
            }
            Dec::List(inner) => {
                out.push(PS::If(
                    vec![(PE::Not(Box::new(isinst(&v, name("list")))), vec![PS::Raise(call_n("ValueError", vec![PE::Str("expected a JSON array".into())]))])],
                    None,
                ));
                let acc = self.new_tmp();
                out.push(PS::Assign(name(&acc), PE::List(vec![])));
                let x = self.new_tmp();
                let mut body = Vec::new();
                let r = self.dec_gen(inner, name(&x), &mut body, mappers, counter);
                body.push(PS::Expr(PE::Call(Box::new(attr(name(&acc), "append")), vec![r], vec![])));
                out.push(PS::For(name(&x), v, body));
                name(&acc)
            }
            Dec::Nullable(inner) => {
                self.needs.option = true;
                let t = self.new_tmp();
                let mut els = Vec::new();
                let r = self.dec_gen(inner, v.clone(), &mut els, mappers, counter);
                els.push(PS::Assign(name(&t), call_n("Some", vec![r])));
                out.push(PS::If(vec![(PE::Cmp(Box::new(v), vec![(Cop::Is, PE::NoneV)]), vec![PS::Assign(name(&t), name("_None_"))])], Some(els)));
                name(&t)
            }
            Dec::Map(_, ds) => {
                let id = *counter;
                *counter += 1;
                let f = mappers.get(&id).cloned().unwrap_or(PE::NoneV);
                let mut rs = Vec::new();
                for x in ds {
                    rs.push(self.dec_gen(x, v.clone(), out, mappers, counter));
                }
                PE::Call(Box::new(f), rs, vec![])
            }
            Dec::Succeed(x) => self.expr(x),
            Dec::Fail(m) => {
                let mv = self.expr(m);
                out.push(PS::Raise(call_n("ValueError", vec![mv])));
                PE::NoneV
            }
            Dec::OneOf(ds) => {
                let t = self.new_tmp();
                let mut handler = vec![PS::Raise(call_n("ValueError", vec![PE::Str("Decode.oneOf: no decoder matched".into())]))];
                // build from the last alternative outwards
                let mut bodies = Vec::new();
                for x in ds {
                    let mut b = Vec::new();
                    let r = self.dec_gen(x, v.clone(), &mut b, mappers, counter);
                    b.push(PS::Assign(name(&t), r));
                    bodies.push(b);
                }
                for b in bodies.into_iter().rev() {
                    handler = vec![PS::Try(b, vec![("Exception".into(), None, handler)])];
                }
                out.extend(handler);
                name(&t)
            }
        }
    }
}
