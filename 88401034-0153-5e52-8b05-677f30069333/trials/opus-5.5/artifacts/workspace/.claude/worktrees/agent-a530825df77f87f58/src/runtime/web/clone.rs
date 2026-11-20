// structuredClone and the byte-level clone serializer (__serializeForClone /
// __deserializeClone) used for cross-thread messages.

use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::collections::HashMap;

pub fn setup(vm: &mut Vm) {
    // `structuredClone(v)` tail-calls its inner `clone(v)`: stacks show `at clone`
    let f = plain_fn_framed(vm, "structuredClone", "clone", 1, structured_clone_fn);
    set_global(vm, "structuredClone", Value::Obj(f));
    let f = plain_fn(vm, "serializeForClone", 1, serialize_fn);
    set_global(vm, "__serializeForClone", Value::Obj(f));
    let f = plain_fn(vm, "deserializeClone", 1, deserialize_fn);
    set_global(vm, "__deserializeClone", Value::Obj(f));
}

fn structured_clone_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut seen: HashMap<usize, Value> = HashMap::new();
    clone_value(vm, &a.arg(0), &mut seen)
}

/// `clone(v)` for a nested value (its own frame on the stack).
fn clone_child(vm: &mut Vm, v: &Value, seen: &mut HashMap<usize, Value>) -> JsResult<Value> {
    with_frame(vm, "clone", |vm| clone_value(vm, v, seen))
}

fn data_clone_error<T>(vm: &mut Vm, msg: &str) -> JsResult<T> {
    throw_dom(vm, msg, "DataCloneError")
}

fn is_view(v: &Value) -> bool {
    match v {
        Value::Obj(o) => matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)),
        _ => false,
    }
}

fn time_clip(t: f64) -> f64 {
    if !t.is_finite() || t.abs() > 8.64e15 {
        return f64::NAN;
    }
    let r = t.trunc();
    if r == 0.0 {
        0.0
    } else {
        r
    }
}

fn new_date(vm: &mut Vm, t: f64) -> Value {
    Value::Obj(Obj::with_class(Some(vm.intr.date_proto.clone()), ObjKind::Date(time_clip(t)), "Date"))
}

fn new_set(vm: &Vm) -> Obj {
    Obj::with_class(Some(vm.intr.set_proto.clone()), ObjKind::Set(Box::new(OrderedMap::new())), "Set")
}

fn map_insert(m: &Obj, k: Value, v: Value) {
    if let ObjKind::Map(mm) = &mut m.borrow_mut().kind {
        mm.set(k, v);
    }
}

fn set_insert(s: &Obj, v: Value) {
    if let ObjKind::Set(ss) = &mut s.borrow_mut().kind {
        ss.set(v.clone(), v);
    }
}

/// `structuredClone(value)` (the reference's JS algorithm; no transfer list).
pub fn structured_clone(vm: &mut Vm, v: &Value) -> JsResult<Value> {
    let mut seen: HashMap<usize, Value> = HashMap::new();
    with_frame(vm, "clone", |vm| clone_value(vm, v, &mut seen))
}

