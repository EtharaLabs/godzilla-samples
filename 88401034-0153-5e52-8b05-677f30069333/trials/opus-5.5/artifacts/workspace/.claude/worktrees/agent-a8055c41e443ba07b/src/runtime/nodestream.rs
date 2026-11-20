// node:stream — Stream / Readable / Writable / Duplex / Transform / PassThrough, the module
// functions (finished, pipeline, compose, ...), stream/promises, stream/consumers, stream/web,
// and process.stdin.
//
// Modelled on the reference runtime's small port of Node streams:
// * state lives in JS-visible `_readableState` / `_writableState` objects;
// * flowing data is delivered from a microtask (`resume()` queues `flow`), 'end' is emitted
//   from a microtask once the buffer is drained;
// * writes are serialised through a promise chain (`_writableState.tail`), `end()` waits for
//   the chain before running `_final` and emitting 'finish';
// * destroy() emits 'error' / 'close' from a microtask.
// The classes are shared with fs (ReadStream / WriteStream extend Readable / Writable).
//
// The helpers at the top are also used by the other node modules of this crate (http, net,
// child_process, readline).

use crate::builtins::promise::{perform_then_internal, promise_resolve_intrinsic};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};

// ============================================================================================
// shared helpers
// ============================================================================================

pub fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

/// `v.k` on any value (throws on nullish bases).
pub fn getp(vm: &mut Vm, v: &Value, k: &str) -> JsResult<Value> {
    vm.get_prop_of(v, &key(k))
}

/// `v.k = x` (strict).
pub fn setp(vm: &mut Vm, v: &Value, k: &str, x: Value) -> JsResult<()> {
    vm.set_prop_of(v, key(k), x, true)
}

/// `Number(v)` (BigInts convert).
pub fn to_num(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    match v {
        Value::Num(n) => Ok(*n),
        Value::BigInt(b) => Ok(b.to_string_radix(10).parse::<f64>().unwrap_or(f64::NAN)),
        _ => vm.to_number(v),
    }
}

/// `String(v)` (symbols allowed).
pub fn string_of(vm: &mut Vm, v: &Value) -> JsResult<String> {
    match v {
        Value::Sym(s) => Ok(s.descriptive_string()),
        _ => Ok(vm.to_string(v)?.to_rust_string()),
    }
}

/// `this.m(...args)`
pub fn call_method(vm: &mut Vm, this: &Value, m: &str, args: &[Value]) -> JsResult<Value> {
    let f = getp(vm, this, m)?;
    if !f.is_callable() {
        return vm.throw_type(format!("(intermediate value).{} is not a function", m));
    }
    vm.call(&f, this.clone(), args)
}

/// `this.emit(ev, ...args)`
pub fn emit(vm: &mut Vm, this: &Value, ev: &str, args: &[Value]) -> JsResult<Value> {
    let mut all = Vec::with_capacity(args.len() + 1);
    all.push(Value::str(ev));
    all.extend_from_slice(args);
    call_method(vm, this, "emit", &all)
}

pub fn closure(vm: &mut Vm, name: &str, len: u32, f: NativeFn, slots: Vec<Value>) -> Value {
    Value::Obj(vm.native_closure(name, len, f, slots))
}

/// process.nextTick(f)
pub fn next_tick(vm: &mut Vm, f: Value) -> JsResult<()> {
    if let Some(p) = vm.host.process_obj.clone() {
        let nt = vm.get_str(&p, "nextTick")?;
        if nt.is_callable() {
            vm.call(&nt, Value::Obj(p), &[f])?;
            return Ok(());
        }
    }
    vm.host.callbacks.push_back((f, Vec::new()));
    Ok(())
}

/// queueMicrotask(f) the reference way: a reaction on a resolved promise (an exception surfaces
/// as an unhandled rejection).
pub fn queue_microtask(vm: &mut Vm, f: Value) {
    match promise_resolve_intrinsic(vm, Value::Undefined) {
        Ok(p) => {
            let _ = crate::builtins::promise::promise_then(vm, &p, f, Value::Undefined);
        }
        Err(_) => vm.jobs.push_back(crate::vm::Job::Callback(f, Vec::new())),
    }
}

/// Promise.resolve(v) for a non-thenable v.
pub fn resolved(vm: &mut Vm, v: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.resolve, Value::Undefined, &[v]);
    cap.promise
}

/// Promise.reject(e)
pub fn rejected(vm: &mut Vm, e: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
    cap.promise
}

pub fn iter_result(vm: &mut Vm, v: Value, done: bool) -> Value {
    Value::Obj(vm.obj_from(vec![("value", v), ("done", Value::Bool(done))]))
}

/// Run `f` on a Host payload of type T.
pub fn with_host<T: 'static, R>(v: &Value, f: impl FnOnce(&T) -> R) -> Option<R> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<T>().map(f),
            _ => None,
        },
        _ => None,
    }
}

pub fn host_obj<T: 'static>(t: T) -> Value {
    Value::Obj(Obj::new(None, ObjKind::Host(Box::new(t))))
}

/// The Buffer constructor of node:buffer.
pub fn buffer_ctor(vm: &mut Vm) -> Value {
    match crate::runtime::node::builtin_module(vm, "buffer") {
        Ok(Some(m)) => getp(vm, &m, "Buffer").unwrap_or(Value::Undefined),
        _ => vm.global.get_own_str("Buffer").unwrap_or(Value::Undefined),
    }
}

/// `Buffer.<m>(...args)`
pub fn buffer_call(vm: &mut Vm, m: &str, args: &[Value]) -> JsResult<Value> {
    let b = buffer_ctor(vm);
    call_method(vm, &b, m, args)
}

pub fn new_buffer(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    crate::runtime::buffer::new_buffer_value(vm, bytes)
}

pub fn is_uint8_array(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(&o.borrow().kind, ObjKind::TypedArray(t) if t.kind == TAKind::Uint8))
}

/// `new Error(msg)` with an own `code`.
pub fn error_with_code(vm: &mut Vm, kind: &str, msg: &str, code: &str) -> Value {
    let e = vm.make_error(kind, msg);
    if let Value::Obj(o) = &e {
        o.set_prop(key("code"), Value::str(code), WEC);
    }
    e
}

/// `Array.prototype.push.call(arr, v)`
pub fn arr_push(vm: &mut Vm, arr: &Value, v: Value) -> JsResult<()> {
    call_method(vm, arr, "push", &[v])?;
    Ok(())
}

pub fn arr_len(vm: &mut Vm, arr: &Value) -> JsResult<f64> {
    let l = getp(vm, arr, "length")?;
    to_num(vm, &l)
}

fn require_new(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.new_target {
        Some(nt) => Ok(nt.clone()),
        None => vm.throw_type("Class constructor cannot be invoked without 'new'"),
    }
}

/// Allocate `this` for a native class constructor (prototype from new.target).
pub fn new_instance(vm: &mut Vm, a: &Args, fallback: &Obj) -> JsResult<Obj> {
    let nt = require_new(vm, a)?;
    let proto = vm.proto_from_nt(&Some(nt), fallback)?;
    Ok(Obj::new(Some(proto), ObjKind::Ordinary))
}

/// `opts = {}` default parameter.
pub fn opts_or_empty(vm: &mut Vm, v: Value) -> Value {
    if v.is_undefined() {
        Value::Obj(vm.new_object())
    } else {
        v
    }
}

/// A native class `name` extending `parent` (constructor + prototype objects).
pub fn make_class(vm: &mut Vm, name: &str, len: u32, ctor: NativeFn, parent: Option<(&Obj, &Obj)>) -> (Obj, Obj) {
    let pproto = parent.map(|p| p.1.clone()).unwrap_or_else(|| vm.intr.object_proto.clone());
    let proto = Obj::new(Some(pproto), ObjKind::Ordinary);
    let c = vm.native_ctor(name, len, ctor, &proto);
    if let Some((pc, _)) = parent {
        c.borrow_mut().proto = Some(pc.clone());
    }
    (c, proto)
}

/// A plain (constructible) function as created by a JS `function` declaration.
pub fn plain_fn(vm: &mut Vm, name: &str, len: u32, f: NativeFn) -> Obj {
    let o = vm.native_fn(name, len, f);
    vm.make_ctor(&o);
    let proto = vm.new_object();
    proto.set_prop(key("constructor"), Value::Obj(o.clone()), WC);
    o.set_prop(key("prototype"), Value::Obj(proto), WRITABLE);
    o
}

fn return_this(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

/// Run `f` with the reference's JS frames (outermost first) on the trace, so errors created
/// inside carry the same `stack` lines as the reference's JS implementation.
pub fn with_frames<T>(vm: &mut Vm, names: &[&str], f: impl FnOnce(&mut Vm) -> JsResult<T>) -> JsResult<T> {
    for n in names {
        vm.trace.push(crate::vm::TraceEntry { name: JsStr::from_str(n) });
    }
    let r = f(vm);
    let keep = vm.trace.len().saturating_sub(names.len());
    vm.trace.truncate(keep);
    r
}

/// A native whose reference counterpart's JS frame(s) are live while it runs.
#[macro_export]
macro_rules! framed_native {
    ($name:ident, [$($frame:expr),*], $inner:ident) => {
        fn $name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
            $crate::runtime::nodestream::with_frames(vm, &[$($frame),*], |vm| $inner(vm, a))
        }
    };
}

// ============================================================================================
// classes
// ============================================================================================

#[derive(Clone)]
pub struct Classes {
    pub ee: Obj,
    pub ee_proto: Obj,
    pub stream: Obj,
    pub stream_proto: Obj,
    pub readable: Obj,
    pub readable_proto: Obj,
    pub writable: Obj,
    pub writable_proto: Obj,
    pub duplex: Obj,
    pub duplex_proto: Obj,
    pub transform: Obj,
    pub transform_proto: Obj,
    pub passthrough: Obj,
    #[allow(dead_code)]
    pub passthrough_proto: Obj,
}

thread_local! {
    static CLASSES: RefCell<Option<Classes>> = RefCell::new(None);
    /// (default highWaterMark, default objectMode highWaterMark)
    static HWM: Cell<(f64, f64)> = Cell::new((65536.0, 16.0));
}

pub fn default_hwm(object_mode: bool) -> f64 {
    let (b, o) = HWM.with(|h| h.get());
    if object_mode {
        o
    } else {
        b
    }
}

pub fn classes(vm: &mut Vm) -> Classes {
    if let Some(c) = CLASSES.with(|c| c.borrow().clone()) {
        return c;
    }
    let c = build_classes(vm);
    CLASSES.with(|s| *s.borrow_mut() = Some(c.clone()));
    c
}

