//! The shapes of a project file's parts, as the original's serde types have them, written in a
//! small language (see `parse`) and read once into a registry the reader walks.
//!
//! A struct lists its fields in declaration order (the order serde takes them from a sequence and
//! reports the first missing one, and the order they are written back), each with its type, its
//! default where the file may leave it out, and when writing it back leaves it out.

use crate::json::Value;
use std::collections::HashMap;
use std::sync::OnceLock;

#[derive(Clone, Debug)]
pub enum Ty {
    F64,
    F32,
    Bool,
    Str,
    /// An unsigned integer of this many bits (0: usize).
    U(u32),
    /// A signed integer of this many bits.
    I(u32),
    /// What an element points at: another's GUID, or its id.
    Ref,
    /// Any JSON value, kept (keys sorted, as serde_json's map holds them).
    Any,
    Opt(Box<Ty>),
    /// An Option the file may leave out but not give as null.
    Some(Box<Ty>),
    Vec(Box<Ty>),
    /// A sequence kept as a set (a `BTreeSet`): written sorted, each member once.
    Set(Box<Ty>),
    Arr(Box<Ty>, usize),
    Tup(Vec<Ty>),
    /// A map with string keys, written in key order.
    Map(Box<Ty>),
    /// A map keyed by what elements point at: GUIDs or ids.
    RefMap(Box<Ty>),
    /// A map keyed by an enum's variants, written in the enum's order.
    EnumMap(String, Box<Ty>),
    /// A struct, enum, untagged enum or alias of the registry, by name.
    Named(String),
}

#[derive(Clone, Debug)]
pub enum Skip {
    Never,
    /// Written unless null (None).
    None,
    /// Written unless an empty sequence, map or string.
    Empty,
    /// Written unless false.
    False,
    /// Written unless equal to this.
    Eq(Value),
}

#[derive(Clone, Debug)]
pub struct Field {
    pub name: String,
    pub aliases: Vec<String>,
    pub ty: Ty,
    /// None: required (an Option is None when left out).
    pub default: Option<Value>,
    pub skip: Skip,
    /// Read but never written back.
    pub hidden: bool,
}

#[derive(Clone, Debug)]
pub struct Struct {
    pub name: String,
    pub fields: Vec<Field>,
    /// A tuple struct (`struct P2(f64, f64)`): a sequence only.
    pub tuple: bool,
    /// Post-processing applied once read (by name, see `hooks`).
    pub hook: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Variant {
    /// The name the file may give it.
    pub name: String,
    /// The name written back.
    pub out: String,
    /// A newtype variant's content.
    pub data: Option<Ty>,
}

#[derive(Clone, Debug)]
pub struct Enum {
    pub variants: Vec<Variant>,
}

#[derive(Clone, Debug)]
pub enum Def {
    Struct(Struct),
    Enum(Enum),
    Untagged(Vec<Ty>),
    Alias(Ty),
    /// A type read by Rust code of its own (see `de::custom`).
    Custom,
}

pub struct Registry {
    pub defs: HashMap<String, Def>,
}

impl Registry {
    pub fn get(&self, name: &str) -> &Def {
        match self.defs.get(name) {
            Some(d) => d,
            None => panic!("schema: no type `{}`", name),
        }
    }
    pub fn st(&self, name: &str) -> &Struct {
        match self.get(name) {
            Def::Struct(s) => s,
            _ => panic!("schema: `{}` isn't a struct", name),
        }
    }
}

pub fn registry() -> &'static Registry {
    static REG: OnceLock<Registry> = OnceLock::new();
    REG.get_or_init(|| {
        let mut defs = HashMap::new();
        for text in [super::elements::SCHEMA, super::sections::SCHEMA] {
            if let Err(e) = parse(text, &mut defs) {
                panic!("schema: {}", e);
            }
        }
        for c in super::de::CUSTOM {
            defs.insert(c.to_string(), Def::Custom);
        }
        let reg = Registry { defs };
        check(&reg);
        reg
    })
}

/// Every name a type uses is defined.
fn check(reg: &Registry) {
    fn walk(reg: &Registry, t: &Ty, from: &str) {
        match t {
            Ty::Opt(x) | Ty::Some(x) | Ty::Vec(x) | Ty::Set(x) | Ty::Arr(x, _) | Ty::Map(x) | Ty::RefMap(x) => walk(reg, x, from),
            Ty::EnumMap(e, x) => {
                walk(reg, &Ty::Named(e.clone()), from);
                walk(reg, x, from)
            }
            Ty::Tup(xs) => xs.iter().for_each(|x| walk(reg, x, from)),
            Ty::Named(n) => {
                if !reg.defs.contains_key(n) {
                    panic!("schema: `{}` (in `{}`) isn't defined", n, from);
                }
            }
            _ => {}
        }
    }
    for (n, d) in &reg.defs {
        match d {
            Def::Struct(s) => s.fields.iter().for_each(|f| walk(reg, &f.ty, n)),
            Def::Enum(e) => e.variants.iter().filter_map(|v| v.data.as_ref()).for_each(|t| walk(reg, t, n)),
            Def::Untagged(ts) => ts.iter().for_each(|t| walk(reg, t, n)),
            Def::Alias(t) => walk(reg, t, n),
            Def::Custom => {}
        }
    }
}

