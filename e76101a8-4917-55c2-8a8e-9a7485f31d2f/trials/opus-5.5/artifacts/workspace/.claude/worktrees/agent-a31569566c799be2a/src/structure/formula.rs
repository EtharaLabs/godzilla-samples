//! The family formula engine: `Width / 2`, `if(Depth > 600, 4, 2)`, + - * / ^, comparisons,
//! if/and/or/not/min/max/abs/sqrt/round/roundup/rounddown/sin/cos/tan (degrees), asin, acos,
//! atan, exp, ln, log and pi(), as the original reads and works them out, with its very words.
//!
//! A formula is parsed once ([`parse`]); [`Formula::check_calls`] says what a family's definition
//! refuses of its functions (an unknown one, a wrong count of values), [`Formula::names`] lists the
//! parameters it reads (in the order they first appear), and [`Formula::eval`] works it out with a
//! lookup of the values it reads. A family's formulas are read twice by the original: once over
//! its definition (`check_calls`, then each name it reads that the family lacks, every formula of
//! it in turn), once for each type (`eval`), lazily: `if` works out only the branch it takes, and
//! a function's name and its count of values are refused only where it is worked out.
//!
//! The grammar, loosest first: a comparison (`<`, `>`, `=`, `<=`, `>=`, at most one; `=` within
//! a billionth), `+` `-`, `*` `/`, `^` (to the right: `2^3^2` is 512), a sign (`-2^2` is 4), and a
//! value: a number (`1.5e3`, `.5`, `5.`), a parameter's name (letters, digits, `_` and spaces,
//! starting with a letter or `_`: `Leg Width`), a function's call (`sqrt (4)`, any case) or a
//! bracketed formula. Each bracket, call, sign and power's exponent nests a level, 64 at most.
//! Angles are in degrees, both ways. A formula comes to a finite number or is refused.

/// The most characters a family's formula has.
pub const MAX_LEN: usize = 1024;

/// The most levels a formula nests.
pub const MAX_DEPTH: usize = 64;

/// The functions there are, as the original lists them.
pub const FUNCTIONS: &str =
    "if, and, or, not, min, max, abs, sqrt, round, roundup, rounddown, sin, cos, tan, asin, acos, atan, exp, ln, log and pi()";

/// An operator between two values.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Op {
    Add,
    Sub,
    Mul,
    Div,
    Pow,
    Lt,
    Gt,
    Eq,
    Le,
    Ge,
}

/// A formula's tree.
#[derive(Clone, Debug, PartialEq)]
pub enum Node {
    Num(f64),
    /// A parameter's name, as written (trailing spaces left out).
    Name(String),
    Neg(Box<Node>),
    Bin(Op, Box<Node>, Box<Node>),
    /// A function's call: its name as written, its values.
    Call(String, Vec<Node>),
}

/// A formula, parsed.
#[derive(Clone, Debug, PartialEq)]
pub struct Formula {
    /// As written.
    pub text: String,
    pub root: Node,
}

/// What reading a formula's text refuses.
#[derive(Clone, Debug, PartialEq)]
pub enum ParseError {
    /// Nothing but spaces: "a formula is empty".
    Empty,
    /// What's wrong and where (the character it stops at, from 1).
    Syntax(String),
}

impl ParseError {
    /// The words the original says it in (for `Syntax`, with the character).
    pub fn message(&self) -> String {
        match self {
            ParseError::Empty => "a formula is empty".to_string(),
            ParseError::Syntax(s) => s.clone(),
        }
    }
}

/// Reads a formula: its syntax only (functions and names are what `check_calls`, `names` and
/// `eval` look at).
pub fn parse(text: &str) -> Result<Formula, ParseError> {
    if text.trim().is_empty() {
        return Err(ParseError::Empty);
    }
    let mut p = Parser { s: text.chars().collect(), pos: 0 };
    let root = p.expr(1).map_err(ParseError::Syntax)?;
    p.ws();
    if let Some(c) = p.peek() {
        return Err(ParseError::Syntax(format!("`{}` follows where it should end (character {})", c, p.pos + 1)));
    }
    Ok(Formula { text: text.to_string(), root })
}

struct Parser {
    s: Vec<char>,
    pos: usize,
}

