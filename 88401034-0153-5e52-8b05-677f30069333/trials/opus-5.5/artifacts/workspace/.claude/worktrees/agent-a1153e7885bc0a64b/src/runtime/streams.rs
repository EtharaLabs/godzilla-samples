// Web streams: ReadableStream / WritableStream / TransformStream and friends, the queuing
// strategies, TextEncoderStream / TextDecoderStream and CompressionStream / DecompressionStream.
//
// The reference runtime uses a deliberately simple, buffered stream model rather than the full
// WHATWG machinery: chunks are queued in a plain array, `pull` is invoked synchronously and its
// result ignored, writes are serialised on a promise chain, and so on.  Everything here follows
// that model.  All instance state lives in ordinary own properties (`_chunks`, `_state`, ...) and
// every step goes through regular property access, method invocation and promise reactions, so
// that both introspection (`Object.keys(stream)`) and the microtask timing of reads/writes line
// up with the reference.

use crate::builtins::promise::{perform_then_internal, promise_resolve_intrinsic};
use crate::compress::Codec;
use crate::object::*;
use crate::value::*;
use crate::vm::{Job, JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::VecDeque;
use std::rc::Rc;

// =====================================================================================
// Small "JS semantics" helpers shared with fetch.rs
// =====================================================================================

#[allow(dead_code)]
pub fn key(k: &str) -> PropKey {
    PropKey::from_str(k)
}

/// `base[k]` (GetV: works on primitives, throws on null/undefined).
pub fn get(vm: &mut Vm, base: &Value, k: &str) -> JsResult<Value> {
    vm.get_prop_of(base, &PropKey::from_str(k))
}

/// `base[sym]`
pub fn get_sym(vm: &mut Vm, base: &Value, s: &Sym) -> JsResult<Value> {
    vm.get_prop_of(base, &PropKey::Sym(s.clone()))
}

/// `base[k] = v` (strict-mode assignment).
pub fn put(vm: &mut Vm, base: &Value, k: &str, v: Value) -> JsResult<()> {
    vm.set_prop_of(base, PropKey::from_str(k), v, true)
}

/// `base[sym] = v`
pub fn put_sym(vm: &mut Vm, base: &Value, s: &Sym, v: Value) -> JsResult<()> {
    vm.set_prop_of(base, PropKey::Sym(s.clone()), v, true)
}

/// Call an already-fetched method value the way `obj.name(...args)` would.
pub fn call_method(vm: &mut Vm, f: &Value, this: &Value, name: &str, args: &[Value]) -> JsResult<Value> {
    if !f.is_callable() {
        return vm.throw_type(format!("(intermediate value).{} is not a function", name));
    }
    vm.call(f, this.clone(), args)
}

/// `base.name(...args)`
pub fn invoke(vm: &mut Vm, base: &Value, name: &str, args: &[Value]) -> JsResult<Value> {
    let f = get(vm, base, name)?;
    call_method(vm, &f, base, name, args)
}

pub fn is_str(v: &Value, s: &str) -> bool {
    matches!(v, Value::Str(x) if x.eq_str(s))
}

pub fn new_obj(vm: &mut Vm) -> Value {
    Value::Obj(vm.new_object())
}

pub fn new_arr(vm: &mut Vm, items: Vec<Value>) -> Value {
    Value::Obj(vm.new_array(items))
}

/// `{ value, done }`
pub fn iter_result(vm: &mut Vm, value: Value, done: bool) -> Value {
    Value::Obj(vm.obj_from(vec![("value", value), ("done", Value::Bool(done))]))
}

pub fn type_error(vm: &mut Vm, msg: &str) -> Value {
    vm.make_error("TypeError", msg)
}

/// `String(v)` (symbols allowed).
pub fn js_string(vm: &mut Vm, v: &Value) -> JsResult<JsStr> {
    match v {
        Value::Sym(s) => Ok(JsStr::from_str(&s.descriptive_string())),
        _ => vm.to_string(v),
    }
}

/// A function object closing over `slots` (an arrow function / method of an object literal).
pub fn func(vm: &mut Vm, name: &str, len: u32, f: NativeFn, slots: Vec<Value>) -> Value {
    Value::Obj(vm.native_closure(name, len, f, slots))
}

fn noop_native(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

/// `() => {}`
pub fn noop_fn(vm: &mut Vm) -> Value {
    func(vm, "", 0, noop_native, vec![])
}

/// `Promise.resolve(v)`
pub fn resolved(vm: &mut Vm, v: Value) -> JsResult<Value> {
    Ok(Value::Obj(promise_resolve_intrinsic(vm, v)?))
}

/// `Promise.reject(e)`
pub fn rejected(vm: &mut Vm, e: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
    cap.promise
}

/// Resolve/reject a capability from a completion.
pub fn settle(vm: &mut Vm, cap: &Capability, r: JsResult<Value>) {
    let _ = match r {
        Ok(v) => vm.call(&cap.resolve, Value::Undefined, &[v]),
        Err(e) => vm.call(&cap.reject, Value::Undefined, &[e]),
    };
}

/// Continuation of an emulated `await`: receives the settled value and the coroutine data.
pub type Cont = fn(&mut Vm, Value, &Value) -> JsResult<Value>;

/// `await v` inside an emulated async function: exactly one PerformPromiseThen on
/// PromiseResolve(v), without a derived promise (the same reaction count as a real `await`).
pub fn await_value(vm: &mut Vm, v: Value, data: &Value, ok: Cont, err: Cont) {
    match promise_resolve_intrinsic(vm, v) {
        Ok(p) => perform_then_internal(vm, &p, Handler::Native(ok, data.clone()), Handler::Native(err, data.clone()), None),
        Err(e) => vm.jobs.push_back(Job::Reaction(Reaction { capability: None, is_reject: true, handler: Handler::Native(err, data.clone()) }, e)),
    }
}

/// Wrap Rust state for use as coroutine data / closure slot.
pub fn host<T: 'static>(v: Rc<T>) -> Value {
    Value::Obj(Obj::new(None, ObjKind::Host(Box::new(v))))
}

pub fn unhost<T: 'static>(v: &Value) -> Rc<T> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(r) = h.downcast_ref::<Rc<T>>() {
                return r.clone();
            }
        }
    }
    panic!("streams: bad host data")
}

/// Class-constructor prologue: requires `new`, creates `this` from new.target's prototype.
pub fn new_this(vm: &mut Vm, a: &Args, fallback: &Obj) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Class constructor cannot be invoked without 'new'");
    }
    let proto = vm.proto_from_nt(&a.new_target, fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Ordinary)))
}

pub fn construct(vm: &mut Vm, ctor: &Obj, args: &[Value]) -> JsResult<Value> {
    vm.construct(&Value::Obj(ctor.clone()), args, None)
}

/// Look up a global binding (e.g. a class provided by another part of the runtime).
pub fn global(vm: &mut Vm, name: &str) -> Value {
    let g = vm.global.clone();
    vm.get_str(&g, name).unwrap_or(Value::Undefined)
}

pub fn class_ctor(vm: &mut Vm, name: &str, len: u32, f: NativeFn, proto: &Obj) -> Obj {
    vm.native_ctor(name, len, f, proto)
}

pub fn method(vm: &mut Vm, target: &Obj, name: &str, len: u32, f: NativeFn) -> Obj {
    vm.def_method(target, name, len, f)
}

pub fn getter(vm: &mut Vm, target: &Obj, name: &str, f: NativeFn) {
    vm.def_getter(target, name, f);
}

pub fn tag_getter(vm: &mut Vm, target: &Obj, f: NativeFn) {
    let s = vm.intr.sym_to_string_tag.clone();
    vm.def_sym_getter(target, &s, "[Symbol.toStringTag]", f);
}

pub fn add(vm: &mut Vm, v: &Value, n: f64) -> JsResult<Value> {
    vm.op_add(v, &Value::Num(n))
}

pub fn sub(vm: &mut Vm, v: &Value, n: f64) -> JsResult<Value> {
    let x = vm.to_numeric(v)?;
    match x {
        Value::Num(f) => Ok(Value::Num(f - n)),
        _ => vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
    }
}

// ---------------- bytes / typed arrays ----------------

pub const MAX_TA: usize = 1048576;

/// A fresh plain `Uint8Array` (engine-wide 1 MiB typed array cap applies).
pub fn new_u8(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    if bytes.len() > MAX_TA {
        return vm.throw_range("Invalid typed array length");
    }
    Ok(Value::Obj(crate::builtins::typedarray::typed_array_from_bytes(vm, bytes)))
}

pub fn is_array_buffer(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(&o.borrow().kind, ObjKind::ArrayBuffer(b) if !b.borrow().shared))
}

/// `ArrayBuffer.isView(v)`
pub fn is_view(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)))
}

pub fn is_typed_array(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_)))
}

/// Bytes of an ArrayBuffer / TypedArray / DataView (empty otherwise).
pub fn bytes_of_buffer_source(v: &Value) -> Vec<u8> {
    match v {
        Value::Obj(o) => crate::builtins::typedarray::ta_bytes(o),
        _ => Vec::new(),
    }
}

/// `new Uint8Array(view.buffer, view.byteOffset, view.byteLength)` for a view, or
/// `new Uint8Array(ab)` for an ArrayBuffer: a Uint8Array sharing the memory.
pub fn u8_view_of(vm: &mut Vm, v: &Value) -> Option<Value> {
    let o = v.as_obj()?;
    let (buffer, buf, offset, len) = {
        let b = o.borrow();
        match &b.kind {
            ObjKind::TypedArray(t) => {
                let len = t.len() * t.kind.size();
                (t.buffer.clone(), t.buf.clone(), t.offset, len)
            }
            ObjKind::DataView(d) => {
                let blen = d.buf.borrow().bytes.len();
                let len = d.length.unwrap_or(blen.saturating_sub(d.offset));
                (d.buffer.clone(), d.buf.clone(), d.offset, len)
            }
            ObjKind::ArrayBuffer(bd) => {
                let len = bd.borrow().bytes.len();
                (o.clone(), bd.clone(), 0, len)
            }
            _ => return None,
        }
    };
    let p = vm.intr.ta_protos[1].clone();
    Some(Value::Obj(Obj::with_class(
        Some(p),
        ObjKind::TypedArray(Box::new(TypedArrayData { kind: TAKind::Uint8, buffer, buf, offset, length: Some(len) })),
        "Uint8Array",
    )))
}

/// Is `v` an object whose prototype chain contains `%Uint8Array.prototype%`?
pub fn is_uint8array(vm: &mut Vm, v: &Value) -> bool {
    let ctor = Value::Obj(vm.intr.ta_ctors[1].clone());
    vm.instance_of(v, &ctor).unwrap_or(false)
}

// ---------------- private UTF-8 codec (matches the reference runtime's string encoding) -----

