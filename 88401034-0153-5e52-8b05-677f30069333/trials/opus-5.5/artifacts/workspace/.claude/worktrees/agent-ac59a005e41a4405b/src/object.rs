// Object model: objects, properties, internal kinds.

use crate::bigint::BigInt;
use crate::bytecode::FunctionCode;
use crate::value::*;
use crate::vm::{Env, Frame, JsResult, Vm};
use std::cell::{Ref, RefCell, RefMut};
use std::collections::HashMap;
use std::rc::{Rc, Weak};

pub const WRITABLE: u8 = 1;
pub const ENUMERABLE: u8 = 2;
pub const CONFIGURABLE: u8 = 4;
pub const WEC: u8 = 7;
pub const WC: u8 = WRITABLE | CONFIGURABLE;

#[derive(Clone)]
pub enum Prop {
    Data { value: Value, flags: u8 },
    Accessor { get: Option<Obj>, set: Option<Obj>, flags: u8 },
}

impl Prop {
    pub fn data(value: Value, flags: u8) -> Prop {
        Prop::Data { value, flags }
    }
    pub fn flags(&self) -> u8 {
        match self {
            Prop::Data { flags, .. } => *flags,
            Prop::Accessor { flags, .. } => *flags,
        }
    }
    pub fn enumerable(&self) -> bool {
        self.flags() & ENUMERABLE != 0
    }
    pub fn configurable(&self) -> bool {
        self.flags() & CONFIGURABLE != 0
    }
    pub fn writable(&self) -> bool {
        match self {
            Prop::Data { flags, .. } => flags & WRITABLE != 0,
            _ => false,
        }
    }
}

/// Ordered property map.
#[derive(Default)]
pub struct PropMap {
    keys: Vec<PropKey>,
    vals: Vec<Prop>,
    index: Option<FxHashMap<PropKey, u32>>,
}

const INDEX_THRESHOLD: usize = 8;

impl PropMap {
    pub fn new() -> PropMap {
        PropMap { keys: Vec::new(), vals: Vec::new(), index: None }
    }
    pub fn len(&self) -> usize {
        self.keys.len()
    }
    pub fn is_empty(&self) -> bool {
        self.keys.is_empty()
    }
    fn find(&self, k: &PropKey) -> Option<usize> {
        if let Some(idx) = &self.index {
            return idx.get(k).map(|i| *i as usize);
        }
        // pointer-equality fast path then content
        for (i, key) in self.keys.iter().enumerate() {
            match (key, k) {
                (PropKey::Str(a), PropKey::Str(b)) => {
                    if a.ptr_eq(b) || a == b {
                        return Some(i);
                    }
                }
                (PropKey::Sym(a), PropKey::Sym(b)) => {
                    if a == b {
                        return Some(i);
                    }
                }
                _ => {}
            }
        }
        None
    }
    pub fn get(&self, k: &PropKey) -> Option<&Prop> {
        self.find(k).map(|i| &self.vals[i])
    }
    pub fn get_mut(&mut self, k: &PropKey) -> Option<&mut Prop> {
        match self.find(k) {
            Some(i) => Some(&mut self.vals[i]),
            None => None,
        }
    }
    pub fn contains(&self, k: &PropKey) -> bool {
        self.find(k).is_some()
    }
    pub fn insert(&mut self, k: PropKey, p: Prop) {
        if let Some(i) = self.find(&k) {
            self.vals[i] = p;
            return;
        }
        let i = self.keys.len();
        if let Some(idx) = &mut self.index {
            idx.insert(k.clone(), i as u32);
        }
        self.keys.push(k);
        self.vals.push(p);
        if self.index.is_none() && self.keys.len() > INDEX_THRESHOLD {
            self.rebuild_index();
        }
    }
    fn rebuild_index(&mut self) {
        let mut m = new_fx_map();
        for (i, k) in self.keys.iter().enumerate() {
            m.insert(k.clone(), i as u32);
        }
        self.index = Some(m);
    }
    pub fn remove(&mut self, k: &PropKey) -> Option<Prop> {
        let i = self.find(k)?;
        self.keys.remove(i);
        let p = self.vals.remove(i);
        if self.index.is_some() {
            if self.keys.len() > INDEX_THRESHOLD {
                self.rebuild_index();
            } else {
                self.index = None;
            }
        }
        Some(p)
    }
    pub fn keys(&self) -> &[PropKey] {
        &self.keys
    }
    pub fn iter(&self) -> impl Iterator<Item = (&PropKey, &Prop)> {
        self.keys.iter().zip(self.vals.iter())
    }
    pub fn values_mut(&mut self) -> impl Iterator<Item = &mut Prop> {
        self.vals.iter_mut()
    }
    pub fn clear(&mut self) {
        self.keys.clear();
        self.vals.clear();
        self.index = None;
    }
    /// Keys in spec order: integer indices ascending, then strings, then symbols (insertion order).
    pub fn ordered_keys(&self) -> Vec<PropKey> {
        let mut ints: Vec<(u64, PropKey)> = Vec::new();
        let mut strs = Vec::new();
        let mut syms = Vec::new();
        for k in &self.keys {
            match k {
                PropKey::Str(s) => {
                    if let Some(i) = s.as_array_index() {
                        ints.push((i as u64, k.clone()));
                    } else {
                        strs.push(k.clone());
                    }
                }
                PropKey::Sym(s) => {
                    if !s.is_private() {
                        syms.push(k.clone())
                    }
                }
            }
        }
        if ints.len() > 1 {
            ints.sort_by_key(|(i, _)| *i);
        }
        let mut out: Vec<PropKey> = ints.into_iter().map(|(_, k)| k).collect();
        out.extend(strs);
        out.extend(syms);
        out
    }
}

