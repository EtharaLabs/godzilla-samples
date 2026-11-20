// node:crypto and the global WebCrypto object.
//
// The reference implements most of node:crypto in JavaScript; this binding reproduces its
// observable behaviour on top of the pure-Rust primitives in `crate::crypto`:
// * instances keep the reference's own properties (`Hash` has `_reg`, `_chunks`, `_used`, a
//   `KeyObject` has `_type`, `_material`, `_asym`, ...) and data passed to `update()` is kept
//   by reference until it is consumed, like the reference does;
// * plain `function`s are constructible and own a `prototype`, arrows are not;
// * async variants compute synchronously and deliver `(err, result)` from one promise-based
//   microtask (queueMicrotask semantics);
// * error messages, codes and the internal frames in error stacks (`at toBytes`,
//   `at resolveHash`, `at codedError`, ...) follow the reference; its interpreter eliminates
//   tail calls until a function has run 8 times, which a few helpers emulate.

use crate::builtins::typedarray::{ta_bytes, MAX_TA_LENGTH};
use crate::crypto::{self as cr, CryptoError, HashAlg};
use crate::object::*;
use crate::runtime::buffer::{self, with_frames};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;

const TIER_UP_CALLS: u32 = 8;

#[derive(Default, Clone)]
struct State {
    exports: Option<Obj>,
    regs: HashMap<&'static str, Obj>,
    hash_ctor: Option<Obj>,
    hash_proto: Option<Obj>,
    hmac_ctor: Option<Obj>,
    keyobject_ctor: Option<Obj>,
    keyobject_proto: Option<Obj>,
    cipher_proto: Option<Obj>,
    decipher_proto: Option<Obj>,
    sign_ctor: Option<Obj>,
    verify_ctor: Option<Obj>,
    dh_ctor: Option<Obj>,
    dh_proto: Option<Obj>,
    dhgroup_ctor: Option<Obj>,
    ecdh_ctor: Option<Obj>,
    x509_ctor: Option<Obj>,
    x509_proto: Option<Obj>,
    certificate_ctor: Option<Obj>,
    webcrypto: Option<Obj>,
    subtle: Option<Obj>,
}

thread_local! {
    static ST: RefCell<State> = RefCell::new(State::default());
    static TOBYTES_CALLS: Cell<u32> = Cell::new(0);
    static DIGEST_CALLS: Cell<u32> = Cell::new(0);
    static CUPDATE_CALLS: Cell<u32> = Cell::new(0);
    static CFINAL_CALLS: Cell<u32> = Cell::new(0);
    static CSETAAD_CALLS: Cell<u32> = Cell::new(0);
    static GRV_CALLS: Cell<u32> = Cell::new(0);
    static UUID_CALLS: Cell<u32> = Cell::new(0);
    static RB_CB_CALLS: Cell<u32> = Cell::new(0);
}

fn bump(c: &'static std::thread::LocalKey<Cell<u32>>) -> u32 {
    c.with(|c| {
        let n = c.get();
        c.set(n.saturating_add(1));
        n
    })
}

/// Frames of a `return f(...)` tail call: none while the caller is interpreted.
fn tail<'a>(calls: u32, name: &'a str) -> Vec<&'a str> {
    if calls >= TIER_UP_CALLS {
        vec![name]
    } else {
        vec![]
    }
}

fn st<R>(f: impl FnOnce(&State) -> R) -> R {
    ST.with(|s| f(&s.borrow()))
}

fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

fn get(vm: &mut Vm, v: &Value, k: &str) -> JsResult<Value> {
    vm.get_prop_of(v, &key(k))
}

fn set(vm: &mut Vm, v: &Value, k: &str, x: Value) -> JsResult<()> {
    vm.set_prop_of(v, key(k), x, true)
}

fn call_member(vm: &mut Vm, x: &Value, prop: &str, args: &[Value]) -> JsResult<Value> {
    let f = vm.get_prop_of(x, &key(prop))?;
    if !f.is_callable() {
        let m = buffer::not_callable_msg(true, prop, &f);
        return vm.throw_type(m);
    }
    vm.call(&f, x.clone(), args)
}

fn num(n: f64) -> Value {
    Value::Num(n)
}

// ============================================================================================
// errors
// ============================================================================================

/// `codedError(Ctor, message, code)`: the error gets an own enumerable `code`.
fn coded(vm: &mut Vm, kind: &str, msg: &str, code: &str) -> Value {
    with_frames(vm, &["codedError"], |vm| {
        let e = vm.make_error(kind, msg);
        if let Value::Obj(o) = &e {
            o.set_prop(key("code"), Value::str(code), WEC);
        }
        Ok(e)
    })
    .unwrap_or(Value::Undefined)
}

fn cerr(vm: &mut Vm, e: CryptoError) -> Value {
    match e.code {
        Some(code) => coded(vm, e.kind.name(), &e.message, code),
        None => vm.make_error(e.kind.name(), &e.message),
    }
}

fn throw<T>(vm: &mut Vm, e: CryptoError) -> JsResult<T> {
    Err(cerr(vm, e))
}

/// `new DOMException(message, name)` (falls back to an Error carrying `name`).
fn dom_exception(vm: &mut Vm, msg: &str, name: &str) -> Value {
    let r = with_frames(vm, &["DOMException"], |vm| {
        if let Some(de) = vm.global.get_own_str("DOMException") {
            if let Value::Obj(c) = &de {
                if c.is_constructor() {
                    return vm.construct(&de, &[Value::str(msg), Value::str(name)], None);
                }
            }
        }
        let e = vm.make_error("Error", msg);
        if let Value::Obj(o) = &e {
            o.set_prop(key("name"), Value::str(name), WEC);
        }
        Ok(e)
    });
    match r {
        Ok(v) | Err(v) => v,
    }
}

// ============================================================================================
// small helpers
// ============================================================================================

/// `queueMicrotask(f)` as the reference implements it (promise reaction).
fn queue_microtask(vm: &mut Vm, f: Value) {
    crate::runtime::zlib::queue_microtask(vm, f);
}

fn closure(vm: &mut Vm, f: NativeFn, slots: Vec<Value>) -> Value {
    Value::Obj(vm.native_closure("", 0, f, slots))
}

/// Deliver `cb(err)` or `cb(null, ...results)` from a microtask.
fn defer_cb(vm: &mut Vm, cb: &Value, r: Result<Vec<Value>, Value>) {
    let args = match r {
        Ok(vals) => {
            let mut v = vec![Value::Null];
            v.extend(vals);
            v
        }
        Err(e) => vec![e],
    };
    let arr = Value::Obj(vm.new_array(args));
    let job = closure(vm, deferred_cb_job, vec![cb.clone(), arr]);
    queue_microtask(vm, job);
}

/// `defer_cb` for randomBytes (its arrow's calls are counted for the tier-up wording).
fn defer_random_bytes_cb(vm: &mut Vm, cb: &Value, buf: Value) {
    let arr = Value::Obj(vm.new_array(vec![Value::Null, buf]));
    let job = closure(vm, deferred_cb_job, vec![cb.clone(), arr, Value::Bool(true)]);
    queue_microtask(vm, job);
}

fn deferred_cb_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.slot(0);
    let args = crate::builtins::array::array_like_to_vec(vm, &a.slot(1))?;
    if !cb.is_callable() {
        // only randomBytes can get here (the other APIs validate their callback): its
        // `() => cb(null, buf)` arrow reports with the interpreter's wording until compiled
        let m = if bump(&RB_CB_CALLS) < TIER_UP_CALLS { "cb is not a function".to_string() } else { format!("{} is not a function", buffer::jit_type_name(&cb)) };
        return vm.throw_type(m);
    }
    if !a.slot(2).is_undefined() {
        bump(&RB_CB_CALLS);
    }
    vm.call(&cb, Value::Undefined, &args)
}

fn ta_kind(v: &Value) -> Option<TAKind> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::TypedArray(t) => Some(t.kind),
            _ => None,
        },
        _ => None,
    }
}

/// Raw bytes of a typed array / ArrayBuffer / DataView value (empty for anything else).
fn raw_bytes(v: &Value) -> Vec<u8> {
    match v {
        Value::Obj(o) => ta_bytes(o),
        _ => Vec::new(),
    }
}

fn u8array(vm: &mut Vm, bytes: Vec<u8>) -> Value {
    Value::Obj(crate::builtins::typedarray::typed_array_from_bytes(vm, bytes))
}

fn new_buf(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    buffer::new_buffer_value(vm, bytes)
}

fn array_buffer(vm: &mut Vm, bytes: Vec<u8>) -> Value {
    Value::Obj(crate::builtins::typedarray::new_array_buffer(vm, bytes))
}

fn is_instance(vm: &mut Vm, v: &Value, ctor: &Option<Obj>) -> JsResult<bool> {
    match ctor {
        Some(c) => vm.instance_of(v, &Value::Obj(c.clone())),
        None => Ok(false),
    }
}

/// `encoding && encoding !== "buffer" ? buf.toString(encoding) : buf`
fn maybe_encode(vm: &mut Vm, buf: Value, enc: &Value) -> JsResult<Value> {
    if enc.truthy() && !matches!(enc, Value::Str(s) if s.eq_str("buffer")) {
        buffer::buffer_to_string(vm, &buf, enc)
    } else {
        Ok(buf)
    }
}

/// `encoding ? buf.toString(encoding) : buf`
fn maybe_encode_any(vm: &mut Vm, buf: Value, enc: &Value) -> JsResult<Value> {
    if enc.truthy() {
        buffer::buffer_to_string(vm, &buf, enc)
    } else {
        Ok(buf)
    }
}

/// `Number.isInteger(v)`
fn is_integer(v: &Value) -> bool {
    matches!(v, Value::Num(n) if n.is_finite() && n.fract() == 0.0)
}

fn str_of(vm: &mut Vm, v: &Value) -> JsResult<String> {
    Ok(vm.to_string(v)?.to_rust_string())
}

/// JS `String(v).toLowerCase()`
fn lower_of(vm: &mut Vm, v: &Value) -> JsResult<String> {
    Ok(str_of(vm, v)?.to_lowercase())
}

fn plain(vm: &mut Vm, name: &str, len: u32, f: NativeFn) -> Value {
    Value::Obj(buffer::plain_function(vm, name, len, f))
}

fn arrow(vm: &mut Vm, name: &str, len: u32, f: NativeFn) -> Value {
    Value::Obj(vm.native_fn(name, len, f))
}

fn require_new(vm: &mut Vm, a: &Args) -> JsResult<Obj> {
    match &a.new_target {
        Some(nt) => Ok(nt.clone()),
        None => vm.throw_type("Class constructor cannot be invoked without 'new'"),
    }
}

/// The object a class constructor initialises (prototype from new.target).
fn instance(vm: &mut Vm, nt: &Obj, fallback: Option<Obj>, kind: ObjKind) -> JsResult<Obj> {
    let fb = fallback.unwrap_or_else(|| vm.intr.object_proto.clone());
    let p = vm.proto_from_nt(&Some(nt.clone()), &fb)?;
    Ok(Obj::new(Some(p), kind))
}

/// Define a class: constructor native + prototype with methods (non-enumerable).
fn make_class(vm: &mut Vm, name: &str, len: u32, ctor: NativeFn, methods: &[(&str, u32, NativeFn)]) -> (Obj, Obj) {
    let proto = vm.new_object();
    let c = vm.native_ctor(name, len, ctor, &proto);
    for (n, l, f) in methods {
        vm.def_method(&proto, n, *l, *f);
    }
    (c, proto)
}

// ============================================================================================
// toBytes / resolveHash
// ============================================================================================

/// `toBytes(data, encoding)`: strings → `Buffer.from(s, enc || "utf8")`; a Uint8Array (or
/// Buffer) itself; other views / ArrayBuffers → a Uint8Array over the same memory; a KeyObject
/// → its secret material. Returns the JS value (kept by reference like the reference does).
fn to_bytes(vm: &mut Vm, data: &Value, enc: &Value) -> JsResult<Value> {
    let compiled = bump(&TOBYTES_CALLS) >= TIER_UP_CALLS;
    if let Value::Str(_) = data {
        let e = if enc.truthy() { enc.clone() } else { Value::str("utf8") };
        let frames = if compiled { vec!["toBytes"] } else { vec![] };
        return with_frames(vm, &frames, |vm| buffer::buffer_from_value(vm, data, &e));
    }
    with_frames(vm, &["toBytes"], |vm| {
        if let Value::Obj(o) = data {
            let u8c = vm.intr.ta_ctors[1].clone();
            // data instanceof Uint8Array → itself (Buffers included)
            if proto_chain_has(o, &vm.intr.ta_protos[1].clone()) {
                return Ok(data.clone());
            }
            // ArrayBuffer.isView(data) → a Uint8Array over the same bytes
            let view = match &o.borrow().kind {
                ObjKind::TypedArray(t) => Some((t.buffer.clone(), t.offset, t.len() * t.kind.size())),
                ObjKind::DataView(d) => Some((d.buffer.clone(), d.offset, 0)),
                _ => None,
            };
            if let Some((ab, off, mut blen)) = view {
                if matches!(o.borrow().kind, ObjKind::DataView(_)) {
                    blen = ta_bytes(o).len();
                }
                return vm.construct(&Value::Obj(u8c), &[Value::Obj(ab), num(off as f64), num(blen as f64)], None);
            }
            // data instanceof ArrayBuffer → new Uint8Array(data)
            if proto_chain_has(o, &vm.intr.array_buffer_proto.clone()) {
                return vm.construct(&Value::Obj(u8c), &[data.clone()], None);
            }
            let ko = st(|s| s.keyobject_ctor.clone());
            if is_instance(vm, data, &ko)? {
                return get(vm, data, "_material");
            }
        }
        vm.throw_type("crypto: data must be a string or BufferSource")
    })
}

/// `toBytes` returning the bytes.
fn to_bytes_vec(vm: &mut Vm, data: &Value, enc: &Value) -> JsResult<Vec<u8>> {
    let v = to_bytes(vm, data, enc)?;
    bytes_checked(vm, &v)
}

/// Bytes of a `toBytes` result; an object that only pretends to be a Uint8Array fails like
/// the reference's `.length` read does.
fn bytes_checked(vm: &mut Vm, v: &Value) -> JsResult<Vec<u8>> {
    if let Value::Obj(o) = v {
        let real = matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::ArrayBuffer(_) | ObjKind::DataView(_));
        if !real && proto_chain_has(o, &vm.intr.typed_array_proto.clone()) {
            return vm.throw_type("TypedArray.prototype accessor called on a non-TypedArray");
        }
    }
    Ok(raw_bytes(v))
}

fn proto_chain_has(o: &Obj, target: &Obj) -> bool {
    let mut cur = o.proto();
    let mut guard = 0;
    while let Some(p) = cur {
        if p.ptr_eq(target) {
            return true;
        }
        guard += 1;
        if guard > 100_000 {
            return false;
        }
        cur = p.proto();
    }
    false
}

fn hash_name(alg: HashAlg) -> &'static str {
    match alg {
        HashAlg::Md5 => "md5",
        HashAlg::Sha1 => "sha1",
        HashAlg::Sha224 => "sha224",
        HashAlg::Sha256 => "sha256",
        HashAlg::Sha384 => "sha384",
        HashAlg::Sha512 => "sha512",
        HashAlg::Sha512_224 => "sha512-224",
        HashAlg::Sha512_256 => "sha512-256",
    }
}

fn alg_by_index(i: usize) -> HashAlg {
    [HashAlg::Md5, HashAlg::Sha1, HashAlg::Sha256, HashAlg::Sha384, HashAlg::Sha512, HashAlg::Sha512_224, HashAlg::Sha512_256][i]
}

fn alg_index(alg: HashAlg) -> usize {
    match alg {
        HashAlg::Md5 => 0,
        HashAlg::Sha1 => 1,
        HashAlg::Sha256 => 2,
        HashAlg::Sha384 => 3,
        HashAlg::Sha512 => 4,
        HashAlg::Sha512_224 => 5,
        HashAlg::Sha512_256 => 6,
        HashAlg::Sha224 => 2,
    }
}

/// The JS digest functions' own padding buffer limit (the reference hashes in JS).
fn digest_limit_ok(alg: HashAlg, n: usize) -> bool {
    match alg {
        HashAlg::Md5 | HashAlg::Sha1 | HashAlg::Sha256 | HashAlg::Sha224 => n + 9 <= MAX_TA_LENGTH,
        HashAlg::Sha384 | HashAlg::Sha512 => n + 17 <= MAX_TA_LENGTH,
        _ => true,
    }
}

/// `_reg.fn(bytes)`: digest of a byte array (returns a Uint8Array).
fn reg_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let alg = alg_by_index(a.slot(0).as_num().unwrap_or(0.0) as usize);
    let bytes = raw_bytes(&a.arg(0));
    if !digest_limit_ok(alg, bytes.len()) {
        return vm.throw_range("Invalid typed array length");
    }
    let d = cr::digest(alg, &bytes);
    Ok(u8array(vm, d))
}

/// The shared registry entry `{ fn, outLen, blockSize }` of a digest.
fn reg_obj(vm: &mut Vm, alg: HashAlg) -> Obj {
    let name = hash_name(alg);
    if let Some(o) = st(|s| s.regs.get(name).cloned()) {
        return o;
    }
    let fname = match alg {
        HashAlg::Sha512_224 | HashAlg::Sha512_256 => "fn",
        _ => name,
    };
    let f = vm.native_closure(fname, 1, reg_fn, vec![num(alg_index(alg) as f64)]);
    let o = vm.new_object();
    o.set_prop(key("fn"), Value::Obj(f), WEC);
    o.set_prop(key("outLen"), num(alg.output_len() as f64), WEC);
    o.set_prop(key("blockSize"), num(alg.block_len() as f64), WEC);
    ST.with(|s| s.borrow_mut().regs.insert(name, o.clone()));
    o
}

/// `resolveHash(name)` (frame `resolveHash`): `String(name).toLowerCase()` in the table.
fn resolve_hash(vm: &mut Vm, name: &Value) -> JsResult<(HashAlg, Obj)> {
    with_frames(vm, &["resolveHash"], |vm| {
        let s = str_of(vm, name)?;
        match cr::hash_alg_from_name(&s) {
            Some(alg) => {
                let r = reg_obj(vm, alg);
                Ok((alg, r))
            }
            None => throw(vm, cr::unsupported_digest_error(&s)),
        }
    })
}