/// String -> UTF-8.  Lone surrogates U+D800+k are written as the code point U+10F800+k (the
/// reference runtime's internal encoding), which `utf8_to_str` maps back.
pub fn str_to_utf8(units: &[u16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(units.len());
    let mut i = 0;
    while i < units.len() {
        let u = units[i] as u32;
        let cp = if (0xD800..0xDC00).contains(&u) && i + 1 < units.len() && (0xDC00..0xE000).contains(&(units[i + 1] as u32)) {
            i += 1;
            0x10000 + ((u - 0xD800) << 10) + (units[i] as u32 - 0xDC00)
        } else if (0xD800..0xE000).contains(&u) {
            0x10F800 + (u - 0xD800)
        } else {
            u
        };
        push_utf8(&mut out, cp);
        i += 1;
    }
    out
}

fn push_utf8(out: &mut Vec<u8>, cp: u32) {
    if cp < 0x80 {
        out.push(cp as u8);
    } else if cp < 0x800 {
        out.push(0xC0 | (cp >> 6) as u8);
        out.push(0x80 | (cp & 0x3F) as u8);
    } else if cp < 0x10000 {
        out.push(0xE0 | (cp >> 12) as u8);
        out.push(0x80 | ((cp >> 6) & 0x3F) as u8);
        out.push(0x80 | (cp & 0x3F) as u8);
    } else {
        out.push(0xF0 | (cp >> 18) as u8);
        out.push(0x80 | ((cp >> 12) & 0x3F) as u8);
        out.push(0x80 | ((cp >> 6) & 0x3F) as u8);
        out.push(0x80 | (cp & 0x3F) as u8);
    }
}

/// UTF-8 -> string units.  `None` when `fatal` and the input is malformed; otherwise malformed
/// sequences become U+FFFD (maximal-subpart replacement).
pub fn utf8_to_str(bytes: &[u8], fatal: bool) -> Option<Vec<u16>> {
    let mut out: Vec<u16> = Vec::with_capacity(bytes.len());
    let mut rest = bytes;
    loop {
        match std::str::from_utf8(rest) {
            Ok(s) => {
                push_units(&mut out, s);
                break;
            }
            Err(e) => {
                let good = e.valid_up_to();
                push_units(&mut out, unsafe_free_str(&rest[..good]));
                if fatal {
                    return None;
                }
                out.push(0xFFFD);
                let skip = e.error_len().unwrap_or(rest.len() - good);
                rest = &rest[good + skip..];
                if rest.is_empty() {
                    break;
                }
            }
        }
    }
    Some(out)
}

fn unsafe_free_str(b: &[u8]) -> &str {
    std::str::from_utf8(b).unwrap_or("")
}

fn push_units(out: &mut Vec<u16>, s: &str) {
    for c in s.chars() {
        let cp = c as u32;
        if cp >= 0x10F800 {
            out.push((cp - 0x10F800 + 0xD800) as u16);
        } else {
            let mut b = [0u16; 2];
            out.extend_from_slice(c.encode_utf16(&mut b));
        }
    }
}

/// `new TextDecoder().decode(bytes)` (non-fatal, BOM stripped).
pub fn decode_text(bytes: &[u8]) -> JsStr {
    let mut u = utf8_to_str(bytes, false).unwrap_or_default();
    if u.first() == Some(&0xFEFF) {
        u.remove(0);
    }
    JsStr::from_units(u)
}

// =====================================================================================
// Module state
// =====================================================================================

pub struct Ctx {
    pub k_stream: Sym,
    pub k_ws: Sym,
    pub k_ts: Sym,
    pub rs: Obj,
    pub rs_proto: Obj,
    pub reader: Obj,
    pub reader_proto: Obj,
    pub ctrl: Obj,
    pub ctrl_proto: Obj,
    pub byob_reader: Obj,
    pub byob_reader_proto: Obj,
    pub byte_ctrl: Obj,
    pub byte_ctrl_proto: Obj,
    pub byob_req: Obj,
    pub byob_req_proto: Obj,
    pub ws: Obj,
    pub ws_proto: Obj,
    pub writer: Obj,
    pub writer_proto: Obj,
    pub wctrl: Obj,
    pub wctrl_proto: Obj,
    pub ts: Obj,
    pub ts_proto: Obj,
    pub tsctrl: Obj,
    pub tsctrl_proto: Obj,
    pub bl_proto: Obj,
    pub cq_proto: Obj,
    pub tes_proto: Obj,
    pub tds_proto: Obj,
    pub cs_proto: Obj,
    pub ds_proto: Obj,
    pub bl: Obj,
    pub cq: Obj,
    pub tes: Obj,
    pub tds: Obj,
    pub cs: Obj,
    pub ds: Obj,
}

thread_local! {
    static CTX: RefCell<Option<Rc<Ctx>>> = const { RefCell::new(None) };
}

pub fn ctx() -> Rc<Ctx> {
    CTX.with(|c| c.borrow().clone()).expect("streams: not initialised")
}

pub fn try_ctx() -> Option<Rc<Ctx>> {
    CTX.with(|c| c.borrow().clone())
}

fn proto_obj(vm: &mut Vm) -> Obj {
    vm.new_object()
}

pub fn setup(vm: &mut Vm) {
    let k_stream = Sym::new(Some(JsStr::from_str("stream")));
    let k_ws = Sym::new(Some(JsStr::from_str("writableStream")));
    let k_ts = Sym::new(Some(JsStr::from_str("transformStream")));

    // ReadableStream
    let rs_proto = proto_obj(vm);
    let rs = class_ctor(vm, "ReadableStream", 0, rs_construct, &rs_proto);
    method(vm, &rs_proto, "_maybePull", 0, rs_maybe_pull);
    method(vm, &rs_proto, "_fulfillReads", 0, rs_fulfill_reads);
    method(vm, &rs_proto, "getReader", 0, rs_get_reader);
    getter(vm, &rs_proto, "locked", rs_locked);
    method(vm, &rs_proto, "cancel", 1, rs_cancel);
    method(vm, &rs_proto, "pipeTo", 1, rs_pipe_to);
    method(vm, &rs_proto, "pipeThrough", 1, rs_pipe_through);
    method(vm, &rs_proto, "tee", 0, rs_tee);
    let values = method(vm, &rs_proto, "values", 0, rs_values);
    let ai = vm.intr.sym_async_iterator.clone();
    rs_proto.set_prop(PropKey::Sym(ai), Value::Obj(values), WEC);

    // ReadableStreamDefaultReader
    let reader_proto = proto_obj(vm);
    let reader = class_ctor(vm, "ReadableStreamDefaultReader", 1, reader_construct, &reader_proto);
    method(vm, &reader_proto, "read", 0, reader_read);
    method(vm, &reader_proto, "_readSync", 0, reader_read_sync);
    method(vm, &reader_proto, "releaseLock", 0, reader_release_lock);
    method(vm, &reader_proto, "cancel", 1, reader_cancel);
    getter(vm, &reader_proto, "closed", reader_closed);

    // ReadableStreamDefaultController
    let ctrl_proto = proto_obj(vm);
    let ctrl = class_ctor(vm, "ReadableStreamDefaultController", 1, ctrl_construct, &ctrl_proto);
    method(vm, &ctrl_proto, "enqueue", 1, ctrl_enqueue);
    method(vm, &ctrl_proto, "close", 0, ctrl_close);
    method(vm, &ctrl_proto, "error", 1, ctrl_error);
    getter(vm, &ctrl_proto, "desiredSize", ctrl_desired_size);

    // ReadableStreamBYOBReader
    let byob_reader_proto = proto_obj(vm);
    let byob_reader = class_ctor(vm, "ReadableStreamBYOBReader", 1, byob_reader_construct, &byob_reader_proto);
    method(vm, &byob_reader_proto, "read", 1, byob_reader_read);
    method(vm, &byob_reader_proto, "releaseLock", 0, reader_release_lock);
    method(vm, &byob_reader_proto, "cancel", 1, reader_cancel);
    getter(vm, &byob_reader_proto, "closed", reader_closed);

    // ReadableByteStreamController
    let byte_ctrl_proto = proto_obj(vm);
    let byte_ctrl = class_ctor(vm, "ReadableByteStreamController", 1, byte_ctrl_construct, &byte_ctrl_proto);
    method(vm, &byte_ctrl_proto, "enqueue", 1, byte_ctrl_enqueue);
    method(vm, &byte_ctrl_proto, "close", 0, ctrl_close);
    method(vm, &byte_ctrl_proto, "error", 1, ctrl_error);
    getter(vm, &byte_ctrl_proto, "byobRequest", byte_ctrl_byob_request);
    getter(vm, &byte_ctrl_proto, "desiredSize", ctrl_desired_size);

    // ReadableStreamBYOBRequest
    let byob_req_proto = proto_obj(vm);
    let byob_req = class_ctor(vm, "ReadableStreamBYOBRequest", 2, byob_req_construct, &byob_req_proto);
    method(vm, &byob_req_proto, "respond", 1, byob_req_respond);
    method(vm, &byob_req_proto, "respondWithNewView", 1, byob_req_respond_with_new_view);

    // WritableStream
    let ws_proto = proto_obj(vm);
    let ws = class_ctor(vm, "WritableStream", 0, ws_construct, &ws_proto);
    getter(vm, &ws_proto, "locked", ws_locked);
    method(vm, &ws_proto, "getWriter", 0, ws_get_writer);
    method(vm, &ws_proto, "close", 0, ws_close);
    method(vm, &ws_proto, "abort", 1, ws_abort);
    method(vm, &ws_proto, "_closeInternal", 0, ws_close_internal);
    method(vm, &ws_proto, "_errorInternal", 1, ws_error_internal);
    tag_getter(vm, &ws_proto, |_vm, _a| Ok(Value::str("WritableStream")));

    // WritableStreamDefaultWriter
    let writer_proto = proto_obj(vm);
    let writer = class_ctor(vm, "WritableStreamDefaultWriter", 1, writer_construct, &writer_proto);
    getter(vm, &writer_proto, "desiredSize", writer_desired_size);
    getter(vm, &writer_proto, "ready", |vm, a| get(vm, &a.this, "_ready"));
    getter(vm, &writer_proto, "closed", |vm, a| get(vm, &a.this, "_closed"));
    method(vm, &writer_proto, "write", 1, writer_write);
    method(vm, &writer_proto, "close", 0, writer_close);
    method(vm, &writer_proto, "abort", 1, writer_abort);
    method(vm, &writer_proto, "releaseLock", 0, writer_release_lock);

    // WritableStreamDefaultController
    let wctrl_proto = proto_obj(vm);
    let wctrl = class_ctor(vm, "WritableStreamDefaultController", 1, wctrl_construct, &wctrl_proto);
    method(vm, &wctrl_proto, "error", 1, wctrl_error);
    tag_getter(vm, &wctrl_proto, |_vm, _a| Ok(Value::str("WritableStreamDefaultController")));

    // TransformStream
    let ts_proto = proto_obj(vm);
    let ts = class_ctor(vm, "TransformStream", 0, ts_construct, &ts_proto);
    tag_getter(vm, &ts_proto, |_vm, _a| Ok(Value::str("TransformStream")));

    // TransformStreamDefaultController
    let tsctrl_proto = proto_obj(vm);
    let tsctrl = class_ctor(vm, "TransformStreamDefaultController", 1, tsctrl_construct, &tsctrl_proto);
    getter(vm, &tsctrl_proto, "desiredSize", tsctrl_desired_size);
    method(vm, &tsctrl_proto, "enqueue", 1, tsctrl_enqueue);
    method(vm, &tsctrl_proto, "error", 1, tsctrl_error);
    method(vm, &tsctrl_proto, "terminate", 0, tsctrl_terminate);
    tag_getter(vm, &tsctrl_proto, |_vm, _a| Ok(Value::str("TransformStreamDefaultController")));

    // Queuing strategies
    let bl_proto = proto_obj(vm);
    let bl = class_ctor(vm, "ByteLengthQueuingStrategy", 1, bl_construct, &bl_proto);
    getter(vm, &bl_proto, "size", |vm, _a| Ok(func(vm, "", 1, bl_size, vec![])));
    tag_getter(vm, &bl_proto, |_vm, _a| Ok(Value::str("ByteLengthQueuingStrategy")));
    let cq_proto = proto_obj(vm);
    let cq = class_ctor(vm, "CountQueuingStrategy", 1, cq_construct, &cq_proto);
    getter(vm, &cq_proto, "size", |vm, _a| Ok(func(vm, "", 0, |_vm, _a| Ok(Value::Num(1.0)), vec![])));
    tag_getter(vm, &cq_proto, |_vm, _a| Ok(Value::str("CountQueuingStrategy")));

    // TextEncoderStream / TextDecoderStream
    let tes_proto = proto_obj(vm);
    let tes = class_ctor(vm, "TextEncoderStream", 0, tes_construct, &tes_proto);
    getter(vm, &tes_proto, "encoding", |_vm, _a| Ok(Value::str("utf-8")));
    getter(vm, &tes_proto, "readable", ts_wrapper_readable);
    getter(vm, &tes_proto, "writable", ts_wrapper_writable);
    let tds_proto = proto_obj(vm);
    let tds = class_ctor(vm, "TextDecoderStream", 0, tds_construct, &tds_proto);
    getter(vm, &tds_proto, "encoding", |vm, a| get(vm, &a.this, "_encoding"));
    getter(vm, &tds_proto, "readable", ts_wrapper_readable);
    getter(vm, &tds_proto, "writable", ts_wrapper_writable);

    // CompressionStream / DecompressionStream
    let cs_proto = proto_obj(vm);
    let cs = class_ctor(vm, "CompressionStream", 1, cs_construct, &cs_proto);
    getter(vm, &cs_proto, "readable", ts_wrapper_readable);
    getter(vm, &cs_proto, "writable", ts_wrapper_writable);
    let ds_proto = proto_obj(vm);
    let ds = class_ctor(vm, "DecompressionStream", 1, ds_construct, &ds_proto);
    getter(vm, &ds_proto, "readable", ts_wrapper_readable);
    getter(vm, &ds_proto, "writable", ts_wrapper_writable);

    let c = Ctx {
        k_stream,
        k_ws,
        k_ts,
        rs: rs.clone(),
        rs_proto,
        reader: reader.clone(),
        reader_proto,
        ctrl: ctrl.clone(),
        ctrl_proto,
        byob_reader: byob_reader.clone(),
        byob_reader_proto,
        byte_ctrl: byte_ctrl.clone(),
        byte_ctrl_proto,
        byob_req: byob_req.clone(),
        byob_req_proto,
        ws: ws.clone(),
        ws_proto,
        writer: writer.clone(),
        writer_proto,
        wctrl: wctrl.clone(),
        wctrl_proto,
        ts: ts.clone(),
        ts_proto,
        tsctrl: tsctrl.clone(),
        tsctrl_proto,
        bl_proto,
        cq_proto,
        tes_proto,
        tds_proto,
        cs_proto,
        ds_proto,
        bl: bl.clone(),
        cq: cq.clone(),
        tes: tes.clone(),
        tds: tds.clone(),
        cs: cs.clone(),
        ds: ds.clone(),
    };
    CTX.with(|x| *x.borrow_mut() = Some(Rc::new(c)));

    let globals: Vec<(&str, Obj)> = vec![
        ("ReadableStream", rs),
        ("ReadableStreamDefaultReader", reader),
        ("ReadableStreamDefaultController", ctrl),
        ("ReadableStreamBYOBReader", byob_reader),
        ("ReadableByteStreamController", byte_ctrl),
        ("ReadableStreamBYOBRequest", byob_req),
        ("WritableStream", ws),
        ("WritableStreamDefaultWriter", writer),
        ("WritableStreamDefaultController", wctrl),
        ("TransformStream", ts),
        ("TransformStreamDefaultController", tsctrl),
        ("ByteLengthQueuingStrategy", bl),
        ("CountQueuingStrategy", cq),
        ("TextEncoderStream", tes),
        ("TextDecoderStream", tds),
        ("CompressionStream", cs),
        ("DecompressionStream", ds),
    ];
    for (n, o) in globals {
        vm.global.set_prop(PropKey::from_str(n), Value::Obj(o), WEC);
    }
}

/// `require('stream/web')`: the stream classes, in the reference runtime's key order.
#[allow(unused_variables, dead_code)]
pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    let c = ctx();
    let o = vm.new_object();
    let items: [(&str, &Obj); 17] = [
        ("ReadableStream", &c.rs),
        ("ReadableStreamDefaultReader", &c.reader),
        ("ReadableStreamBYOBReader", &c.byob_reader),
        ("ReadableStreamDefaultController", &c.ctrl),
        ("ReadableByteStreamController", &c.byte_ctrl),
        ("ReadableStreamBYOBRequest", &c.byob_req),
        ("WritableStream", &c.ws),
        ("WritableStreamDefaultWriter", &c.writer),
        ("WritableStreamDefaultController", &c.wctrl),
        ("TransformStream", &c.ts),
        ("TransformStreamDefaultController", &c.tsctrl),
        ("ByteLengthQueuingStrategy", &c.bl),
        ("CountQueuingStrategy", &c.cq),
        ("TextEncoderStream", &c.tes),
        ("TextDecoderStream", &c.tds),
        ("CompressionStream", &c.cs),
        ("DecompressionStream", &c.ds),
    ];
    for (n, ctor) in items {
        o.set_str(n, Value::Obj(ctor.clone()), WEC);
    }
    Value::Obj(o)
}

