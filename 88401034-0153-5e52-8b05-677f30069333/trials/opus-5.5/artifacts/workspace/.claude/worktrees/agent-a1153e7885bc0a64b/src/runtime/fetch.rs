// fetch / Headers / Request / Response, the `Lumen` global (`Lumen.serve` HTTP/1.1 server,
// `Lumen.upgradeWebSocket`), and the WebSocket / EventSource clients.
//
// Like the streams module, these follow the reference runtime's (JS-level) object model: state
// lives in own properties (`status`, `headers`, `_bodyBytes`, `_map`, ...), body consumption is a
// small chain of async steps, and network I/O happens on background threads whose results are
// delivered back to the event loop.

use super::streams::{
    await_value, call_method, construct, decoder_decode, func, get, get_sym, global, host, invoke, is_array_buffer, is_str, is_typed_array,
    is_view, iter_result, js_string, make_dom_exception, new_arr, new_obj, new_this, new_u8, put, put_sym, rejected, settle,
    str_to_utf8, type_error, unhost, u8_view_of, Decoder,
};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

pub const VERSION: &str = "0.1.3";

// =====================================================================================
// Module state
// =====================================================================================

pub struct FCtx {
    pub k_consumed: Sym,
    pub k_source: Sym,
    pub k_body_stream: Sym,
    pub k_conn: Sym,
    pub headers: Obj,
    pub headers_proto: Obj,
    pub request: Obj,
    pub request_proto: Obj,
    pub response: Obj,
    pub response_proto: Obj,
    pub map_ctor: Value,
    pub hiter_protos: [Obj; 3],
    pub ws: Obj,
    pub ws_proto: Obj,
    pub es: Obj,
    pub es_proto: Obj,
}

thread_local! {
    static FCTX: RefCell<Option<Rc<FCtx>>> = const { RefCell::new(None) };
    static SERVERS: RefCell<HashMap<u64, Rc<ServerState>>> = RefCell::new(HashMap::new());
    static CONNS: RefCell<HashMap<u64, TcpStream>> = RefCell::new(HashMap::new());
}

fn fctx() -> Rc<FCtx> {
    FCTX.with(|c| c.borrow().clone()).expect("fetch: not initialised")
}

fn sym(desc: &str) -> Sym {
    Sym::new(Some(JsStr::from_str(desc)))
}

pub fn setup(vm: &mut Vm) {
    let k_consumed = sym("bodyConsumed");
    let k_source = sym("bodySourceStream");
    let k_body_stream = sym("bodyStream");
    let k_conn = sym("lumen.serve.connection");

    // Headers
    let headers_proto = vm.new_object();
    let headers = vm.native_ctor("Headers", 1, headers_construct, &headers_proto);
    vm.def_method(&headers_proto, "append", 2, headers_append);
    vm.def_method(&headers_proto, "delete", 1, headers_delete);
    vm.def_method(&headers_proto, "get", 1, headers_get);
    vm.def_method(&headers_proto, "has", 1, headers_has);
    vm.def_method(&headers_proto, "set", 2, headers_set);
    vm.def_method(&headers_proto, "forEach", 2, headers_for_each);
    let gen_proto = vm.intr.generator_proto.clone();
    let mut hiter_protos = Vec::new();
    for (name, f) in [("entries", headers_entries as NativeFn), ("keys", headers_keys), ("values", headers_values)] {
        let m = vm.def_method(&headers_proto, name, 0, f);
        let p = Obj::new(Some(gen_proto.clone()), ObjKind::Ordinary);
        vm.def_method(&p, "next", 1, hiter_next);
        vm.def_method(&p, "return", 1, hiter_return);
        vm.def_method(&p, "throw", 1, hiter_throw);
        m.set_prop(PropKey::from_str("prototype"), Value::Obj(p.clone()), WRITABLE);
        hiter_protos.push(p);
    }
    vm.def_method(&headers_proto, "_pairs", 0, headers_pairs);
    let si = vm.intr.sym_iterator.clone();
    vm.def_sym_method(&headers_proto, &si, "[Symbol.iterator]", 0, |vm, a| invoke(vm, &a.this, "entries", &[]));

    // Request
    let request_proto = vm.new_object();
    let request = vm.native_ctor("Request", 1, request_construct, &request_proto);
    vm.def_method(&request_proto, "clone", 0, request_clone);
    install_body_mixin(vm, &request_proto);

    // Response
    let response_proto = vm.new_object();
    let response = vm.native_ctor("Response", 0, response_construct, &response_proto);
    vm.def_method(&response, "json", 2, response_json);
    vm.def_method(&response, "error", 0, response_error);
    vm.def_getter(&response_proto, "ok", response_ok);
    vm.def_method(&response_proto, "clone", 0, response_clone);
    install_body_mixin(vm, &response_proto);

    // fetch
    let fetch = vm.native_fn("fetch", 1, fetch_fn);
    plain_function_prototype(vm, &fetch);

    // WebSocket / EventSource (extend the global EventTarget when available)
    let et = global(vm, "EventTarget");
    let (et_ctor, et_proto) = match &et {
        Value::Obj(o) => {
            let p = vm.get_str(o, "prototype").unwrap_or(Value::Undefined);
            (Some(o.clone()), p.as_obj().cloned())
        }
        _ => (None, None),
    };
    let ws_proto = Obj::new(Some(et_proto.clone().unwrap_or_else(|| vm.intr.object_proto.clone())), ObjKind::Ordinary);
    let ws = vm.native_ctor("WebSocket", 2, ws_construct, &ws_proto);
    let es_proto = Obj::new(Some(et_proto.unwrap_or_else(|| vm.intr.object_proto.clone())), ObjKind::Ordinary);
    let es = vm.native_ctor("EventSource", 1, es_construct, &es_proto);
    if let Some(etc) = &et_ctor {
        ws.borrow_mut().proto = Some(etc.clone());
        es.borrow_mut().proto = Some(etc.clone());
    }
    install_websocket(vm, &ws, &ws_proto);
    install_event_source(vm, &es, &es_proto);

    let map_ctor = global(vm, "Map");
    let c = FCtx {
        k_consumed,
        k_source,
        k_body_stream,
        k_conn,
        headers: headers.clone(),
        headers_proto,
        request: request.clone(),
        request_proto,
        response: response.clone(),
        response_proto,
        map_ctor,
        hiter_protos: [hiter_protos[0].clone(), hiter_protos[1].clone(), hiter_protos[2].clone()],
        ws: ws.clone(),
        ws_proto,
        es: es.clone(),
        es_proto,
    };
    FCTX.with(|x| *x.borrow_mut() = Some(Rc::new(c)));

    // Lumen
    let lumen = vm.new_object();
    let serve = vm.native_fn("serve", 2, lumen_serve);
    plain_function_prototype(vm, &serve);
    lumen.set_str("serve", Value::Obj(serve), WEC);
    let up = vm.native_fn("upgradeWebSocket", 1, lumen_upgrade_websocket);
    plain_function_prototype(vm, &up);
    lumen.set_str("upgradeWebSocket", Value::Obj(up), WEC);
    lumen.set_str("version", Value::str(VERSION), ENUMERABLE | CONFIGURABLE);

    for (n, o) in [("Headers", headers), ("Request", request), ("Response", response), ("fetch", fetch), ("WebSocket", ws), ("EventSource", es), ("Lumen", lumen)] {
        vm.global.set_prop(PropKey::from_str(n), Value::Obj(o), WEC);
    }
}

#[allow(unused_variables, dead_code)]
pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    Value::Obj(vm.new_object())
}

/// Give a native function the shape of a plain JS `function` declaration: constructible, with
/// an ordinary `prototype` object.
fn plain_function_prototype(vm: &mut Vm, f: &Obj) {
    vm.make_ctor(f);
    let p = vm.new_object();
    p.set_prop(PropKey::from_str("constructor"), Value::Obj(f.clone()), WC);
    f.set_prop(PropKey::from_str("prototype"), Value::Obj(p), WRITABLE);
}

#[allow(dead_code)]
pub fn conn_symbol() -> Sym {
    fctx().k_conn.clone()
}

// =====================================================================================
// Small helpers
// =====================================================================================

/// `for (const item of iterable) body(item)` with iterator closing on abrupt completion.
fn for_of(vm: &mut Vm, iterable: &Value, mut body: impl FnMut(&mut Vm, Value) -> JsResult<()>) -> JsResult<()> {
    let (it, next) = vm.get_iterator(iterable)?;
    let itv = Value::Obj(it);
    loop {
        let item = match vm.iter_step(&itv, &next)? {
            Some(v) => v,
            None => return Ok(()),
        };
        if let Err(e) = body(vm, item) {
            let _ = vm.iterator_close(&itv);
            return Err(e);
        }
    }
}

fn is_ws_char(u: u16) -> bool {
    matches!(u, 0x09 | 0x0A | 0x0B | 0x0C | 0x0D | 0x20 | 0xA0 | 0x1680 | 0x2000..=0x200A | 0x2028 | 0x2029 | 0x202F | 0x205F | 0x3000 | 0xFEFF)
}

/// `String.prototype.trim`
pub fn js_trim(s: &JsStr) -> JsStr {
    let u = s.units();
    let mut a = 0;
    let mut b = u.len();
    while a < b && is_ws_char(u[a]) {
        a += 1;
    }
    while b > a && is_ws_char(u[b - 1]) {
        b -= 1;
    }
    if a == 0 && b == u.len() {
        return s.clone();
    }
    JsStr::from_units(u[a..b].to_vec())
}

fn is_token_char(u: u16) -> bool {
    u < 128 && {
        let c = u as u8;
        c.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&c)
    }
}

/// normalizeHeaderName: validate as an HTTP token, lowercase.
fn normalize_header_name(vm: &mut Vm, name: &Value) -> JsResult<Value> {
    let s = js_string(vm, name)?;
    let u = s.units();
    if u.is_empty() || !u.iter().all(|&c| is_token_char(c)) {
        return vm.throw_type(format!("invalid header name '{}'", s.to_rust_string()));
    }
    let lower: Vec<u16> = u.iter().map(|&c| if (b'A' as u16..=b'Z' as u16).contains(&c) { c + 32 } else { c }).collect();
    Ok(Value::Str(JsStr::from_units(lower)))
}

fn str_value(vm: &mut Vm, v: &Value) -> JsResult<String> {
    Ok(vm.to_string(v)?.to_rust_string())
}

fn not_defined(vm: &mut Vm, name: &str) -> Value {
    vm.make_error("ReferenceError", &format!("{} is not defined", name))
}

/// `new <globalName>(...args)` for a class provided elsewhere in the runtime.
fn construct_global(vm: &mut Vm, name: &str, args: &[Value]) -> JsResult<Value> {
    let c = global(vm, name);
    if !matches!(&c, Value::Obj(o) if o.is_constructor()) {
        return Err(not_defined(vm, name));
    }
    vm.construct(&c, args, None)
}

fn instance_of_global(vm: &mut Vm, v: &Value, name: &str) -> bool {
    let c = global(vm, name);
    if !c.is_callable() || !v.is_object() {
        return false;
    }
    vm.instance_of(v, &c).unwrap_or(false)
}

fn bytes_from_u8(v: &Value) -> Vec<u8> {
    super::streams::bytes_of_buffer_source(v)
}

// =====================================================================================
// Headers
// =====================================================================================

fn headers_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = new_this(vm, a, &c.headers_proto)?;
    let map = vm.construct(&c.map_ctor, &[], None)?;
    put(vm, &this, "_map", map)?;
    let init = a.arg(0);
    if vm.instance_of(&init, &Value::Obj(c.headers.clone()))? {
        for_of(vm, &init, |vm, entry| {
            let k = get(vm, &entry, "0")?;
            let v = get(vm, &entry, "1")?;
            invoke(vm, &this, "append", &[k, v]).map(|_| ())
        })?;
    } else if crate::builtins::array::is_array(vm, &init)? {
        for_of(vm, &init, |vm, pair| {
            let ok = pair.truthy() && {
                let l = get(vm, &pair, "length")?;
                Value::strict_eq(&l, &Value::Num(2.0))
            };
            if !ok {
                return vm.throw_type("Headers: init pair needs two items");
            }
            let k = get(vm, &pair, "0")?;
            let v = get(vm, &pair, "1")?;
            invoke(vm, &this, "append", &[k, v]).map(|_| ())
        })?;
    } else if init.truthy() && init.type_of() == "object" {
        let o = init.as_obj().unwrap().clone();
        let keys = vm.enumerable_own_keys(&o)?;
        for k in keys {
            let v = vm.get(&o, &PropKey::Str(k.clone()), &init)?;
            invoke(vm, &this, "append", &[Value::Str(k), v])?;
        }
    }
    Ok(this)
}

fn hit_entry(vm: &mut Vm, key: &Value, value: Value) -> Value {
    Value::Obj(vm.obj_from(vec![("name", key.clone()), ("value", value)]))
}

fn headers_append(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let key = normalize_header_name(vm, &a.arg(0))?;
    let value = js_string(vm, &a.arg(1))?;
    let value = js_trim(&value);
    let map = get(vm, &this, "_map")?;
    let existing = invoke(vm, &map, "get", &[key.clone()])?;
    let v = if existing.truthy() {
        let ev = get(vm, &existing, "value")?;
        let evs = vm.to_string(&ev)?;
        let mut u = evs.units().to_vec();
        u.extend_from_slice(&[b',' as u16, b' ' as u16]);
        u.extend_from_slice(value.units());
        Value::Str(JsStr::from_units(u))
    } else {
        Value::Str(value)
    };
    let entry = hit_entry(vm, &key, v);
    let map = get(vm, &this, "_map")?;
    invoke(vm, &map, "set", &[key, entry])?;
    Ok(Value::Undefined)
}

fn headers_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let map = get(vm, &a.this, "_map")?;
    let del = get(vm, &map, "delete")?;
    let key = normalize_header_name(vm, &a.arg(0))?;
    call_method(vm, &del, &map, "delete", &[key])?;
    Ok(Value::Undefined)
}

fn headers_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let map = get(vm, &a.this, "_map")?;
    let g = get(vm, &map, "get")?;
    let key = normalize_header_name(vm, &a.arg(0))?;
    let hit = call_method(vm, &g, &map, "get", &[key])?;
    if hit.truthy() {
        get(vm, &hit, "value")
    } else {
        Ok(Value::Null)
    }
}

fn headers_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let map = get(vm, &a.this, "_map")?;
    let h = get(vm, &map, "has")?;
    let key = normalize_header_name(vm, &a.arg(0))?;
    call_method(vm, &h, &map, "has", &[key])
}

fn headers_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let key = normalize_header_name(vm, &a.arg(0))?;
    let map = get(vm, &this, "_map")?;
    let s = get(vm, &map, "set")?;
    let value = js_string(vm, &a.arg(1))?;
    let entry = hit_entry(vm, &key, Value::Str(js_trim(&value)));
    call_method(vm, &s, &map, "set", &[key, entry])?;
    Ok(Value::Undefined)
}

fn headers_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let f = a.arg(0);
    let this_arg = a.arg(1);
    for_of(vm, &this, |vm, entry| {
        let k = get(vm, &entry, "0")?;
        let v = get(vm, &entry, "1")?;
        let call = get(vm, &f, "call")?;
        call_method(vm, &call, &f, "call", &[this_arg.clone(), v, k, this.clone()]).map(|_| ())
    })?;
    Ok(Value::Undefined)
}

fn headers_pairs(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let items = vm.iterate_to_vec(&a.this)?;
    let mut out = Vec::new();
    for e in items {
        let k = get(vm, &e, "0")?;
        let v = get(vm, &e, "1")?;
        out.push(new_arr(vm, vec![k, v]));
    }
    Ok(new_arr(vm, out))
}

/// Headers as `(name, value)` Rust pairs (via `_pairs()`).
fn header_pairs_rust(vm: &mut Vm, headers: &Value) -> JsResult<Vec<(String, String)>> {
    let pairs = invoke(vm, headers, "_pairs", &[])?;
    let items = vm.iterate_to_vec(&pairs)?;
    let mut out = Vec::new();
    for p in items {
        let k = get(vm, &p, "0")?;
        let v = get(vm, &p, "1")?;
        out.push((str_value(vm, &k)?, str_value(vm, &v)?));
    }
    Ok(out)
}

// ---- generator-like iterators for entries()/keys()/values() ----

enum HIterState {
    Start,
    Entries(Vec<Value>, usize),
    Inner(Value, Value),
    Done,
}

struct HIter {
    kind: usize,
    target: Value,
    state: RefCell<HIterState>,
}

fn make_hiter(vm: &mut Vm, kind: usize, target: Value) -> Value {
    let c = fctx();
    let st = Rc::new(HIter { kind, target, state: RefCell::new(HIterState::Start) });
    let _ = vm;
    Value::Obj(Obj::new(Some(c.hiter_protos[kind].clone()), ObjKind::Host(Box::new(st))))
}