/// The algorithm of a `_reg` object.
fn alg_of_reg(vm: &mut Vm, reg: &Value) -> JsResult<HashAlg> {
    let found = st(|s| {
        for (n, o) in s.regs.iter() {
            if let Value::Obj(r) = reg {
                if r.ptr_eq(o) {
                    return cr::hash_alg_from_name(n);
                }
            }
        }
        None
    });
    match found {
        Some(a) => Ok(a),
        None => vm.throw_type("cannot read property 'fn' of undefined"),
    }
}

/// Concatenate the byte arrays of a `_chunks` array (`new Uint8Array(total)` limit applies).
fn concat_chunks(vm: &mut Vm, chunks: &Value) -> JsResult<Vec<u8>> {
    let items = crate::builtins::array::array_like_to_vec(vm, chunks)?;
    let mut out = Vec::new();
    for c in items {
        let b = bytes_checked(vm, &c)?;
        out.extend(b);
    }
    if out.len() > MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    Ok(out)
}

/// `hmacRaw(reg, key, data)`
fn hmac_raw(vm: &mut Vm, alg: HashAlg, k: &[u8], data: &[u8]) -> JsResult<Vec<u8>> {
    let block = alg.block_len();
    if !digest_limit_ok(alg, block + data.len()) || block + data.len() > MAX_TA_LENGTH {
        return vm.throw_range("Invalid typed array length");
    }
    Ok(cr::hmac(alg, k, data))
}

// ============================================================================================
// Hash / Hmac
// ============================================================================================

fn hash_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["Hash"], |vm| {
        let fb = st(|s| s.hash_proto.clone());
        let o = instance(vm, &nt, fb, ObjKind::Ordinary)?;
        let (_, reg) = resolve_hash(vm, &a.arg(0))?;
        let ov = Value::Obj(o.clone());
        set(vm, &ov, "_reg", Value::Obj(reg))?;
        let chunks = vm.new_array(Vec::new());
        set(vm, &ov, "_chunks", Value::Obj(chunks))?;
        set(vm, &ov, "_used", Value::Bool(false))?;
        Ok(ov)
    })
}

/// `update(data, encoding) { this._chunks.push(toBytes(data, encoding)); return this; }`
fn hash_update(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["update"], |vm| {
        let chunks = get(vm, &a.this, "_chunks")?;
        let b = to_bytes(vm, &a.arg(0), &a.arg(1))?;
        call_member(vm, &chunks, "push", &[b])?;
        Ok(a.this.clone())
    })
}

fn hash_bytes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["_bytes"], |vm| {
        let chunks = get(vm, &a.this, "_chunks")?;
        let b = concat_chunks(vm, &chunks)?;
        Ok(u8array(vm, b))
    })
}

fn hash_digest(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let calls = bump(&DIGEST_CALLS);
    let this = a.this.clone();
    let digest = with_frames(vm, &["digest"], |vm| {
        if get(vm, &this, "_used")?.truthy() {
            return vm.throw_error("Error", "Digest already called");
        }
        set(vm, &this, "_used", Value::Bool(true))?;
        let reg = get(vm, &this, "_reg")?;
        let bytes = call_member(vm, &this, "_bytes", &[])?;
        let f = get(vm, &reg, "fn")?;
        let d = vm.call(&f, reg.clone(), &[bytes])?;
        new_buf(vm, raw_bytes(&d))
    })?;
    // `return encoding && encoding !== "buffer" ? digest.toString(encoding) : digest`
    let frames = tail(calls, "digest");
    with_frames(vm, &frames, |vm| maybe_encode(vm, digest, &a.arg(0)))
}

fn hash_copy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["copy"], |vm| {
        let ctor = st(|s| s.hash_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        let h = vm.construct(&ctor, &[Value::str("md5")], None)?;
        let reg = get(vm, &a.this, "_reg")?;
        set(vm, &h, "_reg", reg)?;
        let chunks = get(vm, &a.this, "_chunks")?;
        let copy = call_member(vm, &chunks, "slice", &[])?;
        set(vm, &h, "_chunks", copy)?;
        Ok(h)
    })
}

fn hmac_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["Hmac"], |vm| {
        let fb = st(|s| s.hmac_ctor.clone()).and_then(|c| c.get_own_str("prototype")).and_then(|p| p.as_obj().cloned());
        let o = instance(vm, &nt, fb, ObjKind::Ordinary)?;
        let ov = Value::Obj(o);
        let (_, reg) = resolve_hash(vm, &a.arg(0))?;
        set(vm, &ov, "_reg", Value::Obj(reg))?;
        let k = a.arg(1);
        let ko = st(|s| s.keyobject_ctor.clone());
        let kb = if is_instance(vm, &k, &ko)? { get(vm, &k, "_material")? } else { to_bytes(vm, &k, &Value::Undefined)? };
        set(vm, &ov, "_key", kb)?;
        let chunks = vm.new_array(Vec::new());
        set(vm, &ov, "_chunks", Value::Obj(chunks))?;
        set(vm, &ov, "_used", Value::Bool(false))?;
        Ok(ov)
    })
}

fn hmac_digest(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    // Hmac#digest has a loop, so the reference runs it compiled: no tail-call elimination
    let this = a.this.clone();
    with_frames(vm, &["digest"], |vm| {
        if get(vm, &this, "_used")?.truthy() {
            return vm.throw_error("Error", "Digest already called");
        }
        set(vm, &this, "_used", Value::Bool(true))?;
        let chunks = get(vm, &this, "_chunks")?;
        let all = concat_chunks(vm, &chunks)?;
        let reg = get(vm, &this, "_reg")?;
        let alg = alg_of_reg(vm, &reg)?;
        let k = get(vm, &this, "_key")?;
        let kb = raw_bytes(&k);
        let d = with_frames(vm, &["hmacRaw"], |vm| hmac_raw(vm, alg, &kb, &all))?;
        let digest = new_buf(vm, d)?;
        maybe_encode(vm, digest, &a.arg(0))
    })
}

/// `createHash(algorithm)` = `new Hash(algorithm)` (options ignored)
fn create_hash(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createHash"], |vm| {
        let c = st(|s| s.hash_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        vm.construct(&c, &[a.arg(0)], None)
    })
}

fn create_hmac(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createHmac"], |vm| {
        let c = st(|s| s.hmac_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        vm.construct(&c, &[a.arg(0), a.arg(1)], None)
    })
}

/// `hash(algorithm, data, outputEncoding = "hex")`
fn crypto_hash(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (h, enc) = with_frames(vm, &["hash"], |vm| {
        let enc = if a.arg(2).is_undefined() { Value::str("hex") } else { a.arg(2) };
        let c = st(|s| s.hash_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        let h = vm.construct(&c, &[a.arg(0)], None)?;
        call_member(vm, &h, "update", &[a.arg(1)])?;
        Ok((h, enc))
    })?;
    // `return enc === "buffer" ? h.digest() : h.digest(enc)` (tail call)
    if matches!(&enc, Value::Str(s) if s.eq_str("buffer")) {
        call_member(vm, &h, "digest", &[])
    } else {
        call_member(vm, &h, "digest", &[enc])
    }
}

fn get_hashes(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let v: Vec<Value> = cr::HASH_NAMES.iter().map(|n| Value::str(n)).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

// ============================================================================================
// KDFs
// ============================================================================================

/// `Math.ceil(a / b)` with JS conversions of `a`.
fn js_ceil_div(vm: &mut Vm, a: &Value, b: f64) -> JsResult<f64> {
    let n = vm.to_numeric(a)?;
    match n {
        Value::Num(x) => Ok((x / b).ceil()),
        _ => vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
    }
}

/// Number of iterations of `for (let j = 1; j < iterations; j++)` plus one.
fn iteration_count(vm: &mut Vm, it: &Value) -> JsResult<u64> {
    let p = vm.to_primitive(it, crate::ops::Hint::Number)?;
    let n = match &p {
        Value::BigInt(b) => b.to_f64(),
        Value::Str(_) => vm.to_number(&p)?,
        other => vm.to_number(other)?,
    };
    if n.is_nan() || n <= 1.0 {
        return Ok(1);
    }
    Ok(n.ceil().min(u32::MAX as f64) as u64)
}

/// `pbkdf2Sync` body (frame `pbkdf2Sync` is pushed by the caller).
fn pbkdf2_impl(vm: &mut Vm, password: &Value, salt: &Value, iterations: &Value, keylen: &Value, digest: &Value) -> JsResult<Value> {
    if digest.is_undefined() {
        return vm.throw_type("The \"digest\" argument is required");
    }
    let (alg, _) = resolve_hash(vm, digest)?;
    let pw = to_bytes_vec(vm, password, &Value::Undefined)?;
    let salt_b = to_bytes_vec(vm, salt, &Value::Undefined)?;
    let hlen = alg.output_len();
    let blocks = js_ceil_div(vm, keylen, hlen as f64)?;
    let total = blocks * hlen as f64;
    let out = buffer::buffer_alloc_value(vm, &num(if total == 0.0 { 0.0 } else { total }))?;
    let out_len = ta_bytes(&out).len();
    let iters = if out_len > 0 { iteration_count(vm, iterations)? } else { 1 };
    if out_len > 0 {
        let dk = match cr::try_pbkdf2(alg, &pw, &salt_b, iters as u32, out_len) {
            Ok(d) => d,
            Err(e) => return throw(vm, e),
        };
        buffer::write_bytes(&out, 0, &dk);
    }
    // out.subarray(0, keylen)
    call_member(vm, &Value::Obj(out), "subarray", &[num(0.0), keylen.clone()])
}

fn pbkdf2_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["pbkdf2Sync"], |vm| pbkdf2_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3), &a.arg(4)))
}

fn pbkdf2_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["pbkdf2"], |vm| {
        let (mut digest, mut cb) = (a.arg(4), a.arg(5));
        if digest.is_callable() {
            cb = digest;
            digest = Value::Undefined;
        }
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["pbkdf2Sync"], |vm| pbkdf2_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3), &digest));
        defer_cb(vm, &cb, r.map(|v| vec![v]));
        Ok(Value::Undefined)
    })
}

fn hkdf_impl(vm: &mut Vm, digest: &Value, ikm: &Value, salt: &Value, info: &Value, keylen: &Value) -> JsResult<Value> {
    let (alg, _) = resolve_hash(vm, digest)?;
    let ikm_b = to_bytes_vec(vm, ikm, &Value::Undefined)?;
    let salt_b = to_bytes_vec(vm, salt, &Value::Undefined)?;
    let info_b = to_bytes_vec(vm, info, &Value::Undefined)?;
    let hlen = alg.output_len();
    let salt_final = if salt_b.is_empty() { vec![0u8; hlen] } else { salt_b };
    let prk = cr::hmac(alg, &salt_final, &ikm_b);
    let n = js_ceil_div(vm, keylen, hlen as f64)?;
    if n > 255.0 {
        return vm.throw_range("hkdf: requested key length is too large");
    }
    let total = n * hlen as f64;
    let size = if total.is_nan() { 0.0 } else { total };
    if size < 0.0 && size != 0.0 {
        return vm.throw_range("index out of range");
    }
    let nn = if n.is_nan() || n <= 0.0 { 0 } else { n as usize };
    let mut okm = Vec::with_capacity(nn * hlen);
    let mut prev: Vec<u8> = Vec::new();
    for i in 1..=nn {
        let mut input = prev.clone();
        input.extend_from_slice(&info_b);
        input.push(i as u8);
        prev = cr::hmac(alg, &prk, &input);
        okm.extend_from_slice(&prev);
    }
    // okm.slice(0, keylen).buffer
    let len = okm.len();
    let end = if keylen.is_undefined() {
        len
    } else {
        let k = vm.to_integer_or_infinity(keylen)?;
        if k < 0.0 {
            (len as f64 + k).max(0.0) as usize
        } else {
            k.min(len as f64) as usize
        }
    };
    okm.truncate(end);
    Ok(array_buffer(vm, okm))
}

fn hkdf_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["hkdfSync"], |vm| hkdf_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3), &a.arg(4)))
}

fn hkdf_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["hkdf"], |vm| {
        let cb = a.arg(5);
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["hkdfSync"], |vm| hkdf_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3), &a.arg(4)));
        defer_cb(vm, &cb, r.map(|v| vec![v]));
        Ok(Value::Undefined)
    })
}

/// Node-style `Received ...` description used by the scrypt validators.
fn received(vm: &mut Vm, v: &Value) -> String {
    let t = buffer::typeof_name(v);
    let s = match v {
        Value::Str(s) => format!("'{}'", s),
        Value::Sym(sym) => sym.descriptive_string(),
        Value::BigInt(b) => b.to_string_radix(10),
        other => match vm.to_string(other) {
            Ok(s) => s.to_rust_string(),
            Err(_) => String::new(),
        },
    };
    format!("type {} ({})", t, s)
}

/// `validateScryptNum(name, value, max)` (frame `validateScryptNum`).
fn validate_scrypt_num(vm: &mut Vm, name: &str, v: &Value, max: f64) -> JsResult<f64> {
    with_frames(vm, &["validateScryptNum"], |vm| {
        let n = match v {
            Value::Num(n) => *n,
            other => {
                let r = received(vm, other);
                return Err(coded(vm, "TypeError", &format!("The \"{}\" argument must be of type number. Received {}", name, r), "ERR_INVALID_ARG_TYPE"));
            }
        };
        if !(n.is_finite() && n.fract() == 0.0) {
            let s = crate::numconv::number_to_string(n);
            return Err(coded(vm, "RangeError", &format!("The value of \"{}\" is out of range. It must be an integer. Received {}", name, s), "ERR_OUT_OF_RANGE"));
        }
        if n < 0.0 || n > max {
            let s = crate::numconv::number_to_string(n);
            let m = crate::numconv::number_to_string(max);
            return Err(coded(vm, "RangeError", &format!("The value of \"{}\" is out of range. It must be >= 0 && <= {}. Received {}", name, m, s), "ERR_OUT_OF_RANGE"));
        }
        Ok(n)
    })
}

fn scrypt_impl(vm: &mut Vm, password: &Value, salt: &Value, keylen: &Value, options: &Value) -> JsResult<Value> {
    validate_scrypt_num(vm, "keylen", keylen, 2147483647.0)?;
    let opts = if options.truthy() { options.clone() } else { Value::Obj(vm.new_object()) };
    let pick = |vm: &mut Vm, primary: &str, alias: &str| -> JsResult<f64> {
        with_frames(vm, &["pickOpt"], |vm| {
            let p = get(vm, &opts, primary)?;
            let al = get(vm, &opts, alias)?;
            if !p.is_undefined() && !al.is_undefined() {
                return Err(coded(vm, "Error", "Invalid scrypt parameter", "ERR_CRYPTO_SCRYPT_INVALID_PARAMETER"));
            }
            let (name, v) = if !p.is_undefined() { (primary, p) } else { (alias, al) };
            if v.is_undefined() {
                return Ok(0.0);
            }
            validate_scrypt_num(vm, name, &v, 4294967295.0)
        })
    };
    let n = pick(vm, "N", "cost")?;
    let n = if n == 0.0 { 16384.0 } else { n };
    let r = pick(vm, "r", "blockSize")?;
    let r = if r == 0.0 { 8.0 } else { r };
    let p = pick(vm, "p", "parallelization")?;
    let p = if p == 0.0 { 1.0 } else { p };
    let mut maxmem = 32.0 * 1024.0 * 1024.0;
    let mm = get(vm, &opts, "maxmem")?;
    if !mm.is_undefined() {
        let v = validate_scrypt_num(vm, "maxmem", &mm, 9007199254740991.0)?;
        if v != 0.0 {
            maxmem = v;
        }
    }
    let ni = n as u64;
    if n < 2.0 || (ni & (ni - 1)) != 0 {
        return Err(coded(vm, "RangeError", "Invalid scrypt params", "ERR_CRYPTO_INVALID_SCRYPT_PARAMS"));
    }
    if 128.0 * r * p + 128.0 * r * (n + 2.0) > maxmem {
        return Err(coded(
            vm,
            "RangeError",
            "Invalid scrypt params: error:030000AC:digital envelope routines::memory limit exceeded",
            "ERR_CRYPTO_INVALID_SCRYPT_PARAMS",
        ));
    }
    let blen = 128.0 * r * p;
    let b = with_frames(vm, &["pbkdf2Sync"], |vm| pbkdf2_impl(vm, password, salt, &num(1.0), &num(blen), &Value::str("sha256")))?;
    let mut bb = raw_bytes(&b);
    if let Err(e) = cr::scrypt_romix(&mut bb, ni, r as u32) {
        return throw(vm, e);
    }
    let mixed = u8array(vm, bb);
    let out = with_frames(vm, &["pbkdf2Sync"], |vm| pbkdf2_impl(vm, password, &mixed, &num(1.0), keylen, &Value::str("sha256")))?;
    let bytes = raw_bytes(&out);
    new_buf(vm, bytes)
}

fn scrypt_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["scryptSync"], |vm| scrypt_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3)))
}

fn scrypt_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["scrypt"], |vm| {
        let (mut options, mut cb) = (a.arg(3), a.arg(4));
        if options.is_callable() {
            cb = options;
            options = Value::Undefined;
        }
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["scryptSync"], |vm| scrypt_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2), &options));
        defer_cb(vm, &cb, r.map(|v| vec![v]));
        Ok(Value::Undefined)
    })
}

/// `argon2Parameters(algorithm, parameters, prefix)` → (variant, params bytes, numbers)
struct Argon2Args {
    variant: cr::Argon2Variant,
    message: Vec<u8>,
    nonce: Vec<u8>,
    secret: Vec<u8>,
    ad: Vec<u8>,
    parallelism: u32,
    tag_length: u32,
    memory: u32,
    passes: u32,
}

