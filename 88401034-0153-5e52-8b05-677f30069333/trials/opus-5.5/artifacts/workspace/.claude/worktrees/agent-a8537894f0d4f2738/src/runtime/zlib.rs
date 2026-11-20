// node:zlib — the module object, sync/async codecs and the stream classes.
//
// Modelled on the reference runtime (see the notes at the top of `crate::compress`):
// * `xSync(input)` = `Buffer.from(codec(toBuf(input)))`: options are never read; decoder
//   failures are plain `Error`s whose only own property is `message`.
// * `x(input, opts, cb)` queues one microtask (promise-based, so a throwing callback becomes an
//   unhandled rejection) that runs `cb(null, xSync(input))`, or `cb(err)` when that throws.
// * The 11 classes start as lazy accessors on the exports object. Each is
//   `class cls extends stream.Transform` that buffers every chunk (Buffers by reference) and
//   runs the sync codec once in `_flush`, pushing exactly one chunk.
// * The reference's helpers are anonymous arrows, so error stacks show `at <anonymous>`; its
//   interpreter eliminates tail calls (e.g. the `toBuf` frame) until a function has been
//   called 8 times.

use crate::builtins::typedarray::{ta_bytes, MAX_TA_LENGTH};
use crate::compress::{Codec, ZLIB_CONSTANTS};
use crate::object::*;
use crate::runtime::buffer::with_frames;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};

struct CodecDef {
    sync: &'static str,
    async_: &'static str,
    class: &'static str,
    create: &'static str,
    codec: Codec,
}

const CODECS: [CodecDef; 11] = [
    CodecDef { sync: "gzipSync", async_: "gzip", class: "Gzip", create: "createGzip", codec: Codec::Gzip },
    CodecDef { sync: "gunzipSync", async_: "gunzip", class: "Gunzip", create: "createGunzip", codec: Codec::Gunzip },
    CodecDef { sync: "deflateSync", async_: "deflate", class: "Deflate", create: "createDeflate", codec: Codec::Deflate },
    CodecDef { sync: "inflateSync", async_: "inflate", class: "Inflate", create: "createInflate", codec: Codec::Inflate },
    CodecDef { sync: "deflateRawSync", async_: "deflateRaw", class: "DeflateRaw", create: "createDeflateRaw", codec: Codec::DeflateRaw },
    CodecDef { sync: "inflateRawSync", async_: "inflateRaw", class: "InflateRaw", create: "createInflateRaw", codec: Codec::InflateRaw },
    CodecDef { sync: "brotliCompressSync", async_: "brotliCompress", class: "BrotliCompress", create: "createBrotliCompress", codec: Codec::BrotliCompress },
    CodecDef {
        sync: "brotliDecompressSync",
        async_: "brotliDecompress",
        class: "BrotliDecompress",
        create: "createBrotliDecompress",
        codec: Codec::BrotliDecompress,
    },
    CodecDef { sync: "zstdCompressSync", async_: "zstdCompress", class: "ZstdCompress", create: "createZstdCompress", codec: Codec::ZstdCompress },
    CodecDef { sync: "zstdDecompressSync", async_: "zstdDecompress", class: "ZstdDecompress", create: "createZstdDecompress", codec: Codec::ZstdDecompress },
    CodecDef { sync: "unzipSync", async_: "unzip", class: "Unzip", create: "createUnzip", codec: Codec::Unzip },
];

const TIER_UP_CALLS: u32 = 8;

thread_local! {
    static CLASSES: RefCell<Vec<Option<Obj>>> = RefCell::new(vec![None; 11]);
    static FALLBACK: RefCell<Option<(Obj, Obj)>> = RefCell::new(None);
    static TOBUF_CALLS: Cell<u32> = Cell::new(0);
    static CRC_CALLS: Cell<u32> = Cell::new(0);
    static JOB_CALLS: Cell<u32> = Cell::new(0);
}

fn bump(c: &'static std::thread::LocalKey<Cell<u32>>) -> u32 {
    c.with(|c| {
        let n = c.get();
        c.set(n.saturating_add(1));
        n
    })
}

fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

fn slot_idx(a: &Args, i: usize) -> usize {
    a.slot(i).as_num().unwrap_or(0.0) as usize
}

/// `queueMicrotask(f)` as the reference implements it (a promise reaction: a throwing job
/// becomes an unhandled rejection).
pub fn queue_microtask(vm: &mut Vm, f: Value) {
    match crate::builtins::promise::promise_resolve_intrinsic(vm, Value::Undefined) {
        Ok(p) => {
            let _ = crate::builtins::promise::promise_then(vm, &p, f, Value::Undefined);
        }
        Err(_) => vm.jobs.push_back(crate::vm::Job::Callback(f, Vec::new())),
    }
}

fn call_member(vm: &mut Vm, x: &Value, prop: &str, args: &[Value]) -> JsResult<Value> {
    let f = vm.get_prop_of(x, &key(prop))?;
    if !f.is_callable() {
        let m = crate::runtime::buffer::not_callable_msg(true, prop, &f);
        return vm.throw_type(m);
    }
    vm.call(&f, x.clone(), args)
}

// ============================================================================================
// input conversion and the codec natives
// ============================================================================================

/// `toBuf(x)`: Uint8Array instances pass through, anything else is `Buffer.from(x)` (a tail
/// call while the helper is interpreted).
fn to_buf(vm: &mut Vm, x: &Value) -> JsResult<Value> {
    let calls = bump(&TOBUF_CALLS);
    let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
    if vm.instance_of(x, &u8c)? {
        return Ok(x.clone());
    }
    if calls >= TIER_UP_CALLS {
        with_frames(vm, &["toBuf"], |vm| crate::runtime::buffer::buffer_from_value(vm, x, &Value::Undefined))
    } else {
        crate::runtime::buffer::buffer_from_value(vm, x, &Value::Undefined)
    }
}

/// Bytes of the typed array handed to a codec native.
fn native_input(vm: &mut Vm, v: &Value, msg: &str) -> JsResult<Vec<u8>> {
    if let Value::Obj(o) = v {
        let ok = matches!(&o.borrow().kind, ObjKind::TypedArray(t) if !t.is_out_of_bounds());
        if ok {
            return Ok(ta_bytes(o));
        }
    }
    vm.throw_type(msg)
}

/// Run codec `idx` and wrap the result in a Buffer.
fn run_codec(vm: &mut Vm, idx: usize, bytes: &[u8]) -> JsResult<Value> {
    let out = match CODECS[idx].codec.run(bytes) {
        Ok(o) => o,
        Err(e) => return Err(vm.make_error("Error", &e.message)),
    };
    if out.len() > MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    crate::runtime::buffer::new_buffer_value(vm, out)
}

/// `xSync(input)` without its frame.
fn sync_impl(vm: &mut Vm, idx: usize, input: &Value) -> JsResult<Value> {
    let b = to_buf(vm, input)?;
    let bytes = native_input(vm, &b, "zlib expects a Buffer/TypedArray")?;
    run_codec(vm, idx, &bytes)
}

fn zlib_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let idx = slot_idx(a, 0);
    with_frames(vm, &["<anonymous>"], |vm| sync_impl(vm, idx, &a.arg(0)))
}

/// `(input, opts, cb) => { if (typeof opts === "function") cb = opts; queueMicrotask(job) }`
fn zlib_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let idx = a.slot(0);
    let mut cb = a.arg(2);
    if a.arg(1).is_callable() {
        cb = a.arg(1);
    }
    let job = vm.native_closure("", 0, zlib_async_job, vec![idx, a.arg(0), cb]);
    queue_microtask(vm, Value::Obj(job));
    Ok(Value::Undefined)
}

