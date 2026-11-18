// Minimal TOML reader for yamark.toml.

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Str(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    Array(Vec<Value>),
    Table(Vec<(String, Value)>),
}

impl Value {
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::Str(_) => "string",
            Value::Int(_) => "integer",
            Value::Float(_) => "float",
            Value::Bool(_) => "boolean",
            Value::Array(_) => "array",
            Value::Table(_) => "table",
        }
    }
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Table(t) => t.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }
}

#[derive(Debug)]
pub struct TomlError {
    pub line: usize,
    pub col: usize,
    pub msg: String,
    pub span: usize,
}

struct P<'a> {
    s: &'a [char],
    i: usize,
}

type R<T> = Result<T, TomlError>;

impl<'a> P<'a> {
    fn pos(&self) -> (usize, usize) {
        let mut line = 1;
        let mut col = 1;
        for &c in &self.s[..self.i.min(self.s.len())] {
            if c == '\n' {
                line += 1;
                col = 1;
            } else {
                col += 1;
            }
        }
        (line, col)
    }
    fn err<T>(&self, msg: &str) -> R<T> {
        let (line, col) = self.pos();
        Err(TomlError { line, col, msg: msg.to_string(), span: 1 })
    }
    fn peek(&self) -> Option<char> {
        self.s.get(self.i).copied()
    }
    fn ws(&mut self) {
        while let Some(c) = self.peek() {
            if c == ' ' || c == '\t' {
                self.i += 1;
            } else {
                break;
            }
        }
    }
    fn ws_nl(&mut self) {
        loop {
            self.ws();
            match self.peek() {
                Some('\n') | Some('\r') => self.i += 1,
                Some('#') => {
                    while let Some(c) = self.peek() {
                        if c == '\n' {
                            break;
                        }
                        self.i += 1;
                    }
                }
                _ => break,
            }
        }
    }
    fn line_end(&mut self) -> R<()> {
        self.ws();
        match self.peek() {
            None => Ok(()),
            Some('\n') => {
                self.i += 1;
                Ok(())
            }
            Some('\r') => {
                self.i += 1;
                if self.peek() == Some('\n') {
                    self.i += 1;
                }
                Ok(())
            }
            Some('#') => {
                while let Some(c) = self.peek() {
                    if c == '\n' {
                        break;
                    }
                    self.i += 1;
                }
                Ok(())
            }
            _ => self.err("expected newline, `#`"),
        }
    }
    fn key_part(&mut self) -> R<String> {
        match self.peek() {
            Some('"') => self.basic_string(),
            Some('\'') => self.literal_string(),
            Some(c) if c.is_ascii_alphanumeric() || c == '_' || c == '-' => {
                let s = self.i;
                while let Some(c) = self.peek() {
                    if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
                        self.i += 1;
                    } else {
                        break;
                    }
                }
                Ok(self.s[s..self.i].iter().collect())
            }
            _ => self.err("invalid key"),
        }
    }
    fn dotted_key(&mut self) -> R<Vec<String>> {
        let mut parts = vec![self.key_part()?];
        loop {
            self.ws();
            if self.peek() == Some('.') {
                self.i += 1;
                self.ws();
                parts.push(self.key_part()?);
            } else {
                break;
            }
        }
        Ok(parts)
    }
    fn basic_string(&mut self) -> R<String> {
        self.i += 1;
        let mut out = String::new();
        loop {
            match self.peek() {
                None | Some('\n') => return self.err("invalid basic string"),
                Some('"') => {
                    self.i += 1;
                    return Ok(out);
                }
                Some('\\') => {
                    self.i += 1;
                    let e = self.peek();
                    self.i += 1;
                    match e {
                        Some('n') => out.push('\n'),
                        Some('t') => out.push('\t'),
                        Some('r') => out.push('\r'),
                        Some('"') => out.push('"'),
                        Some('\\') => out.push('\\'),
                        Some('u') | Some('U') => {
                            let n = if e == Some('u') { 4 } else { 8 };
                            let h: String = self.s[self.i..(self.i + n).min(self.s.len())].iter().collect();
                            self.i += n;
                            match u32::from_str_radix(&h, 16).ok().and_then(char::from_u32) {
                                Some(c) => out.push(c),
                                None => return self.err("invalid unicode escape"),
                            }
                        }
                        _ => return self.err("invalid escape sequence"),
                    }
                }
                Some(c) => {
                    out.push(c);
                    self.i += 1;
                }
            }
        }
    }
    fn literal_string(&mut self) -> R<String> {
        self.i += 1;
        let s = self.i;
        loop {
            match self.peek() {
                None | Some('\n') => return self.err("invalid literal string"),
                Some('\'') => {
                    let v: String = self.s[s..self.i].iter().collect();
                    self.i += 1;
                    return Ok(v);
                }
                _ => self.i += 1,
            }
        }
    }
    fn value(&mut self) -> R<Value> {
        match self.peek() {
            Some('"') => {
                if self.s.get(self.i + 1) == Some(&'"') && self.s.get(self.i + 2) == Some(&'"') {
                    self.i += 3;
                    if self.peek() == Some('\n') {
                        self.i += 1;
                    }
                    let s = self.i;
                    while self.i + 2 < self.s.len() + 0 && !(self.s[self.i] == '"' && self.s[self.i + 1] == '"' && self.s[self.i + 2] == '"') {
                        self.i += 1;
                    }
                    let v: String = self.s[s..self.i.min(self.s.len())].iter().collect();
                    self.i += 3;
                    return Ok(Value::Str(v));
                }
                Ok(Value::Str(self.basic_string()?))
            }
            Some('\'') => Ok(Value::Str(self.literal_string()?)),
            Some('[') => {
                self.i += 1;
                let mut items = Vec::new();
                loop {
                    self.ws_nl();
                    if self.peek() == Some(']') {
                        self.i += 1;
                        break;
                    }
                    items.push(self.value()?);
                    self.ws_nl();
                    match self.peek() {
                        Some(',') => self.i += 1,
                        Some(']') => {
                            self.i += 1;
                            break;
                        }
                        _ => return self.err("invalid array"),
                    }
                }
                Ok(Value::Array(items))
            }
            Some('{') => {
                self.i += 1;
                let mut t: Vec<(String, Value)> = Vec::new();
                self.ws();
                if self.peek() == Some('}') {
                    self.i += 1;
                    return Ok(Value::Table(t));
                }
                loop {
                    self.ws();
                    let k = self.dotted_key()?;
                    self.ws();
                    if self.peek() != Some('=') {
                        return self.err("expected `=`");
                    }
                    self.i += 1;
                    self.ws();
                    let v = self.value()?;
                    insert(&mut t, &k, v).map_err(|m| {
                        let (line, col) = self.pos();
                        TomlError { line, col, msg: m, span: 1 }
                    })?;
                    self.ws();
                    match self.peek() {
                        Some(',') => self.i += 1,
                        Some('}') => {
                            self.i += 1;
                            break;
                        }
                        _ => return self.err("invalid inline table"),
                    }
                }
                Ok(Value::Table(t))
            }
            Some(c) if c == 't' || c == 'f' => {
                let s = self.i;
                while let Some(c) = self.peek() {
                    if c.is_ascii_alphabetic() {
                        self.i += 1;
                    } else {
                        break;
                    }
                }
                let w: String = self.s[s..self.i].iter().collect();
                match w.as_str() {
                    "true" => Ok(Value::Bool(true)),
                    "false" => Ok(Value::Bool(false)),
                    _ => {
                        self.i = s;
                        self.err("invalid string\\nexpected `\\\"`, `'`")
                    }
                }
            }
            Some(c) if c.is_ascii_digit() || c == '-' || c == '+' => {
                let s = self.i;
                while let Some(c) = self.peek() {
                    if c.is_ascii_alphanumeric() || matches!(c, '-' | '+' | '.' | '_') {
                        self.i += 1;
                    } else {
                        break;
                    }
                }
                let w: String = self.s[s..self.i].iter().filter(|c| **c != '_').collect();
                if let Ok(n) = w.parse::<i64>() {
                    return Ok(Value::Int(n));
                }
                if let Ok(f) = w.parse::<f64>() {
                    return Ok(Value::Float(f));
                }
                self.i = s;
                self.err("invalid number")
            }
            Some(c) if c.is_alphabetic() => {
                let s = self.i;
                let mut j = self.i;
                while j < self.s.len() && (self.s[j].is_alphanumeric() || matches!(self.s[j], '_' | '-' | ':' | '.')) {
                    j += 1;
                }
                let (line, col) = self.pos();
                let _ = s;
                Err(TomlError { line, col, msg: "string values must be quoted, expected literal string".into(), span: j - self.i })
            }
            _ => self.err("invalid string\\nexpected `\\\"`, `'`"),
        }
    }
}