fn headers_entries(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(make_hiter(vm, 0, a.this.clone()))
}
fn headers_keys(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(make_hiter(vm, 1, a.this.clone()))
}
fn headers_values(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(make_hiter(vm, 2, a.this.clone()))
}

fn this_hiter(vm: &mut Vm, v: &Value) -> JsResult<Rc<HIter>> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(r) = h.downcast_ref::<Rc<HIter>>() {
                return Ok(r.clone());
            }
        }
    }
    vm.throw_type("next method called on incompatible receiver")
}

fn sort_js_strings(vm: &mut Vm, items: Vec<Value>) -> JsResult<Vec<Value>> {
    let mut keyed = Vec::new();
    for v in items {
        let s = vm.to_string(&v)?;
        keyed.push((s, v));
    }
    keyed.sort_by(|a, b| a.0.units().cmp(b.0.units()));
    Ok(keyed.into_iter().map(|(_, v)| v).collect())
}

fn hiter_step(vm: &mut Vm, it: &HIter) -> JsResult<Option<Value>> {
    loop {
        let st = std::mem::replace(&mut *it.state.borrow_mut(), HIterState::Done);
        match st {
            HIterState::Done => return Ok(None),
            HIterState::Start => {
                if it.kind == 0 {
                    let map = get(vm, &it.target, "_map")?;
                    let keys = invoke(vm, &map, "keys", &[])?;
                    let keys = vm.iterate_to_vec(&keys)?;
                    let keys = sort_js_strings(vm, keys)?;
                    *it.state.borrow_mut() = HIterState::Entries(keys, 0);
                } else {
                    let (io, next) = vm.get_iterator(&it.target)?;
                    *it.state.borrow_mut() = HIterState::Inner(Value::Obj(io), next);
                }
            }
            HIterState::Entries(keys, i) => {
                if i >= keys.len() {
                    return Ok(None);
                }
                let k = keys[i].clone();
                let map = get(vm, &it.target, "_map")?;
                let hit = invoke(vm, &map, "get", &[k.clone()])?;
                let v = get(vm, &hit, "value")?;
                *it.state.borrow_mut() = HIterState::Entries(keys, i + 1);
                return Ok(Some(new_arr(vm, vec![k, v])));
            }
            HIterState::Inner(io, next) => match vm.iter_step(&io, &next)? {
                None => return Ok(None),
                Some(entry) => {
                    let v = get(vm, &entry, if it.kind == 1 { "0" } else { "1" })?;
                    *it.state.borrow_mut() = HIterState::Inner(io, next);
                    return Ok(Some(v));
                }
            },
        }
    }
}

fn hiter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = this_hiter(vm, &a.this)?;
    match hiter_step(vm, &it)? {
        Some(v) => Ok(iter_result(vm, v, false)),
        None => Ok(iter_result(vm, Value::Undefined, true)),
    }
}

fn hiter_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = this_hiter(vm, &a.this)?;
    *it.state.borrow_mut() = HIterState::Done;
    Ok(iter_result(vm, a.arg(0), true))
}

fn hiter_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = this_hiter(vm, &a.this)?;
    *it.state.borrow_mut() = HIterState::Done;
    Err(a.arg(0))
}

// =====================================================================================
// Bodies
// =====================================================================================

fn set_default_content_type(vm: &mut Vm, target: &Value, ct: &str) -> JsResult<()> {
    let h = get(vm, target, "headers")?;
    if !invoke(vm, &h, "has", &[Value::str("content-type")])?.truthy() {
        let h = get(vm, target, "headers")?;
        invoke(vm, &h, "set", &[Value::str("content-type"), Value::str(ct)])?;
    }
    Ok(())
}

/// Bytes held by a Blob (the reference runtime's `Symbol(blobBytes)` slot, or a synchronous
/// drain of `blob.stream()`).
pub fn blob_bytes(vm: &mut Vm, blob: &Value) -> JsResult<Vec<u8>> {
    if let Value::Obj(o) = blob {
        let keys = vm.own_property_keys(o)?;
        for k in keys {
            if let PropKey::Sym(s) = &k {
                let is_bytes = matches!(&s.0.description, Some(d) if d.eq_str("blobBytes"));
                if is_bytes {
                    let v = vm.get(o, &k, blob)?;
                    if is_typed_array(&v) || is_array_buffer(&v) {
                        return Ok(bytes_from_u8(&v));
                    }
                }
            }
        }
    }
    // an already-settled `arrayBuffer()` promise (async method without awaits)
    if get(vm, blob, "arrayBuffer")?.is_callable() {
        let p = invoke(vm, blob, "arrayBuffer", &[])?;
        let settled = match &p {
            Value::Obj(o) => match &o.borrow().kind {
                ObjKind::Promise(pd) => match &pd.state {
                    PromiseState::Fulfilled(v) => Some(Ok(v.clone())),
                    PromiseState::Rejected(e) => Some(Err(e.clone())),
                    PromiseState::Pending => None,
                },
                _ => None,
            },
            _ => None,
        };
        match settled {
            Some(Ok(v)) if is_array_buffer(&v) || is_view(&v) => return Ok(bytes_from_u8(&v)),
            Some(Err(_)) => {
                // keep the rejection handled; fall through to stream()
                let noop = super::streams::noop_fn(vm);
                let _ = invoke(vm, &p, "catch", &[noop]);
            }
            _ => {}
        }
    }
    let stream = invoke(vm, blob, "stream", &[])?;
    let v = drain_stream_sync(vm, &stream)?;
    Ok(bytes_from_u8(&v))
}

fn random_hex(n: usize) -> String {
    let b = crate::crypto::random::random_bytes(n / 2);
    super::encoding::hex_encode(&b)
}

fn escape_form_name(s: &str) -> String {
    s.replace("\r\n", "%0A").replace('\n', "%0A").replace('"', "%22")
}

/// multipart/form-data serialisation of a FormData.
fn encode_form_data(vm: &mut Vm, fd: &Value) -> JsResult<(Vec<u8>, String)> {
    let boundary = format!("----lumenFormBoundary{}", random_hex(32));
    let mut out: Vec<u8> = Vec::new();
    let entries = vm.iterate_to_vec(fd)?;
    for e in entries {
        let name = get(vm, &e, "0")?;
        let value = get(vm, &e, "1")?;
        let name = js_string(vm, &name)?.to_rust_string();
        out.extend_from_slice(format!("--{}\r\n", boundary).as_bytes());
        if let Value::Str(s) = &value {
            out.extend_from_slice(format!("Content-Disposition: form-data; name=\"{}\"\r\n\r\n", escape_form_name(&name)).as_bytes());
            out.extend_from_slice(&str_to_utf8(s.units()));
        } else {
            let fname = get(vm, &value, "name")?;
            let fname = if fname.is_undefined() || fname.is_null() { "blob".to_string() } else { str_value(vm, &fname)? };
            let ty = get(vm, &value, "type")?;
            let ty = if ty.truthy() { str_value(vm, &ty)? } else { "application/octet-stream".to_string() };
            out.extend_from_slice(
                format!("Content-Disposition: form-data; name=\"{}\"; filename=\"{}\"\r\nContent-Type: {}\r\n\r\n", escape_form_name(&name), fname.replace('"', "%22"), ty)
                    .as_bytes(),
            );
            let bytes = blob_bytes(vm, &value)?;
            out.extend_from_slice(&bytes);
        }
        out.extend_from_slice(b"\r\n");
    }
    out.extend_from_slice(format!("--{}--\r\n", boundary).as_bytes());
    Ok((out, format!("multipart/form-data; boundary={}", boundary)))
}

/// initBody(target, body)
fn init_body(vm: &mut Vm, target: &Value, body: &Value) -> JsResult<()> {
    let c = fctx();
    put(vm, target, "_bodyBytes", Value::Undefined)?;
    if body.is_nullish() {
        return Ok(());
    }
    if super::streams::is_readable_stream(vm, body) {
        put_sym(vm, target, &c.k_source, body.clone())?;
        return Ok(());
    }
    let bytes: Value = if let Value::Str(s) = body {
        let b = str_to_utf8(s.units());
        let u = new_u8(vm, b)?;
        set_default_content_type(vm, target, "text/plain;charset=UTF-8")?;
        u
    } else if super::streams::is_uint8array(vm, body) && is_typed_array(body) {
        body.clone()
    } else if is_array_buffer(body) || is_view(body) {
        u8_view_of(vm, body).unwrap_or(Value::Undefined)
    } else if instance_of_global(vm, body, "Blob") {
        let b = blob_bytes(vm, body)?;
        let u = new_u8(vm, b)?;
        let ty = get(vm, body, "type")?;
        if ty.truthy() {
            let t = str_value(vm, &ty)?;
            set_default_content_type(vm, target, &t)?;
        }
        u
    } else if instance_of_global(vm, body, "URLSearchParams") {
        let s = js_string(vm, body)?;
        let u = new_u8(vm, str_to_utf8(s.units()))?;
        set_default_content_type(vm, target, "application/x-www-form-urlencoded;charset=UTF-8")?;
        u
    } else if instance_of_global(vm, body, "FormData") {
        let (b, ct) = encode_form_data(vm, body)?;
        let u = new_u8(vm, b)?;
        set_default_content_type(vm, target, &ct)?;
        u
    } else {
        let s = js_string(vm, body)?;
        new_u8(vm, str_to_utf8(s.units()))?
    };
    put(vm, target, "_bodyBytes", bytes)
}

/// Bytes of one chunk produced by a body stream.
fn chunk_bytes(vm: &mut Vm, v: &Value) -> JsResult<Vec<u8>> {
    match v {
        Value::Str(s) => Ok(str_to_utf8(s.units())),
        _ if is_array_buffer(v) || is_view(v) => Ok(bytes_from_u8(v)),
        _ => vm.throw_type("ReadableStream chunk is not binary data"),
    }
}

/// drainStreamSync(stream): read every chunk of a stream that produces synchronously.
pub fn drain_stream_sync(vm: &mut Vm, stream: &Value) -> JsResult<Value> {
    if get(vm, stream, "locked")?.truthy() {
        return vm.throw_type("cannot construct a body from a locked ReadableStream");
    }
    let reader = invoke(vm, stream, "getReader", &[])?;
    let mut all = Vec::new();
    let r = (|| -> JsResult<()> {
        loop {
            let r = invoke(vm, &reader, "_readSync", &[])?;
            if get(vm, &r, "pending")?.truthy() {
                return vm.throw_type("a body ReadableStream must produce its data synchronously in this runtime");
            }
            if get(vm, &r, "done")?.truthy() {
                return Ok(());
            }
            let v = get(vm, &r, "value")?;
            let b = chunk_bytes(vm, &v)?;
            all.extend_from_slice(&b);
        }
    })();
    let rel = invoke(vm, &reader, "releaseLock", &[]);
    r?;
    rel?;
    new_u8(vm, all)
}

fn body_materialize(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = a.this.clone();
    let src = get_sym(vm, &this, &c.k_source)?;
    if !src.is_undefined() {
        let src = get_sym(vm, &this, &c.k_source)?;
        let bytes = drain_stream_sync(vm, &src)?;
        put(vm, &this, "_bodyBytes", bytes)?;
        put_sym(vm, &this, &c.k_source, Value::Undefined)?;
    }
    Ok(Value::Undefined)
}

fn body_consume(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let r = (|| -> JsResult<Value> {
        let c = fctx();
        let this = a.this.clone();
        if get_sym(vm, &this, &c.k_consumed)?.truthy() {
            return vm.throw_type("body already consumed");
        }
        put_sym(vm, &this, &c.k_consumed, Value::Bool(true))?;
        invoke(vm, &this, "_materialize", &[])?;
        let b = get(vm, &this, "_bodyBytes")?;
        if b.truthy() {
            Ok(b)
        } else {
            new_u8(vm, Vec::new())
        }
    })();
    settle(vm, &cap, r);
    Ok(cap.promise)
}

struct BodyOp {
    cap: Capability,
    this: Value,
    kind: u8,
}

const OP_TEXT: u8 = 0;
const OP_JSON: u8 = 1;
const OP_AB: u8 = 2;
const OP_BLOB: u8 = 3;
const OP_FD_URL: u8 = 4;
const OP_FD_MULTI: u8 = 5;

fn body_op_start(vm: &mut Vm, this: Value, kind: u8, method: &str, extra: Option<Value>) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    match invoke(vm, &this, method, &[]) {
        Ok(p) => {
            let data = host(Rc::new((BodyOp { cap: cap.clone(), this, kind }, extra)));
            await_value(vm, p, &data, body_op_ok, body_op_err);
        }
        Err(e) => settle(vm, &cap, Err(e)),
    }
    Ok(cap.promise)
}

fn body_op_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<(BodyOp, Option<Value>)>(data);
    settle(vm, &st.0.cap, Err(e));
    Ok(Value::Undefined)
}

fn body_op_ok(vm: &mut Vm, v: Value, data: &Value) -> JsResult<Value> {
    let st = unhost::<(BodyOp, Option<Value>)>(data);
    let op = &st.0;
    let r = (|| -> JsResult<Value> {
        match op.kind {
            OP_TEXT => {
                let d = Decoder { fatal: false, ignore_bom: false };
                Ok(Value::Str(decoder_decode(vm, &d, &v)?))
            }
            OP_JSON => {
                let s = vm.to_string(&v)?;
                crate::builtins::json::json_parse(vm, &s)
            }
            OP_AB => {
                let buffer = get(vm, &v, "buffer")?;
                let off = get(vm, &v, "byteOffset")?;
                let off2 = get(vm, &v, "byteOffset")?;
                let len = get(vm, &v, "byteLength")?;
                let end = vm.op_add(&off2, &len)?;
                invoke(vm, &buffer, "slice", &[off, end])
            }
            OP_BLOB => {
                let h = get(vm, &op.this, "headers")?;
                let ty = if h.truthy() {
                    let h = get(vm, &op.this, "headers")?;
                    invoke(vm, &h, "get", &[Value::str("content-type")])?
                } else {
                    h
                };
                let ty = if ty.truthy() { ty } else { Value::str("") };
                let parts = new_arr(vm, vec![v]);
                let opts = Value::Obj(vm.obj_from(vec![("type", ty)]));
                construct_global(vm, "Blob", &[parts, opts])
            }
            OP_FD_URL => {
                let form = st.1.clone().unwrap_or(Value::Undefined);
                let usp = construct_global(vm, "URLSearchParams", &[v])?;
                for_of(vm, &usp, |vm, entry| {
                    let k = get(vm, &entry, "0")?;
                    let val = get(vm, &entry, "1")?;
                    invoke(vm, &form, "append", &[k, val]).map(|_| ())
                })?;
                Ok(form)
            }
            OP_FD_MULTI => {
                let boundary = match &st.1 {
                    Some(Value::Str(s)) => s.to_rust_string(),
                    _ => String::new(),
                };
                let bytes = bytes_from_u8(&v);
                decode_multipart(vm, &bytes, &boundary)
            }
            _ => Ok(Value::Undefined),
        }
    })();
    settle(vm, &op.cap, r);
    Ok(Value::Undefined)
}

fn body_text(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    body_op_start(vm, a.this.clone(), OP_TEXT, "_consume", None)
}

fn body_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    body_op_start(vm, a.this.clone(), OP_JSON, "text", None)
}

fn body_array_buffer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    body_op_start(vm, a.this.clone(), OP_AB, "_consume", None)
}

fn body_bytes(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let r = invoke(vm, &a.this, "_consume", &[]);
    settle(vm, &cap, r);
    Ok(cap.promise)
}

fn body_blob(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    body_op_start(vm, a.this.clone(), OP_BLOB, "_consume", None)
}

fn body_form_data(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let r = (|| -> JsResult<Value> {
        let h = get(vm, &this, "headers")?;
        let ct = if h.truthy() {
            let h = get(vm, &this, "headers")?;
            invoke(vm, &h, "get", &[Value::str("content-type")])?
        } else {
            h
        };
        let ct = if ct.truthy() { ct } else { Value::str("") };
        let cts = vm.to_string(&ct)?.to_rust_string();
        if cts.starts_with("application/x-www-form-urlencoded") {
            let form = construct_global(vm, "FormData", &[])?;
            return body_op_start(vm, this.clone(), OP_FD_URL, "text", Some(form));
        }
        let lower = cts.to_ascii_lowercase();
        let m = lower.find("boundary=").map(|i| {
            let rest = &cts[i + 9..];
            let end = rest.find(';').unwrap_or(rest.len());
            rest[..end].to_string()
        });
        if let (true, Some(b)) = (cts.starts_with("multipart/form-data"), m.filter(|s| !s.is_empty())) {
            let mut b = b.trim().to_string();
            if b.starts_with('"') {
                b.remove(0);
            }
            if b.ends_with('"') {
                b.pop();
            }
            return body_op_start(vm, this.clone(), OP_FD_MULTI, "_consume", Some(Value::str(&b)));
        }
        vm.throw_type(format!("formData(): unsupported content-type '{}'", cts))
    })();
    match r {
        Ok(p) => Ok(p),
        Err(e) => Ok(rejected(vm, e)),
    }
}

