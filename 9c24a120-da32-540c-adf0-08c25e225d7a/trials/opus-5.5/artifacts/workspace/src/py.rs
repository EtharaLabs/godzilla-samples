// Python AST and printer.

#[derive(Clone, Debug, PartialEq)]
pub enum FsPart {
    Lit(String),
    Expr(PE),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Bop {
    Add,
    Sub,
    Mul,
    Div,
    FloorDiv,
    Mod,
    Pow,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Cop {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
    In,
    NotIn,
    Is,
    IsNot,
}

#[derive(Clone, Debug, PartialEq)]
pub enum PE {
    Name(String),
    Int(i64),
    Float(f64),
    Str(String),
    Bool(bool),
    NoneV,
    FStr(Vec<FsPart>),
    Call(Box<PE>, Vec<PE>, Vec<(String, PE)>),
    Attr(Box<PE>, String),
    Index(Box<PE>, Box<PE>),
    Bin(Box<PE>, Bop, Box<PE>),
    Neg(Box<PE>),
    Not(Box<PE>),
    And(Box<PE>, Box<PE>),
    Or(Box<PE>, Box<PE>),
    Cmp(Box<PE>, Vec<(Cop, PE)>),
    IfExp(Box<PE>, Box<PE>, Box<PE>),
    Lambda(Vec<String>, Box<PE>),
    Tuple(Vec<PE>),
    List(Vec<PE>),
    Dict(Vec<(PE, PE)>),
    Await(Box<PE>),
    /// verbatim text (treated as an atom)
    Raw(String),
}

#[derive(Clone, Debug, PartialEq)]
pub enum PPat {
    Wild,
    Capture(String),
    Value(PE),
    Class(String, Vec<PPat>, Vec<(String, PPat)>),
    Seq(Vec<PPat>),
    Star(Option<String>),
    Tuple(Vec<PPat>),
    Or(Vec<PPat>),
    As(Box<PPat>, String),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Case {
    pub pat: PPat,
    pub guard: Option<PE>,
    pub body: Vec<PS>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum PS {
    Expr(PE),
    Assign(PE, PE),
    Return(Option<PE>),
    If(Vec<(PE, Vec<PS>)>, Option<Vec<PS>>),
    While(PE, Vec<PS>),
    For(PE, PE, Vec<PS>),
    Match(PE, Vec<Case>),
    /// `ret`: the return annotation (`--native`)
    Def { name: String, params: Vec<String>, body: Vec<PS>, is_async: bool, ret: Option<String> },
    Try(Vec<PS>, Vec<(String, Option<String>, Vec<PS>)>),
    Raise(PE),
    Pass,
    Continue,
    Break,
    Global(Vec<String>),
    Nonlocal(Vec<String>),
    /// verbatim lines
    Raw(String),
}

pub fn name(s: &str) -> PE {
    PE::Name(s.to_string())
}
pub fn call(f: PE, args: Vec<PE>) -> PE {
    PE::Call(Box::new(f), args, Vec::new())
}
pub fn call_n(f: &str, args: Vec<PE>) -> PE {
    PE::Call(Box::new(name(f)), args, Vec::new())
}
pub fn attr(b: PE, a: &str) -> PE {
    PE::Attr(Box::new(b), a.to_string())
}

pub fn escape(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c => out.push(c),
        }
    }
    out
}

fn prec(e: &PE) -> u8 {
    match e {
        PE::Lambda(..) => 0,
        PE::IfExp(..) => 1,
        PE::Or(..) => 2,
        PE::And(..) => 3,
        PE::Not(..) => 4,
        PE::Cmp(..) => 5,
        PE::Bin(_, op, _) => match op {
            Bop::Add | Bop::Sub => 10,
            Bop::Mul | Bop::Div | Bop::FloorDiv | Bop::Mod => 11,
            Bop::Pow => 13,
        },
        PE::Neg(_) => 12,
        PE::Await(_) => 14,
        PE::Int(n) if *n < 0 => 12,
        PE::Float(f) if *f < 0.0 || (*f == 0.0 && f.is_sign_negative()) => 12,
        _ => 16,
    }
}

pub struct Printer {
    /// emission target: 3.11 avoids PEP 701 f-strings
    pub py311: bool,
}

impl Printer {
    pub fn expr(&self, e: &PE) -> String {
        self.ex(e, 0)
    }

    fn wrap(&self, e: &PE, min: u8) -> String {
        let s = self.ex(e, min);
        s
    }

    fn ex(&self, e: &PE, min: u8) -> String {
        let s = self.ex_raw(e);
        if prec(e) < min {
            format!("({})", s)
        } else {
            s
        }
    }

    fn ex_raw(&self, e: &PE) -> String {
        match e {
            PE::Name(n) => n.clone(),
            PE::Int(n) => n.to_string(),
            PE::Float(f) => fmt_float(*f),
            PE::Str(s) => format!("\"{}\"", escape(s)),
            PE::Bool(b) => if *b { "True".into() } else { "False".into() },
            PE::NoneV => "None".into(),
            PE::Raw(s) => s.clone(),
            PE::FStr(parts) => self.fstr(parts),
            PE::Call(f, args, kws) => {
                let mut v: Vec<String> = args.iter().map(|a| self.ex(a, 0)).collect();
                for (k, a) in kws {
                    v.push(format!("{}={}", k, self.ex(a, 0)));
                }
                format!("{}({})", self.ex(f, 15), v.join(", "))
            }
            PE::Attr(b, a) => format!("{}.{}", self.ex(b, 15), a),
            PE::Index(b, i) => format!("{}[{}]", self.ex(b, 15), self.ex(i, 0)),
            PE::Bin(l, op, r) => {
                let (ops, p) = match op {
                    Bop::Add => ("+", 10),
                    Bop::Sub => ("-", 10),
                    Bop::Mul => ("*", 11),
                    Bop::Div => ("/", 11),
                    Bop::FloorDiv => ("//", 11),
                    Bop::Mod => ("%", 11),
                    Bop::Pow => ("**", 13),
                };
                if *op == Bop::Pow {
                    format!("{} ** {}", self.ex(l, 14), self.ex(r, 12))
                } else {
                    format!("{} {} {}", self.ex(l, p), ops, self.ex(r, p + 1))
                }
            }
            PE::Neg(x) => format!("-{}", self.ex(x, 12)),
            PE::Not(x) => format!("not {}", self.ex(x, 4)),
            PE::And(l, r) => format!("{} and {}", self.ex(l, 3), self.ex(r, 4)),
            PE::Or(l, r) => format!("{} or {}", self.ex(l, 2), self.ex(r, 3)),
            PE::Cmp(first, rest) => {
                let mut s = self.ex(first, 6);
                for (op, x) in rest {
                    let o = match op {
                        Cop::Eq => "==",
                        Cop::Ne => "!=",
                        Cop::Lt => "<",
                        Cop::Le => "<=",
                        Cop::Gt => ">",
                        Cop::Ge => ">=",
                        Cop::In => "in",
                        Cop::NotIn => "not in",
                        Cop::Is => "is",
                        Cop::IsNot => "is not",
                    };
                    s.push_str(&format!(" {} {}", o, self.ex(x, 6)));
                }
                s
            }
            PE::IfExp(c, a, b) => format!("{} if {} else {}", self.ex(a, 2), self.ex(c, 2), self.ex(b, 1)),
            PE::Lambda(ps, body) => {
                let b = match **body {
                    PE::IfExp(..) => format!("({})", self.ex(body, 0)),
                    _ => self.ex(body, 0),
                };
                if ps.is_empty() {
                    format!("lambda: {}", b)
                } else {
                    format!("lambda {}: {}", ps.join(", "), b)
                }
            }
            PE::Tuple(xs) => {
                if xs.len() == 1 {
                    format!("({},)", self.ex(&xs[0], 0))
                } else {
                    let v: Vec<String> = xs.iter().map(|x| self.ex(x, 0)).collect();
                    format!("({})", v.join(", "))
                }
            }
            PE::List(xs) => {
                let v: Vec<String> = xs.iter().map(|x| self.ex(x, 0)).collect();
                format!("[{}]", v.join(", "))
            }
            PE::Dict(kvs) => {
                let v: Vec<String> = kvs.iter().map(|(k, x)| format!("{}: {}", self.ex(k, 0), self.ex(x, 0))).collect();
                format!("{{{}}}", v.join(", "))
            }
            PE::Await(x) => format!("await {}", self.ex(x, 15)),
        }
    }

    fn fstr(&self, parts: &[FsPart]) -> String {
        // before PEP 701 an f-string cannot hold its own quote or a
        // backslash in a hole: such strings become `str.format` calls
        if self.py311 {
            let holes: Vec<String> = parts
                .iter()
                .filter_map(|p| match p {
                    FsPart::Expr(e) => Some(self.ex(e, 0)),
                    _ => None,
                })
                .collect();
            if holes.iter().any(|h| h.contains('"') || h.contains('\\')) {
                let mut s = String::from("\"");
                for p in parts {
                    match p {
                        FsPart::Lit(t) => s.push_str(&escape(t).replace('{', "{{").replace('}', "}}")),
                        FsPart::Expr(_) => s.push_str("{}"),
                    }
                }
                s.push_str("\".format(");
                s.push_str(&holes.join(", "));
                s.push(')');
                return s;
            }
        }
        let mut s = String::from("f\"");
        for p in parts {
            match p {
                FsPart::Lit(t) => s.push_str(&escape(t).replace('{', "{{").replace('}', "}}")),
                FsPart::Expr(e) => {
                    s.push('{');
                    let inner = self.ex(e, 0);
                    // a leading `{` would read as an escaped brace
                    if inner.starts_with('{') {
                        s.push(' ');
                    }
                    s.push_str(&inner);
                    s.push('}');
                }
            }
        }
        s.push('"');
        s
    }

    pub fn pat(&self, p: &PPat) -> String {
        match p {
            PPat::Wild => "_".into(),
            PPat::Capture(n) => n.clone(),
            PPat::Value(e) => self.ex(e, 0),
            PPat::Class(n, args, kws) => {
                let mut v: Vec<String> = args.iter().map(|a| self.pat(a)).collect();
                for (k, a) in kws {
                    v.push(format!("{}={}", k, self.pat(a)));
                }
                format!("{}({})", n, v.join(", "))
            }
            PPat::Seq(xs) => {
                let v: Vec<String> = xs.iter().map(|a| self.pat(a)).collect();
                format!("[{}]", v.join(", "))
            }
            PPat::Star(n) => match n {
                Some(n) => format!("*{}", n),
                None => "*_".into(),
            },
            PPat::Tuple(xs) => {
                let v: Vec<String> = xs.iter().map(|a| self.pat(a)).collect();
                format!("({})", v.join(", "))
            }
            PPat::Or(xs) => {
                let v: Vec<String> = xs.iter().map(|a| self.pat(a)).collect();
                v.join(" | ")
            }
            PPat::As(x, n) => format!("{} as {}", self.pat(x), n),
        }
    }

    pub fn stmts(&self, ss: &[PS], indent: usize, out: &mut String) {
        for s in ss {
            self.stmt(s, indent, out);
        }
    }

    fn line(&self, indent: usize, text: &str, out: &mut String) {
        for _ in 0..indent {
            out.push_str("    ");
        }
        out.push_str(text);
        out.push('\n');
    }

    fn block(&self, body: &[PS], indent: usize, out: &mut String) {
        if body.is_empty() {
            self.line(indent, "pass", out);
        } else {
            self.stmts(body, indent, out);
        }
    }

    pub fn stmt(&self, s: &PS, indent: usize, out: &mut String) {
        match s {
            PS::Expr(e) => self.line(indent, &self.ex(e, 0), out),
            PS::Assign(t, e) => {
                let target = match t {
                    PE::Tuple(xs) => xs.iter().map(|x| self.ex(x, 0)).collect::<Vec<_>>().join(", "),
                    other => self.ex(other, 0),
                };
                self.line(indent, &format!("{} = {}", target, self.ex(e, 0)), out)
            }
            PS::Return(e) => match e {
                Some(e) => self.line(indent, &format!("return {}", self.ex(e, 0)), out),
                None => self.line(indent, "return", out),
            },
            PS::If(arms, els) => {
                for (i, (c, body)) in arms.iter().enumerate() {
                    let kw = if i == 0 { "if" } else { "elif" };
                    self.line(indent, &format!("{} {}:", kw, self.ex(c, 0)), out);
                    self.block(body, indent + 1, out);
                }
                if let Some(e) = els {
                    self.line(indent, "else:", out);
                    self.block(e, indent + 1, out);
                }
            }
            PS::While(c, body) => {
                self.line(indent, &format!("while {}:", self.ex(c, 0)), out);
                self.block(body, indent + 1, out);
            }
            PS::For(t, it, body) => {
                let target = match t {
                    PE::Tuple(xs) => xs.iter().map(|x| self.ex(x, 0)).collect::<Vec<_>>().join(", "),
                    other => self.ex(other, 0),
                };
                self.line(indent, &format!("for {} in {}:", target, self.ex(it, 0)), out);
                self.block(body, indent + 1, out);
            }
            PS::Match(subj, cases) => {
                self.line(indent, &format!("match {}:", self.ex(subj, 0)), out);
                for c in cases {
                    let g = match &c.guard {
                        Some(g) => format!(" if {}", self.ex(g, 0)),
                        None => String::new(),
                    };
                    self.line(indent + 1, &format!("case {}{}:", self.pat(&c.pat), g), out);
                    self.block(&c.body, indent + 2, out);
                }
            }
            PS::Def { name, params, body, is_async, ret } => {
                let kw = if *is_async { "async def" } else { "def" };
                // (the return annotation carries its own ` -> `)
                let ret = ret.clone().unwrap_or_default();
                self.line(indent, &format!("{} {}({}){}:", kw, name, params.join(", "), ret), out);
                self.block(body, indent + 1, out);
            }
            PS::Try(body, handlers) => {
                self.line(indent, "try:", out);
                self.block(body, indent + 1, out);
                for (exc, as_, hb) in handlers {
                    match as_ {
                        Some(n) => self.line(indent, &format!("except {} as {}:", exc, n), out),
                        None => self.line(indent, &format!("except {}:", exc), out),
                    }
                    self.block(hb, indent + 1, out);
                }
            }
            PS::Raise(e) => self.line(indent, &format!("raise {}", self.ex(e, 0)), out),
            PS::Pass => self.line(indent, "pass", out),
            PS::Continue => self.line(indent, "continue", out),
            PS::Break => self.line(indent, "break", out),
            PS::Global(ns) => self.line(indent, &format!("global {}", ns.join(", ")), out),
            PS::Nonlocal(ns) => self.line(indent, &format!("nonlocal {}", ns.join(", ")), out),
            PS::Raw(text) => {
                for l in text.split('\n') {
                    if l.is_empty() {
                        continue;
                    }
                    self.line(indent, l, out);
                }
            }
        }
    }
}

pub fn fmt_float(f: f64) -> String {
    let s = format!("{:?}", f);
    s
}

#[allow(dead_code)]
fn unused(p: &Printer) {
    let _ = p.wrap(&PE::NoneV, 0);
}