fn insert(t: &mut Vec<(String, Value)>, key: &[String], v: Value) -> Result<(), String> {
    if key.len() == 1 {
        if t.iter().any(|(k, _)| k == &key[0]) {
            return Err(format!("duplicate key `{}`", key[0]));
        }
        t.push((key[0].clone(), v));
        return Ok(());
    }
    let pos = t.iter().position(|(k, _)| k == &key[0]);
    let idx = match pos {
        Some(i) => i,
        None => {
            t.push((key[0].clone(), Value::Table(Vec::new())));
            t.len() - 1
        }
    };
    match &mut t[idx].1 {
        Value::Table(inner) => insert(inner, &key[1..], v),
        _ => Err(format!("duplicate key `{}`", key[0])),
    }
}

fn table_at<'a>(root: &'a mut Vec<(String, Value)>, path: &[String]) -> Result<&'a mut Vec<(String, Value)>, String> {
    if path.is_empty() {
        return Ok(root);
    }
    let pos = root.iter().position(|(k, _)| k == &path[0]);
    let idx = match pos {
        Some(i) => i,
        None => {
            root.push((path[0].clone(), Value::Table(Vec::new())));
            root.len() - 1
        }
    };
    match &mut root[idx].1 {
        Value::Table(inner) => table_at(inner, &path[1..]),
        _ => Err(format!("duplicate key `{}`", path[0])),
    }
}

