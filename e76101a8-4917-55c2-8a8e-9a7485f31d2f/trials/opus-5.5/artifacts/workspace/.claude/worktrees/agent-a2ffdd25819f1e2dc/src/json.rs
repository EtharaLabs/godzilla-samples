//! A JSON value with insertion-ordered objects, a parser whose errors read as
//! serde_json's do, and writers (compact, pretty, key-sorted) that format numbers
//! the way serde_json does (integers as integers, floats in shortest form).

use std::fmt::Write as _;

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Num(Num),
    Str(String),
    Arr(Vec<Value>),
    Obj(Map),
}

impl Default for Value {
    fn default() -> Value {
        Value::Null
    }
}

#[derive(Clone, Copy, Debug)]
pub enum Num {
    U(u64),
    I(i64),
    F(f64),
}

impl PartialEq for Num {
    fn eq(&self, other: &Num) -> bool {
        match (self, other) {
            (Num::U(a), Num::U(b)) => a == b,
            (Num::I(a), Num::I(b)) => a == b,
            (Num::F(a), Num::F(b)) => a == b,
            _ => false,
        }
    }
}

impl Num {
    pub fn as_f64(&self) -> f64 {
        match *self {
            Num::U(u) => u as f64,
            Num::I(i) => i as f64,
            Num::F(f) => f,
        }
    }
}

/// An object: keys in insertion order.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Map {
    pub items: Vec<(String, Value)>,
}

impl Map {
    pub fn new() -> Map {
        Map { items: Vec::new() }
    }
    pub fn get(&self, k: &str) -> Option<&Value> {
        self.items.iter().find(|(kk, _)| kk == k).map(|(_, v)| v)
    }
    pub fn get_mut(&mut self, k: &str) -> Option<&mut Value> {
        self.items.iter_mut().find(|(kk, _)| kk == k).map(|(_, v)| v)
    }
    pub fn contains(&self, k: &str) -> bool {
        self.items.iter().any(|(kk, _)| kk == k)
    }
    /// Sets a key, keeping its place if it is there, else appending it.
    pub fn insert(&mut self, k: &str, v: Value) {
        if let Some(slot) = self.get_mut(k) {
            *slot = v;
        } else {
            self.items.push((k.to_string(), v));
        }
    }
    /// Sets a key in sorted (byte) order, as a BTreeMap would hold it.
    pub fn insert_sorted(&mut self, k: &str, v: Value) {
        match self.items.binary_search_by(|(kk, _)| kk.as_str().cmp(k)) {
            Ok(i) => self.items[i].1 = v,
            Err(i) => self.items.insert(i, (k.to_string(), v)),
        }
    }
    pub fn remove(&mut self, k: &str) -> Option<Value> {
        let i = self.items.iter().position(|(kk, _)| kk == k)?;
        Some(self.items.remove(i).1)
    }
    pub fn len(&self) -> usize {
        self.items.len()
    }
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
    pub fn keys(&self) -> impl Iterator<Item = &String> {
        self.items.iter().map(|(k, _)| k)
    }
    pub fn iter(&self) -> impl Iterator<Item = (&String, &Value)> {
        self.items.iter().map(|(k, v)| (k, v))
    }
    pub fn sort(&mut self) {
        self.items.sort_by(|a, b| a.0.cmp(&b.0));
    }
}