fn argon2_parameters(vm: &mut Vm, algorithm: &Value, params: &Value, prefix: &str) -> JsResult<Argon2Args> {
    with_frames(vm, &["argon2Parameters"], |vm| {
        let variant = match algorithm {
            Value::Str(s) => cr::Argon2Variant::from_name(&s.to_rust_string()).filter(|_| matches!(s.to_rust_string().as_str(), "argon2d" | "argon2i" | "argon2id")),
            _ => None,
        };
        let variant = match variant {
            Some(v) => v,
            None => return vm.throw_type(format!("{}: algorithm must be 'argon2d', 'argon2i', or 'argon2id'", prefix)),
        };
        if !matches!(params, Value::Obj(_)) {
            return vm.throw_type(format!("{}: parameters must be an object", prefix));
        }
        let mut vals = Vec::new();
        for name in ["message", "nonce", "parallelism", "tagLength", "memory", "passes"] {
            let v = get(vm, params, name)?;
            if v.is_undefined() {
                return vm.throw_type(format!("{}: parameters.{} is required", prefix, name));
            }
            vals.push(v);
        }
        let message = to_bytes_vec(vm, &vals[0], &Value::Undefined)?;
        let nonce = to_bytes_vec(vm, &vals[1], &Value::Undefined)?;
        let check = |vm: &mut Vm, name: &str, v: &Value, min: f64, max: f64| -> JsResult<u32> {
            match v {
                Value::Num(n) if n.is_finite() && n.fract() == 0.0 && *n >= min && *n <= max => Ok(*n as u32),
                _ => vm.throw_range(format!(
                    "{}: parameters.{} must be an integer between {} and {}",
                    prefix,
                    name,
                    crate::numconv::number_to_string(min),
                    crate::numconv::number_to_string(max)
                )),
            }
        };
        let parallelism = check(vm, "parallelism", &vals[2], 1.0, 16777215.0)?;
        let tag_length = check(vm, "tagLength", &vals[3], 4.0, 4294967295.0)?;
        let memory = check(vm, "memory", &vals[4], 8.0 * parallelism as f64, 4294967295.0)?;
        let passes = check(vm, "passes", &vals[5], 1.0, 4294967295.0)?;
        if nonce.len() < 8 {
            return vm.throw_range(format!("{}: parameters.nonce must be at least 8 bytes", prefix));
        }
        let s = get(vm, params, "secret")?;
        let secret = if s.is_undefined() { Vec::new() } else { to_bytes_vec(vm, &s, &Value::Undefined)? };
        let ad_v = get(vm, params, "associatedData")?;
        let ad = if ad_v.is_undefined() { Vec::new() } else { to_bytes_vec(vm, &ad_v, &Value::Undefined)? };
        Ok(Argon2Args { variant, message, nonce, secret, ad, parallelism, tag_length, memory, passes })
    })
}

fn run_argon2(vm: &mut Vm, p: &Argon2Args) -> JsResult<Vec<u8>> {
    let params = cr::Argon2Params {
        message: &p.message,
        nonce: &p.nonce,
        secret: &p.secret,
        associated_data: &p.ad,
        parallelism: p.parallelism,
        tag_length: p.tag_length,
        memory: p.memory,
        passes: p.passes,
        version: 0x13,
    };
    match cr::argon2(p.variant, &params) {
        Ok(o) => Ok(o),
        Err(e) => throw(vm, e),
    }
}

fn argon2_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["argon2Sync"], |vm| {
        let p = argon2_parameters(vm, &a.arg(0), &a.arg(1), "crypto.argon2Sync")?;
        let out = run_argon2(vm, &p)?;
        new_buf(vm, out)
    })
}

fn argon2_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["argon2"], |vm| {
        let cb = a.arg(2);
        if !cb.is_callable() {
            return vm.throw_type("crypto.argon2: callback must be a function");
        }
        let p = argon2_parameters(vm, &a.arg(0), &a.arg(1), "crypto.argon2")?;
        // the reference hashes on a worker and calls back from the event loop
        let r = run_argon2(vm, &p);
        let args = match r {
            Ok(out) => vec![Value::Null, new_buf(vm, out)?],
            Err(e) => vec![e],
        };
        crate::runtime::timers::add_timer(vm, cb, 0.0, args, false);
        Ok(Value::Undefined)
    })
}

// ============================================================================================
// random
// ============================================================================================

fn fill_value(v: &Value) {
    if let Value::Obj(o) = v {
        let mut bytes = ta_bytes(o);
        cr::fill_random(&mut bytes);
        let b = o.borrow();
        match &b.kind {
            ObjKind::TypedArray(t) => {
                let mut bb = t.buf.borrow_mut();
                let off = t.offset;
                bb.bytes[off..off + bytes.len()].copy_from_slice(&bytes);
            }
            ObjKind::ArrayBuffer(ab) => {
                let mut bb = ab.borrow_mut();
                let n = bytes.len().min(bb.bytes.len());
                bb.bytes[..n].copy_from_slice(&bytes[..n]);
            }
            _ => {}
        }
    }
}

/// `randomBytes(size)` body: `Buffer.alloc(size)` filled with random bytes.
fn random_buffer(vm: &mut Vm, size: &Value) -> JsResult<Value> {
    let b = buffer::buffer_alloc_value(vm, size)?;
    let v = Value::Obj(b);
    fill_value(&v);
    Ok(v)
}

fn random_bytes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["randomBytes"], |vm| {
        let buf = random_buffer(vm, &a.arg(0))?;
        let cb = a.arg(1);
        if cb.truthy() {
            defer_random_bytes_cb(vm, &cb, buf);
            return Ok(Value::Undefined);
        }
        Ok(buf)
    })
}

fn random_fill_impl(vm: &mut Vm, buf: &Value, offset: &Value, size: &Value) -> JsResult<Value> {
    let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
    let view = match buf {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_)) => {
            let ab = get(vm, buf, "buffer")?;
            let off = get(vm, buf, "byteOffset")?;
            let bl = get(vm, buf, "byteLength")?;
            vm.construct(&u8c, &[ab, off, bl], None)?
        }
        _ => vm.construct(&u8c, &[buf.clone()], None)?,
    };
    let off = if offset.is_undefined() { num(0.0) } else { offset.clone() };
    let sz = if size.is_undefined() {
        let l = get(vm, &view, "length")?;
        vm.op_arith(crate::bytecode::Op::Sub, &l, &off)?
    } else {
        size.clone()
    };
    let rnd = with_frames(vm, &["randomBytes"], |vm| random_buffer(vm, &sz))?;
    let rb = raw_bytes(&rnd);
    // view.set(rnd, off)
    let len = ta_bytes(view.as_obj().unwrap()).len();
    let o = vm.to_integer_or_infinity(&off)?;
    if o < 0.0 {
        return vm.throw_range("TypedArray.prototype.set offset is negative");
    }
    if o + rb.len() as f64 > len as f64 {
        return vm.throw_range("source is too large for the target at offset");
    }
    if let Value::Obj(vo) = &view {
        buffer::write_bytes(vo, o as usize, &rb);
    }
    Ok(buf.clone())
}

fn random_fill_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["randomFillSync"], |vm| random_fill_impl(vm, &a.arg(0), &a.arg(1), &a.arg(2)))
}

fn random_fill(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["randomFill"], |vm| {
        let buf = a.arg(0);
        let (mut offset, mut size, mut cb) = (a.arg(1), a.arg(2), a.arg(3));
        if offset.is_callable() {
            cb = offset;
            offset = Value::Undefined;
            size = Value::Undefined;
        } else if size.is_callable() {
            cb = size;
            size = Value::Undefined;
        }
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["randomFillSync"], |vm| random_fill_impl(vm, &buf, &offset, &size));
        let res = r.map(|_| vec![buf.clone()]);
        defer_cb(vm, &cb, res);
        Ok(Value::Undefined)
    })
}

fn is_safe_integer(v: &Value) -> Option<i64> {
    match v {
        Value::Num(n) if n.is_finite() && n.fract() == 0.0 && n.abs() <= 9007199254740991.0 => Some(*n as i64),
        _ => None,
    }
}

fn random_int(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["randomInt"], |vm| {
        let mut args: Vec<Value> = a.args.to_vec();
        let mut cb = Value::Undefined;
        if args.last().map_or(false, |v| v.is_callable()) {
            cb = args.pop().unwrap();
        }
        let (min, max) = if args.len() == 1 { (num(0.0), args[0].clone()) } else { (args.first().cloned().unwrap_or(Value::Undefined), args.get(1).cloned().unwrap_or(Value::Undefined)) };
        let (mn, mx) = match (is_safe_integer(&min), is_safe_integer(&max)) {
            (Some(a), Some(b)) => (a, b),
            _ => return vm.throw_range("randomInt: min and max must be safe integers"),
        };
        if mx - mn <= 0 {
            return vm.throw_range("The value of \"max\" is out of range. It must be greater than the value of \"min\".");
        }
        let v = cr::random_int(mn, mx).unwrap_or(mn);
        if cb.truthy() {
            defer_cb(vm, &cb, Ok(vec![num(v as f64)]));
            return Ok(Value::Undefined);
        }
        Ok(num(v as f64))
    })
}

fn random_uuid(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    // `() => webCrypto.randomUUID()` (tail call)
    let frames = tail(bump(&UUID_CALLS), "randomUUID");
    with_frames(vm, &frames, |vm| {
        let wc = st(|s| s.webcrypto.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        call_member(vm, &wc, "randomUUID", &[])
    })
}

fn get_random_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let frames = tail(bump(&GRV_CALLS), "getRandomValues");
    with_frames(vm, &frames, |vm| {
        let wc = st(|s| s.webcrypto.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        call_member(vm, &wc, "getRandomValues", &[a.arg(0)])
    })
}

fn timing_safe_equal(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["timingSafeEqual"], |vm| {
        let x = to_bytes_vec(vm, &a.arg(0), &Value::Undefined)?;
        let y = to_bytes_vec(vm, &a.arg(1), &Value::Undefined)?;
        if x.len() != y.len() {
            return vm.throw_range("Input buffers must have the same byte length");
        }
        Ok(Value::Bool(cr::timing_safe_eq(&x, &y)))
    })
}

// ============================================================================================
// WebCrypto
// ============================================================================================

fn wc_get_random_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["getRandomValues"], |vm| {
        let view = a.arg(0);
        let ok = matches!(
            ta_kind(&view),
            Some(TAKind::Int8 | TAKind::Uint8 | TAKind::Uint8C | TAKind::Int16 | TAKind::Uint16 | TAKind::Int32 | TAKind::Uint32 | TAKind::BigInt64 | TAKind::BigUint64)
        );
        if !ok {
            return vm.throw_type("getRandomValues expects an integer typed array");
        }
        if raw_bytes(&view).len() > 65536 {
            let e = dom_exception(vm, "getRandomValues: quota (65536 bytes) exceeded", "QuotaExceededError");
            return Err(e);
        }
        fill_value(&view);
        Ok(view)
    })
}

fn wc_random_uuid(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let _ = vm;
    Ok(Value::str(&cr::random_uuid()))
}

fn wc_subtle(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(st(|s| s.subtle.clone()).map(Value::Obj).unwrap_or(Value::Undefined))
}

fn empty_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    let fb = vm.get_str(a.callee, "prototype")?.as_obj().cloned();
    Ok(Value::Obj(instance(vm, &nt, fb, ObjKind::Ordinary)?))
}

/// `async digest(algorithm, data)`: SHA-256 only.
fn subtle_digest(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let r = with_frames(vm, &["digest"], |vm| -> JsResult<Value> {
        let algorithm = a.arg(0);
        let name = match &algorithm {
            Value::Str(_) => algorithm.clone(),
            v if v.truthy() => get(vm, v, "name")?,
            v => v.clone(),
        };
        let name = if name.truthy() { name } else { Value::str("") };
        let s = vm.to_string(&name)?.to_rust_string();
        if s.to_uppercase() != "SHA-256" {
            return Err(dom_exception(vm, &format!("unsupported digest algorithm '{}' (SHA-256 only for now)", s), "NotSupportedError"));
        }
        let data = a.arg(1);
        let ok = matches!(&data, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::ArrayBuffer(_) | ObjKind::TypedArray(_) | ObjKind::DataView(_)));
        if !ok {
            return vm.throw_type("digest expects a BufferSource");
        }
        let d = cr::digest(HashAlg::Sha256, &raw_bytes(&data));
        Ok(array_buffer(vm, d))
    });
    match r {
        Ok(v) => vm.call(&cap.resolve, Value::Undefined, &[v])?,
        Err(e) => vm.call(&cap.reject, Value::Undefined, &[e])?,
    };
    Ok(cap.promise)
}

/// Global WebCrypto: `crypto`, `Crypto`, `SubtleCrypto`, `CryptoKey`.
pub fn setup(vm: &mut Vm) {
    let (crypto_c, cp) = make_class(vm, "Crypto", 0, empty_ctor, &[("getRandomValues", 1, wc_get_random_values), ("randomUUID", 0, wc_random_uuid)]);
    vm.def_getter(&cp, "subtle", wc_subtle);
    let (subtle_c, sp) = make_class(vm, "SubtleCrypto", 0, empty_ctor, &[]);
    vm.def_method(&sp, "digest", 2, subtle_digest);
    let (key_c, _kp) = make_class(vm, "CryptoKey", 0, empty_ctor, &[]);
    let subtle = Obj::new(Some(sp), ObjKind::Ordinary);
    let wc = Obj::new(Some(cp), ObjKind::Ordinary);
    ST.with(|s| {
        let mut s = s.borrow_mut();
        s.webcrypto = Some(wc.clone());
        s.subtle = Some(subtle);
    });
    // the reference's global key order: Crypto, SubtleCrypto, crypto, CryptoKey
    let g = vm.global.clone();
    g.set_prop(key("Crypto"), Value::Obj(crypto_c), WEC);
    g.set_prop(key("SubtleCrypto"), Value::Obj(subtle_c), WEC);
    g.set_prop(key("crypto"), Value::Obj(wc), WEC);
    g.set_prop(key("CryptoKey"), Value::Obj(key_c), WEC);
}

// ============================================================================================
// KeyObject (secret keys) and key generation
// ============================================================================================

/// Native state behind an asymmetric KeyObject.
struct AsymState {
    key: cr::keys::AsymKey,
}

fn keyobject_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["KeyObject"], |vm| {
        let fb = st(|s| s.keyobject_proto.clone());
        let o = instance(vm, &nt, fb, ObjKind::Ordinary)?;
        let ov = Value::Obj(o);
        set(vm, &ov, "_type", a.arg(0))?;
        set(vm, &ov, "_material", a.arg(1))?;
        set(vm, &ov, "_asym", Value::Null)?;
        Ok(ov)
    })
}

/// `new KeyObject("secret", material)`
fn new_secret_key(vm: &mut Vm, bytes: Vec<u8>) -> JsResult<Value> {
    let c = st(|s| s.keyobject_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
    let m = u8array(vm, bytes);
    vm.construct(&c, &[Value::str("secret"), m], None)
}

/// The native asymmetric key of a KeyObject value (None for secret keys / other values).
fn asym_of(v: &Value) -> Option<cr::keys::AsymKey> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<AsymState>().map(|s| s.key.clone()),
            _ => None,
        },
        _ => None,
    }
}

fn ko_type(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get(vm, &a.this, "_type")
}

fn ko_symmetric_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = get(vm, &a.this, "_type")?;
    if matches!(&t, Value::Str(s) if s.eq_str("secret")) {
        let m = get(vm, &a.this, "_material")?;
        return get(vm, &m, "length");
    }
    Ok(Value::Undefined)
}

fn ko_asym_type(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let asym = get(vm, &a.this, "_asym")?;
    if asym.truthy() {
        return get(vm, &asym, "kind");
    }
    Ok(Value::Undefined)
}

fn ko_asym_details(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let asym = get(vm, &a.this, "_asym")?;
    if !asym.truthy() {
        return Ok(Value::Undefined);
    }
    asym_details(vm, &a.this)
}

fn ko_export(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["export"], |vm| {
        let t = get(vm, &a.this, "_type")?;
        let opts = a.arg(0);
        if !matches!(&t, Value::Str(s) if s.eq_str("secret")) {
            return export_asymmetric(vm, &a.this, &opts);
        }
        let m = get(vm, &a.this, "_material")?;
        if opts.truthy() {
            let f = get(vm, &opts, "format")?;
            if matches!(&f, Value::Str(s) if s.eq_str("jwk")) {
                let b = raw_bytes(&m);
                let k = crate::runtime::encoding::base64_encode(&b, true);
                let k = k.trim_end_matches('=');
                let o = vm.new_object();
                o.set_prop(key("kty"), Value::str("oct"), WEC);
                o.set_prop(key("k"), Value::str(k), WEC);
                return Ok(Value::Obj(o));
            }
        }
        let b = raw_bytes(&m);
        new_buf(vm, b)
    })
}

fn ko_equals(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["equals"], |vm| {
        let other = a.arg(0);
        let ko = st(|s| s.keyobject_ctor.clone());
        if !is_instance(vm, &other, &ko)? {
            return Ok(Value::Bool(false));
        }
        let t1 = get(vm, &a.this, "_type")?;
        let t2 = get(vm, &other, "_type")?;
        if !Value::strict_eq(&t1, &t2) {
            return Ok(Value::Bool(false));
        }
        if !matches!(&t1, Value::Str(s) if s.eq_str("secret")) {
            let (x, y) = (asym_of(&a.this), asym_of(&other));
            let private = matches!(&t1, Value::Str(s) if s.eq_str("private"));
            let enc = |k: &cr::keys::AsymKey| -> Option<Vec<u8>> {
                if private {
                    k.export_pkcs8().ok()
                } else {
                    Some(k.export_spki())
                }
            };
            return Ok(Value::Bool(match (x, y) {
                (Some(x), Some(y)) => enc(&x) == enc(&y),
                _ => false,
            }));
        }
        let m1 = get(vm, &a.this, "_material")?;
        let m2 = get(vm, &other, "_material")?;
        let (b1, b2) = (raw_bytes(&m1), raw_bytes(&m2));
        if b1.len() != b2.len() {
            return Ok(Value::Bool(false));
        }
        Ok(Value::Bool(cr::timing_safe_eq(&b1, &b2)))
    })
}

fn create_secret_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createSecretKey"], |vm| {
        let k = a.arg(0);
        let bytes = if let Value::Str(_) = k {
            let enc = if a.arg(1).truthy() { a.arg(1) } else { Value::str("utf8") };
            let b = buffer::buffer_from_value(vm, &k, &enc)?;
            raw_bytes(&b)
        } else {
            to_bytes_vec(vm, &k, &Value::Undefined)?
        };
        new_secret_key(vm, bytes)
    })
}

fn generate_key_impl(vm: &mut Vm, ty: &Value, options: &Value) -> JsResult<Value> {
    let t = lower_of(vm, ty)?;
    if t != "hmac" && t != "aes" {
        let s = str_of(vm, ty)?;
        return vm.throw_error("Error", format!("Unsupported key type '{}' in lumen (secret 'hmac'/'aes' only)", s));
    }
    let length = if options.truthy() { get(vm, options, "length")? } else { options.clone() };
    if !is_integer(&length) {
        return vm.throw_type("options.length must be an integer number of bits");
    }
    let bits = length.as_num().unwrap_or(0.0);
    if bits % 8.0 != 0.0 {
        return vm.throw_range("options.length must be a multiple of 8");
    }
    let b = with_frames(vm, &["randomBytes"], |vm| random_buffer(vm, &num(bits / 8.0)))?;
    new_secret_key(vm, raw_bytes(&b))
}

fn generate_key_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["generateKeySync"], |vm| generate_key_impl(vm, &a.arg(0), &a.arg(1)))
}