fn build_classes(vm: &mut Vm) -> Classes {
    let ee_v = crate::runtime::node::builtin_module(vm, "events").ok().flatten().unwrap_or(Value::Undefined);
    let (ee, ee_proto) = match &ee_v {
        Value::Obj(e) => {
            let p = e.get_own_str("prototype").and_then(|p| p.as_obj().cloned()).unwrap_or_else(|| vm.intr.object_proto.clone());
            (e.clone(), p)
        }
        _ => {
            let p = vm.new_object();
            (vm.native_fn("EventEmitter", 0, noop), p)
        }
    };
    let sai = vm.intr.sym_async_iterator.clone();

    // Stream extends EventEmitter
    let (stream, stream_proto) = make_class(vm, "Stream", 0, stream_ctor, Some((&ee, &ee_proto)));

    // Readable extends Stream
    let (readable, rp) = make_class(vm, "Readable", 0, readable_ctor_f, Some((&stream, &stream_proto)));
    vm.def_method(&rp, "_read", 0, noop);
    vm.def_getter(&rp, "readableLength", readable_length);
    vm.def_getter(&rp, "readableHighWaterMark", readable_hwm);
    vm.def_getter(&rp, "readableObjectMode", readable_object_mode);
    let rmethods: &[(&str, u32, NativeFn)] = &[
        ("push", 1, readable_push),
        ("read", 1, readable_read_f),
        ("setEncoding", 1, readable_set_encoding),
        ("on", 2, readable_on),
        ("addListener", 2, readable_add_listener),
        ("once", 2, readable_once),
        ("resume", 0, readable_resume),
        ("pause", 0, readable_pause),
        ("isPaused", 0, readable_is_paused),
        ("pipe", 1, readable_pipe),
        ("unpipe", 0, readable_unpipe),
        ("destroy", 1, readable_destroy),
    ];
    for (n, l, f) in rmethods {
        vm.def_method(&rp, n, *l, *f);
    }
    vm.def_sym_method(&rp, &sai, "[Symbol.asyncIterator]", 0, readable_async_iterator);
    let from = plain_fn(vm, "", 2, readable_from);
    readable.set_prop(key("from"), Value::Obj(from), WEC);

    // Writable extends Stream
    let (writable, wp) = make_class(vm, "Writable", 0, writable_ctor_f, Some((&stream, &stream_proto)));
    let wmethods: &[(&str, u32, NativeFn)] = &[
        ("_write", 3, writable_default_write),
        ("write", 3, writable_write_f),
        ("_queueBatch", 1, writable_queue_batch),
        ("end", 3, writable_end),
        ("cork", 0, writable_cork),
        ("uncork", 0, writable_uncork),
        ("setDefaultEncoding", 0, return_this),
    ];
    let mut wfns: Vec<(&str, Obj)> = Vec::new();
    for (n, l, f) in wmethods {
        let fo = vm.def_method(&wp, n, *l, *f);
        wfns.push((n, fo));
    }
    let g1 = vm.def_getter(&wp, "writableLength", writable_length);
    let g2 = vm.def_getter(&wp, "writableHighWaterMark", writable_hwm);
    let g3 = vm.def_getter(&wp, "writableObjectMode", writable_object_mode);
    vm.def_method(&wp, "destroy", 1, writable_destroy);

    // Duplex extends Readable, with Writable's members (but destroy) mixed in
    let (duplex, dp) = make_class(vm, "Duplex", 0, duplex_ctor_f, Some((&readable, &rp)));
    for (n, fo) in &wfns {
        dp.set_prop(key(n), Value::Obj(fo.clone()), WEC);
    }
    for (n, g) in [("writableLength", g1), ("writableHighWaterMark", g2), ("writableObjectMode", g3)] {
        dp.set_accessor(key(n), Some(g), None, CONFIGURABLE);
    }

    // Transform extends Duplex
    let (transform, tp) = make_class(vm, "Transform", 0, transform_ctor_f, Some((&duplex, &dp)));
    vm.def_method(&tp, "_transform", 3, transform_default_transform);
    vm.def_method(&tp, "_write", 3, transform_write);
    vm.def_method(&tp, "_final", 1, transform_final);

    // PassThrough extends Transform
    let (passthrough, pp) = make_class(vm, "PassThrough", 0, passthrough_ctor_f, Some((&transform, &tp)));
    vm.def_method(&pp, "_transform", 3, transform_default_transform);

    Classes {
        ee,
        ee_proto,
        stream,
        stream_proto,
        readable,
        readable_proto: rp,
        writable,
        writable_proto: wp,
        duplex,
        duplex_proto: dp,
        transform,
        transform_proto: tp,
        passthrough,
        passthrough_proto: pp,
    }
}

// ============================================================================================
// Readable
// ============================================================================================

fn rstate(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    getp(vm, this, "_readableState")
}

fn wstate(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    getp(vm, this, "_writableState")
}

fn snum(vm: &mut Vm, st: &Value, k: &str) -> JsResult<f64> {
    let v = getp(vm, st, k)?;
    to_num(vm, &v)
}

fn chunk_len(vm: &mut Vm, chunk: &Value) -> JsResult<f64> {
    let l = getp(vm, chunk, "length")?;
    to_num(vm, &l)
}

fn hwm_option(vm: &mut Vm, opts: &Value, om: bool) -> JsResult<Value> {
    let hwm = getp(vm, opts, "highWaterMark")?;
    Ok(if hwm.is_undefined() { Value::Num(default_hwm(om)) } else { Value::Num(to_num(vm, &hwm)?) })
}

/// The Readable constructor body (`super()` + readable state), used by subclasses.
pub fn readable_init(vm: &mut Vm, o: &Obj, opts: &Value) -> JsResult<()> {
    crate::runtime::events::init_emitter(vm, o);
    let this = Value::Obj(o.clone());
    let om = getp(vm, opts, "objectMode")?.truthy() || getp(vm, opts, "readableObjectMode")?.truthy();
    let hwm = hwm_option(vm, opts, om)?;
    let buffer = Value::Obj(vm.new_array(Vec::new()));
    let st = vm.obj_from(vec![
        ("flowing", Value::Null),
        ("ended", Value::Bool(false)),
        ("endEmitted", Value::Bool(false)),
        ("buffer", buffer),
        ("length", Value::Num(0.0)),
        ("objectMode", Value::Bool(om)),
        ("highWaterMark", hwm),
        ("encoding", Value::Null),
        ("destroyed", Value::Bool(false)),
        ("reading", Value::Bool(false)),
        ("errored", Value::Null),
    ]);
    setp(vm, &this, "_readableState", Value::Obj(st))?;
    setp(vm, &this, "readable", Value::Bool(true))?;
    let enc = getp(vm, opts, "encoding")?;
    if enc.truthy() {
        call_method(vm, &this, "setEncoding", &[enc])?;
    }
    let read = getp(vm, opts, "read")?;
    if read.is_callable() {
        setp(vm, &this, "_read", read)?;
    }
    Ok(())
}

/// writableState(opts)
fn writable_state(vm: &mut Vm, opts: &Value) -> JsResult<Value> {
    let om = getp(vm, opts, "objectMode")?.truthy() || getp(vm, opts, "writableObjectMode")?.truthy();
    let hwm = hwm_option(vm, opts, om)?;
    let cork = Value::Obj(vm.new_array(Vec::new()));
    let tail = resolved(vm, Value::Undefined);
    let st = vm.obj_from(vec![
        ("ended", Value::Bool(false)),
        ("finished", Value::Bool(false)),
        ("destroyed", Value::Bool(false)),
        ("corked", Value::Num(0.0)),
        ("corkBuffer", cork),
        ("errored", Value::Null),
        ("tail", tail),
        ("objectMode", Value::Bool(om)),
        ("highWaterMark", hwm),
        ("length", Value::Num(0.0)),
        ("needDrain", Value::Bool(false)),
    ]);
    Ok(Value::Obj(st))
}

/// The writable half of a constructor body (state + `_write` / `_writev` / `_final` options).
fn writable_state_init(vm: &mut Vm, o: &Obj, opts: &Value) -> JsResult<()> {
    let this = Value::Obj(o.clone());
    let st = writable_state(vm, opts)?;
    setp(vm, &this, "_writableState", st)?;
    setp(vm, &this, "writable", Value::Bool(true))?;
    for (opt, prop) in [("write", "_write"), ("writev", "_writev"), ("final", "_final")] {
        let f = getp(vm, opts, opt)?;
        if f.is_callable() {
            setp(vm, &this, prop, f)?;
        }
    }
    Ok(())
}

/// The Writable constructor body (`super()` + writable state), used by subclasses.
pub fn writable_init(vm: &mut Vm, o: &Obj, opts: &Value) -> JsResult<()> {
    crate::runtime::events::init_emitter(vm, o);
    writable_state_init(vm, o, opts)
}

/// The Duplex constructor body.
pub fn duplex_init(vm: &mut Vm, o: &Obj, opts: &Value) -> JsResult<()> {
    readable_init(vm, o, opts)?;
    writable_state_init(vm, o, opts)
}

fn stream_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes_or_proto(vm, |c| c.stream_proto.clone());
    let o = new_instance(vm, a, &c)?;
    crate::runtime::events::init_emitter(vm, &o);
    Ok(Value::Obj(o))
}

fn classes_or_proto(vm: &mut Vm, f: fn(&Classes) -> Obj) -> Obj {
    match CLASSES.with(|c| c.borrow().as_ref().map(f)) {
        Some(p) => p,
        None => vm.intr.object_proto.clone(),
    }
}

fn readable_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = classes_or_proto(vm, |c| c.readable_proto.clone());
    let o = new_instance(vm, a, &fb)?;
    let opts = opts_or_empty(vm, a.arg(0));
    readable_init(vm, &o, &opts)?;
    Ok(Value::Obj(o))
}

fn writable_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = classes_or_proto(vm, |c| c.writable_proto.clone());
    let o = new_instance(vm, a, &fb)?;
    let opts = opts_or_empty(vm, a.arg(0));
    writable_init(vm, &o, &opts)?;
    Ok(Value::Obj(o))
}

fn duplex_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = classes_or_proto(vm, |c| c.duplex_proto.clone());
    let o = new_instance(vm, a, &fb)?;
    let opts = opts_or_empty(vm, a.arg(0));
    duplex_init(vm, &o, &opts)?;
    Ok(Value::Obj(o))
}

fn transform_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = classes_or_proto(vm, |c| c.transform_proto.clone());
    let o = new_instance(vm, a, &fb)?;
    let opts = opts_or_empty(vm, a.arg(0));
    duplex_init(vm, &o, &opts)?;
    let this = Value::Obj(o.clone());
    for (opt, prop) in [("transform", "_transform"), ("flush", "_flush")] {
        let f = getp(vm, &opts, opt)?;
        if f.is_callable() {
            setp(vm, &this, prop, f)?;
        }
    }
    Ok(this)
}

/// maybeEmitEnd(stream)
fn maybe_emit_end(vm: &mut Vm, this: &Value) -> JsResult<()> {
    let st = rstate(vm, this)?;
    let ended = getp(vm, &st, "ended")?.truthy();
    let emitted = getp(vm, &st, "endEmitted")?.truthy();
    let len = snum(vm, &st, "length")?;
    let flowing = getp(vm, &st, "flowing")?;
    if ended && !emitted && len == 0.0 && !matches!(flowing, Value::Bool(false)) {
        setp(vm, &st, "endEmitted", Value::Bool(true))?;
        setp(vm, &st, "flowing", Value::Bool(false))?;
        setp(vm, this, "readable", Value::Bool(false))?;
        let f = closure(vm, "", 0, emit_end_job, vec![this.clone()]);
        queue_microtask(vm, f);
    }
    Ok(())
}

fn emit_end_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "end", &[])?;
    Ok(Value::Undefined)
}

fn flow_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flow(vm, a.slot(0))?;
    Ok(Value::Undefined)
}