fn clone_value(vm: &mut Vm, v: &Value, seen: &mut HashMap<usize, Value>) -> JsResult<Value> {
    if v.type_of() == "function" || matches!(v, Value::Sym(_)) {
        return data_clone_error(vm, "value could not be cloned");
    }
    let o = match v {
        Value::Obj(o) => o.clone(),
        _ => return Ok(v.clone()),
    };
    if let Some(c) = seen.get(&o.addr()) {
        return Ok(c.clone());
    }
    let dp = vm.intr.date_proto.clone();
    if has_in_chain(vm, v, &dp)? {
        let t = invoke(vm, v, "getTime", &[])?;
        let n = vm.to_number(&t)?;
        return Ok(new_date(vm, n));
    }
    let rp = vm.intr.regexp_proto.clone();
    if has_in_chain(vm, v, &rp)? {
        let src = get(vm, v, "source")?;
        let flags = get(vm, v, "flags")?;
        return crate::builtins::regexp::regexp_create(vm, &src, &flags);
    }
    let pp = vm.intr.promise_proto.clone();
    if has_in_chain(vm, v, &pp)? {
        return data_clone_error(vm, "a Promise cannot be cloned");
    }
    let abp = vm.intr.array_buffer_proto.clone();
    if has_in_chain(vm, v, &abp)? {
        let c = invoke(vm, v, "slice", &[Value::Num(0.0)])?;
        seen.insert(o.addr(), c.clone());
        return Ok(c);
    }
    let dvp = vm.intr.data_view_proto.clone();
    if is_view(v) && !has_in_chain(vm, v, &dvp)? {
        let ctor = get(vm, v, "constructor")?;
        let c = vm.construct(&ctor, &[v.clone()], None)?;
        seen.insert(o.addr(), c.clone());
        return Ok(c);
    }
    let mp = vm.intr.map_proto.clone();
    if has_in_chain(vm, v, &mp)? {
        let m = new_map(vm);
        seen.insert(o.addr(), Value::Obj(m.clone()));
        let entries = vm.iterate_to_vec(v)?;
        for e in entries {
            let k = get_key(vm, &e, &PropKey::from_index(0))?;
            let val = get_key(vm, &e, &PropKey::from_index(1))?;
            let ck = clone_child(vm, &k, seen)?;
            let cv = clone_child(vm, &val, seen)?;
            map_insert(&m, ck, cv);
        }
        return Ok(Value::Obj(m));
    }
    let sp = vm.intr.set_proto.clone();
    if has_in_chain(vm, v, &sp)? {
        let s = new_set(vm);
        seen.insert(o.addr(), Value::Obj(s.clone()));
        let items = vm.iterate_to_vec(v)?;
        for it in items {
            let c = clone_child(vm, &it, seen)?;
            set_insert(&s, c);
        }
        return Ok(Value::Obj(s));
    }
    let ep = vm.intr.error_proto.clone();
    if has_in_chain(vm, v, &ep)? {
        let c = get(vm, v, "constructor")?;
        let ctor = if c.is_callable() { c } else { Value::Obj(error_ctor(vm)) };
        let msg = get(vm, v, "message")?;
        let e = vm.construct(&ctor, &[msg], None)?;
        let name = get(vm, v, "name")?;
        set(vm, &e, "name", name)?;
        seen.insert(o.addr(), e.clone());
        return Ok(e);
    }
    if crate::builtins::array::is_array(vm, v)? {
        let arr = vm.new_array(Vec::new());
        let av = Value::Obj(arr.clone());
        seen.insert(o.addr(), av.clone());
        let mut i: u64 = 0;
        loop {
            let len = get(vm, v, "length")?;
            let len = vm.to_number(&len)?;
            if !((i as f64) < len) {
                break;
            }
            let k = PropKey::from_index(i as u32);
            if vm.has_property(&o, &k)? {
                let item = vm.get(&o, &k, v)?;
                let c = clone_child(vm, &item, seen)?;
                vm.set_prop_of(&av, k, c, true)?;
            }
            i += 1;
        }
        return Ok(av);
    }
    let out = vm.new_object();
    let ov = Value::Obj(out.clone());
    seen.insert(o.addr(), ov.clone());
    let keys = vm.enumerable_own_keys(&o)?;
    for k in keys {
        let pk = PropKey::Str(k);
        let item = vm.get(&o, &pk, v)?;
        let c = clone_child(vm, &item, seen)?;
        vm.set_prop_of(&ov, pk, c, true)?;
    }
    Ok(ov)
}

fn error_ctor(vm: &mut Vm) -> Obj {
    match vm.intr.error_proto.get_own_str("constructor") {
        Some(Value::Obj(c)) => c,
        _ => vm.intr.object_proto.clone(),
    }
}

// ---------------------------------------------------------------------------------------------
// byte serializer
// ---------------------------------------------------------------------------------------------

const T_UNDEFINED: u8 = 0;
const T_NULL: u8 = 1;
const T_FALSE: u8 = 2;
const T_TRUE: u8 = 3;
const T_NUMBER: u8 = 4;
const T_STRING: u8 = 5;
const T_BIGINT: u8 = 6;
const T_REF: u8 = 7;
const T_ARRAY: u8 = 8;
const T_OBJECT: u8 = 9;
const T_DATE: u8 = 10;
const T_REGEXP: u8 = 11;
const T_MAP: u8 = 12;
const T_SET: u8 = 13;
const T_ARRAYBUFFER: u8 = 14;
const T_TYPEDARRAY: u8 = 15;
const T_DATAVIEW: u8 = 16;
const T_ERROR: u8 = 17;
const T_BOOLOBJ: u8 = 18;
const T_NUMOBJ: u8 = 19;
const T_STROBJ: u8 = 20;