pub struct ArrayData {
    /// dense element storage; Value::Empty marks holes
    pub dense: Vec<Value>,
    pub len: u32,
    /// when true, all elements live in the property map
    pub sparse: bool,
    pub length_writable: bool,
}

pub type NativeFn = fn(&mut Vm, &Args) -> JsResult<Value>;

pub struct Args<'a> {
    pub this: Value,
    pub args: &'a [Value],
    pub callee: &'a Obj,
    pub new_target: Option<Obj>,
}

impl<'a> Args<'a> {
    #[inline]
    pub fn arg(&self, i: usize) -> Value {
        self.args.get(i).cloned().unwrap_or(Value::Undefined)
    }

    pub fn len(&self) -> usize {
        self.args.len()
    }
    pub fn slot(&self, i: usize) -> Value {
        let o = self.callee.borrow();
        match &o.kind {
            ObjKind::Native(n) => n.slots.get(i).cloned().unwrap_or(Value::Undefined),
            _ => Value::Undefined,
        }
    }
}

/// NativeFunc name tag of the [[IsHTMLDDA]] host function
pub const HTMLDDA_TAG: &str = "\0htmldda";

pub struct NativeFunc {
    pub f: NativeFn,
    pub slots: Vec<Value>,
    pub is_ctor: bool,
    pub name: &'static str,
    /// the realm the function was created in
    pub realm: u32,
}

#[derive(Clone)]
pub struct ClassField {
    pub key: FieldKey,
    pub init: Option<Obj>,
    pub is_accessor: bool,
    /// decorator-provided initializers applied to the initial value (in order)
    pub extra_inits: Vec<Value>,
}

#[derive(Clone)]
pub enum FieldKey {
    Key(PropKey),
    Private(Sym),
    /// private method/accessor to install on the instance
    PrivateMethod(Sym, Prop),
    /// initializer added by a decorator (`addInitializer`), run after the fields
    Initializer,
}