/// `cb(...)` from the job: a non-callable `cb` is reported with the job's tier wording.
fn call_cb(vm: &mut Vm, cb: &Value, args: &[Value], interpreted: bool) -> JsResult<Value> {
    if !cb.is_callable() {
        let m = if interpreted { "cb is not a function".to_string() } else { format!("{} is not a function", crate::runtime::buffer::jit_type_name(cb)) };
        return vm.throw_type(m);
    }
    vm.call(cb, Value::Undefined, args)
}

/// `() => { try { cb(null, syncFn(input)); } catch (e) { cb(e); } }`
fn zlib_async_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let interpreted = bump(&JOB_CALLS) < TIER_UP_CALLS;
    let idx = slot_idx(a, 0);
    let input = a.slot(1);
    let cb = a.slot(2);
    with_frames(vm, &["<anonymous>"], |vm| {
        let r = (|| -> JsResult<Value> {
            let out = with_frames(vm, &["<anonymous>"], |vm| sync_impl(vm, idx, &input))?;
            call_cb(vm, &cb, &[Value::Null, out], interpreted)
        })();
        if let Err(e) = r {
            call_cb(vm, &cb, &[e], interpreted)?;
        }
        Ok(Value::Undefined)
    })
}

/// `(data, value = 0) => __zlib.crc32(toBuf(data), value >>> 0)`
fn zlib_crc32(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let compiled = bump(&CRC_CALLS) >= TIER_UP_CALLS;
    let (b, init) = with_frames(vm, &["<anonymous>"], |vm| {
        let b = to_buf(vm, &a.arg(0))?;
        let v = a.arg(1);
        let v = if v.is_undefined() { Value::Num(0.0) } else { v };
        let n = vm.to_numeric(&v)?;
        let init = match n {
            Value::Num(f) => crate::builtins::number::to_uint32(f),
            _ => return vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
        };
        Ok((b, init))
    })?;
    // the native call is a tail call while the arrow is interpreted
    let frames: &[&str] = if compiled { &["<anonymous>"] } else { &[] };
    with_frames(vm, frames, |vm| {
        let bytes = native_input(vm, &b, "zlib.crc32 expects a Buffer/TypedArray")?;
        Ok(Value::Num(crate::compress::crc32(&bytes, init) as f64))
    })
}

/// `(options) => new zlib[cap](options)`
fn zlib_create(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let exports = a.slot(0);
    let cap = match a.slot(1) {
        Value::Str(s) => PropKey::Str(s),
        _ => key(""),
    };
    let ctor = vm.get_prop_of(&exports, &cap)?;
    vm.construct(&ctor, &[a.arg(0)], None)
}

// ============================================================================================
// stream classes
// ============================================================================================

/// The getter of a lazily created class: builds it and redefines the export as a data property.
fn zlib_class_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let exports = a.slot(0);
    let idx = slot_idx(a, 1);
    let cls = class_for(vm, idx)?;
    if let Value::Obj(e) = &exports {
        e.set_prop(key(CODECS[idx].class), Value::Obj(cls.clone()), WEC);
    }
    Ok(Value::Obj(cls))
}

/// `require('stream').Transform` when the runtime provides it, else a Transform built on the
/// fs module's Readable/Writable bases.
fn transform_base(vm: &mut Vm) -> JsResult<Obj> {
    if let Some(m) = crate::runtime::node::builtin_module(vm, "stream")? {
        if let Value::Obj(mo) = &m {
            let t = vm.get_str(mo, "Transform")?;
            if let Value::Obj(to) = &t {
                if to.is_constructor() {
                    return Ok(to.clone());
                }
            }
        }
    }
    fallback_transform(vm)
}