const TA_KINDS: [&str; 11] = [
    "Int8Array",
    "Uint8Array",
    "Uint8ClampedArray",
    "Int16Array",
    "Uint16Array",
    "Int32Array",
    "Uint32Array",
    "Float32Array",
    "Float64Array",
    "BigInt64Array",
    "BigUint64Array",
];
const ERROR_NAMES: [&str; 7] = ["Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "EvalError", "URIError"];

struct Ser {
    out: Vec<u8>,
    memory: HashMap<usize, u32>,
}

impl Ser {
    fn u8(&mut self, n: u8) {
        self.out.push(n);
    }
    fn u32(&mut self, n: u32) {
        self.out.extend_from_slice(&n.to_le_bytes());
    }
    fn f64(&mut self, n: f64) {
        self.out.extend_from_slice(&n.to_le_bytes());
    }
    fn raw(&mut self, b: &[u8]) {
        self.out.extend_from_slice(b);
    }
}

fn ser_str(vm: &mut Vm, s: &mut Ser, v: &Value) -> JsResult<()> {
    let st = js_string(vm, v)?;
    let enc = super::encoding::engine_utf8(st.units());
    s.u32(enc.len() as u32);
    s.raw(&enc);
    Ok(())
}

fn to_u32(vm: &mut Vm, v: &Value) -> JsResult<u32> {
    vm.to_uint32(v)
}

fn ser_write(vm: &mut Vm, s: &mut Ser, v: &Value) -> JsResult<()> {
    match v {
        Value::Undefined | Value::Empty => {
            s.u8(T_UNDEFINED);
            return Ok(());
        }
        Value::Null => {
            s.u8(T_NULL);
            return Ok(());
        }
        Value::Bool(b) => {
            s.u8(if *b { T_TRUE } else { T_FALSE });
            return Ok(());
        }
        Value::Num(n) => {
            s.u8(T_NUMBER);
            s.f64(*n);
            return Ok(());
        }
        Value::Str(_) => {
            s.u8(T_STRING);
            return ser_str(vm, s, v);
        }
        Value::BigInt(b) => {
            s.u8(T_BIGINT);
            let t = Value::str(&b.to_string_radix(10));
            return ser_str(vm, s, &t);
        }
        Value::Sym(_) => return data_clone_error(vm, "value could not be cloned"),
        Value::Obj(_) => {}
    }
    if v.type_of() == "function" {
        return data_clone_error(vm, "value could not be cloned");
    }
    let o = v.as_obj().unwrap().clone();
    if let Some(r) = s.memory.get(&o.addr()) {
        let r = *r;
        s.u8(T_REF);
        s.u32(r);
        return Ok(());
    }
    let r = s.memory.len() as u32;
    let dp = vm.intr.date_proto.clone();
    if has_in_chain(vm, v, &dp)? {
        s.u8(T_DATE);
        let t = invoke(vm, v, "getTime", &[])?;
        let n = vm.to_number(&t)?;
        s.f64(n);
        return Ok(());
    }
    let rp = vm.intr.regexp_proto.clone();
    if has_in_chain(vm, v, &rp)? {
        s.u8(T_REGEXP);
        let src = get(vm, v, "source")?;
        ser_str(vm, s, &src)?;
        let flags = get(vm, v, "flags")?;
        return ser_str(vm, s, &flags);
    }
    let pp = vm.intr.promise_proto.clone();
    if has_in_chain(vm, v, &pp)? {
        return data_clone_error(vm, "a Promise cannot be cloned");
    }
    let abp = vm.intr.array_buffer_proto.clone();
    if has_in_chain(vm, v, &abp)? {
        s.memory.insert(o.addr(), r);
        s.u8(T_ARRAYBUFFER);
        let bytes = crate::builtins::typedarray::ta_bytes(&o);
        s.u32(bytes.len() as u32);
        s.raw(&bytes);
        return Ok(());
    }
    let dvp = vm.intr.data_view_proto.clone();
    if has_in_chain(vm, v, &dvp)? {
        s.memory.insert(o.addr(), r);
        s.u8(T_DATAVIEW);
        let bo = get(vm, v, "byteOffset")?;
        let bo = to_u32(vm, &bo)?;
        s.u32(bo);
        let bl = get(vm, v, "byteLength")?;
        let bl = to_u32(vm, &bl)?;
        s.u32(bl);
        let buf = get(vm, v, "buffer")?;
        return ser_write(vm, s, &buf);
    }
    if is_view(v) {
        let ctor = get(vm, v, "constructor")?;
        let name = get(vm, &ctor, "name")?;
        let kind = match &name {
            Value::Str(n) => TA_KINDS.iter().position(|k| n.eq_str(k)),
            _ => None,
        };
        let kind = match kind {
            Some(k) => k,
            None => return data_clone_error(vm, "unsupported typed array"),
        };
        s.memory.insert(o.addr(), r);
        s.u8(T_TYPEDARRAY);
        s.u8(kind as u8);
        let bo = get(vm, v, "byteOffset")?;
        let bo = to_u32(vm, &bo)?;
        s.u32(bo);
        let l = get(vm, v, "length")?;
        let l = to_u32(vm, &l)?;
        s.u32(l);
        let buf = get(vm, v, "buffer")?;
        return ser_write(vm, s, &buf);
    }
    let mp = vm.intr.map_proto.clone();
    if has_in_chain(vm, v, &mp)? {
        s.memory.insert(o.addr(), r);
        s.u8(T_MAP);
        let size = get(vm, v, "size")?;
        let size = to_u32(vm, &size)?;
        s.u32(size);
        for e in vm.iterate_to_vec(v)? {
            let k = get_key(vm, &e, &PropKey::from_index(0))?;
            let val = get_key(vm, &e, &PropKey::from_index(1))?;
            ser_write(vm, s, &k)?;
            ser_write(vm, s, &val)?;
        }
        return Ok(());
    }
    let sp = vm.intr.set_proto.clone();
    if has_in_chain(vm, v, &sp)? {
        s.memory.insert(o.addr(), r);
        s.u8(T_SET);
        let size = get(vm, v, "size")?;
        let size = to_u32(vm, &size)?;
        s.u32(size);
        for it in vm.iterate_to_vec(v)? {
            ser_write(vm, s, &it)?;
        }
        return Ok(());
    }
    let ep = vm.intr.error_proto.clone();
    if has_in_chain(vm, v, &ep)? {
        s.memory.insert(o.addr(), r);
        s.u8(T_ERROR);
        let name = get(vm, v, "name")?;
        let idx = match &name {
            Value::Str(n) => ERROR_NAMES.iter().position(|k| n.eq_str(k)).unwrap_or(0),
            _ => 0,
        };
        s.u8(idx as u8);
        let msg = get(vm, v, "message")?;
        ser_str(vm, s, &msg)?;
        let stack = get(vm, v, "stack")?;
        let stack = if stack.is_nullish() { Value::str("") } else { stack };
        return ser_str(vm, s, &stack);
    }
    let ots = get(vm, &Value::Obj(vm.intr.object_proto.clone()), "toString")?;
    let tag = vm.call(&ots, v.clone(), &[])?;
    let tag = match &tag {
        Value::Str(t) => t.to_rust_string(),
        _ => String::new(),
    };
    if tag == "[object Boolean]" {
        s.memory.insert(o.addr(), r);
        s.u8(T_BOOLOBJ);
        let b = invoke(vm, v, "valueOf", &[])?;
        s.u8(if b.truthy() { 1 } else { 0 });
        return Ok(());
    }
    if tag == "[object Number]" {
        s.memory.insert(o.addr(), r);
        s.u8(T_NUMOBJ);
        let n = invoke(vm, v, "valueOf", &[])?;
        let n = vm.to_number(&n)?;
        s.f64(n);
        return Ok(());
    }
    if tag == "[object String]" {
        s.memory.insert(o.addr(), r);
        s.u8(T_STROBJ);
        let st = invoke(vm, v, "valueOf", &[])?;
        return ser_str(vm, s, &st);
    }
    if crate::builtins::array::is_array(vm, v)? {
        s.memory.insert(o.addr(), r);
        s.u8(T_ARRAY);
        let len = get(vm, v, "length")?;
        let len = to_u32(vm, &len)?;
        s.u32(len);
        let mut i: u64 = 0;
        loop {
            let l = get(vm, v, "length")?;
            let l = vm.to_number(&l)?;
            if !((i as f64) < l) {
                break;
            }
            let item = vm.get(&o, &PropKey::from_index(i as u32), v)?;
            ser_write(vm, s, &item)?;
            i += 1;
        }
        return Ok(());
    }
    s.memory.insert(o.addr(), r);
    s.u8(T_OBJECT);
    let keys = vm.enumerable_own_keys(&o)?;
    s.u32(keys.len() as u32);
    for k in keys {
        let kv = Value::Str(k.clone());
        ser_str(vm, s, &kv)?;
        let item = vm.get(&o, &PropKey::Str(k), v)?;
        ser_write(vm, s, &item)?;
    }
    Ok(())
}

fn serialize_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut s = Ser { out: Vec::new(), memory: HashMap::new() };
    ser_write(vm, &mut s, &a.arg(0))?;
    let len = s.out.len();
    let mut cap = 64;
    while cap < len {
        cap *= 2;
    }
    let mut bytes = s.out;
    bytes.resize(cap, 0);
    let full = crate::builtins::typedarray::typed_array_from_bytes(vm, bytes);
    if let ObjKind::TypedArray(t) = &mut full.borrow_mut().kind {
        t.length = Some(len);
    }
    Ok(Value::Obj(full))
}