pub struct Closure {
    pub code: Rc<FunctionCode>,
    pub env: Option<Env>,
    pub home_object: Option<Obj>,
    pub fields: Option<Rc<Vec<ClassField>>>,
    /// lexical this captured at creation (arrow functions at global/module level)
    pub this_val: Option<Value>,
    pub is_class_ctor: bool,
    pub derived: bool,
    /// the realm the function was created in
    pub realm: u32,
}

pub struct BoundFunc {
    pub target: Obj,
    pub this: Value,
    pub args: Vec<Value>,
}

pub struct ProxyData {
    pub target: Option<Obj>,
    pub handler: Option<Obj>,
    pub callable: bool,
    pub constructor: bool,
}

#[derive(Clone)]
pub enum PromiseState {
    Pending,
    Fulfilled(Value),
    Rejected(Value),
}

#[derive(Clone)]
pub enum Handler {
    Callable(Value),
    Identity,
    Thrower,
    /// resume an async function / async generator coroutine
    Await(Obj),
    /// internal callback with data
    Native(fn(&mut Vm, Value, &Value) -> JsResult<Value>, Value),
}

#[derive(Clone)]
pub struct Capability {
    pub promise: Value,
    pub resolve: Value,
    pub reject: Value,
}

#[derive(Clone)]
pub struct Reaction {
    pub capability: Option<Capability>,
    pub is_reject: bool,
    pub handler: Handler,
}

pub struct PromiseData {
    pub state: PromiseState,
    pub fulfill_reactions: Vec<Reaction>,
    pub reject_reactions: Vec<Reaction>,
    pub is_handled: bool,
    pub id: u64,
}

pub struct OrderedMap {
    pub entries: Vec<Option<(Value, Value)>>,
    pub index: HashMap<MapKey, usize, FxBuild>,
    pub live: usize,
}

impl OrderedMap {
    pub fn new() -> OrderedMap {
        OrderedMap { entries: Vec::new(), index: HashMap::with_hasher(FxBuild), live: 0 }
    }
    pub fn get(&self, k: &Value) -> Option<&Value> {
        let i = *self.index.get(&MapKey(k.clone()))?;
        self.entries[i].as_ref().map(|(_, v)| v)
    }
    pub fn has(&self, k: &Value) -> bool {
        self.index.contains_key(&MapKey(k.clone()))
    }
    pub fn set(&mut self, k: Value, v: Value) {
        let k = match k {
            Value::Num(n) if n == 0.0 => Value::Num(0.0),
            other => other,
        };
        let mk = MapKey(k.clone());
        if let Some(&i) = self.index.get(&mk) {
            if let Some(e) = &mut self.entries[i] {
                e.1 = v;
            }
            return;
        }
        self.index.insert(mk, self.entries.len());
        self.entries.push(Some((k, v)));
        self.live += 1;
    }
    pub fn delete(&mut self, k: &Value) -> bool {
        match self.index.remove(&MapKey(k.clone())) {
            Some(i) => {
                self.entries[i] = None;
                self.live -= 1;
                true
            }
            None => false,
        }
    }
    pub fn clear(&mut self) {
        for e in self.entries.iter_mut() {
            *e = None;
        }
        self.index.clear();
        self.live = 0;
    }
}

impl Default for OrderedMap {
    fn default() -> Self {
        OrderedMap::new()
    }
}

pub struct WeakTable {
    pub map: HashMap<usize, (Weak<RefCell<ObjectData>>, Value), FxBuild>,
}

impl WeakTable {
    pub fn new() -> WeakTable {
        WeakTable { map: HashMap::with_hasher(FxBuild) }
    }
    pub fn get(&self, k: &Obj) -> Option<Value> {
        match self.map.get(&k.addr()) {
            Some((w, v)) if w.strong_count() > 0 => Some(v.clone()),
            _ => None,
        }
    }
    pub fn has(&self, k: &Obj) -> bool {
        matches!(self.map.get(&k.addr()), Some((w, _)) if w.strong_count() > 0)
    }
    pub fn set(&mut self, k: &Obj, v: Value) {
        if self.map.len() > 64 && self.map.len().is_power_of_two() {
            self.map.retain(|_, (w, _)| w.strong_count() > 0);
        }
        self.map.insert(k.addr(), (Rc::downgrade(&k.0), v));
    }
    pub fn delete(&mut self, k: &Obj) -> bool {
        match self.map.remove(&k.addr()) {
            Some((w, _)) => w.strong_count() > 0,
            None => false,
        }
    }
}