fn find_bytes(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if needle.is_empty() || from > hay.len() {
        return None;
    }
    hay[from..].windows(needle.len()).position(|w| w == needle).map(|p| p + from)
}

fn regex_quoted(s: &str, key: &str) -> Option<String> {
    // first match of /<key>="([^"]*)"/
    let pat = format!("{}=\"", key);
    let mut from = 0;
    while let Some(i) = s[from..].find(&pat) {
        let start = from + i + pat.len();
        if let Some(end) = s[start..].find('"') {
            return Some(s[start..start + end].to_string());
        }
        from = start;
    }
    None
}

fn unescape_form_name(s: &str) -> String {
    s.replace("%0A", "\n").replace("%22", "\"")
}

/// decodeMultipart(bytes, boundary) -> FormData
fn decode_multipart(vm: &mut Vm, bytes: &[u8], boundary: &str) -> JsResult<Value> {
    let form = construct_global(vm, "FormData", &[])?;
    let delim = format!("--{}", boundary);
    let d = delim.as_bytes();
    let mut pos = match find_bytes(bytes, d, 0) {
        Some(p) => p,
        None => return Ok(form),
    };
    loop {
        let mut start = pos + d.len();
        if bytes[start..].starts_with(b"--") {
            break;
        }
        if bytes[start..].starts_with(b"\r\n") {
            start += 2;
        } else {
            break;
        }
        let mut nd = b"\r\n".to_vec();
        nd.extend_from_slice(d);
        let next = match find_bytes(bytes, &nd, start) {
            Some(n) => n,
            None => break,
        };
        let part = &bytes[start..next];
        if let Some(sep) = find_bytes(part, b"\r\n\r\n", 0) {
            let head = String::from_utf8_lossy(&part[..sep]).to_string();
            let body = &part[sep + 4..];
            let mut disposition = String::new();
            let mut ctype = String::new();
            for line in head.split("\r\n") {
                if let Some(ci) = line.find(':') {
                    let n = line[..ci].trim().to_ascii_lowercase();
                    let v = line[ci + 1..].trim().to_string();
                    if n == "content-disposition" {
                        disposition = v;
                    } else if n == "content-type" {
                        ctype = v;
                    }
                }
            }
            if let Some(name) = regex_quoted(&disposition, "name") {
                let name = unescape_form_name(&name);
                match regex_quoted(&disposition, "filename") {
                    Some(fname) => {
                        let u = new_u8(vm, body.to_vec())?;
                        let parts = new_arr(vm, vec![u]);
                        let opts = Value::Obj(vm.obj_from(vec![("type", Value::str(&ctype))]));
                        let file = construct_global(vm, "File", &[parts, Value::str(&unescape_form_name(&fname)), opts])?;
                        invoke(vm, &form, "append", &[Value::str(&name), file])?;
                    }
                    None => {
                        let text = super::streams::decode_text(body);
                        invoke(vm, &form, "append", &[Value::str(&name), Value::Str(text)])?;
                    }
                }
            }
        }
        pos = next + 2;
    }
    Ok(form)
}

fn body_used_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    Ok(Value::Bool(get_sym(vm, &a.this, &c.k_consumed)?.truthy()))
}

fn body_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = a.this.clone();
    let src = get_sym(vm, &this, &c.k_source)?;
    if !src.is_undefined() {
        return get_sym(vm, &this, &c.k_source);
    }
    if get(vm, &this, "_bodyBytes")?.is_undefined() {
        return Ok(Value::Null);
    }
    if get_sym(vm, &this, &c.k_body_stream)?.is_undefined() {
        let s = make_body_stream(vm, &this)?;
        put_sym(vm, &this, &c.k_body_stream, s)?;
    }
    get_sym(vm, &this, &c.k_body_stream)
}

fn make_body_stream(vm: &mut Vm, target: &Value) -> JsResult<Value> {
    let src = vm.new_object();
    let pull = func(vm, "pull", 1, body_stream_pull, vec![target.clone()]);
    src.set_str("pull", pull, WEC);
    super::streams::new_readable_stream(vm, Value::Obj(src))
}

fn body_stream_pull(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let target = a.slot(0);
    let controller = a.arg(0);
    let r = (|| -> JsResult<()> {
        if get_sym(vm, &target, &c.k_consumed)?.truthy() {
            return vm.throw_type("body already consumed");
        }
        put_sym(vm, &target, &c.k_consumed, Value::Bool(true))?;
        let bytes = get(vm, &target, "_bodyBytes")?;
        if get(vm, &bytes, "length")?.truthy() {
            invoke(vm, &controller, "enqueue", &[bytes])?;
        }
        invoke(vm, &controller, "close", &[])?;
        Ok(())
    })();
    if let Err(e) = r {
        invoke(vm, &controller, "error", &[e])?;
    }
    Ok(Value::Undefined)
}

fn install_body_mixin(vm: &mut Vm, proto: &Obj) {
    let fns: [(&str, NativeFn); 8] = [
        ("text", body_text),
        ("json", body_json),
        ("arrayBuffer", body_array_buffer),
        ("bytes", body_bytes),
        ("blob", body_blob),
        ("formData", body_form_data),
        ("_consume", body_consume),
        ("_materialize", body_materialize),
    ];
    for (n, f) in fns {
        let fo = vm.native_fn("", 0, f);
        proto.set_prop(PropKey::from_str(n), Value::Obj(fo), WEC);
    }
    let g = vm.native_fn("get", 0, body_used_get);
    proto.set_accessor(PropKey::from_str("bodyUsed"), Some(g), None, 0);
    let g = vm.native_fn("get", 0, body_get);
    proto.set_accessor(PropKey::from_str("body"), Some(g), None, CONFIGURABLE);
}

// =====================================================================================
// URL handling
// =====================================================================================

/// `new URL(String(input)).href` (falls back to an internal parser when URL is unavailable).
fn url_href(vm: &mut Vm, input: &Value) -> JsResult<Value> {
    let s = js_string(vm, input)?;
    let u = global(vm, "URL");
    if matches!(&u, Value::Obj(o) if o.is_constructor()) {
        let url = vm.construct(&u, &[Value::Str(s)], None)?;
        return get(vm, &url, "href");
    }
    match parse_url(&s.to_rust_string()) {
        Some(p) => Ok(Value::str(&p.href())),
        None => vm.throw_type(format!("URL: invalid URL '{}' (relative, and no base given)", s.to_rust_string())),
    }
}

#[derive(Clone, Debug)]
pub struct ParsedUrl {
    pub scheme: String,
    pub userinfo: String,
    pub host: String,
    pub port: Option<u16>,
    pub path: String,
    pub query: String,
    pub fragment: String,
}

pub fn default_port(scheme: &str) -> Option<u16> {
    match scheme {
        "http" | "ws" => Some(80),
        "https" | "wss" => Some(443),
        "ftp" => Some(21),
        _ => None,
    }
}

impl ParsedUrl {
    pub fn host_port(&self) -> String {
        match self.port {
            Some(p) if Some(p) != default_port(&self.scheme) => format!("{}:{}", self.host, p),
            _ => self.host.clone(),
        }
    }
    pub fn href(&self) -> String {
        let mut s = format!("{}:", self.scheme);
        if !self.host.is_empty() || self.scheme == "file" {
            s.push_str("//");
            if !self.userinfo.is_empty() {
                s.push_str(&self.userinfo);
                s.push('@');
            }
            s.push_str(&self.host_port());
        }
        s.push_str(&self.path);
        s.push_str(&self.query);
        s.push_str(&self.fragment);
        s
    }
    pub fn effective_port(&self) -> u16 {
        self.port.or(default_port(&self.scheme)).unwrap_or(80)
    }
    pub fn path_and_query(&self) -> String {
        let p = if self.path.is_empty() { "/".to_string() } else { self.path.clone() };
        format!("{}{}", p, self.query)
    }
    /// Host for socket connection ([::1] -> ::1).
    pub fn connect_host(&self) -> String {
        self.host.trim_start_matches('[').trim_end_matches(']').to_string()
    }
}

fn normalize_path(p: &str) -> String {
    let mut out: Vec<&str> = Vec::new();
    let segs: Vec<&str> = p.split('/').collect();
    let n = segs.len();
    for (i, seg) in segs.iter().enumerate().skip(1) {
        let last = i == n - 1;
        match *seg {
            "." | "%2e" | "%2E" => {
                if last {
                    out.push("");
                }
            }
            ".." | ".%2e" | "%2e." | "%2e%2e" | ".%2E" | "%2E." | "%2E%2E" => {
                out.pop();
                if last {
                    out.push("");
                }
            }
            s => out.push(s),
        }
    }
    format!("/{}", out.join("/"))
}

/// A small URL parser for absolute URLs (special schemes) used for fetch/WebSocket plumbing.
pub fn parse_url(input: &str) -> Option<ParsedUrl> {
    let s = input.trim_matches(|c: char| c <= ' ');
    let colon = s.find(':')?;
    let scheme = s[..colon].to_ascii_lowercase();
    if scheme.is_empty() || !scheme.chars().next()?.is_ascii_alphabetic() || !scheme.chars().all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c)) {
        return None;
    }
    let mut rest = &s[colon + 1..];
    let (mut fragment, mut query) = (String::new(), String::new());
    if let Some(h) = rest.find('#') {
        fragment = rest[h..].to_string();
        rest = &rest[..h];
    }
    if let Some(q) = rest.find('?') {
        query = rest[q..].to_string();
        rest = &rest[..q];
    }
    let special = matches!(scheme.as_str(), "http" | "https" | "ws" | "wss" | "ftp" | "file");
    if !special {
        return Some(ParsedUrl { scheme, userinfo: String::new(), host: String::new(), port: None, path: rest.to_string(), query, fragment });
    }
    let rest = rest.trim_start_matches(['/', '\\']);
    let auth_end = rest.find(['/', '\\']).unwrap_or(rest.len());
    let authority = &rest[..auth_end];
    let path = rest[auth_end..].replace('\\', "/");
    let (userinfo, hostport) = match authority.rfind('@') {
        Some(i) => (authority[..i].to_string(), &authority[i + 1..]),
        None => (String::new(), authority),
    };
    let (host, port) = if hostport.starts_with('[') {
        let end = hostport.find(']')?;
        let h = &hostport[..=end];
        let p = &hostport[end + 1..];
        let port = if let Some(ps) = p.strip_prefix(':') { if ps.is_empty() { None } else { Some(ps.parse::<u16>().ok()?) } } else if p.is_empty() { None } else { return None };
        (h.to_ascii_lowercase(), port)
    } else {
        match hostport.rfind(':') {
            Some(i) => {
                let ps = &hostport[i + 1..];
                let port = if ps.is_empty() { None } else { Some(ps.parse::<u16>().ok()?) };
                (hostport[..i].to_ascii_lowercase(), port)
            }
            None => (hostport.to_ascii_lowercase(), None),
        }
    };
    if host.is_empty() && scheme != "file" {
        return None;
    }
    if host.chars().any(|c| " <>^|%\"".contains(c)) {
        return None;
    }
    let port = if port == default_port(&scheme) { None } else { port };
    let path = if path.is_empty() { "/".to_string() } else { normalize_path(&path) };
    let query = query.replace(' ', "%20");
    let path = path.replace(' ', "%20");
    Some(ParsedUrl { scheme, userinfo, host, port, path, query, fragment })
}

/// Resolve `loc` (Location header) against `base`.
pub fn resolve_url(base: &ParsedUrl, loc: &str) -> Option<ParsedUrl> {
    if let Some(p) = parse_url(loc) {
        if loc.contains(':') && loc.split(':').next().map(|s| s.chars().all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c))).unwrap_or(false) {
            return Some(p);
        }
    }
    let mut u = base.clone();
    u.fragment = String::new();
    if let Some(rest) = loc.strip_prefix("//") {
        return parse_url(&format!("{}://{}", base.scheme, rest));
    }
    let (mut l, mut frag) = (loc.to_string(), String::new());
    if let Some(h) = l.find('#') {
        frag = l[h..].to_string();
        l.truncate(h);
    }
    let mut q = String::new();
    if let Some(i) = l.find('?') {
        q = l[i..].to_string();
        l.truncate(i);
    }
    if l.starts_with('/') {
        u.path = normalize_path(&l);
        u.query = q;
    } else if l.is_empty() {
        if !q.is_empty() {
            u.query = q;
        }
    } else {
        let dir = match u.path.rfind('/') {
            Some(i) => &u.path[..=i],
            None => "/",
        };
        u.path = normalize_path(&format!("{}{}", dir, l));
        u.query = q;
    }
    u.fragment = frag;
    Some(u)
}

// =====================================================================================
// Request / Response
// =====================================================================================

fn request_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = new_this(vm, a, &c.request_proto)?;
    let input = a.arg(0);
    let mut init = a.arg(1);
    if init.is_undefined() {
        init = new_obj(vm);
    }
    let init = if init.truthy() && init.type_of() == "object" { init } else { new_obj(vm) };
    if vm.instance_of(&input, &Value::Obj(c.request.clone()))? {
        let url = get(vm, &input, "url")?;
        put(vm, &this, "url", url)?;
        let m = get(vm, &init, "method")?;
        let method = if m.truthy() {
            let m = get(vm, &init, "method")?;
            Value::str(&js_string(vm, &m)?.to_rust_string().to_uppercase())
        } else {
            get(vm, &input, "method")?
        };
        put(vm, &this, "method", method)?;
        let ih = get(vm, &init, "headers")?;
        let hinit = if ih.truthy() { ih } else { get(vm, &input, "headers")? };
        let h = construct(vm, &c.headers, &[hinit])?;
        put(vm, &this, "headers", h)?;
        let init_o = init.as_obj().unwrap().clone();
        if vm.has_property(&init_o, &PropKey::from_str("body"))? {
            let body = get(vm, &init, "body")?;
            init_body(vm, &this, &body)?;
        } else {
            let bb = get(vm, &input, "_bodyBytes")?;
            put(vm, &this, "_bodyBytes", bb)?;
            let ss = get_sym(vm, &input, &c.k_source)?;
            put_sym(vm, &this, &c.k_source, ss)?;
        }
        let s1 = get(vm, &init, "signal")?;
        let signal = if s1.truthy() {
            s1
        } else {
            let s2 = get(vm, &input, "signal")?;
            if s2.truthy() {
                s2
            } else {
                Value::Null
            }
        };
        put(vm, &this, "signal", signal)?;
    } else {
        let href = url_href(vm, &input)?;
        put(vm, &this, "url", href)?;
        let m = get(vm, &init, "method")?;
        let method = if m.truthy() {
            let m = get(vm, &init, "method")?;
            Value::str(&js_string(vm, &m)?.to_rust_string().to_uppercase())
        } else {
            Value::str("GET")
        };
        put(vm, &this, "method", method)?;
        let ih = get(vm, &init, "headers")?;
        let h = construct(vm, &c.headers, &[ih])?;
        put(vm, &this, "headers", h)?;
        let body = get(vm, &init, "body")?;
        init_body(vm, &this, &body)?;
        let s1 = get(vm, &init, "signal")?;
        put(vm, &this, "signal", if s1.truthy() { s1 } else { Value::Null })?;
    }
    let method = get(vm, &this, "method")?;
    if is_str(&method, "GET") || is_str(&method, "HEAD") {
        let has_body = !get(vm, &this, "_bodyBytes")?.is_undefined() || !get_sym(vm, &this, &c.k_source)?.is_undefined();
        if has_body {
            let m = vm.to_string(&method)?.to_rust_string();
            return vm.throw_type(format!("{} request cannot have a body", m));
        }
    }
    put_sym(vm, &this, &c.k_consumed, Value::Bool(false))?;
    Ok(this)
}

fn request_clone(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = a.this.clone();
    invoke(vm, &this, "_materialize", &[])?;
    let url = get(vm, &this, "url")?;
    let method = get(vm, &this, "method")?;
    let headers = get(vm, &this, "headers")?;
    let body = get(vm, &this, "_bodyBytes")?;
    let signal = get(vm, &this, "signal")?;
    let init = Value::Obj(vm.obj_from(vec![("method", method), ("headers", headers), ("body", body), ("signal", signal)]));
    construct(vm, &c.request, &[url, init])
}