// =====================================================================================
// ReadableStream
// =====================================================================================

fn rs_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.rs_proto)?;
    let mut src = a.arg(0);
    if src.is_undefined() {
        src = new_obj(vm);
    }
    if !src.truthy() {
        src = new_obj(vm);
    }
    let chunks = new_arr(vm, vec![]);
    put(vm, &this, "_chunks", chunks)?;
    put(vm, &this, "_state", Value::str("readable"))?;
    put(vm, &this, "_storedError", Value::Undefined)?;
    put(vm, &this, "_reader", Value::Null)?;
    put(vm, &this, "_source", src.clone())?;
    put(vm, &this, "_pulling", Value::Bool(false))?;
    let ty = get(vm, &src, "type")?;
    put(vm, &this, "_isBytes", Value::Bool(is_str(&ty, "bytes")))?;
    let is_bytes = get(vm, &this, "_isBytes")?.truthy();
    let ctrl = construct(vm, if is_bytes { &c.byte_ctrl } else { &c.ctrl }, &[this.clone()])?;
    put(vm, &this, "_controller", ctrl)?;
    let start = get(vm, &src, "start")?;
    if start.is_callable() {
        let ctrl = get(vm, &this, "_controller")?;
        vm.call(&start, src, &[ctrl])?;
    }
    Ok(this)
}

fn rs_maybe_pull(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let state = get(vm, &this, "_state")?;
    if !is_str(&state, "readable") || get(vm, &this, "_pulling")?.truthy() {
        return Ok(Value::Undefined);
    }
    let source = get(vm, &this, "_source")?;
    let pull = get(vm, &source, "pull")?;
    if !pull.is_callable() {
        return Ok(Value::Undefined);
    }
    put(vm, &this, "_pulling", Value::Bool(true))?;
    let r = (|| -> JsResult<Value> {
        let src = get(vm, &this, "_source")?;
        let ctrl = get(vm, &this, "_controller")?;
        vm.call(&pull, src, &[ctrl])
    })();
    put(vm, &this, "_pulling", Value::Bool(false))?;
    r?;
    Ok(Value::Undefined)
}

fn chunks_len(vm: &mut Vm, s: &Value) -> JsResult<bool> {
    let chunks = get(vm, s, "_chunks")?;
    Ok(get(vm, &chunks, "length")?.truthy())
}

fn chunks_shift(vm: &mut Vm, s: &Value) -> JsResult<Value> {
    let chunks = get(vm, s, "_chunks")?;
    invoke(vm, &chunks, "shift", &[])
}

fn rs_fulfill_reads(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let reader = get(vm, &this, "_reader")?;
    if !reader.truthy() {
        return Ok(Value::Undefined);
    }
    loop {
        let reqs = get(vm, &reader, "_readRequests")?;
        if !get(vm, &reqs, "length")?.truthy() {
            break;
        }
        let req = get(vm, &reqs, "0")?;
        if chunks_len(vm, &this)? {
            let reqs = get(vm, &reader, "_readRequests")?;
            invoke(vm, &reqs, "shift", &[])?;
            let resolve = get(vm, &req, "resolve")?;
            let view = get(vm, &req, "view")?;
            let result = if view.truthy() {
                let view = get(vm, &req, "view")?;
                let v = fill_from_queue(vm, &this, &view)?;
                iter_result(vm, v, false)
            } else {
                let v = chunks_shift(vm, &this)?;
                iter_result(vm, v, false)
            };
            call_method(vm, &resolve, &req, "resolve", &[result])?;
            continue;
        }
        let state = get(vm, &this, "_state")?;
        if is_str(&state, "closed") {
            let reqs = get(vm, &reader, "_readRequests")?;
            invoke(vm, &reqs, "shift", &[])?;
            let resolve = get(vm, &req, "resolve")?;
            let view = get(vm, &req, "view")?;
            let result = if view.truthy() {
                let view = get(vm, &req, "view")?;
                let v = empty_view_like(vm, &view)?;
                iter_result(vm, v, true)
            } else {
                iter_result(vm, Value::Undefined, true)
            };
            call_method(vm, &resolve, &req, "resolve", &[result])?;
        } else if is_str(&state, "errored") {
            let reqs = get(vm, &reader, "_readRequests")?;
            let r = invoke(vm, &reqs, "shift", &[])?;
            let e = get(vm, &this, "_storedError")?;
            invoke(vm, &r, "reject", &[e])?;
        } else {
            break;
        }
    }
    let state = get(vm, &this, "_state")?;
    if is_str(&state, "closed") && get(vm, &reader, "_closedResolve")?.truthy() {
        invoke(vm, &reader, "_closedResolve", &[Value::Undefined])?;
    } else if is_str(&state, "errored") && get(vm, &reader, "_closedReject")?.truthy() {
        let e = get(vm, &this, "_storedError")?;
        invoke(vm, &reader, "_closedReject", &[e])?;
    }
    Ok(Value::Undefined)
}

/// `new view.constructor(view.buffer, view.byteOffset, 0)`
fn empty_view_like(vm: &mut Vm, view: &Value) -> JsResult<Value> {
    let ctor = get(vm, view, "constructor")?;
    let buffer = get(vm, view, "buffer")?;
    let off = get(vm, view, "byteOffset")?;
    vm.construct(&ctor, &[buffer, off, Value::Num(0.0)], None)
}

