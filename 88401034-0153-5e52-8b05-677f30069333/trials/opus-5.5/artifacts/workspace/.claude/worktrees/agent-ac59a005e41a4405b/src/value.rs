// Core value types: Value, JsStr (UTF-16 rope), Sym, PropKey.

use crate::bigint::BigInt;
use crate::object::Obj;
use std::cell::{Cell, OnceCell, RefCell};
use std::fmt;
use std::hash::{Hash, Hasher};
use std::rc::Rc;

// ---------------- JsStr ----------------

pub struct StrNode {
    flat: OnceCell<Box<[u16]>>,
    rope: RefCell<Option<(JsStr, JsStr)>>,
    len: usize,
    hash: Cell<u64>,
    /// cached: is every code unit < 128
    ascii: Cell<u8>, // 0 unknown, 1 yes, 2 no
}

#[derive(Clone)]
pub struct JsStr(Rc<StrNode>);

impl Drop for StrNode {
    fn drop(&mut self) {
        // iterative drop of deep ropes
        let mut stack: Vec<JsStr> = Vec::new();
        if let Some((a, b)) = self.rope.get_mut().take() {
            stack.push(a);
            stack.push(b);
        }
        while let Some(s) = stack.pop() {
            if let Ok(mut node) = Rc::try_unwrap(s.0) {
                if let Some((a, b)) = node.rope.get_mut().take() {
                    stack.push(a);
                    stack.push(b);
                }
                // node dropped here with no children
            }
        }
    }
}

pub fn fx_hash_u16(s: &[u16]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for &c in s {
        h = (h.rotate_left(5) ^ c as u64).wrapping_mul(0x517cc1b727220a95);
    }
    h
}

impl JsStr {
    pub fn from_units(v: Vec<u16>) -> JsStr {
        let len = v.len();
        let cell = OnceCell::new();
        let _ = cell.set(v.into_boxed_slice());
        JsStr(Rc::new(StrNode { flat: cell, rope: RefCell::new(None), len, hash: Cell::new(0), ascii: Cell::new(0) }))
    }
    pub fn from_slice(v: &[u16]) -> JsStr {
        JsStr::from_units(v.to_vec())
    }
    pub fn from_str(s: &str) -> JsStr {
        JsStr::from_units(s.encode_utf16().collect())
    }
    pub fn empty() -> JsStr {
        thread_local! {
            static EMPTY: JsStr = JsStr::from_units(Vec::new());
        }
        EMPTY.with(|e| e.clone())
    }
    pub fn len(&self) -> usize {
        self.0.len
    }
    pub fn is_empty(&self) -> bool {
        self.0.len == 0
    }
    pub fn ptr_eq(&self, o: &JsStr) -> bool {
        Rc::ptr_eq(&self.0, &o.0)
    }

    /// Flattened UTF-16 code units.
    pub fn units(&self) -> &[u16] {
        if let Some(f) = self.0.flat.get() {
            return f;
        }
        let mut out: Vec<u16> = Vec::with_capacity(self.0.len);
        let mut stack: Vec<JsStr> = Vec::new();
        {
            let r = self.0.rope.borrow();
            let (a, b) = r.as_ref().expect("rope");
            stack.push(b.clone());
            stack.push(a.clone());
        }
        while let Some(n) = stack.pop() {
            if let Some(f) = n.0.flat.get() {
                out.extend_from_slice(f);
                continue;
            }
            let r = n.0.rope.borrow();
            let (a, b) = r.as_ref().expect("rope");
            stack.push(b.clone());
            stack.push(a.clone());
        }
        let _ = self.0.flat.set(out.into_boxed_slice());
        // release children
        let children = self.0.rope.borrow_mut().take();
        drop(children);
        self.0.flat.get().unwrap()
    }

    pub fn concat(a: &JsStr, b: &JsStr) -> JsStr {
        if a.is_empty() {
            return b.clone();
        }
        if b.is_empty() {
            return a.clone();
        }
        let len = a.len() + b.len();
        if len <= 64 {
            let mut v = Vec::with_capacity(len);
            v.extend_from_slice(a.units());
            v.extend_from_slice(b.units());
            return JsStr::from_units(v);
        }
        JsStr(Rc::new(StrNode {
            flat: OnceCell::new(),
            rope: RefCell::new(Some((a.clone(), b.clone()))),
            len,
            hash: Cell::new(0),
            ascii: Cell::new(0),
        }))
    }