fn response_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = new_this(vm, a, &c.response_proto)?;
    let mut body = a.arg(0);
    if body.is_undefined() {
        body = Value::Null;
    }
    let mut init = a.arg(1);
    if init.is_undefined() {
        init = new_obj(vm);
    }
    let init = if init.truthy() && init.type_of() == "object" { init } else { new_obj(vm) };
    let st = get(vm, &init, "status")?;
    let status = if !st.is_undefined() {
        let st = get(vm, &init, "status")?;
        Value::Num(vm.to_number(&st)?)
    } else {
        Value::Num(200.0)
    };
    put(vm, &this, "status", status)?;
    let s = get(vm, &this, "status")?;
    let sn = vm.to_number(&s)?;
    let s2 = get(vm, &this, "status")?;
    let sn2 = vm.to_number(&s2)?;
    if sn < 200.0 || sn2 > 599.0 {
        let shown = vm.to_string(&s)?.to_rust_string();
        return vm.throw_range(format!("invalid response status {}", shown));
    }
    let stt = get(vm, &init, "statusText")?;
    let status_text = if !stt.is_undefined() {
        let stt = get(vm, &init, "statusText")?;
        Value::Str(js_string(vm, &stt)?)
    } else {
        Value::str("")
    };
    put(vm, &this, "statusText", status_text)?;
    let ih = get(vm, &init, "headers")?;
    let h = construct(vm, &c.headers, &[ih])?;
    put(vm, &this, "headers", h)?;
    put(vm, &this, "url", Value::str(""))?;
    put(vm, &this, "redirected", Value::Bool(false))?;
    init_body(vm, &this, &body)?;
    put_sym(vm, &this, &c.k_consumed, Value::Bool(false))?;
    Ok(this)
}

fn response_ok(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = get(vm, &a.this, "status")?;
    let ge = !vm.op_compare(crate::bytecode::Op::Lt, &s, &Value::Num(200.0))? && !matches!(vm.to_numeric(&s)?, Value::Num(n) if n.is_nan());
    if !ge {
        return Ok(Value::Bool(false));
    }
    let s = get(vm, &a.this, "status")?;
    Ok(Value::Bool(vm.op_compare(crate::bytecode::Op::Lt, &s, &Value::Num(300.0))?))
}

fn response_clone(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = a.this.clone();
    if get_sym(vm, &this, &c.k_consumed)?.truthy() {
        return vm.throw_type("cannot clone a used Response");
    }
    invoke(vm, &this, "_materialize", &[])?;
    let body = get(vm, &this, "_bodyBytes")?;
    let status = get(vm, &this, "status")?;
    let status_text = get(vm, &this, "statusText")?;
    let headers = get(vm, &this, "headers")?;
    let init = Value::Obj(vm.obj_from(vec![("status", status), ("statusText", status_text), ("headers", headers)]));
    let r = construct(vm, &c.response, &[body, init])?;
    let url = get(vm, &this, "url")?;
    put(vm, &r, "url", url)?;
    let red = get(vm, &this, "redirected")?;
    put(vm, &r, "redirected", red)?;
    Ok(r)
}

fn response_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let s = crate::builtins::json::json_stringify(vm, &a.arg(0), &Value::Undefined, &Value::Undefined)?;
    let body = match s {
        Some(s) => Value::Str(s),
        None => Value::Undefined,
    };
    let r = construct(vm, &c.response, &[body, a.arg(1)])?;
    let h = get(vm, &r, "headers")?;
    if !invoke(vm, &h, "has", &[Value::str("content-type")])?.truthy() {
        let h = get(vm, &r, "headers")?;
        invoke(vm, &h, "set", &[Value::str("content-type"), Value::str("application/json")])?;
    }
    Ok(r)
}

fn response_error(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let c = fctx();
    let init = Value::Obj(vm.obj_from(vec![("status", Value::Num(200.0))]));
    let r = construct(vm, &c.response, &[Value::Null, init])?;
    put(vm, &r, "status", Value::Num(0.0))?;
    put(vm, &r, "type", Value::str("error"))?;
    Ok(r)
}

// =====================================================================================
// fetch (HTTP/1.1 client)
// =====================================================================================

pub struct RawResponse {
    pub status: u16,
    pub status_text: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub url: String,
}

struct FetchState {
    cap: Capability,
    request: Value,
    signal: Value,
    on_abort: RefCell<Value>,
    settled: Cell<bool>,
}

fn fetch_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let mut init = a.arg(1);
    if init.is_undefined() {
        init = new_obj(vm);
    }
    if let Err(e) = fetch_executor(vm, &cap, a.arg(0), init) {
        let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
    }
    Ok(cap.promise)
}

fn abort_reason(vm: &mut Vm, signal: &Value) -> JsResult<Value> {
    let r = get(vm, signal, "reason")?;
    if r.truthy() {
        Ok(r)
    } else {
        make_dom_exception(vm, "The operation was aborted", "AbortError")
    }
}

fn fetch_executor(vm: &mut Vm, cap: &Capability, input: Value, init: Value) -> JsResult<()> {
    let c = fctx();
    let request = match construct(vm, &c.request, &[input, init]) {
        Ok(r) => r,
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(());
        }
    };
    let signal = get(vm, &request, "signal")?;
    if signal.truthy() && get(vm, &signal, "aborted")?.truthy() {
        let r = abort_reason(vm, &signal)?;
        vm.call(&cap.reject, Value::Undefined, &[r])?;
        return Ok(());
    }
    let headers = get(vm, &request, "headers")?;
    let pairs = header_pairs_rust(vm, &headers)?;
    let body = match (|| -> JsResult<Value> {
        invoke(vm, &request, "_materialize", &[])?;
        get(vm, &request, "_bodyBytes")
    })() {
        Ok(b) => b,
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(());
        }
    };
    let st = Rc::new(FetchState { cap: cap.clone(), request: request.clone(), signal: signal.clone(), on_abort: RefCell::new(Value::Undefined), settled: Cell::new(false) });
    let data = host(st.clone());
    if signal.truthy() {
        let on_abort = func(vm, "onAbort", 0, fetch_on_abort, vec![data.clone()]);
        *st.on_abort.borrow_mut() = on_abort.clone();
        invoke(vm, &signal, "addEventListener", &[Value::str("abort"), on_abort])?;
    }
    let method = get(vm, &request, "method")?;
    let method = str_value(vm, &method)?;
    let url = get(vm, &request, "url")?;
    let url = str_value(vm, &url)?;
    let body_bytes = if body.is_undefined() || body.is_null() { None } else { Some(bytes_from_u8(&body)) };
    super::spawn_op(
        vm,
        move || {
            let r = http_fetch(&method, &url, &pairs, body_bytes.as_deref());
            if r.is_err() {
                // the reference runtime reports failures a few ms later (after 0ms timers)
                std::thread::sleep(Duration::from_millis(4));
            }
            r
        },
        move |vm, res: Result<RawResponse, String>| fetch_complete(vm, &data, res),
    );
    Ok(())
}

fn fetch_on_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = unhost::<FetchState>(&a.slot(0));
    if st.settled.get() {
        return Ok(Value::Undefined);
    }
    st.settled.set(true);
    let r = abort_reason(vm, &st.signal)?;
    vm.call(&st.cap.reject, Value::Undefined, &[r])?;
    Ok(Value::Undefined)
}

fn fetch_complete(vm: &mut Vm, data: &Value, res: Result<RawResponse, String>) {
    let st = unhost::<FetchState>(data);
    if st.settled.get() {
        return;
    }
    st.settled.set(true);
    let r = (|| -> JsResult<()> {
        if st.signal.truthy() {
            let h = st.on_abort.borrow().clone();
            invoke(vm, &st.signal, "removeEventListener", &[Value::str("abort"), h])?;
        }
        match res {
            Ok(raw) => {
                let c = fctx();
                let body = new_u8(vm, raw.body)?;
                let mut hs = Vec::new();
                for (k, v) in raw.headers {
                    hs.push(new_arr(vm, vec![Value::str(&k), Value::str(&v)]));
                }
                let hs = new_arr(vm, hs);
                let init = Value::Obj(vm.obj_from(vec![("status", Value::Num(raw.status as f64)), ("statusText", Value::str(&raw.status_text)), ("headers", hs)]));
                let response = construct(vm, &c.response, &[body, init])?;
                put(vm, &response, "url", Value::str(&raw.url))?;
                let req_url = get(vm, &st.request, "url")?;
                let redirected = !Value::strict_eq(&Value::str(&raw.url), &req_url);
                put(vm, &response, "redirected", Value::Bool(redirected))?;
                vm.call(&st.cap.resolve, Value::Undefined, &[response])?;
            }
            Err(msg) => {
                let e = type_error(vm, &msg);
                vm.call(&st.cap.reject, Value::Undefined, &[e])?;
            }
        }
        Ok(())
    })();
    if let Err(e) = r {
        super::report_uncaught(vm, &e);
    }
}

fn read_line(stream: &mut impl Read, buf: &mut Vec<u8>) -> std::io::Result<Option<String>> {
    // read one line terminated by \n from a buffered prefix + stream
    loop {
        if let Some(i) = buf.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = buf.drain(..=i).collect();
            let mut s = String::from_utf8_lossy(&line).to_string();
            while s.ends_with('\n') || s.ends_with('\r') {
                s.pop();
            }
            return Ok(Some(s));
        }
        let mut tmp = [0u8; 8192];
        let n = stream.read(&mut tmp)?;
        if n == 0 {
            if buf.is_empty() {
                return Ok(None);
            }
            let s = String::from_utf8_lossy(buf).to_string();
            buf.clear();
            return Ok(Some(s));
        }
        buf.extend_from_slice(&tmp[..n]);
    }
}

fn read_exact_buffered(stream: &mut impl Read, buf: &mut Vec<u8>, n: usize) -> std::io::Result<Vec<u8>> {
    let mut out = Vec::with_capacity(n);
    let take = n.min(buf.len());
    out.extend(buf.drain(..take));
    if out.len() < n {
        let mut rest = vec![0u8; n - out.len()];
        stream.read_exact(&mut rest)?;
        out.extend_from_slice(&rest);
    }
    Ok(out)
}

fn read_to_end_buffered(stream: &mut impl Read, buf: &mut Vec<u8>) -> std::io::Result<Vec<u8>> {
    let mut out = std::mem::take(buf);
    stream.read_to_end(&mut out)?;
    Ok(out)
}

fn read_chunked(stream: &mut impl Read, buf: &mut Vec<u8>) -> std::io::Result<Vec<u8>> {
    let mut out = Vec::new();
    loop {
        let line = match read_line(stream, buf)? {
            Some(l) => l,
            None => break,
        };
        let size_s = line.split(';').next().unwrap_or("").trim();
        if size_s.is_empty() {
            continue;
        }
        let size = usize::from_str_radix(size_s, 16).map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidData, "invalid chunk size"))?;
        if size == 0 {
            // trailers
            while let Some(l) = read_line(stream, buf)? {
                if l.is_empty() {
                    break;
                }
            }
            break;
        }
        let data = read_exact_buffered(stream, buf, size)?;
        out.extend_from_slice(&data);
        let _ = read_line(stream, buf)?;
    }
    Ok(out)
}

/// One request/response exchange; follows redirects (at most 5).
pub fn http_fetch(method: &str, url: &str, headers: &[(String, String)], body: Option<&[u8]>) -> Result<RawResponse, String> {
    let mut cur = match parse_url(url) {
        Some(u) => u,
        None => return Err(format!("fetch '{}': invalid URL", url)),
    };
    if cur.scheme != "http" && cur.scheme != "https" {
        return Err(format!("fetch: unsupported scheme '{}'", cur.scheme));
    }
    let mut method = method.to_string();
    let mut body: Option<Vec<u8>> = body.map(|b| b.to_vec());
    let mut cur_url = url.to_string();
    let mut redirects = 0;
    loop {
        let resp = http_once(&method, &cur, headers, body.as_deref()).map_err(|e| format!("fetch '{}': {}", url, e))?;
        let (status, status_text, rheaders, rbody) = resp;
        let is_redirect = matches!(status, 301 | 302 | 303 | 307 | 308);
        let location = rheaders.iter().find(|(k, _)| k.eq_ignore_ascii_case("location")).map(|(_, v)| v.clone());
        if is_redirect {
            if let Some(loc) = location {
                if redirects >= 5 {
                    return Err(format!("fetch '{}': too many redirects", url));
                }
                redirects += 1;
                let next = match resolve_url(&cur, &loc) {
                    Some(n) => n,
                    None => return Err(format!("fetch '{}': invalid redirect location '{}'", url, loc)),
                };
                if matches!(status, 301 | 302 | 303) && method != "HEAD" {
                    method = "GET".to_string();
                    body = None;
                }
                cur = next;
                cur_url = cur.href();
                if cur.scheme != "http" && cur.scheme != "https" {
                    return Err(format!("fetch: unsupported scheme '{}'", cur.scheme));
                }
                continue;
            }
        }
        return Ok(RawResponse { status, status_text, headers: rheaders, body: rbody, url: cur_url });
    }
}

type Exchange = (u16, String, Vec<(String, String)>, Vec<u8>);

fn http_once(method: &str, u: &ParsedUrl, headers: &[(String, String)], body: Option<&[u8]>) -> Result<Exchange, String> {
    let host = u.connect_host();
    let port = u.effective_port();
    let mut stream = TcpStream::connect((host.as_str(), port)).map_err(|e| format!("connect: {}", e))?;
    if u.scheme == "https" {
        return Err(tls_failure(&mut stream));
    }
    let mut req = format!("{} {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n", method, u.path_and_query(), u.host_port());
    let mut has_ua = false;
    for (k, v) in headers {
        if k == "host" || k == "connection" {
            continue;
        }
        if k == "user-agent" {
            has_ua = true;
        }
        req.push_str(&format!("{}: {}\r\n", k, v));
    }
    if !has_ua {
        req.push_str(&format!("User-Agent: lumen/{}\r\n", VERSION));
    }
    if let Some(b) = body {
        req.push_str(&format!("Content-Length: {}\r\n", b.len()));
    }
    req.push_str("\r\n");
    let mut out = req.into_bytes();
    if let Some(b) = body {
        out.extend_from_slice(b);
    }
    stream.write_all(&out).map_err(|e| format!("write: {}", e))?;
    let _ = stream.flush();
    let mut buf: Vec<u8> = Vec::new();
    let status_line = read_line(&mut stream, &mut buf).map_err(|e| format!("read: {}", e))?.unwrap_or_default();
    let (status, status_text) = match parse_status_line(&status_line) {
        Some(x) => x,
        None => {
            let raw = if status_line.is_empty() { String::new() } else { format!("{}\r\n", status_line) };
            return Err(format!("malformed status line {:?}", raw));
        }
    };
    let mut rheaders = Vec::new();
    loop {
        let line = match read_line(&mut stream, &mut buf).map_err(|e| format!("read: {}", e))? {
            Some(l) => l,
            None => break,
        };
        if line.is_empty() {
            break;
        }
        if let Some(i) = line.find(':') {
            rheaders.push((line[..i].trim().to_string(), line[i + 1..].trim().to_string()));
        }
    }
    let hv = |name: &str| rheaders.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.clone());
    let body = if method == "HEAD" || status == 204 || status == 304 || (100..200).contains(&status) {
        Vec::new()
    } else if hv("transfer-encoding").map(|v| v.to_ascii_lowercase().contains("chunked")).unwrap_or(false) {
        read_chunked(&mut stream, &mut buf).map_err(|e| format!("body: {}", e))?
    } else if let Some(cl) = hv("content-length") {
        let n: usize = cl.trim().parse().map_err(|_| "body: invalid content-length".to_string())?;
        read_exact_buffered(&mut stream, &mut buf, n).map_err(|e| format!("body: {}", e))?
    } else {
        read_to_end_buffered(&mut stream, &mut buf).map_err(|e| format!("body: {}", e))?
    };
    Ok((status, status_text, rheaders, body))
}

fn parse_status_line(line: &str) -> Option<(u16, String)> {
    let rest = line.strip_prefix("HTTP/")?;
    let mut it = rest.splitn(2, ' ');
    let _ver = it.next()?;
    let rest = it.next()?;
    let (code, text) = match rest.find(' ') {
        Some(i) => (&rest[..i], rest[i + 1..].to_string()),
        None => (rest, String::new()),
    };
    if code.len() != 3 || !code.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some((code.parse().ok()?, text))
}

/// We cannot speak TLS (std only): probe the peer the way a failed handshake would look.
fn tls_failure(stream: &mut TcpStream) -> String {
    // minimal TLS 1.2 ClientHello record header + body
    let hello: [u8; 5] = [0x16, 0x03, 0x01, 0x00, 0x00];
    let _ = stream.write_all(&hello);
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let mut b = [0u8; 5];
    match stream.read(&mut b) {
        Ok(0) | Err(_) => "TLS handshake failed (SSL error 1: error:0A000126:SSL routines::unexpected eof while reading)".to_string(),
        Ok(_) => "TLS handshake failed (SSL error 1: error:0A00010B:SSL routines::wrong version number)".to_string(),
    }
}

// =====================================================================================
// Lumen.serve (HTTP/1.1 server)
// =====================================================================================

pub struct ServerState {
    pub id: u64,
    pub entry: Value,
    pub listener: Arc<TcpListener>,
    pub shutdown: Arc<AtomicBool>,
    pub hostname: String,
    pub port: u16,
    pub next_conn: Cell<u64>,
    pub closed: Cell<bool>,
}