/// Copy queued byte chunks into `view` (possibly spanning several chunks, splitting the last
/// one), returning a view of the filled part with the caller's element type.
fn fill_from_queue(vm: &mut Vm, stream: &Value, view: &Value) -> JsResult<Value> {
    let buffer = get(vm, view, "buffer")?;
    let offv = get(vm, view, "byteOffset")?;
    let off = vm.to_number(&offv)? as usize;
    let capv = get(vm, view, "byteLength")?;
    let cap = vm.to_number(&capv)? as usize;
    let dest = match &buffer {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::ArrayBuffer(b) => Some(b.clone()),
            _ => None,
        },
        _ => None,
    };
    let mut filled = 0usize;
    while filled < cap {
        if !chunks_len(vm, stream)? {
            break;
        }
        let chunks = get(vm, stream, "_chunks")?;
        let chunk = get(vm, &chunks, "0")?;
        let src: Option<(Rc<RefCell<BufferData>>, usize, usize, Obj)> = match &chunk {
            Value::Obj(o) => match &o.borrow().kind {
                ObjKind::TypedArray(t) => Some((t.buf.clone(), t.offset, t.len() * t.kind.size(), t.buffer.clone())),
                _ => None,
            },
            _ => None,
        };
        let (sbuf, soff, slen, sbuffer) = match src {
            Some(x) => x,
            None => return vm.throw_type("undefined is not a function"),
        };
        let n = slen.min(cap - filled);
        if let Some(d) = &dest {
            let data: Vec<u8> = sbuf.borrow().bytes[soff..soff + n].to_vec();
            let mut db = d.borrow_mut();
            let start = off + filled;
            if start + n <= db.bytes.len() {
                db.bytes[start..start + n].copy_from_slice(&data);
            }
        }
        filled += n;
        if n < slen {
            let p = vm.intr.ta_protos[1].clone();
            let rest = Obj::with_class(
                Some(p),
                ObjKind::TypedArray(Box::new(TypedArrayData { kind: TAKind::Uint8, buffer: sbuffer, buf: sbuf, offset: soff + n, length: Some(slen - n) })),
                "Uint8Array",
            );
            let chunks = get(vm, stream, "_chunks")?;
            put(vm, &chunks, "0", Value::Obj(rest))?;
        } else {
            chunks_shift(vm, stream)?;
        }
    }
    let ctor = get(vm, view, "constructor")?;
    let bpe = get(vm, view, "BYTES_PER_ELEMENT")?;
    let bpe = vm.to_number(&bpe)?;
    let len = filled as f64 / bpe;
    let buffer = get(vm, view, "buffer")?;
    let offv = get(vm, view, "byteOffset")?;
    vm.construct(&ctor, &[buffer, offv, Value::Num(len)], None)
}

fn rs_get_reader(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = a.this.clone();
    let options = a.arg(0);
    if options.truthy() {
        let mode = get(vm, &options, "mode")?;
        if is_str(&mode, "byob") {
            if !get(vm, &this, "_isBytes")?.truthy() {
                return vm.throw_type("BYOB readers require a byte stream (type: 'bytes')");
            }
            return construct(vm, &c.byob_reader, &[this]);
        }
    }
    construct(vm, &c.reader, &[this])
}

fn rs_locked(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = get(vm, &a.this, "_reader")?;
    Ok(Value::Bool(!r.is_null()))
}

fn rs_cancel(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "locked")?.truthy() {
        let e = type_error(vm, "cannot cancel a locked stream");
        return Ok(rejected(vm, e));
    }
    let empty = new_arr(vm, vec![]);
    put(vm, &this, "_chunks", empty)?;
    if is_str(&get(vm, &this, "_state")?, "readable") {
        put(vm, &this, "_state", Value::str("closed"))?;
    }
    let source = get(vm, &this, "_source")?;
    let cancel = get(vm, &source, "cancel")?;
    let r = (|| -> JsResult<()> {
        if cancel.is_callable() {
            let src = get(vm, &this, "_source")?;
            vm.call(&cancel, src, &[a.arg(0)])?;
        }
        Ok(())
    })();
    if let Err(e) = r {
        return Ok(rejected(vm, e));
    }
    resolved(vm, Value::Undefined)
}

// ---------------- pipeTo (async function emulation) ----------------

struct PipeTo {
    cap: Capability,
    options: Value,
    reader: RefCell<Value>,
    writer: RefCell<Value>,
    error: RefCell<Value>,
}

fn rs_pipe_to(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let this = a.this.clone();
    let dest = a.arg(0);
    let mut options = a.arg(1);
    if options.is_undefined() {
        options = new_obj(vm);
    }
    let st = Rc::new(PipeTo {
        cap: cap.clone(),
        options,
        reader: RefCell::new(Value::Undefined),
        writer: RefCell::new(Value::Undefined),
        error: RefCell::new(Value::Undefined),
    });
    let r = (|| -> JsResult<()> {
        let reader = invoke(vm, &this, "getReader", &[])?;
        *st.reader.borrow_mut() = reader;
        let writer = invoke(vm, &dest, "getWriter", &[])?;
        *st.writer.borrow_mut() = writer;
        Ok(())
    })();
    if let Err(e) = r {
        settle(vm, &cap, Err(e));
        return Ok(cap.promise);
    }
    let data = host(st);
    pipe_loop(vm, &data);
    Ok(cap.promise)
}

fn pipe_loop(vm: &mut Vm, data: &Value) {
    let st = unhost::<PipeTo>(data);
    let reader = st.reader.borrow().clone();
    match invoke(vm, &reader, "read", &[]) {
        Ok(p) => await_value(vm, p, data, pipe_on_read, pipe_on_error),
        Err(e) => pipe_catch(vm, data, e),
    }
}

fn pipe_on_read(vm: &mut Vm, r: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<PipeTo>(data);
    let parts = (|| -> JsResult<(Value, Value)> {
        let value = get(vm, &r, "value")?;
        let done = get(vm, &r, "done")?;
        Ok((value, done))
    })();
    match parts {
        Err(e) => pipe_catch(vm, data, e),
        Ok((value, done)) => {
            if done.truthy() {
                pipe_after_loop(vm, data);
            } else {
                let writer = st.writer.borrow().clone();
                match invoke(vm, &writer, "write", &[value]) {
                    Ok(p) => await_value(vm, p, data, pipe_on_written, pipe_on_error),
                    Err(e) => pipe_catch(vm, data, e),
                }
            }
        }
    }
    Ok(Value::Undefined)
}

fn pipe_on_written(vm: &mut Vm, _v: Value, data: &Value) -> JsResult<Value> {
    pipe_loop(vm, data);
    Ok(Value::Undefined)
}

fn pipe_on_error(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    pipe_catch(vm, data, e);
    Ok(Value::Undefined)
}

fn pipe_after_loop(vm: &mut Vm, data: &Value) {
    let st = unhost::<PipeTo>(data);
    let options = st.options.clone();
    match get(vm, &options, "preventClose") {
        Err(e) => pipe_catch(vm, data, e),
        Ok(pc) => {
            if !pc.truthy() {
                let writer = st.writer.borrow().clone();
                match invoke(vm, &writer, "close", &[]) {
                    Ok(p) => await_value(vm, p, data, pipe_on_closed, pipe_on_error),
                    Err(e) => pipe_catch(vm, data, e),
                }
            } else {
                pipe_finally(vm, data, Ok(Value::Undefined));
            }
        }
    }
}

fn pipe_on_closed(vm: &mut Vm, _v: Value, data: &Value) -> JsResult<Value> {
    pipe_finally(vm, data, Ok(Value::Undefined));
    Ok(Value::Undefined)
}

fn pipe_catch(vm: &mut Vm, data: &Value, e: Value) {
    let st = unhost::<PipeTo>(data);
    *st.error.borrow_mut() = e.clone();
    let options = st.options.clone();
    match get(vm, &options, "preventAbort") {
        Err(e2) => pipe_finally(vm, data, Err(e2)),
        Ok(pa) => {
            if !pa.truthy() {
                let writer = st.writer.borrow().clone();
                let r = (|| -> JsResult<Value> {
                    let p = invoke(vm, &writer, "abort", &[e.clone()])?;
                    let noop = noop_fn(vm);
                    invoke(vm, &p, "catch", &[noop])
                })();
                match r {
                    Ok(p) => await_value(vm, p, data, pipe_after_abort, pipe_after_abort_err),
                    Err(e2) => pipe_finally(vm, data, Err(e2)),
                }
            } else {
                pipe_finally(vm, data, Err(e));
            }
        }
    }
}

fn pipe_after_abort(vm: &mut Vm, _v: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<PipeTo>(data);
    let e = st.error.borrow().clone();
    pipe_finally(vm, data, Err(e));
    Ok(Value::Undefined)
}

fn pipe_after_abort_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    pipe_finally(vm, data, Err(e));
    Ok(Value::Undefined)
}

fn pipe_finally(vm: &mut Vm, data: &Value, completion: JsResult<Value>) {
    let st = unhost::<PipeTo>(data);
    let reader = st.reader.borrow().clone();
    let writer = st.writer.borrow().clone();
    let r = (|| -> JsResult<()> {
        invoke(vm, &reader, "releaseLock", &[])?;
        invoke(vm, &writer, "releaseLock", &[])?;
        Ok(())
    })();
    let completion = match r {
        Err(e) => Err(e),
        Ok(()) => completion,
    };
    settle(vm, &st.cap, completion);
}

fn rs_pipe_through(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let transform = a.arg(0);
    let mut options = a.arg(1);
    if options.is_undefined() {
        options = new_obj(vm);
    }
    let ok = transform.truthy() && get(vm, &transform, "writable")?.truthy() && get(vm, &transform, "readable")?.truthy();
    if !ok {
        return vm.throw_type("pipeThrough expects { readable, writable }");
    }
    let writable = get(vm, &transform, "writable")?;
    let p = invoke(vm, &this, "pipeTo", &[writable, options])?;
    let noop = noop_fn(vm);
    invoke(vm, &p, "catch", &[noop])?;
    get(vm, &transform, "readable")
}

// ---------------- tee ----------------

struct Tee {
    reader: Value,
    pending: [RefCell<VecDeque<Value>>; 2],
    ended: Cell<bool>,
}

fn rs_tee(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let reader = invoke(vm, &a.this, "getReader", &[])?;
    let st = host(Rc::new(Tee { reader, pending: [RefCell::new(VecDeque::new()), RefCell::new(VecDeque::new())], ended: Cell::new(false) }));
    let mut branches = Vec::new();
    for i in 0..2 {
        let src = vm.new_object();
        let pull = func(vm, "pull", 1, tee_pull, vec![st.clone(), Value::Num(i as f64)]);
        src.set_str("pull", pull, WEC);
        let b = construct(vm, &c.rs, &[Value::Obj(src)])?;
        branches.push(b);
    }
    Ok(new_arr(vm, branches))
}

struct TeeRead {
    cap: Capability,
    tee: Value,
    branch: usize,
}

/// `readOne(branch)` (async arrow function).
fn tee_read_one(vm: &mut Vm, tee_v: &Value, branch: usize) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let tee = unhost::<Tee>(tee_v);
    let queued = tee.pending[branch].borrow_mut().pop_front();
    if let Some(v) = queued {
        let r = iter_result(vm, v, false);
        settle(vm, &cap, Ok(r));
        return cap.promise;
    }
    if tee.ended.get() {
        let r = iter_result(vm, Value::Undefined, true);
        settle(vm, &cap, Ok(r));
        return cap.promise;
    }
    match invoke(vm, &tee.reader, "read", &[]) {
        Ok(p) => {
            let data = host(Rc::new(TeeRead { cap: cap.clone(), tee: tee_v.clone(), branch }));
            await_value(vm, p, &data, tee_read_one_ok, tee_read_one_err);
        }
        Err(e) => settle(vm, &cap, Err(e)),
    }
    cap.promise
}

