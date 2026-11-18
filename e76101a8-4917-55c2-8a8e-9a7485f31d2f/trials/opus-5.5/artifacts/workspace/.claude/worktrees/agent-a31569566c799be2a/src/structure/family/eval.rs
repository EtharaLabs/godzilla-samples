//! Working a family out for one of its types (and a component's own values): each parameter's
//! value, a formula reading others through theirs, and a form's or a symbol's sizes.

use super::model::*;
use crate::json::{Map, Value};
use crate::structure::formula::{self, ParseError};

/// The most formulas in a row that read one another.
pub const MAX_CHAIN: usize = 16;

/// The largest number a size may come to (mm).
pub const MAX_COORD: f64 = 1e9;

/// The wall thickness a door's or a window's family is worked out in when it stands in none.
pub const DEFAULT_WALL: f64 = 200.0;

/// The name a hosted family's formulas read its wall's thickness by.
pub const WALL_THICKNESS: &str = "Wall Thickness";

/// A parameter's value worked out: a number (a yes as 1, a no as 0), or a material's name.
#[derive(Clone, Debug, PartialEq)]
pub enum PVal {
    Num(f64),
    Mat(String),
}

impl PVal {
    pub fn value(&self) -> Value {
        match self {
            PVal::Num(x) => Value::f(*x),
            PVal::Mat(s) => Value::s(s),
        }
    }
    pub fn num(&self) -> f64 {
        match self {
            PVal::Num(x) => *x,
            PVal::Mat(_) => 0.0,
        }
    }
}

/// A number as the original says it in its messages (Rust's `{}` of an f64).
pub fn disp(x: f64) -> String {
    format!("{}", x)
}

/// A family worked out for one type: the values its type gives (and a component's over them).
pub struct Eval<'a> {
    pub fam: &'a Family,
    /// What's given: the type's values, a component's instance values over them, by name.
    pub given: Map,
    /// A hosted family's wall thickness.
    pub wall: Option<f64>,
}