fn generate_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["generateKey"], |vm| {
        let cb = a.arg(2);
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["generateKeySync"], |vm| generate_key_impl(vm, &a.arg(0), &a.arg(1)));
        defer_cb(vm, &cb, r.map(|v| vec![v]));
        Ok(Value::Undefined)
    })
}

// ============================================================================================
// ciphers
// ============================================================================================

struct CipherState {
    ctx: RefCell<cr::CipherCtx>,
}

fn cipher_info_obj(vm: &mut Vm, info: &cr::CipherInfo) -> Value {
    let o = vm.new_object();
    o.set_prop(key("mode"), Value::str(info.mode.as_str()), WEC);
    o.set_prop(key("name"), Value::str(info.info_name), WEC);
    o.set_prop(key("nid"), num(info.nid as f64), WEC);
    o.set_prop(key("blockSize"), num(info.block_size as f64), WEC);
    if let Some(iv) = info.iv_len {
        o.set_prop(key("ivLength"), num(iv as f64), WEC);
    }
    o.set_prop(key("keyLength"), num(info.key_len as f64), WEC);
    Value::Obj(o)
}

/// `initCipher(this, algorithm, key, iv, options, decipher)`
fn init_cipher(vm: &mut Vm, nt: &Obj, a: &Args, decipher: bool) -> JsResult<Value> {
    with_frames(vm, &["initCipher"], |vm| {
        let name = str_of(vm, &a.arg(0))?;
        let info = match cr::cipher_info(&name) {
            Some(i) => i,
            None => return throw(vm, cr::cipher::unsupported_cipher_error(&name)),
        };
        let kv = to_bytes(vm, &a.arg(1), &Value::Undefined)?;
        let kb = raw_bytes(&kv);
        if kb.len() != info.key_len {
            return throw(vm, cr::cipher::invalid_key_length_error());
        }
        let ivv = a.arg(2);
        let ivb = if ivv.is_nullish() { None } else { Some(to_bytes_vec(vm, &ivv, &Value::Undefined)?) };
        let mut ctx = match cr::CipherCtx::with_info(info, &kb, ivb.as_deref(), decipher) {
            Ok(c) => c,
            Err(e) => return throw(vm, e),
        };
        let gcm = info.mode == cr::CipherMode::Gcm;
        let mut tag_explicit = false;
        let mut tag_len = 16.0;
        if gcm {
            let opts = a.arg(3);
            if opts.truthy() {
                let tl = get(vm, &opts, "authTagLength")?;
                if !tl.is_undefined() {
                    let ok = matches!(&tl, Value::Num(n) if n.fract() == 0.0 && cr::GCM_TAG_LENGTHS.contains(&(*n as usize)) && *n >= 0.0);
                    if !ok {
                        let s = str_of(vm, &tl)?;
                        return throw(vm, cr::cipher::invalid_auth_tag_error(&s));
                    }
                    let n = tl.as_num().unwrap();
                    if let Err(e) = ctx.set_auth_tag_length(n as usize) {
                        return throw(vm, e);
                    }
                    tag_explicit = true;
                    tag_len = n;
                }
            }
        }
        let proto_fb = st(|s| if decipher { s.decipher_proto.clone() } else { s.cipher_proto.clone() });
        let fb = proto_fb.unwrap_or_else(|| vm.intr.object_proto.clone());
        let p = vm.proto_from_nt(&Some(nt.clone()), &fb)?;
        let o = Obj::new(Some(p), ObjKind::Host(Box::new(CipherState { ctx: RefCell::new(ctx) })));
        let ov = Value::Obj(o.clone());
        let info_v = cipher_info_obj(vm, info);
        o.set_prop(key("_info"), info_v, WEC);
        let kc = u8array(vm, kb);
        o.set_prop(key("_key"), kc, WEC);
        let ivc = match &ivb {
            Some(b) if info.mode != cr::CipherMode::Ecb => u8array(vm, b.clone()),
            _ => Value::Null,
        };
        o.set_prop(key("_iv"), ivc, WEC);
        o.set_prop(key("_decipher"), Value::Bool(decipher), WEC);
        o.set_prop(key("_autoPadding"), Value::Bool(true), WEC);
        o.set_prop(key("_state"), num(0.0), WEC);
        let empty = u8array(vm, Vec::new());
        o.set_prop(key("_buf"), empty, WEC);
        if gcm {
            o.set_prop(key("_tagLenExplicit"), Value::Bool(tag_explicit), WEC);
            o.set_prop(key("_tagLen"), num(tag_len), WEC);
            let aad = u8array(vm, Vec::new());
            o.set_prop(key("_aad"), aad, WEC);
            let ct = u8array(vm, Vec::new());
            o.set_prop(key("_ct"), ct, WEC);
        }
        if gcm || info.mode == cr::CipherMode::Ctr {
            let mut counter = [0u8; 16];
            if let Some(b) = &ivb {
                if gcm && b.len() == 12 {
                    counter[..12].copy_from_slice(b);
                    counter[15] = 2;
                } else if !gcm {
                    counter.copy_from_slice(&b[..16.min(b.len())]);
                }
            }
            let cv = u8array(vm, counter.to_vec());
            o.set_prop(key("_counter"), cv, WEC);
            let ks = u8array(vm, Vec::new());
            o.set_prop(key("_ks"), ks, WEC);
        }
        if gcm {
            o.set_prop(key("_authTag"), Value::Null, WEC);
            o.set_prop(key("_tag"), Value::Null, WEC);
        }
        Ok(ov)
    })
}

fn cipheriv_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["Cipheriv"], |vm| init_cipher(vm, &nt, a, false))
}

fn decipheriv_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["Decipheriv"], |vm| init_cipher(vm, &nt, a, true))
}

fn create_cipheriv(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createCipheriv"], |vm| {
        let c = st(|s| s.exports.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        let ctor = cipher_ctor_of(vm, &c, false)?;
        vm.construct(&ctor, &[a.arg(0), a.arg(1), a.arg(2), a.arg(3)], None)
    })
}

fn create_decipheriv(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createDecipheriv"], |vm| {
        let c = st(|s| s.exports.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        let ctor = cipher_ctor_of(vm, &c, true)?;
        vm.construct(&ctor, &[a.arg(0), a.arg(1), a.arg(2), a.arg(3)], None)
    })
}

/// The internal Cipheriv / Decipheriv class (not looked up on the exports).
fn cipher_ctor_of(_vm: &mut Vm, _exports: &Value, decipher: bool) -> JsResult<Value> {
    let p = st(|s| if decipher { s.decipher_proto.clone() } else { s.cipher_proto.clone() });
    Ok(match p.and_then(|p| p.get_own_str("constructor")) {
        Some(c) => c,
        None => Value::Undefined,
    })
}

fn with_ctx<R>(v: &Value, f: impl FnOnce(&mut cr::CipherCtx) -> R) -> Option<R> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<CipherState>().map(|s| f(&mut s.ctx.borrow_mut())),
            _ => None,
        },
        _ => None,
    }
}

fn sync_padding(vm: &mut Vm, this: &Value) -> JsResult<()> {
    let ap = get(vm, this, "_autoPadding")?.truthy();
    with_ctx(this, |c| c.set_auto_padding(ap));
    Ok(())
}

/// `cipherUpdate(this, data, inputEncoding, outputEncoding)`
fn cipher_update(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let calls = bump(&CUPDATE_CALLS);
    let frames = tail(calls, "update");
    let this = a.this.clone();
    let out = with_frames(vm, &frames, |vm| {
        with_frames(vm, &["cipherUpdate"], |vm| {
            let data = to_bytes_vec(vm, &a.arg(0), &a.arg(1))?;
            sync_padding(vm, &this)?;
            let r = match with_ctx(&this, |c| c.update(&data)) {
                Some(r) => r,
                None => return vm.throw_type("cannot read property 'mode' of undefined"),
            };
            let out = match r {
                Ok(o) => o,
                Err(e) => return throw(vm, e),
            };
            set(vm, &this, "_state", num(1.0))?;
            new_buf(vm, out)
        })
    })?;
    // cipherUpdate's `return ... buf.toString(outputEncoding)` is a tail call too
    let inner = tail(calls, "cipherUpdate");
    with_frames(vm, &frames, |vm| with_frames(vm, &inner, |vm| maybe_encode(vm, out, &a.arg(2))))
}

fn cipher_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let frames = tail(bump(&CFINAL_CALLS), "final");
    let this = a.this.clone();
    let out = with_frames(vm, &frames, |vm| {
        with_frames(vm, &["cipherFinal"], |vm| {
            sync_padding(vm, &this)?;
            let r = match with_ctx(&this, |c| (c.finalize(), c.info().mode == cr::CipherMode::Gcm && !c.is_decipher())) {
                Some(r) => r,
                None => return vm.throw_type("cannot read property 'mode' of undefined"),
            };
            set(vm, &this, "_state", num(2.0))?;
            let out = match r.0 {
                Ok(o) => o,
                Err(e) => return throw(vm, e),
            };
            if r.1 {
                if let Some(Ok(tag)) = with_ctx(&this, |c| c.auth_tag()) {
                    let t = u8array(vm, tag);
                    set(vm, &this, "_tag", t)?;
                }
            }
            new_buf(vm, out)
        })
    })?;
    with_frames(vm, &frames, |vm| with_frames(vm, &["cipherFinal"], |vm| maybe_encode(vm, out, &a.arg(0))))
}

fn cipher_set_auto_padding(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setAutoPadding"], |vm| {
        let v = a.arg(0);
        let on = if v.is_undefined() { true } else { v.truthy() };
        set(vm, &a.this, "_autoPadding", Value::Bool(on))?;
        with_ctx(&a.this, |c| c.set_auto_padding(on));
        Ok(a.this.clone())
    })
}

fn cipher_set_aad(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let frames = tail(bump(&CSETAAD_CALLS), "setAAD");
    with_frames(vm, &frames, |vm| {
        with_frames(vm, &["cipherSetAAD"], |vm| {
            let this = a.this.clone();
            let st_v = get(vm, &this, "_state")?;
            let gcm = with_ctx(&this, |c| c.info().mode == cr::CipherMode::Gcm).unwrap_or(false);
            if !gcm || !matches!(st_v, Value::Num(n) if n == 0.0) {
                return Err(coded(vm, "Error", "Invalid state for operation setAAD", "ERR_CRYPTO_INVALID_STATE"));
            }
            let b = to_bytes_vec(vm, &a.arg(0), &Value::Undefined)?;
            match with_ctx(&this, |c| c.set_aad(&b)) {
                Some(Err(e)) => return throw(vm, e),
                _ => {}
            }
            Ok(this)
        })
    })
}

fn cipher_get_auth_tag(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["getAuthTag"], |vm| {
        let this = a.this.clone();
        let info = get(vm, &this, "_info")?;
        let mode = get(vm, &info, "mode")?;
        let state = get(vm, &this, "_state")?;
        let tag = get(vm, &this, "_tag")?;
        if !matches!(&mode, Value::Str(s) if s.eq_str("gcm")) || !matches!(state, Value::Num(n) if n == 2.0) || tag.is_null() {
            return Err(coded(vm, "Error", "Invalid state for operation getAuthTag", "ERR_CRYPTO_INVALID_STATE"));
        }
        let b = raw_bytes(&tag);
        new_buf(vm, b)
    })
}

fn decipher_set_auth_tag(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setAuthTag"], |vm| {
        let this = a.this.clone();
        let info = get(vm, &this, "_info")?;
        let mode = get(vm, &info, "mode")?;
        let state = get(vm, &this, "_state")?;
        if !matches!(&mode, Value::Str(s) if s.eq_str("gcm")) || matches!(state, Value::Num(n) if n == 2.0) {
            return Err(coded(vm, "Error", "Invalid state for operation setAuthTag", "ERR_CRYPTO_INVALID_STATE"));
        }
        let t = to_bytes_vec(vm, &a.arg(0), &a.arg(1))?;
        match with_ctx(&this, |c| c.set_auth_tag(&t)) {
            Some(Err(e)) => return throw(vm, e),
            _ => {}
        }
        let tv = u8array(vm, t);
        set(vm, &this, "_authTag", tv)?;
        Ok(this)
    })
}

fn get_ciphers(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let v: Vec<Value> = cr::cipher_names().iter().map(|n| Value::str(n)).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn get_curves(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let v: Vec<Value> = ["P-256", "prime256v1", "secp256r1"].iter().map(|n| Value::str(n)).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn get_cipher_info(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["getCipherInfo"], |vm| {
        let n = a.arg(0);
        let info = match &n {
            Value::Num(x) => {
                if x.fract() == 0.0 && *x >= 0.0 && *x <= u32::MAX as f64 {
                    cr::cipher_info_by_nid(*x as u32)
                } else {
                    None
                }
            }
            other => {
                let s = with_frames(vm, &["resolveCipherName"], |vm| str_of(vm, other))?;
                cr::cipher_info(&s)
            }
        };
        let info = match info {
            Some(i) => i,
            None => return Ok(Value::Undefined),
        };
        let result = cipher_info_obj(vm, info);
        let opts = a.arg(1);
        if opts.truthy() {
            let kl = get(vm, &opts, "keyLength")?;
            if !kl.is_undefined() && !Value::strict_eq(&kl, &num(info.key_len as f64)) {
                return Ok(Value::Undefined);
            }
            let ivl = get(vm, &opts, "ivLength")?;
            if !ivl.is_undefined() {
                match info.mode {
                    cr::CipherMode::Ecb => return Ok(Value::Undefined),
                    cr::CipherMode::Gcm => {
                        if vm.op_compare(crate::bytecode::Op::Lt, &ivl, &num(1.0))? {
                            return Ok(Value::Undefined);
                        }
                        if let Value::Obj(o) = &result {
                            o.set_prop(key("ivLength"), ivl, WEC);
                        }
                    }
                    _ => {
                        if !Value::strict_eq(&ivl, &num(16.0)) {
                            return Ok(Value::Undefined);
                        }
                    }
                }
            }
        }
        Ok(result)
    })
}

// ============================================================================================
// misc exports
// ============================================================================================

fn set_fips(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setFips"], |vm| {
        if a.arg(0).truthy() {
            return vm.throw_error("Error", "FIPS mode is not supported in lumen");
        }
        Ok(Value::Undefined)
    })
}

fn secure_heap_used(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(vm.obj_from(vec![("total", num(0.0)), ("min", num(0.0)), ("used", num(0.0)), ("utilization", num(0.0))])))
}

fn set_engine(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    with_frames(vm, &["<anonymous>"], |vm| vm.throw_error("Error", "node:crypto setEngine is not supported in lumen (no native primitive available)"))
}

const CONSTANTS: &[(&str, f64)] = &[
    ("OPENSSL_VERSION_NUMBER", 805306624.0),
    ("SSL_OP_ALL", 2147485776.0),
    ("SSL_OP_ALLOW_NO_DHE_KEX", 1024.0),
    ("SSL_OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION", 262144.0),
    ("SSL_OP_CIPHER_SERVER_PREFERENCE", 4194304.0),
    ("SSL_OP_CISCO_ANYCONNECT", 32768.0),
    ("SSL_OP_COOKIE_EXCHANGE", 8192.0),
    ("SSL_OP_CRYPTOPRO_TLSEXT_BUG", 2147483648.0),
    ("SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS", 2048.0),
    ("SSL_OP_LEGACY_SERVER_CONNECT", 4.0),
    ("SSL_OP_NO_COMPRESSION", 131072.0),
    ("SSL_OP_NO_ENCRYPT_THEN_MAC", 524288.0),
    ("SSL_OP_NO_QUERY_MTU", 4096.0),
    ("SSL_OP_NO_RENEGOTIATION", 1073741824.0),
    ("SSL_OP_NO_SESSION_RESUMPTION_ON_RENEGOTIATION", 65536.0),
    ("SSL_OP_NO_SSLv2", 0.0),
    ("SSL_OP_NO_SSLv3", 33554432.0),
    ("SSL_OP_NO_TICKET", 16384.0),
    ("SSL_OP_NO_TLSv1", 67108864.0),
    ("SSL_OP_NO_TLSv1_1", 268435456.0),
    ("SSL_OP_NO_TLSv1_2", 134217728.0),
    ("SSL_OP_NO_TLSv1_3", 536870912.0),
    ("SSL_OP_PRIORITIZE_CHACHA", 2097152.0),
    ("SSL_OP_TLS_ROLLBACK_BUG", 8388608.0),
    ("ENGINE_METHOD_RSA", 1.0),
    ("ENGINE_METHOD_DSA", 2.0),
    ("ENGINE_METHOD_DH", 4.0),
    ("ENGINE_METHOD_RAND", 8.0),
    ("ENGINE_METHOD_EC", 2048.0),
    ("ENGINE_METHOD_CIPHERS", 64.0),
    ("ENGINE_METHOD_DIGESTS", 128.0),
    ("ENGINE_METHOD_PKEY_METHS", 512.0),
    ("ENGINE_METHOD_PKEY_ASN1_METHS", 1024.0),
    ("ENGINE_METHOD_ALL", 65535.0),
    ("ENGINE_METHOD_NONE", 0.0),
    ("DH_CHECK_P_NOT_SAFE_PRIME", 2.0),
    ("DH_CHECK_P_NOT_PRIME", 1.0),
    ("DH_UNABLE_TO_CHECK_GENERATOR", 4.0),
    ("DH_NOT_SUITABLE_GENERATOR", 8.0),
    ("RSA_PKCS1_PADDING", 1.0),
    ("RSA_NO_PADDING", 3.0),
    ("RSA_PKCS1_OAEP_PADDING", 4.0),
    ("RSA_X931_PADDING", 5.0),
    ("RSA_PKCS1_PSS_PADDING", 6.0),
    ("RSA_PSS_SALTLEN_DIGEST", -1.0),
    ("RSA_PSS_SALTLEN_MAX_SIGN", -2.0),
    ("RSA_PSS_SALTLEN_AUTO", -2.0),
    ("defaultCoreCipherList", f64::NAN),
    ("TLS1_VERSION", 769.0),
    ("TLS1_1_VERSION", 770.0),
    ("TLS1_2_VERSION", 771.0),
    ("TLS1_3_VERSION", 772.0),
    ("POINT_CONVERSION_COMPRESSED", 2.0),
    ("POINT_CONVERSION_UNCOMPRESSED", 4.0),
    ("POINT_CONVERSION_HYBRID", 6.0),
    ("defaultCipherList", f64::NAN),
];

const DEFAULT_CIPHER_LIST: &str = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA256:DHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384:DHE-RSA-AES256-SHA384:ECDHE-RSA-AES256-SHA256:DHE-RSA-AES256-SHA256:HIGH:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!SRP:!CAMELLIA";