fn class_for(vm: &mut Vm, idx: usize) -> JsResult<Obj> {
    if let Some(c) = CLASSES.with(|c| c.borrow()[idx].clone()) {
        return Ok(c);
    }
    let parent = transform_base(vm)?;
    let parent_proto = match vm.get_str(&parent, "prototype")? {
        Value::Obj(p) => p,
        _ => vm.intr.object_proto.clone(),
    };
    let proto = Obj::new(Some(parent_proto), ObjKind::Ordinary);
    let cls = vm.native_closure("cls", 1, cls_ctor, vec![Value::Obj(parent.clone())]);
    vm.make_ctor(&cls);
    cls.borrow_mut().proto = Some(parent);
    cls.set_prop(key("prototype"), Value::Obj(proto.clone()), 0);
    proto.set_prop(key("constructor"), Value::Obj(cls.clone()), WC);
    let t = vm.native_fn("_transform", 3, cls_transform);
    proto.set_prop(key("_transform"), Value::Obj(t), WC);
    let f = vm.native_closure("_flush", 1, cls_flush, vec![Value::Num(idx as f64)]);
    proto.set_prop(key("_flush"), Value::Obj(f), WC);
    CLASSES.with(|c| c.borrow_mut()[idx] = Some(cls.clone()));
    Ok(cls)
}

/// `constructor(options) { super(options); this._chunks = []; }`
fn cls_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = match &a.new_target {
        Some(nt) => nt.clone(),
        None => return vm.throw_type("Class constructor cannot be invoked without 'new'"),
    };
    let parent = a.slot(0);
    with_frames(vm, &["cls"], |vm| {
        let this = vm.construct(&parent, &[a.arg(0)], Some(&Value::Obj(nt)))?;
        let chunks = vm.new_array(Vec::new());
        vm.set_prop_of(&this, key("_chunks"), Value::Obj(chunks), true)?;
        Ok(this)
    })
}

/// `_transform(chunk, enc, next) { this._chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, enc)); next(); }`
fn cls_transform(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["_transform"], |vm| {
        let chunk = a.arg(0);
        let c = if crate::runtime::buffer::is_buffer(vm, &chunk) { chunk } else { crate::runtime::buffer::buffer_from_value(vm, &chunk, &a.arg(1))? };
        let chunks = vm.get_prop_of(&a.this, &key("_chunks"))?;
        call_member(vm, &chunks, "push", &[c])?;
        let next = a.arg(2);
        if !next.is_callable() {
            return vm.throw_type("next is not a function");
        }
        vm.call(&next, Value::Undefined, &[])
    })
}

/// `_flush(done) { try { this.push(syncFn(Buffer.concat(this._chunks))); done(); } catch (e) { done(e); } }`
fn cls_flush(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let idx = slot_idx(a, 0);
    let done = a.arg(0);
    let this = a.this.clone();
    with_frames(vm, &["_flush"], |vm| {
        let r = (|| -> JsResult<Value> {
            let chunks = vm.get_prop_of(&this, &key("_chunks"))?;
            let input = crate::runtime::buffer::concat_value(vm, &chunks)?;
            let out = with_frames(vm, &["<anonymous>"], |vm| sync_impl(vm, idx, &input))?;
            call_member(vm, &this, "push", &[out])?;
            call_done(vm, &done, &[])
        })();
        if let Err(e) = r {
            call_done(vm, &done, &[e])?;
        }
        Ok(Value::Undefined)
    })
}

fn call_done(vm: &mut Vm, f: &Value, args: &[Value]) -> JsResult<Value> {
    if !f.is_callable() {
        return vm.throw_type("done is not a function");
    }
    vm.call(f, Value::Undefined, args)
}

// --- fallback Duplex/Transform (used when node:stream does not provide Transform) ---

fn require_new(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.new_target {
        Some(nt) => Ok(nt.clone()),
        None => vm.throw_type("Class constructor cannot be invoked without 'new'"),
    }
}

fn opts_or_empty(vm: &mut Vm, v: &Value) -> Value {
    if v.is_undefined() {
        Value::Obj(vm.new_object())
    } else {
        v.clone()
    }
}