struct De {
    bytes: Vec<u8>,
    pos: usize,
    memory: Vec<Value>,
}

fn oob<T>(vm: &mut Vm) -> JsResult<T> {
    vm.throw_range("Offset is outside the bounds of the DataView")
}

impl De {
    fn u8(&mut self) -> Option<u8> {
        let b = self.bytes.get(self.pos).copied();
        self.pos += 1;
        b
    }
}

fn de_u32(vm: &mut Vm, d: &mut De) -> JsResult<u32> {
    if d.pos + 4 > d.bytes.len() {
        return oob(vm);
    }
    let n = u32::from_le_bytes([d.bytes[d.pos], d.bytes[d.pos + 1], d.bytes[d.pos + 2], d.bytes[d.pos + 3]]);
    d.pos += 4;
    Ok(n)
}

fn de_f64(vm: &mut Vm, d: &mut De) -> JsResult<f64> {
    if d.pos + 8 > d.bytes.len() {
        return oob(vm);
    }
    let mut b = [0u8; 8];
    b.copy_from_slice(&d.bytes[d.pos..d.pos + 8]);
    d.pos += 8;
    Ok(f64::from_le_bytes(b))
}

fn de_str(vm: &mut Vm, d: &mut De) -> JsResult<Value> {
    let len = de_u32(vm, d)? as usize;
    let start = d.pos.min(d.bytes.len());
    let end = d.pos.saturating_add(len).min(d.bytes.len());
    let s = super::encoding::decode_default(&d.bytes[start..end]);
    d.pos += len;
    Ok(Value::Str(s))
}