impl Value {
    pub fn obj() -> Value {
        Value::Obj(Map::new())
    }
    pub fn f(x: f64) -> Value {
        Value::Num(Num::F(x))
    }
    pub fn u(x: u64) -> Value {
        Value::Num(Num::U(x))
    }
    pub fn i(x: i64) -> Value {
        if x >= 0 {
            Value::Num(Num::U(x as u64))
        } else {
            Value::Num(Num::I(x))
        }
    }
    pub fn s(x: &str) -> Value {
        Value::Str(x.to_string())
    }
    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Num(n) => Some(n.as_f64()),
            _ => None,
        }
    }
    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Value::Num(Num::U(u)) if *u <= i64::MAX as u64 => Some(*u as i64),
            Value::Num(Num::I(i)) => Some(*i),
            _ => None,
        }
    }
    pub fn as_u64(&self) -> Option<u64> {
        match self {
            Value::Num(Num::U(u)) => Some(*u),
            _ => None,
        }
    }
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Value::Bool(b) => Some(*b),
            _ => None,
        }
    }
    pub fn as_arr(&self) -> Option<&Vec<Value>> {
        match self {
            Value::Arr(a) => Some(a),
            _ => None,
        }
    }
    pub fn as_arr_mut(&mut self) -> Option<&mut Vec<Value>> {
        match self {
            Value::Arr(a) => Some(a),
            _ => None,
        }
    }
    pub fn as_obj(&self) -> Option<&Map> {
        match self {
            Value::Obj(m) => Some(m),
            _ => None,
        }
    }
    pub fn as_obj_mut(&mut self) -> Option<&mut Map> {
        match self {
            Value::Obj(m) => Some(m),
            _ => None,
        }
    }
    pub fn get(&self, k: &str) -> Option<&Value> {
        match self {
            Value::Obj(m) => m.get(k),
            _ => None,
        }
    }
    pub fn get_mut(&mut self, k: &str) -> Option<&mut Value> {
        match self {
            Value::Obj(m) => m.get_mut(k),
            _ => None,
        }
    }
    /// Sets a key of an object (appending a new key at the end).
    pub fn set(&mut self, k: &str, v: Value) {
        if let Value::Obj(m) = self {
            m.insert(k, v);
        }
    }
    pub fn remove(&mut self, k: &str) -> Option<Value> {
        match self {
            Value::Obj(m) => m.remove(k),
            _ => None,
        }
    }
    /// The kind of value, as serde names it in "invalid type" errors.
    pub fn kind_name(&self) -> String {
        match self {
            Value::Null => "null".into(),
            Value::Bool(b) => format!("boolean `{}`", b),
            Value::Num(Num::U(u)) => format!("integer `{}`", u),
            Value::Num(Num::I(i)) => format!("integer `{}`", i),
            Value::Num(Num::F(f)) => format!("floating point `{}`", fmt_f64_display(*f)),
            Value::Str(s) => format!("string {:?}", s),
            Value::Arr(_) => "sequence".into(),
            Value::Obj(_) => "map".into(),
        }
    }
    /// Recursively sorts every object's keys, as serde_json::Value holds them.
    pub fn sorted(mut self) -> Value {
        self.sort_keys();
        self
    }
    pub fn sort_keys(&mut self) {
        match self {
            Value::Arr(a) => a.iter_mut().for_each(|v| v.sort_keys()),
            Value::Obj(m) => {
                m.items.iter_mut().for_each(|(_, v)| v.sort_keys());
                // stable: a duplicate key keeps the last value as a BTreeMap would
                m.items.sort_by(|a, b| a.0.cmp(&b.0));
                let mut out: Vec<(String, Value)> = Vec::with_capacity(m.items.len());
                for (k, v) in m.items.drain(..) {
                    if let Some(last) = out.last_mut() {
                        if last.0 == k {
                            last.1 = v;
                            continue;
                        }
                    }
                    out.push((k, v));
                }
                m.items = out;
            }
            _ => {}
        }
    }
    pub fn to_compact(&self) -> String {
        let mut s = String::new();
        write_compact(self, &mut s);
        s
    }
    pub fn to_pretty(&self) -> String {
        let mut s = String::new();
        write_pretty(self, &mut s, 0);
        s
    }
}

impl From<f64> for Value {
    fn from(x: f64) -> Value {
        Value::f(x)
    }
}
impl From<u64> for Value {
    fn from(x: u64) -> Value {
        Value::u(x)
    }
}
impl From<i64> for Value {
    fn from(x: i64) -> Value {
        Value::i(x)
    }
}
impl From<usize> for Value {
    fn from(x: usize) -> Value {
        Value::u(x as u64)
    }
}
impl From<u32> for Value {
    fn from(x: u32) -> Value {
        Value::u(x as u64)
    }
}
impl From<i32> for Value {
    fn from(x: i32) -> Value {
        Value::i(x as i64)
    }
}
impl From<bool> for Value {
    fn from(x: bool) -> Value {
        Value::Bool(x)
    }
}
impl From<&str> for Value {
    fn from(x: &str) -> Value {
        Value::Str(x.to_string())
    }
}
impl From<String> for Value {
    fn from(x: String) -> Value {
        Value::Str(x)
    }
}
impl From<&String> for Value {
    fn from(x: &String) -> Value {
        Value::Str(x.clone())
    }
}
impl<T: Into<Value>> From<Vec<T>> for Value {
    fn from(x: Vec<T>) -> Value {
        Value::Arr(x.into_iter().map(|v| v.into()).collect())
    }
}
impl<T: Into<Value>> From<Option<T>> for Value {
    fn from(x: Option<T>) -> Value {
        match x {
            Some(v) => v.into(),
            None => Value::Null,
        }
    }
}
impl From<Map> for Value {
    fn from(m: Map) -> Value {
        Value::Obj(m)
    }
}
impl From<[f64; 2]> for Value {
    fn from(p: [f64; 2]) -> Value {
        Value::Arr(vec![Value::f(p[0]), Value::f(p[1])])
    }
}
impl From<[f64; 3]> for Value {
    fn from(p: [f64; 3]) -> Value {
        Value::Arr(vec![Value::f(p[0]), Value::f(p[1]), Value::f(p[2])])
    }
}