thread_local! {
    static NEXT_SERVER: Cell<u64> = const { Cell::new(1) };
}

pub struct RawRequest {
    pub method: String,
    pub target: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

enum Accepted {
    Conn(TcpStream, std::net::SocketAddr),
    Closed,
}

fn lumen_serve(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let a0 = a.arg(0);
    let a1 = a.arg(1);
    let (handler, options, from_obj) = if a0.is_callable() {
        let o = if a1.truthy() && a1.type_of() == "object" { a1.clone() } else { new_obj(vm) };
        (a0.clone(), o, false)
    } else if a0.truthy() && a0.type_of() == "object" && a1.is_callable() {
        (a1.clone(), a0.clone(), false)
    } else if a0.truthy() && a0.type_of() == "object" && get(vm, &a0, "fetch")?.is_callable() {
        let f = get(vm, &a0, "fetch")?;
        let bound = invoke(vm, &f, "bind", &[a0.clone()])?;
        (bound, a0.clone(), true)
    } else {
        return vm.throw_type("Lumen.serve requires a handler function or an object with a fetch() method");
    };
    let hn = get(vm, &options, "hostname")?;
    let hostname = if let Value::Str(s) = &hn { s.to_rust_string() } else { "0.0.0.0".to_string() };
    let pv = get(vm, &options, "port")?;
    let port_num = if let Value::Num(n) = pv { n } else { 8000.0 };
    let ol = get(vm, &options, "onListen")?;
    let on_listen = if ol.is_callable() { ol } else { Value::Null };
    let on_error = if !from_obj {
        let oe = get(vm, &options, "onError")?;
        if oe.is_callable() {
            oe
        } else {
            Value::Null
        }
    } else {
        Value::Null
    };
    // __http_server.listen(hostname, port)
    if !(0.0..=65535.0).contains(&port_num) {
        return vm.throw_type("listen: port must be 0..=65535");
    }
    let port = port_num.trunc() as u16;
    let listener = match TcpListener::bind((hostname.as_str(), port)) {
        Ok(l) => l,
        Err(e) => {
            return Err(vm.make_error("Error", &format!("listen {}:{}: {}", hostname, port, e)));
        }
    };
    let bound_port = listener.local_addr().map(|a| a.port()).unwrap_or(port);
    let _ = listener.set_nonblocking(true);
    let id = NEXT_SERVER.with(|n| {
        let v = n.get();
        n.set(v + 1);
        v
    });
    let finished_cap = vm.new_promise_capability_intrinsic();
    let entry = Value::Obj(vm.obj_from(vec![("handler", handler), ("onError", on_error), ("resolveFinished", finished_cap.resolve.clone())]));
    let state = Rc::new(ServerState {
        id,
        entry,
        listener: Arc::new(listener),
        shutdown: Arc::new(AtomicBool::new(false)),
        hostname: hostname.clone(),
        port: bound_port,
        next_conn: Cell::new(0),
        closed: Cell::new(false),
    });
    SERVERS.with(|s| s.borrow_mut().insert(id, state.clone()));
    spawn_accept(vm, state);
    let finished = finished_cap.promise.clone();
    let shutdown = func(vm, "shutdown", 0, server_shutdown, vec![Value::Num(id as f64), finished.clone()]);
    let signal = get(vm, &options, "signal")?;
    if signal.truthy() && get(vm, &signal, "addEventListener")?.is_callable() {
        if get(vm, &signal, "aborted")?.truthy() {
            vm.call(&shutdown, Value::Undefined, &[])?;
        } else {
            let opts = Value::Obj(vm.obj_from(vec![("once", Value::Bool(true))]));
            invoke(vm, &signal, "addEventListener", &[Value::str("abort"), shutdown.clone(), opts])?;
        }
    }
    if on_listen.is_callable() {
        let info = Value::Obj(vm.obj_from(vec![("hostname", Value::str(&hostname)), ("port", Value::Num(bound_port as f64))]));
        vm.call(&on_listen, Value::Undefined, &[info])?;
    }
    let srv = vm.obj_from(vec![("hostname", Value::str(&hostname)), ("port", Value::Num(bound_port as f64)), ("finished", finished), ("shutdown", shutdown)]);
    let r = func(vm, "ref", 0, |_vm, _a| Ok(Value::Undefined), vec![]);
    let u = func(vm, "unref", 0, |_vm, _a| Ok(Value::Undefined), vec![]);
    srv.set_str("ref", r, WEC);
    srv.set_str("unref", u, WEC);
    Ok(Value::Obj(srv))
}

fn server_shutdown(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = a.slot(0).as_num().unwrap_or(0.0) as u64;
    if let Some(s) = SERVERS.with(|m| m.borrow().get(&id).cloned()) {
        if !s.shutdown.swap(true, Ordering::SeqCst) {
            // the listener closes right away; `finished` settles on the next timer turn
            let r = get(vm, &s.entry, "resolveFinished")?;
            super::timers::add_timer(vm, r, 0.0, vec![], false);
        }
    }
    Ok(a.slot(1))
}

fn spawn_accept(vm: &mut Vm, state: Rc<ServerState>) {
    let listener = state.listener.clone();
    let flag = state.shutdown.clone();
    let id = state.id;
    super::spawn_op(
        vm,
        move || loop {
            if flag.load(Ordering::SeqCst) {
                return Accepted::Closed;
            }
            match listener.accept() {
                Ok((s, addr)) => {
                    let _ = s.set_nonblocking(false);
                    return Accepted::Conn(s, addr);
                }
                Err(_) => std::thread::sleep(Duration::from_millis(2)),
            }
        },
        move |vm, acc: Accepted| on_accept(vm, id, acc),
    );
}

fn on_accept(vm: &mut Vm, id: u64, acc: Accepted) {
    let state = match SERVERS.with(|m| m.borrow().get(&id).cloned()) {
        Some(s) => s,
        None => return,
    };
    match acc {
        Accepted::Closed => {
            if !state.closed.get() {
                state.closed.set(true);
                SERVERS.with(|m| m.borrow_mut().remove(&id));
            }
        }
        Accepted::Conn(stream, addr) => {
            let conn_id = state.next_conn.get();
            state.next_conn.set(conn_id + 1);
            spawn_accept(vm, state.clone());
            let state = state.clone();
            super::spawn_op(
                vm,
                move || {
                    let mut s = stream;
                    let r = read_http_request(&mut s);
                    (s, r)
                },
                move |vm, (s, r): (TcpStream, Result<RawRequest, String>)| match r {
                    Ok(req) => {
                        CONNS.with(|c| c.borrow_mut().insert(conn_id_key(id, conn_id), s));
                        dispatch_request(vm, state, conn_id, addr, req);
                    }
                    Err(msg) => {
                        let body = msg.into_bytes();
                        let mut out = format!("HTTP/1.1 400 Bad Request\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).into_bytes();
                        out.extend_from_slice(&body);
                        write_and_close(vm, s, out);
                    }
                },
            );
        }
    }
}

pub fn conn_id_key(server: u64, conn: u64) -> u64 {
    (server << 32) | conn
}

pub fn take_conn(key: u64) -> Option<TcpStream> {
    CONNS.with(|c| c.borrow_mut().remove(&key))
}

fn write_and_close(vm: &mut Vm, stream: TcpStream, data: Vec<u8>) {
    super::spawn_op(
        vm,
        move || {
            let mut s = stream;
            let _ = s.write_all(&data);
            let _ = s.flush();
            let _ = s.shutdown(Shutdown::Write);
            // drain briefly so the peer sees an orderly close
            let _ = s.set_read_timeout(Some(Duration::from_millis(200)));
            let mut tmp = [0u8; 1024];
            let _ = s.read(&mut tmp);
        },
        |_vm, _: ()| {},
    );
}

fn read_http_request(stream: &mut TcpStream) -> Result<RawRequest, String> {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
    let mut buf: Vec<u8> = Vec::new();
    let first = match read_line(stream, &mut buf) {
        Ok(Some(l)) => l,
        _ => return Err("empty request".into()),
    };
    if first.is_empty() && buf.is_empty() {
        return Err("empty request".into());
    }
    let mut parts = first.split(' ').filter(|s| !s.is_empty());
    let method = parts.next().unwrap_or("GET").to_string();
    let target = parts.next().unwrap_or("/").to_string();
    let mut headers = Vec::new();
    while let Ok(Some(line)) = read_line(stream, &mut buf) {
        if line.is_empty() {
            break;
        }
        if let Some(i) = line.find(':') {
            headers.push((line[..i].to_string(), line[i + 1..].trim().to_string()));
        }
    }
    let hv = |name: &str| headers.iter().find(|(k, _): &&(String, String)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.clone());
    let body = if hv("transfer-encoding").map(|v| v.to_ascii_lowercase().contains("chunked")).unwrap_or(false) {
        read_chunked(stream, &mut buf).unwrap_or_default()
    } else if let Some(cl) = hv("content-length") {
        match cl.trim().parse::<usize>() {
            Ok(n) => read_exact_buffered(stream, &mut buf, n).unwrap_or_default(),
            Err(_) => Vec::new(),
        }
    } else {
        Vec::new()
    };
    Ok(RawRequest { method, target, headers, body })
}

pub fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        201 => "Created",
        202 => "Accepted",
        204 => "No Content",
        301 => "Moved Permanently",
        302 => "Found",
        303 => "See Other",
        304 => "Not Modified",
        307 => "Temporary Redirect",
        308 => "Permanent Redirect",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        410 => "Gone",
        422 => "Unprocessable Entity",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        501 => "Not Implemented",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        _ => "",
    }
}

struct Dispatch {
    cap: Capability,
    server: u64,
    conn: u64,
    entry: Value,
    conn_obj: Value,
}

fn dispatch_request(vm: &mut Vm, state: Rc<ServerState>, conn: u64, addr: std::net::SocketAddr, req: RawRequest) {
    let server = state.id;
    let c = fctx();
    let cap = vm.new_promise_capability_intrinsic();
    let conn_obj = Value::Obj(vm.obj_from(vec![
        ("connId", Value::Num(conn as f64)),
        ("upgraded", Value::Bool(false)),
        ("remoteAddress", Value::str(&addr.ip().to_string())),
    ]));
    if let Value::Obj(o) = &conn_obj {
        o.set_prop(priv_key(), Value::Num(conn_id_key(server, conn) as f64), WC);
    }
    let st = Rc::new(Dispatch { cap, server, conn, entry: state.entry.clone(), conn_obj: conn_obj.clone() });
    let data = host(st.clone());
    let r = (|| -> JsResult<Value> {
        let host_hdr = req.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case("host")).map(|(_, v)| v.clone());
        let url = if req.target.starts_with("http://") || req.target.starts_with("https://") {
            req.target.clone()
        } else {
            let h = host_hdr.unwrap_or_else(|| format!("{}:{}", state.hostname, state.port));
            format!("http://{}{}", h, req.target)
        };
        let mut pairs = Vec::new();
        for (k, v) in &req.headers {
            pairs.push(new_arr(vm, vec![Value::str(k), Value::str(v)]));
        }
        let pairs = new_arr(vm, pairs);
        let upper = req.method.to_uppercase();
        let body = if !req.body.is_empty() && upper != "GET" && upper != "HEAD" { new_u8(vm, req.body.clone())? } else { Value::Undefined };
        let init = Value::Obj(vm.obj_from(vec![("method", Value::str(&req.method)), ("headers", pairs), ("body", body)]));
        let request = construct(vm, &c.request, &[Value::str(&url), init])?;
        put_sym(vm, &request, &c.k_conn, conn_obj.clone())?;
        let remote = Value::Obj(vm.obj_from(vec![
            ("transport", Value::str("tcp")),
            ("hostname", Value::str(&addr.ip().to_string())),
            ("port", Value::Num(addr.port() as f64)),
        ]));
        let info = Value::Obj(vm.obj_from(vec![("remoteAddr", remote)]));
        let handler = get(vm, &st.entry, "handler")?;
        call_method(vm, &handler, &st.entry, "handler", &[request, info])
    })();
    match r {
        Ok(v) => await_value(vm, v, &data, dispatch_handler_ok, dispatch_handler_err),
        Err(e) => dispatch_catch(vm, &data, e),
    }
}

fn dispatch_handler_ok(vm: &mut Vm, v: Value, data: &Value) -> JsResult<Value> {
    let c = fctx();
    if vm.instance_of(&v, &Value::Obj(c.response.clone())).unwrap_or(false) {
        dispatch_send(vm, data, v);
    } else {
        let e = type_error(vm, "serve handler did not return a Response");
        dispatch_catch(vm, data, e);
    }
    Ok(Value::Undefined)
}

fn dispatch_handler_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    dispatch_catch(vm, data, e);
    Ok(Value::Undefined)
}

fn dispatch_catch(vm: &mut Vm, data: &Value, e: Value) {
    let st = unhost::<Dispatch>(data);
    if get(vm, &st.conn_obj, "upgraded").map(|v| v.truthy()).unwrap_or(false) {
        settle(vm, &st.cap, Ok(Value::Undefined));
        return;
    }
    let on_error = get(vm, &st.entry, "onError").unwrap_or(Value::Null);
    if on_error.truthy() {
        match call_method(vm, &on_error, &st.entry, "onError", &[e]) {
            Ok(v) => await_value(vm, v, data, dispatch_on_error_ok, dispatch_on_error_err),
            Err(e2) => {
                let _ = dispatch_on_error_err(vm, e2, data);
            }
        }
        return;
    }
    print_server_error(vm, &e);
    let r = internal_error_response(vm);
    match r {
        Ok(resp) => dispatch_send(vm, data, resp),
        Err(e) => super::report_uncaught(vm, &e),
    }
}

fn print_server_error(vm: &mut Vm, e: &Value) {
    let console = global(vm, "console");
    if invoke(vm, &console, "error", &[e.clone()]).is_err() {
        let s = super::display_value(vm, e);
        super::write_stderr(&format!("{}\n", s));
    }
}

fn internal_error_response(vm: &mut Vm) -> JsResult<Value> {
    let c = fctx();
    let init = Value::Obj(vm.obj_from(vec![("status", Value::Num(500.0))]));
    construct(vm, &c.response, &[Value::str("Internal Server Error"), init])
}

fn dispatch_on_error_ok(vm: &mut Vm, v: Value, data: &Value) -> JsResult<Value> {
    dispatch_send(vm, data, v);
    Ok(Value::Undefined)
}

fn dispatch_on_error_err(vm: &mut Vm, e: Value, data: &Value) -> JsResult<Value> {
    print_server_error(vm, &e);
    if let Ok(resp) = internal_error_response(vm) {
        dispatch_send(vm, data, resp);
    }
    Ok(Value::Undefined)
}

/// Serialise `response` onto the connection.
fn dispatch_send(vm: &mut Vm, data: &Value, response: Value) {
    let st = unhost::<Dispatch>(data);
    let key = conn_id_key(st.server, st.conn);
    let upgraded = get(vm, &st.conn_obj, "upgraded").map(|v| v.truthy()).unwrap_or(false);
    if upgraded {
        return;
    }
    let r = (|| -> JsResult<Vec<u8>> {
        let headers = get(vm, &response, "headers")?;
        let pairs = header_pairs_rust(vm, &headers)?;
        let body = match invoke(vm, &response, "_materialize", &[]) {
            Ok(_) => {
                let b = get(vm, &response, "_bodyBytes")?;
                if b.is_undefined() || b.is_null() {
                    Vec::new()
                } else {
                    bytes_from_u8(&b)
                }
            }
            Err(_) => Vec::new(),
        };
        let status = get(vm, &response, "status")?;
        let status_s = vm.to_string(&status)?.to_rust_string();
        let status_n = vm.to_number(&status)?;
        let stt = get(vm, &response, "statusText")?;
        let stt = if stt.truthy() { vm.to_string(&stt)?.to_rust_string() } else { reason_phrase(status_n as u16).to_string() };
        let mut head = format!("HTTP/1.1 {} {}\r\n", status_s, stt);
        let mut has_cl = false;
        let mut has_server = false;
        for (k, v) in &pairs {
            if k == "connection" {
                continue;
            }
            if k == "content-length" {
                has_cl = true;
            }
            if k == "server" {
                has_server = true;
            }
            head.push_str(&format!("{}: {}\r\n", k, v));
        }
        if !has_cl {
            head.push_str(&format!("Content-Length: {}\r\n", body.len()));
        }
        if !has_server {
            head.push_str(&format!("Server: lumen/{}\r\n", VERSION));
        }
        head.push_str("Connection: close\r\n\r\n");
        let mut out = head.into_bytes();
        out.extend_from_slice(&body);
        Ok(out)
    })();
    match r {
        Ok(bytes) => {
            if let Some(s) = take_conn(key) {
                write_and_close(vm, s, bytes);
            }
        }
        Err(e) => {
            // mirrors an unhandled rejection inside the reference dispatcher
            let p = rejected(vm, e);
            let _ = p;
        }
    }
    settle(vm, &st.cap, Ok(Value::Undefined));
}