    pub fn hash_value(&self) -> u64 {
        let h = self.0.hash.get();
        if h != 0 {
            return h;
        }
        let mut h = fx_hash_u16(self.units());
        if h == 0 {
            h = 1;
        }
        self.0.hash.set(h);
        h
    }

    pub fn is_ascii(&self) -> bool {
        match self.0.ascii.get() {
            1 => true,
            2 => false,
            _ => {
                let r = self.units().iter().all(|&c| c < 128);
                self.0.ascii.set(if r { 1 } else { 2 });
                r
            }
        }
    }

    pub fn to_rust_string(&self) -> String {
        String::from_utf16_lossy(self.units())
    }

    pub fn eq_str(&self, s: &str) -> bool {
        let u = self.units();
        let mut i = 0;
        for c in s.encode_utf16() {
            if i >= u.len() || u[i] != c {
                return false;
            }
            i += 1;
        }
        i == u.len()
    }

    pub fn at(&self, i: usize) -> u16 {
        self.units()[i]
    }

    pub fn substring(&self, start: usize, end: usize) -> JsStr {
        if start == 0 && end == self.len() {
            return self.clone();
        }
        JsStr::from_slice(&self.units()[start..end])
    }

    /// If this string is a canonical array index (0..2^32-2), return it.
    pub fn as_array_index(&self) -> Option<u32> {
        let u = self.units();
        if u.is_empty() || u.len() > 10 {
            return None;
        }
        if u[0] == b'0' as u16 {
            return if u.len() == 1 { Some(0) } else { None };
        }
        let mut v: u64 = 0;
        for &c in u {
            if !(b'0' as u16..=b'9' as u16).contains(&c) {
                return None;
            }
            v = v * 10 + (c - b'0' as u16) as u64;
        }
        if v < 4294967295 {
            Some(v as u32)
        } else {
            None
        }
    }

    /// Canonical numeric string check for integer-index keys (used for typed arrays & ordering)
    pub fn as_integer_key(&self) -> Option<u64> {
        let u = self.units();
        if u.is_empty() || u.len() > 16 {
            return None;
        }
        if u[0] == b'0' as u16 {
            return if u.len() == 1 { Some(0) } else { None };
        }
        let mut v: u64 = 0;
        for &c in u {
            if !(b'0' as u16..=b'9' as u16).contains(&c) {
                return None;
            }
            v = v * 10 + (c - b'0' as u16) as u64;
        }
        Some(v)
    }

    pub fn index_of(&self, pat: &[u16], from: usize) -> Option<usize> {
        let s = self.units();
        if pat.is_empty() {
            return if from <= s.len() { Some(from) } else { None };
        }
        if pat.len() > s.len() {
            return None;
        }
        let last = s.len() - pat.len();
        let first = pat[0];
        let mut i = from;
        while i <= last {
            if s[i] == first && &s[i..i + pat.len()] == pat {
                return Some(i);
            }
            i += 1;
        }
        None
    }
}

impl PartialEq for JsStr {
    fn eq(&self, other: &JsStr) -> bool {
        if Rc::ptr_eq(&self.0, &other.0) {
            return true;
        }
        if self.len() != other.len() {
            return false;
        }
        let (h1, h2) = (self.0.hash.get(), other.0.hash.get());
        if h1 != 0 && h2 != 0 && h1 != h2 {
            return false;
        }
        self.units() == other.units()
    }
}
impl Eq for JsStr {}
impl Hash for JsStr {
    fn hash<H: Hasher>(&self, state: &mut H) {
        state.write_u64(self.hash_value());
    }
}
impl PartialOrd for JsStr {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for JsStr {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.units().cmp(other.units())
    }
}

impl fmt::Debug for JsStr {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self.to_rust_string())
    }
}
impl fmt::Display for JsStr {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_rust_string())
    }
}

impl From<&str> for JsStr {
    fn from(s: &str) -> JsStr {
        JsStr::from_str(s)
    }
}
impl From<String> for JsStr {
    fn from(s: String) -> JsStr {
        JsStr::from_str(&s)
    }
}

