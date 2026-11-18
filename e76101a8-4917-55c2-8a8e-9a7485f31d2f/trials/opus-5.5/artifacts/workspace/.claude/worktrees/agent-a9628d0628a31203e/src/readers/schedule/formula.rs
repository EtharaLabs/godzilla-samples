//! Calculated fields' formulas, as a family's are written: numbers, the row's fields by name
//! (words and spaces as the field is named), `+ - * / ^`, a comparison (`< <= > >= =`), and
//! if, and, or, not, min, max, abs, sqrt, round, roundup, rounddown, sin, cos, tan (degrees),
//! asin, acos, atan, exp, ln, log and pi().

#[derive(Clone, Debug)]
pub enum Expr {
    Num(f64),
    /// A field, by name.
    Field(String),
    Neg(Box<Expr>),
    Bin(Op, Box<Expr>, Box<Expr>),
    Call(Func, Vec<Expr>),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Op {
    Add,
    Sub,
    Mul,
    Div,
    Pow,
    Lt,
    Le,
    Gt,
    Ge,
    Eq,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Func {
    If,
    And,
    Or,
    Not,
    Min,
    Max,
    Abs,
    Sqrt,
    Round,
    RoundUp,
    RoundDown,
    Sin,
    Cos,
    Tan,
    Asin,
    Acos,
    Atan,
    Exp,
    Ln,
    Log,
    Pi,
}

const FUNCS: &[(&str, Func)] = &[
    ("if", Func::If),
    ("and", Func::And),
    ("or", Func::Or),
    ("not", Func::Not),
    ("min", Func::Min),
    ("max", Func::Max),
    ("abs", Func::Abs),
    ("sqrt", Func::Sqrt),
    ("round", Func::Round),
    ("roundup", Func::RoundUp),
    ("rounddown", Func::RoundDown),
    ("sin", Func::Sin),
    ("cos", Func::Cos),
    ("tan", Func::Tan),
    ("asin", Func::Asin),
    ("acos", Func::Acos),
    ("atan", Func::Atan),
    ("exp", Func::Exp),
    ("ln", Func::Ln),
    ("log", Func::Log),
    ("pi", Func::Pi),
];

const FUNC_LIST: &str = "if, and, or, not, min, max, abs, sqrt, round, roundup, rounddown, sin, cos, tan, asin, acos, atan, exp, ln, log and pi()";

impl Func {
    fn takes(self, n: usize) -> bool {
        match self {
            Func::If => n == 3,
            Func::And | Func::Or | Func::Min | Func::Max => n >= 1,
            Func::Pi => n == 0,
            _ => n == 1,
        }
    }
}

struct Parser {
    s: Vec<char>,
    i: usize,
}

type PR<T> = Result<T, String>;

impl Parser {
    fn skip(&mut self) {
        while self.i < self.s.len() && self.s[self.i].is_whitespace() {
            self.i += 1;
        }
    }
    fn peek(&mut self) -> Option<char> {
        self.skip();
        self.s.get(self.i).copied()
    }
    /// The 1-based place of the character the parser is at (one past the end at the end).
    fn at(&self) -> usize {
        self.i + 1
    }
    fn missing_or(&self, what: &dyn Fn(char) -> String) -> String {
        match self.s.get(self.i) {
            Some(c) => format!("{} (character {})", what(*c), self.at()),
            None => format!("something's missing at its end (character {})", self.at()),
        }
    }

    fn expr(&mut self) -> PR<Expr> {
        let a = self.add()?;
        let op = match self.peek() {
            Some('<') | Some('>') => {
                let c = self.s[self.i];
                self.i += 1;
                let eq = self.peek() == Some('=');
                if eq {
                    self.i += 1;
                }
                match (c, eq) {
                    ('<', false) => Op::Lt,
                    ('<', true) => Op::Le,
                    ('>', false) => Op::Gt,
                    _ => Op::Ge,
                }
            }
            Some('=') => {
                self.i += 1;
                Op::Eq
            }
            _ => return Ok(a),
        };
        let b = self.add()?;
        Ok(Expr::Bin(op, Box::new(a), Box::new(b)))
    }

    fn add(&mut self) -> PR<Expr> {
        let mut a = self.mul()?;
        loop {
            let op = match self.peek() {
                Some('+') => Op::Add,
                Some('-') => Op::Sub,
                _ => return Ok(a),
            };
            self.i += 1;
            let b = self.mul()?;
            a = Expr::Bin(op, Box::new(a), Box::new(b));
        }
    }

    fn mul(&mut self) -> PR<Expr> {
        let mut a = self.pow()?;
        loop {
            let op = match self.peek() {
                Some('*') => Op::Mul,
                Some('/') => Op::Div,
                _ => return Ok(a),
            };
            self.i += 1;
            let b = self.pow()?;
            a = Expr::Bin(op, Box::new(a), Box::new(b));
        }
    }

    fn pow(&mut self) -> PR<Expr> {
        let a = self.unary()?;
        if self.peek() == Some('^') {
            self.i += 1;
            let b = self.pow()?;
            return Ok(Expr::Bin(Op::Pow, Box::new(a), Box::new(b)));
        }
        Ok(a)
    }

    fn unary(&mut self) -> PR<Expr> {
        match self.peek() {
            Some('-') => {
                self.i += 1;
                let a = self.unary()?;
                Ok(Expr::Neg(Box::new(a)))
            }
            Some('+') => {
                self.i += 1;
                self.unary()
            }
            _ => self.primary(),
        }
    }

    fn primary(&mut self) -> PR<Expr> {
        let Some(c) = self.peek() else {
            return Err(format!("something's missing at its end (character {})", self.at()));
        };
        if c.is_ascii_digit() || c == '.' {
            let start = self.i;
            while self.i < self.s.len() && (self.s[self.i].is_ascii_digit() || self.s[self.i] == '.') {
                self.i += 1;
            }
            // an exponent, where digits follow it
            if self.i < self.s.len() && (self.s[self.i] == 'e' || self.s[self.i] == 'E') {
                let mut j = self.i + 1;
                if j < self.s.len() && (self.s[j] == '+' || self.s[j] == '-') {
                    j += 1;
                }
                if j < self.s.len() && self.s[j].is_ascii_digit() {
                    while j < self.s.len() && self.s[j].is_ascii_digit() {
                        j += 1;
                    }
                    self.i = j;
                }
            }
            let text: String = self.s[start..self.i].iter().collect();
            return match text.parse::<f64>() {
                Ok(x) => Ok(Expr::Num(x)),
                Err(_) => Err(format!("`{}` isn't a number (character {})", text, self.at())),
            };
        }
        if c.is_alphabetic() || c == '_' {
            let start = self.i;
            while self.i < self.s.len() && (self.s[self.i].is_alphanumeric() || self.s[self.i] == '_' || self.s[self.i] == ' ') {
                self.i += 1;
            }
            let raw: String = self.s[start..self.i].iter().collect();
            let name = raw.trim_end().to_string();
            if self.peek() == Some('(') {
                let low = name.to_lowercase();
                let Some((_, f)) = FUNCS.iter().find(|(n, _)| *n == low) else {
                    return Err(format!("`{}` isn't a function: there are {}", name, FUNC_LIST));
                };
                self.i += 1;
                let mut args = Vec::new();
                if self.peek() == Some(')') {
                    self.i += 1;
                } else {
                    loop {
                        args.push(self.expr()?);
                        match self.peek() {
                            Some(',') => {
                                self.i += 1;
                            }
                            Some(')') => {
                                self.i += 1;
                                break;
                            }
                            _ => return Err(format!("`{}(` needs a `,` or a `)` (character {})", name, self.at())),
                        }
                    }
                }
                if !f.takes(args.len()) {
                    return Err(format!("`{}` doesn't take {} values", name, args.len()));
                }
                return Ok(Expr::Call(*f, args));
            }
            return Ok(Expr::Field(name));
        }
        if c == '(' {
            self.i += 1;
            let e = self.expr()?;
            if self.peek() == Some(')') {
                self.i += 1;
                return Ok(e);
            }
            return Err(format!("a `(` isn't closed (character {})", self.at()));
        }
        Err(self.missing_or(&|c| format!("`{}` can't start a value there", c)))
    }
}

/// A formula parsed, or what's wrong with it ("something's missing at its end (character 8)").
pub fn parse(src: &str) -> Result<Expr, String> {
    let mut p = Parser { s: src.chars().collect(), i: 0 };
    let e = p.expr()?;
    if let Some(c) = p.peek() {
        return Err(format!("`{}` follows where it should end (character {})", c, p.at()));
    }
    Ok(e)
}

/// The fields a formula reads, in the order it names them.
pub fn fields(e: &Expr, out: &mut Vec<String>) {
    match e {
        Expr::Num(_) => {}
        Expr::Field(n) => out.push(n.clone()),
        Expr::Neg(a) => fields(a, out),
        Expr::Bin(_, a, b) => {
            fields(a, out);
            fields(b, out);
        }
        Expr::Call(_, args) => args.iter().for_each(|a| fields(a, out)),
    }
}

fn deg(x: f64) -> f64 {
    x.to_radians()
}

fn b(x: bool) -> f64 {
    if x {
        1.0
    } else {
        0.0
    }
}

/// A formula's value, the fields read through `get` (None: no value, which the result has too).
pub fn eval(e: &Expr, get: &mut dyn FnMut(&str) -> Option<f64>) -> Option<f64> {
    Some(match e {
        Expr::Num(x) => *x,
        Expr::Field(n) => get(n)?,
        Expr::Neg(a) => -eval(a, get)?,
        Expr::Bin(op, a, bb) => {
            let x = eval(a, get)?;
            let y = eval(bb, get)?;
            match op {
                Op::Add => x + y,
                Op::Sub => x - y,
                Op::Mul => x * y,
                Op::Div => x / y,
                Op::Pow => x.powf(y),
                Op::Lt => b(x < y),
                Op::Le => b(x <= y),
                Op::Gt => b(x > y),
                Op::Ge => b(x >= y),
                Op::Eq => b(x == y),
            }
        }
        Expr::Call(f, args) => match f {
            Func::If => {
                let c = eval(&args[0], get)?;
                if c != 0.0 {
                    eval(&args[1], get)?
                } else {
                    eval(&args[2], get)?
                }
            }
            Func::And | Func::Or | Func::Min | Func::Max => {
                let mut vals = Vec::with_capacity(args.len());
                for a in args {
                    vals.push(eval(a, get)?);
                }
                match f {
                    Func::And => b(vals.iter().all(|v| *v != 0.0)),
                    Func::Or => b(vals.iter().any(|v| *v != 0.0)),
                    Func::Min => vals.iter().copied().fold(f64::INFINITY, f64::min),
                    _ => vals.iter().copied().fold(f64::NEG_INFINITY, f64::max),
                }
            }
            Func::Pi => std::f64::consts::PI,
            _ => {
                let x = eval(&args[0], get)?;
                match f {
                    Func::Not => b(x == 0.0),
                    Func::Abs => x.abs(),
                    Func::Sqrt => x.sqrt(),
                    Func::Round => x.round(),
                    Func::RoundUp => x.ceil(),
                    Func::RoundDown => x.floor(),
                    Func::Sin => deg(x).sin(),
                    Func::Cos => deg(x).cos(),
                    Func::Tan => deg(x).tan(),
                    Func::Asin => x.asin().to_degrees(),
                    Func::Acos => x.acos().to_degrees(),
                    Func::Atan => x.atan().to_degrees(),
                    Func::Exp => x.exp(),
                    Func::Ln => x.ln(),
                    _ => x.log10(),
                }
            }
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn val(s: &str) -> Option<f64> {
        let e = parse(s).unwrap();
        eval(&e, &mut |n| if n == "Length" { Some(8000.0) } else { None })
    }

    #[test]
    fn reads_as_the_original() {
        assert_eq!(val("2 ^ 3 ^ 2"), Some(512.0));
        assert_eq!(val("-2 ^ 2"), Some(4.0));
        assert_eq!(val("Length > = 2"), Some(1.0));
        assert_eq!(parse("Width *").unwrap_err(), "something's missing at its end (character 8)");
        assert_eq!(parse("if(Length == 8000, 1, 2)").unwrap_err(), "`=` can't start a value there (character 12)");
        assert_eq!(parse("if(Length <> 8000, 1, 2)").unwrap_err(), "`>` can't start a value there (character 12)");
        assert_eq!(parse("if(Length != 8000, 1, 2)").unwrap_err(), "`if(` needs a `,` or a `)` (character 11)");
        assert_eq!(parse("2 * (3").unwrap_err(), "a `(` isn't closed (character 7)");
        assert_eq!(parse("(1, 5)").unwrap_err(), "a `(` isn't closed (character 3)");
        assert_eq!(parse("1.2.3").unwrap_err(), "`1.2.3` isn't a number (character 6)");
        assert_eq!(parse("1e").unwrap_err(), "`e` follows where it should end (character 2)");
        assert_eq!(parse("Length > 9000 and Length < 1").unwrap_err(), "`a` follows where it should end (character 15)");
        assert_eq!(parse("1 < 2 < 3").unwrap_err(), "`<` follows where it should end (character 7)");
    }
}