fn tee_read_one_ok(vm: &mut Vm, r: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<TeeRead>(data);
    let tee = unhost::<Tee>(&st.tee);
    let res = (|| -> JsResult<Value> {
        if get(vm, &r, "done")?.truthy() {
            tee.ended.set(true);
            return Ok(iter_result(vm, Value::Undefined, true));
        }
        let v = get(vm, &r, "value")?;
        tee.pending[1 - st.branch].borrow_mut().push_back(v);
        let v = get(vm, &r, "value")?;
        Ok(iter_result(vm, v, false))
    })();
    settle(vm, &st.cap, res);
    Ok(Value::Undefined)
}

fn tee_read_one_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<TeeRead>(data);
    settle(vm, &st.cap, Err(e));
    Ok(Value::Undefined)
}

struct TeePull {
    cap: Capability,
    controller: Value,
}

/// `async pull(controller) { try { const r = await readOne(i); ... } catch (e) { controller.error(e); } }`
fn tee_pull(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let tee = a.slot(0);
    let branch = a.slot(1).as_num().unwrap_or(0.0) as usize;
    let p = tee_read_one(vm, &tee, branch);
    let data = host(Rc::new(TeePull { cap: cap.clone(), controller: a.arg(0) }));
    await_value(vm, p, &data, tee_pull_ok, tee_pull_err);
    Ok(cap.promise)
}

fn tee_pull_ok(vm: &mut Vm, r: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<TeePull>(data);
    let c = st.controller.clone();
    let res = (|| -> JsResult<()> {
        if get(vm, &r, "done")?.truthy() {
            invoke(vm, &c, "close", &[])?;
        } else {
            let enqueue = get(vm, &c, "enqueue")?;
            let v = get(vm, &r, "value")?;
            call_method(vm, &enqueue, &c, "enqueue", &[v])?;
        }
        Ok(())
    })();
    let res = match res {
        Ok(()) => Ok(Value::Undefined),
        Err(e) => invoke(vm, &c, "error", &[e]).map(|_| Value::Undefined),
    };
    settle(vm, &st.cap, res);
    Ok(Value::Undefined)
}

fn tee_pull_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<TeePull>(data);
    let c = st.controller.clone();
    let res = invoke(vm, &c, "error", &[e]).map(|_| Value::Undefined);
    settle(vm, &st.cap, res);
    Ok(Value::Undefined)
}

// ---------------- values() / async iteration ----------------

fn rs_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let options = a.arg(0);
    let reader = invoke(vm, &a.this, "getReader", &[])?;
    let prevent_cancel = if options.is_undefined() { false } else { options.truthy() && get(vm, &options, "preventCancel")?.truthy() };
    let it = vm.new_object();
    let next = func(vm, "next", 0, values_next, vec![reader.clone()]);
    let ret = func(vm, "return", 1, values_return, vec![reader, Value::Bool(prevent_cancel)]);
    let ai = func(vm, "[Symbol.asyncIterator]", 0, |_vm, a| Ok(a.this.clone()), vec![]);
    it.set_str("next", next, WEC);
    it.set_str("return", ret, WEC);
    let s = vm.intr.sym_async_iterator.clone();
    it.set_prop(PropKey::Sym(s), ai, WEC);
    Ok(Value::Obj(it))
}

fn values_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let reader = a.slot(0);
    let p = invoke(vm, &reader, "read", &[])?;
    let cb = func(vm, "", 1, values_next_cb, vec![reader]);
    invoke(vm, &p, "then", &[cb])
}

fn values_next_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = a.arg(0);
    if get(vm, &r, "done")?.truthy() {
        let reader = a.slot(0);
        invoke(vm, &reader, "releaseLock", &[])?;
    }
    Ok(r)
}

fn values_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let reader = a.slot(0);
    let value = a.arg(0);
    if !a.slot(1).truthy() {
        invoke(vm, &reader, "cancel", &[value.clone()])?;
    } else {
        invoke(vm, &reader, "releaseLock", &[])?;
    }
    let r = iter_result(vm, value, true);
    resolved(vm, r)
}

// =====================================================================================
// Readers
// =====================================================================================

fn reader_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.reader_proto)?;
    let stream = a.arg(0);
    if !vm.instance_of(&stream, &Value::Obj(c.rs.clone()))? {
        return vm.throw_type("not a ReadableStream");
    }
    if get(vm, &stream, "locked")?.truthy() {
        return vm.throw_type("stream is already locked to a reader");
    }
    put_sym(vm, &this, &c.k_stream, stream.clone())?;
    put(vm, &stream, "_reader", this.clone())?;
    let reqs = new_arr(vm, vec![]);
    put(vm, &this, "_readRequests", reqs)?;
    put(vm, &this, "_closedPromise", Value::Null)?;
    put(vm, &this, "_closedResolve", Value::Null)?;
    put(vm, &this, "_closedReject", Value::Null)?;
    Ok(this)
}

fn reader_stream(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let c = ctx();
    get_sym(vm, this, &c.k_stream)
}

fn read_now(vm: &mut Vm, s: &Value) -> JsResult<Option<Value>> {
    if chunks_len(vm, s)? {
        let v = chunks_shift(vm, s)?;
        let r = iter_result(vm, v, false);
        return Ok(Some(resolved(vm, r)?));
    }
    let state = get(vm, s, "_state")?;
    if is_str(&state, "errored") {
        let e = get(vm, s, "_storedError")?;
        return Ok(Some(rejected(vm, e)));
    }
    let state = get(vm, s, "_state")?;
    if is_str(&state, "closed") {
        let r = iter_result(vm, Value::Undefined, true);
        return Ok(Some(resolved(vm, r)?));
    }
    Ok(None)
}

fn reader_read(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let s = reader_stream(vm, &this)?;
    if !s.truthy() {
        let e = type_error(vm, "reader has been released");
        return Ok(rejected(vm, e));
    }
    if let Some(p) = read_now(vm, &s)? {
        return Ok(p);
    }
    invoke(vm, &s, "_maybePull", &[])?;
    if let Some(p) = read_now(vm, &s)? {
        return Ok(p);
    }
    let cap = vm.new_promise_capability_intrinsic();
    let req = vm.obj_from(vec![("resolve", cap.resolve.clone()), ("reject", cap.reject.clone())]);
    let r = (|| -> JsResult<Value> {
        let reqs = get(vm, &this, "_readRequests")?;
        invoke(vm, &reqs, "push", &[Value::Obj(req)])
    })();
    if let Err(e) = r {
        settle(vm, &cap, Err(e));
    }
    Ok(cap.promise)
}

fn read_sync_now(vm: &mut Vm, s: &Value) -> JsResult<Option<Value>> {
    if chunks_len(vm, s)? {
        let v = chunks_shift(vm, s)?;
        return Ok(Some(iter_result(vm, v, false)));
    }
    let state = get(vm, s, "_state")?;
    if is_str(&state, "errored") {
        return Err(get(vm, s, "_storedError")?);
    }
    let state = get(vm, s, "_state")?;
    if is_str(&state, "closed") {
        return Ok(Some(iter_result(vm, Value::Undefined, true)));
    }
    Ok(None)
}

fn reader_read_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let s = reader_stream(vm, &this)?;
    if !s.truthy() {
        return vm.throw_type("reader has been released");
    }
    if let Some(r) = read_sync_now(vm, &s)? {
        return Ok(r);
    }
    invoke(vm, &s, "_maybePull", &[])?;
    if let Some(r) = read_sync_now(vm, &s)? {
        return Ok(r);
    }
    Ok(Value::Obj(vm.obj_from(vec![("pending", Value::Bool(true))])))
}

fn reader_release_lock(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = a.this.clone();
    let s = reader_stream(vm, &this)?;
    if !s.truthy() {
        return Ok(Value::Undefined);
    }
    let reqs = get(vm, &this, "_readRequests")?;
    if get(vm, &reqs, "length")?.truthy() {
        return vm.throw_type("cannot release a reader with pending reads");
    }
    put(vm, &s, "_reader", Value::Null)?;
    put_sym(vm, &this, &c.k_stream, Value::Null)?;
    Ok(Value::Undefined)
}

fn reader_cancel(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = a.this.clone();
    let s = reader_stream(vm, &this)?;
    if !s.truthy() {
        let e = type_error(vm, "reader has been released");
        return Ok(rejected(vm, e));
    }
    put(vm, &s, "_reader", Value::Null)?;
    put_sym(vm, &this, &c.k_stream, Value::Null)?;
    invoke(vm, &s, "cancel", &[a.arg(0)])
}

fn reader_closed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if !get(vm, &this, "_closedPromise")?.truthy() {
        let cap = vm.new_promise_capability_intrinsic();
        put(vm, &this, "_closedResolve", cap.resolve.clone())?;
        put(vm, &this, "_closedReject", cap.reject.clone())?;
        put(vm, &this, "_closedPromise", cap.promise.clone())?;
        let s = reader_stream(vm, &this)?;
        if !s.truthy() || is_str(&get(vm, &s, "_state")?, "closed") {
            invoke(vm, &this, "_closedResolve", &[Value::Undefined])?;
        } else if is_str(&get(vm, &s, "_state")?, "errored") {
            let e = get(vm, &s, "_storedError")?;
            invoke(vm, &this, "_closedReject", &[e])?;
        }
    }
    get(vm, &this, "_closedPromise")
}

fn byob_reader_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.byob_reader_proto)?;
    let stream = a.arg(0);
    let ok = vm.instance_of(&stream, &Value::Obj(c.rs.clone()))? && get(vm, &stream, "_isBytes")?.truthy();
    if !ok {
        return vm.throw_type("BYOB reader requires a byte ReadableStream");
    }
    if get(vm, &stream, "locked")?.truthy() {
        return vm.throw_type("stream is already locked to a reader");
    }
    put_sym(vm, &this, &c.k_stream, stream.clone())?;
    put(vm, &stream, "_reader", this.clone())?;
    put(vm, &this, "_byob", Value::Bool(true))?;
    let reqs = new_arr(vm, vec![]);
    put(vm, &this, "_readRequests", reqs)?;
    put(vm, &this, "_closedResolve", Value::Null)?;
    put(vm, &this, "_closedReject", Value::Null)?;
    put(vm, &this, "_closedPromise", Value::Null)?;
    Ok(this)
}