// ---------------------------------------------------------------- the language
//
//   # a comment
//   struct Name ["display name"] [@hook] {
//       field: Type [= json] [?none|?empty|?false|?eq json|?default|?never] [~alias]
//   }
//   tuple P2 (f64, f64)                 a tuple struct
//   enum Name { a b>c d(Type) }        names in the order serde lists them; `b>c`: b read as c
//   untagged Name = Type | Type
//   alias Name = Type
//
// A field's `= json` is its default as written back; `?default` leaves it out when equal to it.

struct Lexer<'a> {
    s: &'a [u8],
    i: usize,
    line: usize,
}

impl<'a> Lexer<'a> {
    fn ws(&mut self) {
        while self.i < self.s.len() {
            let c = self.s[self.i];
            if c == b'#' {
                while self.i < self.s.len() && self.s[self.i] != b'\n' {
                    self.i += 1;
                }
            } else if c == b'\n' {
                self.line += 1;
                self.i += 1;
            } else if c.is_ascii_whitespace() {
                self.i += 1;
            } else {
                break;
            }
        }
    }
    fn peek(&mut self) -> Option<u8> {
        self.ws();
        self.s.get(self.i).copied()
    }
    fn eat(&mut self, c: u8) -> bool {
        if self.peek() == Some(c) {
            self.i += 1;
            true
        } else {
            false
        }
    }
    fn expect(&mut self, c: u8) -> Result<(), String> {
        if self.eat(c) {
            Ok(())
        } else {
            Err(self.err(&format!("expected `{}`", c as char)))
        }
    }
    fn err(&self, m: &str) -> String {
        let end = (self.i + 30).min(self.s.len());
        format!("line {}: {} at {:?}", self.line, m, String::from_utf8_lossy(&self.s[self.i.min(end)..end]))
    }
    fn word(&mut self) -> Result<String, String> {
        self.ws();
        let st = self.i;
        while self.i < self.s.len() {
            let c = self.s[self.i];
            if c.is_ascii_alphanumeric() || c == b'_' {
                self.i += 1;
            } else {
                break;
            }
        }
        if st == self.i {
            return Err(self.err("expected a word"));
        }
        Ok(String::from_utf8_lossy(&self.s[st..self.i]).to_string())
    }
    /// A variant's name: up to a blank, `(` or `}`.
    fn token(&mut self) -> Result<String, String> {
        self.ws();
        let st = self.i;
        while self.i < self.s.len() {
            let c = self.s[self.i];
            if c.is_ascii_whitespace() || c == b'(' || c == b'}' {
                break;
            }
            self.i += 1;
        }
        if st == self.i {
            return Err(self.err("expected a name"));
        }
        Ok(String::from_utf8_lossy(&self.s[st..self.i]).to_string())
    }
    fn quoted(&mut self) -> Result<String, String> {
        self.ws();
        self.expect(b'"')?;
        let st = self.i;
        while self.i < self.s.len() && self.s[self.i] != b'"' {
            self.i += 1;
        }
        let w = String::from_utf8_lossy(&self.s[st..self.i]).to_string();
        self.i += 1;
        Ok(w)
    }
    /// A JSON literal, up to where it ends.
    fn json(&mut self) -> Result<Value, String> {
        self.ws();
        let rest = std::str::from_utf8(&self.s[self.i..]).map_err(|e| e.to_string())?;
        let (v, n) = crate::json::parse_prefix(rest).map_err(|e| self.err(&format!("bad json: {}", e)))?;
        self.i += n;
        Ok(v)
    }
    fn ty(&mut self) -> Result<Ty, String> {
        if self.eat(b'[') {
            let t = self.ty()?;
            self.expect(b';')?;
            let n = self.word()?;
            self.expect(b']')?;
            return Ok(Ty::Arr(Box::new(t), n.parse().map_err(|_| self.err("bad array length"))?));
        }
        if self.eat(b'(') {
            let mut ts = vec![self.ty()?];
            while self.eat(b',') {
                ts.push(self.ty()?);
            }
            self.expect(b')')?;
            return Ok(Ty::Tup(ts));
        }
        let w = self.word()?;
        let one = |lx: &mut Lexer| -> Result<Box<Ty>, String> {
            lx.expect(b'<')?;
            let t = lx.ty()?;
            lx.expect(b'>')?;
            Ok(Box::new(t))
        };
        Ok(match w.as_str() {
            "f64" => Ty::F64,
            "f32" => Ty::F32,
            "bool" => Ty::Bool,
            "String" => Ty::Str,
            "u8" => Ty::U(8),
            "u16" => Ty::U(16),
            "u32" => Ty::U(32),
            "u64" => Ty::U(64),
            "usize" => Ty::U(0),
            "i8" => Ty::I(8),
            "i16" => Ty::I(16),
            "i32" => Ty::I(32),
            "i64" => Ty::I(64),
            "Ref" => Ty::Ref,
            "Any" => Ty::Any,
            "Option" => Ty::Opt(one(self)?),
            "Some" => Ty::Some(one(self)?),
            "Vec" => Ty::Vec(one(self)?),
            "Set" => Ty::Set(one(self)?),
            "Map" => Ty::Map(one(self)?),
            "RefMap" => Ty::RefMap(one(self)?),
            "EnumMap" => {
                self.expect(b'<')?;
                let e = self.word()?;
                self.expect(b',')?;
                let t = self.ty()?;
                self.expect(b'>')?;
                Ty::EnumMap(e, Box::new(t))
            }
            _ => Ty::Named(w),
        })
    }
}