// ---------------- Symbols ----------------

pub struct SymbolData {
    pub description: Option<JsStr>,
    pub registered: bool,
    pub private: bool,
}

#[derive(Clone)]
pub struct Sym(pub Rc<SymbolData>);

impl Sym {
    pub fn new(desc: Option<JsStr>) -> Sym {
        Sym(Rc::new(SymbolData { description: desc, registered: false, private: false }))
    }
    pub fn new_private(desc: JsStr) -> Sym {
        Sym(Rc::new(SymbolData { description: Some(desc), registered: false, private: true }))
    }
    pub fn ptr_eq(&self, o: &Sym) -> bool {
        Rc::ptr_eq(&self.0, &o.0)
    }
    pub fn descriptive_string(&self) -> String {
        match &self.0.description {
            Some(d) => format!("Symbol({})", d),
            None => "Symbol()".to_string(),
        }
    }
    pub fn is_private(&self) -> bool {
        self.0.private
    }
}
thread_local! {
    /// Engine-internal symbol ids (the reference engine stores symbol-keyed properties under
    /// "\0<id>" keys and prints that spelling in some error messages). Well-known symbols
    /// have ids 1..=16; symbols created by user code count up from 57.
    static SYM_IDS: RefCell<std::collections::HashMap<usize, (std::rc::Weak<SymbolData>, u32)>> = RefCell::new(std::collections::HashMap::new());
    static NEXT_SYM_ID: Cell<u32> = Cell::new(57);
}

impl Sym {
    pub fn set_id(&self, id: u32) {
        let addr = Rc::as_ptr(&self.0) as usize;
        SYM_IDS.with(|m| {
            m.borrow_mut().insert(addr, (Rc::downgrade(&self.0), id));
        });
    }
    /// Give a user-created symbol the next engine id.
    pub fn assign_next_id(&self) {
        let id = NEXT_SYM_ID.with(|c| {
            let v = c.get();
            c.set(v + 1);
            v
        });
        self.set_id(id);
    }
    pub fn id(&self) -> Option<u32> {
        let addr = Rc::as_ptr(&self.0) as usize;
        SYM_IDS.with(|m| match m.borrow().get(&addr) {
            Some((w, id)) if w.ptr_eq(&Rc::downgrade(&self.0)) => Some(*id),
            _ => None,
        })
    }
}

impl PartialEq for Sym {
    fn eq(&self, o: &Sym) -> bool {
        Rc::ptr_eq(&self.0, &o.0)
    }
}
impl Eq for Sym {}
impl Hash for Sym {
    fn hash<H: Hasher>(&self, state: &mut H) {
        (Rc::as_ptr(&self.0) as usize).hash(state)
    }
}

// ---------------- PropKey ----------------

#[derive(Clone, PartialEq, Eq, Hash)]
pub enum PropKey {
    Str(JsStr),
    Sym(Sym),
}

impl PropKey {
    pub fn from_str(s: &str) -> PropKey {
        PropKey::Str(JsStr::from_str(s))
    }
    pub fn as_index(&self) -> Option<u32> {
        match self {
            PropKey::Str(s) => s.as_array_index(),
            _ => None,
        }
    }
    pub fn is_symbol(&self) -> bool {
        matches!(self, PropKey::Sym(_))
    }
    pub fn is_private(&self) -> bool {
        matches!(self, PropKey::Sym(s) if s.is_private())
    }
    pub fn to_display(&self) -> String {
        match self {
            PropKey::Str(s) => s.to_rust_string(),
            PropKey::Sym(s) => s.descriptive_string(),
        }
    }
    /// Key spelling used inside error messages: symbols print as the engine-internal
    /// "\0<id>" key when they have an id.
    pub fn to_err_display(&self) -> String {
        match self {
            PropKey::Str(s) => s.to_rust_string(),
            PropKey::Sym(s) => match s.id() {
                Some(id) => format!("\u{0}{}", id),
                None => s.descriptive_string(),
            },
        }
    }
    pub fn from_index(i: u32) -> PropKey {
        PropKey::Str(index_to_jsstr(i as u64))
    }
    pub fn as_jsstr(&self) -> Option<&JsStr> {
        match self {
            PropKey::Str(s) => Some(s),
            _ => None,
        }
    }
    pub fn eq_str(&self, s: &str) -> bool {
        match self {
            PropKey::Str(x) => x.eq_str(s),
            _ => false,
        }
    }
}