fn global_ctor(vm: &mut Vm, name: &str) -> JsResult<Value> {
    global_get(vm, name)
}

fn de_read(vm: &mut Vm, d: &mut De) -> JsResult<Value> {
    let tag = d.u8();
    match tag {
        Some(T_UNDEFINED) => Ok(Value::Undefined),
        Some(T_NULL) => Ok(Value::Null),
        Some(T_FALSE) => Ok(Value::Bool(false)),
        Some(T_TRUE) => Ok(Value::Bool(true)),
        Some(T_NUMBER) => Ok(Value::Num(de_f64(vm, d)?)),
        Some(T_STRING) => de_str(vm, d),
        Some(T_BIGINT) => {
            let s = de_str(vm, d)?;
            let f = global_ctor(vm, "BigInt")?;
            vm.call(&f, Value::Undefined, &[s])
        }
        Some(T_REF) => {
            let i = de_u32(vm, d)? as usize;
            Ok(d.memory.get(i).cloned().unwrap_or(Value::Undefined))
        }
        Some(T_DATE) => {
            let t = de_f64(vm, d)?;
            Ok(new_date(vm, t))
        }
        Some(T_REGEXP) => {
            let src = de_str(vm, d)?;
            let flags = de_str(vm, d)?;
            crate::builtins::regexp::regexp_create(vm, &src, &flags)
        }
        Some(T_ARRAYBUFFER) => {
            let len = de_u32(vm, d)? as usize;
            if len > (1usize << 30) {
                return vm.throw_range("ArrayBuffer allocation too large");
            }
            let mut bytes = vec![0u8; len];
            let start = d.pos.min(d.bytes.len());
            let end = d.pos.saturating_add(len).min(d.bytes.len());
            bytes[..end - start].copy_from_slice(&d.bytes[start..end]);
            d.pos += len;
            let ab = Value::Obj(crate::builtins::typedarray::new_array_buffer(vm, bytes));
            d.memory.push(ab.clone());
            Ok(ab)
        }
        Some(T_DATAVIEW) => {
            let bo = de_u32(vm, d)?;
            let bl = de_u32(vm, d)?;
            let ctor = global_ctor(vm, "DataView")?;
            let buf = de_read(vm, d)?;
            let dv = vm.construct(&ctor, &[buf, Value::Num(bo as f64), Value::Num(bl as f64)], None)?;
            d.memory.push(dv.clone());
            Ok(dv)
        }
        Some(T_TYPEDARRAY) => {
            let kind = d.u8().map(|k| k as usize).unwrap_or(usize::MAX);
            let bo = de_u32(vm, d)?;
            let len = de_u32(vm, d)?;
            let name = TA_KINDS.get(kind).copied().unwrap_or("undefined");
            let ctor = global_ctor(vm, name)?;
            let buf = de_read(vm, d)?;
            let ta = vm.construct(&ctor, &[buf, Value::Num(bo as f64), Value::Num(len as f64)], None)?;
            d.memory.push(ta.clone());
            Ok(ta)
        }
        Some(T_MAP) => {
            let m = new_map(vm);
            d.memory.push(Value::Obj(m.clone()));
            let n = de_u32(vm, d)?;
            for _ in 0..n {
                let k = de_read(vm, d)?;
                let v = de_read(vm, d)?;
                map_insert(&m, k, v);
            }
            Ok(Value::Obj(m))
        }
        Some(T_SET) => {
            let s = new_set(vm);
            d.memory.push(Value::Obj(s.clone()));
            let n = de_u32(vm, d)?;
            for _ in 0..n {
                let v = de_read(vm, d)?;
                set_insert(&s, v);
            }
            Ok(Value::Obj(s))
        }
        Some(T_ERROR) => {
            let idx = d.u8().map(|k| k as usize).unwrap_or(usize::MAX);
            let name = ERROR_NAMES.get(idx).copied().unwrap_or("undefined");
            let c = global_ctor(vm, name)?;
            let ctor = if c.is_nullish() { Value::Obj(error_ctor(vm)) } else { c };
            let msg = de_str(vm, d)?;
            let e = vm.construct(&ctor, &[msg], None)?;
            let stack = de_str(vm, d)?;
            set(vm, &e, "stack", stack)?;
            d.memory.push(e.clone());
            Ok(e)
        }
        Some(T_BOOLOBJ) => {
            let b = d.u8() == Some(1);
            let o = vm.to_object(&Value::Bool(b))?;
            d.memory.push(Value::Obj(o.clone()));
            Ok(Value::Obj(o))
        }
        Some(T_NUMOBJ) => {
            let n = de_f64(vm, d)?;
            let o = vm.to_object(&Value::Num(n))?;
            d.memory.push(Value::Obj(o.clone()));
            Ok(Value::Obj(o))
        }
        Some(T_STROBJ) => {
            let s = de_str(vm, d)?;
            let o = vm.to_object(&s)?;
            d.memory.push(Value::Obj(o.clone()));
            Ok(Value::Obj(o))
        }
        Some(T_ARRAY) => {
            let arr = vm.new_array(Vec::new());
            let av = Value::Obj(arr);
            d.memory.push(av.clone());
            let len = de_u32(vm, d)?;
            for i in 0..len {
                let v = de_read(vm, d)?;
                vm.set_prop_of(&av, PropKey::from_index(i), v, true)?;
            }
            Ok(av)
        }
        Some(T_OBJECT) => {
            let o = vm.new_object();
            let ov = Value::Obj(o);
            d.memory.push(ov.clone());
            let n = de_u32(vm, d)?;
            for _ in 0..n {
                let k = de_str(vm, d)?;
                let v = de_read(vm, d)?;
                let pk = vm.to_property_key(&k)?;
                vm.set_prop_of(&ov, pk, v, true)?;
            }
            Ok(ov)
        }
        _ => data_clone_error(vm, "malformed clone data"),
    }
}

fn deserialize_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let buf = a.arg(0);
    let ab = get(vm, &buf, "buffer")?;
    let is_ab = matches!(&ab, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::ArrayBuffer(_)));
    if !is_ab {
        return vm.throw_type("DataView requires an ArrayBuffer");
    }
    let bytes = match &buf {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(_) | ObjKind::DataView(_) => None,
            _ => Some(Vec::new()),
        },
        _ => Some(Vec::new()),
    };
    let bytes = match bytes {
        Some(b) => b,
        None => crate::builtins::typedarray::ta_bytes(buf.as_obj().unwrap()),
    };
    let mut d = De { bytes, pos: 0, memory: Vec::new() };
    de_read(vm, &mut d)
}