/// Duplex: Readable state plus a Writable's state (`writable`, `_writableState`).
fn duplex_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    let (readable, writable) = match crate::runtime::fs::stream_base_ctors(vm) {
        Some(x) => x,
        None => return vm.throw_type("stream bases unavailable"),
    };
    with_frames(vm, &["Duplex"], |vm| {
        let opts = opts_or_empty(vm, &a.arg(0));
        let this = with_frames(vm, &["Readable"], |vm| vm.construct(&Value::Obj(readable), &[opts.clone()], Some(&Value::Obj(nt))))?;
        let tmp = vm.construct(&Value::Obj(writable), &[opts.clone()], None)?;
        let ws = vm.get_prop_of(&tmp, &key("_writableState"))?;
        vm.set_prop_of(&this, key("_writableState"), ws, true)?;
        vm.set_prop_of(&this, key("writable"), Value::Bool(true), true)?;
        for (opt, prop) in [("write", "_write"), ("writev", "_writev"), ("final", "_final")] {
            let f = vm.get_prop_of(&opts, &key(opt))?;
            if f.is_callable() {
                vm.set_prop_of(&this, key(prop), f, true)?;
            }
        }
        Ok(this)
    })
}

fn transform_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    let duplex = match FALLBACK.with(|f| f.borrow().clone()) {
        Some((d, _)) => d,
        None => return vm.throw_type("Transform base unavailable"),
    };
    with_frames(vm, &["Transform"], |vm| {
        let opts = opts_or_empty(vm, &a.arg(0));
        let this = vm.construct(&Value::Obj(duplex), &[opts.clone()], Some(&Value::Obj(nt)))?;
        for (opt, prop) in [("transform", "_transform"), ("flush", "_flush")] {
            let f = vm.get_prop_of(&opts, &key(opt))?;
            if f.is_callable() {
                vm.set_prop_of(&this, key(prop), f, true)?;
            }
        }
        Ok(this)
    })
}

/// `_transform(chunk, encoding, cb) { cb(null, chunk); }`
fn transform_default_transform(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(2);
    vm.call(&cb, Value::Undefined, &[Value::Null, a.arg(0)])
}

/// `_write(chunk, encoding, cb)`: run `_transform`, push its data, then `cb()`.
fn transform_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let inner = vm.native_closure("", 2, transform_write_cb, vec![this.clone(), a.arg(2)]);
    call_member(vm, &this, "_transform", &[a.arg(0), a.arg(1), Value::Obj(inner)])
}

fn transform_write_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb) = (a.slot(0), a.slot(1));
    let err = a.arg(0);
    if err.truthy() {
        return vm.call(&cb, Value::Undefined, &[err]);
    }
    let data = a.arg(1);
    if !data.is_nullish() {
        call_member(vm, &this, "push", &[data])?;
    }
    vm.call(&cb, Value::Undefined, &[])
}

/// `_final(cb)`: `_flush` (pushing its data and then null) or just `push(null)`.
fn transform_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    // the reference runs `_final` from end()'s `state.tail.then(() => ...)` arrow
    with_frames(vm, &["<anonymous>", "_final"], |vm| {
        let flush = vm.get_prop_of(&this, &key("_flush"))?;
        if flush.truthy() {
            let inner = vm.native_closure("", 2, transform_final_cb, vec![this.clone(), cb.clone()]);
            vm.call(&flush, this.clone(), &[Value::Obj(inner)])?;
        } else {
            call_member(vm, &this, "push", &[Value::Null])?;
            vm.call(&cb, Value::Undefined, &[])?;
        }
        Ok(Value::Undefined)
    })
}

fn transform_final_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb) = (a.slot(0), a.slot(1));
    let data = a.arg(1);
    if !data.is_nullish() {
        call_member(vm, &this, "push", &[data])?;
    }
    call_member(vm, &this, "push", &[Value::Null])?;
    vm.call(&cb, Value::Undefined, &[a.arg(0)])
}