impl Default for WeakTable {
    fn default() -> Self {
        WeakTable::new()
    }
}

pub struct BufferData {
    pub bytes: Vec<u8>,
    pub detached: bool,
    pub max_len: Option<usize>,
    pub shared: bool,
    /// immutable ArrayBuffer (transferToImmutable / sliceToImmutable)
    pub immutable: bool,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TAKind {
    Int8,
    Uint8,
    Uint8C,
    Int16,
    Uint16,
    Int32,
    Uint32,
    Float16,
    Float32,
    Float64,
    BigInt64,
    BigUint64,
}

impl TAKind {
    pub fn size(self) -> usize {
        match self {
            TAKind::Int8 | TAKind::Uint8 | TAKind::Uint8C => 1,
            TAKind::Int16 | TAKind::Uint16 | TAKind::Float16 => 2,
            TAKind::Int32 | TAKind::Uint32 | TAKind::Float32 => 4,
            TAKind::Float64 | TAKind::BigInt64 | TAKind::BigUint64 => 8,
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            TAKind::Int8 => "Int8Array",
            TAKind::Uint8 => "Uint8Array",
            TAKind::Uint8C => "Uint8ClampedArray",
            TAKind::Int16 => "Int16Array",
            TAKind::Uint16 => "Uint16Array",
            TAKind::Int32 => "Int32Array",
            TAKind::Uint32 => "Uint32Array",
            TAKind::Float16 => "Float16Array",
            TAKind::Float32 => "Float32Array",
            TAKind::Float64 => "Float64Array",
            TAKind::BigInt64 => "BigInt64Array",
            TAKind::BigUint64 => "BigUint64Array",
        }
    }
    pub fn is_bigint(self) -> bool {
        matches!(self, TAKind::BigInt64 | TAKind::BigUint64)
    }
    pub fn all() -> [TAKind; 12] {
        [
            TAKind::Int8,
            TAKind::Uint8,
            TAKind::Uint8C,
            TAKind::Int16,
            TAKind::Uint16,
            TAKind::Int32,
            TAKind::Uint32,
            TAKind::Float16,
            TAKind::Float32,
            TAKind::Float64,
            TAKind::BigInt64,
            TAKind::BigUint64,
        ]
    }
}

pub struct TypedArrayData {
    pub kind: TAKind,
    pub buffer: Obj,
    pub buf: Rc<RefCell<BufferData>>,
    pub offset: usize,
    /// None = length tracking (resizable buffer)
    pub length: Option<usize>,
}

impl TypedArrayData {
    /// current length in elements (0 if out of bounds/detached)
    pub fn len(&self) -> usize {
        let b = self.buf.borrow();
        if b.detached {
            return 0;
        }
        let blen = b.bytes.len();
        match self.length {
            Some(l) => {
                if self.offset + l * self.kind.size() > blen {
                    0
                } else {
                    l
                }
            }
            None => {
                if self.offset > blen {
                    0
                } else {
                    (blen - self.offset) / self.kind.size()
                }
            }
        }
    }
    pub fn is_out_of_bounds(&self) -> bool {
        let b = self.buf.borrow();
        if b.detached {
            return true;
        }
        let blen = b.bytes.len();
        match self.length {
            Some(l) => self.offset + l * self.kind.size() > blen,
            None => self.offset > blen,
        }
    }
}

pub struct DataViewData {
    pub buffer: Obj,
    pub buf: Rc<RefCell<BufferData>>,
    pub offset: usize,
    pub length: Option<usize>,
}

pub struct ArgumentsData {
    /// mapped arguments: (env, slot index) per argument index, None if unmapped
    pub mapped: Vec<Option<(Env, u32)>>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum GenState {
    SuspendedStart,
    SuspendedYield,
    Executing,
    Completed,
}

pub struct GeneratorData {
    pub state: GenState,
    pub frame: Option<Box<Frame>>,
}

pub struct AsyncGenRequest {
    pub kind: u8, // 0 next, 1 throw, 2 return
    pub value: Value,
    pub capability: Capability,
}

pub struct AsyncGenData {
    pub state: GenState,
    /// awaiting-return state
    pub awaiting_return: bool,
    pub frame: Option<Box<Frame>>,
    pub queue: std::collections::VecDeque<AsyncGenRequest>,
}

/// Coroutine state for async functions
pub struct AsyncFnData {
    pub frame: Option<Box<Frame>>,
    pub capability: Capability,
}

pub enum IterState {
    Array { obj: Value, index: usize, kind: u8, done: bool },
    Map { map: Obj, index: usize, kind: u8, done: bool },
    Set { set: Obj, index: usize, kind: u8, done: bool },
    Str { s: JsStr, index: usize, done: bool },
    RegExpStr { re: Obj, s: JsStr, global: bool, unicode: bool, done: bool },
    ForIn { obj: Option<Obj>, keys: Vec<JsStr>, index: usize, visited: Vec<JsStr>, started: bool },
    Helper(Box<IterHelper>),
    Wrap { iterated: Obj, next: Value },
    AsyncFromSync { iter: Obj, next: Value },
    Concat { iterables: Vec<(Value, Value)>, index: usize, inner: Option<(Obj, Value)> },
    Zip(Box<ZipState>),
}

pub struct ZipState {
    pub iters: Vec<Option<(Obj, Value)>>,
    pub mode: u8,
    pub padding: Vec<Value>,
    pub done: bool,
    pub keys: Option<Vec<PropKey>>,
}

pub struct IterHelper {
    pub kind: HelperKind,
    pub underlying: Obj,
    pub next_method: Value,
    pub func: Value,
    pub counter: f64,
    pub remaining: f64,
    pub inner: Option<(Obj, Value)>,
    pub done: bool,
    pub running: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum HelperKind {
    Map,
    Filter,
    Take,
    Drop,
    FlatMap,
}

pub struct RegExpData {
    pub source: JsStr,
    pub flags: JsStr,
    pub compiled: crate::regexp::CompiledRegex,
    pub rflags: crate::regexp::RegexFlags,
    pub legacy: bool,
}

pub enum ObjKind {
    Ordinary,
    Array(ArrayData),
    Closure(Box<Closure>),
    Native(NativeFunc),
    Bound(Box<BoundFunc>),
    Error,
    Boolean(bool),
    Number(f64),
    String(JsStr),
    Symbol(Sym),
    BigInt(Rc<BigInt>),
    Date(f64),
    RegExp(Box<RegExpData>),
    Map(Box<OrderedMap>),
    Set(Box<OrderedMap>),
    WeakMap(Box<WeakTable>),
    WeakSet(Box<WeakTable>),
    WeakRef(Weak<RefCell<ObjectData>>),
    FinalizationRegistry(Box<Vec<(Weak<RefCell<ObjectData>>, Value, Option<Value>)>>, Value),
    Promise(Box<PromiseData>),
    Proxy(Box<ProxyData>),
    ArrayBuffer(Rc<RefCell<BufferData>>),
    TypedArray(Box<TypedArrayData>),
    DataView(Box<DataViewData>),
    Arguments(Box<ArgumentsData>),
    Generator(Box<GeneratorData>),
    AsyncGenerator(Box<AsyncGenData>),
    AsyncFn(Box<AsyncFnData>),
    Iterator(Box<IterState>),
    Namespace(Rc<crate::modules::ModuleRecord>),
    Host(Box<dyn std::any::Any>),
    /// ordinary object marked as [[IsHTMLDDA]]
    HtmlDda,
}

pub struct ObjectData {
    pub proto: Option<Obj>,
    pub props: PropMap,
    pub extensible: bool,
    pub kind: ObjKind,
    /// class name hint used for some builtins (e.g. "Object" for plain objects)
    pub class: &'static str,
}

#[derive(Clone)]
pub struct Obj(pub Rc<RefCell<ObjectData>>);

impl PartialEq for Obj {
    fn eq(&self, o: &Obj) -> bool {
        Rc::ptr_eq(&self.0, &o.0)
    }
}
impl Eq for Obj {}
impl std::hash::Hash for Obj {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.addr().hash(state)
    }
}

impl Obj {
    pub fn new(proto: Option<Obj>, kind: ObjKind) -> Obj {
        Obj(Rc::new(RefCell::new(ObjectData { proto, props: PropMap::new(), extensible: true, kind, class: "Object" })))
    }
    pub fn with_class(proto: Option<Obj>, kind: ObjKind, class: &'static str) -> Obj {
        Obj(Rc::new(RefCell::new(ObjectData { proto, props: PropMap::new(), extensible: true, kind, class })))
    }
    #[inline]
    pub fn borrow(&self) -> Ref<'_, ObjectData> {
        self.0.borrow()
    }
    #[inline]
    pub fn borrow_mut(&self) -> RefMut<'_, ObjectData> {
        self.0.borrow_mut()
    }
    pub fn ptr_eq(&self, o: &Obj) -> bool {
        Rc::ptr_eq(&self.0, &o.0)
    }
    pub fn addr(&self) -> usize {
        Rc::as_ptr(&self.0) as *const u8 as usize
    }
    pub fn downgrade(&self) -> Weak<RefCell<ObjectData>> {
        Rc::downgrade(&self.0)
    }
    pub fn is_callable(&self) -> bool {
        match &self.borrow().kind {
            ObjKind::Closure(_) | ObjKind::Native(_) | ObjKind::Bound(_) => true,
            ObjKind::Proxy(p) => p.callable,
            _ => false,
        }
    }
    pub fn is_constructor(&self) -> bool {
        match &self.borrow().kind {
            ObjKind::Closure(c) => c.code.is_constructor(),
            ObjKind::Native(n) => n.is_ctor,
            ObjKind::Bound(b) => b.target.is_constructor(),
            ObjKind::Proxy(p) => p.constructor,
            _ => false,
        }
    }
    pub fn is_htmldda(&self) -> bool {
        match &self.borrow().kind {
            ObjKind::HtmlDda => true,
            // the callable $262.IsHTMLDDA
            ObjKind::Native(n) => n.name == HTMLDDA_TAG,
            _ => false,
        }
    }
    pub fn is_array(&self) -> bool {
        matches!(self.borrow().kind, ObjKind::Array(_))
    }
    pub fn is_proxy(&self) -> bool {
        matches!(self.borrow().kind, ObjKind::Proxy(_))
    }
    pub fn proto(&self) -> Option<Obj> {
        self.borrow().proto.clone()
    }
    pub fn class_name(&self) -> &'static str {
        self.borrow().class
    }

    /// Define/overwrite an own data property directly (no checks).
    pub fn set_prop(&self, key: PropKey, value: Value, flags: u8) {
        let mut o = self.borrow_mut();
        if let ObjKind::Array(a) = &mut o.kind {
            if let Some(i) = key.as_index() {
                if !a.sparse && flags == WEC {
                    let i = i as usize;
                    if i < a.dense.len() {
                        a.dense[i] = value;
                        return;
                    }
                    if i == a.dense.len() {
                        a.dense.push(value);
                        if a.len < (i + 1) as u32 {
                            a.len = (i + 1) as u32;
                        }
                        return;
                    }
                }
            }
        }
        o.props.insert(key, Prop::Data { value, flags });
    }
    pub fn set_str(&self, key: &str, value: Value, flags: u8) {
        self.set_prop(PropKey::from_str(key), value, flags)
    }
    /// writable+configurable non-enumerable (builtin methods)
    pub fn set_hidden(&self, key: &str, value: Value) {
        self.set_prop(PropKey::from_str(key), value, WC)
    }
    pub fn set_accessor(&self, key: PropKey, get: Option<Obj>, set: Option<Obj>, flags: u8) {
        self.borrow_mut().props.insert(key, Prop::Accessor { get, set, flags });
    }
    /// Own data property lookup without invoking getters (None for accessors/missing)
    pub fn get_own_data(&self, key: &PropKey) -> Option<Value> {
        let o = self.borrow();
        if let ObjKind::Array(a) = &o.kind {
            if !a.sparse {
                if let Some(i) = key.as_index() {
                    return match a.dense.get(i as usize) {
                        Some(Value::Empty) | None => None,
                        Some(v) => Some(v.clone()),
                    };
                }
            }
        }
        match o.props.get(key) {
            Some(Prop::Data { value, .. }) => Some(value.clone()),
            _ => None,
        }
    }
    pub fn get_own_str(&self, key: &str) -> Option<Value> {
        self.get_own_data(&PropKey::from_str(key))
    }
    pub fn closure_code(&self) -> Option<Rc<FunctionCode>> {
        match &self.borrow().kind {
            ObjKind::Closure(c) => Some(c.code.clone()),
            _ => None,
        }
    }
}