/// Builds an object from pairs, keeping their order.
#[macro_export]
macro_rules! jobj {
    () => { $crate::json::Value::Obj($crate::json::Map::new()) };
    ($($k:expr => $v:expr),+ $(,)?) => {{
        let mut m = $crate::json::Map::new();
        $( m.insert($k, $crate::json::Value::from($v)); )+
        $crate::json::Value::Obj(m)
    }};
}

// ---------------------------------------------------------------- numbers

/// Shortest round-trip digits and the decimal exponent: value = 0.d1d2d3... * 10^kk
fn shortest_digits(x: f64) -> (String, i32) {
    // `{:e}` gives the shortest digits that round-trip, as ryu does.
    let s = format!("{:e}", x.abs());
    let (mant, exp) = s.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let mut digits: String = mant.chars().filter(|c| *c != '.').collect();
    // Where the value lies exactly halfway between two shortest candidates (an f32 widened to
    // f64 often does), ryu takes the even one and Rust's `{:e}` the upper: take the even one.
    if digits.len() >= 16 && (digits.as_bytes()[digits.len() - 1] - b'0') % 2 == 1 {
        let mut alt = digits.clone().into_bytes();
        *alt.last_mut().unwrap() -= 1;
        let alt = String::from_utf8(alt).unwrap();
        let exact = format!("{:.*e}", digits.len() + 60, x.abs());
        if let Some((em, ee)) = exact.split_once('e') {
            if ee.parse::<i32>().ok() == Some(exp) {
                let ed: String = em.chars().filter(|c| *c != '.').collect();
                let half = format!("{}5", alt);
                if ed.starts_with(&half) && ed[half.len()..].bytes().all(|b| b == b'0') {
                    let back: Option<f64> = format!("{}.{}e{}", &alt[..1], &alt[1..], exp).parse().ok();
                    if back == Some(x.abs()) {
                        digits = alt;
                    }
                }
            }
        }
    }
    // mant = d.ddd, so value = d.ddd * 10^exp = 0.dddd * 10^(exp+1)
    (digits, exp + 1)
}

/// Formats an f64 as serde_json (ryu) does.
pub fn fmt_f64(x: f64) -> String {
    if !x.is_finite() {
        return "null".to_string();
    }
    let mut out = String::new();
    if x.is_sign_negative() {
        out.push('-');
    }
    if x == 0.0 {
        out.push_str("0.0");
        return out;
    }
    let (digits, kk) = shortest_digits(x);
    let length = digits.len() as i32;
    let k = kk - length;
    if 0 <= k && kk <= 16 {
        out.push_str(&digits);
        for _ in length..kk {
            out.push('0');
        }
        out.push_str(".0");
    } else if 0 < kk && kk <= 16 {
        out.push_str(&digits[..kk as usize]);
        out.push('.');
        out.push_str(&digits[kk as usize..]);
    } else if -5 < kk && kk <= 0 {
        out.push_str("0.");
        for _ in 0..(-kk) {
            out.push('0');
        }
        out.push_str(&digits);
    } else {
        out.push_str(&digits[..1]);
        if length > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        if kk - 1 > 0 {
            out.push('+');
        }
        let _ = write!(out, "{}", kk - 1);
    }
    out
}

/// How serde's "invalid type" message shows a float (Rust's Display, with a `.0` for integers).
pub fn fmt_f64_display(x: f64) -> String {
    if x.is_finite() && x == x.trunc() && x.abs() < 1e16 {
        format!("{}.0", x as i64)
    } else {
        format!("{}", x)
    }
}