impl Parser {
    fn peek(&self) -> Option<char> {
        self.s.get(self.pos).copied()
    }
    fn ws(&mut self) {
        while let Some(c) = self.peek() {
            if c.is_whitespace() {
                self.pos += 1;
            } else {
                break;
            }
        }
    }
    fn at(&self) -> String {
        format!("(character {})", self.pos + 1)
    }

    fn expr(&mut self, depth: usize) -> Result<Node, String> {
        let left = self.additive(depth)?;
        self.ws();
        let op = match self.peek() {
            Some('<') => Op::Lt,
            Some('>') => Op::Gt,
            Some('=') => Op::Eq,
            _ => return Ok(left),
        };
        self.pos += 1;
        let op = if op == Op::Eq {
            op
        } else {
            self.ws();
            if self.peek() == Some('=') {
                self.pos += 1;
                if op == Op::Lt {
                    Op::Le
                } else {
                    Op::Ge
                }
            } else {
                op
            }
        };
        let right = self.additive(depth)?;
        Ok(Node::Bin(op, Box::new(left), Box::new(right)))
    }

    fn additive(&mut self, depth: usize) -> Result<Node, String> {
        let mut left = self.term(depth)?;
        loop {
            self.ws();
            let op = match self.peek() {
                Some('+') => Op::Add,
                Some('-') => Op::Sub,
                _ => return Ok(left),
            };
            self.pos += 1;
            let right = self.term(depth)?;
            left = Node::Bin(op, Box::new(left), Box::new(right));
        }
    }

    fn term(&mut self, depth: usize) -> Result<Node, String> {
        let mut left = self.power(depth)?;
        loop {
            self.ws();
            let op = match self.peek() {
                Some('*') => Op::Mul,
                Some('/') => Op::Div,
                _ => return Ok(left),
            };
            self.pos += 1;
            let right = self.power(depth)?;
            left = Node::Bin(op, Box::new(left), Box::new(right));
        }
    }

    fn power(&mut self, depth: usize) -> Result<Node, String> {
        let base = self.unary(depth)?;
        self.ws();
        if self.peek() == Some('^') {
            self.pos += 1;
            let exp = self.power(depth + 1)?;
            return Ok(Node::Bin(Op::Pow, Box::new(base), Box::new(exp)));
        }
        Ok(base)
    }

    fn unary(&mut self, depth: usize) -> Result<Node, String> {
        self.ws();
        if depth > MAX_DEPTH {
            return Err(format!("it's nested too deep (more than {} levels) {}", MAX_DEPTH, self.at()));
        }
        match self.peek() {
            None => Err(format!("something's missing at its end {}", self.at())),
            Some('-') => {
                self.pos += 1;
                let inner = self.unary(depth + 1)?;
                Ok(Node::Neg(Box::new(inner)))
            }
            Some('+') => {
                self.pos += 1;
                self.unary(depth + 1)
            }
            Some(_) => self.primary(depth),
        }
    }

    fn primary(&mut self, depth: usize) -> Result<Node, String> {
        let c = self.peek().unwrap();
        if c.is_ascii_digit() || c == '.' {
            return self.number();
        }
        if c.is_alphabetic() || c == '_' {
            let start = self.pos;
            while let Some(c) = self.peek() {
                if c.is_alphanumeric() || c == '_' || c == ' ' {
                    self.pos += 1;
                } else {
                    break;
                }
            }
            let name: String = self.s[start..self.pos].iter().collect::<String>().trim_end_matches(' ').to_string();
            self.ws();
            if self.peek() != Some('(') {
                return Ok(Node::Name(name));
            }
            self.pos += 1;
            let mut args = Vec::new();
            self.ws();
            if self.peek() == Some(')') {
                self.pos += 1;
                return Ok(Node::Call(name, args));
            }
            loop {
                args.push(self.expr(depth + 1)?);
                self.ws();
                match self.peek() {
                    Some(',') => self.pos += 1,
                    Some(')') => {
                        self.pos += 1;
                        return Ok(Node::Call(name, args));
                    }
                    _ => return Err(format!("`{}(` needs a `,` or a `)` {}", name, self.at())),
                }
            }
        }
        if c == '(' {
            self.pos += 1;
            let e = self.expr(depth + 1)?;
            self.ws();
            if self.peek() == Some(')') {
                self.pos += 1;
                return Ok(e);
            }
            return Err(format!("a `(` isn't closed {}", self.at()));
        }
        Err(format!("`{}` can't start a value there {}", c, self.at()))
    }

