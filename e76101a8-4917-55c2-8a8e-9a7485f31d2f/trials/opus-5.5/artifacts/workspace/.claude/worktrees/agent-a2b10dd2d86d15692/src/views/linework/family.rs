//! What a plan draws of a door or a window of a family: its opening's jambs, the outlines of its
//! forms the plan cuts (their profiles, flipped as the door is), and its plan symbols (lines and
//! arcs), each in the family's terms: across the opening (`x`, from its middle) and through the
//! wall (`y`, from its centre line), their sizes formulas of the family's parameters. And the
//! formulas themselves, and the values a door's, a window's or a component's parameters have.

use super::super::common::*;
use super::plan::Line;
use crate::json::Value;
use crate::project::Project;

// ---------------------------------------------------------------- formulas

#[derive(Debug, Clone, PartialEq)]
enum Tok {
    Num(f64),
    Name(String),
    Op(char),
    /// A comparison: `>`, `<`, `=`, `>=` or `<=`.
    Cmp(&'static str),
}

fn tokens(s: &str) -> Option<Vec<Tok>> {
    let cs: Vec<char> = s.chars().collect();
    let mut i = 0;
    let mut out = Vec::new();
    while i < cs.len() {
        let c = cs[i];
        if c.is_whitespace() {
            i += 1;
        } else if c.is_ascii_digit() || (c == '.' && i + 1 < cs.len() && cs[i + 1].is_ascii_digit()) {
            let st = i;
            while i < cs.len() && (cs[i].is_ascii_digit() || cs[i] == '.') {
                i += 1;
            }
            if i < cs.len() && (cs[i] == 'e' || cs[i] == 'E') {
                let save = i;
                i += 1;
                if i < cs.len() && (cs[i] == '+' || cs[i] == '-') {
                    i += 1;
                }
                if i < cs.len() && cs[i].is_ascii_digit() {
                    while i < cs.len() && cs[i].is_ascii_digit() {
                        i += 1;
                    }
                } else {
                    i = save;
                }
            }
            out.push(Tok::Num(cs[st..i].iter().collect::<String>().parse().ok()?));
        } else if c.is_alphabetic() || c == '_' {
            let st = i;
            while i < cs.len() && (cs[i].is_alphanumeric() || cs[i] == '_' || cs[i] == ' ') {
                i += 1;
            }
            out.push(Tok::Name(cs[st..i].iter().collect::<String>().trim_end().to_string()));
        } else if c == '>' || c == '<' {
            if i + 1 < cs.len() && cs[i + 1] == '=' {
                out.push(Tok::Cmp(if c == '>' { ">=" } else { "<=" }));
                i += 2;
            } else {
                out.push(Tok::Cmp(if c == '>' { ">" } else { "<" }));
                i += 1;
            }
        } else if c == '=' {
            out.push(Tok::Cmp("="));
            i += 1;
        } else if "+-*/^(),".contains(c) {
            out.push(Tok::Op(c));
            i += 1;
        } else {
            return None;
        }
    }
    Some(out)
}

struct Parser<'a> {
    t: Vec<Tok>,
    i: usize,
    vars: &'a dyn Fn(&str) -> Option<f64>,
}

impl Parser<'_> {
    fn peek(&self) -> Option<&Tok> {
        self.t.get(self.i)
    }
    /// A formula: a sum, or two compared (1 or 0).
    fn formula(&mut self) -> Option<f64> {
        let a = self.sum()?;
        if let Some(Tok::Cmp(c)) = self.peek().cloned() {
            self.i += 1;
            let b = self.sum()?;
            let r = match c {
                ">" => a > b,
                "<" => a < b,
                ">=" => a >= b,
                "<=" => a <= b,
                _ => a == b,
            };
            return Some(if r { 1.0 } else { 0.0 });
        }
        Some(a)
    }
    fn sum(&mut self) -> Option<f64> {
        let mut v = self.term()?;
        while let Some(Tok::Op(c @ ('+' | '-'))) = self.peek().cloned() {
            self.i += 1;
            let r = self.term()?;
            v = if c == '+' { v + r } else { v - r };
        }
        Some(v)
    }
    fn term(&mut self) -> Option<f64> {
        let mut v = self.power()?;
        while let Some(Tok::Op(c @ ('*' | '/'))) = self.peek().cloned() {
            self.i += 1;
            let r = self.power()?;
            v = if c == '*' { v * r } else { v / r };
        }
        Some(v)
    }
    /// A power, to the right first (`2^3^2` is 2^9), of a signed value (`-2^2` is 4).
    fn power(&mut self) -> Option<f64> {
        let b = self.unary()?;
        if self.peek() == Some(&Tok::Op('^')) {
            self.i += 1;
            let e = self.power()?;
            return Some(b.powf(e));
        }
        Some(b)
    }
    fn unary(&mut self) -> Option<f64> {
        match self.peek().cloned()? {
            Tok::Op('-') => {
                self.i += 1;
                Some(-self.unary()?)
            }
            Tok::Op('+') => {
                self.i += 1;
                self.unary()
            }
            _ => self.atom(),
        }
    }
    fn atom(&mut self) -> Option<f64> {
        match self.peek().cloned()? {
            Tok::Op('(') => {
                self.i += 1;
                let v = self.formula()?;
                if self.peek() != Some(&Tok::Op(')')) {
                    return None;
                }
                self.i += 1;
                Some(v)
            }
            Tok::Num(n) => {
                self.i += 1;
                Some(n)
            }
            Tok::Name(n) => {
                self.i += 1;
                if self.peek() == Some(&Tok::Op('(')) {
                    self.i += 1;
                    let mut args = Vec::new();
                    if self.peek() != Some(&Tok::Op(')')) {
                        loop {
                            args.push(self.formula()?);
                            match self.peek() {
                                Some(Tok::Op(',')) => self.i += 1,
                                _ => break,
                            }
                        }
                    }
                    if self.peek() != Some(&Tok::Op(')')) {
                        return None;
                    }
                    self.i += 1;
                    return call(&n.to_lowercase(), &args);
                }
                (self.vars)(&n)
            }
            _ => None,
        }
    }
}

