// Binding right-hand sides: `w = 120;` stays bare, `k = a b;` gains a group,
// and `k = (a);` sheds one. The decision reads the text as a math expression.

#[derive(Clone, Debug, PartialEq)]
enum Kind {
    Num,
    Ident,
    Call,
    Unary,
    Paren(Box<Kind>),
    Compound, // binary, ternary, tuple, block
}

#[derive(Clone, Debug, PartialEq)]
enum T {
    Num,
    Ident,
    Op(String),
    LParen,
    RParen,
    Comma,
    Eq,
    Semi,
    Colon,
    Bad,
}

fn tokenize(s: &str) -> Vec<(T, bool)> {
    // (token, whitespace before)
    let cs: Vec<char> = s.chars().collect();
    let n = cs.len();
    let at = |i: usize| -> char { if i < n { cs[i] } else { '\0' } };
    let mut out = Vec::new();
    let mut i = 0;
    let mut sp = true;
    while i < n {
        let c = cs[i];
        if c.is_whitespace() {
            sp = true;
            i += 1;
            continue;
        }
        if c == '/' && at(i + 1) == '/' {
            while i < n && cs[i] != '\n' {
                i += 1;
            }
            sp = true;
            continue;
        }
        let t;
        if c.is_ascii_digit() || (c == '.' && at(i + 1).is_ascii_digit()) {
            while at(i).is_ascii_digit() {
                i += 1;
            }
            if at(i) == '.' && at(i + 1).is_ascii_digit() {
                i += 1;
                while at(i).is_ascii_digit() {
                    i += 1;
                }
            }
            if at(i) == 'e' || at(i) == 'E' {
                let mut j = i + 1;
                if at(j) == '+' || at(j) == '-' {
                    j += 1;
                }
                if at(j).is_ascii_digit() {
                    while at(j).is_ascii_digit() {
                        j += 1;
                    }
                    i = j;
                }
            }
            if at(i) == '%' {
                t = T::Bad;
                i += 1;
            } else {
                t = T::Num;
            }
        } else if c.is_ascii_alphabetic() || c == '_' {
            // inside math '-' subtracts: `x-93` is x minus 93
            while at(i).is_ascii_alphanumeric() || at(i) == '_' {
                i += 1;
            }
            t = T::Ident;
        } else {
            let two: String = [c, at(i + 1)].iter().collect();
            if ["<=", ">=", "==", "!=", "&&", "||"].contains(&two.as_str()) {
                t = T::Op(two);
                i += 2;
            } else {
                i += 1;
                t = match c {
                    '+' | '-' | '*' | '/' | '^' | '<' | '>' | '?' => T::Op(c.to_string()),
                    '(' => T::LParen,
                    ')' => T::RParen,
                    ',' => T::Comma,
                    '=' => T::Eq,
                    ';' => T::Semi,
                    ':' => T::Colon,
                    _ => T::Bad,
                };
            }
        }
        out.push((t, sp));
        sp = false;
    }
    out
}

struct P {
    toks: Vec<(T, bool)>,
    pos: usize,
}

// no '&&' / '||' in the math language
fn prec(op: &str) -> Option<u8> {
    Some(match op {
        "==" | "!=" => 3,
        "<" | ">" | "<=" | ">=" => 4,
        "+" | "-" => 5,
        "*" | "/" => 6,
        "^" => 8,
        _ => return None,
    })
}