impl fmt::Debug for PropKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_display())
    }
}

thread_local! {
    static SMALL_INTS: Vec<JsStr> = (0..1024u32).map(|i| JsStr::from_str(&i.to_string())).collect();
}

pub fn index_to_jsstr(i: u64) -> JsStr {
    if i < 1024 {
        SMALL_INTS.with(|v| v[i as usize].clone())
    } else {
        JsStr::from_str(&i.to_string())
    }
}

// ---------------- Value ----------------

#[derive(Clone)]
pub enum Value {
    Undefined,
    Null,
    Bool(bool),
    Num(f64),
    Str(JsStr),
    Sym(Sym),
    BigInt(Rc<BigInt>),
    Obj(Obj),
    /// internal: uninitialized binding / array hole. Never visible to JS.
    Empty,
}

impl Default for Value {
    fn default() -> Self {
        Value::Undefined
    }
}

impl Value {
    pub fn str(s: &str) -> Value {
        Value::Str(JsStr::from_str(s))
    }
    pub fn is_undefined(&self) -> bool {
        matches!(self, Value::Undefined)
    }
    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }
    pub fn is_nullish(&self) -> bool {
        matches!(self, Value::Undefined | Value::Null)
    }
    pub fn is_object(&self) -> bool {
        matches!(self, Value::Obj(_))
    }
    pub fn is_empty(&self) -> bool {
        matches!(self, Value::Empty)
    }
    pub fn as_obj(&self) -> Option<&Obj> {
        match self {
            Value::Obj(o) => Some(o),
            _ => None,
        }
    }
    pub fn as_num(&self) -> Option<f64> {
        match self {
            Value::Num(n) => Some(*n),
            _ => None,
        }
    }
    pub fn type_of(&self) -> &'static str {
        match self {
            Value::Undefined | Value::Empty => "undefined",
            Value::Null => "object",
            Value::Bool(_) => "boolean",
            Value::Num(_) => "number",
            Value::Str(_) => "string",
            Value::Sym(_) => "symbol",
            Value::BigInt(_) => "bigint",
            Value::Obj(o) => {
                if o.is_htmldda() {
                    "undefined"
                } else if o.is_callable() {
                    "function"
                } else {
                    "object"
                }
            }
        }
    }
    pub fn truthy(&self) -> bool {
        match self {
            Value::Undefined | Value::Null | Value::Empty => false,
            Value::Bool(b) => *b,
            Value::Num(n) => !(*n == 0.0 || n.is_nan()),
            Value::Str(s) => !s.is_empty(),
            Value::Sym(_) => true,
            Value::BigInt(b) => !b.is_zero(),
            Value::Obj(o) => !o.is_htmldda(),
        }
    }
    pub fn is_callable(&self) -> bool {
        match self {
            Value::Obj(o) => o.is_callable(),
            _ => false,
        }
    }
    pub fn same_value(a: &Value, b: &Value) -> bool {
        match (a, b) {
            (Value::Num(x), Value::Num(y)) => {
                if x.is_nan() && y.is_nan() {
                    true
                } else {
                    x == y && x.is_sign_negative() == y.is_sign_negative()
                }
            }
            _ => Value::strict_eq(a, b),
        }
    }
    pub fn same_value_zero(a: &Value, b: &Value) -> bool {
        match (a, b) {
            (Value::Num(x), Value::Num(y)) => (x.is_nan() && y.is_nan()) || x == y,
            _ => Value::strict_eq(a, b),
        }
    }
    pub fn strict_eq(a: &Value, b: &Value) -> bool {
        match (a, b) {
            (Value::Undefined, Value::Undefined) => true,
            (Value::Null, Value::Null) => true,
            (Value::Bool(x), Value::Bool(y)) => x == y,
            (Value::Num(x), Value::Num(y)) => x == y,
            (Value::Str(x), Value::Str(y)) => x == y,
            (Value::Sym(x), Value::Sym(y)) => x == y,
            (Value::BigInt(x), Value::BigInt(y)) => x == y,
            (Value::Obj(x), Value::Obj(y)) => x.ptr_eq(y),
            (Value::Empty, Value::Empty) => true,
            _ => false,
        }
    }
}