/// flow(stream): deliver buffered chunks while flowing.
fn flow(vm: &mut Vm, this: Value) -> JsResult<()> {
    let st = rstate(vm, &this)?;
    loop {
        let flowing = getp(vm, &st, "flowing")?.truthy();
        let buf = getp(vm, &st, "buffer")?;
        if !flowing || arr_len(vm, &buf)? == 0.0 {
            break;
        }
        let chunk = call_method(vm, &buf, "shift", &[])?;
        let om = getp(vm, &st, "objectMode")?.truthy();
        let l = if om { 1.0 } else { chunk_len(vm, &chunk)? };
        let cur = snum(vm, &st, "length")?;
        setp(vm, &st, "length", Value::Num(cur - l))?;
        emit(vm, &this, "data", &[chunk])?;
    }
    maybe_emit_end(vm, &this)
}

fn readable_push(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let st = rstate(vm, &this)?;
    let mut chunk = a.arg(0);
    if chunk.is_null() {
        setp(vm, &st, "ended", Value::Bool(true))?;
        maybe_emit_end(vm, &this)?;
        return Ok(Value::Bool(false));
    }
    if getp(vm, &st, "destroyed")?.truthy() {
        return Ok(Value::Bool(false));
    }
    let enc = getp(vm, &st, "encoding")?;
    if enc.truthy() && is_uint8_array(&chunk) {
        let b = buffer_call(vm, "from", &[chunk])?;
        chunk = call_method(vm, &b, "toString", &[enc])?;
    }
    if getp(vm, &st, "flowing")?.truthy() {
        emit(vm, &this, "data", &[chunk])?;
    } else {
        let buf = getp(vm, &st, "buffer")?;
        arr_push(vm, &buf, chunk.clone())?;
        let om = getp(vm, &st, "objectMode")?.truthy();
        let l = if om { Value::Num(1.0) } else { getp(vm, &chunk, "length")? };
        let cur = getp(vm, &st, "length")?;
        let n = vm.op_add(&cur, &l)?;
        setp(vm, &st, "length", n)?;
        emit(vm, &this, "readable", &[])?;
    }
    let len = getp(vm, &st, "length")?;
    let hwm = getp(vm, &st, "highWaterMark")?;
    Ok(Value::Bool(vm.op_compare(crate::bytecode::Op::Lt, &len, &hwm)?))
}

fn readable_read(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let st = rstate(vm, &this)?;
    if getp(vm, &st, "objectMode")?.truthy() {
        let buf = getp(vm, &st, "buffer")?;
        if arr_len(vm, &buf)? == 0.0 {
            return Ok(Value::Null);
        }
        let cur = snum(vm, &st, "length")?;
        setp(vm, &st, "length", Value::Num(cur - 1.0))?;
        let buf = getp(vm, &st, "buffer")?;
        let v = call_method(vm, &buf, "shift", &[])?;
        maybe_emit_end(vm, &this)?;
        return Ok(v);
    }
    let size = a.arg(0);
    let mut wanted = if size.is_nullish() { snum(vm, &st, "length")? } else { to_num(vm, &size)? };
    if !(wanted.is_finite() && wanted.fract() == 0.0) || wanted < 0.0 {
        return vm.throw_range("The value of size is out of range");
    }
    if wanted == 0.0 {
        maybe_emit_end(vm, &this)?;
        return Ok(Value::Null);
    }
    let len = snum(vm, &st, "length")?;
    if len < wanted {
        if !getp(vm, &st, "ended")?.truthy() {
            return Ok(Value::Null);
        }
        wanted = len;
    }
    let buf = getp(vm, &st, "buffer")?;
    if arr_len(vm, &buf)? == 0.0 {
        return Ok(Value::Null);
    }
    let mut chunks = Vec::new();
    let mut remaining = wanted;
    while remaining > 0.0 && arr_len(vm, &buf)? > 0.0 {
        let first = vm.get_elem(&buf, &Value::Num(0.0))?;
        let cl = chunk_len(vm, &first)?;
        if cl <= remaining {
            let c = call_method(vm, &buf, "shift", &[])?;
            chunks.push(c);
            remaining -= cl;
        } else {
            let head = call_method(vm, &first, "slice", &[Value::Num(0.0), Value::Num(remaining)])?;
            chunks.push(head);
            let tail = call_method(vm, &first, "slice", &[Value::Num(remaining)])?;
            vm.set_elem(&buf, &Value::Num(0.0), tail, true)?;
            remaining = 0.0;
        }
    }
    let cur = snum(vm, &st, "length")?;
    setp(vm, &st, "length", Value::Num(cur - wanted))?;
    let enc = getp(vm, &st, "encoding")?;
    let out = if enc.truthy() {
        let arr = Value::Obj(vm.new_array(chunks));
        call_method(vm, &arr, "join", &[Value::str("")])?
    } else {
        let mut bufs = Vec::with_capacity(chunks.len());
        for c in chunks {
            bufs.push(buffer_call(vm, "from", &[c])?);
        }
        let arr = Value::Obj(vm.new_array(bufs));
        buffer_call(vm, "concat", &[arr, Value::Num(wanted)])?
    };
    maybe_emit_end(vm, &this)?;
    Ok(out)
}

fn readable_set_encoding(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    let s = string_of(vm, &a.arg(0))?.to_lowercase().replacen('-', "", 1);
    setp(vm, &st, "encoding", Value::str(&s))?;
    Ok(a.this.clone())
}

fn ee_method(vm: &mut Vm, name: &str) -> JsResult<Value> {
    let p = classes(vm).ee_proto;
    vm.get_str(&p, name)
}

fn is_event(v: &Value, name: &str) -> bool {
    matches!(v, Value::Str(s) if s.eq_str(name))
}

fn readable_on(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let on = ee_method(vm, "on")?;
    let res = vm.call(&on, a.this.clone(), &[a.arg(0), a.arg(1)])?;
    if is_event(&a.arg(0), "data") {
        let st = rstate(vm, &a.this)?;
        if !matches!(getp(vm, &st, "flowing")?, Value::Bool(false)) {
            call_method(vm, &a.this, "resume", &[])?;
        }
    }
    Ok(res)
}

fn readable_add_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.this, "on", &[a.arg(0), a.arg(1)])
}

fn readable_once(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let once = ee_method(vm, "once")?;
    let res = vm.call(&once, a.this.clone(), &[a.arg(0), a.arg(1)])?;
    if is_event(&a.arg(0), "data") {
        let st = rstate(vm, &a.this)?;
        if !matches!(getp(vm, &st, "flowing")?, Value::Bool(false)) {
            call_method(vm, &a.this, "resume", &[])?;
        }
    }
    Ok(res)
}

fn readable_resume(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    if getp(vm, &st, "flowing")?.truthy() {
        return Ok(a.this.clone());
    }
    setp(vm, &st, "flowing", Value::Bool(true))?;
    let f = closure(vm, "", 0, flow_job, vec![a.this.clone()]);
    queue_microtask(vm, f);
    Ok(a.this.clone())
}

fn readable_pause(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    setp(vm, &st, "flowing", Value::Bool(false))?;
    Ok(a.this.clone())
}

fn readable_is_paused(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    Ok(Value::Bool(matches!(getp(vm, &st, "flowing")?, Value::Bool(false))))
}

fn readable_pipe(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let dest = a.arg(0);
    let opts = opts_or_empty(vm, a.arg(1));
    let ondata = closure(vm, "", 1, pipe_on_data, vec![this.clone(), dest.clone()]);
    call_method(vm, &this, "on", &[Value::str("data"), ondata])?;
    let end = getp(vm, &opts, "end")?;
    if !matches!(end, Value::Bool(false)) {
        let onend = closure(vm, "", 0, pipe_on_end, vec![dest.clone()]);
        call_method(vm, &this, "on", &[Value::str("end"), onend])?;
    }
    let onerr = closure(vm, "", 1, pipe_on_error, vec![dest.clone()]);
    call_method(vm, &this, "on", &[Value::str("error"), onerr])?;
    if getp(vm, &dest, "emit")?.truthy() {
        emit(vm, &dest, "pipe", &[this])?;
    }
    Ok(dest)
}

fn pipe_on_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (src, dest) = (a.slot(0), a.slot(1));
    let ok = call_method(vm, &dest, "write", &[a.arg(0)])?;
    if matches!(ok, Value::Bool(false)) && getp(vm, &src, "pause")?.is_callable() {
        call_method(vm, &src, "pause", &[])?;
        let resume = closure(vm, "", 0, pipe_resume, vec![src]);
        call_method(vm, &dest, "once", &[Value::str("drain"), resume])?;
    }
    Ok(Value::Undefined)
}

fn pipe_resume(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "resume", &[])
}

fn pipe_on_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "end", &[])
}

fn pipe_on_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let dest = a.slot(0);
    if getp(vm, &dest, "destroy")?.truthy() {
        call_method(vm, &dest, "destroy", &[a.arg(0)])?;
    }
    Ok(Value::Undefined)
}

fn readable_unpipe(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.this, "pause", &[])?;
    Ok(a.this.clone())
}

fn destroy_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let err = a.slot(1);
    if err.truthy() {
        emit(vm, &this, "error", &[err])?;
    }
    emit(vm, &this, "close", &[])?;
    Ok(Value::Undefined)
}

fn readable_destroy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let st = rstate(vm, &this)?;
    if getp(vm, &st, "destroyed")?.truthy() {
        return Ok(this);
    }
    setp(vm, &st, "destroyed", Value::Bool(true))?;
    let err = a.arg(0);
    if err.truthy() {
        setp(vm, &st, "errored", err.clone())?;
        let ws = getp(vm, &this, "_writableState")?;
        if ws.truthy() {
            setp(vm, &ws, "errored", err.clone())?;
        }
    }
    setp(vm, &this, "readable", Value::Bool(false))?;
    let job = closure(vm, "", 0, destroy_job, vec![this.clone(), err]);
    queue_microtask(vm, job);
    Ok(this)
}

fn readable_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    getp(vm, &st, "length")
}

fn readable_hwm(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    getp(vm, &st, "highWaterMark")
}

fn readable_object_mode(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = rstate(vm, &a.this)?;
    getp(vm, &st, "objectMode")
}

// --- Readable.prototype[Symbol.asyncIterator] ---

struct RIter {
    queue: RefCell<std::collections::VecDeque<Value>>,
    done: Cell<bool>,
    error: RefCell<Option<Value>>,
    pending: RefCell<Option<(Value, Value)>>,
}

fn riter<R>(v: &Value, f: impl FnOnce(&RIter) -> R) -> Option<R> {
    with_host::<RIter, R>(v, f)
}

fn riter_settle(vm: &mut Vm, st: &Value) -> JsResult<()> {
    let pending = riter(st, |s| s.pending.borrow().clone()).flatten();
    let (res, rej) = match pending {
        Some(p) => p,
        None => return Ok(()),
    };
    let err = riter(st, |s| s.error.borrow().clone()).flatten();
    if let Some(e) = err {
        riter(st, |s| *s.pending.borrow_mut() = None);
        vm.call(&rej, Value::Undefined, &[e])?;
        return Ok(());
    }
    let item = riter(st, |s| s.queue.borrow_mut().pop_front()).flatten();
    if let Some(v) = item {
        riter(st, |s| *s.pending.borrow_mut() = None);
        let r = iter_result(vm, v, false);
        vm.call(&res, Value::Undefined, &[r])?;
        return Ok(());
    }
    if riter(st, |s| s.done.get()).unwrap_or(false) {
        riter(st, |s| *s.pending.borrow_mut() = None);
        let r = iter_result(vm, Value::Undefined, true);
        vm.call(&res, Value::Undefined, &[r])?;
    }
    Ok(())
}