impl P {
    fn peek(&self) -> Option<&T> {
        self.toks.get(self.pos).map(|t| &t.0)
    }
    fn peek2(&self) -> Option<&T> {
        self.toks.get(self.pos + 1).map(|t| &t.0)
    }
    fn bump(&mut self) {
        self.pos += 1;
    }
    fn expr(&mut self) -> Option<Kind> {
        // local bindings: name = expr; ... expr
        let mut block = false;
        while matches!(self.peek(), Some(T::Ident)) && matches!(self.peek2(), Some(T::Eq)) {
            self.bump();
            self.bump();
            self.ternary()?;
            if matches!(self.peek(), Some(T::Semi)) {
                self.bump();
            }
            block = true;
        }
        let k = self.ternary()?;
        Some(if block { Kind::Compound } else { k })
    }
    fn ternary(&mut self) -> Option<Kind> {
        let c = self.binary(0)?;
        if matches!(self.peek(), Some(T::Op(o)) if o == "?") {
            self.bump();
            self.ternary()?;
            if !matches!(self.peek(), Some(T::Colon)) {
                return None;
            }
            self.bump();
            self.ternary()?;
            return Some(Kind::Compound);
        }
        Some(c)
    }
    fn binary(&mut self, min: u8) -> Option<Kind> {
        let mut lhs = self.unary()?;
        loop {
            let op = match self.peek() {
                Some(T::Op(o)) => o.clone(),
                _ => break,
            };
            let p = match prec(&op) {
                Some(p) => p,
                None => break,
            };
            if p < min {
                break;
            }
            self.bump();
            let next = if op == "^" { p } else { p + 1 };
            self.binary(next)?;
            lhs = Kind::Compound;
        }
        Some(lhs)
    }
    // unary minus binds looser than '^': -x^2 is -(x^2)
    fn unary(&mut self) -> Option<Kind> {
        if matches!(self.peek(), Some(T::Op(o)) if o == "-") {
            self.bump();
            self.unary_pow()?;
            return Some(Kind::Unary);
        }
        self.primary()
    }
    fn unary_pow(&mut self) -> Option<Kind> {
        let base = self.unary()?;
        if matches!(self.peek(), Some(T::Op(o)) if o == "^") {
            self.bump();
            self.binary(8)?;
            return Some(Kind::Compound);
        }
        Some(base)
    }
    fn primary(&mut self) -> Option<Kind> {
        match self.peek()?.clone() {
            T::Num => {
                self.bump();
                Some(Kind::Num)
            }
            T::Ident => {
                self.bump();
                if matches!(self.peek(), Some(T::LParen)) {
                    self.bump();
                    if matches!(self.peek(), Some(T::RParen)) {
                        self.bump();
                        return Some(Kind::Call);
                    }
                    loop {
                        self.expr()?;
                        match self.peek() {
                            Some(T::Comma) => self.bump(),
                            Some(T::RParen) => {
                                self.bump();
                                return Some(Kind::Call);
                            }
                            _ => return None,
                        }
                    }
                }
                Some(Kind::Ident)
            }
            T::LParen => {
                self.bump();
                let k = self.expr()?;
                let mut tuple = false;
                while matches!(self.peek(), Some(T::Comma)) {
                    self.bump();
                    self.expr()?;
                    tuple = true;
                }
                if !matches!(self.peek(), Some(T::RParen)) {
                    return None;
                }
                self.bump();
                Some(if tuple { Kind::Compound } else { Kind::Paren(Box::new(k)) })
            }
            _ => None,
        }
    }
}

fn classify(s: &str) -> Option<Kind> {
    let toks = tokenize(s);
    if toks.iter().any(|t| t.0 == T::Bad) {
        return None;
    }
    let mut p = P { toks, pos: 0 };
    let k = p.expr()?;
    if p.pos != p.toks.len() {
        return None;
    }
    Some(k)
}

fn simple(k: &Kind) -> bool {
    matches!(k, Kind::Num | Kind::Ident | Kind::Call | Kind::Unary)
}

fn core(k: &Kind) -> &Kind {
    match k {
        Kind::Paren(inner) => core(inner),
        k => k,
    }
}

// RHS written as '( inner )'
pub fn binding_group(inner: &str) -> String {
    match classify(inner) {
        Some(k) if simple(core(&k)) => inner.to_string(),
        _ => format!("({})", inner),
    }
}

// RHS written bare
pub fn binding_bare(text: &str) -> String {
    match classify(text) {
        Some(k) if simple(&k) => text.to_string(),
        _ => format!("({})", text),
    }
}