fn fallback_transform(vm: &mut Vm) -> JsResult<Obj> {
    if let Some((_, t)) = FALLBACK.with(|f| f.borrow().clone()) {
        return Ok(t);
    }
    let (readable, writable) = match crate::runtime::fs::stream_base_ctors(vm) {
        Some(x) => x,
        None => return vm.throw_type("stream bases unavailable"),
    };
    let rproto = match vm.get_str(&readable, "prototype")? {
        Value::Obj(p) => p,
        _ => vm.intr.object_proto.clone(),
    };
    let wproto = match vm.get_str(&writable, "prototype")? {
        Value::Obj(p) => p,
        _ => vm.intr.object_proto.clone(),
    };
    // Duplex
    let dproto = Obj::new(Some(rproto), ObjKind::Ordinary);
    let duplex = vm.native_ctor("Duplex", 0, duplex_ctor, &dproto);
    duplex.borrow_mut().proto = Some(readable);
    for name in ["_write", "write", "_queueBatch", "end", "cork", "uncork", "setDefaultEncoding", "writableLength", "writableHighWaterMark", "writableObjectMode"] {
        let p = wproto.borrow().props.get(&key(name)).cloned();
        if let Some(p) = p {
            dproto.borrow_mut().props.insert(key(name), p);
        }
    }
    // Transform
    let tproto = Obj::new(Some(dproto), ObjKind::Ordinary);
    let transform = vm.native_ctor("Transform", 0, transform_ctor, &tproto);
    transform.borrow_mut().proto = Some(duplex.clone());
    vm.def_method(&tproto, "_transform", 3, transform_default_transform);
    vm.def_method(&tproto, "_write", 3, transform_write);
    vm.def_method(&tproto, "_final", 1, transform_final);
    FALLBACK.with(|f| *f.borrow_mut() = Some((duplex, transform.clone())));
    Ok(transform)
}

// ============================================================================================
// module
// ============================================================================================

pub fn create_module(vm: &mut Vm) -> Value {
    let exports = vm.new_object();
    let ev = Value::Obj(exports.clone());
    for (i, c) in CODECS.iter().enumerate() {
        let idx = Value::Num(i as f64);
        let s = vm.native_closure("", 1, zlib_sync, vec![idx.clone()]);
        exports.set_prop(key(c.sync), Value::Obj(s), WEC);
        let asy = vm.native_closure("", 3, zlib_async, vec![idx.clone()]);
        exports.set_prop(key(c.async_), Value::Obj(asy), WEC);
        let g = vm.native_closure("get", 0, zlib_class_getter, vec![ev.clone(), idx.clone()]);
        exports.set_accessor(key(c.class), Some(g), None, ENUMERABLE | CONFIGURABLE);
        let cr = vm.native_closure("", 1, zlib_create, vec![ev.clone(), Value::str(c.class)]);
        exports.set_prop(key(c.create), Value::Obj(cr), WEC);
    }
    let crc = vm.native_fn("", 1, zlib_crc32);
    exports.set_prop(key("crc32"), Value::Obj(crc), WEC);
    let constants = vm.new_object();
    for (k, v) in ZLIB_CONSTANTS {
        let val = match v {
            Some(n) => Value::Num(*n as f64),
            None => Value::Null,
        };
        constants.set_prop(key(k), val, WEC);
    }
    exports.set_prop(key("constants"), Value::Obj(constants), WEC);
    let codes = vm.new_object();
    let names = ["Z_VERSION_ERROR", "Z_BUF_ERROR", "Z_MEM_ERROR", "Z_DATA_ERROR", "Z_STREAM_ERROR", "Z_ERRNO", "Z_OK", "Z_STREAM_END", "Z_NEED_DICT"];
    for (i, n) in names.iter().enumerate() {
        let num = i as i32 - 6;
        codes.set_prop(key(&num.to_string()), Value::str(n), WEC);
    }
    for (n, v) in [("Z_OK", 0), ("Z_STREAM_END", 1), ("Z_NEED_DICT", 2), ("Z_ERRNO", -1), ("Z_STREAM_ERROR", -2), ("Z_DATA_ERROR", -3), ("Z_MEM_ERROR", -4), ("Z_BUF_ERROR", -5), ("Z_VERSION_ERROR", -6)] {
        codes.set_prop(key(n), Value::Num(v as f64), WEC);
    }
    exports.set_prop(key("codes"), Value::Obj(codes), WEC);
    ev
}