fn riter_on_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let c = a.arg(0);
    riter(&st, |s| s.queue.borrow_mut().push_back(c));
    riter_settle(vm, &st)?;
    Ok(Value::Undefined)
}

fn riter_on_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    riter(&st, |s| s.done.set(true));
    riter_settle(vm, &st)?;
    Ok(Value::Undefined)
}

fn riter_on_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let e = a.arg(0);
    riter(&st, |s| *s.error.borrow_mut() = Some(e));
    riter_settle(vm, &st)?;
    Ok(Value::Undefined)
}

fn riter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    if let Some(v) = riter(&st, |s| s.queue.borrow_mut().pop_front()).flatten() {
        let r = iter_result(vm, v, false);
        return Ok(resolved(vm, r));
    }
    if let Some(e) = riter(&st, |s| s.error.borrow().clone()).flatten() {
        return Ok(rejected(vm, e));
    }
    if riter(&st, |s| s.done.get()).unwrap_or(false) {
        let r = iter_result(vm, Value::Undefined, true);
        return Ok(resolved(vm, r));
    }
    let cap = vm.new_promise_capability_intrinsic();
    riter(&st, |s| *s.pending.borrow_mut() = Some((cap.resolve.clone(), cap.reject.clone())));
    Ok(cap.promise)
}

fn riter_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(1), "destroy", &[])?;
    let r = iter_result(vm, Value::Undefined, true);
    Ok(resolved(vm, r))
}

fn readable_async_iterator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let st = host_obj(RIter { queue: RefCell::new(Default::default()), done: Cell::new(false), error: RefCell::new(None), pending: RefCell::new(None) });
    let ondata = closure(vm, "", 1, riter_on_data, vec![st.clone()]);
    call_method(vm, &this, "on", &[Value::str("data"), ondata])?;
    let onend = closure(vm, "", 0, riter_on_end, vec![st.clone()]);
    call_method(vm, &this, "on", &[Value::str("end"), onend])?;
    let onerr = closure(vm, "", 1, riter_on_error, vec![st.clone()]);
    call_method(vm, &this, "on", &[Value::str("error"), onerr])?;
    let it = vm.new_object();
    let next = vm.native_closure("next", 0, riter_next, vec![st.clone(), this.clone()]);
    it.set_prop(key("next"), Value::Obj(next), WEC);
    let ret = vm.native_closure("return", 0, riter_return, vec![st, this]);
    it.set_prop(key("return"), Value::Obj(ret), WEC);
    let ai = vm.native_fn("[Symbol.asyncIterator]", 0, return_this);
    it.set_prop(PropKey::Sym(vm.intr.sym_async_iterator.clone()), Value::Obj(ai), WEC);
    Ok(Value::Obj(it))
}

// ============================================================================================
// Writable
// ============================================================================================

fn writable_default_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.arg(2), Value::Undefined, &[])
}

fn then_on(vm: &mut Vm, p: &Value, f: Value) -> JsResult<Value> {
    match p {
        Value::Obj(po) if crate::builtins::promise::is_promise(p) => crate::builtins::promise::promise_then(vm, po, f, Value::Undefined),
        _ => call_method(vm, p, "then", &[f]),
    }
}

/// queueWrite(stream, entry): chain the `_write` call onto `state.tail`.
fn queue_write(vm: &mut Vm, this: &Value, entry: &Value) -> JsResult<()> {
    let st = wstate(vm, this)?;
    let tail = getp(vm, &st, "tail")?;
    let h = closure(vm, "", 0, write_job, vec![this.clone(), entry.clone()]);
    let nt = then_on(vm, &tail, h)?;
    setp(vm, &st, "tail", nt)
}

fn write_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, entry) = (a.slot(0), a.slot(1));
    let cap = vm.new_promise_capability_intrinsic();
    let done = closure(vm, "", 1, write_done, vec![this.clone(), entry.clone(), cap.resolve.clone()]);
    let chunk = getp(vm, &entry, "chunk")?;
    let enc = getp(vm, &entry, "encoding")?;
    if let Err(e) = call_method(vm, &this, "_write", &[chunk, enc, done]) {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

fn write_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    complete_write(vm, &a.slot(0), &a.slot(1), &a.arg(0))?;
    vm.call(&a.slot(2), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

/// completeWrite(stream, entry, err)
fn complete_write(vm: &mut Vm, this: &Value, entry: &Value, err: &Value) -> JsResult<()> {
    let st = wstate(vm, this)?;
    let l = getp(vm, entry, "length")?;
    let l = to_num(vm, &l)?;
    let cur = snum(vm, &st, "length")?;
    setp(vm, &st, "length", Value::Num(cur - l))?;
    if err.truthy() {
        emit(vm, this, "error", &[err.clone()])?;
    }
    let cb = getp(vm, entry, "cb")?;
    if cb.truthy() {
        vm.call(&cb, Value::Undefined, &[err.clone()])?;
    }
    if getp(vm, &st, "needDrain")?.truthy() {
        let len = snum(vm, &st, "length")?;
        let hwm = snum(vm, &st, "highWaterMark")?;
        if len < hwm {
            setp(vm, &st, "needDrain", Value::Bool(false))?;
            let f = closure(vm, "", 0, emit_drain_job, vec![this.clone()]);
            queue_microtask(vm, f);
        }
    }
    Ok(())
}

fn emit_drain_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "drain", &[])?;
    Ok(Value::Undefined)
}

fn write_after_end_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(0), Value::Undefined, &[a.slot(1)])
}

fn writable_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let chunk = a.arg(0);
    let (mut enc, mut cb) = (a.arg(1), a.arg(2));
    if enc.is_callable() {
        cb = enc;
        enc = Value::Null;
    }
    let st = wstate(vm, &this)?;
    if getp(vm, &st, "ended")?.truthy() {
        let err = vm.make_error("Error", "write after end");
        if cb.truthy() {
            let f = closure(vm, "", 0, write_after_end_cb, vec![cb, err]);
            queue_microtask(vm, f);
        } else {
            emit(vm, &this, "error", &[err])?;
        }
        return Ok(Value::Bool(false));
    }
    let length = if getp(vm, &st, "objectMode")?.truthy() {
        1.0
    } else {
        let l = if chunk.truthy() { getp(vm, &chunk, "length")? } else { Value::Undefined };
        if !l.is_undefined() {
            to_num(vm, &l)?
        } else {
            let s = string_of(vm, &chunk)?;
            let e = if enc.truthy() { enc.clone() } else { Value::str("utf8") };
            let n = buffer_call(vm, "byteLength", &[Value::str(&s), e])?;
            to_num(vm, &n)?
        }
    };
    let cur = snum(vm, &st, "length")?;
    setp(vm, &st, "length", Value::Num(cur + length))?;
    let entry = Value::Obj(vm.obj_from(vec![("chunk", chunk), ("encoding", enc), ("cb", cb), ("length", Value::Num(length))]));
    if getp(vm, &st, "corked")?.truthy() {
        let cbuf = getp(vm, &st, "corkBuffer")?;
        arr_push(vm, &cbuf, entry)?;
    } else {
        queue_write(vm, &this, &entry)?;
    }
    let len = snum(vm, &st, "length")?;
    let hwm = snum(vm, &st, "highWaterMark")?;
    if len >= hwm {
        setp(vm, &st, "needDrain", Value::Bool(true))?;
    }
    Ok(Value::Bool(!getp(vm, &st, "needDrain")?.truthy()))
}

fn writable_queue_batch(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let entries = a.arg(0);
    let list = crate::builtins::array::array_like_to_vec(vm, &entries)?;
    let writev = getp(vm, &this, "_writev")?;
    if list.len() > 1 && writev.is_callable() {
        let st = wstate(vm, &this)?;
        let tail = getp(vm, &st, "tail")?;
        let h = closure(vm, "", 0, writev_job, vec![this.clone(), entries.clone()]);
        let nt = then_on(vm, &tail, h)?;
        setp(vm, &st, "tail", nt)?;
    } else {
        for e in list {
            queue_write(vm, &this, &e)?;
        }
    }
    Ok(Value::Undefined)
}

fn writev_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, entries) = (a.slot(0), a.slot(1));
    let cap = vm.new_promise_capability_intrinsic();
    let list = crate::builtins::array::array_like_to_vec(vm, &entries)?;
    let mut chunks = Vec::new();
    for e in &list {
        let c = getp(vm, e, "chunk")?;
        let en = getp(vm, e, "encoding")?;
        chunks.push(Value::Obj(vm.obj_from(vec![("chunk", c), ("encoding", en)])));
    }
    let arr = Value::Obj(vm.new_array(chunks));
    let done = closure(vm, "", 1, writev_done, vec![this.clone(), entries, cap.resolve.clone()]);
    if let Err(e) = call_method(vm, &this, "_writev", &[arr, done]) {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

fn writev_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let list = crate::builtins::array::array_like_to_vec(vm, &a.slot(1))?;
    for e in list {
        complete_write(vm, &this, &e, &a.arg(0))?;
    }
    vm.call(&a.slot(2), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn writable_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (mut chunk, mut enc, mut cb) = (a.arg(0), a.arg(1), a.arg(2));
    if chunk.is_callable() {
        cb = chunk;
        chunk = Value::Null;
    } else if enc.is_callable() {
        cb = enc;
        enc = Value::Null;
    }
    let st = wstate(vm, &this)?;
    if !chunk.is_nullish() {
        call_method(vm, &this, "write", &[chunk, enc])?;
    }
    setp(vm, &st, "ended", Value::Bool(true))?;
    if getp(vm, &st, "corked")?.truthy() {
        setp(vm, &st, "corked", Value::Num(0.0))?;
        let cbuf = getp(vm, &st, "corkBuffer")?;
        let entries = call_method(vm, &cbuf, "splice", &[Value::Num(0.0)])?;
        call_method(vm, &this, "_queueBatch", &[entries])?;
    }
    let tail = getp(vm, &st, "tail")?;
    let h = closure(vm, "", 0, end_job, vec![this.clone(), cb, st]);
    then_on(vm, &tail, h)?;
    Ok(this)
}

fn end_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb, st) = (a.slot(0), a.slot(1), a.slot(2));
    if getp(vm, &st, "finished")?.truthy() {
        return Ok(Value::Undefined);
    }
    let fin = getp(vm, &this, "_final")?;
    if fin.truthy() {
        let f = closure(vm, "", 1, final_done, vec![this.clone(), cb, st]);
        call_method(vm, &this, "_final", &[f])?;
    } else {
        end_finish(vm, &this, &cb, &st)?;
    }
    Ok(Value::Undefined)
}

fn end_finish(vm: &mut Vm, this: &Value, cb: &Value, st: &Value) -> JsResult<()> {
    setp(vm, st, "finished", Value::Bool(true))?;
    if cb.truthy() {
        vm.call(cb, Value::Undefined, &[])?;
    }
    emit(vm, this, "finish", &[])?;
    Ok(())
}

fn final_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb, st) = (a.slot(0), a.slot(1), a.slot(2));
    let err = a.arg(0);
    if err.truthy() {
        emit(vm, &this, "error", &[err])?;
    } else {
        end_finish(vm, &this, &cb, &st)?;
    }
    Ok(Value::Undefined)
}