impl From<f64> for Value {
    fn from(n: f64) -> Value {
        Value::Num(n)
    }
}
impl From<bool> for Value {
    fn from(b: bool) -> Value {
        Value::Bool(b)
    }
}
impl From<JsStr> for Value {
    fn from(s: JsStr) -> Value {
        Value::Str(s)
    }
}
impl From<Obj> for Value {
    fn from(o: Obj) -> Value {
        Value::Obj(o)
    }
}
impl From<&str> for Value {
    fn from(s: &str) -> Value {
        Value::str(s)
    }
}
impl From<i32> for Value {
    fn from(n: i32) -> Value {
        Value::Num(n as f64)
    }
}
impl From<u32> for Value {
    fn from(n: u32) -> Value {
        Value::Num(n as f64)
    }
}
impl From<usize> for Value {
    fn from(n: usize) -> Value {
        Value::Num(n as f64)
    }
}

impl fmt::Debug for Value {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Value::Undefined => write!(f, "undefined"),
            Value::Null => write!(f, "null"),
            Value::Bool(b) => write!(f, "{}", b),
            Value::Num(n) => write!(f, "{}", n),
            Value::Str(s) => write!(f, "{:?}", s),
            Value::Sym(s) => write!(f, "{}", s.descriptive_string()),
            Value::BigInt(b) => write!(f, "{}n", b.to_string_radix(10)),
            Value::Obj(_) => write!(f, "[object]"),
            Value::Empty => write!(f, "<empty>"),
        }
    }
}

/// Key wrapper implementing SameValueZero hashing for Map/Set.
#[derive(Clone)]
pub struct MapKey(pub Value);

impl PartialEq for MapKey {
    fn eq(&self, o: &MapKey) -> bool {
        Value::same_value_zero(&self.0, &o.0)
    }
}
impl Eq for MapKey {}
impl Hash for MapKey {
    fn hash<H: Hasher>(&self, state: &mut H) {
        match &self.0 {
            Value::Undefined => 0u8.hash(state),
            Value::Null => 1u8.hash(state),
            Value::Bool(b) => {
                2u8.hash(state);
                b.hash(state)
            }
            Value::Num(n) => {
                3u8.hash(state);
                let n = if *n == 0.0 { 0.0 } else { *n };
                if n.is_nan() {
                    u64::MAX.hash(state)
                } else {
                    n.to_bits().hash(state)
                }
            }
            Value::Str(s) => {
                4u8.hash(state);
                s.hash(state)
            }
            Value::Sym(s) => {
                5u8.hash(state);
                s.hash(state)
            }
            Value::BigInt(b) => {
                6u8.hash(state);
                b.hash(state)
            }
            Value::Obj(o) => {
                7u8.hash(state);
                o.addr().hash(state)
            }
            Value::Empty => 8u8.hash(state),
        }
    }
}

/// Simple fast hasher (FxHash-like) for internal maps.
#[derive(Default, Clone, Copy)]
pub struct FxHasher {
    hash: u64,
}
impl Hasher for FxHasher {
    fn finish(&self) -> u64 {
        self.hash
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.hash = (self.hash.rotate_left(5) ^ b as u64).wrapping_mul(0x517cc1b727220a95);
        }
    }
    fn write_u8(&mut self, i: u8) {
        self.hash = (self.hash.rotate_left(5) ^ i as u64).wrapping_mul(0x517cc1b727220a95);
    }
    fn write_u64(&mut self, i: u64) {
        self.hash = (self.hash.rotate_left(5) ^ i).wrapping_mul(0x517cc1b727220a95);
    }
    fn write_usize(&mut self, i: usize) {
        self.write_u64(i as u64)
    }
}
#[derive(Default, Clone, Copy)]
pub struct FxBuild;
impl std::hash::BuildHasher for FxBuild {
    type Hasher = FxHasher;
    fn build_hasher(&self) -> FxHasher {
        FxHasher::default()
    }
}
pub type FxHashMap<K, V> = std::collections::HashMap<K, V, FxBuild>;

pub fn new_fx_map<K, V>() -> FxHashMap<K, V> {
    std::collections::HashMap::with_hasher(FxBuild)
}
