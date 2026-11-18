// Compile-time expression evaluation: bindings, functions, math.

use crate::ast::{Expr, Term};
use crate::diag::{Diag, Span};
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub enum EV {
    Num(f64),
    Tuple(Vec<EV>),
    Str(String),
}

impl EV {
    pub fn num(&self) -> Option<f64> {
        match self {
            EV::Num(v) => Some(*v),
            _ => None,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Func {
    pub params: Vec<String>,
    pub body: Term,
}

#[derive(Default, Clone, Debug)]
pub struct Env {
    pub vars: HashMap<String, EV>,
    pub funcs: HashMap<String, Func>,
}

pub fn err(msg: &str, span: Span) -> Diag {
    Diag::error("resolve", msg, span)
}

impl Env {
    pub fn eval_term(&self, t: &Term, locals: &HashMap<String, EV>) -> Result<EV, Diag> {
        match t {
            Term::Num(v, _, _) => Ok(EV::Num(*v)),
            Term::Group(e, _) => self.eval(e, locals),
            Term::Call(name, args, sp) => self.call(name, args, locals, *sp),
            Term::Ident(n, sp) => self.lookup(n, locals, *sp),
            Term::Str(s, _) => Ok(EV::Str(s.clone())),
            _ => Err(err("expected a number", t.span())),
        }
    }

    fn lookup(&self, n: &str, locals: &HashMap<String, EV>, sp: Span) -> Result<EV, Diag> {
        if let Some(v) = locals.get(n) {
            return Ok(v.clone());
        }
        if let Some(v) = self.vars.get(n) {
            return Ok(v.clone());
        }
        match n {
            "pi" => Ok(EV::Num(std::f64::consts::PI)),
            "e" => Ok(EV::Num(std::f64::consts::E)),
            _ => Err(err(&format!("unknown name '{}' in an expression", n), sp)),
        }
    }

    pub fn eval(&self, e: &Expr, locals: &HashMap<String, EV>) -> Result<EV, Diag> {
        match e {
            Expr::Num(v, _) => Ok(EV::Num(*v)),
            Expr::Percent(v, _) => Ok(EV::Num(*v / 100.0)),
            Expr::Str(s, _) => Ok(EV::Str(s.clone())),
            Expr::Ident(n, sp) => self.lookup(n, locals, *sp),
            Expr::Var(_, sp) | Expr::Hash(_, sp) => Err(err("expected a number", *sp)),
            Expr::Call(name, args, sp) => self.call(name, args, locals, *sp),
            Expr::Unary(op, a, sp) => {
                let v = self.eval(a, locals)?;
                let x = v.num().ok_or_else(|| err("expected a number", *sp))?;
                Ok(EV::Num(match op.as_str() {
                    "-" => -x,
                    "!" => {
                        if x == 0.0 {
                            1.0
                        } else {
                            0.0
                        }
                    }
                    _ => x,
                }))
            }
            Expr::Bin(op, a, b, sp) => {
                let x = self.eval(a, locals)?.num().ok_or_else(|| err("expected a number", *sp))?;
                if op == "&&" {
                    if x == 0.0 {
                        return Ok(EV::Num(0.0));
                    }
                    let y = self.eval(b, locals)?.num().ok_or_else(|| err("expected a number", *sp))?;
                    return Ok(EV::Num(if y != 0.0 { 1.0 } else { 0.0 }));
                }
                if op == "||" {
                    if x != 0.0 {
                        return Ok(EV::Num(1.0));
                    }
                    let y = self.eval(b, locals)?.num().ok_or_else(|| err("expected a number", *sp))?;
                    return Ok(EV::Num(if y != 0.0 { 1.0 } else { 0.0 }));
                }
                let y = self.eval(b, locals)?.num().ok_or_else(|| err("expected a number", *sp))?;
                let b2 = |c: bool| if c { 1.0 } else { 0.0 };
                Ok(EV::Num(match op.as_str() {
                    "+" => x + y,
                    "-" => x - y,
                    "*" => x * y,
                    "/" => x / y,
                    "^" => x.powf(y),
                    "<" => b2(x < y),
                    ">" => b2(x > y),
                    "<=" => b2(x <= y),
                    ">=" => b2(x >= y),
                    "==" => b2(x == y),
                    "!=" => b2(x != y),
                    _ => return Err(err("unknown operator", *sp)),
                }))
            }
            Expr::Ternary(c, a, b, sp) => {
                let cv = self.eval(c, locals)?.num().ok_or_else(|| err("expected a number", *sp))?;
                if cv != 0.0 {
                    self.eval(a, locals)
                } else {
                    self.eval(b, locals)
                }
            }
            Expr::Tuple(items, _) => {
                let mut out = Vec::new();
                for it in items {
                    out.push(self.eval(it, locals)?);
                }
                Ok(EV::Tuple(out))
            }
            Expr::Block(binds, body, _) => {
                let mut l2 = locals.clone();
                for (n, ex) in binds {
                    let v = self.eval(ex, &l2)?;
                    l2.insert(n.clone(), v);
                }
                self.eval(body, &l2)
            }
        }
    }

    fn call(&self, name: &str, args: &[Expr], locals: &HashMap<String, EV>, sp: Span) -> Result<EV, Diag> {
        if let Some(f) = self.funcs.get(name) {
            let mut l2 = locals.clone();
            for (i, p) in f.params.iter().enumerate() {
                let v = match args.get(i) {
                    Some(a) => self.eval(a, locals)?,
                    None => EV::Num(0.0),
                };
                l2.insert(p.clone(), v);
            }
            return self.eval_term(&f.body, &l2);
        }
        let mut xs = Vec::new();
        for a in args {
            match self.eval(a, locals)? {
                EV::Num(v) => xs.push(v),
                _ => return Err(err("expected a number", a.span())),
            }
        }
        let a = |i: usize| xs.get(i).copied().unwrap_or(0.0);
        let v = match name {
            "sin" => a(0).sin(),
            "cos" => a(0).cos(),
            "tan" => a(0).tan(),
            "sqrt" => a(0).sqrt(),
            "abs" => a(0).abs(),
            "exp" => a(0).exp(),
            "ln" => a(0).ln(),
            "log" => a(0).log10(),
            "floor" => a(0).floor(),
            "round" => a(0).round(),
            "pow" => a(0).powf(a(1)),
            "min" => xs.iter().cloned().fold(f64::INFINITY, f64::min),
            "max" => xs.iter().cloned().fold(f64::NEG_INFINITY, f64::max),
            "clamp" => a(0).max(a(1)).min(a(2)),
            _ => return Err(err(&format!("unknown function '{}'", name), sp)),
        };
        Ok(EV::Num(v))
    }
}