fn byob_reader_read(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = a.this.clone();
    let view = a.arg(0);
    let s = reader_stream(vm, &this)?;
    if !s.truthy() {
        let e = type_error(vm, "reader has been released");
        return Ok(rejected(vm, e));
    }
    if !is_view(&view) {
        let e = type_error(vm, "BYOB read expects an ArrayBufferView");
        return Ok(rejected(vm, e));
    }
    if chunks_len(vm, &s)? {
        let v = fill_from_queue(vm, &s, &view)?;
        let r = iter_result(vm, v, false);
        return resolved(vm, r);
    }
    if is_str(&get(vm, &s, "_state")?, "errored") {
        let e = get(vm, &s, "_storedError")?;
        return Ok(rejected(vm, e));
    }
    if is_str(&get(vm, &s, "_state")?, "closed") {
        let v = empty_view_like(vm, &view)?;
        let r = iter_result(vm, v, true);
        return resolved(vm, r);
    }
    let source = get(vm, &s, "_source")?;
    if get(vm, &source, "pull")?.is_callable() {
        let ctrl = get(vm, &s, "_controller")?;
        let req = construct(vm, &c.byob_req, &[ctrl, view.clone()])?;
        let ctrl = get(vm, &s, "_controller")?;
        put(vm, &ctrl, "_byobRequest", req)?;
        invoke(vm, &s, "_maybePull", &[])?;
        let ctrl = get(vm, &s, "_controller")?;
        put(vm, &ctrl, "_byobRequest", Value::Null)?;
        if chunks_len(vm, &s)? {
            let v = fill_from_queue(vm, &s, &view)?;
            let r = iter_result(vm, v, false);
            return resolved(vm, r);
        }
        if is_str(&get(vm, &s, "_state")?, "closed") {
            let v = empty_view_like(vm, &view)?;
            let r = iter_result(vm, v, true);
            return resolved(vm, r);
        }
    }
    let cap = vm.new_promise_capability_intrinsic();
    let req = vm.obj_from(vec![("view", view), ("resolve", cap.resolve.clone()), ("reject", cap.reject.clone())]);
    let r = (|| -> JsResult<Value> {
        let reqs = get(vm, &this, "_readRequests")?;
        invoke(vm, &reqs, "push", &[Value::Obj(req)])
    })();
    if let Err(e) = r {
        settle(vm, &cap, Err(e));
    }
    Ok(cap.promise)
}

// =====================================================================================
// Controllers
// =====================================================================================

fn ctrl_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.ctrl_proto)?;
    put_sym(vm, &this, &c.k_stream, a.arg(0))?;
    Ok(this)
}

fn ctrl_stream(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let c = ctx();
    get_sym(vm, this, &c.k_stream)
}

fn ctrl_enqueue(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = ctrl_stream(vm, &a.this)?;
    if !is_str(&get(vm, &s, "_state")?, "readable") {
        return vm.throw_type("stream is not in a readable state");
    }
    let chunks = get(vm, &s, "_chunks")?;
    invoke(vm, &chunks, "push", &[a.arg(0)])?;
    invoke(vm, &s, "_fulfillReads", &[])?;
    Ok(Value::Undefined)
}

fn ctrl_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = ctrl_stream(vm, &a.this)?;
    if !is_str(&get(vm, &s, "_state")?, "readable") {
        return Ok(Value::Undefined);
    }
    put(vm, &s, "_state", Value::str("closed"))?;
    invoke(vm, &s, "_fulfillReads", &[])?;
    Ok(Value::Undefined)
}

fn ctrl_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = ctrl_stream(vm, &a.this)?;
    if !is_str(&get(vm, &s, "_state")?, "readable") {
        return Ok(Value::Undefined);
    }
    put(vm, &s, "_state", Value::str("errored"))?;
    put(vm, &s, "_storedError", a.arg(0))?;
    let empty = new_arr(vm, vec![]);
    put(vm, &s, "_chunks", empty)?;
    invoke(vm, &s, "_fulfillReads", &[])?;
    Ok(Value::Undefined)
}

fn ctrl_desired_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = ctrl_stream(vm, &a.this)?;
    if is_str(&get(vm, &s, "_state")?, "errored") {
        return Ok(Value::Null);
    }
    if is_str(&get(vm, &s, "_state")?, "closed") {
        return Ok(Value::Num(0.0));
    }
    Ok(Value::Num(1.0))
}

fn byte_ctrl_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.byte_ctrl_proto)?;
    put_sym(vm, &this, &c.k_stream, a.arg(0))?;
    put(vm, &this, "_byobRequest", Value::Null)?;
    Ok(this)
}

fn byte_ctrl_enqueue(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = ctrl_stream(vm, &a.this)?;
    if !is_str(&get(vm, &s, "_state")?, "readable") {
        return vm.throw_type("stream is not in a readable state");
    }
    let chunk = a.arg(0);
    if !is_view(&chunk) {
        return vm.throw_type("byte stream enqueue expects an ArrayBufferView");
    }
    let bytes = bytes_of_buffer_source(&chunk);
    let copy = new_u8(vm, bytes)?;
    let chunks = get(vm, &s, "_chunks")?;
    invoke(vm, &chunks, "push", &[copy])?;
    invoke(vm, &s, "_fulfillReads", &[])?;
    Ok(Value::Undefined)
}

fn byte_ctrl_byob_request(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get(vm, &a.this, "_byobRequest")
}

fn byob_req_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.byob_req_proto)?;
    let controller = a.arg(0);
    let s = get_sym(vm, &controller, &c.k_stream)?;
    put_sym(vm, &this, &c.k_stream, s)?;
    put(vm, &this, "_controller", controller)?;
    put(vm, &this, "view", a.arg(1))?;
    Ok(this)
}

/// `new Uint8Array(buffer, byteOffset, length).slice()`
fn u8_copy(vm: &mut Vm, buffer: &Value, off: &Value, len: &Value) -> JsResult<Value> {
    let ctor = Value::Obj(vm.intr.ta_ctors[1].clone());
    let view = vm.construct(&ctor, &[buffer.clone(), off.clone(), len.clone()], None)?;
    invoke(vm, &view, "slice", &[])
}

fn byob_req_respond(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let s = ctrl_stream(vm, &this)?;
    let view = get(vm, &this, "view")?;
    let buffer = get(vm, &view, "buffer")?;
    let view = get(vm, &this, "view")?;
    let off = get(vm, &view, "byteOffset")?;
    let filled = u8_copy(vm, &buffer, &off, &a.arg(0))?;
    let chunks = get(vm, &s, "_chunks")?;
    invoke(vm, &chunks, "push", &[filled])?;
    let ctrl = get(vm, &this, "_controller")?;
    put(vm, &ctrl, "_byobRequest", Value::Null)?;
    put(vm, &this, "view", Value::Null)?;
    invoke(vm, &s, "_fulfillReads", &[])?;
    Ok(Value::Undefined)
}

fn byob_req_respond_with_new_view(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let s = ctrl_stream(vm, &this)?;
    let view = a.arg(0);
    let buffer = get(vm, &view, "buffer")?;
    let off = get(vm, &view, "byteOffset")?;
    let len = get(vm, &view, "byteLength")?;
    let copy = u8_copy(vm, &buffer, &off, &len)?;
    let chunks = get(vm, &s, "_chunks")?;
    invoke(vm, &chunks, "push", &[copy])?;
    let ctrl = get(vm, &this, "_controller")?;
    put(vm, &ctrl, "_byobRequest", Value::Null)?;
    put(vm, &this, "view", Value::Null)?;
    invoke(vm, &s, "_fulfillReads", &[])?;
    Ok(Value::Undefined)
}

// =====================================================================================
// WritableStream
// =====================================================================================

/// `new AbortController()` (the global class; a minimal stand-in when it is unavailable).
fn new_abort_controller(vm: &mut Vm) -> JsResult<Value> {
    let ac = global(vm, "AbortController");
    if let Value::Obj(o) = &ac {
        if o.is_constructor() {
            return vm.construct(&ac, &[], None);
        }
    }
    let signal = vm.obj_from(vec![("aborted", Value::Bool(false)), ("reason", Value::Undefined)]);
    let ctl = vm.obj_from(vec![("signal", Value::Obj(signal.clone()))]);
    let abort = func(vm, "abort", 1, fallback_abort, vec![Value::Obj(signal)]);
    ctl.set_str("abort", abort, WC);
    Ok(Value::Obj(ctl))
}

fn fallback_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let signal = a.slot(0);
    if get(vm, &signal, "aborted")?.truthy() {
        return Ok(Value::Undefined);
    }
    put(vm, &signal, "aborted", Value::Bool(true))?;
    let reason = a.arg(0);
    let reason = if reason.is_undefined() { make_dom_exception(vm, "signal is aborted without reason", "AbortError")? } else { reason };
    put(vm, &signal, "reason", reason)?;
    Ok(Value::Undefined)
}

/// `new DOMException(message, name)` (falls back to an Error with that name).
pub fn make_dom_exception(vm: &mut Vm, msg: &str, name: &str) -> JsResult<Value> {
    let de = global(vm, "DOMException");
    if let Value::Obj(o) = &de {
        if o.is_constructor() {
            return vm.construct(&de, &[Value::str(msg), Value::str(name)], None);
        }
    }
    let e = vm.make_error("Error", msg);
    if let Value::Obj(o) = &e {
        o.set_str("name", Value::str(name), WC);
    }
    Ok(e)
}

fn ws_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.ws_proto)?;
    let mut sink = a.arg(0);
    if sink.is_undefined() {
        sink = new_obj(vm);
    }
    let mut strategy = a.arg(1);
    if strategy.is_undefined() {
        strategy = new_obj(vm);
    }
    let sink = if sink.truthy() { sink } else { new_obj(vm) };
    put(vm, &this, "_sink", sink)?;
    put(vm, &this, "_state", Value::str("writable"))?;
    put(vm, &this, "_storedError", Value::Undefined)?;
    put(vm, &this, "_writer", Value::Null)?;
    let chain = resolved(vm, Value::Undefined)?;
    put(vm, &this, "_writeChain", chain)?;
    put(vm, &this, "_queueSize", Value::Num(0.0))?;
    let hwm = if strategy.truthy() && !get(vm, &strategy, "highWaterMark")?.is_undefined() {
        let h = get(vm, &strategy, "highWaterMark")?;
        Value::Num(vm.to_number(&h)?)
    } else {
        Value::Num(1.0)
    };
    put(vm, &this, "_hwm", hwm)?;
    let ac = new_abort_controller(vm)?;
    put(vm, &this, "_abortController", ac)?;
    let ctrl = construct(vm, &c.wctrl, &[this.clone()])?;
    put(vm, &this, "_controller", ctrl)?;
    let sink = get(vm, &this, "_sink")?;
    if get(vm, &sink, "start")?.is_callable() {
        let r = (|| -> JsResult<()> {
            let sink = get(vm, &this, "_sink")?;
            let start = get(vm, &sink, "start")?;
            let ctrl = get(vm, &this, "_controller")?;
            let ret = call_method(vm, &start, &sink, "start", &[ctrl])?;
            let p = resolved(vm, ret)?;
            let h = func(vm, "", 1, ws_start_catch, vec![this.clone()]);
            invoke(vm, &p, "catch", &[h])?;
            Ok(())
        })();
        if let Err(e) = r {
            invoke(vm, &this, "_errorInternal", &[e])?;
        }
    }
    Ok(this)
}

fn ws_start_catch(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    invoke(vm, &this, "_errorInternal", &[a.arg(0)])
}

fn ws_locked(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let w = get(vm, &a.this, "_writer")?;
    Ok(Value::Bool(!w.is_null()))
}

fn ws_get_writer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    construct(vm, &c.writer, &[a.this.clone()])
}

fn ws_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "locked")?.truthy() {
        let e = type_error(vm, "WritableStream is locked");
        return Ok(rejected(vm, e));
    }
    let w = invoke(vm, &this, "getWriter", &[])?;
    let p = invoke(vm, &w, "close", &[])?;
    let f = func(vm, "", 0, |vm, a| invoke(vm, &a.slot(0), "releaseLock", &[]), vec![w]);
    invoke(vm, &p, "finally", &[f])
}