pub fn parse(text: &str, defs: &mut HashMap<String, Def>) -> Result<(), String> {
    let mut lx = Lexer { s: text.as_bytes(), i: 0, line: 1 };
    while lx.peek().is_some() {
        let kw = lx.word()?;
        match kw.as_str() {
            "struct" => {
                let name = lx.word()?;
                let mut display = name.clone();
                if lx.peek() == Some(b'"') {
                    display = lx.quoted()?;
                }
                let mut hook = None;
                if lx.eat(b'@') {
                    hook = Some(lx.word()?);
                }
                lx.expect(b'{')?;
                let mut fields = Vec::new();
                while !lx.eat(b'}') {
                    let fname = lx.word()?;
                    lx.expect(b':')?;
                    let ty = lx.ty()?;
                    let mut f = Field { name: fname, aliases: vec![], ty, default: None, skip: Skip::Never, hidden: false };
                    if matches!(f.ty, Ty::Opt(_) | Ty::Some(_)) {
                        f.default = Some(Value::Null);
                    }
                    loop {
                        match lx.peek() {
                            Some(b'=') => {
                                lx.i += 1;
                                f.default = Some(lx.json()?);
                            }
                            Some(b'?') => {
                                lx.i += 1;
                                let w = lx.word()?;
                                f.skip = match w.as_str() {
                                    "none" => Skip::None,
                                    "empty" => Skip::Empty,
                                    "false" => Skip::False,
                                    "eq" => Skip::Eq(lx.json()?),
                                    "default" => Skip::Eq(f.default.clone().ok_or_else(|| lx.err("?default without a default"))?),
                                    "never" => {
                                        f.hidden = true;
                                        Skip::Never
                                    }
                                    _ => return Err(lx.err("unknown skip rule")),
                                };
                            }
                            Some(b'~') => {
                                // another name the file may give it
                                lx.i += 1;
                                f.aliases.push(lx.word()?);
                            }
                            _ => break,
                        }
                    }
                    fields.push(f);
                }
                defs.insert(name, Def::Struct(Struct { name: display, fields, tuple: false, hook }));
            }
            "tuple" => {
                let name = lx.word()?;
                let t = lx.ty()?;
                let ts = match t {
                    Ty::Tup(ts) => ts,
                    _ => return Err(lx.err("a tuple struct takes (T, …)")),
                };
                let fields = ts
                    .into_iter()
                    .enumerate()
                    .map(|(i, ty)| Field { name: i.to_string(), aliases: vec![], ty, default: None, skip: Skip::Never, hidden: false })
                    .collect();
                defs.insert(name.clone(), Def::Struct(Struct { name, fields, tuple: true, hook: None }));
            }
            "enum" => {
                let name = lx.word()?;
                lx.expect(b'{')?;
                let mut variants = Vec::new();
                while !lx.eat(b'}') {
                    let w = if lx.peek() == Some(b'"') { lx.quoted()? } else { lx.token()? };
                    let (n, out) = match w.split_once('>') {
                        Some((a, b)) => (a.to_string(), b.to_string()),
                        None => (w.clone(), w.clone()),
                    };
                    let mut data = None;
                    if lx.s.get(lx.i) == Some(&b'(') {
                        lx.i += 1;
                        data = Some(lx.ty()?);
                        lx.expect(b')')?;
                    }
                    variants.push(Variant { name: n, out, data });
                }
                defs.insert(name, Def::Enum(Enum { variants }));
            }
            "untagged" => {
                let name = lx.word()?;
                lx.expect(b'=')?;
                let mut ts = vec![lx.ty()?];
                while lx.eat(b'|') {
                    ts.push(lx.ty()?);
                }
                defs.insert(name, Def::Untagged(ts));
            }
            "alias" => {
                let name = lx.word()?;
                lx.expect(b'=')?;
                let t = lx.ty()?;
                defs.insert(name, Def::Alias(t));
            }
            _ => return Err(lx.err(&format!("unknown keyword `{}`", kw))),
        }
    }
    Ok(())
}