// =====================================================================================
// WebSocket client, Lumen.upgradeWebSocket (server side) and EventSource
// =====================================================================================

const WS_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC11B65";
const CONNECTING: u8 = 0;
const OPEN: u8 = 1;
const CLOSING: u8 = 2;
const CLOSED: u8 = 3;

thread_local! {
    static PRIV_KEY: Sym = Sym::new_private(JsStr::from_str("#state"));
    static WS_UPGRADED: RefCell<HashMap<u64, Rc<ServerWs>>> = RefCell::new(HashMap::new());
    static NEXT_WS: Cell<u64> = const { Cell::new(1) };
}

fn priv_key() -> PropKey {
    PRIV_KEY.with(|k| PropKey::Sym(k.clone()))
}

fn set_private<T: 'static>(o: &Value, v: Rc<T>) {
    if let Value::Obj(o) = o {
        o.set_prop(priv_key(), host(v), WC);
    }
}

fn get_private<T: 'static>(vm: &mut Vm, o: &Value, what: &str) -> JsResult<Rc<T>> {
    if let Value::Obj(ob) = o {
        if let Some(Value::Obj(h)) = ob.get_own_data(&priv_key()) {
            if let ObjKind::Host(b) = &h.borrow().kind {
                if let Some(r) = b.downcast_ref::<Rc<T>>() {
                    return Ok(r.clone());
                }
            }
        }
    }
    vm.throw_type(format!("Cannot read private member {} from an object whose class did not declare it", what))
}

fn dom_exception(vm: &mut Vm, msg: &str, name: &str) -> Value {
    match make_dom_exception(vm, msg, name) {
        Ok(v) => v,
        Err(e) => e,
    }
}

/// `new Event(type)` / `new MessageEvent(type, init)` / `new CloseEvent(type, init)` via the
/// globals, with plain-object fallbacks.
fn make_event(vm: &mut Vm, class: &str, ty: &str, init: Option<Value>) -> JsResult<Value> {
    let c = global(vm, class);
    if matches!(&c, Value::Obj(o) if o.is_constructor()) {
        let mut args = vec![Value::str(ty)];
        if let Some(i) = init.clone() {
            args.push(i);
        }
        return vm.construct(&c, &args, None);
    }
    let o = vm.obj_from(vec![("type", Value::str(ty))]);
    if let Some(Value::Obj(i)) = init {
        for k in vm.enumerable_own_keys(&i)? {
            let v = vm.get(&i, &PropKey::Str(k.clone()), &Value::Obj(i.clone()))?;
            o.set_prop(PropKey::Str(k), v, WEC);
        }
    }
    Ok(Value::Obj(o))
}

/// `#fireEvent(type, event)`: `on<type>` handler (errors reported), then dispatchEvent.
fn fire_event(vm: &mut Vm, target: &Value, ty: &str, event: Value) {
    let handler = get(vm, target, &format!("on{}", ty)).unwrap_or(Value::Undefined);
    if handler.is_callable() {
        if let Err(e) = vm.call(&handler, target.clone(), &[event.clone()]) {
            let re = global(vm, "reportError");
            if re.is_callable() {
                let _ = vm.call(&re, Value::Undefined, &[e]);
            } else {
                super::report_uncaught(vm, &e);
            }
        }
    }
    let d = get(vm, target, "dispatchEvent").unwrap_or(Value::Undefined);
    if d.is_callable() {
        if let Err(e) = vm.call(&d, target.clone(), &[event]) {
            super::report_uncaught(vm, &e);
        }
    }
}

/// `super()` for classes extending the global EventTarget.
fn construct_event_target(vm: &mut Vm, a: &Args, fallback: &Obj) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Class constructor cannot be invoked without 'new'");
    }
    let et = global(vm, "EventTarget");
    if let Value::Obj(eto) = &et {
        if eto.is_constructor() {
            // late-bind the parent class if EventTarget appeared after setup
            let op = vm.intr.object_proto.clone();
            if fallback.proto().map(|p| p.ptr_eq(&op)).unwrap_or(false) {
                if let Ok(Value::Obj(etp)) = vm.get_str(eto, "prototype") {
                    fallback.borrow_mut().proto = Some(etp);
                    let c = fctx();
                    for ctor in [&c.ws, &c.es] {
                        if ctor.proto().map(|p| p.ptr_eq(&vm.intr.function_proto)).unwrap_or(false) {
                            let is_mine = matches!(vm.get_str(ctor, "prototype"), Ok(Value::Obj(p)) if p.ptr_eq(fallback));
                            if is_mine {
                                ctor.borrow_mut().proto = Some(eto.clone());
                            }
                        }
                    }
                }
            }
            let nt = Value::Obj(a.new_target.clone().unwrap());
            return vm.construct(&et, &[], Some(&nt));
        }
    }
    new_this(vm, a, fallback)
}

// ---- frames ----

fn ws_frame(opcode: u8, payload: &[u8], mask: bool) -> Vec<u8> {
    let mut out = vec![0x80 | opcode];
    let mbit = if mask { 0x80 } else { 0 };
    let n = payload.len();
    if n < 126 {
        out.push(mbit | n as u8);
    } else if n < 65536 {
        out.push(mbit | 126);
        out.extend_from_slice(&(n as u16).to_be_bytes());
    } else {
        out.push(mbit | 127);
        out.extend_from_slice(&(n as u64).to_be_bytes());
    }
    if mask {
        let key = crate::crypto::random::random_bytes(4);
        out.extend_from_slice(&key);
        out.extend(payload.iter().enumerate().map(|(i, b)| b ^ key[i % 4]));
    } else {
        out.extend_from_slice(payload);
    }
    out
}

fn close_payload(code: u16, reason: &str) -> Vec<u8> {
    let mut p = code.to_be_bytes().to_vec();
    p.extend_from_slice(reason.as_bytes());
    p
}

enum WsMsg {
    Text(Vec<u8>),
    Binary(Vec<u8>),
    Close(Option<u16>, String),
    Fail(u16, String),
    Io(String),
}

fn read_frame(s: &mut TcpStream) -> std::io::Result<(bool, u8, Vec<u8>)> {
    let mut h = [0u8; 2];
    s.read_exact(&mut h)?;
    let fin = h[0] & 0x80 != 0;
    let op = h[0] & 0x0F;
    let masked = h[1] & 0x80 != 0;
    let mut len = (h[1] & 0x7F) as u64;
    if len == 126 {
        let mut b = [0u8; 2];
        s.read_exact(&mut b)?;
        len = u16::from_be_bytes(b) as u64;
    } else if len == 127 {
        let mut b = [0u8; 8];
        s.read_exact(&mut b)?;
        len = u64::from_be_bytes(b);
    }
    let mut key = [0u8; 4];
    if masked {
        s.read_exact(&mut key)?;
    }
    if len > (64 << 20) {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, "frame too large"));
    }
    let mut p = vec![0u8; len as usize];
    s.read_exact(&mut p)?;
    if masked {
        for (i, b) in p.iter_mut().enumerate() {
            *b ^= key[i % 4];
        }
    }
    Ok((fin, op, p))
}

/// Read one complete message; answers pings itself. `mask` = whether our replies are masked.
fn read_ws_message(s: &mut TcpStream, mask: bool) -> WsMsg {
    let mut buf: Vec<u8> = Vec::new();
    let mut kind: Option<u8> = None;
    loop {
        let (fin, op, p) = match read_frame(s) {
            Ok(f) => f,
            Err(e) => return WsMsg::Io(e.to_string()),
        };
        match op {
            0x0 | 0x1 | 0x2 => {
                if op != 0 {
                    kind = Some(op);
                    buf.clear();
                }
                buf.extend_from_slice(&p);
                if fin {
                    return match kind {
                        Some(1) => {
                            if std::str::from_utf8(&buf).is_err() {
                                WsMsg::Fail(1007, "invalid UTF-8 in text frame".into())
                            } else {
                                WsMsg::Text(buf)
                            }
                        }
                        _ => WsMsg::Binary(buf),
                    };
                }
            }
            0x8 => {
                if p.len() >= 2 {
                    let code = u16::from_be_bytes([p[0], p[1]]);
                    return WsMsg::Close(Some(code), String::from_utf8_lossy(&p[2..]).to_string());
                }
                return WsMsg::Close(None, String::new());
            }
            0x9 => {
                let _ = s.write_all(&ws_frame(0xA, &p, mask));
            }
            0xA => {}
            _ => return WsMsg::Fail(1002, "unknown opcode".into()),
        }
    }
}

// ---- client ----

pub struct WsState {
    url: String,
    ready_state: Cell<u8>,
    binary_type: RefCell<String>,
    protocol: RefCell<String>,
    writer: RefCell<Option<TcpStream>>,
    close_sent: Cell<bool>,
    this: RefCell<Value>,
}

fn install_websocket(vm: &mut Vm, ctor: &Obj, proto: &Obj) {
    for (n, v) in [("CONNECTING", 0.0), ("OPEN", 1.0), ("CLOSING", 2.0), ("CLOSED", 3.0)] {
        let g = vm.native_closure(&format!("get {}", n), 0, |_vm, a| Ok(a.slot(0)), vec![Value::Num(v)]);
        ctor.set_accessor(PropKey::from_str(n), Some(g), None, CONFIGURABLE);
    }
    for (n, v) in [("CONNECTING", 0.0), ("OPEN", 1.0), ("CLOSING", 2.0), ("CLOSED", 3.0)] {
        let g = vm.native_closure(&format!("get {}", n), 0, |_vm, a| Ok(a.slot(0)), vec![Value::Num(v)]);
        proto.set_accessor(PropKey::from_str(n), Some(g), None, CONFIGURABLE);
    }
    vm.def_getter(proto, "url", |vm, a| Ok(Value::str(&get_private::<WsState>(vm, &a.this, "#url")?.url)));
    vm.def_getter(proto, "readyState", |vm, a| Ok(Value::Num(get_private::<WsState>(vm, &a.this, "#readyState")?.ready_state.get() as f64)));
    vm.def_getter(proto, "bufferedAmount", |vm, a| get_private::<WsState>(vm, &a.this, "#bufferedAmount").map(|_| Value::Num(0.0)));
    vm.def_getter(proto, "extensions", |vm, a| get_private::<WsState>(vm, &a.this, "#extensions").map(|_| Value::str("")));
    vm.def_getter(proto, "protocol", |vm, a| Ok(Value::str(&get_private::<WsState>(vm, &a.this, "#protocol")?.protocol.borrow())));
    vm.def_accessor(proto, "binaryType", |vm, a| Ok(Value::str(&get_private::<WsState>(vm, &a.this, "#binaryType")?.binary_type.borrow())), ws_set_binary_type);
    vm.def_method(proto, "send", 1, ws_send);
    vm.def_method(proto, "close", 2, ws_close);
    for n in ["onopen", "onmessage", "onerror", "onclose"] {
        proto.set_str(n, Value::Null, WEC);
    }
}

fn ws_set_binary_type(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = get_private::<WsState>(vm, &a.this, "#binaryType")?;
    let v = a.arg(0);
    if is_str(&v, "blob") || is_str(&v, "arraybuffer") {
        *st.binary_type.borrow_mut() = vm.to_string(&v)?.to_rust_string();
        Ok(Value::Undefined)
    } else {
        vm.throw_syntax("binaryType must be 'blob' or 'arraybuffer'")
    }
}

/// URL parsing for WebSocket/EventSource: `new URL(String(url))` -> (href, protocol, hash, origin).
fn parse_global_url(vm: &mut Vm, url: &Value) -> JsResult<Option<(String, String, String, String)>> {
    let s = js_string(vm, url)?;
    let u = global(vm, "URL");
    if matches!(&u, Value::Obj(o) if o.is_constructor()) {
        let r = vm.construct(&u, &[Value::Str(s)], None);
        let parsed = match r {
            Ok(p) => p,
            Err(_) => return Ok(None),
        };
        let href = get(vm, &parsed, "href")?;
        let proto = get(vm, &parsed, "protocol")?;
        let hash = get(vm, &parsed, "hash")?;
        let origin = get(vm, &parsed, "origin")?;
        return Ok(Some((str_value(vm, &href)?, str_value(vm, &proto)?, str_value(vm, &hash)?, str_value(vm, &origin)?)));
    }
    Ok(parse_url(&s.to_rust_string()).map(|p| {
        let origin = format!("{}://{}", p.scheme, p.host_port());
        (p.href(), format!("{}:", p.scheme), p.fragment.clone(), origin)
    }))
}

fn normalize_protocols(vm: &mut Vm, v: &Value) -> JsResult<Vec<String>> {
    let list: Vec<String> = if v.is_nullish() {
        Vec::new()
    } else if let Value::Str(s) = v {
        vec![s.to_rust_string()]
    } else if v.is_object() && !v.is_callable() && get(vm, v, "length")?.type_of() == "number" {
        let items = crate::builtins::array::array_like_to_vec(vm, v)?;
        let mut out = Vec::new();
        for i in items {
            out.push(js_string(vm, &i)?.to_rust_string());
        }
        out
    } else {
        vec![js_string(vm, v)?.to_rust_string()]
    };
    let mut seen = std::collections::HashSet::new();
    for p in &list {
        let ok = !p.is_empty() && p.bytes().all(|c| c.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&c));
        if !ok || !seen.insert(p.clone()) {
            let e = dom_exception(vm, "invalid or duplicate WebSocket subprotocol", "SyntaxError");
            return Err(e);
        }
    }
    Ok(list)
}

fn ws_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = construct_event_target(vm, a, &c.ws_proto)?;
    if a.args.is_empty() {
        return vm.throw_type("WebSocket constructor requires a url");
    }
    let url = a.arg(0);
    let parsed = parse_global_url(vm, &url)?;
    let (href, protocol, hash, _origin) = match parsed {
        Some(p) => p,
        None => {
            let shown = vm.to_string(&url)?.to_rust_string();
            return Err(dom_exception(vm, &format!("invalid WebSocket URL: {}", shown), "SyntaxError"));
        }
    };
    if protocol != "ws:" && protocol != "wss:" {
        return Err(dom_exception(vm, &format!("WebSocket URL scheme must be ws or wss, got '{}'", protocol), "SyntaxError"));
    }
    if !hash.is_empty() {
        return Err(dom_exception(vm, "WebSocket URL must not contain a fragment", "SyntaxError"));
    }
    let protocols = normalize_protocols(vm, &a.arg(1))?;
    let st = Rc::new(WsState {
        url: href.clone(),
        ready_state: Cell::new(CONNECTING),
        binary_type: RefCell::new("blob".into()),
        protocol: RefCell::new(String::new()),
        writer: RefCell::new(None),
        close_sent: Cell::new(false),
        this: RefCell::new(this.clone()),
    });
    set_private(&this, st.clone());
    let joined = protocols.join(", ");
    let data = host(st);
    super::spawn_op(vm, move || ws_client_connect(&href, &joined), move |vm, r: Result<(TcpStream, String), String>| ws_client_connected(vm, &data, r));
    Ok(this)
}

fn ws_client_connect(url: &str, protocols: &str) -> Result<(TcpStream, String), String> {
    let u = parse_url(url).ok_or_else(|| "invalid url".to_string())?;
    let mut s = TcpStream::connect((u.connect_host().as_str(), u.effective_port())).map_err(|e| format!("connect: {}", e))?;
    if u.scheme == "wss" {
        return Err(tls_failure(&mut s));
    }
    let key = super::encoding::base64_encode(&crate::crypto::random::random_bytes(16), false);
    let mut req = format!(
        "GET {} HTTP/1.1\r\nHost: {}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n",
        u.path_and_query(),
        u.host_port(),
        key
    );
    if !protocols.is_empty() {
        req.push_str(&format!("Sec-WebSocket-Protocol: {}\r\n", protocols));
    }
    req.push_str("\r\n");
    s.write_all(req.as_bytes()).map_err(|e| e.to_string())?;
    // read the handshake response byte-wise up to the blank line
    let mut head = Vec::new();
    let mut b = [0u8; 1];
    while !head.ends_with(b"\r\n\r\n") {
        match s.read(&mut b) {
            Ok(1) => head.push(b[0]),
            _ => return Err("handshake: connection closed".into()),
        }
        if head.len() > 65536 {
            return Err("handshake: response too large".into());
        }
    }
    let text = String::from_utf8_lossy(&head).to_string();
    let mut lines = text.split("\r\n");
    let status = lines.next().unwrap_or("");
    if parse_status_line(status).map(|x| x.0) != Some(101) {
        return Err(format!("handshake: unexpected status line {:?}", status));
    }
    let mut accept = None;
    let mut proto = String::new();
    for l in lines {
        if let Some(i) = l.find(':') {
            let k = l[..i].trim().to_ascii_lowercase();
            let v = l[i + 1..].trim().to_string();
            if k == "sec-websocket-accept" {
                accept = Some(v);
            } else if k == "sec-websocket-protocol" {
                proto = v;
            }
        }
    }
    let expect = super::encoding::base64_encode(&crate::crypto::hash::digest(crate::crypto::hash::HashAlg::Sha1, format!("{}{}", key, WS_GUID).as_bytes()), false);
    if accept.as_deref() != Some(expect.as_str()) {
        return Err("handshake: bad Sec-WebSocket-Accept".into());
    }
    Ok((s, proto))
}

