//! The family formula language, as the original reads and works it out: numbers (lengths in mm,
//! angles in degrees), parameters by name (words with spaces and digits between them),
//! `+ - * / ^` (`^` to the right, a sign binding tighter than it), the comparisons
//! `< > = <= >=` (one to a formula's level, `=` equal to within a billionth), and the functions
//! `if`, `and`, `or`, `not`, `min`, `max`, `abs`, `sqrt`, `round`, `roundup`, `rounddown`, `sin`,
//! `cos`, `tan`, `asin`, `acos`, `atan` (degrees), `exp`, `ln`, `log` and `pi()`, in any case.

/// A formula read.
#[derive(Clone, Debug)]
pub enum Expr {
    Num(f64),
    Name(String),
    Neg(Box<Expr>),
    Bin(char, Box<Expr>, Box<Expr>),
    Cmp(&'static str, Box<Expr>, Box<Expr>),
    Call(String, Vec<Expr>),
}

#[derive(Clone, Debug, PartialEq)]
enum Tok {
    Num(f64),
    Name(String),
    Op(&'static str),
}

const STOP: &[char] = &['+', '-', '*', '/', '^', '(', ')', ',', '<', '>', '=', '!', '%'];

fn lex(s: &str) -> Result<Vec<(Tok, usize)>, String> {
    let cs: Vec<char> = s.chars().collect();
    let mut i = 0;
    let mut out = Vec::new();
    while i < cs.len() {
        let c = cs[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        let at = i + 1;
        if c.is_ascii_digit() || (c == '.' && cs.get(i + 1).map(|d| d.is_ascii_digit()).unwrap_or(false)) {
            let st = i;
            while i < cs.len() && cs[i].is_ascii_digit() {
                i += 1;
            }
            if i < cs.len() && cs[i] == '.' {
                i += 1;
                while i < cs.len() && cs[i].is_ascii_digit() {
                    i += 1;
                }
            }
            if i < cs.len() && (cs[i] == 'e' || cs[i] == 'E') {
                let mut j = i + 1;
                if j < cs.len() && (cs[j] == '+' || cs[j] == '-') {
                    j += 1;
                }
                if j < cs.len() && cs[j].is_ascii_digit() {
                    while j < cs.len() && cs[j].is_ascii_digit() {
                        j += 1;
                    }
                    i = j;
                }
            }
            let t: String = cs[st..i].iter().collect();
            let v: f64 = t.parse().map_err(|_| format!("`{}` isn't a number (character {})", t, at))?;
            out.push((Tok::Num(v), at));
            continue;
        }
        let two: String = cs[i..(i + 2).min(cs.len())].iter().collect();
        if two == "<=" || two == ">=" {
            out.push((Tok::Op(if two == "<=" { "<=" } else { ">=" }), at));
            i += 2;
            continue;
        }
        if STOP.contains(&c) {
            let op: &'static str = match c {
                '+' => "+",
                '-' => "-",
                '*' => "*",
                '/' => "/",
                '^' => "^",
                '(' => "(",
                ')' => ")",
                ',' => ",",
                '<' => "<",
                '>' => ">",
                '=' => "=",
                '!' => "!",
                _ => "%",
            };
            out.push((Tok::Op(op), at));
            i += 1;
            continue;
        }
        // a name: everything up to the next operator, its trailing spaces left out
        let st = i;
        while i < cs.len() && !STOP.contains(&cs[i]) {
            i += 1;
        }
        let t: String = cs[st..i].iter().collect();
        out.push((Tok::Name(t.trim_end().to_string()), at));
    }
    Ok(out)
}

struct P {
    toks: Vec<(Tok, usize)>,
    i: usize,
    len: usize,
}

impl P {
    fn peek(&self) -> Option<&Tok> {
        self.toks.get(self.i).map(|t| &t.0)
    }
    fn at(&self) -> usize {
        self.toks.get(self.i).map(|t| t.1).unwrap_or(self.len + 1)
    }
    fn is_op(&self, op: &str) -> bool {
        matches!(self.peek(), Some(Tok::Op(o)) if *o == op)
    }
    fn cmp(&mut self) -> Result<Expr, String> {
        let a = self.add()?;
        for op in ["<=", ">=", "<", ">", "="] {
            if self.is_op(op) {
                self.i += 1;
                let b = self.add()?;
                let op: &'static str = match op {
                    "<=" => "<=",
                    ">=" => ">=",
                    "<" => "<",
                    ">" => ">",
                    _ => "=",
                };
                return Ok(Expr::Cmp(op, Box::new(a), Box::new(b)));
            }
        }
        Ok(a)
    }
    fn add(&mut self) -> Result<Expr, String> {
        let mut a = self.mul()?;
        loop {
            let op = if self.is_op("+") {
                '+'
            } else if self.is_op("-") {
                '-'
            } else {
                break;
            };
            self.i += 1;
            let b = self.mul()?;
            a = Expr::Bin(op, Box::new(a), Box::new(b));
        }
        Ok(a)
    }
    fn mul(&mut self) -> Result<Expr, String> {
        let mut a = self.pow()?;
        loop {
            let op = if self.is_op("*") {
                '*'
            } else if self.is_op("/") {
                '/'
            } else {
                break;
            };
            self.i += 1;
            let b = self.pow()?;
            a = Expr::Bin(op, Box::new(a), Box::new(b));
        }
        Ok(a)
    }
    fn pow(&mut self) -> Result<Expr, String> {
        let a = self.unary()?;
        if self.is_op("^") {
            self.i += 1;
            let b = self.pow()?;
            return Ok(Expr::Bin('^', Box::new(a), Box::new(b)));
        }
        Ok(a)
    }
    fn unary(&mut self) -> Result<Expr, String> {
        if self.is_op("-") {
            self.i += 1;
            let a = self.unary()?;
            return Ok(Expr::Neg(Box::new(a)));
        }
        if self.is_op("+") {
            self.i += 1;
            return self.unary();
        }
        self.primary()
    }
    fn primary(&mut self) -> Result<Expr, String> {
        let at = self.at();
        match self.peek().cloned() {
            None => Err(format!("something's missing at its end (character {})", at)),
            Some(Tok::Num(v)) => {
                self.i += 1;
                Ok(Expr::Num(v))
            }
            Some(Tok::Name(n)) => {
                self.i += 1;
                if self.is_op("(") {
                    self.i += 1;
                    let mut args = Vec::new();
                    if self.is_op(")") {
                        self.i += 1;
                    } else {
                        loop {
                            args.push(self.cmp()?);
                            if self.is_op(",") {
                                self.i += 1;
                                continue;
                            }
                            if self.is_op(")") {
                                self.i += 1;
                                break;
                            }
                            return Err(format!("a `(` isn't closed (character {})", self.at()));
                        }
                    }
                    Ok(Expr::Call(n.to_lowercase(), args))
                } else {
                    Ok(Expr::Name(n))
                }
            }
            Some(Tok::Op("(")) => {
                self.i += 1;
                let e = self.cmp()?;
                if !self.is_op(")") {
                    return Err(format!("a `(` isn't closed (character {})", self.at()));
                }
                self.i += 1;
                Ok(e)
            }
            Some(Tok::Op(o)) => Err(format!("`{}` can't start a value there (character {})", o, at)),
        }
    }
}

/// Reads a formula.
pub fn parse(s: &str) -> Result<Expr, String> {
    let toks = lex(s)?;
    if toks.is_empty() {
        return Err("a formula is empty".into());
    }
    let mut p = P { toks, i: 0, len: s.chars().count() };
    let e = p.cmp()?;
    if p.i < p.toks.len() {
        let t = &p.toks[p.i];
        let what = match &t.0 {
            Tok::Num(v) => crate::json::fmt_f64(*v),
            Tok::Name(n) => n.clone(),
            Tok::Op(o) => o.to_string(),
        };
        return Err(format!("`{}` follows where it should end (character {})", what, t.1));
    }
    Ok(e)
}

/// The names a formula reads (its parameters), in the order it reads them.
pub fn names(e: &Expr, out: &mut Vec<String>) {
    match e {
        Expr::Num(_) => {}
        Expr::Name(n) => {
            if !out.contains(n) {
                out.push(n.clone())
            }
        }
        Expr::Neg(a) => names(a, out),
        Expr::Bin(_, a, b) | Expr::Cmp(_, a, b) => {
            names(a, out);
            names(b, out);
        }
        Expr::Call(_, args) => args.iter().for_each(|a| names(a, out)),
    }
}

fn truth(x: f64) -> bool {
    x != 0.0
}

fn b(x: bool) -> f64 {
    if x {
        1.0
    } else {
        0.0
    }
}

/// Works a formula out, reading its names through `get`.
pub fn eval(e: &Expr, get: &mut dyn FnMut(&str) -> Result<f64, String>) -> Result<f64, String> {
    Ok(match e {
        Expr::Num(v) => *v,
        Expr::Name(n) => get(n)?,
        Expr::Neg(a) => -eval(a, get)?,
        Expr::Bin(op, a, bb) => {
            let x = eval(a, get)?;
            let y = eval(bb, get)?;
            match op {
                '+' => x + y,
                '-' => x - y,
                '*' => x * y,
                '/' => x / y,
                _ => x.powf(y),
            }
        }
        Expr::Cmp(op, a, bb) => {
            let x = eval(a, get)?;
            let y = eval(bb, get)?;
            b(match *op {
                "<" => x < y,
                ">" => x > y,
                "<=" => x <= y,
                ">=" => x >= y,
                _ => (x - y).abs() <= 1e-9 * 1f64.max(x.abs()).max(y.abs()),
            })
        }
        Expr::Call(f, args) => {
            let n = args.len();
            let arity = |want: usize| -> Result<(), String> {
                if n != want {
                    Err(format!("`{}` doesn't take {} values", f, n))
                } else {
                    Ok(())
                }
            };
            match f.as_str() {
                "if" => {
                    arity(3)?;
                    let c = eval(&args[0], get)?;
                    if truth(c) {
                        eval(&args[1], get)?
                    } else {
                        eval(&args[2], get)?
                    }
                }
                "and" | "or" => {
                    if n == 0 {
                        return Err(format!("`{}` doesn't take 0 values", f));
                    }
                    let mut vals = Vec::new();
                    for a in args {
                        vals.push(truth(eval(a, get)?));
                    }
                    b(if f == "and" { vals.iter().all(|v| *v) } else { vals.iter().any(|v| *v) })
                }
                "min" | "max" => {
                    if n == 0 {
                        return Err(format!("`{}` doesn't take 0 values", f));
                    }
                    let mut acc = eval(&args[0], get)?;
                    for a in &args[1..] {
                        let v = eval(a, get)?;
                        acc = if f == "min" { acc.min(v) } else { acc.max(v) };
                    }
                    acc
                }
                "pi" => {
                    arity(0)?;
                    std::f64::consts::PI
                }
                one => {
                    arity(1)?;
                    let x = eval(&args[0], get)?;
                    match one {
                        "not" => b(!truth(x)),
                        "abs" => x.abs(),
                        "sqrt" => x.sqrt(),
                        "round" => x.round(),
                        "roundup" => x.ceil(),
                        "rounddown" => x.floor(),
                        "sin" => x.to_radians().sin(),
                        "cos" => x.to_radians().cos(),
                        "tan" => x.to_radians().tan(),
                        "asin" => x.asin().to_degrees(),
                        "acos" => x.acos().to_degrees(),
                        "atan" => x.atan().to_degrees(),
                        "exp" => x.exp(),
                        "ln" => x.ln(),
                        "log" => x.log10(),
                        _ => return Err(format!("`{}` isn't a function", one)),
                    }
                }
            }
        }
    })
}

/// Works out a formula given as text.
pub fn eval_str(s: &str, get: &mut dyn FnMut(&str) -> Result<f64, String>) -> Result<f64, String> {
    let e = parse(s)?;
    eval(&e, get)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn ev(s: &str) -> f64 {
        eval_str(s, &mut |n| match n {
            "A" => Ok(1200.0),
            "B" => Ok(500.0),
            "Long Name X" => Ok(10.0),
            _ => Err(format!("no {}", n)),
        })
        .unwrap()
    }
    #[test]
    fn basics() {
        assert_eq!(ev("1 + 2 * 3"), 7.0);
        assert_eq!(ev("2 ^ 3 ^ 2"), 512.0);
        assert_eq!(ev("-2 ^ 2"), 4.0);
        assert_eq!(ev("-2^-2"), 0.25);
        assert_eq!(ev("7 - 2 - 1"), 4.0);
        assert_eq!(ev("A / B"), 2.4);
        assert_eq!(ev("Long Name X * 2"), 20.0);
        assert_eq!(ev("1 + 2 > 2"), 1.0);
        assert_eq!(ev("0.1 + 0.2 = 0.3"), 1.0);
        assert_eq!(ev("SIN(30)"), 0.49999999999999994);
        assert_eq!(ev("asin(0.5)"), 30.000000000000004);
        assert_eq!(ev("round(-2.5)"), -3.0);
        assert_eq!(ev("5."), 5.0);
        assert_eq!(ev(".5"), 0.5);
        assert_eq!(ev("1e3"), 1000.0);
        assert_eq!(ev("max(A, B, 3)"), 1200.0);
        assert_eq!(ev("if(A > B, 1, 2)"), 1.0);
    }
}