// ============================================================================================
// module
// ============================================================================================

pub fn create_module(vm: &mut Vm) -> Value {
    let exports = vm.new_object();
    ST.with(|s| s.borrow_mut().exports = Some(exports.clone()));
    let e = &exports;
    let put = |name: &str, v: Value| e.set_prop(key(name), v, WEC);

    // classes
    let (hash_c, hash_p) = make_class(vm, "Hash", 1, hash_ctor, &[("update", 2, hash_update), ("_bytes", 0, hash_bytes), ("digest", 1, hash_digest), ("copy", 0, hash_copy)]);
    let (hmac_c, _hmac_p) = make_class(vm, "Hmac", 2, hmac_ctor, &[("update", 2, hash_update), ("digest", 1, hmac_digest)]);
    let (ko_c, ko_p) = make_class(vm, "KeyObject", 2, keyobject_ctor, &[]);
    vm.def_getter(&ko_p, "type", ko_type);
    vm.def_getter(&ko_p, "symmetricKeySize", ko_symmetric_size);
    vm.def_getter(&ko_p, "asymmetricKeyType", ko_asym_type);
    vm.def_getter(&ko_p, "asymmetricKeyDetails", ko_asym_details);
    vm.def_method(&ko_p, "export", 1, ko_export);
    vm.def_method(&ko_p, "equals", 1, ko_equals);
    let (ci_c, ci_p) = make_class(
        vm,
        "Cipheriv",
        4,
        cipheriv_ctor,
        &[("update", 3, cipher_update), ("final", 1, cipher_final), ("setAutoPadding", 1, cipher_set_auto_padding), ("setAAD", 2, cipher_set_aad), ("getAuthTag", 0, cipher_get_auth_tag)],
    );
    let (de_c, de_p) = make_class(
        vm,
        "Decipheriv",
        4,
        decipheriv_ctor,
        &[("update", 3, cipher_update), ("final", 1, cipher_final), ("setAutoPadding", 1, cipher_set_auto_padding), ("setAAD", 2, cipher_set_aad), ("setAuthTag", 2, decipher_set_auth_tag)],
    );
    ST.with(|s| {
        let mut s = s.borrow_mut();
        s.hash_ctor = Some(hash_c.clone());
        s.hash_proto = Some(hash_p.clone());
        s.hmac_ctor = Some(hmac_c.clone());
        s.keyobject_ctor = Some(ko_c.clone());
        s.keyobject_proto = Some(ko_p.clone());
        s.cipher_proto = Some(ci_p.clone());
        s.decipher_proto = Some(de_p.clone());
    });
    let asym = crate::runtime::cryptomod::asym_classes(vm);

    let v = plain(vm, "argon2", 3, argon2_async);
    put("argon2", v);
    let v = plain(vm, "argon2Sync", 2, argon2_sync);
    put("argon2Sync", v);
    let v = arrow(vm, "createHash", 1, create_hash);
    put("createHash", v);
    let v = arrow(vm, "createHmac", 2, create_hmac);
    put("createHmac", v);
    put("Hash", Value::Obj(hash_c));
    put("Hmac", Value::Obj(hmac_c));
    let v = plain(vm, "hash", 3, crypto_hash);
    put("hash", v);
    let v = arrow(vm, "getHashes", 0, get_hashes);
    put("getHashes", v);
    let v = plain(vm, "pbkdf2", 6, pbkdf2_async);
    put("pbkdf2", v);
    let v = plain(vm, "pbkdf2Sync", 5, pbkdf2_sync);
    put("pbkdf2Sync", v);
    let v = plain(vm, "hkdf", 6, hkdf_async);
    put("hkdf", v);
    let v = plain(vm, "hkdfSync", 5, hkdf_sync);
    put("hkdfSync", v);
    let v = plain(vm, "scrypt", 5, scrypt_async);
    put("scrypt", v);
    let v = plain(vm, "scryptSync", 4, scrypt_sync);
    put("scryptSync", v);
    let v = plain(vm, "randomBytes", 2, random_bytes);
    put("randomBytes", v);
    let v = plain(vm, "randomFill", 4, random_fill);
    put("randomFill", v);
    let v = plain(vm, "randomFillSync", 3, random_fill_sync);
    put("randomFillSync", v);
    let v = plain(vm, "randomInt", 0, random_int);
    put("randomInt", v);
    let v = arrow(vm, "randomUUID", 0, random_uuid);
    put("randomUUID", v);
    let v = arrow(vm, "getRandomValues", 1, get_random_values);
    put("getRandomValues", v);
    let v = plain(vm, "timingSafeEqual", 2, timing_safe_equal);
    put("timingSafeEqual", v);
    put("KeyObject", Value::Obj(ko_c));
    let v = plain(vm, "createSecretKey", 2, create_secret_key);
    put("createSecretKey", v);
    let v = plain(vm, "generateKey", 3, generate_key);
    put("generateKey", v);
    let v = plain(vm, "generateKeySync", 2, generate_key_sync);
    put("generateKeySync", v);
    let v = arrow(vm, "createCipheriv", 4, create_cipheriv);
    put("createCipheriv", v);
    let v = arrow(vm, "createDecipheriv", 4, create_decipheriv);
    put("createDecipheriv", v);
    put("Cipheriv", Value::Obj(ci_c));
    put("Decipheriv", Value::Obj(de_c));
    let v = arrow(vm, "getCiphers", 0, get_ciphers);
    put("getCiphers", v);
    let v = arrow(vm, "getCurves", 0, get_curves);
    put("getCurves", v);
    let v = plain(vm, "getCipherInfo", 2, get_cipher_info);
    put("getCipherInfo", v);
    let v = arrow(vm, "getFips", 0, |_vm, _a| Ok(num(0.0)));
    put("getFips", v);
    let v = arrow(vm, "setFips", 1, set_fips);
    put("setFips", v);
    let v = arrow(vm, "secureHeapUsed", 0, secure_heap_used);
    put("secureHeapUsed", v);
    let constants = vm.new_object();
    for (k, v) in CONSTANTS {
        let val = if v.is_nan() { Value::str(DEFAULT_CIPHER_LIST) } else { num(*v) };
        constants.set_prop(key(k), val, WEC);
    }
    put("constants", Value::Obj(constants));
    let wc = st(|s| s.webcrypto.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
    put("webcrypto", wc);
    let sub = st(|s| s.subtle.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
    put("subtle", sub);
    for (name, v) in asym {
        put(name, v);
    }
    let v = arrow(vm, "", 0, set_engine);
    put("setEngine", v);
    Value::Obj(exports)
}

// ============================================================================================
// asymmetric cryptography (sign/verify, key objects, RSA encryption, DH/ECDH, primes, X.509)
// ============================================================================================

use crate::crypto::bigint::BigUint;
use crate::crypto::keys::{AsymKey, KeyKind};

thread_local! {
    static EXPORT_CALLS: Cell<u32> = Cell::new(0);
    static SIGN_CALLS: Cell<u32> = Cell::new(0);
    static VERIFY_CALLS: Cell<u32> = Cell::new(0);
    static CURVE_OBJ: RefCell<Option<Obj>> = RefCell::new(None);
}

fn big_to_js(b: &BigUint) -> Value {
    let h = b.to_hex();
    let bi = crate::bigint::BigInt::from_str_radix(if h.is_empty() { "0" } else { &h }, 16).unwrap_or_else(crate::bigint::BigInt::zero);
    Value::BigInt(std::rc::Rc::new(bi))
}

fn js_big_to_biguint(b: &crate::bigint::BigInt) -> BigUint {
    if b.is_negative() {
        return BigUint::zero();
    }
    BigUint::from_hex(&b.to_string_radix(16)).unwrap_or_else(BigUint::zero)
}

fn is_negative_big(v: &Value) -> bool {
    matches!(v, Value::BigInt(b) if b.is_negative())
}

// ---------------------------------------------------------------- key objects

/// The JS-visible `_asym` struct of a key.
fn asym_js(vm: &mut Vm, k: &AsymKey) -> Value {
    let o = vm.new_object();
    let kind = k.kind().name();
    o.set_prop(key("kind"), Value::str(kind), WEC);
    match k {
        AsymKey::RsaPublic(p) => {
            o.set_prop(key("n"), big_to_js(&p.n), WEC);
            o.set_prop(key("e"), big_to_js(&p.e), WEC);
        }
        AsymKey::RsaPrivate(p) => {
            for (n, v) in [("n", &p.n), ("e", &p.e), ("d", &p.d), ("p", &p.p), ("q", &p.q), ("dp", &p.dp), ("dq", &p.dq), ("qi", &p.qi)] {
                o.set_prop(key(n), big_to_js(v), WEC);
            }
        }
        AsymKey::EcPublic { point } => {
            o.set_prop(key("curve"), Value::str("prime256v1"), WEC);
            let pv = u8array(vm, point.clone());
            o.set_prop(key("point"), pv, WEC);
        }
        AsymKey::EcPrivate { d, point } => {
            o.set_prop(key("curve"), Value::str("prime256v1"), WEC);
            o.set_prop(key("d"), big_to_js(&BigUint::from_bytes_be(d)), WEC);
            let pv = u8array(vm, point.clone());
            o.set_prop(key("point"), pv, WEC);
        }
        AsymKey::Ed25519Public(p) => {
            let pv = u8array(vm, p.to_vec());
            o.set_prop(key("pub"), pv, WEC);
        }
        AsymKey::Ed25519Private { seed, public } => {
            let s = u8array(vm, seed.to_vec());
            o.set_prop(key("seed"), s, WEC);
            let pv = u8array(vm, public.to_vec());
            o.set_prop(key("pub"), pv, WEC);
        }
        AsymKey::X25519Public(p) => {
            let pv = u8array(vm, p.to_vec());
            o.set_prop(key("pub"), pv, WEC);
        }
        AsymKey::X25519Private { secret, public } => {
            let s = u8array(vm, secret.to_vec());
            o.set_prop(key("priv"), s, WEC);
            let pv = u8array(vm, public.to_vec());
            o.set_prop(key("pub"), pv, WEC);
        }
    }
    Value::Obj(o)
}

/// `makeKeyObject(type, struct)`
fn make_key_object(vm: &mut Vm, ty: &str, k: AsymKey) -> Value {
    let proto = st(|s| s.keyobject_proto.clone()).unwrap_or_else(|| vm.intr.object_proto.clone());
    let asym = asym_js(vm, &k);
    let o = Obj::new(Some(proto), ObjKind::Host(Box::new(AsymState { key: k })));
    o.set_prop(key("_type"), Value::str(ty), WEC);
    o.set_prop(key("_material"), Value::Null, WEC);
    o.set_prop(key("_asym"), asym, WEC);
    Value::Obj(o)
}

fn asym_details(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let o = vm.new_object();
    if let Some(k) = asym_of(this) {
        match k.kind() {
            KeyKind::Rsa => {
                if let Some((bits, e)) = k.rsa_details() {
                    o.set_prop(key("modulusLength"), num(bits as f64), WEC);
                    o.set_prop(key("publicExponent"), big_to_js(&e), WEC);
                }
            }
            KeyKind::Ec => o.set_prop(key("namedCurve"), Value::str("prime256v1"), WEC),
            _ => {}
        }
    }
    Ok(Value::Obj(o))
}

/// Normalised key input (`normalizeKeyInput`).
struct NormKey {
    key_object: Option<Value>,
    data: Value,
    format: String,
    ty: Option<String>,
    passphrase: Value,
}

fn is_key_object(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    let ko = st(|s| s.keyobject_ctor.clone());
    is_instance(vm, v, &ko)
}

fn is_binary(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_) | ObjKind::ArrayBuffer(_)))
}

fn normalize_key_input(vm: &mut Vm, input: &Value) -> JsResult<NormKey> {
    with_frames(vm, &["normalizeKeyInput"], |vm| {
        let blank = |v: Value| NormKey { key_object: None, data: v, format: "pem".into(), ty: None, passphrase: Value::Undefined };
        if is_key_object(vm, input)? {
            let mut n = blank(Value::Undefined);
            n.key_object = Some(input.clone());
            return Ok(n);
        }
        if let Value::Str(_) = input {
            return Ok(blank(input.clone()));
        }
        if is_binary(input) {
            return Ok(blank(input.clone()));
        }
        if let Value::Obj(_) = input {
            let k = get(vm, input, "key")?;
            if !k.is_undefined() {
                if is_key_object(vm, &k)? {
                    let mut n = blank(Value::Undefined);
                    n.key_object = Some(k);
                    return Ok(n);
                }
                let f = get(vm, input, "format")?;
                let format = if f.truthy() { str_of(vm, &f)? } else { "pem".to_string() };
                let t = get(vm, input, "type")?;
                let ty = if t.truthy() { Some(str_of(vm, &t)?) } else { None };
                let passphrase = get(vm, input, "passphrase")?;
                return Ok(NormKey { key_object: None, data: k, format, ty, passphrase });
            }
        }
        vm.throw_type("crypto: invalid key input")
    })
}

/// `keyDataToDer(norm)` → (der, PEM label)
fn key_data_to_der(vm: &mut Vm, n: &NormKey) -> JsResult<(Vec<u8>, Option<String>)> {
    with_frames(vm, &["keyDataToDer"], |vm| {
        if !n.passphrase.is_undefined() {
            return vm.throw_error("Error", "crypto: encrypted private keys are not supported in lumen");
        }
        if n.format == "der" {
            let b = to_bytes_vec(vm, &n.data, &Value::Undefined)?;
            return Ok((b, None));
        }
        let text = match &n.data {
            Value::Str(s) => s.to_rust_string(),
            other => {
                let b = to_bytes_vec(vm, other, &Value::Undefined)?;
                String::from_utf8_lossy(&b).to_string()
            }
        };
        match with_frames(vm, &["pemDecode"], |vm| match crate::crypto::asn1::pem_decode(&text) {
            Ok(r) => Ok(r),
            Err(e) => throw(vm, e),
        }) {
            Ok((label, der)) => Ok((der, Some(label))),
            Err(e) => Err(e),
        }
    })
}

/// Frame of the DER parser used for a label / type.
fn parser_frame(private: bool, label: Option<&str>, ty: Option<&str>) -> &'static str {
    if private {
        if label == Some("RSA PRIVATE KEY") || ty == Some("pkcs1") {
            "parsePkcs1Private"
        } else if label == Some("EC PRIVATE KEY") || ty == Some("sec1") {
            "parseSec1"
        } else {
            "parsePkcs8"
        }
    } else if label == Some("CERTIFICATE") {
        "x509SpkiDer"
    } else if label == Some("RSA PUBLIC KEY") || ty == Some("pkcs1") {
        "parsePkcs1Public"
    } else if label == Some("RSA PRIVATE KEY") {
        "parsePkcs1Private"
    } else if label == Some("EC PRIVATE KEY") {
        "parseSec1"
    } else if label == Some("PRIVATE KEY") {
        "parsePkcs8"
    } else {
        "parseSpki"
    }
}

fn parse_err(vm: &mut Vm, frame: &str, e: CryptoError) -> Value {
    let frames: Vec<&str> = if e.message == "ASN.1: truncated DER" { vec![frame, "derRead"] } else { vec![frame] };
    match with_frames(vm, &frames, |vm| -> JsResult<Value> { Err(cerr(vm, e)) }) {
        Ok(v) | Err(v) => v,
    }
}

/// `keyFromJwk(jwk, wantPrivate)`
fn key_from_jwk(vm: &mut Vm, data: &Value, want_private: bool) -> JsResult<AsymKey> {
    with_frames(vm, &["keyFromJwk"], |vm| {
        if !matches!(data, Value::Obj(_)) {
            return vm.throw_type("crypto: JWK must be an object");
        }
        let mut fields: HashMap<&'static str, String> = HashMap::new();
        for f in ["kty", "crv", "x", "y", "d", "n", "e", "p", "q", "dp", "dq", "qi"] {
            let v = get(vm, data, f)?;
            if !v.is_undefined() {
                let s = str_of(vm, &v)?;
                fields.insert(f, s);
            }
        }
        match AsymKey::from_jwk(&|n: &str| fields.get(n).cloned(), want_private) {
            Ok(k) => Ok(k),
            Err(e) => throw(vm, e),
        }
    })
}

fn create_public_key_impl(vm: &mut Vm, input: &Value) -> JsResult<Value> {
    with_frames(vm, &["createPublicKey"], |vm| {
        let n = normalize_key_input(vm, input)?;
        if let Some(src) = n.key_object {
            let t = get(vm, &src, "_type")?;
            if matches!(&t, Value::Str(s) if s.eq_str("public")) {
                return Ok(src);
            }
            let asym = get(vm, &src, "_asym")?;
            let native = asym_of(&src);
            if !matches!(&t, Value::Str(s) if s.eq_str("private")) || !asym.truthy() || native.is_none() {
                return vm.throw_type("crypto: cannot derive a public key from this KeyObject");
            }
            return Ok(make_key_object(vm, "public", native.unwrap().to_public()));
        }
        let k = if n.format == "jwk" {
            key_from_jwk(vm, &n.data, false)?
        } else {
            let (der, label) = key_data_to_der(vm, &n)?;
            match cr::keys::parse_public_key(&der, label.as_deref(), n.ty.as_deref()) {
                Ok(k) => k,
                Err(e) => {
                    let f = parser_frame(false, label.as_deref(), n.ty.as_deref());
                    return Err(parse_err(vm, f, e));
                }
            }
        };
        Ok(make_key_object(vm, "public", k.to_public()))
    })
}

fn create_private_key_impl(vm: &mut Vm, input: &Value) -> JsResult<Value> {
    with_frames(vm, &["createPrivateKey"], |vm| {
        let n = normalize_key_input(vm, input)?;
        if let Some(src) = n.key_object {
            let t = get(vm, &src, "_type")?;
            if matches!(&t, Value::Str(s) if s.eq_str("private")) {
                return Ok(src);
            }
            return vm.throw_type("crypto: cannot create a private key from a public key");
        }
        let k = if n.format == "jwk" {
            key_from_jwk(vm, &n.data, true)?
        } else {
            let (der, label) = key_data_to_der(vm, &n)?;
            match cr::keys::parse_private_key(&der, label.as_deref(), n.ty.as_deref()) {
                Ok(k) => k,
                Err(e) => {
                    if e.message == "crypto: key data does not contain a private key" {
                        return throw(vm, e);
                    }
                    let f = parser_frame(true, label.as_deref(), n.ty.as_deref());
                    return Err(parse_err(vm, f, e));
                }
            }
        };
        Ok(make_key_object(vm, "private", k))
    })
}