/// A function of a formula: angles in degrees, conditions true when not 0.
fn call(f: &str, a: &[f64]) -> Option<f64> {
    let truth = |b: bool| if b { 1.0 } else { 0.0 };
    Some(match (f, a.len()) {
        ("if", 3) => {
            if a[0] != 0.0 {
                a[1]
            } else {
                a[2]
            }
        }
        ("and", n) if n >= 1 => truth(a.iter().all(|x| *x != 0.0)),
        ("or", n) if n >= 1 => truth(a.iter().any(|x| *x != 0.0)),
        ("not", 1) => truth(a[0] == 0.0),
        ("min", n) if n >= 1 => a.iter().cloned().fold(f64::INFINITY, f64::min),
        ("max", n) if n >= 1 => a.iter().cloned().fold(f64::NEG_INFINITY, f64::max),
        ("abs", 1) => a[0].abs(),
        ("sqrt", 1) => a[0].sqrt(),
        ("round", 1) => a[0].round(),
        ("roundup", 1) => a[0].ceil(),
        ("rounddown", 1) => a[0].floor(),
        ("sin", 1) => a[0].to_radians().sin(),
        ("cos", 1) => a[0].to_radians().cos(),
        ("tan", 1) => a[0].to_radians().tan(),
        ("asin", 1) => a[0].asin().to_degrees(),
        ("acos", 1) => a[0].acos().to_degrees(),
        ("atan", 1) => a[0].atan().to_degrees(),
        ("log", 1) => a[0].log10(),
        ("ln", 1) => a[0].ln(),
        ("exp", 1) => a[0].exp(),
        ("pi", 0) => std::f64::consts::PI,
        _ => return None,
    })
}

/// A formula's value, its names the family's parameters: a number, or a formula's text.
pub fn eval(v: &Value, vars: &dyn Fn(&str) -> Option<f64>) -> Option<f64> {
    match v {
        Value::Num(n) => Some(n.as_f64()),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        Value::Str(s) => {
            let t = tokens(s)?;
            let mut p = Parser { t, i: 0, vars };
            let x = p.formula()?;
            if p.i != p.t.len() || !x.is_finite() {
                return None;
            }
            Some(x)
        }
        _ => None,
    }
}

// ---------------------------------------------------------------- the family's values

/// What a door's, a window's or a component's family is, and the values its parameters have
/// for it: its own (an instance parameter's, keyed in the element by the parameter's GUID), its
/// type's, else the family's, a parameter with a formula worked out from the others; a hosted
/// family's `Wall Thickness` its wall's.
pub struct Values<'a> {
    pr: &'a Project,
    e: &'a Value,
    pub fam: Value,
    fam_name: String,
    type_name: String,
    wall_t: Option<f64>,
    depth: std::cell::Cell<usize>,
}