fn ws_client_connected(vm: &mut Vm, data: &Value, r: Result<(TcpStream, String), String>) {
    let st = unhost::<WsState>(data);
    let this = st.this.borrow().clone();
    match r {
        Ok((s, proto)) => {
            let reader = s.try_clone();
            *st.writer.borrow_mut() = Some(s);
            st.ready_state.set(OPEN);
            *st.protocol.borrow_mut() = proto;
            if let Ok(ev) = make_event(vm, "Event", "open", None) {
                fire_event(vm, &this, "open", ev);
            }
            if let Ok(rs) = reader {
                ws_client_read(vm, data.clone(), rs);
            }
        }
        Err(_) => ws_client_fail(vm, &st, 1006, ""),
    }
}

fn ws_client_fail(vm: &mut Vm, st: &Rc<WsState>, code: u16, reason: &str) {
    let this = st.this.borrow().clone();
    st.ready_state.set(CLOSED);
    if let Ok(ev) = make_event(vm, "Event", "error", None) {
        fire_event(vm, &this, "error", ev);
    }
    let init = Value::Obj(vm.obj_from(vec![("code", Value::Num(code as f64)), ("reason", Value::str(reason)), ("wasClean", Value::Bool(false))]));
    if let Ok(ev) = make_event(vm, "CloseEvent", "close", Some(init)) {
        fire_event(vm, &this, "close", ev);
    }
}

fn ws_client_read(vm: &mut Vm, data: Value, stream: TcpStream) {
    super::spawn_op(
        vm,
        move || {
            let mut s = stream;
            let m = read_ws_message(&mut s, true);
            (s, m)
        },
        move |vm, (s, m): (TcpStream, WsMsg)| ws_client_on_message(vm, data, s, m),
    );
}

fn ws_client_on_message(vm: &mut Vm, data: Value, s: TcpStream, m: WsMsg) {
    let st = unhost::<WsState>(&data);
    let this = st.this.borrow().clone();
    match m {
        WsMsg::Text(t) => {
            if st.ready_state.get() == OPEN {
                let text = Value::Str(super::streams::decode_text(&t));
                let init = Value::Obj(vm.obj_from(vec![("data", text), ("origin", Value::str(&st.url))]));
                if let Ok(ev) = make_event(vm, "MessageEvent", "message", Some(init)) {
                    fire_event(vm, &this, "message", ev);
                }
            }
            ws_client_read(vm, data, s);
        }
        WsMsg::Binary(b) => {
            if st.ready_state.get() == OPEN {
                let payload = if st.binary_type.borrow().as_str() == "arraybuffer" {
                    Ok(Value::Obj(crate::builtins::typedarray::new_array_buffer(vm, b)))
                } else {
                    new_u8(vm, b).and_then(|u| {
                        let parts = new_arr(vm, vec![u]);
                        construct_global(vm, "Blob", &[parts])
                    })
                };
                if let Ok(d) = payload {
                    let init = Value::Obj(vm.obj_from(vec![("data", d), ("origin", Value::str(&st.url))]));
                    if let Ok(ev) = make_event(vm, "MessageEvent", "message", Some(init)) {
                        fire_event(vm, &this, "message", ev);
                    }
                }
            }
            ws_client_read(vm, data, s);
        }
        WsMsg::Close(code, reason) => {
            if !st.close_sent.get() {
                st.close_sent.set(true);
                let payload = match code {
                    Some(c) => c.to_be_bytes().to_vec(),
                    None => Vec::new(),
                };
                if let Some(w) = st.writer.borrow_mut().as_mut() {
                    let _ = w.write_all(&ws_frame(0x8, &payload, true));
                }
            }
            let _ = s.shutdown(Shutdown::Both);
            st.ready_state.set(CLOSED);
            let init = Value::Obj(vm.obj_from(vec![
                ("code", Value::Num(code.unwrap_or(1005) as f64)),
                ("reason", Value::str(&reason)),
                ("wasClean", Value::Bool(true)),
            ]));
            if let Ok(ev) = make_event(vm, "CloseEvent", "close", Some(init)) {
                fire_event(vm, &this, "close", ev);
            }
        }
        WsMsg::Fail(code, reason) => {
            let _ = s.shutdown(Shutdown::Both);
            if st.ready_state.get() != CLOSED {
                ws_client_fail(vm, &st, code, &reason);
            }
        }
        WsMsg::Io(_) => {
            if st.ready_state.get() != CLOSED {
                ws_client_fail(vm, &st, 1006, "");
            }
        }
    }
}

fn ws_send(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = get_private::<WsState>(vm, &a.this, "#readyState")?;
    if st.ready_state.get() == CONNECTING {
        return Err(dom_exception(vm, "WebSocket is still CONNECTING", "InvalidStateError"));
    }
    if st.ready_state.get() != OPEN {
        return Ok(Value::Undefined);
    }
    let data = a.arg(0);
    let frame = if let Value::Str(s) = &data {
        ws_frame(0x1, &str_to_utf8(s.units()), true)
    } else if is_array_buffer(&data) || is_view(&data) {
        ws_frame(0x2, &bytes_from_u8(&data), true)
    } else if data.truthy() && get(vm, &data, "arrayBuffer")?.is_callable() {
        let p = invoke(vm, &data, "arrayBuffer", &[])?;
        let cb = func(vm, "", 1, ws_send_blob_cb, vec![host(st.clone())]);
        invoke(vm, &p, "then", &[cb])?;
        return Ok(Value::Undefined);
    } else {
        let s = js_string(vm, &data)?;
        ws_frame(0x1, &str_to_utf8(s.units()), true)
    };
    if let Some(w) = st.writer.borrow_mut().as_mut() {
        let _ = w.write_all(&frame);
    }
    Ok(Value::Undefined)
}

fn ws_send_blob_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = unhost::<WsState>(&a.slot(0));
    if st.ready_state.get() == OPEN {
        let bytes = bytes_from_u8(&a.arg(0));
        if let Some(w) = st.writer.borrow_mut().as_mut() {
            let _ = w.write_all(&ws_frame(0x2, &bytes, true));
        }
    }
    let _ = vm;
    Ok(Value::Undefined)
}

fn ws_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = get_private::<WsState>(vm, &a.this, "#readyState")?;
    let code = a.arg(0);
    if !code.is_undefined() {
        let is_1000 = Value::strict_eq(&code, &Value::Num(1000.0));
        let in_range = !vm.op_compare(crate::bytecode::Op::Lt, &code, &Value::Num(3000.0))? && !vm.op_compare(crate::bytecode::Op::Gt, &code, &Value::Num(4999.0))?;
        let n = vm.to_number(&code)?;
        if !is_1000 && !(in_range && !n.is_nan()) {
            return Err(dom_exception(vm, "close code must be 1000 or in 3000-4999", "InvalidAccessError"));
        }
    }
    let reason = a.arg(1);
    let r = if reason.is_undefined() { String::new() } else { js_string(vm, &reason)?.to_rust_string() };
    if r.len() > 123 {
        return Err(dom_exception(vm, "close reason too long (>123 bytes)", "SyntaxError"));
    }
    let s = st.ready_state.get();
    if s == CLOSING || s == CLOSED {
        return Ok(Value::Undefined);
    }
    st.ready_state.set(CLOSING);
    let code_n = if code.is_nullish() { 1000 } else { vm.to_number(&code)? as u16 };
    if !st.close_sent.get() {
        if let Some(w) = st.writer.borrow_mut().as_mut() {
            st.close_sent.set(true);
            let _ = w.write_all(&ws_frame(0x8, &close_payload(code_n, &r), true));
        }
    }
    Ok(Value::Undefined)
}

// ---- server side: Lumen.upgradeWebSocket ----

pub struct ServerWs {
    id: u64,
    handle: Value,
    writer: RefCell<Option<TcpStream>>,
    closed: Cell<bool>,
    close_sent: Cell<bool>,
}

fn lumen_upgrade_websocket(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let request = a.arg(0);
    let mut options = a.arg(1);
    if options.is_undefined() {
        options = new_obj(vm);
    }
    let conn = if request.truthy() { get_sym(vm, &request, &c.k_conn)? } else { Value::Undefined };
    if !conn.truthy() {
        return vm.throw_type("upgradeWebSocket: the request was not delivered by Lumen.serve");
    }
    if get(vm, &conn, "upgraded")?.truthy() {
        return Err(vm.make_error("Error", "upgradeWebSocket: connection already upgraded"));
    }
    let headers = get(vm, &request, "headers")?;
    let upgrade = invoke(vm, &headers, "get", &[Value::str("upgrade")])?;
    let headers = get(vm, &request, "headers")?;
    let key = invoke(vm, &headers, "get", &[Value::str("sec-websocket-key")])?;
    if !upgrade.truthy() || str_value(vm, &upgrade)?.to_lowercase() != "websocket" || !key.truthy() {
        return Ok(Value::Null);
    }
    let key = str_value(vm, &key)?;
    let mut pairs: Vec<(String, String)> = Vec::new();
    let extra = get(vm, &options, "headers")?;
    if extra.truthy() {
        if get(vm, &extra, "_pairs")?.is_callable() {
            pairs = header_pairs_rust(vm, &extra)?;
        } else if crate::builtins::array::is_array(vm, &extra)? {
            for p in vm.iterate_to_vec(&extra)? {
                let n = get(vm, &p, "0")?;
                let v = get(vm, &p, "1")?;
                pairs.push((js_string(vm, &n)?.to_rust_string(), js_string(vm, &v)?.to_rust_string()));
            }
        } else if let Value::Obj(o) = &extra {
            for k in vm.enumerable_own_keys(o)? {
                let v = vm.get(o, &PropKey::Str(k.clone()), &extra)?;
                pairs.push((k.to_rust_string(), js_string(vm, &v)?.to_rust_string()));
            }
        }
    }
    let remote = get(vm, &conn, "remoteAddress")?;
    let handle = Value::Obj(vm.obj_from(vec![("remoteAddress", remote), ("onmessage", Value::Null), ("onclose", Value::Null)]));
    let proto = get(vm, &options, "protocol")?;
    let proto = if proto.truthy() { js_string(vm, &proto)?.to_rust_string() } else { String::new() };
    // take the connection out of the HTTP layer
    let ckey = match &conn {
        Value::Obj(o) => match o.get_own_data(&priv_key()) {
            Some(Value::Num(k)) => k as u64,
            _ => u64::MAX,
        },
        _ => u64::MAX,
    };
    let stream = take_conn(ckey);
    let id = NEXT_WS.with(|n| {
        let v = n.get();
        n.set(v + 1);
        v
    });
    let sw = Rc::new(ServerWs { id, handle: handle.clone(), writer: RefCell::new(None), closed: Cell::new(false), close_sent: Cell::new(false) });
    if let Some(mut s) = stream {
        let accept = super::encoding::base64_encode(&crate::crypto::hash::digest(crate::crypto::hash::HashAlg::Sha1, format!("{}{}", key, WS_GUID).as_bytes()), false);
        let mut resp = format!("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\n", accept);
        if !proto.is_empty() {
            resp.push_str(&format!("Sec-WebSocket-Protocol: {}\r\n", proto));
        }
        for (k, v) in &pairs {
            resp.push_str(&format!("{}: {}\r\n", k, v));
        }
        resp.push_str("\r\n");
        let _ = s.set_read_timeout(None);
        let _ = s.write_all(resp.as_bytes());
        if let Ok(r) = s.try_clone() {
            server_ws_read(vm, sw.clone(), r);
        }
        *sw.writer.borrow_mut() = Some(s);
    }
    WS_UPGRADED.with(|m| m.borrow_mut().insert(id, sw.clone()));
    put(vm, &conn, "upgraded", Value::Bool(true))?;
    let hv = host(sw);
    let send = func(vm, "", 1, server_ws_send, vec![hv.clone()]);
    put(vm, &handle, "send", send)?;
    let close = func(vm, "", 2, server_ws_close, vec![hv]);
    put(vm, &handle, "close", close)?;
    Ok(handle)
}

fn server_ws_fire_close(vm: &mut Vm, sw: &Rc<ServerWs>, code: f64, reason: Value, clean: bool) {
    if sw.closed.get() {
        return;
    }
    sw.closed.set(true);
    WS_UPGRADED.with(|m| m.borrow_mut().remove(&sw.id));
    let f = get(vm, &sw.handle, "onclose").unwrap_or(Value::Undefined);
    if f.is_callable() {
        if let Err(e) = vm.call(&f, sw.handle.clone(), &[Value::Num(code), reason, Value::Bool(clean)]) {
            super::report_uncaught(vm, &e);
        }
    }
}

fn server_ws_read(vm: &mut Vm, sw: Rc<ServerWs>, stream: TcpStream) {
    let data = host(sw);
    super::spawn_op(
        vm,
        move || {
            let mut s = stream;
            let m = read_ws_message(&mut s, false);
            (s, m)
        },
        move |vm, (s, m): (TcpStream, WsMsg)| server_ws_on_message(vm, &data, s, m),
    );
}

fn server_ws_on_message(vm: &mut Vm, data: &Value, s: TcpStream, m: WsMsg) {
    let sw = unhost::<ServerWs>(data);
    match m {
        WsMsg::Text(t) => {
            if sw.closed.get() {
                return;
            }
            let f = get(vm, &sw.handle, "onmessage").unwrap_or(Value::Undefined);
            if f.is_callable() {
                let text = Value::Str(super::streams::decode_text(&t));
                if let Err(e) = vm.call(&f, sw.handle.clone(), &[text, Value::Bool(false)]) {
                    super::report_uncaught(vm, &e);
                }
            }
            server_ws_read(vm, sw.clone(), s);
        }
        WsMsg::Binary(b) => {
            if sw.closed.get() {
                return;
            }
            let f = get(vm, &sw.handle, "onmessage").unwrap_or(Value::Undefined);
            if f.is_callable() {
                if let Ok(u) = new_u8(vm, b) {
                    if let Err(e) = vm.call(&f, sw.handle.clone(), &[u, Value::Bool(true)]) {
                        super::report_uncaught(vm, &e);
                    }
                }
            }
            server_ws_read(vm, sw.clone(), s);
        }
        WsMsg::Close(code, reason) => {
            if !sw.close_sent.get() {
                sw.close_sent.set(true);
                let payload = code.map(|c| c.to_be_bytes().to_vec()).unwrap_or_default();
                if let Some(w) = sw.writer.borrow_mut().as_mut() {
                    let _ = w.write_all(&ws_frame(0x8, &payload, false));
                }
            }
            if let Some(w) = sw.writer.borrow_mut().take() {
                let _ = w.shutdown(Shutdown::Both);
            }
            server_ws_fire_close(vm, &sw, code.unwrap_or(1005) as f64, Value::str(&reason), true);
        }
        WsMsg::Fail(code, reason) => {
            if let Some(w) = sw.writer.borrow_mut().take() {
                let _ = w.shutdown(Shutdown::Both);
            }
            server_ws_fire_close(vm, &sw, code as f64, Value::str(&reason), false);
        }
        WsMsg::Io(msg) => {
            if let Some(w) = sw.writer.borrow_mut().take() {
                let _ = w.shutdown(Shutdown::Both);
            }
            server_ws_fire_close(vm, &sw, 1006.0, Value::str(&msg), false);
        }
    }
}

fn server_ws_send(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let sw = unhost::<ServerWs>(&a.slot(0));
    if sw.closed.get() {
        return Ok(Value::Bool(false));
    }
    let data = a.arg(0);
    let frame = if let Value::Str(s) = &data {
        ws_frame(0x1, &str_to_utf8(s.units()), false)
    } else if is_array_buffer(&data) || is_view(&data) {
        ws_frame(0x2, &bytes_from_u8(&data), false)
    } else {
        let s = js_string(vm, &data)?;
        ws_frame(0x1, &str_to_utf8(s.units()), false)
    };
    let ok = match sw.writer.borrow_mut().as_mut() {
        Some(w) => w.write_all(&frame).is_ok(),
        None => false,
    };
    Ok(Value::Bool(ok))
}

fn server_ws_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let sw = unhost::<ServerWs>(&a.slot(0));
    let code = a.arg(0);
    let code = if code.is_undefined() { 1000 } else { vm.to_number(&code)? as u16 };
    let reason = a.arg(1);
    let reason = if reason.is_undefined() { String::new() } else { js_string(vm, &reason)?.to_rust_string() };
    if !sw.close_sent.get() {
        sw.close_sent.set(true);
        if let Some(w) = sw.writer.borrow_mut().as_mut() {
            let _ = w.write_all(&ws_frame(0x8, &close_payload(code, &reason), false));
        }
    }
    Ok(Value::Undefined)
}