fn writable_cork(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = wstate(vm, &a.this)?;
    let c = getp(vm, &st, "corked")?;
    let n = vm.op_add(&c, &Value::Num(1.0))?;
    setp(vm, &st, "corked", n)?;
    Ok(Value::Undefined)
}

fn writable_uncork(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = wstate(vm, &a.this)?;
    if getp(vm, &st, "corked")?.truthy() {
        let c = snum(vm, &st, "corked")?;
        setp(vm, &st, "corked", Value::Num(c - 1.0))?;
    }
    let corked = getp(vm, &st, "corked")?.truthy();
    let cbuf = getp(vm, &st, "corkBuffer")?;
    if !corked && arr_len(vm, &cbuf)? > 0.0 {
        let entries = call_method(vm, &cbuf, "splice", &[Value::Num(0.0)])?;
        call_method(vm, &a.this, "_queueBatch", &[entries])?;
    }
    Ok(Value::Undefined)
}

fn writable_destroy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let st = wstate(vm, &this)?;
    if getp(vm, &st, "destroyed")?.truthy() {
        return Ok(this);
    }
    setp(vm, &st, "destroyed", Value::Bool(true))?;
    let err = a.arg(0);
    if err.truthy() {
        setp(vm, &st, "errored", err.clone())?;
        let rs = getp(vm, &this, "_readableState")?;
        if rs.truthy() {
            setp(vm, &rs, "errored", err.clone())?;
        }
    }
    setp(vm, &this, "writable", Value::Bool(false))?;
    let job = closure(vm, "", 0, destroy_job, vec![this.clone(), err]);
    queue_microtask(vm, job);
    Ok(this)
}

fn writable_length(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = wstate(vm, &a.this)?;
    getp(vm, &st, "length")
}

fn writable_hwm(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = wstate(vm, &a.this)?;
    getp(vm, &st, "highWaterMark")
}

fn writable_object_mode(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = wstate(vm, &a.this)?;
    getp(vm, &st, "objectMode")
}

// ============================================================================================
// Transform / PassThrough
// ============================================================================================

fn transform_default_transform(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.arg(2), Value::Undefined, &[Value::Null, a.arg(0)])
}

fn transform_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let done = closure(vm, "", 2, transform_write_done, vec![this.clone(), a.arg(2)]);
    call_method(vm, &this, "_transform", &[a.arg(0), a.arg(1), done])?;
    Ok(Value::Undefined)
}

fn transform_write_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb) = (a.slot(0), a.slot(1));
    let (err, data) = (a.arg(0), a.arg(1));
    if err.truthy() {
        return vm.call(&cb, Value::Undefined, &[err]);
    }
    if !data.is_nullish() {
        call_method(vm, &this, "push", &[data])?;
    }
    vm.call(&cb, Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn transform_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    if getp(vm, &this, "_flush")?.truthy() {
        let done = closure(vm, "", 2, transform_flush_done, vec![this.clone(), cb]);
        call_method(vm, &this, "_flush", &[done])?;
    } else {
        call_method(vm, &this, "push", &[Value::Null])?;
        vm.call(&cb, Value::Undefined, &[])?;
    }
    Ok(Value::Undefined)
}

fn transform_flush_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb) = (a.slot(0), a.slot(1));
    let (err, data) = (a.arg(0), a.arg(1));
    if !data.is_nullish() {
        call_method(vm, &this, "push", &[data])?;
    }
    call_method(vm, &this, "push", &[Value::Null])?;
    vm.call(&cb, Value::Undefined, &[err])?;
    Ok(Value::Undefined)
}

// ============================================================================================
// for await (const chunk of iterable) — a native driver with the spec's promise timing
// ============================================================================================

#[derive(Clone, Copy, PartialEq)]
enum DriveKind {
    /// Readable.from: push each chunk, push(null) at the end, destroy(err) on failure
    Push,
    /// stream/consumers collect(): Buffer.from(chunk) each chunk, resolve Buffer.concat
    Collect,
}

struct Drive {
    kind: DriveKind,
    iter: RefCell<Value>,
    next: RefCell<Value>,
    sync: Cell<bool>,
    target: Value,
    chunks: RefCell<Vec<Value>>,
    cap: RefCell<Option<Capability>>,
}

fn drv<R>(d: &Value, f: impl FnOnce(&Drive) -> R) -> Option<R> {
    with_host::<Drive, R>(d, f)
}

fn obj_or_prim_get_method(vm: &mut Vm, v: &Value, k: &PropKey) -> JsResult<Value> {
    match v {
        Value::Undefined => vm.throw_type("cannot read property '\u{0}2' of undefined"),
        Value::Null => vm.throw_type("cannot read property '\u{0}2' of null"),
        _ => vm.get_prop_of(v, k),
    }
}

/// GetIterator(obj, async) → (iterator, next, is_sync)
fn get_async_iterator(vm: &mut Vm, v: &Value) -> JsResult<(Value, Value, bool)> {
    let ak = PropKey::Sym(vm.intr.sym_async_iterator.clone());
    let m = obj_or_prim_get_method(vm, v, &ak)?;
    if !m.is_nullish() {
        if !m.is_callable() {
            return vm.throw_type("@@asyncIterator is not callable");
        }
        let it = vm.call(&m, v.clone(), &[])?;
        if !it.is_object() {
            return vm.throw_type("@@asyncIterator did not return an object");
        }
        let next = getp(vm, &it, "next")?;
        return Ok((it, next, false));
    }
    let sk = PropKey::Sym(vm.intr.sym_iterator.clone());
    let sm = vm.get_prop_of(v, &sk)?;
    if !sm.is_callable() {
        return vm.throw_type("value is not iterable");
    }
    let it = vm.call(&sm, v.clone(), &[])?;
    if !it.is_object() {
        return vm.throw_type("@@iterator returned a non-object");
    }
    let next = getp(vm, &it, "next")?;
    Ok((it, next, true))
}

fn start_drive(vm: &mut Vm, iterable: &Value, kind: DriveKind, target: Value, cap: Option<Capability>) {
    let d = host_obj(Drive {
        kind,
        iter: RefCell::new(Value::Undefined),
        next: RefCell::new(Value::Undefined),
        sync: Cell::new(false),
        target,
        chunks: RefCell::new(Vec::new()),
        cap: RefCell::new(cap),
    });
    match get_async_iterator(vm, iterable) {
        Ok((it, next, sync)) => {
            drv(&d, |s| {
                *s.iter.borrow_mut() = it;
                *s.next.borrow_mut() = next;
                s.sync.set(sync);
            });
            drive_step(vm, &d);
        }
        Err(e) => drive_fail(vm, &d, e),
    }
}

/// Await(v) with continuations `ok` / `err` (data = the driver).
fn await_value(vm: &mut Vm, v: Value, ok: fn(&mut Vm, Value, &Value) -> JsResult<Value>, err: fn(&mut Vm, Value, &Value) -> JsResult<Value>, data: &Value) {
    match promise_resolve_intrinsic(vm, v) {
        Ok(p) => perform_then_internal(vm, &p, Handler::Native(ok, data.clone()), Handler::Native(err, data.clone()), None),
        Err(e) => {
            let _ = err(vm, e, data);
        }
    }
}

/// %AsyncFromSyncIteratorPrototype%.next continuation: a promise for the iterator result.
fn async_from_sync_result(vm: &mut Vm, result: JsResult<Value>, close_on_rejection: bool, sync_iter: &Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let r: JsResult<()> = (|| {
        let result = result?;
        if !result.is_object() {
            return vm.throw_type("iterator result is not an object");
        }
        let done = getp(vm, &result, "done")?.truthy();
        let value = getp(vm, &result, "value")?;
        let vw = match promise_resolve_intrinsic(vm, value) {
            Ok(p) => p,
            Err(e) => {
                if !done && close_on_rejection {
                    if let Ok(ret) = getp(vm, sync_iter, "return") {
                        if ret.is_callable() {
                            let _ = vm.call(&ret, sync_iter.clone(), &[]);
                        }
                    }
                }
                return Err(e);
            }
        };
        perform_then_internal(vm, &vw, Handler::Native(unwrap_iter_value, Value::Bool(done)), Handler::Thrower, Some(cap.clone()));
        Ok(())
    })();
    if let Err(e) = r {
        let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
    }
    cap.promise
}

fn unwrap_iter_value(vm: &mut Vm, v: Value, done: &Value) -> JsResult<Value> {
    Ok(iter_result(vm, v, done.truthy()))
}

fn drive_step(vm: &mut Vm, d: &Value) {
    let (it, next, sync) = match drv(d, |s| (s.iter.borrow().clone(), s.next.borrow().clone(), s.sync.get())) {
        Some(x) => x,
        None => return,
    };
    if sync {
        let r = vm.call(&next, it.clone(), &[]);
        let p = async_from_sync_result(vm, r, true, &it);
        await_value(vm, p, drive_on_result, drive_on_reject, d);
    } else {
        match vm.call(&next, it, &[]) {
            Ok(res) => await_value(vm, res, drive_on_result, drive_on_reject, d),
            Err(e) => drive_fail(vm, d, e),
        }
    }
}

fn drive_on_result(vm: &mut Vm, result: Value, d: &Value) -> JsResult<Value> {
    let r: JsResult<Option<Value>> = (|| {
        if !result.is_object() {
            return vm.throw_type("iterator result is not an object");
        }
        if getp(vm, &result, "done")?.truthy() {
            return Ok(None);
        }
        Ok(Some(getp(vm, &result, "value")?))
    })();
    match r {
        Err(e) => drive_fail(vm, d, e),
        Ok(None) => drive_done(vm, d),
        Ok(Some(v)) => match drive_body(vm, d, v) {
            Ok(()) => drive_step(vm, d),
            Err(e) => drive_close(vm, d, e),
        },
    }
    Ok(Value::Undefined)
}

fn drive_on_reject(vm: &mut Vm, e: Value, d: &Value) -> JsResult<Value> {
    drive_fail(vm, d, e);
    Ok(Value::Undefined)
}

fn drive_body(vm: &mut Vm, d: &Value, chunk: Value) -> JsResult<()> {
    let (kind, target) = drv(d, |s| (s.kind, s.target.clone())).unwrap();
    match kind {
        DriveKind::Push => {
            call_method(vm, &target, "push", &[chunk])?;
        }
        DriveKind::Collect => {
            let b = buffer_call(vm, "from", &[chunk])?;
            drv(d, |s| s.chunks.borrow_mut().push(b));
        }
    }
    Ok(())
}

/// The loop completed normally.
fn drive_done(vm: &mut Vm, d: &Value) {
    let (kind, target) = drv(d, |s| (s.kind, s.target.clone())).unwrap();
    match kind {
        DriveKind::Push => {
            if let Err(e) = call_method(vm, &target, "push", &[Value::Null]) {
                drive_fail(vm, d, e);
            }
        }
        DriveKind::Collect => {
            let chunks = drv(d, |s| s.chunks.borrow().clone()).unwrap_or_default();
            let arr = Value::Obj(vm.new_array(chunks));
            let r = buffer_call(vm, "concat", &[arr]);
            let cap = drv(d, |s| s.cap.borrow().clone()).flatten();
            if let Some(cap) = cap {
                let _ = match r {
                    Ok(b) => vm.call(&cap.resolve, Value::Undefined, &[b]),
                    Err(e) => vm.call(&cap.reject, Value::Undefined, &[e]),
                };
            }
        }
    }
}