fn create_public_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    create_public_key_impl(vm, &a.arg(0))
}

fn create_private_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    create_private_key_impl(vm, &a.arg(0))
}

/// `exportAsymmetricKey(key, options)`
fn export_asymmetric(vm: &mut Vm, this: &Value, opts: &Value) -> JsResult<Value> {
    let frames = tail(bump(&EXPORT_CALLS), "export");
    // the `export` frame was pushed by the caller; drop it while interpreted
    let saved = if frames.is_empty() { vm.trace.pop() } else { None };
    let r = with_frames(vm, &["exportAsymmetricKey"], |vm| {
        let format = if opts.truthy() { get(vm, opts, "format")? } else { Value::Undefined };
        if !format.truthy() {
            return vm.throw_type("KeyObject.export: options.format is required for asymmetric keys");
        }
        let fs = str_of(vm, &format)?;
        let k = match asym_of(this) {
            Some(k) => k,
            None => return vm.throw_type("cannot read property 'kind' of null"),
        };
        if fs == "jwk" {
            let o = vm.new_object();
            for (n, v) in k.jwk_fields() {
                o.set_prop(key(n), Value::str(&v), WEC);
            }
            return Ok(Value::Obj(o));
        }
        let cipher = get(vm, opts, "cipher")?;
        let pass = get(vm, opts, "passphrase")?;
        if !cipher.is_undefined() || !pass.is_undefined() {
            return vm.throw_error("Error", "KeyObject.export: encrypted private-key export is not supported in lumen");
        }
        let t = get(vm, opts, "type")?;
        let ts = str_of(vm, &t)?;
        let der = match k.export_der(&ts) {
            Ok(d) => d,
            Err(e) => return throw(vm, e),
        };
        match fs.as_str() {
            "der" => new_buf(vm, der),
            "pem" => Ok(Value::str(&crate::crypto::asn1::pem_encode(k.pem_label(&ts), &der))),
            other => vm.throw_error("Error", format!("KeyObject.export: unsupported format '{}'", other)),
        }
    });
    if let Some(s) = saved {
        vm.trace.push(s);
    }
    r
}

// ---------------------------------------------------------------- key pair generation

fn curve_by_name(vm: &mut Vm, c: &Value) -> JsResult<()> {
    with_frames(vm, &["curveByName"], |vm| {
        let s = str_of(vm, c)?;
        match s.to_lowercase().as_str() {
            "p-256" | "prime256v1" | "secp256r1" => Ok(()),
            _ => vm.throw_error("Error", format!("Named curve '{}' is not supported in lumen (only prime256v1/P-256)", s)),
        }
    })
}

fn generate_key_pair_struct(vm: &mut Vm, ty: &Value, options: &Value) -> JsResult<AsymKey> {
    let t = with_frames(vm, &["generateKeyPairStruct"], |vm| lower_of(vm, ty))?;
    let gen = |vm: &mut Vm, kind: KeyKind, bits: usize, e: &BigUint| -> JsResult<AsymKey> {
        match AsymKey::generate(kind, bits, e) {
            Ok(k) => Ok(k),
            Err(err) => throw(vm, err),
        }
    };
    match t.as_str() {
        "ed25519" => gen(vm, KeyKind::Ed25519, 0, &BigUint::zero()),
        "x25519" => gen(vm, KeyKind::X25519, 0, &BigUint::zero()),
        "rsa" => {
            let ml = if options.truthy() { get(vm, options, "modulusLength")? } else { Value::Undefined };
            if !is_integer(&ml) {
                return with_frames(vm, &["generateKeyPairStruct"], |vm| vm.throw_type("options.modulusLength is required for RSA key generation"));
            }
            with_frames(vm, &["generateRsa"], |vm| {
                let bits = ml.as_num().unwrap_or(0.0);
                if !(512.0..=8192.0).contains(&bits) {
                    return vm.throw_range("RSA modulusLength must be an integer in [512, 8192]");
                }
                let pe = get(vm, options, "publicExponent")?;
                let e = match &pe {
                    Value::Undefined => BigUint::from_u64(65537),
                    Value::BigInt(b) => js_big_to_biguint(b),
                    Value::Num(n) => BigUint::from_u64(*n as u64),
                    other => {
                        let s = str_of(vm, other)?;
                        BigUint::from_decimal(s.trim()).unwrap_or_else(|| BigUint::from_u64(65537))
                    }
                };
                gen(vm, KeyKind::Rsa, bits as usize, &e)
            })
        }
        "ec" => with_frames(vm, &["generateEc"], |vm| {
            let c = if options.truthy() { get(vm, options, "namedCurve")? } else { Value::Undefined };
            curve_by_name(vm, &c)?;
            gen(vm, KeyKind::Ec, 0, &BigUint::zero())
        }),
        _ => with_frames(vm, &["generateKeyPairStruct"], |vm| {
            let s = str_of(vm, ty)?;
            vm.throw_error("Error", format!("generateKeyPair type '{}' is not supported in lumen (ed25519, x25519, rsa, ec)", s))
        }),
    }
}

fn generate_key_pair_impl(vm: &mut Vm, ty: &Value, options: &Value) -> JsResult<(Value, Value)> {
    let k = generate_key_pair_struct(vm, ty, options)?;
    let public = make_key_object(vm, "public", k.to_public());
    let private = make_key_object(vm, "private", k);
    let pub_enc = if options.truthy() { get(vm, options, "publicKeyEncoding")? } else { options.clone() };
    let priv_enc = if options.truthy() { get(vm, options, "privateKeyEncoding")? } else { options.clone() };
    let pk = if pub_enc.truthy() { call_member(vm, &public, "export", &[pub_enc])? } else { public };
    let sk = if priv_enc.truthy() { call_member(vm, &private, "export", &[priv_enc])? } else { private };
    Ok((pk, sk))
}

fn generate_key_pair_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["generateKeyPairSync"], |vm| {
        let (pk, sk) = generate_key_pair_impl(vm, &a.arg(0), &a.arg(1))?;
        let o = vm.new_object();
        o.set_prop(key("publicKey"), pk, WEC);
        o.set_prop(key("privateKey"), sk, WEC);
        Ok(Value::Obj(o))
    })
}

fn generate_key_pair(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["generateKeyPair"], |vm| {
        let (mut options, mut cb) = (a.arg(1), a.arg(2));
        if options.is_callable() {
            cb = options;
            options = Value::Undefined;
        }
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["generateKeyPairSync"], |vm| generate_key_pair_impl(vm, &a.arg(0), &options));
        defer_cb(vm, &cb, r.map(|(p, s)| vec![p, s]));
        Ok(Value::Undefined)
    })
}

// ---------------------------------------------------------------- sign / verify

/// Options carried by a key-like options object (`keyOptionsFrom`).
struct KeyOpts {
    padding: Value,
    salt_length: Value,
    dsa_encoding: Value,
    oaep_hash: Value,
    oaep_label: Value,
}

fn key_options_from(vm: &mut Vm, key_like: &Value) -> JsResult<KeyOpts> {
    let mut o = KeyOpts { padding: Value::Undefined, salt_length: Value::Undefined, dsa_encoding: Value::Undefined, oaep_hash: Value::Undefined, oaep_label: Value::Undefined };
    let plain = matches!(key_like, Value::Obj(_)) && !is_binary(key_like) && !is_key_object(vm, key_like)?;
    if plain {
        o.padding = get(vm, key_like, "padding")?;
        o.salt_length = get(vm, key_like, "saltLength")?;
        o.dsa_encoding = get(vm, key_like, "dsaEncoding")?;
        o.oaep_hash = get(vm, key_like, "oaepHash")?;
        o.oaep_label = get(vm, key_like, "oaepLabel")?;
    }
    Ok(o)
}

fn opt_i64(vm: &mut Vm, v: &Value) -> JsResult<Option<i64>> {
    if v.is_undefined() {
        return Ok(None);
    }
    let n = vm.to_number(v)?;
    Ok(Some(n as i64))
}

fn sign_options(vm: &mut Vm, o: &KeyOpts) -> JsResult<cr::asym::SignOptions> {
    Ok(cr::asym::SignOptions {
        padding: opt_i64(vm, &o.padding)?,
        salt_length: opt_i64(vm, &o.salt_length)?,
        dsa_encoding: if o.dsa_encoding.is_undefined() { None } else { Some(str_of(vm, &o.dsa_encoding)?) },
    })
}

/// The kind / digest checks of signDigest / verifyDigest (digest errors get `resolveHash`).
fn sign_prologue(vm: &mut Vm, fname: &str, verb: &str, alg: Option<&str>, k: &AsymKey) -> JsResult<()> {
    match k.kind() {
        KeyKind::X25519 => vm.throw_error("Error", format!("{}: X25519 keys cannot {}", fname, verb)),
        KeyKind::Ed25519 => {
            if alg.is_some() {
                return vm.throw_error("Error", format!("{}: algorithm must be null/undefined for Ed25519 keys", fname));
            }
            Ok(())
        }
        kind => match alg {
            None => vm.throw_error("Error", format!("{}: a digest algorithm is required for {} keys", fname, kind.name())),
            Some(name) => {
                let n = cr::normalize_digest_name(name);
                if cr::hash_alg_from_name(&n).is_none() {
                    return with_frames(vm, &["resolveHash"], |vm| throw(vm, cr::unsupported_digest_error(&n)));
                }
                Ok(())
            }
        },
    }
}

fn alg_arg(vm: &mut Vm, v: &Value) -> JsResult<Option<String>> {
    if v.is_nullish() {
        Ok(None)
    } else {
        Ok(Some(str_of(vm, v)?))
    }
}

/// `signDigest(algorithm, data, keyLike)`
fn sign_digest(vm: &mut Vm, algorithm: &Value, data: &Value, key_like: &Value) -> JsResult<Value> {
    with_frames(vm, &["signDigest"], |vm| {
        let ko = key_options_from(vm, key_like)?;
        let kv = create_private_key_impl(vm, key_like)?;
        let k = match asym_of(&kv) {
            Some(k) => k,
            None => return vm.throw_type("cannot read property 'kind' of null"),
        };
        let alg = alg_arg(vm, algorithm)?;
        sign_prologue(vm, "crypto.sign", "sign", alg.as_deref(), &k)?;
        let bytes = to_bytes_vec(vm, data, &Value::Undefined)?;
        let so = sign_options(vm, &ko)?;
        match cr::asym::sign(alg.as_deref(), &bytes, &k, &so) {
            Ok(s) => new_buf(vm, s),
            Err(e) => throw(vm, e),
        }
    })
}

/// `verifyDigest(algorithm, data, keyLike, signature)`
fn verify_digest(vm: &mut Vm, algorithm: &Value, data: &Value, key_like: &Value, sig: &Value) -> JsResult<Value> {
    with_frames(vm, &["verifyDigest"], |vm| {
        let ko = key_options_from(vm, key_like)?;
        let kv = create_public_key_impl(vm, key_like)?;
        let k = match asym_of(&kv) {
            Some(k) => k,
            None => return vm.throw_type("cannot read property 'kind' of null"),
        };
        let alg = alg_arg(vm, algorithm)?;
        sign_prologue(vm, "crypto.verify", "verify", alg.as_deref(), &k)?;
        let bytes = to_bytes_vec(vm, data, &Value::Undefined)?;
        let s = to_bytes_vec(vm, sig, &Value::Undefined)?;
        let so = sign_options(vm, &ko)?;
        match cr::asym::verify(alg.as_deref(), &bytes, &k, &s, &so) {
            Ok(b) => Ok(Value::Bool(b)),
            Err(e) => throw(vm, e),
        }
    })
}

fn crypto_sign(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(3);
    if cb.is_callable() {
        return with_frames(vm, &["cryptoSign"], |vm| {
            let r = sign_digest(vm, &a.arg(0), &a.arg(1), &a.arg(2));
            defer_cb(vm, &cb, r.map(|v| vec![v]));
            Ok(Value::Undefined)
        });
    }
    let frames = tail(bump(&SIGN_CALLS), "cryptoSign");
    with_frames(vm, &frames, |vm| sign_digest(vm, &a.arg(0), &a.arg(1), &a.arg(2)))
}

fn crypto_verify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(4);
    if cb.is_callable() {
        return with_frames(vm, &["cryptoVerify"], |vm| {
            let r = verify_digest(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3));
            defer_cb(vm, &cb, r.map(|v| vec![v]));
            Ok(Value::Undefined)
        });
    }
    let frames = tail(bump(&VERIFY_CALLS), "cryptoVerify");
    with_frames(vm, &frames, |vm| verify_digest(vm, &a.arg(0), &a.arg(1), &a.arg(2), &a.arg(3)))
}

/// `class Sign { constructor(algorithm) }` / `class Verify`
fn sign_like_ctor(vm: &mut Vm, a: &Args, name: &str) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &[name], |vm| {
        let fb = vm.get_str(a.callee, "prototype")?.as_obj().cloned();
        let o = instance(vm, &nt, fb, ObjKind::Ordinary)?;
        let ov = Value::Obj(o);
        let s = str_of(vm, &a.arg(0))?;
        let algo = cr::normalize_digest_name(&s);
        set(vm, &ov, "_algo", Value::str(&algo))?;
        if cr::hash_alg_from_name(&algo).is_none() {
            return with_frames(vm, &["resolveHash"], |vm| throw(vm, cr::unsupported_digest_error(&algo)));
        }
        let chunks = vm.new_array(Vec::new());
        set(vm, &ov, "_chunks", Value::Obj(chunks))?;
        Ok(ov)
    })
}

fn sign_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    sign_like_ctor(vm, a, "Sign")
}

fn verify_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    sign_like_ctor(vm, a, "Verify")
}

fn sign_sign(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    // Sign#sign has a loop: compiled, so its frame stays for the toString call
    with_frames(vm, &["sign"], |vm| {
        let chunks = get(vm, &this, "_chunks")?;
        let all = concat_chunks(vm, &chunks)?;
        let algo = get(vm, &this, "_algo")?;
        let data = u8array(vm, all);
        let out = sign_digest(vm, &algo, &data, &a.arg(0))?;
        maybe_encode(vm, out, &a.arg(1))
    })
}

fn verify_verify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    with_frames(vm, &["verify"], |vm| {
        let chunks = get(vm, &this, "_chunks")?;
        let all = concat_chunks(vm, &chunks)?;
        let algo = get(vm, &this, "_algo")?;
        let data = u8array(vm, all);
        let sig = a.arg(1);
        let sigv = if let Value::Str(_) = sig {
            let enc = if a.arg(2).truthy() { a.arg(2) } else { Value::str("hex") };
            buffer::buffer_from_value(vm, &sig, &enc)?
        } else {
            to_bytes(vm, &sig, &Value::Undefined)?
        };
        verify_digest(vm, &algo, &data, &a.arg(0), &sigv)
    })
}

fn create_sign(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createSign"], |vm| {
        let c = st(|s| s.sign_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        vm.construct(&c, &[a.arg(0)], None)
    })
}

fn create_verify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createVerify"], |vm| {
        let c = st(|s| s.verify_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        vm.construct(&c, &[a.arg(0)], None)
    })
}

// ---------------------------------------------------------------- RSA encryption

fn rsa_op(vm: &mut Vm, a: &Args, op: cr::asym::RsaOp) -> JsResult<Value> {
    with_frames(vm, &[op.name()], |vm| {
        let key_like = a.arg(0);
        let ko = key_options_from(vm, &key_like)?;
        let kv = if op.needs_private() { create_private_key_impl(vm, &key_like)? } else { create_public_key_impl(vm, &key_like)? };
        let k = match asym_of(&kv) {
            Some(k) => k,
            None => return vm.throw_type("cannot read property 'kind' of null"),
        };
        if let Err(e) = cr::asym::require_rsa(op, &k) {
            return throw(vm, e);
        }
        let data = to_bytes_vec(vm, &a.arg(1), &Value::Undefined)?;
        let padding = opt_i64(vm, &ko.padding)?;
        let oaep_default = matches!(op, cr::asym::RsaOp::PublicEncrypt | cr::asym::RsaOp::PrivateDecrypt);
        let uses_oaep = oaep_default && padding.unwrap_or(cr::asym::RSA_PKCS1_OAEP_PADDING) == cr::asym::RSA_PKCS1_OAEP_PADDING;
        let (alg, label) = if uses_oaep {
            let h = if ko.oaep_hash.truthy() { ko.oaep_hash.clone() } else { Value::str("sha1") };
            let (alg, _) = resolve_hash(vm, &h)?;
            let label = if ko.oaep_label.truthy() { to_bytes_vec(vm, &ko.oaep_label, &Value::Undefined)? } else { Vec::new() };
            (alg, label)
        } else {
            (HashAlg::Sha1, Vec::new())
        };
        match cr::asym::rsa_encrypt_op(op, &k, &data, padding, alg, &label) {
            Ok(out) => new_buf(vm, out),
            Err(e) => throw(vm, e),
        }
    })
}

fn public_encrypt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    rsa_op(vm, a, cr::asym::RsaOp::PublicEncrypt)
}
fn private_decrypt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    rsa_op(vm, a, cr::asym::RsaOp::PrivateDecrypt)
}
fn private_encrypt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    rsa_op(vm, a, cr::asym::RsaOp::PrivateEncrypt)
}
fn public_decrypt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    rsa_op(vm, a, cr::asym::RsaOp::PublicDecrypt)
}

// ---------------------------------------------------------------- DiffieHellman

/// `dhBigInt(value, encoding)`
fn dh_bigint(vm: &mut Vm, v: &Value, enc: &Value) -> JsResult<Value> {
    if let Value::BigInt(_) = v {
        return Ok(v.clone());
    }
    let b = to_bytes_vec(vm, v, enc)?;
    Ok(big_to_js(&BigUint::from_bytes_be(&b)))
}

fn as_big(vm: &mut Vm, v: &Value) -> JsResult<BigUint> {
    match v {
        Value::BigInt(b) => Ok(js_big_to_biguint(b)),
        _ => vm.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
    }
}

fn dh_init(vm: &mut Vm, o: &Value, prime: Value, generator: Value) -> JsResult<()> {
    set(vm, o, "_prime", prime)?;
    set(vm, o, "_generator", generator)?;
    set(vm, o, "_private", Value::Null)?;
    set(vm, o, "_public", Value::Null)?;
    set(vm, o, "verifyError", num(0.0))
}

fn dh_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["DiffieHellman"], |vm| {
        let fb = st(|s| s.dh_proto.clone());
        let o = Value::Obj(instance(vm, &nt, fb, ObjKind::Ordinary)?);
        let g = if a.arg(1).is_undefined() { num(2.0) } else { a.arg(1) };
        dh_init(vm, &o, a.arg(0), g)?;
        Ok(o)
    })
}