// ---- EventSource ----

const ES_CONNECTING: u8 = 0;
const ES_OPEN: u8 = 1;
const ES_CLOSED: u8 = 2;
const DEFAULT_RETRY: f64 = 3000.0;

pub struct EsState {
    url: String,
    origin: String,
    with_credentials: bool,
    ready_state: Cell<u8>,
    conn_gen: Cell<u64>,
    reconnect_time: Cell<f64>,
    reconnect_timer: RefCell<Value>,
    last_event_id: RefCell<Vec<u16>>,
    buffer: RefCell<Vec<u16>>,
    pending_bytes: RefCell<Vec<u8>>,
    data_lines: RefCell<Vec<Vec<u16>>>,
    event_type: RefCell<Vec<u16>>,
    id_buffer: RefCell<Vec<u16>>,
    abort: RefCell<Option<Arc<AtomicBool>>>,
    this: RefCell<Value>,
}

fn install_event_source(vm: &mut Vm, ctor: &Obj, proto: &Obj) {
    for (n, v) in [("CONNECTING", 0.0), ("OPEN", 1.0), ("CLOSED", 2.0)] {
        let g = vm.native_closure(&format!("get {}", n), 0, |_vm, a| Ok(a.slot(0)), vec![Value::Num(v)]);
        ctor.set_accessor(PropKey::from_str(n), Some(g), None, CONFIGURABLE);
    }
    for (n, v) in [("CONNECTING", 0.0), ("OPEN", 1.0), ("CLOSED", 2.0)] {
        let g = vm.native_closure(&format!("get {}", n), 0, |_vm, a| Ok(a.slot(0)), vec![Value::Num(v)]);
        proto.set_accessor(PropKey::from_str(n), Some(g), None, CONFIGURABLE);
    }
    vm.def_getter(proto, "url", |vm, a| Ok(Value::str(&get_private::<EsState>(vm, &a.this, "#url")?.url)));
    vm.def_getter(proto, "withCredentials", |vm, a| Ok(Value::Bool(get_private::<EsState>(vm, &a.this, "#withCredentials")?.with_credentials)));
    vm.def_getter(proto, "readyState", |vm, a| Ok(Value::Num(get_private::<EsState>(vm, &a.this, "#readyState")?.ready_state.get() as f64)));
    vm.def_method(proto, "close", 0, es_close);
    for n in ["onopen", "onmessage", "onerror"] {
        proto.set_str(n, Value::Null, WEC);
    }
}

fn es_construct(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = fctx();
    let this = construct_event_target(vm, a, &c.es_proto)?;
    if a.args.is_empty() {
        return vm.throw_type("EventSource constructor requires a url");
    }
    let url = a.arg(0);
    let (href, _proto, _hash, origin) = match parse_global_url(vm, &url)? {
        Some(p) => p,
        None => {
            let shown = vm.to_string(&url)?.to_rust_string();
            return Err(dom_exception(vm, &format!("invalid EventSource URL: {}", shown), "SyntaxError"));
        }
    };
    let mut config = a.arg(1);
    if config.is_undefined() {
        config = new_obj(vm);
    }
    let config = if config.truthy() && config.type_of() == "object" { config } else { new_obj(vm) };
    let wc = get(vm, &config, "withCredentials")?.truthy();
    let st = Rc::new(EsState {
        url: href,
        origin,
        with_credentials: wc,
        ready_state: Cell::new(ES_CONNECTING),
        conn_gen: Cell::new(0),
        reconnect_time: Cell::new(DEFAULT_RETRY),
        reconnect_timer: RefCell::new(Value::Undefined),
        last_event_id: RefCell::new(Vec::new()),
        buffer: RefCell::new(Vec::new()),
        pending_bytes: RefCell::new(Vec::new()),
        data_lines: RefCell::new(Vec::new()),
        event_type: RefCell::new(Vec::new()),
        id_buffer: RefCell::new(Vec::new()),
        abort: RefCell::new(None),
        this: RefCell::new(this.clone()),
    });
    set_private(&this, st.clone());
    es_reset_parser(&st);
    es_connect(vm, &st)?;
    Ok(this)
}

fn es_reset_parser(st: &EsState) {
    st.buffer.borrow_mut().clear();
    st.pending_bytes.borrow_mut().clear();
    st.data_lines.borrow_mut().clear();
    st.event_type.borrow_mut().clear();
    *st.id_buffer.borrow_mut() = st.last_event_id.borrow().clone();
}

enum SseEvent {
    Open(TcpStream, Vec<u8>),
    Fatal,
    Drop,
    Chunk(TcpStream, Vec<u8>),
    Eof,
}

fn es_connect(vm: &mut Vm, st: &Rc<EsState>) -> JsResult<()> {
    if st.ready_state.get() == ES_CLOSED {
        return Ok(());
    }
    es_reset_parser(st);
    let u = parse_url(&st.url);
    let scheme = u.as_ref().map(|p| p.scheme.clone()).unwrap_or_default();
    if scheme != "http" && scheme != "https" {
        return vm.throw_syntax(format!("EventSource: unsupported scheme '{}'", scheme));
    }
    let gen = st.conn_gen.get() + 1;
    st.conn_gen.set(gen);
    let abort = Arc::new(AtomicBool::new(false));
    *st.abort.borrow_mut() = Some(abort.clone());
    let url = st.url.clone();
    let last_id = String::from_utf16_lossy(&st.last_event_id.borrow());
    let data = host(st.clone());
    super::spawn_op(vm, move || sse_open(&url, &last_id, &abort), move |vm, ev: SseEvent| es_on_event(vm, &data, gen, ev));
    Ok(())
}

fn sse_open(url: &str, last_id: &str, abort: &AtomicBool) -> SseEvent {
    let u = match parse_url(url) {
        Some(u) => u,
        None => return SseEvent::Drop,
    };
    let mut s = match TcpStream::connect((u.connect_host().as_str(), u.effective_port())) {
        Ok(s) => s,
        Err(_) => return SseEvent::Drop,
    };
    if u.scheme == "https" {
        return SseEvent::Drop;
    }
    let mut req = format!(
        "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nAccept: text/event-stream\r\nCache-Control: no-cache\r\n",
        u.path_and_query(),
        u.host_port()
    );
    if !last_id.is_empty() {
        req.push_str(&format!("Last-Event-ID: {}\r\n", last_id));
    }
    req.push_str(&format!("User-Agent: lumen/{}\r\n\r\n", VERSION));
    if s.write_all(req.as_bytes()).is_err() {
        return SseEvent::Drop;
    }
    // read the response head, polling the abort flag (close() before the server answers)
    let _ = s.set_read_timeout(Some(Duration::from_millis(50)));
    let mut buf = Vec::new();
    let mut tmp = [0u8; 4096];
    loop {
        if abort.load(Ordering::SeqCst) {
            return SseEvent::Drop;
        }
        if buf.windows(4).any(|w| w == b"\r\n\r\n") || buf.windows(2).any(|w| w == b"\n\n") {
            break;
        }
        match s.read(&mut tmp) {
            Ok(0) => break,
            Ok(n) => buf.extend_from_slice(&tmp[..n]),
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => continue,
            Err(_) => return SseEvent::Drop,
        }
    }
    let _ = s.set_read_timeout(None);
    let status = match read_line(&mut s, &mut buf) {
        Ok(Some(l)) => l,
        _ => return SseEvent::Drop,
    };
    let code = match parse_status_line(&status) {
        Some((c, _)) => c,
        None => return SseEvent::Drop,
    };
    let mut ctype = String::new();
    let mut chunked = false;
    loop {
        match read_line(&mut s, &mut buf) {
            Ok(Some(l)) if !l.is_empty() => {
                if let Some(i) = l.find(':') {
                    let k = l[..i].trim().to_ascii_lowercase();
                    let v = l[i + 1..].trim().to_string();
                    if k == "content-type" {
                        ctype = v;
                    } else if k == "transfer-encoding" && v.to_ascii_lowercase().contains("chunked") {
                        chunked = true;
                    }
                }
            }
            Ok(_) => break,
            Err(_) => return SseEvent::Drop,
        }
    }
    if abort.load(Ordering::SeqCst) {
        return SseEvent::Drop;
    }
    if code != 200 || !ctype.to_ascii_lowercase().starts_with("text/event-stream") {
        return SseEvent::Fatal;
    }
    if chunked {
        let body = read_chunked(&mut s, &mut buf).unwrap_or_default();
        return SseEvent::Open(s, body);
    }
    SseEvent::Open(s, buf)
}

fn es_on_event(vm: &mut Vm, data: &Value, gen: u64, ev: SseEvent) {
    let st = unhost::<EsState>(data);
    if st.conn_gen.get() != gen {
        return;
    }
    let this = st.this.borrow().clone();
    match ev {
        SseEvent::Open(s, initial) => {
            if st.ready_state.get() == ES_CLOSED {
                return;
            }
            st.ready_state.set(ES_OPEN);
            if let Ok(e) = make_event(vm, "Event", "open", None) {
                fire_event(vm, &this, "open", e);
            }
            if !initial.is_empty() && st.ready_state.get() == ES_OPEN {
                es_feed(vm, &st, &initial);
            }
            es_read_more(vm, data.clone(), gen, s);
        }
        SseEvent::Chunk(s, bytes) => {
            if st.ready_state.get() == ES_OPEN {
                es_feed(vm, &st, &bytes);
            }
            es_read_more(vm, data.clone(), gen, s);
        }
        SseEvent::Eof | SseEvent::Drop => es_schedule_reconnect(vm, &st),
        SseEvent::Fatal => {
            st.ready_state.set(ES_CLOSED);
            if let Ok(e) = make_event(vm, "Event", "error", None) {
                fire_event(vm, &this, "error", e);
            }
        }
    }
}

fn es_read_more(vm: &mut Vm, data: Value, gen: u64, stream: TcpStream) {
    let st = unhost::<EsState>(&data);
    if st.ready_state.get() == ES_CLOSED || st.conn_gen.get() != gen {
        return;
    }
    let abort = st.abort.borrow().clone().unwrap_or_else(|| Arc::new(AtomicBool::new(false)));
    super::spawn_op(
        vm,
        move || {
            let mut s = stream;
            let _ = s.set_read_timeout(Some(Duration::from_millis(50)));
            let mut tmp = vec![0u8; 16384];
            loop {
                if abort.load(Ordering::SeqCst) {
                    return SseEvent::Eof;
                }
                match s.read(&mut tmp) {
                    Ok(0) => return SseEvent::Eof,
                    Ok(n) => return SseEvent::Chunk(s, tmp[..n].to_vec()),
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => continue,
                    Err(_) => return SseEvent::Eof,
                }
            }
        },
        move |vm, ev: SseEvent| es_on_event(vm, &data, gen, ev),
    );
}

fn es_schedule_reconnect(vm: &mut Vm, st: &Rc<EsState>) {
    if st.ready_state.get() == ES_CLOSED {
        return;
    }
    st.ready_state.set(ES_CONNECTING);
    let this = st.this.borrow().clone();
    if let Ok(e) = make_event(vm, "Event", "error", None) {
        fire_event(vm, &this, "error", e);
    }
    if st.ready_state.get() == ES_CLOSED {
        return;
    }
    let cb = func(vm, "", 0, es_reconnect_cb, vec![host(st.clone())]);
    let id = super::timers::add_timer(vm, cb, st.reconnect_time.get(), vec![], false);
    *st.reconnect_timer.borrow_mut() = Value::Num(id as f64);
}

fn es_reconnect_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = unhost::<EsState>(&a.slot(0));
    *st.reconnect_timer.borrow_mut() = Value::Undefined;
    es_connect(vm, &st)?;
    Ok(Value::Undefined)
}

fn es_feed(vm: &mut Vm, st: &Rc<EsState>, bytes: &[u8]) {
    // streaming UTF-8 decode (keeps an incomplete trailing sequence for the next chunk)
    let mut all = std::mem::take(&mut *st.pending_bytes.borrow_mut());
    all.extend_from_slice(bytes);
    let keep = incomplete_utf8_tail(&all);
    let (head, tail) = all.split_at(all.len() - keep);
    let text = super::streams::utf8_to_str(head, false).unwrap_or_default();
    *st.pending_bytes.borrow_mut() = tail.to_vec();
    st.buffer.borrow_mut().extend_from_slice(&text);
    loop {
        if st.ready_state.get() == ES_CLOSED {
            return;
        }
        let line = {
            let buf = st.buffer.borrow();
            let mut found = None;
            for (i, &c) in buf.iter().enumerate() {
                if c == b'\n' as u16 {
                    found = Some((i, i + 1));
                    break;
                }
                if c == b'\r' as u16 {
                    found = Some(if i + 1 < buf.len() && buf[i + 1] == b'\n' as u16 { (i, i + 2) } else { (i, i + 1) });
                    break;
                }
            }
            found.map(|(end, next)| (buf[..end].to_vec(), next))
        };
        match line {
            Some((l, next)) => {
                st.buffer.borrow_mut().drain(..next);
                es_process_line(vm, st, &l);
            }
            None => break,
        }
    }
}

fn incomplete_utf8_tail(b: &[u8]) -> usize {
    let n = b.len();
    for back in 1..=3.min(n) {
        let c = b[n - back];
        if c & 0xC0 == 0x80 {
            continue;
        }
        let need = if c >= 0xF0 {
            4
        } else if c >= 0xE0 {
            3
        } else if c >= 0xC0 {
            2
        } else {
            1
        };
        return if need > back { back } else { 0 };
    }
    0
}

fn es_process_line(vm: &mut Vm, st: &Rc<EsState>, line: &[u16]) {
    if line.is_empty() {
        es_dispatch(vm, st);
        return;
    }
    if line[0] == b':' as u16 {
        return;
    }
    let (field, value): (Vec<u16>, Vec<u16>) = match line.iter().position(|&c| c == b':' as u16) {
        None => (line.to_vec(), Vec::new()),
        Some(i) => {
            let mut v = line[i + 1..].to_vec();
            if v.first() == Some(&(b' ' as u16)) {
                v.remove(0);
            }
            (line[..i].to_vec(), v)
        }
    };
    let f = String::from_utf16_lossy(&field);
    match f.as_str() {
        "event" => *st.event_type.borrow_mut() = value,
        "data" => st.data_lines.borrow_mut().push(value),
        "id" => {
            if !value.contains(&0) {
                *st.id_buffer.borrow_mut() = value;
            }
        }
        "retry" => {
            if !value.is_empty() && value.iter().all(|&c| (b'0' as u16..=b'9' as u16).contains(&c)) {
                let s = String::from_utf16_lossy(&value);
                if let Ok(n) = s.parse::<f64>() {
                    st.reconnect_time.set(n);
                }
            }
        }
        _ => {}
    }
}

fn es_dispatch(vm: &mut Vm, st: &Rc<EsState>) {
    let id = st.id_buffer.borrow().clone();
    *st.last_event_id.borrow_mut() = id;
    if st.data_lines.borrow().is_empty() {
        st.event_type.borrow_mut().clear();
        return;
    }
    let mut data: Vec<u16> = Vec::new();
    for (i, l) in st.data_lines.borrow().iter().enumerate() {
        if i > 0 {
            data.push(b'\n' as u16);
        }
        data.extend_from_slice(l);
    }
    let ty = {
        let t = st.event_type.borrow();
        if t.is_empty() {
            "message".encode_utf16().collect::<Vec<u16>>()
        } else {
            t.clone()
        }
    };
    st.data_lines.borrow_mut().clear();
    st.event_type.borrow_mut().clear();
    if st.ready_state.get() != ES_OPEN {
        return;
    }
    let this = st.this.borrow().clone();
    let ty_s = String::from_utf16_lossy(&ty);
    let lid = Value::Str(JsStr::from_units(st.last_event_id.borrow().clone()));
    let init = Value::Obj(vm.obj_from(vec![("data", Value::Str(JsStr::from_units(data))), ("origin", Value::str(&st.origin)), ("lastEventId", lid)]));
    if let Ok(e) = make_event(vm, "MessageEvent", &ty_s, Some(init)) {
        fire_event(vm, &this, &ty_s, e);
    }
}

fn es_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let st = get_private::<EsState>(vm, &a.this, "#readyState")?;
    st.ready_state.set(ES_CLOSED);
    let t = std::mem::replace(&mut *st.reconnect_timer.borrow_mut(), Value::Undefined);
    if !t.is_undefined() {
        super::timers::clear_timer_id(vm, &t);
    }
    if let Some(ab) = st.abort.borrow_mut().take() {
        ab.store(true, Ordering::SeqCst);
    }
    st.conn_gen.set(st.conn_gen.get() + 1);
    Ok(Value::Undefined)
}