impl<'a> Values<'a> {
    pub fn of(pr: &'a Project, e: &'a Value, wall_t: Option<f64>) -> Option<Values<'a>> {
        let fam_name = lib_ref_name(pr, e, "family")?;
        let fam = pr.section("families")?.get(&fam_name)?.clone();
        let type_name = super::super::tags::fields::type_name(pr, e).unwrap_or_default();
        Some(Values { pr, e, fam, fam_name, type_name, wall_t, depth: std::cell::Cell::new(0) })
    }

    /// A parameter's value as a number (yes 1, no 0).
    pub fn get(&self, name: &str) -> Option<f64> {
        if name == "Wall Thickness" {
            if let Some(t) = self.wall_t {
                return Some(t);
            }
        }
        let def = self.fam.get("parameters")?.as_arr()?.iter().find(|p| s_of(p, "name") == Some(name))?;
        if let Some(f) = def.get("formula").filter(|f| !f.is_null()) {
            if self.depth.get() > 64 {
                return None;
            }
            self.depth.set(self.depth.get() + 1);
            let v = eval(f, &|n| self.get(n));
            self.depth.set(self.depth.get() - 1);
            return v;
        }
        let own = self.e.get("params").and_then(|m| {
            let g = self.pr.lib_guid("family-parameter", &format!("{}: {}", self.fam_name, name));
            g.and_then(|g| m.get(&g).cloned()).or_else(|| m.get(name).cloned())
        });
        let v = own
            .filter(|v| !v.is_null())
            .or_else(|| self.fam.get("types").and_then(|t| t.get(&self.type_name)).and_then(|t| t.get(name)).cloned())
            .filter(|v| !v.is_null())
            .or_else(|| def.get("value").cloned())?;
        match v {
            Value::Num(n) => Some(n.as_f64()),
            Value::Bool(b) => Some(if b { 1.0 } else { 0.0 }),
            Value::Str(_) => eval(&v, &|n| self.get(n)),
            _ => None,
        }
    }

    /// A formula's value for it.
    pub fn eval(&self, v: &Value) -> Option<f64> {
        eval(v, &|n| self.get(n))
    }

    /// Whether a form or a symbol is there: its `visible`, a yes/no parameter or a formula, not 0.
    pub fn shows(&self, part: &Value) -> bool {
        match part.get("visible") {
            None | Some(Value::Null) => true,
            Some(v) => self.eval(v).map(|x| x != 0.0).unwrap_or(false),
        }
    }

    /// A point of a profile or a symbol, worked out.
    pub fn point(&self, q: &Value) -> Option<[f64; 2]> {
        let q = q.as_arr()?;
        Some([self.eval(q.first()?)?, self.eval(q.get(1)?)?])
    }
}

/// How many degrees a chord of a symbol's arc turns (a quarter turn in 24).
pub const ARC_STEP: f64 = 3.75;

/// The points of a symbol's arc, in the family's terms: from `from` to `to` degrees (a whole
/// turn without them), in chords of at most `ARC_STEP` degrees.
pub fn symbol_arc(vals: &Values, a: &Value) -> Option<Vec<[f64; 2]>> {
    let c = a.get("centre")?.as_arr()?;
    let (cx, cy) = (vals.eval(c.first()?)?, vals.eval(c.get(1)?)?);
    let r = vals.eval(a.get("radius")?)?;
    let from = a.get("from").and_then(|x| vals.eval(x)).unwrap_or(0.0);
    let to = a.get("to").and_then(|x| vals.eval(x)).unwrap_or(360.0);
    let sweep = to - from;
    let n = ((sweep.abs() / ARC_STEP) - 1e-9).ceil().max(1.0) as usize;
    Some(
        (0..=n)
            .map(|k| {
                let t = (from + sweep * k as f64 / n as f64).to_radians();
                [cx + r * t.cos(), cy + r * t.sin()]
            })
            .collect(),
    )
}

/// The lines a plan draws of a door or a window of a family, cut `z` mm over its sill: `place`
/// maps the family's (x, y) to plan mm, `jambs` the opening's own.
pub fn family_opening_lines(
    pr: &Project,
    e: &Value,
    wall_t: f64,
    z: f64,
    place: &dyn Fn(f64, f64) -> [f64; 2],
    jamb: &dyn Fn(f64) -> Vec<Line>,
    mirrored: bool,
) -> Option<Vec<Line>> {
    let vals = Values::of(pr, e, Some(wall_t))?;
    let width = vals.get("Width")?;
    let mut out = Vec::new();
    out.extend(jamb(width));
    if let Some(forms) = vals.fam.get("forms").and_then(|f| f.as_arr()) {
        for f in forms {
            if f.get("void").and_then(|v| v.as_bool()) == Some(true) {
                continue;
            }
            if s_of(f, "plane").unwrap_or("xy") != "xy" {
                continue;
            }
            if !vals.shows(f) {
                continue;
            }
            let from = f.get("from").and_then(|x| vals.eval(x)).unwrap_or(0.0);
            let to = match f.get("to").and_then(|x| vals.eval(x)) {
                Some(t) => t,
                None => continue,
            };
            if !(from <= z && z < to) {
                continue;
            }
            let Some(profile) = f.get("profile").and_then(|p| p.as_arr()) else { continue };
            let pts: Option<Vec<[f64; 2]>> = profile.iter().map(|q| vals.point(q).map(|p| place(p[0], p[1]))).collect();
            if let Some(mut pts) = pts {
                if pts.len() >= 2 {
                    // mirrored, a profile is taken the other way round so it keeps its turn
                    if mirrored {
                        pts.reverse();
                    }
                    out.push(Line::ring(pts));
                }
            }
        }
    }
    if let Some(symbols) = vals.fam.get("symbols").and_then(|s| s.as_arr()) {
        for s in symbols {
            if !vals.shows(s) {
                continue;
            }
            if let Some(l) = s.get("line").and_then(|l| l.as_arr()) {
                let pts: Option<Vec<[f64; 2]>> = l.iter().map(|q| vals.point(q).map(|p| place(p[0], p[1]))).collect();
                if let Some(pts) = pts {
                    if pts.len() >= 2 {
                        out.push(Line::open(pts));
                    }
                }
            } else if let Some(a) = s.get("arc") {
                if let Some(pts) = symbol_arc(&vals, a) {
                    out.push(Line::open(pts.into_iter().map(|p| place(p[0], p[1])).collect()));
                }
            }
        }
    }
    Some(out)
}