fn dh_group_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["DiffieHellmanGroup"], |vm| {
        let name = str_of(vm, &a.arg(0))?;
        if name.to_lowercase() != "modp14" {
            return vm.throw_error("Error", format!("Unknown DH group '{}' (lumen supports modp14)", name));
        }
        let fb = st(|s| s.dhgroup_ctor.clone()).and_then(|c| c.get_own_str("prototype")).and_then(|p| p.as_obj().cloned());
        let o = Value::Obj(instance(vm, &nt, fb, ObjKind::Ordinary)?);
        let p = BigUint::from_hex(cr::dh::MODP14_HEX).unwrap_or_else(BigUint::zero);
        dh_init(vm, &o, big_to_js(&p), big_to_js(&BigUint::from_u64(2)))?;
        Ok(o)
    })
}

fn prime_bytes_len(p: &BigUint) -> usize {
    p.bits().div_ceil(8)
}

fn dh_generate_keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    with_frames(vm, &["generateKeys"], |vm| {
        let p_v = get(vm, &this, "_prime")?;
        let p = as_big(vm, &p_v)?;
        if get(vm, &this, "_private")?.is_null() {
            let x = cr::dh::generate_private(&p);
            set(vm, &this, "_private", big_to_js(&x))?;
        }
        let g_v = get(vm, &this, "_generator")?;
        let g = as_big(vm, &g_v)?;
        let x_v = get(vm, &this, "_private")?;
        let x = as_big(vm, &x_v)?;
        let y = if p.is_zero() { BigUint::zero() } else { g.modpow(&x, &p) };
        set(vm, &this, "_public", big_to_js(&y))?;
        // generateKeys loops (do/while): compiled, so the call below keeps its frame
        call_member(vm, &this, "getPublicKey", &[a.arg(0)])
    })
}

fn dh_compute_secret(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let out = with_frames(vm, &["computeSecret"], |vm| {
        let x_v = get(vm, &this, "_private")?;
        if x_v.is_null() {
            return vm.throw_error("Error", "No private key - did you forget to generate one?");
        }
        let other_v = dh_bigint(vm, &a.arg(0), &a.arg(1))?;
        let other = as_big(vm, &other_v)?;
        let p_v = get(vm, &this, "_prime")?;
        let p = as_big(vm, &p_v)?;
        if is_negative_big(&other_v) || other <= BigUint::one() || p <= BigUint::one() || other >= p.sub_u64(1) {
            return vm.throw_error("Error", "Supplied key is too small");
        }
        let x = as_big(vm, &x_v)?;
        let s = other.modpow(&x, &p).to_bytes_be_padded(prime_bytes_len(&p));
        new_buf(vm, s)
    })?;
    maybe_encode_any(vm, out, &a.arg(2))
}

fn dh_get_prime(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p_v = get(vm, &a.this, "_prime")?;
    let p = as_big(vm, &p_v)?;
    let b = new_buf(vm, p.to_bytes_be_padded(prime_bytes_len(&p)))?;
    maybe_encode_any(vm, b, &a.arg(0))
}

fn big_bytes(b: &BigUint) -> Vec<u8> {
    let v = b.to_bytes_be();
    if v.is_empty() {
        vec![]
    } else {
        v
    }
}

fn dh_get_generator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let g_v = get(vm, &a.this, "_generator")?;
    let g = match &g_v {
        Value::Num(n) => BigUint::from_u64(*n as u64),
        other => as_big(vm, other)?,
    };
    let b = new_buf(vm, big_bytes(&g))?;
    maybe_encode_any(vm, b, &a.arg(0))
}

fn dh_get_public_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = with_frames(vm, &["getPublicKey"], |vm| {
        let y_v = get(vm, &a.this, "_public")?;
        if y_v.is_null() {
            return vm.throw_error("Error", "No public key - did you forget to generate one?");
        }
        let y = as_big(vm, &y_v)?;
        let p_v = get(vm, &a.this, "_prime")?;
        let p = as_big(vm, &p_v)?;
        new_buf(vm, y.to_bytes_be_padded(prime_bytes_len(&p).max(y.to_bytes_be().len())))
    })?;
    maybe_encode_any(vm, b, &a.arg(0))
}

fn dh_get_private_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = with_frames(vm, &["getPrivateKey"], |vm| {
        let x_v = get(vm, &a.this, "_private")?;
        if x_v.is_null() {
            return vm.throw_error("Error", "No private key - did you forget to generate one?");
        }
        let x = as_big(vm, &x_v)?;
        new_buf(vm, big_bytes(&x))
    })?;
    maybe_encode_any(vm, b, &a.arg(0))
}

fn dh_set_public_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setPublicKey"], |vm| {
        let v = dh_bigint(vm, &a.arg(0), &a.arg(1))?;
        set(vm, &a.this, "_public", v)?;
        Ok(Value::Undefined)
    })
}

fn dh_set_private_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setPrivateKey"], |vm| {
        let v = dh_bigint(vm, &a.arg(0), &a.arg(1))?;
        let x = as_big(vm, &v)?;
        let p_v = get(vm, &a.this, "_prime")?;
        let p = as_big(vm, &p_v)?;
        if is_negative_big(&v) || x <= BigUint::one() || p <= BigUint::one() || x >= p.sub_u64(1) {
            return vm.throw_range("Private key is not valid for specified group");
        }
        set(vm, &a.this, "_private", v)?;
        let g_v = get(vm, &a.this, "_generator")?;
        let g = as_big(vm, &g_v)?;
        set(vm, &a.this, "_public", big_to_js(&g.modpow(&x, &p)))?;
        Ok(Value::Undefined)
    })
}

fn create_diffie_hellman(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createDiffieHellman"], |vm| {
        let ctor = st(|s| s.dh_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        let prime = a.arg(0);
        let (mut penc, mut gen, genc) = (a.arg(1), a.arg(2), a.arg(3));
        if let Value::Num(_) = prime {
            let opts = vm.obj_from(vec![("bigint", Value::Bool(true)), ("safe", Value::Bool(true))]);
            let p = with_frames(vm, &["generatePrimeSync"], |vm| generate_prime_impl(vm, &prime, &Value::Obj(opts)))?;
            let g = match &penc {
                Value::Num(n) => big_to_js(&BigUint::from_u64(*n as u64)),
                _ => big_to_js(&BigUint::from_u64(2)),
            };
            return vm.construct(&ctor, &[p, g], None);
        }
        if matches!(penc, Value::Num(_) | Value::BigInt(_)) {
            gen = penc;
            penc = Value::Undefined;
        }
        let p = dh_bigint(vm, &prime, &penc)?;
        let g = if gen.is_undefined() {
            big_to_js(&BigUint::from_u64(2))
        } else if let Value::Num(n) = gen {
            big_to_js(&BigUint::from_u64(n as u64))
        } else {
            dh_bigint(vm, &gen, &genc)?
        };
        let pb = as_big(vm, &p)?;
        let gb = as_big(vm, &g)?;
        if pb <= BigUint::from_u64(4) || gb <= BigUint::one() || gb >= pb {
            return vm.throw_range("Invalid Diffie-Hellman parameters");
        }
        vm.construct(&ctor, &[p, g], None)
    })
}

fn create_dh_group(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = st(|s| s.dhgroup_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
    vm.construct(&c, &[a.arg(0)], None)
}

fn get_diffie_hellman(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["getDiffieHellman"], |vm| create_dh_group(vm, a))
}

fn create_diffie_hellman_group(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createDiffieHellmanGroup"], |vm| create_dh_group(vm, a))
}

fn crypto_diffie_hellman(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["diffieHellman"], |vm| {
        let o = a.arg(0);
        let ok = if o.truthy() {
            let pk = get(vm, &o, "privateKey")?;
            let pubk = get(vm, &o, "publicKey")?;
            is_key_object(vm, &pk)? && is_key_object(vm, &pubk)?
        } else {
            false
        };
        if !ok {
            return vm.throw_type("diffieHellman requires privateKey and publicKey KeyObjects");
        }
        let pk = get(vm, &o, "privateKey")?;
        let pubk = get(vm, &o, "publicKey")?;
        let (x, y) = match (asym_of(&pk), asym_of(&pubk)) {
            (Some(x), Some(y)) => (x, y),
            _ => return vm.throw_type("cannot read property 'kind' of null"),
        };
        match cr::asym::diffie_hellman(&x, &y) {
            Ok(s) => new_buf(vm, s),
            Err(e) => throw(vm, e),
        }
    })
}

// ---------------------------------------------------------------- ECDH

struct EcdhState {
    d: RefCell<Option<Vec<u8>>>,
    point: RefCell<Option<Vec<u8>>>,
}

fn curve_obj(vm: &mut Vm) -> Value {
    if let Some(o) = CURVE_OBJ.with(|c| c.borrow().clone()) {
        return Value::Obj(o);
    }
    let o = vm.new_object();
    o.set_prop(key("name"), Value::str("prime256v1"), WEC);
    let hexes = [
        ("p", "ffffffff00000001000000000000000000000000ffffffffffffffffffffffff"),
        ("a", "ffffffff00000001000000000000000000000000fffffffffffffffffffffffc"),
        ("b", "5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b"),
        ("n", "ffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551"),
        ("gx", "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"),
        ("gy", "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5"),
    ];
    for (n, h) in hexes {
        o.set_prop(key(n), big_to_js(&BigUint::from_hex(h).unwrap_or_else(BigUint::zero)), WEC);
    }
    o.set_prop(key("size"), num(32.0), WEC);
    CURVE_OBJ.with(|c| *c.borrow_mut() = Some(o.clone()));
    Value::Obj(o)
}

fn ecdh_state<R>(v: &Value, f: impl FnOnce(&EcdhState) -> R) -> Option<R> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<EcdhState>().map(f),
            _ => None,
        },
        _ => None,
    }
}

/// The JS-visible Jacobian `[X, Y, Z]` of an uncompressed point.
fn point_js(vm: &mut Vm, point: &[u8]) -> Value {
    let (x, y) = if point.len() == 65 { (&point[1..33], &point[33..65]) } else { (&[][..], &[][..]) };
    let v = vec![big_to_js(&BigUint::from_bytes_be(x)), big_to_js(&BigUint::from_bytes_be(y)), big_to_js(&BigUint::one())];
    Value::Obj(vm.new_array(v))
}

fn ecdh_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["ECDH"], |vm| {
        curve_by_name(vm, &a.arg(0))?;
        let fb = st(|s| s.ecdh_ctor.clone()).and_then(|c| c.get_own_str("prototype")).and_then(|p| p.as_obj().cloned());
        let o = instance(vm, &nt, fb, ObjKind::Host(Box::new(EcdhState { d: RefCell::new(None), point: RefCell::new(None) })))?;
        let ov = Value::Obj(o);
        let c = curve_obj(vm);
        set(vm, &ov, "_curve", c)?;
        set(vm, &ov, "_private", Value::Null)?;
        set(vm, &ov, "_public", Value::Null)?;
        Ok(ov)
    })
}

fn ecdh_set_keys(vm: &mut Vm, this: &Value, d: Option<Vec<u8>>, point: Vec<u8>) -> JsResult<()> {
    if let Some(d) = &d {
        set(vm, this, "_private", big_to_js(&BigUint::from_bytes_be(d)))?;
    }
    let pj = point_js(vm, &point);
    set(vm, this, "_public", pj)?;
    ecdh_state(this, |s| {
        if d.is_some() {
            *s.d.borrow_mut() = d;
        }
        *s.point.borrow_mut() = Some(point);
    });
    Ok(())
}

fn ecdh_generate_keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    // generateKeys loops (do/while), so the reference runs it compiled: its frame stays
    with_frames(vm, &["generateKeys"], |vm| {
        let (d, point) = cr::p256::generate_keypair();
        ecdh_set_keys(vm, &this, Some(d.to_vec()), point)?;
        call_member(vm, &this, "getPublicKey", &[a.arg(0), a.arg(1)])
    })
}

/// `ecPointDecode(curve, bytes)` → uncompressed encoding
fn ec_point_decode(vm: &mut Vm, bytes: &[u8]) -> JsResult<Vec<u8>> {
    with_frames(vm, &["ecPointDecode"], |vm| match cr::p256::decode_point(bytes) {
        Ok(p) => Ok(cr::p256::encode_point(&p, cr::p256::PointFormat::Uncompressed)),
        Err(e) => throw(vm, e),
    })
}

/// `ecPointEncodeFormat(curve, point, format)`
fn ec_point_encode(vm: &mut Vm, point: &[u8], format: &Value) -> JsResult<Vec<u8>> {
    with_frames(vm, &["ecPointEncodeFormat"], |vm| {
        let f = if format.is_nullish() { cr::p256::PointFormat::Uncompressed } else {
            let s = str_of(vm, format)?;
            match cr::p256::PointFormat::from_name(&s) {
                Some(f) => f,
                None => return throw(vm, cr::p256::invalid_point_format_error(&s)),
            }
        };
        let p = match cr::p256::decode_point(point) {
            Ok(p) => p,
            Err(e) => return throw(vm, e),
        };
        Ok(cr::p256::encode_point(&p, f))
    })
}

fn ecdh_compute_secret(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let out = with_frames(vm, &["computeSecret"], |vm| {
        let d = ecdh_state(&this, |s| s.d.borrow().clone()).flatten();
        let d = match d {
            Some(d) => d,
            None => return vm.throw_error("Error", "Private key is not set"),
        };
        let bytes = to_bytes_vec(vm, &a.arg(0), &a.arg(1))?;
        let q = ec_point_decode(vm, &bytes)?;
        match cr::p256::ecdh(&d, &q) {
            Ok(x) => new_buf(vm, x.to_vec()),
            Err(e) => throw(vm, e),
        }
    })?;
    maybe_encode_any(vm, out, &a.arg(2))
}

fn ecdh_get_private_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = with_frames(vm, &["getPrivateKey"], |vm| {
        let d = ecdh_state(&a.this, |s| s.d.borrow().clone()).flatten();
        match d {
            Some(d) => new_buf(vm, BigUint::from_bytes_be(&d).to_bytes_be_padded(32)),
            None => vm.throw_error("Error", "Private key is not set"),
        }
    })?;
    maybe_encode_any(vm, b, &a.arg(0))
}

fn ecdh_get_public_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = with_frames(vm, &["getPublicKey"], |vm| {
        let p = ecdh_state(&a.this, |s| s.point.borrow().clone()).flatten();
        let p = match p {
            Some(p) => p,
            None => return vm.throw_error("Error", "Public key is not set"),
        };
        let enc = ec_point_encode(vm, &p, &a.arg(1))?;
        new_buf(vm, enc)
    })?;
    maybe_encode_any(vm, b, &a.arg(0))
}

fn ecdh_set_private_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setPrivateKey"], |vm| {
        let b = to_bytes_vec(vm, &a.arg(0), &a.arg(1))?;
        let point = match cr::p256::public_from_private(&b) {
            Ok(p) => p,
            Err(e) => return throw(vm, e),
        };
        let d = BigUint::from_bytes_be(&b).to_bytes_be_padded(32);
        ecdh_set_keys(vm, &a.this, Some(d), point)?;
        Ok(Value::Undefined)
    })
}

fn ecdh_set_public_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["setPublicKey"], |vm| {
        let b = to_bytes_vec(vm, &a.arg(0), &a.arg(1))?;
        let p = ec_point_decode(vm, &b)?;
        ecdh_set_keys(vm, &a.this, None, p)?;
        Ok(Value::Undefined)
    })
}

fn ecdh_convert_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = with_frames(vm, &["convertKey"], |vm| {
        curve_by_name(vm, &a.arg(1))?;
        let bytes = to_bytes_vec(vm, &a.arg(0), &a.arg(2))?;
        let p = ec_point_decode(vm, &bytes)?;
        let enc = ec_point_encode(vm, &p, &a.arg(4))?;
        new_buf(vm, enc)
    })?;
    maybe_encode_any(vm, b, &a.arg(3))
}

fn create_ecdh(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["createECDH"], |vm| {
        let c = st(|s| s.ecdh_ctor.clone()).map(Value::Obj).unwrap_or(Value::Undefined);
        vm.construct(&c, &[a.arg(0)], None)
    })
}

// ---------------------------------------------------------------- primes

fn candidate_big(vm: &mut Vm, v: &Value) -> JsResult<(BigUint, bool)> {
    if let Value::BigInt(b) = v {
        return Ok((js_big_to_biguint(b), b.is_negative()));
    }
    let bytes = to_bytes_vec(vm, v, &Value::Undefined)?;
    Ok((BigUint::from_bytes_be(&bytes), false))
}

fn check_prime_impl(vm: &mut Vm, cand: &Value, options: &Value) -> JsResult<Value> {
    let (n, neg) = candidate_big(vm, cand)?;
    let checks = if options.truthy() { get(vm, options, "checks")? } else { Value::Undefined };
    let checks = if checks.truthy() { vm.to_number(&checks)? } else { 40.0 };
    if neg {
        return Ok(Value::Bool(false));
    }
    Ok(Value::Bool(cr::prime::is_probable_prime(&n, checks.max(1.0) as usize)))
}

fn check_prime_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["checkPrimeSync"], |vm| check_prime_impl(vm, &a.arg(0), &a.arg(1)))
}

fn check_prime(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["checkPrime"], |vm| {
        let (mut options, mut cb) = (a.arg(1), a.arg(2));
        if options.is_callable() {
            cb = options;
            options = Value::Undefined;
        }
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["checkPrimeSync"], |vm| check_prime_impl(vm, &a.arg(0), &options));
        defer_cb(vm, &cb, r.map(|v| vec![v]));
        Ok(Value::Undefined)
    })
}