/// The loop threw (the catch clause / the async function's rejection).
fn drive_fail(vm: &mut Vm, d: &Value, e: Value) {
    let (kind, target) = drv(d, |s| (s.kind, s.target.clone())).unwrap();
    match kind {
        DriveKind::Push => {
            if let Err(e2) = call_method(vm, &target, "destroy", &[e]) {
                // the IIFE's promise rejects unobserved
                rejected(vm, e2);
            }
        }
        DriveKind::Collect => {
            let cap = drv(d, |s| s.cap.borrow().clone()).flatten();
            if let Some(cap) = cap {
                let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
            }
        }
    }
}

struct CloseErr {
    d: Value,
    err: Value,
}

fn close_resume(vm: &mut Vm, _v: Value, data: &Value) -> JsResult<Value> {
    if let Some((d, err)) = with_host::<CloseErr, _>(data, |c| (c.d.clone(), c.err.clone())) {
        drive_fail(vm, &d, err);
    }
    Ok(Value::Undefined)
}

/// AsyncIteratorClose(iteratorRecord, throw completion) then the catch clause.
fn drive_close(vm: &mut Vm, d: &Value, err: Value) {
    let (it, sync) = drv(d, |s| (s.iter.borrow().clone(), s.sync.get())).unwrap();
    let data = host_obj(CloseErr { d: d.clone(), err: err.clone() });
    if sync {
        // %AsyncFromSyncIteratorPrototype%.return
        let ret = match getp(vm, &it, "return") {
            Ok(r) => r,
            Err(e) => {
                let p = rejected(vm, e);
                await_value(vm, p, close_resume, close_resume, &data);
                return;
            }
        };
        let p = if ret.is_nullish() {
            let r = iter_result(vm, Value::Undefined, true);
            resolved(vm, r)
        } else {
            let r = vm.call(&ret, it.clone(), &[]);
            async_from_sync_result(vm, r, false, &it)
        };
        await_value(vm, p, close_resume, close_resume, &data);
    } else {
        let ret = match getp(vm, &it, "return") {
            Ok(r) => r,
            Err(_) => return drive_fail(vm, d, err),
        };
        if ret.is_nullish() {
            return drive_fail(vm, d, err);
        }
        match vm.call(&ret, it, &[]) {
            Ok(v) => await_value(vm, v, close_resume, close_resume, &data),
            Err(_) => drive_fail(vm, d, err),
        }
    }
}

// --- Readable.from ---

fn readable_from(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let args: Vec<Value> = if a.args.len() > 1 { vec![a.arg(1)] } else { Vec::new() };
    let r = vm.construct(&Value::Obj(c.readable), &args, None)?;
    start_drive(vm, &a.arg(0), DriveKind::Push, r.clone(), None);
    Ok(r)
}

/// `Readable.from(x)` from Rust.
pub fn readable_from_value(vm: &mut Vm, iterable: &Value) -> JsResult<Value> {
    let c = classes(vm);
    let r = vm.construct(&Value::Obj(c.readable), &[], None)?;
    start_drive(vm, iterable, DriveKind::Push, r.clone(), None);
    Ok(r)
}

// ============================================================================================
// module functions
// ============================================================================================

fn state_flag(vm: &mut Vm, st: &Value, k: &str) -> JsResult<bool> {
    if !st.truthy() {
        return Ok(false);
    }
    Ok(getp(vm, st, k)?.truthy())
}

/// isNodeStream(x)
fn is_node_stream(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    if !v.truthy() || !v.is_object() {
        return Ok(false);
    }
    if !getp(vm, v, "on")?.is_callable() {
        return Ok(false);
    }
    Ok(getp(vm, v, "_readableState")?.truthy() || getp(vm, v, "_writableState")?.truthy())
}

fn is_destroyed_impl(vm: &mut Vm, s: &Value) -> JsResult<bool> {
    let r = if s.truthy() { getp(vm, s, "_readableState")? } else { s.clone() };
    let w = if s.truthy() { getp(vm, s, "_writableState")? } else { s.clone() };
    Ok(state_flag(vm, &r, "destroyed")? || state_flag(vm, &w, "destroyed")?)
}

fn is_destroyed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(is_destroyed_impl(vm, &a.arg(0))?))
}

fn is_errored(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.arg(0);
    let r = if s.truthy() { getp(vm, &s, "_readableState")? } else { s.clone() };
    let w = if s.truthy() { getp(vm, &s, "_writableState")? } else { s.clone() };
    if state_flag(vm, &r, "errored")? || state_flag(vm, &w, "errored")? {
        return Ok(Value::Bool(true));
    }
    Ok(Value::Bool(s.truthy() && getp(vm, &s, "errored")?.truthy()))
}

fn is_readable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.arg(0);
    let r = if s.truthy() { getp(vm, &s, "_readableState")? } else { s.clone() };
    if !r.truthy() {
        return Ok(Value::Bool(s.truthy() && matches!(getp(vm, &s, "readable")?, Value::Bool(true))));
    }
    let ok = !getp(vm, &r, "ended")?.truthy()
        && !getp(vm, &r, "endEmitted")?.truthy()
        && !getp(vm, &r, "destroyed")?.truthy()
        && !matches!(getp(vm, &s, "readable")?, Value::Bool(false));
    Ok(Value::Bool(ok))
}

fn is_writable(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.arg(0);
    let w = if s.truthy() { getp(vm, &s, "_writableState")? } else { s.clone() };
    if !w.truthy() {
        return Ok(Value::Bool(s.truthy() && matches!(getp(vm, &s, "writable")?, Value::Bool(true))));
    }
    let ok = !getp(vm, &w, "ended")?.truthy()
        && !getp(vm, &w, "finished")?.truthy()
        && !getp(vm, &w, "destroyed")?.truthy()
        && !matches!(getp(vm, &s, "writable")?, Value::Bool(false));
    Ok(Value::Bool(ok))
}

fn is_disturbed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.arg(0);
    let r = if s.truthy() { getp(vm, &s, "_readableState")? } else { s.clone() };
    if !r.truthy() {
        return Ok(Value::Bool(false));
    }
    let d = !getp(vm, &r, "flowing")?.is_null() || getp(vm, &r, "endEmitted")?.truthy() || getp(vm, &r, "ended")?.truthy();
    Ok(Value::Bool(d))
}

fn get_default_hwm(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Num(default_hwm(a.arg(0).truthy())))
}

fn set_default_hwm(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // the reference stores the raw value; only numbers are meaningful here
    let v = to_num(vm, &a.arg(1)).unwrap_or(f64::NAN);
    HWM.with(|h| {
        let (b, o) = h.get();
        h.set(if a.arg(0).truthy() { (b, v) } else { (v, o) });
    });
    Ok(Value::Undefined)
}

fn is_array_buffer_view(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(&a.arg(0), Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)))))
}

fn is_uint8_array_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
    Ok(Value::Bool(vm.instance_of(&a.arg(0), &u8c)?))
}

fn uint8_array_to_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = a.arg(0);
    let b = getp(vm, &c, "buffer")?;
    let off = getp(vm, &c, "byteOffset")?;
    let len = getp(vm, &c, "byteLength")?;
    buffer_call(vm, "from", &[b, off, len])
}

fn destroy_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.arg(0);
    if s.truthy() && getp(vm, &s, "destroy")?.is_callable() {
        call_method(vm, &s, "destroy", &[a.arg(1)])?;
    }
    Ok(s)
}

// --- finished ---

struct Fin {
    stream: Value,
    cb: Value,
    readable_done: Cell<bool>,
    writable_done: Cell<bool>,
    called: Cell<bool>,
    listeners: RefCell<Vec<Value>>,
}

fn fin<R>(v: &Value, f: impl FnOnce(&Fin) -> R) -> Option<R> {
    with_host::<Fin, R>(v, f)
}

pub fn premature_close(vm: &mut Vm) -> Value {
    error_with_code(vm, "Error", "Premature close", "ERR_STREAM_PREMATURE_CLOSE")
}

fn fin_cleanup(vm: &mut Vm, st: &Value) -> JsResult<()> {
    let (stream, ls) = fin(st, |f| (f.stream.clone(), f.listeners.borrow().clone())).unwrap();
    if !getp(vm, &stream, "removeListener")?.truthy() {
        return Ok(());
    }
    let names = ["end", "finish", "close", "error"];
    for (i, n) in names.iter().enumerate() {
        if let Some(l) = ls.get(i) {
            call_method(vm, &stream, "removeListener", &[Value::str(n), l.clone()])?;
        }
    }
    Ok(())
}

fn fin_cleanup_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    fin_cleanup(vm, &a.slot(0))?;
    Ok(Value::Undefined)
}

fn fin_cb_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(0), Value::Undefined, &[a.slot(1)])
}

fn fin_settle(vm: &mut Vm, st: &Value, err: Value) -> JsResult<()> {
    if fin(st, |f| f.called.get()).unwrap_or(true) {
        return Ok(());
    }
    fin(st, |f| f.called.set(true));
    fin_cleanup(vm, st)?;
    let cb = fin(st, |f| f.cb.clone()).unwrap();
    let e = if err.truthy() { err } else { Value::Null };
    let job = closure(vm, "", 0, fin_cb_job, vec![cb, e]);
    queue_microtask(vm, job);
    Ok(())
}

fn fin_check(vm: &mut Vm, st: &Value) -> JsResult<()> {
    if fin(st, |f| f.readable_done.get() && f.writable_done.get()).unwrap_or(false) {
        fin_settle(vm, st, Value::Undefined)?;
    }
    Ok(())
}

fn fin_onend(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    fin(&st, |f| f.readable_done.set(true));
    fin_check(vm, &st)?;
    Ok(Value::Undefined)
}

fn fin_onfinish(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    fin(&st, |f| f.writable_done.set(true));
    fin_check(vm, &st)?;
    Ok(Value::Undefined)
}

fn fin_onerror(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    let err = a.arg(0);
    let e = if err.truthy() { err } else { premature_close(vm) };
    fin_settle(vm, &st, e)?;
    Ok(Value::Undefined)
}

fn fin_onclose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    if fin(&st, |f| f.readable_done.get() && f.writable_done.get()).unwrap_or(false) {
        fin_settle(vm, &st, Value::Undefined)?;
    } else {
        let e = premature_close(vm);
        fin_settle(vm, &st, e)?;
    }
    Ok(Value::Undefined)
}