    fn number(&mut self) -> Result<Node, String> {
        let start = self.pos;
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || c == '.' {
                self.pos += 1;
            } else {
                break;
            }
        }
        if matches!(self.peek(), Some('e') | Some('E')) {
            let d = |i: usize| self.s.get(i).map(|c| c.is_ascii_digit()).unwrap_or(false);
            let n = self.pos + 1;
            let skip = if d(n) {
                Some(n)
            } else if matches!(self.s.get(n), Some('+') | Some('-')) && d(n + 1) {
                Some(n + 1)
            } else {
                None
            };
            if let Some(mut i) = skip {
                while d(i) {
                    i += 1;
                }
                self.pos = i;
            }
        }
        let text: String = self.s[start..self.pos].iter().collect();
        match text.parse::<f64>() {
            Ok(v) => Ok(Node::Num(v)),
            Err(_) => Err(format!("`{}` isn't a number {}", text, self.at())),
        }
    }
}

/// How many values a function takes: (least, most).
fn arity(lower: &str) -> Option<(usize, usize)> {
    Some(match lower {
        "if" => (3, 3),
        "and" | "or" | "min" | "max" => (1, usize::MAX),
        "not" | "abs" | "sqrt" | "round" | "roundup" | "rounddown" | "sin" | "cos" | "tan" | "asin" | "acos" | "atan"
        | "exp" | "ln" | "log" => (1, 1),
        "pi" => (0, 0),
        _ => return None,
    })
}

fn not_a_function(name: &str) -> String {
    format!("`{}` isn't a function: there are {}", name, FUNCTIONS)
}

/// `a = b` as the original compares: within a billionth of the larger (of 1, at least).
pub fn approx_eq(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-9 * a.abs().max(b.abs()).max(1.0)
}

impl Formula {
    /// What a family's definition refuses of the functions it calls, the outer first: one it
    /// hasn't (`` `floor` isn't a function: there are … ``) or a count of values it doesn't take
    /// (`` `if` doesn't take 2 values ``).
    pub fn check_calls(&self) -> Result<(), String> {
        fn walk(n: &Node) -> Result<(), String> {
            match n {
                Node::Num(_) | Node::Name(_) => Ok(()),
                Node::Neg(e) => walk(e),
                Node::Bin(_, a, b) => {
                    walk(a)?;
                    walk(b)
                }
                Node::Call(name, args) => {
                    let (lo, hi) = arity(&name.to_lowercase()).ok_or_else(|| not_a_function(name))?;
                    if args.len() < lo || args.len() > hi {
                        return Err(format!("`{}` doesn't take {} values", name, args.len()));
                    }
                    for a in args {
                        walk(a)?;
                    }
                    Ok(())
                }
            }
        }
        walk(&self.root)
    }

    /// The parameters it reads, each once, in the order they first appear.
    pub fn names(&self) -> Vec<String> {
        fn walk(n: &Node, out: &mut Vec<String>) {
            match n {
                Node::Num(_) => {}
                Node::Name(s) => {
                    if !out.iter().any(|x| x == s) {
                        out.push(s.clone());
                    }
                }
                Node::Neg(e) => walk(e, out),
                Node::Bin(_, a, b) => {
                    walk(a, out);
                    walk(b, out);
                }
                Node::Call(_, args) => args.iter().for_each(|a| walk(a, out)),
            }
        }
        let mut out = Vec::new();
        walk(&self.root, &mut out);
        out
    }

    /// Works it out, reading each name with `look` (which says why it can't: `` `Q` isn't one of
    /// its parameters ``, `` `M` is a material, not a number ``…), lazily as the original does:
    /// `if` works out the branch it takes alone. A result that isn't finite is refused (`it comes
    /// to inf, which isn't a number`). The error is without the `formula `…`: ` the caller puts
    /// before it.
    pub fn eval(&self, look: &mut dyn FnMut(&str) -> Result<f64, String>) -> Result<f64, String> {
        let v = eval_node(&self.root, look)?;
        if !v.is_finite() {
            return Err(format!("it comes to {}, which isn't a number", v));
        }
        Ok(v)
    }
}