fn generate_prime_impl(vm: &mut Vm, size: &Value, options: &Value) -> JsResult<Value> {
    let opts = if options.truthy() { options.clone() } else { Value::Obj(vm.new_object()) };
    let add_v = get(vm, &opts, "add")?;
    let safe = get(vm, &opts, "safe")?.truthy();
    let mut add: Option<BigUint> = None;
    let mut rem: Option<BigUint> = None;
    if !add_v.is_undefined() {
        let (a_b, a_neg) = candidate_big(vm, &add_v)?;
        let rem_v = get(vm, &opts, "rem")?;
        let (r_b, r_neg) = if rem_v.is_undefined() { (BigUint::from_u64(if safe { 3 } else { 1 }), false) } else { candidate_big(vm, &rem_v)? };
        if a_neg || a_b.is_zero() {
            return vm.throw_range("generatePrime option 'add' must be greater than zero");
        }
        if r_neg || r_b >= a_b {
            return vm.throw_range("generatePrime option 'rem' must be non-negative and less than 'add'");
        }
        let gt2 = vm.op_compare(crate::bytecode::Op::Gt, size, &num(2.0))?;
        if gt2 && a_b.is_even() && r_b.is_even() {
            return vm.throw_range("generatePrime add/rem constraints cannot produce an odd prime");
        }
        add = Some(a_b);
        rem = Some(r_b);
    }
    let bits = with_frames(vm, &["randomPrime"], |vm| match size {
        Value::Num(n) if n.fract() == 0.0 && *n >= 2.0 && n.is_finite() => Ok(*n as usize),
        _ => vm.throw_range("prime size must be an integer >= 2 bits"),
    })?;
    let p = cr::prime::generate_prime(bits, safe, add.as_ref(), rem.as_ref());
    if get(vm, &opts, "bigint")?.truthy() {
        return Ok(big_to_js(&p));
    }
    Ok(array_buffer(vm, p.to_bytes_be_padded(bits.div_ceil(8))))
}

fn generate_prime_sync(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["generatePrimeSync"], |vm| generate_prime_impl(vm, &a.arg(0), &a.arg(1)))
}

fn generate_prime(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["generatePrime"], |vm| {
        let (mut options, mut cb) = (a.arg(1), a.arg(2));
        if options.is_callable() {
            cb = options;
            options = Value::Undefined;
        }
        if !cb.is_callable() {
            return vm.throw_type("callback must be a function");
        }
        let r = with_frames(vm, &["generatePrimeSync"], |vm| generate_prime_impl(vm, &a.arg(0), &options));
        defer_cb(vm, &cb, r.map(|v| vec![v]));
        Ok(Value::Undefined)
    })
}

// ---------------------------------------------------------------- X509Certificate

struct X509State {
    cert: cr::x509::Certificate,
}

fn x509_of(v: &Value) -> Option<cr::x509::Certificate> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::Host(h) => h.downcast_ref::<X509State>().map(|s| s.cert.clone()),
            _ => None,
        },
        _ => None,
    }
}

fn new_date(vm: &mut Vm, ms: i64) -> JsResult<Value> {
    let d = vm.global.get_own_str("Date").unwrap_or(Value::Undefined);
    vm.construct(&d, &[num(ms as f64)], None)
}

fn x509_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let nt = require_new(vm, a)?;
    with_frames(vm, &["X509Certificate"], |vm| {
        let input = a.arg(0);
        let der: Vec<u8> = {
            let is_str = matches!(input, Value::Str(_));
            let u8_text = match &input {
                Value::Obj(_) if ta_kind(&input) == Some(TAKind::Uint8) => {
                    let t = String::from_utf8_lossy(&raw_bytes(&input)).to_string();
                    if t.contains("BEGIN CERTIFICATE") {
                        Some(t)
                    } else {
                        None
                    }
                }
                _ => None,
            };
            if is_str || u8_text.is_some() {
                let text = match &input {
                    Value::Str(s) => s.to_rust_string(),
                    _ => u8_text.unwrap_or_default(),
                };
                let (label, der) = with_frames(vm, &["pemDecode"], |vm| match crate::crypto::asn1::pem_decode(&text) {
                    Ok(r) => Ok(r),
                    Err(e) => throw(vm, e),
                })?;
                if label != "CERTIFICATE" {
                    return vm.throw_error("Error", "X509: expected a CERTIFICATE PEM block");
                }
                der
            } else {
                to_bytes_vec(vm, &input, &Value::Undefined)?
            }
        };
        let cert = match cr::x509::Certificate::parse(&der) {
            Ok(c) => c,
            Err(e) => return throw(vm, e),
        };
        let fb = st(|s| s.x509_proto.clone());
        let o = instance(vm, &nt, fb, ObjKind::Host(Box::new(X509State { cert: cert.clone() })))?;
        let ov = Value::Obj(o.clone());
        let raw = new_buf(vm, cert.raw.clone())?;
        o.set_prop(key("raw"), raw, WEC);
        o.set_prop(key("serialNumber"), Value::str(&cert.serial_number), WEC);
        o.set_prop(key("issuer"), Value::str(&cert.issuer), WEC);
        o.set_prop(key("subject"), Value::str(&cert.subject), WEC);
        let vf = new_date(vm, cert.valid_from_ms)?;
        o.set_prop(key("validFromDate"), vf, WEC);
        let vt = new_date(vm, cert.valid_to_ms)?;
        o.set_prop(key("validToDate"), vt, WEC);
        o.set_prop(key("validFrom"), Value::str(&cert.valid_from), WEC);
        o.set_prop(key("validTo"), Value::str(&cert.valid_to), WEC);
        o.set_prop(key("fingerprint"), Value::str(&cert.fingerprint), WEC);
        o.set_prop(key("fingerprint256"), Value::str(&cert.fingerprint256), WEC);
        o.set_prop(key("fingerprint512"), Value::str(&cert.fingerprint512), WEC);
        let spki = new_buf(vm, cert.spki.clone())?;
        let ko = vm.obj_from(vec![("key", spki), ("format", Value::str("der")), ("type", Value::str("spki"))]);
        let pk = create_public_key_impl(vm, &Value::Obj(ko))?;
        o.set_prop(key("publicKey"), pk, WEC);
        o.set_prop(key("ca"), Value::Bool(cert.ca), WEC);
        o.set_prop(key("keyUsage"), Value::Undefined, WEC);
        let mut alts = Vec::new();
        for (t, v) in &cert.alt_names {
            alts.push(Value::Obj(vm.obj_from(vec![("type", Value::str(t)), ("value", Value::str(v))])));
        }
        let alt_arr = vm.new_array(alts);
        o.set_prop(key("_altNames"), Value::Obj(alt_arr), WEC);
        o.set_prop(key("subjectAltName"), cert.subject_alt_name.as_deref().map(Value::str).unwrap_or(Value::Undefined), WEC);
        o.set_prop(key("infoAccess"), Value::Undefined, WEC);
        o.set_prop(key("issuerCertificate"), Value::Undefined, WEC);
        let tbs = u8array(vm, cert.tbs.clone());
        o.set_prop(key("_tbs"), tbs, WEC);
        o.set_prop(key("_signatureAlgorithm"), cert.signature_digest.map(|h| Value::str(hash_name(h))).unwrap_or(Value::Undefined), WEC);
        let sig = u8array(vm, cert.signature.clone());
        o.set_prop(key("_signature"), sig, WEC);
        Ok(ov)
    })
}

fn x509_check_issued(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["checkIssued"], |vm| {
        let other = a.arg(0);
        let c = st(|s| s.x509_ctor.clone());
        if !is_instance(vm, &other, &c)? {
            return vm.throw_type("checkIssued expects an X509Certificate");
        }
        let i = get(vm, &a.this, "issuer")?;
        let s = get(vm, &other, "subject")?;
        Ok(Value::Bool(Value::strict_eq(&i, &s)))
    })
}

fn x509_check_private_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = with_frames(vm, &["checkPrivateKey"], |vm| {
        let k = create_public_key_impl(vm, &a.arg(0))?;
        let mine = get(vm, &a.this, "publicKey")?;
        Ok(match (asym_of(&k), asym_of(&mine)) {
            (Some(x), Some(y)) => x.jwk_fields() == y.jwk_fields(),
            _ => false,
        })
    });
    Ok(Value::Bool(r.unwrap_or(false)))
}

fn x509_verify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    with_frames(vm, &["verify"], |vm| {
        let alg = get(vm, &a.this, "_signatureAlgorithm")?;
        if !alg.truthy() {
            return Ok(Value::Bool(false));
        }
        let tbs = get(vm, &a.this, "_tbs")?;
        let sig = get(vm, &a.this, "_signature")?;
        with_frames(vm, &["cryptoVerify"], |vm| verify_digest(vm, &alg, &tbs, &a.arg(0), &sig))
    })
}

fn x509_check_host(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = a.arg(0);
    let host = lower_of(vm, &name)?;
    let cert = match x509_of(&a.this) {
        Some(c) => c,
        None => return Ok(Value::Undefined),
    };
    let _ = cert.check_host(&host);
    let alts = get(vm, &a.this, "_altNames")?;
    let items = crate::builtins::array::array_like_to_vec(vm, &alts)?;
    let mut candidates = Vec::new();
    for it in &items {
        let t = get(vm, it, "type")?;
        if matches!(&t, Value::Str(s) if s.eq_str("DNS")) {
            let v = get(vm, it, "value")?;
            candidates.push(str_of(vm, &v)?);
        }
    }
    if candidates.is_empty() {
        let subj = get(vm, &a.this, "subject")?;
        let s = str_of(vm, &subj)?;
        if let Some(cn) = s.split('\n').find(|f| f.starts_with("CN=")) {
            candidates.push(cn[3..].to_string());
        }
    }
    for c in candidates {
        let pattern = c.to_lowercase();
        if pattern == host {
            return Ok(name);
        }
        if pattern.starts_with("*.") && host.ends_with(&pattern[1..]) && host.split('.').count() == pattern.split('.').count() {
            return Ok(name);
        }
    }
    Ok(Value::Undefined)
}

fn x509_check_alt(vm: &mut Vm, a: &Args, ty: &str) -> JsResult<Value> {
    let arg = a.arg(0);
    let target = lower_of(vm, &arg)?;
    let alts = get(vm, &a.this, "_altNames")?;
    let items = crate::builtins::array::array_like_to_vec(vm, &alts)?;
    for it in &items {
        let t = get(vm, it, "type")?;
        if matches!(&t, Value::Str(s) if s.eq_str(ty)) {
            let v = get(vm, it, "value")?;
            if str_of(vm, &v)?.to_lowercase() == target {
                return Ok(arg);
            }
        }
    }
    Ok(Value::Undefined)
}

fn x509_check_email(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    x509_check_alt(vm, a, "email")
}

fn x509_check_ip(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    x509_check_alt(vm, a, "IP Address")
}

fn x509_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let raw = get(vm, &a.this, "raw")?;
    Ok(Value::str(&crate::crypto::asn1::pem_encode("CERTIFICATE", &raw_bytes(&raw))))
}

fn x509_to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_member(vm, &a.this, "toString", &[])
}

// ---------------------------------------------------------------- Certificate (SPKAC)

fn spkac_bytes(vm: &mut Vm, spkac: &Value, enc: &Value) -> JsResult<Vec<u8>> {
    if let Value::Str(_) = spkac {
        let b = buffer::buffer_from_value(vm, spkac, enc)?;
        return Ok(raw_bytes(&b));
    }
    to_bytes_vec(vm, spkac, &Value::Undefined)
}

fn cert_export_challenge(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = spkac_bytes(vm, &a.arg(0), &a.arg(1)).ok().and_then(|b| cr::x509::parse_spkac(&b).ok());
    match r {
        Some(s) => new_buf(vm, s.challenge),
        None => new_buf(vm, Vec::new()),
    }
}

fn cert_export_public_key(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = spkac_bytes(vm, &a.arg(0), &a.arg(1)).ok().and_then(|b| cr::x509::parse_spkac(&b).ok());
    match r {
        Some(s) => {
            let pem = crate::crypto::asn1::pem_encode("PUBLIC KEY", &s.public_key_der);
            new_buf(vm, pem.into_bytes())
        }
        None => new_buf(vm, Vec::new()),
    }
}

fn cert_verify_spkac(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = spkac_bytes(vm, &a.arg(0), &a.arg(1)).ok().map(|b| cr::x509::verify_spkac(&b));
    Ok(Value::Bool(r.unwrap_or(false)))
}

/// `function Certificate() { if (!(this instanceof Certificate)) return new Certificate(); }`
fn certificate_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = st(|s| s.certificate_ctor.clone());
    if is_instance(vm, &a.this, &c)? {
        return Ok(Value::Undefined);
    }
    let cv = c.map(Value::Obj).unwrap_or(Value::Undefined);
    vm.construct(&cv, &[], None)
}

// ---------------------------------------------------------------- assembly

/// Builds the exports from `sign` to `Certificate` in the reference's order.
fn asym_classes(vm: &mut Vm) -> Vec<(&'static str, Value)> {
    let mut out: Vec<(&'static str, Value)> = Vec::new();
    let v = plain(vm, "cryptoSign", 4, crypto_sign);
    out.push(("sign", v));
    let v = plain(vm, "cryptoVerify", 5, crypto_verify);
    out.push(("verify", v));
    let v = arrow(vm, "createSign", 1, create_sign);
    out.push(("createSign", v));
    let v = arrow(vm, "createVerify", 1, create_verify);
    out.push(("createVerify", v));
    let (sign_c, sign_p) = make_class(vm, "Sign", 1, sign_ctor, &[("update", 2, hash_update), ("sign", 2, sign_sign)]);
    let (verify_c, verify_p) = make_class(vm, "Verify", 1, verify_ctor, &[("update", 2, hash_update), ("verify", 3, verify_verify)]);
    let _ = (sign_p, verify_p);
    out.push(("Sign", Value::Obj(sign_c.clone())));
    out.push(("Verify", Value::Obj(verify_c.clone())));
    let v = plain(vm, "privateEncrypt", 2, private_encrypt);
    out.push(("privateEncrypt", v));
    let v = plain(vm, "privateDecrypt", 2, private_decrypt);
    out.push(("privateDecrypt", v));
    let v = plain(vm, "publicEncrypt", 2, public_encrypt);
    out.push(("publicEncrypt", v));
    let v = plain(vm, "publicDecrypt", 2, public_decrypt);
    out.push(("publicDecrypt", v));
    let v = plain(vm, "createPublicKey", 1, create_public_key);
    out.push(("createPublicKey", v));
    let v = plain(vm, "createPrivateKey", 1, create_private_key);
    out.push(("createPrivateKey", v));
    let v = plain(vm, "generateKeyPair", 3, generate_key_pair);
    out.push(("generateKeyPair", v));
    let v = plain(vm, "generateKeyPairSync", 2, generate_key_pair_sync);
    out.push(("generateKeyPairSync", v));
    let (dh_c, dh_p) = make_class(
        vm,
        "DiffieHellman",
        1,
        dh_ctor,
        &[
            ("generateKeys", 1, dh_generate_keys),
            ("computeSecret", 3, dh_compute_secret),
            ("getPrime", 1, dh_get_prime),
            ("getGenerator", 1, dh_get_generator),
            ("getPublicKey", 1, dh_get_public_key),
            ("getPrivateKey", 1, dh_get_private_key),
            ("setPublicKey", 2, dh_set_public_key),
            ("setPrivateKey", 2, dh_set_private_key),
        ],
    );
    let (dhg_c, dhg_p) = make_class(vm, "DiffieHellmanGroup", 1, dh_group_ctor, &[]);
    dhg_p.borrow_mut().proto = Some(dh_p.clone());
    dhg_c.borrow_mut().proto = Some(dh_c.clone());
    out.push(("DiffieHellman", Value::Obj(dh_c.clone())));
    out.push(("DiffieHellmanGroup", Value::Obj(dhg_c.clone())));
    let (ecdh_c, _ecdh_p) = make_class(
        vm,
        "ECDH",
        1,
        ecdh_ctor,
        &[
            ("generateKeys", 2, ecdh_generate_keys),
            ("computeSecret", 3, ecdh_compute_secret),
            ("getPrivateKey", 1, ecdh_get_private_key),
            ("getPublicKey", 2, ecdh_get_public_key),
            ("setPrivateKey", 2, ecdh_set_private_key),
            ("setPublicKey", 2, ecdh_set_public_key),
        ],
    );
    vm.def_method(&ecdh_c, "convertKey", 5, ecdh_convert_key);
    out.push(("ECDH", Value::Obj(ecdh_c.clone())));
    let v = plain(vm, "createDiffieHellman", 4, create_diffie_hellman);
    out.push(("createDiffieHellman", v));
    let v = plain(vm, "createDiffieHellmanGroup", 1, create_diffie_hellman_group);
    out.push(("createDiffieHellmanGroup", v));
    let v = plain(vm, "createECDH", 1, create_ecdh);
    out.push(("createECDH", v));
    let v = plain(vm, "getDiffieHellman", 1, get_diffie_hellman);
    out.push(("getDiffieHellman", v));
    let v = plain(vm, "diffieHellman", 1, crypto_diffie_hellman);
    out.push(("diffieHellman", v));
    let v = plain(vm, "checkPrime", 3, check_prime);
    out.push(("checkPrime", v));
    let v = plain(vm, "checkPrimeSync", 2, check_prime_sync);
    out.push(("checkPrimeSync", v));
    let v = plain(vm, "generatePrime", 3, generate_prime);
    out.push(("generatePrime", v));
    let v = plain(vm, "generatePrimeSync", 2, generate_prime_sync);
    out.push(("generatePrimeSync", v));
    let (x509_c, x509_p) = make_class(
        vm,
        "X509Certificate",
        1,
        x509_ctor,
        &[
            ("checkIssued", 1, x509_check_issued),
            ("checkPrivateKey", 1, x509_check_private_key),
            ("verify", 1, x509_verify),
            ("checkHost", 1, x509_check_host),
            ("checkEmail", 1, x509_check_email),
            ("checkIP", 1, x509_check_ip),
            ("toString", 0, x509_to_string),
            ("toJSON", 0, x509_to_json),
        ],
    );
    out.push(("X509Certificate", Value::Obj(x509_c.clone())));
    let cert = buffer::plain_function(vm, "Certificate", 0, certificate_fn);
    let cert_proto = cert.get_own_str("prototype").and_then(|p| p.as_obj().cloned());
    for (n, f) in [("exportChallenge", cert_export_challenge as NativeFn), ("exportPublicKey", cert_export_public_key), ("verifySpkac", cert_verify_spkac)] {
        let fname = match n {
            "exportChallenge" => "certificateExportChallenge",
            "exportPublicKey" => "certificateExportPublicKey",
            _ => "certificateVerifySpkac",
        };
        let fo = plain(vm, fname, 2, f);
        if let Some(p) = &cert_proto {
            p.set_prop(key(n), fo.clone(), WEC);
        }
        cert.set_prop(key(n), fo, WEC);
    }
    out.push(("Certificate", Value::Obj(cert.clone())));
    ST.with(|s| {
        let mut s = s.borrow_mut();
        s.sign_ctor = Some(sign_c);
        s.verify_ctor = Some(verify_c);
        s.dh_ctor = Some(dh_c);
        s.dh_proto = Some(dh_p);
        s.dhgroup_ctor = Some(dhg_c);
        s.ecdh_ctor = Some(ecdh_c);
        s.x509_ctor = Some(x509_c);
        s.x509_proto = Some(x509_p);
        s.certificate_ctor = Some(cert);
    });
    out
}