/// finished(stream, opts, cb) → cleanup function
pub fn finished_impl(vm: &mut Vm, stream: &Value, opts: Value, cb: Value) -> JsResult<Value> {
    let (mut opts, mut cb) = (opts, cb);
    if opts.is_callable() {
        cb = opts;
        opts = Value::Obj(vm.new_object());
    }
    if !opts.truthy() {
        opts = Value::Obj(vm.new_object());
    }
    let rs = getp(vm, stream, "_readableState")?;
    let ws = getp(vm, stream, "_writableState")?;
    let want_r = !matches!(getp(vm, &opts, "readable")?, Value::Bool(false)) && rs.truthy();
    let want_w = !matches!(getp(vm, &opts, "writable")?, Value::Bool(false)) && ws.truthy();
    let rdone = !want_r || getp(vm, &rs, "endEmitted")?.truthy();
    let wdone = !want_w || getp(vm, &ws, "finished")?.truthy();
    let st = host_obj(Fin {
        stream: stream.clone(),
        cb,
        readable_done: Cell::new(rdone),
        writable_done: Cell::new(wdone),
        called: Cell::new(false),
        listeners: RefCell::new(Vec::new()),
    });
    let onend = closure(vm, "onend", 0, fin_onend, vec![st.clone()]);
    let onfinish = closure(vm, "onfinish", 0, fin_onfinish, vec![st.clone()]);
    let onclose = closure(vm, "onclose", 0, fin_onclose, vec![st.clone()]);
    let onerror = closure(vm, "onerror", 1, fin_onerror, vec![st.clone()]);
    fin(&st, |f| *f.listeners.borrow_mut() = vec![onend.clone(), onfinish.clone(), onclose.clone(), onerror.clone()]);
    let cleanup = closure(vm, "cleanup", 0, fin_cleanup_fn, vec![st.clone()]);
    call_method(vm, stream, "on", &[Value::str("end"), onend])?;
    call_method(vm, stream, "on", &[Value::str("finish"), onfinish])?;
    call_method(vm, stream, "on", &[Value::str("close"), onclose])?;
    call_method(vm, stream, "on", &[Value::str("error"), onerror])?;
    let re = if rs.truthy() { getp(vm, &rs, "errored")? } else { Value::Undefined };
    let we = if ws.truthy() { getp(vm, &ws, "errored")? } else { Value::Undefined };
    if re.truthy() || we.truthy() {
        let e = if re.truthy() { re } else { we };
        fin_settle(vm, &st, e)?;
    } else {
        fin_check(vm, &st)?;
    }
    Ok(cleanup)
}

fn finished_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    finished_impl(vm, &a.arg(0), a.arg(1), a.arg(2))
}

// --- pipeline ---

struct Pipe {
    nodes: RefCell<Vec<Value>>,
    done: Cell<bool>,
    cb: Value,
}

fn pipe_st<R>(v: &Value, f: impl FnOnce(&Pipe) -> R) -> Option<R> {
    with_host::<Pipe, R>(v, f)
}

fn pipeline_finish(vm: &mut Vm, st: &Value, err: Value) -> JsResult<()> {
    if pipe_st(st, |p| p.done.get()).unwrap_or(true) {
        return Ok(());
    }
    pipe_st(st, |p| p.done.set(true));
    if err.truthy() {
        let nodes = pipe_st(st, |p| p.nodes.borrow().clone()).unwrap_or_default();
        for n in nodes {
            if is_node_stream(vm, &n)? && !is_destroyed_impl(vm, &n)? {
                call_method(vm, &n, "destroy", &[err.clone()])?;
            }
        }
    }
    let cb = pipe_st(st, |p| p.cb.clone()).unwrap();
    let e = if err.truthy() { err } else { Value::Null };
    let job = closure(vm, "", 0, fin_cb_job, vec![cb, e]);
    queue_microtask(vm, job);
    Ok(())
}

fn pipeline_on_err(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    pipeline_finish(vm, &a.slot(0), a.arg(0))?;
    Ok(Value::Undefined)
}

fn pipeline_on_ok(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    pipeline_finish(vm, &a.slot(0), Value::Null)?;
    Ok(Value::Undefined)
}

pub fn pipeline_impl(vm: &mut Vm, args: &[Value]) -> JsResult<Value> {
    let mut args = args.to_vec();
    let cb = match args.last() {
        Some(f) if f.is_callable() => args.pop().unwrap(),
        _ => Value::Obj(vm.native_fn("", 0, noop)),
    };
    let arr = Value::Obj(vm.new_array(args));
    let flat = call_method(vm, &arr, "flat", &[])?;
    let parts = crate::builtins::array::array_like_to_vec(vm, &flat)?;
    if parts.len() < 2 {
        return vm.throw_error("Error", "pipeline requires at least 2 streams");
    }
    let st = host_obj(Pipe { nodes: RefCell::new(Vec::new()), done: Cell::new(false), cb });
    let mut current = parts[0].clone();
    if !is_node_stream(vm, &current)? {
        current = readable_from_value(vm, &current)?;
    }
    pipe_st(&st, |p| p.nodes.borrow_mut().push(current.clone()));
    let mut cur: Option<Value> = Some(current);
    for i in 1..parts.len() {
        let part = parts[i].clone();
        let is_last = i == parts.len() - 1;
        let c = cur.clone().unwrap();
        if part.is_callable() {
            let result = match vm.call(&part, Value::Undefined, &[c.clone()]) {
                Ok(r) => r,
                Err(e) => {
                    pipeline_finish(vm, &st, e)?;
                    return Ok(c);
                }
            };
            let has_ai = if result.truthy() {
                let ak = PropKey::Sym(vm.intr.sym_async_iterator.clone());
                vm.get_prop_of(&result, &ak)?.is_callable()
            } else {
                false
            };
            if is_last && !has_ai {
                let p = promise_resolve_intrinsic(vm, result)?;
                let ok = closure(vm, "", 0, pipeline_on_ok, vec![st.clone()]);
                let er = closure(vm, "", 1, pipeline_on_err, vec![st.clone()]);
                crate::builtins::promise::promise_then(vm, &p, ok, er)?;
                cur = None;
                break;
            }
            let r = readable_from_value(vm, &result)?;
            pipe_st(&st, |p| p.nodes.borrow_mut().push(r.clone()));
            cur = Some(r);
        } else {
            call_method(vm, &c, "pipe", &[part.clone()])?;
            pipe_st(&st, |p| p.nodes.borrow_mut().push(part.clone()));
            cur = Some(part);
        }
    }
    let nodes = pipe_st(&st, |p| p.nodes.borrow().clone()).unwrap_or_default();
    for n in &nodes {
        if is_node_stream(vm, n)? {
            let h = closure(vm, "", 1, pipeline_on_err, vec![st.clone()]);
            call_method(vm, n, "on", &[Value::str("error"), h])?;
        }
    }
    match cur {
        Some(c) => {
            let h = closure(vm, "", 1, pipeline_on_err, vec![st.clone()]);
            finished_impl(vm, &c, h, Value::Undefined)?;
            Ok(c)
        }
        None => Ok(nodes.last().cloned().unwrap_or(Value::Undefined)),
    }
}

fn pipeline_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    pipeline_impl(vm, a.args)
}

// --- promises ---

fn settle_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let err = a.arg(0);
    if err.truthy() {
        vm.call(&a.slot(1), Value::Undefined, &[err])?;
    } else {
        vm.call(&a.slot(0), Value::Undefined, &[])?;
    }
    Ok(Value::Undefined)
}

fn promises_finished(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let cb = closure(vm, "", 1, settle_cb, vec![cap.resolve.clone(), cap.reject.clone()]);
    let opts = if a.arg(1).truthy() { a.arg(1) } else { Value::Obj(vm.new_object()) };
    if let Err(e) = finished_impl(vm, &a.arg(0), opts, cb) {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

fn promises_pipeline(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let cb = closure(vm, "", 1, settle_cb, vec![cap.resolve.clone(), cap.reject.clone()]);
    let mut args = a.args.to_vec();
    args.push(cb);
    if let Err(e) = pipeline_impl(vm, &args) {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

// --- addAbortSignal / compose / duplexPair ---

fn abort_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (signal, stream) = (a.slot(0), a.slot(1));
    let mut err = getp(vm, &signal, "reason")?;
    if !err.truthy() {
        err = vm.make_error("Error", "The operation was aborted");
        setp(vm, &err, "code", Value::str("ABORT_ERR"))?;
        setp(vm, &err, "name", Value::str("AbortError"))?;
    }
    if getp(vm, &stream, "destroy")?.is_callable() {
        call_method(vm, &stream, "destroy", &[err])?;
    }
    Ok(Value::Undefined)
}

fn add_abort_signal(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (signal, stream) = (a.arg(0), a.arg(1));
    if !signal.truthy() || !getp(vm, &signal, "addEventListener")?.is_callable() {
        return Ok(stream);
    }
    let abort = closure(vm, "abort", 0, abort_job, vec![signal.clone(), stream.clone()]);
    if getp(vm, &signal, "aborted")?.truthy() {
        queue_microtask(vm, abort);
    } else {
        let o = Value::Obj(vm.obj_from(vec![("once", Value::Bool(true))]));
        call_method(vm, &signal, "addEventListener", &[Value::str("abort"), abort, o])?;
    }
    Ok(stream)
}

fn compose_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let head = a.slot(0);
    call_method(vm, &head, "write", &[a.arg(0), a.arg(1)])?;
    vm.call(&a.arg(2), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn compose_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "end", &[])?;
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn compose_on_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "push", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn compose_on_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "push", &[Value::Null])?;
    Ok(Value::Undefined)
}

fn compose_on_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "destroy", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn compose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let arr = Value::Obj(vm.new_array(a.args.to_vec()));
    let flat = call_method(vm, &arr, "flat", &[])?;
    let streams: Vec<Value> = crate::builtins::array::array_like_to_vec(vm, &flat)?.into_iter().filter(|s| !s.is_nullish()).collect();
    if streams.is_empty() {
        return vm.construct(&Value::Obj(c.passthrough), &[], None);
    }
    let head = streams[0].clone();
    let tail = streams[streams.len() - 1].clone();
    for i in 0..streams.len() - 1 {
        call_method(vm, &streams[i], "pipe", &[streams[i + 1].clone()])?;
    }
    let read = vm.native_fn("read", 0, noop);
    let write = vm.native_closure("write", 3, compose_write, vec![head.clone()]);
    let fin_ = vm.native_closure("final", 1, compose_final, vec![head]);
    let opts = Value::Obj(vm.obj_from(vec![("read", Value::Obj(read)), ("write", Value::Obj(write)), ("final", Value::Obj(fin_))]));
    let d = vm.construct(&Value::Obj(c.duplex), &[opts], None)?;
    if getp(vm, &tail, "on")?.truthy() {
        let ondata = closure(vm, "", 1, compose_on_data, vec![d.clone()]);
        call_method(vm, &tail, "on", &[Value::str("data"), ondata])?;
        let onend = closure(vm, "", 0, compose_on_end, vec![d.clone()]);
        call_method(vm, &tail, "on", &[Value::str("end"), onend])?;
    }
    for s in &streams {
        if getp(vm, s, "on")?.truthy() {
            let onerr = closure(vm, "", 1, compose_on_error, vec![d.clone()]);
            call_method(vm, s, "on", &[Value::str("error"), onerr])?;
        }
    }
    Ok(d)
}

struct PairCell(RefCell<Value>);

fn pair_peer(a: &Args) -> Value {
    with_host::<PairCell, Value>(&a.slot(0), |c| c.0.borrow().clone()).unwrap_or(Value::Undefined)
}