pub fn parse(text: &str) -> Result<Value, TomlError> {
    let chars: Vec<char> = text.chars().collect();
    let mut p = P { s: &chars, i: 0 };
    let mut root: Vec<(String, Value)> = Vec::new();
    let mut current: Vec<String> = Vec::new();
    loop {
        p.ws_nl();
        if p.peek().is_none() {
            break;
        }
        if p.peek() == Some('[') {
            p.i += 1;
            if p.peek() == Some('[') {
                return p.err("arrays of tables are not supported");
            }
            p.ws();
            let path = p.dotted_key()?;
            p.ws();
            if p.peek() != Some(']') {
                if p.peek().is_none() || p.peek() == Some('\n') {
                    return p.err("unclosed table, expected `]`");
                }
                return p.err("invalid table header\\nexpected `.`, `]`");
            }
            p.i += 1;
            p.line_end()?;
            if let Err(m) = table_at(&mut root, &path) {
                return p.err(&m);
            }
            current = path;
            continue;
        }
        let key = p.dotted_key()?;
        p.ws();
        if p.peek() != Some('=') {
            return p.err("key with no value, expected `=`");
        }
        p.i += 1;
        p.ws();
        let v = p.value()?;
        let tbl = match table_at(&mut root, &current) {
            Ok(t) => t,
            Err(m) => return p.err(&m),
        };
        if let Err(m) = insert(tbl, &key, v) {
            return p.err(&m);
        }
        p.line_end()?;
    }
    Ok(Value::Table(root))
}