fn write_num(n: &Num, out: &mut String) {
    match n {
        Num::U(u) => {
            let _ = write!(out, "{}", u);
        }
        Num::I(i) => {
            let _ = write!(out, "{}", i);
        }
        Num::F(f) => out.push_str(&fmt_f64(*f)),
    }
}

pub fn write_str(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

pub fn write_compact(v: &Value, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Num(n) => write_num(n, out),
        Value::Str(s) => write_str(s, out),
        Value::Arr(a) => {
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_compact(x, out);
            }
            out.push(']');
        }
        Value::Obj(m) => {
            out.push('{');
            for (i, (k, x)) in m.items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_str(k, out);
                out.push(':');
                write_compact(x, out);
            }
            out.push('}');
        }
    }
}

fn indent(out: &mut String, n: usize) {
    for _ in 0..n {
        out.push_str("  ");
    }
}

pub fn write_pretty(v: &Value, out: &mut String, level: usize) {
    match v {
        Value::Arr(a) => {
            if a.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                indent(out, level + 1);
                write_pretty(x, out, level + 1);
            }
            out.push('\n');
            indent(out, level);
            out.push(']');
        }
        Value::Obj(m) => {
            if m.items.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (i, (k, x)) in m.items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push('\n');
                indent(out, level + 1);
                write_str(k, out);
                out.push_str(": ");
                write_pretty(x, out, level + 1);
            }
            out.push('\n');
            indent(out, level);
            out.push('}');
        }
        _ => write_compact(v, out),
    }
}

// ---------------------------------------------------------------- parsing

#[derive(Debug, Clone)]
pub struct ParseError {
    pub msg: String,
    pub line: usize,
    pub col: usize,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        if self.line == 0 {
            write!(f, "{}", self.msg)
        } else {
            write!(f, "{} at line {} column {}", self.msg, self.line, self.col)
        }
    }
}

/// 10^e as serde_json's table holds it (each power the literal's own rounding).
fn pow10(e: usize) -> f64 {
    // parsing "1e{e}" gives the nearest double, as a literal in the table would be
    format!("1e{}", e).parse().unwrap()
}

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
    depth: usize,
}