impl<'a> Eval<'a> {
    /// For a type (by name; none gives the parameters' own values), with a component's values
    /// over its instance parameters, and a hosted family's wall thickness (200 when none).
    pub fn new(fam: &'a Family, type_name: Option<&str>, instance: Option<&Map>, wall: Option<f64>) -> Eval<'a> {
        // a type's value is its parameter's (the first of that name), an instance parameter's
        // the component's
        let mut given = Map::new();
        if let Some(t) = type_name.and_then(|n| fam.type_values(n)) {
            for (k, v) in t.iter() {
                if !v.is_null() && fam.param(k).map(|p| !p.instance).unwrap_or(true) {
                    given.insert(k, v.clone());
                }
            }
        }
        if let Some(inst) = instance {
            for (k, v) in inst.iter() {
                if v.is_null() {
                    continue;
                }
                if fam.param(k).map(|p| p.instance).unwrap_or(false) {
                    given.insert(k, v.clone());
                }
            }
        }
        let wall = if fam.hosted() { Some(wall.unwrap_or(DEFAULT_WALL)) } else { None };
        Eval { fam, given, wall }
    }

    /// What's given a parameter: the first of its name takes it.
    fn given_for(&self, p: &Param) -> Option<&Value> {
        let first = self.fam.param(&p.name).map(|q| std::ptr::eq(q, p)).unwrap_or(false);
        if first {
            self.given.get(&p.name)
        } else {
            None
        }
    }

    /// A parameter's plain value (no formula): what's given, else its own; a material's name.
    fn plain(&self, p: &Param) -> PVal {
        let v = self.given_for(p).unwrap_or(&p.value);
        match p.kind {
            Kind::Material => PVal::Mat(v.as_str().unwrap_or("").to_string()),
            // a yes/no holds yes (1) for any number but 0
            Kind::YesNo => PVal::Num(match v {
                Value::Num(n) if n.as_f64() != 0.0 => 1.0,
                Value::Bool(true) => 1.0,
                _ => 0.0,
            }),
            _ => PVal::Num(match v {
                Value::Num(n) => n.as_f64(),
                Value::Bool(b) => {
                    if *b {
                        1.0
                    } else {
                        0.0
                    }
                }
                _ => 0.0,
            }),
        }
    }

    /// A parameter's plain value as `values` takes it: refused where it isn't of its kind.
    fn plain_strict(&self, p: &Param) -> Result<PVal, String> {
        let v = self.given_for(p).unwrap_or(&p.value);
        let fits = match (p.kind, v) {
            (_, Value::Null) => true,
            (Kind::Material, Value::Str(_)) => true,
            (Kind::YesNo, Value::Bool(_) | Value::Num(_)) => true,
            (Kind::Length | Kind::Number | Kind::Angle, Value::Num(_)) => true,
            _ => false,
        };
        if !fits {
            let holds = match p.kind {
                Kind::YesNo => "yes or no",
                Kind::Material => "a material's name",
                _ => "a number",
            };
            return Err(format!("parameter `{}` holds {}, not {}", p.name, holds, v.to_compact()));
        }
        Ok(self.plain(p))
    }

    /// A name as a formula reads it, with the formulas being worked out (`stack`, by place).
    fn read(&self, name: &str, stack: &mut Vec<usize>) -> Result<f64, String> {
        if let Some(w) = self.wall {
            if name == WALL_THICKNESS {
                return Ok(w);
            }
        }
        let Some(i) = self.fam.parameters.iter().position(|p| p.name == name) else {
            return Err(format!("`{}` isn't one of its parameters", name));
        };
        let p = &self.fam.parameters[i];
        if p.kind == Kind::Material {
            return Err(format!("`{}` is a material, not a number", name));
        }
        match &p.formula {
            None => Ok(self.plain(p).num()),
            Some(f) => {
                if stack.contains(&i) {
                    return Err(format!("`{}`'s formula comes back to itself", name));
                }
                if stack.len() >= MAX_CHAIN {
                    return Err(format!(
                        "`{}` takes from formulas taking from more than {} others in a row: nested too deep",
                        name, MAX_CHAIN
                    ));
                }
                stack.push(i);
                let r = self.formula(f, stack);
                stack.pop();
                r.map_err(|e| format!("parameter `{}`: {}", name, e))
            }
        }
    }

    /// A formula's text worked out: "formula `…`: why" when it can't be.
    fn formula(&self, text: &str, stack: &mut Vec<usize>) -> Result<f64, String> {
        let f = match formula::parse(text) {
            Ok(f) => f,
            Err(ParseError::Empty) => return Err("a formula is empty".into()),
            Err(ParseError::Syntax(m)) => return Err(format!("formula `{}`: {}", text, m)),
        };
        f.eval(&mut |n: &str| self.read(n, stack)).map_err(|e| format!("formula `{}`: {}", text, e))
    }

    fn param_at(&self, i: usize, strict: bool) -> Result<PVal, String> {
        let p = &self.fam.parameters[i];
        match (&p.formula, p.kind) {
            (Some(f), k) if k != Kind::Material => {
                let mut stack = vec![i];
                let v = self.formula(f, &mut stack).map_err(|e| format!("parameter `{}`: {}", p.name, e))?;
                Ok(PVal::Num(v))
            }
            _ if strict => self.plain_strict(p),
            _ => Ok(self.plain(p)),
        }
    }

    /// A parameter's value worked out (its formula, if it has one), as `values` shows it.
    pub fn param(&self, p: &Param) -> Result<PVal, String> {
        match self.fam.parameters.iter().position(|q| std::ptr::eq(q, p)).or_else(|| self.fam.parameters.iter().position(|q| q.name == p.name)) {
            Some(i) => self.param_at(i, false),
            None => Ok(self.plain(p)),
        }
    }

    /// A parameter's value by name (a hosted family's `Wall Thickness` too).
    pub fn value_of(&self, name: &str) -> Option<Result<PVal, String>> {
        if let Some(w) = self.wall {
            if name == WALL_THICKNESS {
                return Some(Ok(PVal::Num(w)));
            }
        }
        self.fam.parameters.iter().position(|p| p.name == name).map(|i| self.param_at(i, false))
    }

    /// Every parameter's value, in their order (and a hosted family's `Wall Thickness` last);
    /// refused where a value isn't of its parameter's kind or a formula can't be worked out.
    pub fn values(&self) -> Result<Vec<(String, PVal)>, String> {
        let mut out: Vec<(String, PVal)> = Vec::with_capacity(self.fam.parameters.len() + 1);
        for (i, p) in self.fam.parameters.iter().enumerate() {
            // a name is the first parameter's of it
            if out.iter().any(|(n, _)| *n == p.name) {
                continue;
            }
            out.push((p.name.clone(), self.param_at(i, true)?));
        }
        if let Some(w) = self.wall {
            out.push((WALL_THICKNESS.to_string(), PVal::Num(w)));
        }
        Ok(out)
    }

    /// A size: a number as it is, a formula worked out ("formula `…`: why").
    pub fn expr(&self, e: &Expr) -> Result<f64, String> {
        match e {
            Expr::Num(x) => Ok(*x),
            Expr::Text(s) => self.formula(s, &mut Vec::new()),
        }
    }

    /// A size that must be usable: finite and within 1000 km.
    pub fn usable(&self, e: &Expr) -> Result<f64, String> {
        let x = self.expr(e)?;
        if !(x.is_finite() && x.abs() <= MAX_COORD) {
            return Err(format!("{} is not a usable number", disp(x)));
        }
        Ok(x)
    }

    pub fn point(&self, p: &Pt) -> Result<[f64; 2], String> {
        Ok([self.usable(&p[0])?, self.usable(&p[1])?])
    }

    /// Whether a part is there: its `visible` worked out, not zero (none, it is).
    pub fn visible(&self, v: &Option<Expr>) -> Result<bool, String> {
        match v {
            None => Ok(true),
            Some(e) => Ok(self.usable(e)? != 0.0),
        }
    }
}

/// A family's values for a type as `family` and `elements` show them: {name: number or
/// material name}, a hosted family's `Wall Thickness` among them.
pub fn values_view(vals: &[(String, PVal)]) -> Value {
    let mut m = Map::new();
    for (k, v) in vals {
        m.insert_sorted(k, v.value());
    }
    Value::Obj(m)
}