fn b(x: bool) -> f64 {
    if x {
        1.0
    } else {
        0.0
    }
}

fn eval_node(n: &Node, look: &mut dyn FnMut(&str) -> Result<f64, String>) -> Result<f64, String> {
    match n {
        Node::Num(v) => Ok(*v),
        Node::Name(s) => look(s),
        Node::Neg(e) => Ok(-eval_node(e, look)?),
        Node::Bin(op, l, r) => {
            let x = eval_node(l, look)?;
            let y = eval_node(r, look)?;
            Ok(match op {
                Op::Add => x + y,
                Op::Sub => x - y,
                Op::Mul => x * y,
                Op::Div => x / y,
                Op::Pow => x.powf(y),
                Op::Lt => b(x < y),
                Op::Gt => b(x > y),
                Op::Le => b(x <= y),
                Op::Ge => b(x >= y),
                Op::Eq => b(approx_eq(x, y)),
            })
        }
        Node::Call(name, args) => {
            let lower = name.to_lowercase();
            let n = args.len();
            let one = |look: &mut dyn FnMut(&str) -> Result<f64, String>| -> Result<f64, String> {
                if n != 1 {
                    return Err(format!("`{}` takes one value, not {}", name, n));
                }
                eval_node(&args[0], look)
            };
            let some = |look: &mut dyn FnMut(&str) -> Result<f64, String>| -> Result<Vec<f64>, String> {
                if n == 0 {
                    return Err(format!("`{}` takes one value or more", name));
                }
                let mut v = Vec::with_capacity(n);
                for a in args {
                    v.push(eval_node(a, look)?);
                }
                Ok(v)
            };
            match lower.as_str() {
                "if" => {
                    if n != 3 {
                        return Err(format!("`{}` takes a condition and two values, not {} values", name, n));
                    }
                    let c = eval_node(&args[0], look)?;
                    if c != 0.0 {
                        eval_node(&args[1], look)
                    } else {
                        eval_node(&args[2], look)
                    }
                }
                "and" => Ok(b(some(look)?.iter().all(|x| *x != 0.0))),
                "or" => Ok(b(some(look)?.iter().any(|x| *x != 0.0))),
                "min" => Ok(some(look)?.into_iter().fold(f64::INFINITY, f64::min)),
                "max" => Ok(some(look)?.into_iter().fold(f64::NEG_INFINITY, f64::max)),
                "not" => Ok(b(one(look)? == 0.0)),
                "abs" => Ok(one(look)?.abs()),
                "sqrt" => Ok(one(look)?.sqrt()),
                "round" => Ok(one(look)?.round()),
                "roundup" => Ok(one(look)?.ceil()),
                "rounddown" => Ok(one(look)?.floor()),
                "sin" => Ok(one(look)?.to_radians().sin()),
                "cos" => Ok(one(look)?.to_radians().cos()),
                "tan" => Ok(one(look)?.to_radians().tan()),
                "asin" => Ok(one(look)?.asin().to_degrees()),
                "acos" => Ok(one(look)?.acos().to_degrees()),
                "atan" => Ok(one(look)?.atan().to_degrees()),
                "exp" => Ok(one(look)?.exp()),
                "ln" => Ok(one(look)?.ln()),
                "log" => Ok(one(look)?.log10()),
                "pi" if n == 0 => Ok(std::f64::consts::PI),
                _ => Err(not_a_function(name)),
            }
        }
    }
}

/// A value a name stands for in a formula.
#[derive(Clone, Debug, PartialEq)]
pub enum Val {
    /// A number, a length (mm) or an angle (degrees).
    Num(f64),
    /// A yes (1) or a no (0).
    YesNo(bool),
    /// A material, by name: a formula can't read one.
    Material(String),
}

impl Formula {
    /// Works it out over values by name, with the original's words for a name it hasn't
    /// (`` `Q` isn't one of its parameters ``) and for a material (`` `M` is a material, not a
    /// number ``).
    pub fn eval_with(&self, look: &dyn Fn(&str) -> Option<Val>) -> Result<f64, String> {
        self.eval(&mut |n: &str| match look(n) {
            Some(Val::Num(x)) => Ok(x),
            Some(Val::YesNo(b)) => Ok(if b { 1.0 } else { 0.0 }),
            Some(Val::Material(_)) => Err(format!("`{}` is a material, not a number", n)),
            None => Err(format!("`{}` isn't one of its parameters", n)),
        })
    }
}