fn ws_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let reason = a.arg(0);
    let st = get(vm, &this, "_state")?;
    let st2 = get(vm, &this, "_state")?;
    if is_str(&st, "closed") || is_str(&st2, "errored") {
        return resolved(vm, Value::Undefined);
    }
    let ac = get(vm, &this, "_abortController")?;
    invoke(vm, &ac, "abort", &[reason.clone()])?;
    let chain = get(vm, &this, "_writeChain")?;
    let f = func(vm, "", 0, ws_abort_step, vec![this, reason]);
    invoke(vm, &chain, "then", &[f])
}

fn ws_abort_step(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let reason = a.slot(1);
    let sink = get(vm, &this, "_sink")?;
    let p = if get(vm, &sink, "abort")?.truthy() {
        let sink = get(vm, &this, "_sink")?;
        let r = invoke(vm, &sink, "abort", &[reason.clone()])?;
        resolved(vm, r)?
    } else {
        resolved(vm, Value::Undefined)?
    };
    let f = func(vm, "", 0, ws_abort_done, vec![this, reason]);
    invoke(vm, &p, "then", &[f])
}

fn ws_abort_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    put(vm, &this, "_state", Value::str("errored"))?;
    put(vm, &this, "_storedError", a.slot(1))?;
    Ok(Value::Undefined)
}

fn ws_close_internal(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let chain = get(vm, &this, "_writeChain")?;
    let f = func(vm, "", 0, ws_close_step, vec![this]);
    invoke(vm, &chain, "then", &[f])
}

fn ws_close_step(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    if is_str(&get(vm, &this, "_state")?, "errored") {
        return Err(get(vm, &this, "_storedError")?);
    }
    let sink = get(vm, &this, "_sink")?;
    let p = if get(vm, &sink, "close")?.truthy() {
        let sink = get(vm, &this, "_sink")?;
        let r = invoke(vm, &sink, "close", &[])?;
        resolved(vm, r)?
    } else {
        resolved(vm, Value::Undefined)?
    };
    let f = func(vm, "", 0, |vm, a| put(vm, &a.slot(0), "_state", Value::str("closed")).map(|_| Value::Undefined), vec![this]);
    invoke(vm, &p, "then", &[f])
}

fn ws_error_internal(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let e = a.arg(0);
    let st = get(vm, &this, "_state")?;
    let st2 = get(vm, &this, "_state")?;
    if is_str(&st, "writable") || is_str(&st2, "erroring") {
        put(vm, &this, "_state", Value::str("errored"))?;
        put(vm, &this, "_storedError", e.clone())?;
        let w = get(vm, &this, "_writer")?;
        if w.truthy() && get(vm, &w, "_closedReject")?.truthy() {
            let w = get(vm, &this, "_writer")?;
            invoke(vm, &w, "_closedReject", &[e])?;
        }
    }
    Ok(Value::Undefined)
}

fn writer_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.writer_proto)?;
    let stream = a.arg(0);
    if !vm.instance_of(&stream, &Value::Obj(c.ws.clone()))? {
        return vm.throw_type("not a WritableStream");
    }
    if get(vm, &stream, "locked")?.truthy() {
        return vm.throw_type("WritableStream is already locked");
    }
    put_sym(vm, &this, &c.k_ws, stream.clone())?;
    put(vm, &stream, "_writer", this.clone())?;
    let ready = if is_str(&get(vm, &stream, "_state")?, "writable") {
        resolved(vm, Value::Undefined)?
    } else {
        let e = get(vm, &stream, "_storedError")?;
        rejected(vm, e)
    };
    put(vm, &this, "_ready", ready)?;
    let ready = get(vm, &this, "_ready")?;
    let noop = noop_fn(vm);
    invoke(vm, &ready, "catch", &[noop])?;
    let cap = vm.new_promise_capability_intrinsic();
    put(vm, &this, "_closedResolve", cap.resolve.clone())?;
    put(vm, &this, "_closedReject", cap.reject.clone())?;
    put(vm, &this, "_closed", cap.promise.clone())?;
    let closed = get(vm, &this, "_closed")?;
    let noop = noop_fn(vm);
    invoke(vm, &closed, "catch", &[noop])?;
    if is_str(&get(vm, &stream, "_state")?, "closed") {
        invoke(vm, &this, "_closedResolve", &[])?;
    } else if is_str(&get(vm, &stream, "_state")?, "errored") {
        let e = get(vm, &stream, "_storedError")?;
        invoke(vm, &this, "_closedReject", &[e])?;
    }
    Ok(this)
}

fn writer_stream(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let c = ctx();
    get_sym(vm, this, &c.k_ws)
}

fn writer_desired_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = writer_stream(vm, &a.this)?;
    if !s.truthy() {
        return vm.throw_type("writer released");
    }
    let st = get(vm, &s, "_state")?;
    let st2 = get(vm, &s, "_state")?;
    if is_str(&st, "errored") || is_str(&st2, "erroring") {
        return Ok(Value::Null);
    }
    if is_str(&get(vm, &s, "_state")?, "closed") {
        return Ok(Value::Num(0.0));
    }
    let h = get(vm, &s, "_hwm")?;
    let q = get(vm, &s, "_queueSize")?;
    let hn = vm.to_numeric(&h)?;
    let qn = vm.to_numeric(&q)?;
    match (hn, qn) {
        (Value::Num(x), Value::Num(y)) => Ok(Value::Num(x - y)),
        _ => vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
    }
}

fn writer_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = writer_stream(vm, &a.this)?;
    if !s.truthy() {
        let e = type_error(vm, "writer released");
        return Ok(rejected(vm, e));
    }
    if is_str(&get(vm, &s, "_state")?, "errored") {
        let e = get(vm, &s, "_storedError")?;
        return Ok(rejected(vm, e));
    }
    let q = get(vm, &s, "_queueSize")?;
    let q = add(vm, &q, 1.0)?;
    put(vm, &s, "_queueSize", q)?;
    let chain = get(vm, &s, "_writeChain")?;
    let step = func(vm, "", 0, writer_write_step, vec![s.clone(), a.arg(0)]);
    let p1 = invoke(vm, &chain, "then", &[step])?;
    let ok = func(vm, "", 0, writer_write_ok, vec![s.clone()]);
    let err = func(vm, "", 1, writer_write_err, vec![s.clone()]);
    let p2 = invoke(vm, &p1, "then", &[ok, err])?;
    put(vm, &s, "_writeChain", p2)?;
    get(vm, &s, "_writeChain")
}

fn writer_write_step(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.slot(0);
    let chunk = a.slot(1);
    let st = get(vm, &s, "_state")?;
    let st2 = get(vm, &s, "_state")?;
    if is_str(&st, "errored") || is_str(&st2, "erroring") {
        return Err(get(vm, &s, "_storedError")?);
    }
    let sink = get(vm, &s, "_sink")?;
    if get(vm, &sink, "write")?.truthy() {
        let sink = get(vm, &s, "_sink")?;
        let w = get(vm, &sink, "write")?;
        let ctrl = get(vm, &s, "_controller")?;
        call_method(vm, &w, &sink, "write", &[chunk, ctrl])
    } else {
        Ok(Value::Undefined)
    }
}

fn writer_write_ok(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.slot(0);
    let q = get(vm, &s, "_queueSize")?;
    let q = sub(vm, &q, 1.0)?;
    put(vm, &s, "_queueSize", q)?;
    Ok(Value::Undefined)
}

fn writer_write_err(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.slot(0);
    let e = a.arg(0);
    let q = get(vm, &s, "_queueSize")?;
    let q = sub(vm, &q, 1.0)?;
    put(vm, &s, "_queueSize", q)?;
    invoke(vm, &s, "_errorInternal", &[e.clone()])?;
    Err(e)
}

fn writer_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let s = writer_stream(vm, &this)?;
    if !s.truthy() {
        let e = type_error(vm, "writer released");
        return Ok(rejected(vm, e));
    }
    let p = invoke(vm, &s, "_closeInternal", &[])?;
    let f = func(vm, "", 0, |vm, a| invoke(vm, &a.slot(0), "_closedResolve", &[]), vec![this]);
    invoke(vm, &p, "then", &[f])
}

fn writer_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = writer_stream(vm, &a.this)?;
    if s.truthy() {
        let s = writer_stream(vm, &a.this)?;
        invoke(vm, &s, "abort", &[a.arg(0)])
    } else {
        let e = type_error(vm, "writer released");
        Ok(rejected(vm, e))
    }
}

fn writer_release_lock(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = a.this.clone();
    let s = writer_stream(vm, &this)?;
    if !s.truthy() {
        return Ok(Value::Undefined);
    }
    put(vm, &s, "_writer", Value::Null)?;
    put_sym(vm, &this, &c.k_ws, Value::Null)?;
    Ok(Value::Undefined)
}

fn wctrl_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.wctrl_proto)?;
    let stream = a.arg(0);
    put_sym(vm, &this, &c.k_ws, stream.clone())?;
    let ac = get(vm, &stream, "_abortController")?;
    let signal = get(vm, &ac, "signal")?;
    put(vm, &this, "signal", signal)?;
    Ok(this)
}

fn wctrl_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let s = get_sym(vm, &a.this, &c.k_ws)?;
    invoke(vm, &s, "_errorInternal", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

// =====================================================================================
// TransformStream
// =====================================================================================

fn ts_capture_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cell = unhost::<RefCell<Value>>(&a.slot(0));
    *cell.borrow_mut() = a.arg(0);
    let _ = vm;
    Ok(Value::Undefined)
}

fn ts_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.ts_proto)?;
    let mut transformer = a.arg(0);
    if transformer.is_undefined() {
        transformer = new_obj(vm);
    }
    let mut ws_strategy = a.arg(1);
    if ws_strategy.is_undefined() {
        ws_strategy = new_obj(vm);
    }
    let mut rs_strategy = a.arg(2);
    if rs_strategy.is_undefined() {
        rs_strategy = new_obj(vm);
    }
    if !transformer.truthy() {
        transformer = new_obj(vm);
    }
    let cell: Rc<RefCell<Value>> = Rc::new(RefCell::new(Value::Undefined));
    let src = vm.new_object();
    let start = func(vm, "start", 1, ts_capture_start, vec![host(cell.clone())]);
    src.set_str("start", start, WEC);
    let readable = construct(vm, &c.rs, &[Value::Obj(src), rs_strategy])?;
    put(vm, &this, "readable", readable)?;
    let rc = cell.borrow().clone();
    put(vm, &this, "_readableController", rc)?;
    let ctrl = construct(vm, &c.tsctrl, &[this.clone()])?;
    put(vm, &this, "_controller", ctrl)?;
    let sink = vm.new_object();
    let w = func(vm, "write", 1, ts_sink_write, vec![transformer.clone(), this.clone()]);
    let cl = func(vm, "close", 0, ts_sink_close, vec![transformer.clone(), this.clone()]);
    let ab = func(vm, "abort", 1, ts_sink_abort, vec![this.clone()]);
    sink.set_str("write", w, WEC);
    sink.set_str("close", cl, WEC);
    sink.set_str("abort", ab, WEC);
    let writable = construct(vm, &c.ws, &[Value::Obj(sink), ws_strategy])?;
    put(vm, &this, "writable", writable)?;
    let w = get(vm, &this, "writable")?;
    put(vm, &this, "_writable", w)?;
    if get(vm, &transformer, "start")?.is_callable() {
        let start = get(vm, &transformer, "start")?;
        let ctrl = get(vm, &this, "_controller")?;
        call_method(vm, &start, &transformer, "start", &[ctrl])?;
    }
    Ok(this)
}