impl<'a> Parser<'a> {
    /// Line and column of the byte before `self.i` (serde_json reports the last byte read).
    fn pos_at(&self, idx: usize) -> (usize, usize) {
        let mut line = 1;
        let mut col = 0;
        for &b in &self.s[..idx.min(self.s.len())] {
            if b == b'\n' {
                line += 1;
                col = 0;
            } else {
                col += 1;
            }
        }
        (line, col)
    }
    fn err(&self, msg: &str) -> ParseError {
        let (line, col) = self.pos_at(self.i);
        ParseError { msg: msg.to_string(), line, col }
    }
    fn peek(&self) -> Option<u8> {
        self.s.get(self.i).copied()
    }
    fn skip_ws(&mut self) {
        while let Some(b) = self.peek() {
            if b == b' ' || b == b'\n' || b == b'\t' || b == b'\r' {
                self.i += 1;
            } else {
                break;
            }
        }
    }
    fn parse_value(&mut self) -> Result<Value, ParseError> {
        self.skip_ws();
        let b = match self.peek() {
            None => return Err(self.err("EOF while parsing a value")),
            Some(b) => b,
        };
        match b {
            b'n' => {
                self.i += 1;
                self.ident(b"ull")?;
                Ok(Value::Null)
            }
            b't' => {
                self.i += 1;
                self.ident(b"rue")?;
                Ok(Value::Bool(true))
            }
            b'f' => {
                self.i += 1;
                self.ident(b"alse")?;
                Ok(Value::Bool(false))
            }
            b'-' | b'0'..=b'9' => self.parse_number(),
            b'"' => {
                self.i += 1;
                Ok(Value::Str(self.parse_string()?))
            }
            b'[' => {
                self.depth += 1;
                if self.depth > 128 {
                    self.i += 1;
                    return Err(self.err("recursion limit exceeded"));
                }
                self.i += 1;
                let mut items = Vec::new();
                self.skip_ws();
                if self.peek() == Some(b']') {
                    self.i += 1;
                    self.depth -= 1;
                    return Ok(Value::Arr(items));
                }
                loop {
                    let v = self.parse_value()?;
                    items.push(v);
                    self.skip_ws();
                    match self.peek() {
                        Some(b',') => {
                            self.i += 1;
                            self.skip_ws();
                            if self.peek() == Some(b']') {
                                self.i += 1;
                                return Err(self.err("trailing comma"));
                            }
                        }
                        Some(b']') => {
                            self.i += 1;
                            break;
                        }
                        None => return Err(self.err("EOF while parsing a list")),
                        Some(_) => {
                            self.i += 1;
                            return Err(self.err("expected `,` or `]`"));
                        }
                    }
                }
                self.depth -= 1;
                Ok(Value::Arr(items))
            }
            b'{' => {
                self.depth += 1;
                if self.depth > 128 {
                    self.i += 1;
                    return Err(self.err("recursion limit exceeded"));
                }
                self.i += 1;
                let mut m = Map::new();
                self.skip_ws();
                if self.peek() == Some(b'}') {
                    self.i += 1;
                    self.depth -= 1;
                    return Ok(Value::Obj(m));
                }
                let mut first = true;
                loop {
                    self.skip_ws();
                    match self.peek() {
                        Some(b'"') => {
                            self.i += 1;
                        }
                        None if first => return Err(self.err("EOF while parsing an object")),
                        None => return Err(self.err("EOF while parsing a value")),
                        Some(_) => {
                            self.i += 1;
                            return Err(self.err("key must be a string"));
                        }
                    }
                    first = false;
                    let k = self.parse_string()?;
                    self.skip_ws();
                    match self.peek() {
                        Some(b':') => self.i += 1,
                        None => return Err(self.err("EOF while parsing an object")),
                        Some(_) => {
                            self.i += 1;
                            return Err(self.err("expected `:`"));
                        }
                    }
                    let v = self.parse_value()?;
                    // a duplicate key keeps the last value, in the first one's place
                    m.insert(&k, v);
                    self.skip_ws();
                    match self.peek() {
                        Some(b',') => {
                            self.i += 1;
                            self.skip_ws();
                            if self.peek() == Some(b'}') {
                                self.i += 1;
                                return Err(self.err("trailing comma"));
                            }
                        }
                        Some(b'}') => {
                            self.i += 1;
                            break;
                        }
                        None => return Err(self.err("EOF while parsing an object")),
                        Some(_) => {
                            self.i += 1;
                            return Err(self.err("expected `,` or `}`"));
                        }
                    }
                }
                self.depth -= 1;
                Ok(Value::Obj(m))
            }
            _ => {
                self.i += 1;
                Err(self.err("expected value"))
            }
        }
    }
    fn ident(&mut self, rest: &[u8]) -> Result<(), ParseError> {
        for &c in rest {
            match self.peek() {
                None => return Err(self.err("EOF while parsing a value")),
                Some(b) if b == c => self.i += 1,
                Some(_) => {
                    self.i += 1;
                    return Err(self.err("expected ident"));
                }
            }
        }
        Ok(())
    }
    fn parse_number(&mut self) -> Result<Value, ParseError> {
        let positive = self.peek() != Some(b'-');
        if !positive {
            self.i += 1;
        }
        let c = match self.peek() {
            None => return Err(self.err("EOF while parsing a value")),
            Some(c) => c,
        };
        self.i += 1;
        let significand: u64;
        match c {
            b'0' => {
                if let Some(b'0'..=b'9') = self.peek() {
                    self.i += 1;
                    return Err(self.err("invalid number"));
                }
                significand = 0;
            }
            b'1'..=b'9' => {
                let mut sig = (c - b'0') as u64;
                loop {
                    match self.peek() {
                        Some(d @ b'0'..=b'9') => {
                            let digit = (d - b'0') as u64;
                            match sig.checked_mul(10).and_then(|x| x.checked_add(digit)) {
                                Some(n) => {
                                    self.i += 1;
                                    sig = n;
                                }
                                None => {
                                    let f = self.parse_long_integer(positive, sig)?;
                                    return Ok(Value::Num(Num::F(f)));
                                }
                            }
                        }
                        _ => break,
                    }
                }
                significand = sig;
            }
            _ => return Err(self.err("invalid number")),
        }
        match self.peek() {
            Some(b'.') => Ok(Value::Num(Num::F(self.parse_decimal(positive, significand, 0)?))),
            Some(b'e') | Some(b'E') => Ok(Value::Num(Num::F(self.parse_exponent(positive, significand, 0)?))),
            _ => {
                if positive {
                    Ok(Value::Num(Num::U(significand)))
                } else {
                    let neg = (significand as i64).wrapping_neg();
                    if neg >= 0 {
                        Ok(Value::Num(Num::F(-(significand as f64))))
                    } else {
                        Ok(Value::Num(Num::I(neg)))
                    }
                }
            }
        }
    }
    fn parse_long_integer(&mut self, positive: bool, significand: u64) -> Result<f64, ParseError> {
        let mut exponent = 0i32;
        loop {
            match self.peek() {
                Some(b'0'..=b'9') => {
                    self.i += 1;
                    exponent += 1;
                }
                Some(b'.') => return self.parse_decimal(positive, significand, exponent),
                Some(b'e') | Some(b'E') => return self.parse_exponent(positive, significand, exponent),
                _ => return self.f64_from_parts(positive, significand, exponent),
            }
        }
    }
    fn parse_decimal(&mut self, positive: bool, mut significand: u64, before: i32) -> Result<f64, ParseError> {
        self.i += 1; // the point
        let mut after = 0i32;
        while let Some(d @ b'0'..=b'9') = self.peek() {
            let digit = (d - b'0') as u64;
            match significand.checked_mul(10).and_then(|x| x.checked_add(digit)) {
                Some(n) => {
                    self.i += 1;
                    significand = n;
                    after -= 1;
                }
                None => {
                    // the digits past what a u64 holds are dropped
                    while let Some(b'0'..=b'9') = self.peek() {
                        self.i += 1;
                    }
                    let exponent = before + after;
                    return match self.peek() {
                        Some(b'e') | Some(b'E') => self.parse_exponent(positive, significand, exponent),
                        _ => self.f64_from_parts(positive, significand, exponent),
                    };
                }
            }
        }
        if after == 0 {
            return match self.peek() {
                Some(_) => {
                    self.i += 1;
                    Err(self.err("invalid number"))
                }
                None => Err(self.err("EOF while parsing a value")),
            };
        }
        let exponent = before + after;
        match self.peek() {
            Some(b'e') | Some(b'E') => self.parse_exponent(positive, significand, exponent),
            _ => self.f64_from_parts(positive, significand, exponent),
        }
    }
    fn parse_exponent(&mut self, positive: bool, significand: u64, starting: i32) -> Result<f64, ParseError> {
        self.i += 1; // the e
        let positive_exp = match self.peek() {
            Some(b'+') => {
                self.i += 1;
                true
            }
            Some(b'-') => {
                self.i += 1;
                false
            }
            _ => true,
        };
        let next = match self.peek() {
            None => return Err(self.err("EOF while parsing a value")),
            Some(b) => b,
        };
        self.i += 1;
        let mut exp = match next {
            b'0'..=b'9' => (next - b'0') as i32,
            _ => return Err(self.err("invalid number")),
        };
        while let Some(d @ b'0'..=b'9') = self.peek() {
            self.i += 1;
            let digit = (d - b'0') as i32;
            match exp.checked_mul(10).and_then(|x| x.checked_add(digit)) {
                Some(n) => exp = n,
                None => {
                    while let Some(b'0'..=b'9') = self.peek() {
                        self.i += 1;
                    }
                    if significand != 0 && positive_exp {
                        return Err(self.err("number out of range"));
                    }
                    return Ok(if positive { 0.0 } else { -0.0 });
                }
            }
        }
        let final_exp = if positive_exp { starting.saturating_add(exp) } else { starting.saturating_sub(exp) };
        self.f64_from_parts(positive, significand, final_exp)
    }
    fn f64_from_parts(&mut self, positive: bool, significand: u64, mut exponent: i32) -> Result<f64, ParseError> {
        let mut f = significand as f64;
        loop {
            let e = exponent.unsigned_abs() as usize;
            if e <= 308 {
                let pow = pow10(e);
                if exponent >= 0 {
                    f *= pow;
                    if f.is_infinite() {
                        return Err(self.err("number out of range"));
                    }
                } else {
                    f /= pow;
                }
                break;
            } else {
                if f == 0.0 {
                    break;
                }
                if exponent >= 0 {
                    return Err(self.err("number out of range"));
                }
                f /= 1e308;
                exponent += 308;
            }
        }
        Ok(if positive { f } else { -f })
    }
    fn hex4(&mut self) -> Result<u16, ParseError> {
        let mut v: u16 = 0;
        for _ in 0..4 {
            let b = match self.peek() {
                None => return Err(self.err("EOF while parsing a string")),
                Some(b) => b,
            };
            self.i += 1;
            let d = match b {
                b'0'..=b'9' => b - b'0',
                b'a'..=b'f' => b - b'a' + 10,
                b'A'..=b'F' => b - b'A' + 10,
                _ => return Err(self.err("invalid escape")),
            };
            v = v * 16 + d as u16;
        }
        Ok(v)
    }
    fn parse_string(&mut self) -> Result<String, ParseError> {
        let mut out: Vec<u8> = Vec::new();
        loop {
            let b = match self.peek() {
                None => return Err(self.err("EOF while parsing a string")),
                Some(b) => b,
            };
            self.i += 1;
            match b {
                b'"' => break,
                b'\\' => {
                    let e = match self.peek() {
                        None => return Err(self.err("EOF while parsing a string")),
                        Some(e) => e,
                    };
                    self.i += 1;
                    match e {
                        b'"' => out.push(b'"'),
                        b'\\' => out.push(b'\\'),
                        b'/' => out.push(b'/'),
                        b'b' => out.push(8),
                        b'f' => out.push(12),
                        b'n' => out.push(b'\n'),
                        b'r' => out.push(b'\r'),
                        b't' => out.push(b'\t'),
                        b'u' => {
                            let c = self.hex4()?;
                            let ch = if (0xD800..0xDC00).contains(&c) {
                                if self.peek() != Some(b'\\') {
                                    if self.peek().is_none() {
                                        return Err(self.err("EOF while parsing a string"));
                                    }
                                    self.i += 1;
                                    return Err(self.err("unexpected end of hex escape"));
                                }
                                self.i += 1;
                                if self.peek() != Some(b'u') {
                                    self.i += 1;
                                    return Err(self.err("unexpected end of hex escape"));
                                }
                                self.i += 1;
                                let c2 = self.hex4()?;
                                if !(0xDC00..0xE000).contains(&c2) {
                                    return Err(self.err("lone leading surrogate in hex escape"));
                                }
                                let n = 0x10000 + (((c as u32) - 0xD800) << 10) + ((c2 as u32) - 0xDC00);
                                char::from_u32(n).unwrap()
                            } else if (0xDC00..0xE000).contains(&c) {
                                return Err(self.err("lone leading surrogate in hex escape"));
                            } else {
                                char::from_u32(c as u32).unwrap()
                            };
                            let mut buf = [0u8; 4];
                            out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
                        }
                        _ => return Err(self.err("invalid escape")),
                    }
                }
                b if b < 0x20 => {
                    return Err(self.err("control character (\\u0000-\\u001F) found while parsing a string"))
                }
                b => out.push(b),
            }
        }
        match String::from_utf8(out) {
            Ok(s) => Ok(s),
            Err(_) => Err(self.err("invalid unicode code point")),
        }
    }
}