/// A family's type worked out (each parameter's value, its formulas read through the others',
/// a component's or an opening's own values by name over the type's, a hosted family's `Wall
/// Thickness`): `crate::structure::family::type_values`, here too for whoever looks for it with
/// the formulas.
pub use crate::structure::family::type_values;

/// Reads and works out a formula over values by name (numbers, a yes as 1 and a no as 0): what
/// a schedule's calculated field or anything else outside a family needs. The error is as a
/// family's definition says it (syntax, an unknown function, a wrong count of values), else as
/// working it out does.
pub fn evaluate(text: &str, look: &mut dyn FnMut(&str) -> Result<f64, String>) -> Result<f64, String> {
    let f = parse(text).map_err(|e| e.message())?;
    f.check_calls()?;
    f.eval(look)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ev(s: &str) -> Result<f64, String> {
        let f = parse(s).map_err(|e| e.message())?;
        f.eval(&mut |n: &str| match n {
            "A" => Ok(100.0),
            "B" => Ok(3.0),
            "Y" => Ok(1.0),
            "N" => Ok(0.0),
            "Wide Thing" => Ok(250.0),
            _ => Err(format!("`{}` isn't one of its parameters", n)),
        })
    }

    #[test]
    fn values() {
        assert_eq!(ev("A/3"), Ok(33.333333333333336));
        assert_eq!(ev("2^3^2"), Ok(512.0));
        assert_eq!(ev("-2^2"), Ok(4.0));
        assert_eq!(ev("2*-3^2"), Ok(18.0));
        assert_eq!(ev("sin(30)"), Ok(0.49999999999999994));
        assert_eq!(ev("cos(60)"), Ok(0.5000000000000001));
        assert_eq!(ev("tan(45)"), Ok(0.9999999999999999));
        assert_eq!(ev("asin(0.5)"), Ok(30.000000000000004));
        assert_eq!(ev("acos(0.5)"), Ok(60.00000000000001));
        assert_eq!(ev("tan(90)"), Ok(1.633123935319537e16));
        assert_eq!(ev("cos(90)"), Ok(6.123233995736766e-17));
        assert_eq!(ev("atan(0.5)"), Ok(26.56505117707799));
        assert_eq!(ev("round(-2.5)"), Ok(-3.0));
        assert_eq!(ev("1 < = 2"), Ok(1.0));
        assert_eq!(ev("Wide Thing * 2"), Ok(500.0));
        assert_eq!(ev("1.e5"), Ok(100000.0));
        assert_eq!(ev("if(1, 1, 1/0)"), Ok(1.0));
        assert_eq!(ev("10/0"), Err("it comes to inf, which isn't a number".into()));
        assert_eq!(ev("0/0"), Err("it comes to NaN, which isn't a number".into()));
        assert_eq!(ev("ln(0)"), Err("it comes to -inf, which isn't a number".into()));
    }

    #[test]
    fn syntax() {
        let e = |s: &str| parse(s).unwrap_err().message();
        assert_eq!(e("5 mm"), "`m` follows where it should end (character 3)");
        assert_eq!(e("1 +"), "something's missing at its end (character 4)");
        assert_eq!(e("(1"), "a `(` isn't closed (character 3)");
        assert_eq!(e("1 <> 2"), "`>` can't start a value there (character 4)");
        assert_eq!(e("1.2.3"), "`1.2.3` isn't a number (character 6)");
        assert_eq!(e(".e5"), "`.e5` isn't a number (character 4)");
        assert_eq!(e("max(1 2)"), "`max(` needs a `,` or a `)` (character 7)");
        assert_eq!(e("Ä + * 3"), "`*` can't start a value there (character 5)");
        assert_eq!(e(&format!("{}1{}", "(".repeat(64), ")".repeat(64))), "it's nested too deep (more than 64 levels) (character 65)");
        assert!(parse(&format!("{}1{}", "(".repeat(63), ")".repeat(63))).is_ok());
        assert_eq!(e(&format!("{}1", "2^".repeat(64))), "it's nested too deep (more than 64 levels) (character 129)");
        assert_eq!(e(" "), "a formula is empty");
    }
}