pub fn new_array_data(dense: Vec<Value>) -> ArrayData {
    let len = dense.len() as u32;
    ArrayData { dense, len, sparse: false, length_writable: true }
}

/// Property descriptor (fields optional) used by defineProperty & friends.
#[derive(Clone, Default)]
pub struct PropDesc {
    pub value: Option<Value>,
    pub writable: Option<bool>,
    pub get: Option<Value>,
    pub set: Option<Value>,
    pub enumerable: Option<bool>,
    pub configurable: Option<bool>,
}

impl PropDesc {
    pub fn data(value: Value, flags: u8) -> PropDesc {
        PropDesc {
            value: Some(value),
            writable: Some(flags & WRITABLE != 0),
            get: None,
            set: None,
            enumerable: Some(flags & ENUMERABLE != 0),
            configurable: Some(flags & CONFIGURABLE != 0),
        }
    }
    pub fn is_accessor(&self) -> bool {
        self.get.is_some() || self.set.is_some()
    }
    pub fn is_data(&self) -> bool {
        self.value.is_some() || self.writable.is_some()
    }
    pub fn is_generic(&self) -> bool {
        !self.is_accessor() && !self.is_data()
    }
    pub fn from_prop(p: &Prop) -> PropDesc {
        match p {
            Prop::Data { value, flags } => PropDesc::data(value.clone(), *flags),
            Prop::Accessor { get, set, flags } => PropDesc {
                value: None,
                writable: None,
                get: Some(get.clone().map(Value::Obj).unwrap_or(Value::Undefined)),
                set: Some(set.clone().map(Value::Obj).unwrap_or(Value::Undefined)),
                enumerable: Some(flags & ENUMERABLE != 0),
                configurable: Some(flags & CONFIGURABLE != 0),
            },
        }
    }
    pub fn flags(&self) -> u8 {
        let mut f = 0;
        if self.writable == Some(true) {
            f |= WRITABLE;
        }
        if self.enumerable == Some(true) {
            f |= ENUMERABLE;
        }
        if self.configurable == Some(true) {
            f |= CONFIGURABLE;
        }
        f
    }
}

/// Move an own property to the end of the insertion order.
pub fn move_to_end(o: &Obj, key: &PropKey) {
    let removed = o.borrow_mut().props.remove(key);
    if let Some(p) = removed {
        o.borrow_mut().props.insert(key.clone(), p);
    }
}