/// Parses a whole JSON text.
pub fn parse(text: &str) -> Result<Value, ParseError> {
    parse_bytes(text.as_bytes())
}

pub fn parse_bytes(bytes: &[u8]) -> Result<Value, ParseError> {
    let mut p = Parser { s: bytes, i: 0, depth: 0 };
    let v = p.parse_value()?;
    p.skip_ws();
    if p.i < p.s.len() {
        p.i += 1;
        return Err(p.err("trailing characters"));
    }
    Ok(v)
}

/// Parses the first JSON value of a text and says where it ended (for `id {json} rest`).
pub fn parse_prefix(text: &str) -> Result<(Value, usize), ParseError> {
    let mut p = Parser { s: text.as_bytes(), i: 0, depth: 0 };
    let v = p.parse_value()?;
    Ok((v, p.i))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn floats() {
        assert_eq!(fmt_f64(3000.0), "3000.0");
        assert_eq!(fmt_f64(0.1), "0.1");
        assert_eq!(fmt_f64(2666.667), "2666.667");
        assert_eq!(fmt_f64(1e16), "1e+16");
        assert_eq!(fmt_f64(1e15), "1000000000000000.0");
        assert_eq!(fmt_f64(1.5e17), "1.5e+17");
        assert_eq!(fmt_f64(0.0001), "0.0001");
        assert_eq!(fmt_f64(0.00001), "0.00001");
        assert_eq!(fmt_f64(0.000001), "1e-6");
        assert_eq!(fmt_f64(1.25e-7), "1.25e-7");
        assert_eq!(fmt_f64(-0.0), "-0.0");
        assert_eq!(fmt_f64(123456789012345680.0), "1.2345678901234568e+17");
    }
}