fn ts_sink_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let transformer = a.slot(0);
    let me = a.slot(1);
    let chunk = a.arg(0);
    if get(vm, &transformer, "transform")?.is_callable() {
        let t = get(vm, &transformer, "transform")?;
        let ctrl = get(vm, &me, "_controller")?;
        let r = call_method(vm, &t, &transformer, "transform", &[chunk, ctrl])?;
        return resolved(vm, r);
    }
    let rc = get(vm, &me, "_readableController")?;
    invoke(vm, &rc, "enqueue", &[chunk])?;
    Ok(Value::Undefined)
}

fn ts_sink_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let transformer = a.slot(0);
    let me = a.slot(1);
    let flush = if get(vm, &transformer, "flush")?.is_callable() {
        let f = get(vm, &transformer, "flush")?;
        let ctrl = get(vm, &me, "_controller")?;
        let r = call_method(vm, &f, &transformer, "flush", &[ctrl])?;
        resolved(vm, r)?
    } else {
        resolved(vm, Value::Undefined)?
    };
    let f = func(vm, "", 0, ts_flush_done, vec![me]);
    invoke(vm, &flush, "then", &[f])
}

fn ts_flush_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let me = a.slot(0);
    let _ = (|| -> JsResult<Value> {
        let rc = get(vm, &me, "_readableController")?;
        invoke(vm, &rc, "close", &[])
    })();
    Ok(Value::Undefined)
}

fn ts_sink_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let me = a.slot(0);
    let rc = get(vm, &me, "_readableController")?;
    invoke(vm, &rc, "error", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn tsctrl_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.tsctrl_proto)?;
    put_sym(vm, &this, &c.k_ts, a.arg(0))?;
    Ok(this)
}

fn tsctrl_ts(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let c = ctx();
    get_sym(vm, this, &c.k_ts)
}

fn tsctrl_desired_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ts = tsctrl_ts(vm, &a.this)?;
    let rc = get(vm, &ts, "_readableController")?;
    if rc.truthy() {
        get(vm, &rc, "desiredSize")
    } else {
        Ok(Value::Null)
    }
}

fn tsctrl_enqueue(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ts = tsctrl_ts(vm, &a.this)?;
    let rc = get(vm, &ts, "_readableController")?;
    invoke(vm, &rc, "enqueue", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn tsctrl_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let e = a.arg(0);
    let ts = tsctrl_ts(vm, &a.this)?;
    let rc = get(vm, &ts, "_readableController")?;
    invoke(vm, &rc, "error", &[e.clone()])?;
    let ts = tsctrl_ts(vm, &a.this)?;
    let w = get(vm, &ts, "_writable")?;
    invoke(vm, &w, "_errorInternal", &[e])?;
    Ok(Value::Undefined)
}

fn tsctrl_terminate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let _ = (|| -> JsResult<Value> {
        let ts = tsctrl_ts(vm, &a.this)?;
        let rc = get(vm, &ts, "_readableController")?;
        invoke(vm, &rc, "close", &[])
    })();
    let ts = tsctrl_ts(vm, &a.this)?;
    let w = get(vm, &ts, "_writable")?;
    let e = type_error(vm, "TransformStream terminated");
    invoke(vm, &w, "_errorInternal", &[e])?;
    Ok(Value::Undefined)
}

// =====================================================================================
// Queuing strategies
// =====================================================================================

fn bl_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.bl_proto)?;
    let hwm = get(vm, &a.arg(0), "highWaterMark")?;
    put(vm, &this, "highWaterMark", hwm)?;
    Ok(this)
}

fn cq_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.cq_proto)?;
    let hwm = get(vm, &a.arg(0), "highWaterMark")?;
    put(vm, &this, "highWaterMark", hwm)?;
    Ok(this)
}

fn bl_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get(vm, &a.arg(0), "byteLength")
}

// =====================================================================================
// TextEncoderStream / TextDecoderStream / CompressionStream / DecompressionStream
// =====================================================================================

fn ts_wrapper_readable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ts = get(vm, &a.this, "_ts")?;
    get(vm, &ts, "readable")
}

fn ts_wrapper_writable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ts = get(vm, &a.this, "_ts")?;
    get(vm, &ts, "writable")
}

fn tes_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.tes_proto)?;
    let transformer = vm.new_object();
    let t = func(vm, "transform", 2, tes_transform, vec![]);
    transformer.set_str("transform", t, WEC);
    let ts = construct(vm, &c.ts, &[Value::Obj(transformer)])?;
    put(vm, &this, "_ts", ts)?;
    Ok(this)
}

fn tes_transform(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let bytes = str_to_utf8(s.units());
    let n = bytes.len();
    let u8 = new_u8(vm, bytes)?;
    if n > 0 {
        invoke(vm, &a.arg(1), "enqueue", &[u8])?;
    }
    Ok(Value::Undefined)
}

pub struct Decoder {
    pub fatal: bool,
    pub ignore_bom: bool,
}

/// The reference runtime's `TextDecoder` constructor checks (utf-8 only).
pub fn make_decoder(vm: &mut Vm, label: &Value, options: &Value) -> JsResult<Decoder> {
    let label = if label.is_undefined() { Value::str("utf-8") } else { label.clone() };
    let l = js_string(vm, &label)?.to_rust_string().to_lowercase();
    if l != "utf-8" && l != "utf8" && l != "unicode-1-1-utf-8" {
        let shown = vm.to_string(&label)?.to_rust_string();
        return vm.throw_range(format!("TextDecoder: unsupported encoding '{}' (utf-8 only for now)", shown));
    }
    let opts = if options.truthy() && options.type_of() == "object" { options.clone() } else { Value::Undefined };
    let (fatal, ignore_bom) = if opts.is_undefined() {
        (false, false)
    } else {
        (get(vm, &opts, "fatal")?.truthy(), get(vm, &opts, "ignoreBOM")?.truthy())
    };
    Ok(Decoder { fatal, ignore_bom })
}

/// `decoder.decode(input)` with the reference runtime's semantics.
pub fn decoder_decode(vm: &mut Vm, d: &Decoder, input: &Value) -> JsResult<JsStr> {
    if input.is_undefined() {
        return Ok(JsStr::empty());
    }
    let bytes = if is_array_buffer(input) || is_typed_array(input) {
        bytes_of_buffer_source(input)
    } else {
        return vm.throw_type("TextDecoder.decode expects a BufferSource");
    };
    let mut u = match utf8_to_str(&bytes, d.fatal) {
        Some(u) => u,
        None => return vm.throw_type("TextDecoder: invalid utf-8 (fatal)"),
    };
    if !d.ignore_bom && u.first() == Some(&0xFEFF) {
        u.remove(0);
    }
    Ok(JsStr::from_units(u))
}

fn tds_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.tds_proto)?;
    let mut options = a.arg(1);
    if options.is_undefined() {
        options = new_obj(vm);
    }
    let d = make_decoder(vm, &a.arg(0), &options)?;
    put(vm, &this, "_encoding", Value::str("utf-8"))?;
    let dv = host(Rc::new(d));
    let transformer = vm.new_object();
    let t = func(vm, "transform", 2, tds_transform, vec![dv.clone()]);
    let f = func(vm, "flush", 1, tds_flush, vec![dv]);
    transformer.set_str("transform", t, WEC);
    transformer.set_str("flush", f, WEC);
    let ts = construct(vm, &c.ts, &[Value::Obj(transformer)])?;
    put(vm, &this, "_ts", ts)?;
    Ok(this)
}

fn tds_transform(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let d = unhost::<Decoder>(&a.slot(0));
    let text = decoder_decode(vm, &d, &a.arg(0))?;
    if !text.is_empty() {
        invoke(vm, &a.arg(1), "enqueue", &[Value::Str(text)])?;
    }
    Ok(Value::Undefined)
}

fn tds_flush(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    // `dec.decode()` is always "" in the reference runtime: nothing to emit.
    Ok(Value::Undefined)
}

struct CodecState {
    codec: Codec,
    name: &'static str,
    chunks: RefCell<Vec<Value>>,
}

fn codec_stream(vm: &mut Vm, format: &Value, compress: bool) -> JsResult<Value> {
    let c = ctx();
    let name = if compress { "CompressionStream" } else { "DecompressionStream" };
    let f = js_string(vm, format)?.to_rust_string();
    let codec = if compress { Codec::for_compression_stream(&f) } else { Codec::for_decompression_stream(&f) };
    let codec = match codec {
        Some(k) => k,
        None => return vm.throw_type(format!("Unsupported {} format: '{}'", name, f)),
    };
    let st = host(Rc::new(CodecState { codec, name, chunks: RefCell::new(Vec::new()) }));
    let transformer = vm.new_object();
    let t = func(vm, "transform", 1, codec_transform, vec![st.clone()]);
    let fl = func(vm, "flush", 1, codec_flush, vec![st]);
    transformer.set_str("transform", t, WEC);
    transformer.set_str("flush", fl, WEC);
    construct(vm, &c.ts, &[Value::Obj(transformer)])
}

fn codec_transform(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = unhost::<CodecState>(&a.slot(0));
    let chunk = a.arg(0);
    if is_array_buffer(&chunk) || is_view(&chunk) {
        // kept by reference: bytes are read at flush time
        st.chunks.borrow_mut().push(chunk);
        Ok(Value::Undefined)
    } else {
        vm.throw_type(format!("{} expects BufferSource chunks", st.name))
    }
}

fn codec_flush(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = unhost::<CodecState>(&a.slot(0));
    let mut input = Vec::new();
    for ch in st.chunks.borrow().iter() {
        input.extend_from_slice(&bytes_of_buffer_source(ch));
    }
    if input.len() > MAX_TA {
        return vm.throw_range("Invalid typed array length");
    }
    let out = match st.codec.run(&input) {
        Ok(o) => o,
        Err(e) => return vm.throw_type(e.message),
    };
    if out.len() > MAX_TA {
        return vm.throw_range("Invalid typed array length");
    }
    if !out.is_empty() {
        let u = new_u8(vm, out)?;
        invoke(vm, &a.arg(0), "enqueue", &[u])?;
    }
    Ok(Value::Undefined)
}

fn cs_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.cs_proto)?;
    let ts = codec_stream(vm, &a.arg(0), true)?;
    put(vm, &this, "_ts", ts)?;
    Ok(this)
}

fn ds_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = ctx();
    let this = new_this(vm, a, &c.ds_proto)?;
    let ts = codec_stream(vm, &a.arg(0), false)?;
    put(vm, &this, "_ts", ts)?;
    Ok(this)
}

// =====================================================================================
// Helpers for other runtime modules (Response bodies, Blob.stream(), ...)
// =====================================================================================

/// Is `v` a ReadableStream (instanceof)?
pub fn is_readable_stream(vm: &mut Vm, v: &Value) -> bool {
    match try_ctx() {
        Some(c) => vm.instance_of(v, &Value::Obj(c.rs.clone())).unwrap_or(false),
        None => false,
    }
}

/// `new ReadableStream(source)`
pub fn new_readable_stream(vm: &mut Vm, source: Value) -> JsResult<Value> {
    let c = ctx();
    construct(vm, &c.rs, &[source])
}