fn pair_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let peer = pair_peer(a);
    call_method(vm, &peer, "push", &[a.arg(0)])?;
    vm.call(&a.arg(2), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn pair_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let peer = pair_peer(a);
    call_method(vm, &peer, "push", &[Value::Null])?;
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn duplex_pair(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let cell_a = host_obj(PairCell(RefCell::new(Value::Undefined)));
    let cell_b = host_obj(PairCell(RefCell::new(Value::Undefined)));
    let mk = |vm: &mut Vm, peer_cell: &Value| -> JsResult<Value> {
        let read = vm.native_fn("read", 0, noop);
        let write = vm.native_closure("write", 3, pair_write, vec![peer_cell.clone()]);
        let fin_ = vm.native_closure("final", 1, pair_final, vec![peer_cell.clone()]);
        let opts = Value::Obj(vm.obj_from(vec![("read", Value::Obj(read)), ("write", Value::Obj(write)), ("final", Value::Obj(fin_))]));
        vm.construct(&Value::Obj(c.duplex.clone()), &[opts], None)
    };
    // a writes into b, b writes into a
    let da = mk(vm, &cell_b)?;
    let db = mk(vm, &cell_a)?;
    with_host::<PairCell, ()>(&cell_a, |c| *c.0.borrow_mut() = da.clone());
    with_host::<PairCell, ()>(&cell_b, |c| *c.0.borrow_mut() = db.clone());
    Ok(Value::Obj(vm.new_array(vec![da, db])))
}

// ============================================================================================
// stream/consumers
// ============================================================================================

fn collect(vm: &mut Vm, src: &Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let p = cap.promise.clone();
    start_drive(vm, src, DriveKind::Collect, Value::Undefined, Some(cap));
    p
}

/// `await p` inside a native "async function": continue with `f(vm, value, data)`; the result
/// (or exception) settles `cap`.
fn await_then(vm: &mut Vm, p: Value, cap: &Capability, f: NativeFn, data: Value) {
    let ok = closure(vm, "", 1, f, vec![data, cap.resolve.clone(), cap.reject.clone()]);
    let er = cap.reject.clone();
    if let Value::Obj(po) = &p {
        perform_then_internal(vm, po, Handler::Callable(ok), Handler::Callable(er), None);
    }
}

fn settle_from(vm: &mut Vm, a: &Args, r: JsResult<Value>) -> JsResult<Value> {
    match r {
        Ok(v) => vm.call(&a.slot(1), Value::Undefined, &[v]),
        Err(e) => vm.call(&a.slot(2), Value::Undefined, &[e]),
    }
}

fn text_after(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = call_method(vm, &a.arg(0), "toString", &[Value::str("utf8")]);
    settle_from(vm, a, r)
}

fn consumer_text_promise(vm: &mut Vm, src: &Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let p = collect(vm, src);
    await_then(vm, p, &cap, text_after, Value::Undefined);
    cap.promise
}

fn consumer_text(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(consumer_text_promise(vm, &a.arg(0)))
}

fn json_after(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = match vm.to_string(&a.arg(0)) {
        Ok(s) => crate::builtins::json::json_parse(vm, &s),
        Err(e) => Err(e),
    };
    settle_from(vm, a, r)
}

fn consumer_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let p = consumer_text_promise(vm, &a.arg(0));
    await_then(vm, p, &cap, json_after, Value::Undefined);
    Ok(cap.promise)
}

fn consumer_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let p = collect(vm, &a.arg(0));
    vm.call(&cap.resolve, Value::Undefined, &[p])?;
    Ok(cap.promise)
}

fn array_buffer_after(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = a.arg(0);
    let r = (|| {
        let ab = getp(vm, &b, "buffer")?;
        let off = getp(vm, &b, "byteOffset")?;
        let len = getp(vm, &b, "byteLength")?;
        let end = vm.op_add(&off, &len)?;
        call_method(vm, &ab, "slice", &[off, end])
    })();
    settle_from(vm, a, r)
}

fn consumer_array_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let p = collect(vm, &a.arg(0));
    await_then(vm, p, &cap, array_buffer_after, Value::Undefined);
    Ok(cap.promise)
}

fn blob_after(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = (|| {
        let blob = match vm.global.get_own_str("Blob") {
            Some(b) => b,
            None => return vm.throw_ref("Blob is not defined"),
        };
        let parts = Value::Obj(vm.new_array(vec![a.arg(0)]));
        vm.construct(&blob, &[parts], None)
    })();
    settle_from(vm, a, r)
}

fn consumer_blob(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let p = collect(vm, &a.arg(0));
    await_then(vm, p, &cap, blob_after, Value::Undefined);
    Ok(cap.promise)
}

// ============================================================================================
// process.stdin
// ============================================================================================

struct StdinState {
    pumping: Cell<bool>,
}

/// process.stdin: a Readable fed from fd 0 once something resumes it.
pub fn make_stdin(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let read = vm.native_fn("read", 0, noop);
    let opts = Value::Obj(vm.obj_from(vec![("read", Value::Obj(read))]));
    let s = match vm.construct(&Value::Obj(c.readable), &[opts], None) {
        Ok(s) => s,
        Err(_) => return Value::Obj(vm.new_object()),
    };
    if let Value::Obj(o) = &s {
        let st = host_obj(StdinState { pumping: Cell::new(false) });
        let resume = vm.native_closure("", 0, stdin_resume, vec![st]);
        o.set_prop(key("resume"), Value::Obj(resume), WEC);
        o.set_prop(key("isTTY"), Value::Bool(false), WEC);
        o.set_prop(key("fd"), Value::Num(0.0), WEC);
    }
    s
}

fn stdin_resume(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = a.slot(0);
    if !with_host::<StdinState, bool>(&st, |s| s.pumping.get()).unwrap_or(true) {
        with_host::<StdinState, ()>(&st, |s| s.pumping.set(true));
        stdin_pump(vm, a.this.clone());
    }
    let rp = classes(vm).readable_proto;
    let resume = vm.get_str(&rp, "resume")?;
    vm.call(&resume, a.this.clone(), &[])
}

fn stdin_pump(vm: &mut Vm, target: Value) {
    crate::runtime::spawn_op(
        vm,
        || {
            use std::io::Read;
            let mut buf = vec![0u8; 65536];
            loop {
                match std::io::stdin().read(&mut buf) {
                    Ok(n) => {
                        buf.truncate(n);
                        return buf;
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(_) => return Vec::new(),
                }
            }
        },
        move |vm: &mut Vm, bytes: Vec<u8>| {
            // the reference's pump is an async function: a throwing listener rejects it (an
            // unhandled rejection) and stops the reading
            if bytes.is_empty() {
                if let Err(e) = call_method(vm, &target, "push", &[Value::Null]) {
                    rejected(vm, e);
                }
                return;
            }
            let r = new_buffer(vm, bytes).and_then(|b| call_method(vm, &target, "push", &[b]));
            if let Err(e) = r {
                rejected(vm, e);
                return;
            }
            stdin_pump(vm, target);
        },
    );
}

// ============================================================================================
// module objects
// ============================================================================================

pub fn setup(vm: &mut Vm) {
    // forked children (LUMEN_FORK_IPC=1) get process.send / disconnect / 'message'
    crate::runtime::child_process::setup(vm);
}

fn create_stream(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let m = c.stream.clone();
    let put = |k: &str, v: Value| m.set_prop(key(k), v, WEC);
    put("Readable", Value::Obj(c.readable.clone()));
    put("Writable", Value::Obj(c.writable.clone()));
    put("Duplex", Value::Obj(c.duplex.clone()));
    put("Transform", Value::Obj(c.transform.clone()));
    put("PassThrough", Value::Obj(c.passthrough.clone()));
    put("Stream", Value::Obj(c.stream.clone()));
    let fns1: &[(&str, u32, NativeFn)] = &[("finished", 3, finished_fn_f), ("pipeline", 0, pipeline_fn_f)];
    for (n, l, f) in fns1 {
        let fo = plain_fn(vm, n, *l, *f);
        put(n, Value::Obj(fo));
    }
    let promises = vm.new_object();
    vm_set_method(vm, &promises, "finished", 2, promises_finished);
    vm_set_method(vm, &promises, "pipeline", 0, promises_pipeline);
    put("promises", Value::Obj(promises));
    let fns2: &[(&str, u32, NativeFn)] = &[
        ("destroy", 2, destroy_fn),
        ("addAbortSignal", 2, add_abort_signal),
        ("compose", 0, compose),
        ("duplexPair", 0, duplex_pair),
        ("isDestroyed", 1, is_destroyed),
        ("isErrored", 1, is_errored),
        ("isReadable", 1, is_readable),
        ("isWritable", 1, is_writable),
        ("isDisturbed", 1, is_disturbed),
        ("getDefaultHighWaterMark", 1, get_default_hwm),
        ("setDefaultHighWaterMark", 2, set_default_hwm),
        ("_isArrayBufferView", 1, is_array_buffer_view),
        ("_isUint8Array", 1, is_uint8_array_fn),
        ("_uint8ArrayToBuffer", 1, uint8_array_to_buffer),
    ];
    for (n, l, f) in fns2 {
        let fo = plain_fn(vm, n, *l, *f);
        put(n, Value::Obj(fo));
    }
    Value::Obj(m)
}

/// An enumerable method property (object-literal method shorthand).
fn vm_set_method(vm: &mut Vm, o: &Obj, name: &str, len: u32, f: NativeFn) {
    let fo = vm.native_fn(name, len, f);
    o.set_prop(key(name), Value::Obj(fo), WEC);
}

pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    match name {
        "stream" => create_stream(vm),
        "stream/promises" => {
            let o = vm.new_object();
            vm_set_method(vm, &o, "finished", 2, promises_finished);
            vm_set_method(vm, &o, "pipeline", 0, promises_pipeline);
            Value::Obj(o)
        }
        "stream/consumers" => {
            let o = vm.new_object();
            let fns: &[(&str, NativeFn)] = &[
                ("arrayBuffer", consumer_array_buffer),
                ("blob", consumer_blob),
                ("buffer", consumer_buffer),
                ("json", consumer_json),
                ("text", consumer_text),
            ];
            for (n, f) in fns {
                vm_set_method(vm, &o, n, 1, *f);
            }
            Value::Obj(o)
        }
        "stream/web" => {
            let o = vm.new_object();
            for n in [
                "ReadableStream",
                "ReadableStreamDefaultReader",
                "ReadableStreamBYOBReader",
                "ReadableStreamDefaultController",
                "ReadableByteStreamController",
                "ReadableStreamBYOBRequest",
                "WritableStream",
                "WritableStreamDefaultWriter",
                "WritableStreamDefaultController",
                "TransformStream",
                "TransformStreamDefaultController",
                "ByteLengthQueuingStrategy",
                "CountQueuingStrategy",
                "TextEncoderStream",
                "TextDecoderStream",
                "CompressionStream",
                "DecompressionStream",
            ] {
                let v = vm.global.get_own_str(n).unwrap_or(Value::Undefined);
                o.set_prop(key(n), v, WEC);
            }
            Value::Obj(o)
        }
        _ => Value::Obj(vm.new_object()),
    }
}

// the reference's JS frames for errors raised synchronously by these entry points
framed_native!(readable_ctor_f, ["Readable"], readable_ctor);
framed_native!(writable_ctor_f, ["Writable"], writable_ctor);
framed_native!(duplex_ctor_f, ["Duplex", "Readable"], duplex_ctor);
framed_native!(transform_ctor_f, ["Transform", "Duplex", "Readable"], transform_ctor);
framed_native!(passthrough_ctor_f, ["PassThrough", "Transform", "Duplex", "Readable"], transform_ctor);
framed_native!(readable_read_f, ["read"], readable_read);
framed_native!(writable_write_f, ["write"], writable_write);
framed_native!(finished_fn_f, ["finished"], finished_fn);
framed_native!(pipeline_fn_f, ["pipeline"], pipeline_fn);
