// node:http / node:https / node:http2, modelled on the reference runtime:
//
// * http.Server sits on a native HTTP/1.1 server equivalent to the reference's `Lumen.serve`:
//   one request per connection (`Connection: close`), bodies buffered both ways. Requests are
//   delivered as IncomingMessage (a Readable fed with the whole body after the 'request' event)
//   and ServerResponse (a Writable collecting the body; `_final` hands the response over).
//   Request headers are lower-cased, combined (", ") and sorted (WHATWG Headers order); the
//   response carries the user's headers in the same normal form plus Content-Length / Server /
//   Connection unless given. A handler exception is logged and answered with a 500.
// * the client (http.request / http.get) behaves like the reference's fetch()-based one: the
//   whole response is read before 'response', redirects are followed, errors are TypeErrors
//   "fetch '<url>': connect: ...".
// * https shares both (no TLS here); http2 exposes settings helpers and constants.

use crate::object::*;
use crate::runtime::nodestream::{buffer_call, call_method, closure, emit, error_with_code, getp, key, make_class, new_buffer, new_instance, plain_fn, queue_microtask, resolved, setp, string_of};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream, ToSocketAddrs};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};

const SERVER_NAME: &str = "lumen/0.1.3";

pub const STATUS_CODES: &[(u16, &str)] = &[
    (100, "Continue"),
    (101, "Switching Protocols"),
    (102, "Processing"),
    (103, "Early Hints"),
    (200, "OK"),
    (201, "Created"),
    (202, "Accepted"),
    (203, "Non-Authoritative Information"),
    (204, "No Content"),
    (205, "Reset Content"),
    (206, "Partial Content"),
    (300, "Multiple Choices"),
    (301, "Moved Permanently"),
    (302, "Found"),
    (303, "See Other"),
    (304, "Not Modified"),
    (307, "Temporary Redirect"),
    (308, "Permanent Redirect"),
    (400, "Bad Request"),
    (401, "Unauthorized"),
    (402, "Payment Required"),
    (403, "Forbidden"),
    (404, "Not Found"),
    (405, "Method Not Allowed"),
    (406, "Not Acceptable"),
    (408, "Request Timeout"),
    (409, "Conflict"),
    (410, "Gone"),
    (411, "Length Required"),
    (412, "Precondition Failed"),
    (413, "Payload Too Large"),
    (414, "URI Too Long"),
    (415, "Unsupported Media Type"),
    (416, "Range Not Satisfiable"),
    (417, "Expectation Failed"),
    (418, "I'm a Teapot"),
    (422, "Unprocessable Entity"),
    (429, "Too Many Requests"),
    (500, "Internal Server Error"),
    (501, "Not Implemented"),
    (502, "Bad Gateway"),
    (503, "Service Unavailable"),
    (504, "Gateway Timeout"),
    (505, "HTTP Version Not Supported"),
];

const METHODS: &[&str] = &[
    "ACL", "BIND", "CHECKOUT", "CONNECT", "COPY", "DELETE", "GET", "HEAD", "LINK", "LOCK", "MERGE", "MKACTIVITY", "MKCALENDAR", "MKCOL", "MOVE", "NOTIFY", "OPTIONS", "PATCH",
    "POST", "PROPFIND", "PROPPATCH", "PURGE", "PUT", "REBIND", "REPORT", "SEARCH", "SOURCE", "SUBSCRIBE", "TRACE", "UNBIND", "UNLINK", "UNLOCK", "UNSUBSCRIBE",
];

fn status_text(code: f64) -> &'static str {
    STATUS_CODES.iter().find(|(c, _)| *c as f64 == code).map(|(_, t)| *t).unwrap_or("")
}

// ============================================================================================
// classes
// ============================================================================================

#[derive(Clone)]
struct HttpClasses {
    server: Obj,
    server_proto: Obj,
    https_server: Obj,
    incoming: Obj,
    incoming_proto: Obj,
    response: Obj,
    response_proto: Obj,
    outgoing: Obj,
    outgoing_proto: Obj,
    client_request: Obj,
    client_request_proto: Obj,
    https_client_request: Obj,
    agent: Obj,
    https_agent: Obj,
}

thread_local! {
    static CLASSES: RefCell<Option<HttpClasses>> = RefCell::new(None);
    static SERVERS: RefCell<HashMap<u64, ServerCore>> = RefCell::new(HashMap::new());
    static CONNS: RefCell<HashMap<u64, TcpStream>> = RefCell::new(HashMap::new());
    static HEAD_REQS: RefCell<std::collections::HashSet<u64>> = RefCell::new(std::collections::HashSet::new());
    static NEXT_ID: Cell<u64> = Cell::new(1);
}

fn next_id() -> u64 {
    NEXT_ID.with(|n| {
        let v = n.get();
        n.set(v + 1);
        v
    })
}

fn classes(vm: &mut Vm) -> HttpClasses {
    if let Some(c) = CLASSES.with(|c| c.borrow().clone()) {
        return c;
    }
    let sc = crate::runtime::nodestream::classes(vm);
    let mk_server = |vm: &mut Vm| {
        let (s, sp) = make_class(vm, "Server", 2, server_ctor, Some((&sc.ee, &sc.ee_proto)));
        let m: &[(&str, u32, NativeFn)] = &[("listen", 0, server_listen), ("address", 0, server_address), ("_dispatch", 2, server_dispatch_method), ("close", 1, server_close), ("setTimeout", 2, set_timeout_once)];
        for (n, l, f) in m {
            vm.def_method(&sp, n, *l, *f);
        }
        (s, sp)
    };
    let (server, server_proto) = mk_server(vm);
    let (https_server, _) = mk_server(vm);

    let (incoming, ip) = make_class(vm, "IncomingMessage", 1, incoming_ctor, Some((&sc.readable, &sc.readable_proto)));
    vm.def_method(&ip, "setTimeout", 2, set_timeout_once);
    vm.def_method(&ip, "destroy", 1, incoming_destroy);

    let (response, rp) = make_class(vm, "ServerResponse", 1, response_ctor, Some((&sc.writable, &sc.writable_proto)));
    let rm: &[(&str, u32, NativeFn)] = &[
        ("setHeader", 2, res_set_header_f),
        ("getHeader", 1, hdr_get),
        ("getHeaderNames", 0, hdr_names),
        ("getHeaders", 0, hdr_all),
        ("hasHeader", 1, hdr_has),
        ("removeHeader", 1, hdr_remove),
        ("appendHeader", 2, res_append_header),
        ("_implicitHeader", 0, res_implicit_header),
        ("writeHead", 3, res_write_head),
        ("flushHeaders", 0, flush_headers),
        ("writeContinue", 0, noop),
        ("setTimeout", 2, set_timeout_once),
        ("_write", 3, res_write),
        ("_final", 1, res_final),
    ];
    for (n, l, f) in rm {
        vm.def_method(&rp, n, *l, *f);
    }

    let (outgoing, op) = make_class(vm, "OutgoingMessage", 0, outgoing_ctor, Some((&sc.writable, &sc.writable_proto)));
    let om: &[(&str, u32, NativeFn)] = &[
        ("setHeader", 2, out_set_header_f),
        ("getHeader", 1, hdr_get),
        ("getHeaderNames", 0, hdr_names),
        ("getHeaders", 0, hdr_all),
        ("hasHeader", 1, hdr_has),
        ("removeHeader", 1, hdr_remove),
        ("setTimeout", 2, set_timeout_once),
    ];
    for (n, l, f) in om {
        vm.def_method(&op, n, *l, *f);
    }

    let (client_request, cp) = make_class(vm, "ClientRequest", 3, client_request_ctor, Some((&outgoing, &op)));
    let cm: &[(&str, u32, NativeFn)] = &[
        ("setTimeout", 2, cr_set_timeout),
        ("_clearTimer", 0, cr_clear_timer),
        ("_write", 3, cr_write),
        ("_final", 1, cr_final),
        ("_send", 0, cr_send),
        ("abort", 0, cr_abort),
        ("destroy", 1, cr_destroy),
        ("flushHeaders", 0, flush_headers),
    ];
    for (n, l, f) in cm {
        vm.def_method(&cp, n, *l, *f);
    }
    vm.def_getter(&cp, "writableEnded", cr_writable_ended);
    client_request.set_prop(key("_defaultProtocol"), Value::str("http:"), WEC);
    let (https_client_request, _) = make_class(vm, "HttpsClientRequest", 0, client_request_ctor, Some((&client_request, &cp)));
    https_client_request.set_prop(key("_defaultProtocol"), Value::str("https:"), WEC);

    let mk_agent = |vm: &mut Vm| {
        let (a, ap) = make_class(vm, "Agent", 0, agent_ctor, Some((&sc.ee, &sc.ee_proto)));
        vm.def_method(&ap, "createConnection", 0, agent_create_connection);
        vm.def_method(&ap, "getName", 0, |_vm, _a| Ok(Value::str("localhost:")));
        vm.def_method(&ap, "destroy", 0, noop);
        a
    };
    let agent = mk_agent(vm);
    let https_agent = mk_agent(vm);
    let c = HttpClasses {
        server,
        server_proto,
        https_server,
        incoming,
        incoming_proto: ip,
        response,
        response_proto: rp,
        outgoing,
        outgoing_proto: op,
        client_request,
        client_request_proto: cp,
        https_client_request,
        agent,
        https_agent,
    };
    CLASSES.with(|s| *s.borrow_mut() = Some(c.clone()));
    c
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

fn proto_of_ctor(vm: &mut Vm, c: &Obj) -> Obj {
    match c.get_own_str("prototype") {
        Some(Value::Obj(p)) => p,
        _ => vm.intr.object_proto.clone(),
    }
}

/// setTimeout(_ms, cb) { if (cb) this.once("timeout", cb); return this; }
fn set_timeout_once(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.arg(1).truthy() {
        call_method(vm, &a.this, "once", &[Value::str("timeout"), a.arg(1)])?;
    }
    Ok(a.this.clone())
}

fn flush_headers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    setp(vm, &a.this, "headersSent", Value::Bool(true))?;
    Ok(Value::Undefined)
}

fn new_map(vm: &mut Vm) -> JsResult<Value> {
    let mc = vm.global.get_own_str("Map").unwrap_or(Value::Undefined);
    vm.construct(&mc, &[], None)
}

fn lower(vm: &mut Vm, v: &Value) -> JsResult<String> {
    Ok(string_of(vm, v)?.to_lowercase())
}

// ============================================================================================
// header helpers (the `_headers` Map: lower-name -> { name, value })
// ============================================================================================

fn hdr_map(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    getp(vm, this, "_headers")
}

fn hdr_set_raw(vm: &mut Vm, this: &Value, name: &Value, value: Value) -> JsResult<()> {
    let m = hdr_map(vm, this)?;
    let l = lower(vm, name)?;
    let n = string_of(vm, name)?;
    let entry = Value::Obj(vm.obj_from(vec![("name", Value::str(&n)), ("value", value)]));
    call_method(vm, &m, "set", &[Value::str(&l), entry])?;
    Ok(())
}

fn hdr_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = hdr_map(vm, &a.this)?;
    let l = lower(vm, &a.arg(0))?;
    let h = call_method(vm, &m, "get", &[Value::str(&l)])?;
    if h.truthy() {
        getp(vm, &h, "value")
    } else {
        Ok(Value::Undefined)
    }
}

fn hdr_entries(vm: &mut Vm, this: &Value) -> JsResult<Vec<(String, Value)>> {
    let m = hdr_map(vm, this)?;
    let vals = call_method(vm, &m, "values", &[])?;
    let list = vm.iterate_to_vec(&vals)?;
    let mut out = Vec::new();
    for h in list {
        let n = getp(vm, &h, "name")?;
        let ns = string_of(vm, &n)?;
        let v = getp(vm, &h, "value")?;
        out.push((ns, v));
    }
    Ok(out)
}

fn hdr_names(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let e = hdr_entries(vm, &a.this)?;
    let v: Vec<Value> = e.into_iter().map(|(n, _)| Value::str(&n.to_lowercase())).collect();
    Ok(Value::Obj(vm.new_array(v)))
}

fn hdr_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let e = hdr_entries(vm, &a.this)?;
    let o = Obj::new(None, ObjKind::Ordinary);
    for (n, v) in e {
        o.set_prop(key(&n.to_lowercase()), v, WEC);
    }
    Ok(Value::Obj(o))
}

fn hdr_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = hdr_map(vm, &a.this)?;
    let l = lower(vm, &a.arg(0))?;
    call_method(vm, &m, "has", &[Value::str(&l)])
}

fn hdr_remove(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = hdr_map(vm, &a.this)?;
    let l = lower(vm, &a.arg(0))?;
    call_method(vm, &m, "delete", &[Value::str(&l)])?;
    Ok(Value::Undefined)
}

/// headerPairs(map): [[name, String(value)], ...] with array values expanded.
fn header_pairs(vm: &mut Vm, this: &Value) -> JsResult<Vec<(String, String)>> {
    let e = hdr_entries(vm, this)?;
    let mut out = Vec::new();
    for (n, v) in e {
        if matches!(&v, Value::Obj(o) if o.is_array()) {
            for x in crate::builtins::array::array_like_to_vec(vm, &v)? {
                out.push((n.clone(), string_of(vm, &x)?));
            }
        } else {
            out.push((n, string_of(vm, &v)?));
        }
    }
    Ok(out)
}

/// The WHATWG Headers normal form: lower-cased names, duplicates joined with ", ", sorted.
fn normalize_headers(pairs: &[(String, String)]) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    for (n, v) in pairs {
        let l = n.to_lowercase();
        let v = v.trim_matches(|c| c == ' ' || c == '\t').to_string();
        match out.iter_mut().find(|(k, _)| *k == l) {
            Some(e) => {
                e.1.push_str(", ");
                e.1.push_str(&v);
            }
            None => out.push((l, v)),
        }
    }
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

fn is_token_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || "!#$%&'*+-.^_`|~".contains(c)
}

/// validateHeaderName(name, label)
fn validate_header_name_impl(vm: &mut Vm, name: &Value, label: &Value) -> JsResult<()> {
    crate::runtime::nodestream::with_frames(vm, &["validateHeaderName"], |vm| validate_header_name_inner(vm, name, label))
}

fn validate_header_name_inner(vm: &mut Vm, name: &Value, label: &Value) -> JsResult<()> {
    let ok = match name {
        Value::Str(s) => {
            let r = s.to_rust_string();
            !r.is_empty() && r.chars().all(is_token_char)
        }
        _ => false,
    };
    if !ok {
        let l = if label.truthy() { string_of(vm, label)? } else { "Header name".to_string() };
        let n = string_of(vm, name)?;
        return Err(error_with_code(vm, "TypeError", &format!("{} must be a valid HTTP token [\"{}\"]", l, n), "ERR_INVALID_HTTP_TOKEN"));
    }
    Ok(())
}

fn validate_header_name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    validate_header_name_impl(vm, &a.arg(0), &a.arg(1))?;
    Ok(Value::Undefined)
}

fn validate_header_value(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (name, value) = (a.arg(0), a.arg(1));
    if value.is_undefined() {
        let n = string_of(vm, &name)?;
        return Err(error_with_code(vm, "TypeError", &format!("Invalid value \"undefined\" for header \"{}\"", n), "ERR_HTTP_INVALID_HEADER_VALUE"));
    }
    let s = string_of(vm, &value)?;
    if s.chars().any(|c| (c < ' ' && c != '\t') || c == '\u{7f}') {
        let n = string_of(vm, &name)?;
        return Err(error_with_code(vm, "TypeError", &format!("Invalid character in header content [\"{}\"]", n), "ERR_INVALID_CHAR"));
    }
    Ok(Value::Undefined)
}

// ============================================================================================
// IncomingMessage / ServerResponse / OutgoingMessage
// ============================================================================================

fn incoming_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.incoming_proto)?;
    incoming_init(vm, &o, &a.arg(0))?;
    Ok(Value::Obj(o))
}

fn incoming_init(vm: &mut Vm, o: &Obj, socket: &Value) -> JsResult<()> {
    let empty = Value::Obj(vm.new_object());
    crate::runtime::nodestream::readable_init(vm, o, &empty)?;
    let this = Value::Obj(o.clone());
    setp(vm, &this, "httpVersion", Value::str("1.1"))?;
    setp(vm, &this, "httpVersionMajor", Value::Num(1.0))?;
    setp(vm, &this, "httpVersionMinor", Value::Num(1.0))?;
    setp(vm, &this, "method", Value::Null)?;
    setp(vm, &this, "url", Value::str(""))?;
    let h = Value::Obj(vm.new_object());
    setp(vm, &this, "headers", h)?;
    let rh = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "rawHeaders", rh)?;
    let t = Value::Obj(vm.new_object());
    setp(vm, &this, "trailers", t)?;
    let rt = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "rawTrailers", rt)?;
    setp(vm, &this, "aborted", Value::Bool(false))?;
    setp(vm, &this, "complete", Value::Bool(false))?;
    let sock = if socket.truthy() {
        socket.clone()
    } else {
        Value::Obj(vm.obj_from(vec![("remoteAddress", Value::Undefined), ("remotePort", Value::Undefined), ("encrypted", Value::Bool(false))]))
    };
    setp(vm, &this, "socket", sock.clone())?;
    setp(vm, &this, "connection", sock)?;
    Ok(())
}

fn incoming_destroy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    setp(vm, &a.this, "aborted", Value::Bool(true))?;
    let sc = crate::runtime::nodestream::classes(vm);
    let d = vm.get_str(&sc.readable_proto, "destroy")?;
    vm.call(&d, a.this.clone(), &[a.arg(0)])
}

fn response_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.response_proto)?;
    response_init(vm, &o, &a.arg(0))?;
    Ok(Value::Obj(o))
}

fn done_executor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    setp(vm, &a.slot(0), "_resolveDone", a.arg(0))?;
    Ok(Value::Undefined)
}

fn response_init(vm: &mut Vm, o: &Obj, req: &Value) -> JsResult<()> {
    let empty = Value::Obj(vm.new_object());
    crate::runtime::nodestream::writable_init(vm, o, &empty)?;
    let this = Value::Obj(o.clone());
    setp(vm, &this, "req", req.clone())?;
    setp(vm, &this, "statusCode", Value::Num(200.0))?;
    setp(vm, &this, "statusMessage", Value::Undefined)?;
    setp(vm, &this, "headersSent", Value::Bool(false))?;
    setp(vm, &this, "finished", Value::Bool(false))?;
    setp(vm, &this, "sendDate", Value::Bool(true))?;
    let m = new_map(vm)?;
    setp(vm, &this, "_headers", m)?;
    let ch = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_chunks", ch)?;
    let sock = if req.truthy() { getp(vm, req, "socket")? } else { Value::Obj(vm.new_object()) };
    setp(vm, &this, "socket", sock.clone())?;
    setp(vm, &this, "connection", sock)?;
    // this._done = new Promise((resolve) => { this._resolveDone = resolve; })
    let pc = Value::Obj(vm.intr.promise_ctor.clone());
    let exec = closure(vm, "", 1, done_executor, vec![this.clone()]);
    let p = vm.construct(&pc, &[exec], None)?;
    setp(vm, &this, "_done", p)?;
    Ok(())
}

fn res_set_header(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if getp(vm, &a.this, "headersSent")?.truthy() {
        return vm.throw_error("Error", "Cannot set headers after they are sent to the client");
    }
    hdr_set_raw(vm, &a.this, &a.arg(0), a.arg(1))?;
    Ok(a.this.clone())
}

fn res_append_header(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let m = hdr_map(vm, &this)?;
    let l = lower(vm, &a.arg(0))?;
    let existing = call_method(vm, &m, "get", &[Value::str(&l)])?;
    if !existing.truthy() {
        return call_method(vm, &this, "setHeader", &[a.arg(0), a.arg(1)]);
    }
    let ev = getp(vm, &existing, "value")?;
    let arr = if matches!(&ev, Value::Obj(o) if o.is_array()) { ev } else { Value::Obj(vm.new_array(vec![ev])) };
    let joined = call_method(vm, &arr, "concat", &[a.arg(1)])?;
    setp(vm, &existing, "value", joined)?;
    Ok(this)
}

fn res_implicit_header(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !getp(vm, &a.this, "headersSent")?.truthy() {
        let sc = getp(vm, &a.this, "statusCode")?;
        call_method(vm, &a.this, "writeHead", &[sc])?;
    }
    Ok(Value::Undefined)
}

fn res_write_head(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    setp(vm, &this, "statusCode", a.arg(0))?;
    let mut headers = a.arg(2);
    if matches!(a.arg(1), Value::Str(_)) {
        setp(vm, &this, "statusMessage", a.arg(1))?;
    } else {
        headers = a.arg(1);
    }
    if headers.truthy() {
        if matches!(&headers, Value::Obj(o) if o.is_array()) {
            let list = crate::builtins::array::array_like_to_vec(vm, &headers)?;
            let mut i = 0;
            while i < list.len() {
                let v = list.get(i + 1).cloned().unwrap_or(Value::Undefined);
                call_method(vm, &this, "setHeader", &[list[i].clone(), v])?;
                i += 2;
            }
        } else if let Value::Obj(ho) = &headers {
            let keys = vm.enumerable_own_keys(ho)?;
            for k in keys {
                let v = vm.get(ho, &PropKey::Str(k.clone()), &headers)?;
                call_method(vm, &this, "setHeader", &[Value::Str(k), v])?;
            }
        }
    }
    emit(vm, &this, "__writeHead", &[])?;
    setp(vm, &this, "headersSent", Value::Bool(true))?;
    Ok(this)
}

fn chunk_to_buffer(vm: &mut Vm, chunk: &Value, encoding: &Value) -> JsResult<Value> {
    let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
    if vm.instance_of(chunk, &u8c)? {
        return Ok(chunk.clone());
    }
    let s = string_of(vm, chunk)?;
    let enc = if encoding.truthy() { encoding.clone() } else { Value::str("utf8") };
    buffer_call(vm, "from", &[Value::str(&s), enc])
}

fn res_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    call_method(vm, &this, "_implicitHeader", &[])?;
    let chunk = a.arg(0);
    if !chunk.is_nullish() {
        let l = getp(vm, &chunk, "length")?;
        if !matches!(l, Value::Num(n) if n == 0.0) {
            let b = chunk_to_buffer(vm, &chunk, &a.arg(1))?;
            let chunks = getp(vm, &this, "_chunks")?;
            call_method(vm, &chunks, "push", &[b])?;
        }
    }
    vm.call(&a.arg(2), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn concat_chunks(vm: &mut Vm, chunks: &Value) -> JsResult<Value> {
    let list = crate::builtins::array::array_like_to_vec(vm, chunks)?;
    let mut total = 0.0;
    for c in &list {
        let l = getp(vm, c, "length")?;
        total += vm.to_number(&l)?;
    }
    buffer_call(vm, "concat", &[chunks.clone(), Value::Num(total)])
}

fn res_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    call_method(vm, &this, "_implicitHeader", &[])?;
    setp(vm, &this, "finished", Value::Bool(true))?;
    let chunks = getp(vm, &this, "_chunks")?;
    let body = concat_chunks(vm, &chunks)?;
    let status = getp(vm, &this, "statusCode")?;
    let sm = getp(vm, &this, "statusMessage")?;
    let st = if sm.truthy() {
        sm
    } else {
        let n = vm.to_number(&status).unwrap_or(f64::NAN);
        Value::str(status_text(n))
    };
    let pairs = header_pairs(vm, &this)?;
    let pv: Vec<Value> = pairs.into_iter().map(|(n, v)| Value::Obj(vm.new_array(vec![Value::str(&n), Value::str(&v)]))).collect();
    let headers = Value::Obj(vm.new_array(pv));
    let out = Value::Obj(vm.obj_from(vec![("status", status), ("statusText", st), ("headers", headers), ("body", body)]));
    let rd = getp(vm, &this, "_resolveDone")?;
    vm.call(&rd, Value::Undefined, &[out])?;
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn outgoing_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.outgoing_proto)?;
    outgoing_init(vm, &o)?;
    Ok(Value::Obj(o))
}

fn outgoing_init(vm: &mut Vm, o: &Obj) -> JsResult<()> {
    let empty = Value::Obj(vm.new_object());
    crate::runtime::nodestream::writable_init(vm, o, &empty)?;
    let this = Value::Obj(o.clone());
    setp(vm, &this, "headersSent", Value::Bool(false))?;
    setp(vm, &this, "finished", Value::Bool(false))?;
    setp(vm, &this, "sendDate", Value::Bool(true))?;
    let m = new_map(vm)?;
    setp(vm, &this, "_headers", m)?;
    Ok(())
}

fn out_set_header(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    validate_header_name_impl(vm, &a.arg(0), &Value::Undefined)?;
    hdr_set_raw(vm, &a.this, &a.arg(0), a.arg(1))?;
    Ok(a.this.clone())
}

// ============================================================================================
// the native server (the reference's Lumen.serve)
// ============================================================================================

struct ParsedReq {
    method: String,
    target: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
}

struct Conn {
    stream: TcpStream,
    req: Option<ParsedReq>,
    peer: Option<SocketAddr>,
}

struct ServerCore {
    shutdown: Arc<AtomicBool>,
    addr: SocketAddr,
    rx: Option<mpsc::Receiver<Conn>>,
    server: Value,
    closed: bool,
}

fn find_crlf2(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

fn read_head(stream: &mut TcpStream, buf: &mut Vec<u8>) -> Option<usize> {
    let mut tmp = [0u8; 8192];
    loop {
        if let Some(p) = find_crlf2(buf) {
            return Some(p);
        }
        match stream.read(&mut tmp) {
            Ok(0) => return None,
            Ok(n) => buf.extend_from_slice(&tmp[..n]),
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return None,
        }
        if buf.len() > 1 << 20 {
            return None;
        }
    }
}

fn parse_headers(lines: &[&str]) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for l in lines {
        if let Some(p) = l.find(':') {
            out.push((l[..p].trim().to_string(), l[p + 1..].trim().to_string()));
        }
    }
    out
}

fn header_val<'a>(h: &'a [(String, String)], name: &str) -> Option<&'a str> {
    h.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.as_str())
}

/// Read a message body following `rest` (bytes already read past the head).
fn read_body(stream: &mut TcpStream, rest: Vec<u8>, headers: &[(String, String)], until_close: bool) -> Option<Vec<u8>> {
    let chunked = header_val(headers, "transfer-encoding").map_or(false, |v| v.to_ascii_lowercase().contains("chunked"));
    let mut data = rest;
    let mut tmp = [0u8; 65536];
    let mut fill = |data: &mut Vec<u8>| -> bool {
        loop {
            match stream.read(&mut tmp) {
                Ok(0) => return false,
                Ok(n) => {
                    data.extend_from_slice(&tmp[..n]);
                    return true;
                }
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => return false,
            }
        }
    };
    if chunked {
        let mut out = Vec::new();
        let mut pos = 0usize;
        loop {
            // chunk size line
            let line_end = loop {
                if let Some(p) = data[pos..].windows(2).position(|w| w == b"\r\n") {
                    break pos + p;
                }
                if !fill(&mut data) {
                    return Some(out);
                }
            };
            let line = String::from_utf8_lossy(&data[pos..line_end]).to_string();
            let size = usize::from_str_radix(line.split(';').next().unwrap_or("").trim(), 16).unwrap_or(0);
            pos = line_end + 2;
            if size == 0 {
                return Some(out);
            }
            while data.len() < pos + size + 2 {
                if !fill(&mut data) {
                    let end = data.len().min(pos + size);
                    out.extend_from_slice(&data[pos..end]);
                    return Some(out);
                }
            }
            out.extend_from_slice(&data[pos..pos + size]);
            pos += size + 2;
        }
    }
    if let Some(cl) = header_val(headers, "content-length").and_then(|v| v.trim().parse::<usize>().ok()) {
        while data.len() < cl {
            if !fill(&mut data) {
                break;
            }
        }
        data.truncate(cl);
        return Some(data);
    }
    if until_close {
        while fill(&mut data) {}
        return Some(data);
    }
    Some(data)
}

fn read_request(stream: &mut TcpStream) -> Option<ParsedReq> {
    let mut buf = Vec::new();
    let p = read_head(stream, &mut buf)?;
    let head = String::from_utf8_lossy(&buf[..p]).to_string();
    let rest = buf[p + 4..].to_vec();
    let lines: Vec<&str> = head.split("\r\n").collect();
    let mut first = lines.first()?.split_whitespace();
    let method = first.next()?.to_string();
    let target = first.next().unwrap_or("/").to_string();
    let headers = parse_headers(&lines[1..]);
    let body = read_body(stream, rest, &headers, false)?;
    Some(ParsedReq { method, target, headers, body })
}

fn listen_error(vm: &mut Vm, host: &str, port: &str, e: &std::io::Error) -> Value {
    vm.make_error("Error", &format!("listen {}:{}: {}", host, port, e))
}

/// Lumen.serve: bind and start accepting; returns (serverId, boundPort).
fn serve_listen(vm: &mut Vm, hostname: &str, port_str: &str, port: u16, server: Value) -> JsResult<(u64, u16)> {
    let addrs: Vec<SocketAddr> = match (hostname, port).to_socket_addrs() {
        Ok(a) => a.collect(),
        Err(e) => return Err(listen_error(vm, hostname, port_str, &e)),
    };
    let mut last_err = None;
    let mut listener = None;
    for a in &addrs {
        match TcpListener::bind(a) {
            Ok(l) => {
                listener = Some(l);
                break;
            }
            Err(e) => last_err = Some(e),
        }
    }
    let listener = match listener {
        Some(l) => l,
        None => {
            let e = last_err.unwrap_or_else(|| std::io::Error::new(std::io::ErrorKind::Other, "no address"));
            return Err(listen_error(vm, hostname, port_str, &e));
        }
    };
    let local = listener.local_addr().map_err(|e| listen_error(vm, hostname, port_str, &e))?;
    let shutdown = Arc::new(AtomicBool::new(false));
    let sd = shutdown.clone();
    let (tx, rx) = mpsc::channel::<Conn>();
    std::thread::spawn(move || {
        for s in listener.incoming() {
            if sd.load(Ordering::SeqCst) {
                break;
            }
            let mut stream = match s {
                Ok(s) => s,
                Err(_) => continue,
            };
            let tx = tx.clone();
            std::thread::spawn(move || {
                let peer = stream.peer_addr().ok();
                let req = read_request(&mut stream);
                let _ = tx.send(Conn { stream, req, peer });
            });
        }
    });
    let id = next_id();
    SERVERS.with(|s| s.borrow_mut().insert(id, ServerCore { shutdown, addr: local, rx: Some(rx), server, closed: false }));
    server_recv(vm, id);
    Ok((id, local.port()))
}

fn serve_shutdown(id: u64) {
    let info = SERVERS.with(|s| {
        s.borrow_mut().get_mut(&id).and_then(|c| {
            if c.closed {
                None
            } else {
                c.closed = true;
                c.shutdown.store(true, Ordering::SeqCst);
                Some(c.addr)
            }
        })
    });
    if let Some(mut addr) = info {
        // wake the blocking accept
        if addr.ip().is_unspecified() {
            addr.set_ip(if addr.is_ipv4() { std::net::IpAddr::from([127, 0, 0, 1]) } else { std::net::IpAddr::from([0u16, 0, 0, 0, 0, 0, 0, 1]) });
        }
        let _ = TcpStream::connect_timeout(&addr, std::time::Duration::from_millis(200));
    }
}

fn server_recv(vm: &mut Vm, id: u64) {
    let rx = match SERVERS.with(|s| s.borrow_mut().get_mut(&id).and_then(|c| c.rx.take())) {
        Some(r) => r,
        None => return,
    };
    crate::runtime::spawn_op(
        vm,
        move || {
            let r = rx.recv().ok();
            (r, rx)
        },
        move |vm: &mut Vm, (conn, rx): (Option<Conn>, mpsc::Receiver<Conn>)| {
            let server = SERVERS.with(|s| {
                let mut s = s.borrow_mut();
                let c = s.get_mut(&id).unwrap();
                c.rx = Some(rx);
                c.server.clone()
            });
            match conn {
                Some(c) => {
                    dispatch_conn(vm, &server, c);
                    server_recv(vm, id);
                }
                None => {
                    SERVERS.with(|s| s.borrow_mut().remove(&id));
                }
            }
        },
    );
}

fn console_error(vm: &mut Vm, e: &Value) {
    let console = vm.global.get_own_str("console").unwrap_or(Value::Undefined);
    if console.truthy() {
        if let Ok(f) = getp(vm, &console, "error") {
            if f.is_callable() {
                let _ = vm.call(&f, console, &[e.clone()]);
                return;
            }
        }
    }
    let s = crate::runtime::display_value(vm, e);
    crate::runtime::write_stderr(&format!("{}\n", s));
}

/// One request: emulate Server.prototype._dispatch and answer when the response is done.
fn dispatch_conn(vm: &mut Vm, server: &Value, conn: Conn) {
    let Conn { stream, req, peer } = conn;
    let cid = next_id();
    CONNS.with(|c| c.borrow_mut().insert(cid, stream));
    let preq = match req {
        Some(r) => r,
        None => {
            write_raw_response(vm, cid, b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec());
            return;
        }
    };
    if preq.method.eq_ignore_ascii_case("HEAD") {
        HEAD_REQS.with(|h| h.borrow_mut().insert(cid));
    }
    let r = dispatch_request(vm, server, cid, preq, peer);
    if let Err(e) = r {
        handler_failed(vm, cid, &e);
    }
}

fn handler_failed(vm: &mut Vm, cid: u64, e: &Value) {
    console_error(vm, e);
    let body = b"Internal Server Error";
    let mut out = format!("HTTP/1.1 500 Internal Server Error\r\ncontent-type: text/plain;charset=UTF-8\r\nContent-Length: {}\r\nServer: {}\r\nConnection: close\r\n\r\n", body.len(), SERVER_NAME).into_bytes();
    if !HEAD_REQS.with(|h| h.borrow_mut().remove(&cid)) {
        out.extend_from_slice(body);
    }
    write_raw_response(vm, cid, out);
}

/// `new URL(request.url)` → pathname + search, for an origin-form target.
fn origin_form(vm: &mut Vm, target: &str, host: &str) -> String {
    if let Some(u) = vm.global.get_own_str("URL") {
        if u.is_callable() {
            let full = if target.starts_with('/') { format!("http://{}{}", if host.is_empty() { "localhost" } else { host }, target) } else { target.to_string() };
            if let Ok(uo) = vm.construct(&u, &[Value::str(&full)], None) {
                let p = getp(vm, &uo, "pathname").ok().map(|v| crate::runtime::display_value(vm, &v)).unwrap_or_default();
                let s = getp(vm, &uo, "search").ok().map(|v| crate::runtime::display_value(vm, &v)).unwrap_or_default();
                return format!("{}{}", p, s);
            }
        }
    }
    let t = target.split('#').next().unwrap_or("");
    if let Some(rest) = t.strip_prefix("http://").or_else(|| t.strip_prefix("https://")) {
        return match rest.find('/') {
            Some(p) => rest[p..].to_string(),
            None => "/".to_string(),
        };
    }
    t.to_string()
}

fn dispatch_request(vm: &mut Vm, server: &Value, cid: u64, preq: ParsedReq, peer: Option<SocketAddr>) -> JsResult<()> {
    let c = classes(vm);
    let (ra, rp) = match peer {
        Some(p) => (Value::str(&p.ip().to_string()), Value::Num(p.port() as f64)),
        None => (Value::Undefined, Value::Undefined),
    };
    let socket = Value::Obj(vm.obj_from(vec![("remoteAddress", ra), ("remotePort", rp), ("encrypted", Value::Bool(false))]));
    let req = vm.construct(&Value::Obj(c.incoming.clone()), &[socket], None)?;
    setp(vm, &req, "method", Value::str(&preq.method))?;
    let host = header_val(&preq.headers, "host").unwrap_or("").to_string();
    let url = origin_form(vm, &preq.target, &host);
    setp(vm, &req, "url", Value::str(&url))?;
    let headers = getp(vm, &req, "headers")?;
    let raw = getp(vm, &req, "rawHeaders")?;
    for (k, v) in normalize_headers(&preq.headers) {
        setp(vm, &headers, &k, Value::str(&v))?;
        call_method(vm, &raw, "push", &[Value::str(&k), Value::str(&v)])?;
    }
    let res = vm.construct(&Value::Obj(c.response.clone()), &[req.clone()], None)?;
    // const bodyBuf = Buffer.from(await request.arrayBuffer()) — then dispatch
    let body = new_buffer(vm, preq.body)?;
    let job = closure(vm, "", 0, dispatch_job, vec![server.clone(), req, res, body, Value::Num(cid as f64)]);
    queue_microtask(vm, job);
    Ok(())
}

fn dispatch_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (server, req, res, body) = (a.slot(0), a.slot(1), a.slot(2), a.slot(3));
    let cid = a.slot(4).as_num().unwrap_or(0.0) as u64;
    let r: JsResult<()> = (|| {
        let n = call_method(vm, &server, "listenerCount", &[Value::str("request")])?;
        if matches!(n, Value::Num(x) if x == 0.0) {
            call_method(vm, &res, "writeHead", &[Value::Num(404.0)])?;
            call_method(vm, &res, "end", &[])?;
        } else {
            emit(vm, &server, "request", &[req.clone(), res.clone()])?;
            let l = getp(vm, &body, "length")?;
            if !matches!(l, Value::Num(x) if x == 0.0) {
                call_method(vm, &req, "push", &[body.clone()])?;
            }
            call_method(vm, &req, "push", &[Value::Null])?;
            setp(vm, &req, "complete", Value::Bool(true))?;
        }
        // const out = await res._done
        let done = getp(vm, &res, "_done")?;
        if let Value::Obj(p) = &done {
            crate::builtins::promise::perform_then_internal(vm, p, Handler::Native(response_ready, Value::Num(cid as f64)), Handler::Native(response_failed, Value::Num(cid as f64)), None);
        }
        Ok(())
    })();
    if let Err(e) = r {
        handler_failed(vm, cid, &e);
    }
    Ok(Value::Undefined)
}

fn response_failed(vm: &mut Vm, e: Value, cid: &Value) -> JsResult<Value> {
    handler_failed(vm, cid.as_num().unwrap_or(0.0) as u64, &e);
    Ok(Value::Undefined)
}

fn response_ready(vm: &mut Vm, out: Value, cid: &Value) -> JsResult<Value> {
    let cid = cid.as_num().unwrap_or(0.0) as u64;
    let r: JsResult<Vec<u8>> = (|| {
        let status = getp(vm, &out, "status")?;
        let status = vm.to_number(&status)?;
        let st = getp(vm, &out, "statusText")?;
        let st = string_of(vm, &st)?;
        let hv = getp(vm, &out, "headers")?;
        let mut pairs = Vec::new();
        for p in crate::builtins::array::array_like_to_vec(vm, &hv)? {
            let k = vm.get_prop_of(&p, &PropKey::from_index(0))?;
            let v = vm.get_prop_of(&p, &PropKey::from_index(1))?;
            pairs.push((string_of(vm, &k)?, string_of(vm, &v)?));
        }
        let body = getp(vm, &out, "body")?;
        let bytes = match &body {
            Value::Obj(o) => crate::builtins::typedarray::ta_bytes(o),
            _ => Vec::new(),
        };
        let mut head = format!("HTTP/1.1 {} {}\r\n", crate::numconv::number_to_string(status), st);
        let norm = normalize_headers(&pairs);
        let mut has_len = false;
        let mut has_server = false;
        for (k, v) in &norm {
            if k == "connection" || k == "keep-alive" || k == "transfer-encoding" {
                continue;
            }
            if k == "content-length" {
                has_len = true;
            }
            if k == "server" {
                has_server = true;
            }
            head.push_str(&format!("{}: {}\r\n", k, v));
        }
        if !has_len {
            head.push_str(&format!("Content-Length: {}\r\n", bytes.len()));
        }
        if !has_server {
            head.push_str(&format!("Server: {}\r\n", SERVER_NAME));
        }
        head.push_str("Connection: close\r\n\r\n");
        let mut outb = head.into_bytes();
        if !HEAD_REQS.with(|h| h.borrow_mut().remove(&cid)) {
            outb.extend_from_slice(&bytes);
        }
        Ok(outb)
    })();
    match r {
        Ok(bytes) => write_raw_response(vm, cid, bytes),
        Err(e) => handler_failed(vm, cid, &e),
    }
    Ok(Value::Undefined)
}

fn write_raw_response(vm: &mut Vm, cid: u64, bytes: Vec<u8>) {
    let stream = CONNS.with(|c| c.borrow_mut().remove(&cid));
    if let Some(mut s) = stream {
        crate::runtime::spawn_op(
            vm,
            move || {
                let _ = s.write_all(&bytes);
                let _ = s.flush();
                let _ = s.shutdown(std::net::Shutdown::Both);
            },
            |_vm: &mut Vm, _: ()| {},
        );
    }
}

// --- http.Server ---

fn server_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.server_proto)?;
    crate::runtime::events::init_emitter(vm, &o);
    let this = Value::Obj(o);
    setp(vm, &this, "address_", Value::Null)?;
    let (opts, mut handler) = (a.arg(0), a.arg(1));
    if opts.is_callable() {
        handler = opts;
    }
    if handler.truthy() {
        call_method(vm, &this, "on", &[Value::str("request"), handler])?;
    }
    setp(vm, &this, "_lumen", Value::Null)?;
    setp(vm, &this, "listening", Value::Bool(false))?;
    Ok(this)
}

fn server_listen(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let port;
    let mut host = Value::str("0.0.0.0");
    let mut cb = Value::Undefined;
    let first = a.arg(0);
    if first.truthy() && first.is_object() && !first.is_callable() {
        let p = getp(vm, &first, "port")?;
        port = if p.is_nullish() { Value::Num(0.0) } else { p };
        let h = getp(vm, &first, "host")?;
        host = if h.is_nullish() { Value::str("0.0.0.0") } else { h };
        if let Some(f) = a.args.iter().find(|v| v.is_callable()) {
            cb = f.clone();
        }
    } else {
        port = if first.is_nullish() { Value::Num(0.0) } else { first };
        for v in a.args.iter().skip(1) {
            match v {
                Value::Str(_) => host = v.clone(),
                f if f.is_callable() => cb = f.clone(),
                _ => {}
            }
        }
    }
    let hs = string_of(vm, &host)?;
    let hostname = if hs == "localhost" { "127.0.0.1".to_string() } else { hs };
    let pn = to_number_js(vm, &port)?;
    let port_str = crate::numconv::number_to_string(pn);
    let p16 = if pn.is_finite() && pn >= 0.0 && pn <= 65535.0 { pn as u16 } else { 0 };
    let (id, bound) = serve_listen(vm, &hostname, &port_str, p16, this.clone())?;
    let lumen = vm.obj_from(vec![("hostname", Value::str(&hostname)), ("port", Value::Num(bound as f64)), ("_id", Value::Num(id as f64))]);
    setp(vm, &this, "_lumen", Value::Obj(lumen))?;
    setp(vm, &this, "listening", Value::Bool(true))?;
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("listening"), cb])?;
    }
    let job = closure(vm, "", 0, emit_listening, vec![this.clone()]);
    queue_microtask(vm, job);
    Ok(this)
}

fn to_number_js(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    crate::runtime::nodestream::to_num(vm, v)
}

fn emit_listening(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "listening", &[])?;
    Ok(Value::Undefined)
}

fn server_address(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let l = getp(vm, &a.this, "_lumen")?;
    if !l.truthy() {
        return Ok(Value::Null);
    }
    let h = getp(vm, &l, "hostname")?;
    let p = getp(vm, &l, "port")?;
    Ok(Value::Obj(vm.obj_from(vec![("address", h), ("family", Value::str("IPv4")), ("port", p)])))
}

fn server_dispatch_method(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    // requests are dispatched natively; the method exists for shape compatibility
    Ok(resolved(vm, Value::Undefined))
}

fn call_cb_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn emit_close_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "close", &[])?;
    Ok(Value::Undefined)
}

fn server_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let l = getp(vm, &this, "_lumen")?;
    if l.truthy() {
        let id = getp(vm, &l, "_id")?;
        if let Value::Num(n) = id {
            serve_shutdown(n as u64);
        }
    }
    setp(vm, &this, "listening", Value::Bool(false))?;
    let cb = a.arg(0);
    if cb.truthy() {
        let j = closure(vm, "", 0, call_cb_job, vec![cb]);
        queue_microtask(vm, j);
    }
    let j = closure(vm, "", 0, emit_close_job, vec![this.clone()]);
    queue_microtask(vm, j);
    Ok(this)
}

fn create_server(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.server), &[a.arg(0), a.arg(1)], None)
}

fn https_create_server(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.https_server), &[a.arg(0), a.arg(1)], None)
}

// ============================================================================================
// Agent
// ============================================================================================

fn agent_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = vm.intr.object_proto.clone();
    let o = new_instance(vm, a, &fb)?;
    crate::runtime::events::init_emitter(vm, &o);
    let this = Value::Obj(o);
    let options = if a.arg(0).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(0) };
    let copy = vm.new_object();
    if let Value::Obj(src) = &options {
        let keys = vm.enumerable_own_keys(src)?;
        for k in keys {
            let pk = PropKey::Str(k);
            let v = vm.get(src, &pk, &options)?;
            copy.set_prop(pk, v, WEC);
        }
    }
    setp(vm, &this, "options", Value::Obj(copy))?;
    let ms = getp(vm, &options, "maxSockets")?;
    setp(vm, &this, "maxSockets", if ms.is_nullish() { Value::Num(f64::INFINITY) } else { ms })?;
    let mf = getp(vm, &options, "maxFreeSockets")?;
    setp(vm, &this, "maxFreeSockets", if mf.is_nullish() { Value::Num(256.0) } else { mf })?;
    let ka = getp(vm, &options, "keepAlive")?;
    setp(vm, &this, "keepAlive", if ka.is_nullish() { Value::Bool(false) } else { ka })?;
    for k in ["sockets", "freeSockets", "requests"] {
        let o = Value::Obj(vm.new_object());
        setp(vm, &this, k, o)?;
    }
    setp(vm, &this, "protocol", Value::str("http:"))?;
    Ok(this)
}

fn agent_create_connection(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:http Agent.createConnection (raw sockets) is not supported in lumen (the client runs over fetch(), which cannot express it)")
}

// ============================================================================================
// ClientRequest
// ============================================================================================

struct ParsedUrl {
    protocol: String,
    hostname: String,
    port: String,
    path: String,
    username: String,
    password: String,
}

fn invalid_url(vm: &mut Vm, s: &str) -> Value {
    vm.make_error("TypeError", &format!("URL: invalid URL '{}' (relative, and no base given)", s))
}

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    let hex = |c: u8| (c as char).to_digit(16);
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// A small absolute-URL parser for the client (scheme://[user[:pass]@]host[:port][/path][?query]).
fn parse_url(s: &str) -> Option<ParsedUrl> {
    let s = s.trim();
    let colon = s.find(':')?;
    let scheme = &s[..colon];
    if scheme.is_empty() || !scheme.chars().next()?.is_ascii_alphabetic() || !scheme.chars().all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c)) {
        return None;
    }
    let rest = s[colon + 1..].strip_prefix("//")?;
    let rest = rest.split('#').next().unwrap_or("");
    let auth_end = rest.find(|c| c == '/' || c == '?').unwrap_or(rest.len());
    let authority = &rest[..auth_end];
    let mut path = rest[auth_end..].to_string();
    if path.is_empty() || path.starts_with('?') {
        path = format!("/{}", path);
    }
    let (userinfo, hostport) = match authority.rfind('@') {
        Some(p) => (&authority[..p], &authority[p + 1..]),
        None => ("", authority),
    };
    let (username, password) = match userinfo.find(':') {
        Some(p) => (userinfo[..p].to_string(), userinfo[p + 1..].to_string()),
        None => (userinfo.to_string(), String::new()),
    };
    let (hostname, port) = if hostport.starts_with('[') {
        let end = hostport.find(']')?;
        let h = hostport[..=end].to_string();
        let p = hostport[end + 1..].strip_prefix(':').unwrap_or("").to_string();
        (h, p)
    } else {
        match hostport.rfind(':') {
            Some(p) => (hostport[..p].to_string(), hostport[p + 1..].to_string()),
            None => (hostport.to_string(), String::new()),
        }
    };
    if hostname.is_empty() {
        return None;
    }
    let scheme_l = scheme.to_ascii_lowercase();
    let default_port = match scheme_l.as_str() {
        "http" => "80",
        "https" => "443",
        _ => "",
    };
    let port = if port == default_port { String::new() } else { port };
    Some(ParsedUrl { protocol: format!("{}:", scheme_l), hostname: hostname.to_ascii_lowercase(), port, path, username, password })
}

fn is_url_object(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    if let Some(u) = vm.global.get_own_str("URL") {
        if u.is_callable() && v.is_object() {
            return vm.instance_of(v, &u);
        }
    }
    Ok(false)
}

/// normalizeClientArgs(input, options, cb, defaultProtocol)
fn normalize_client_args(vm: &mut Vm, input: &Value, options: &Value, cb: &Value, default_protocol: &str) -> JsResult<Value> {
    let opts = vm.new_object();
    let mut cb = cb.clone();
    let mut options = options.clone();
    let is_url = matches!(input, Value::Str(_)) || is_url_object(vm, input)?;
    if is_url {
        let s = if let Value::Str(st) = input {
            st.to_rust_string()
        } else {
            let h = getp(vm, input, "href")?;
            string_of(vm, &h)?
        };
        let u = match parse_url(&s) {
            Some(u) => u,
            None => return Err(invalid_url(vm, &s)),
        };
        opts.set_prop(key("protocol"), Value::str(&u.protocol), WEC);
        opts.set_prop(key("hostname"), Value::str(&u.hostname), WEC);
        opts.set_prop(key("port"), if u.port.is_empty() { Value::Undefined } else { Value::str(&u.port) }, WEC);
        opts.set_prop(key("path"), Value::str(&u.path), WEC);
        let auth = if u.username.is_empty() { Value::Undefined } else { Value::str(&format!("{}:{}", percent_decode(&u.username), percent_decode(&u.password))) };
        opts.set_prop(key("auth"), auth, WEC);
        if options.is_callable() {
            cb = options.clone();
            options = Value::Undefined;
        }
        if options.truthy() {
            if let Value::Obj(src) = &options {
                let keys = vm.enumerable_own_keys(src)?;
                for k in keys {
                    let pk = PropKey::Str(k);
                    let v = vm.get(src, &pk, &options)?;
                    opts.set_prop(pk, v, WEC);
                }
            }
        }
    } else {
        if options.is_callable() {
            cb = options.clone();
        }
        if let Value::Obj(src) = input {
            let keys = vm.enumerable_own_keys(src)?;
            for k in keys {
                let pk = PropKey::Str(k);
                let v = vm.get(src, &pk, input)?;
                opts.set_prop(pk, v, WEC);
            }
        }
    }
    let o = Value::Obj(opts.clone());
    let p = getp(vm, &o, "protocol")?;
    if !p.truthy() {
        setp(vm, &o, "protocol", Value::str(default_protocol))?;
    }
    setp(vm, &o, "_cb", cb)?;
    Ok(o)
}

fn client_request_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.client_request_proto)?;
    let nt = a.new_target.clone();
    outgoing_init(vm, &o)?;
    let this = Value::Obj(o);
    let dp = match &nt {
        Some(t) => {
            let v = vm.get_str(t, "_defaultProtocol")?;
            if v.truthy() {
                string_of(vm, &v)?
            } else {
                "http:".to_string()
            }
        }
        None => "http:".to_string(),
    };
    let opts = normalize_client_args(vm, &a.arg(0), &a.arg(1), &a.arg(2), &dp)?;
    let protocol = getp(vm, &opts, "protocol")?;
    setp(vm, &this, "protocol", protocol.clone())?;
    let m = getp(vm, &opts, "method")?;
    let ms = if m.truthy() { string_of(vm, &m)? } else { "GET".to_string() };
    setp(vm, &this, "method", Value::str(&ms.to_uppercase()))?;
    let p = getp(vm, &opts, "path")?;
    setp(vm, &this, "path", if p.truthy() { p } else { Value::str("/") })?;
    let hn = getp(vm, &opts, "hostname")?;
    let h = if hn.truthy() {
        hn
    } else {
        let h2 = getp(vm, &opts, "host")?;
        if h2.truthy() {
            h2
        } else {
            Value::str("localhost")
        }
    };
    setp(vm, &this, "host", h.clone())?;
    let is_https = matches!(&protocol, Value::Str(s) if s.eq_str("https:"));
    let port = getp(vm, &opts, "port")?;
    let pv = if port.is_nullish() { Value::Num(if is_https { 443.0 } else { 80.0 }) } else { Value::Num(to_number_js(vm, &port)?) };
    setp(vm, &this, "port", pv.clone())?;
    setp(vm, &this, "_opts", opts.clone())?;
    let bc = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_bodyChunks", bc)?;
    setp(vm, &this, "aborted", Value::Bool(false))?;
    setp(vm, &this, "reusedSocket", Value::Bool(false))?;
    let ctrl = match vm.global.get_own_str("AbortController") {
        Some(ac) if ac.is_callable() => vm.construct(&ac, &[], None).unwrap_or(Value::Undefined),
        _ => Value::Obj(vm.new_object()),
    };
    setp(vm, &this, "_controller", ctrl)?;
    let to = getp(vm, &opts, "timeout")?;
    setp(vm, &this, "_timeoutMs", if matches!(to, Value::Num(_)) { to.clone() } else { Value::Undefined })?;
    setp(vm, &this, "_timer", Value::Null)?;
    setp(vm, &this, "res", Value::Null)?;
    let sock = Value::Obj(vm.obj_from(vec![("remoteAddress", h), ("remotePort", pv), ("encrypted", Value::Bool(is_https)), ("destroyed", Value::Bool(false))]));
    setp(vm, &this, "socket", sock.clone())?;
    setp(vm, &this, "connection", sock)?;
    let headers = getp(vm, &opts, "headers")?;
    if let Value::Obj(ho) = &headers {
        let keys = vm.enumerable_own_keys(ho)?;
        for k in keys {
            let v = vm.get(ho, &PropKey::Str(k.clone()), &headers)?;
            if !v.is_undefined() {
                call_method(vm, &this, "setHeader", &[Value::Str(k), v])?;
            }
        }
    }
    let auth = getp(vm, &opts, "auth")?;
    if auth.truthy() && !call_method(vm, &this, "hasHeader", &[Value::str("authorization")])?.truthy() {
        let s = string_of(vm, &auth)?;
        let enc = crate::runtime::encoding::base64_encode(s.as_bytes(), false);
        call_method(vm, &this, "setHeader", &[Value::str("Authorization"), Value::str(&format!("Basic {}", enc))])?;
    }
    let cb = getp(vm, &opts, "_cb")?;
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("response"), cb])?;
    }
    let sig = getp(vm, &opts, "signal")?;
    if sig.truthy() && getp(vm, &sig, "addEventListener")?.is_callable() {
        if getp(vm, &sig, "aborted")?.truthy() {
            let j = closure(vm, "", 0, cr_signal_abort, vec![this.clone(), sig.clone()]);
            queue_microtask(vm, j);
        } else {
            let f = closure(vm, "", 0, cr_signal_abort, vec![this.clone(), sig.clone()]);
            let o = Value::Obj(vm.obj_from(vec![("once", Value::Bool(true))]));
            call_method(vm, &sig, "addEventListener", &[Value::str("abort"), f, o])?;
        }
    }
    let tm = getp(vm, &this, "_timeoutMs")?;
    if !tm.is_undefined() {
        call_method(vm, &this, "setTimeout", &[tm])?;
    }
    Ok(this)
}

fn cr_signal_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = getp(vm, &a.slot(1), "reason")?;
    call_method(vm, &a.slot(0), "destroy", &[r])?;
    Ok(Value::Undefined)
}

fn cr_timeout_fire(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    setp(vm, &this, "_timer", Value::Null)?;
    emit(vm, &this, "timeout", &[])?;
    Ok(Value::Undefined)
}

fn cr_set_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let ms = a.arg(0);
    setp(vm, &this, "_timeoutMs", ms.clone())?;
    if a.arg(1).truthy() {
        call_method(vm, &this, "once", &[Value::str("timeout"), a.arg(1)])?;
    }
    cr_clear_timer_impl(vm, &this)?;
    let n = to_number_js(vm, &ms).unwrap_or(f64::NAN);
    if n > 0.0 {
        let f = closure(vm, "", 0, cr_timeout_fire, vec![this.clone()]);
        let id = crate::runtime::timers::add_timer(vm, f, n, Vec::new(), false);
        setp(vm, &this, "_timer", Value::Num(id as f64))?;
    }
    Ok(this)
}

fn cr_clear_timer_impl(vm: &mut Vm, this: &Value) -> JsResult<()> {
    let t = getp(vm, this, "_timer")?;
    if t.truthy() {
        crate::runtime::timers::clear_timer_id(vm, &t);
        setp(vm, this, "_timer", Value::Null)?;
    }
    Ok(())
}

fn cr_clear_timer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    cr_clear_timer_impl(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn cr_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let chunk = a.arg(0);
    if !chunk.is_nullish() {
        let l = getp(vm, &chunk, "length")?;
        if !matches!(l, Value::Num(n) if n == 0.0) {
            let b = chunk_to_buffer(vm, &chunk, &a.arg(1))?;
            let chunks = getp(vm, &this, "_bodyChunks")?;
            call_method(vm, &chunks, "push", &[b])?;
        }
    }
    vm.call(&a.arg(2), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn cr_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.this, "_send", &[])?;
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn cr_writable_ended(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    getp(vm, &a.this, "writableFinished")
}

fn cr_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "aborted")?.truthy() {
        return Ok(Value::Undefined);
    }
    setp(vm, &this, "aborted", Value::Bool(true))?;
    cr_clear_timer_impl(vm, &this)?;
    abort_controller(vm, &this);
    let sock = getp(vm, &this, "socket")?;
    setp(vm, &sock, "destroyed", Value::Bool(true))?;
    emit(vm, &this, "abort", &[])?;
    let f = closure(vm, "", 0, cr_destroy_job, vec![this]);
    crate::runtime::nodestream::next_tick(vm, f)?;
    Ok(Value::Undefined)
}

fn cr_destroy_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "destroy", &[])
}

fn abort_controller(vm: &mut Vm, this: &Value) {
    if let Ok(c) = getp(vm, this, "_controller") {
        if let Ok(f) = getp(vm, &c, "abort") {
            if f.is_callable() {
                let _ = vm.call(&f, c, &[]);
            }
        }
    }
}

fn cr_destroy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "destroyed")?.truthy() {
        return Ok(this);
    }
    setp(vm, &this, "destroyed", Value::Bool(true))?;
    cr_clear_timer_impl(vm, &this)?;
    abort_controller(vm, &this);
    let sock = getp(vm, &this, "socket")?;
    setp(vm, &sock, "destroyed", Value::Bool(true))?;
    let err = a.arg(0);
    if err.truthy() {
        emit(vm, &this, "error", &[err])?;
    }
    emit(vm, &this, "close", &[])?;
    Ok(this)
}

struct FetchResp {
    status: u16,
    status_text: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
}

fn http_exchange(url: &ParsedUrl, method: &str, headers: &[(String, String)], body: &Option<Vec<u8>>) -> Result<FetchResp, String> {
    let host = url.hostname.trim_start_matches('[').trim_end_matches(']').to_string();
    let port: u16 = if url.port.is_empty() {
        if url.protocol == "https:" {
            443
        } else {
            80
        }
    } else {
        url.port.parse().map_err(|_| "invalid port".to_string())?
    };
    let addrs: Vec<SocketAddr> = (host.as_str(), port).to_socket_addrs().map_err(|e| format!("connect: {}", e))?.collect();
    let mut stream = None;
    let mut last = None;
    for a in &addrs {
        match TcpStream::connect(a) {
            Ok(s) => {
                stream = Some(s);
                break;
            }
            Err(e) => last = Some(e),
        }
    }
    let mut stream = match stream {
        Some(s) => s,
        None => return Err(format!("connect: {}", last.map(|e| e.to_string()).unwrap_or_else(|| "no address".into()))),
    };
    if url.protocol == "https:" {
        return Err("TLS is not supported".to_string());
    }
    let host_header = if url.port.is_empty() { url.hostname.clone() } else { format!("{}:{}", url.hostname, url.port) };
    let mut req = format!("{} {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n", method, url.path, host_header);
    let mut has_ua = false;
    for (k, v) in headers {
        if k == "user-agent" {
            has_ua = true;
        }
        req.push_str(&format!("{}: {}\r\n", k, v));
    }
    if !has_ua {
        req.push_str(&format!("User-Agent: {}\r\n", SERVER_NAME));
    }
    if let Some(b) = body {
        req.push_str(&format!("Content-Length: {}\r\n", b.len()));
    }
    req.push_str("\r\n");
    let mut bytes = req.into_bytes();
    if let Some(b) = body {
        bytes.extend_from_slice(b);
    }
    stream.write_all(&bytes).map_err(|e| e.to_string())?;
    let mut buf = Vec::new();
    let p = read_head(&mut stream, &mut buf).ok_or_else(|| "connection closed before response".to_string())?;
    let head = String::from_utf8_lossy(&buf[..p]).to_string();
    let rest = buf[p + 4..].to_vec();
    let lines: Vec<&str> = head.split("\r\n").collect();
    let status_line = lines.first().copied().unwrap_or("");
    let mut parts = status_line.splitn(3, ' ');
    let _ver = parts.next();
    let status: u16 = parts.next().and_then(|s| s.parse().ok()).ok_or_else(|| "invalid response".to_string())?;
    let status_text = parts.next().unwrap_or("").to_string();
    let rh = parse_headers(&lines[1..]);
    let no_body = method == "HEAD" || status == 204 || status == 304 || (100..200).contains(&status);
    let body = if no_body { Vec::new() } else { read_body(&mut stream, rest, &rh, true).unwrap_or_default() };
    Ok(FetchResp { status, status_text, headers: rh, body })
}

/// fetch(url, { method, headers, body }) with redirects followed.
fn fetch_blocking(url_s: String, method: String, headers: Vec<(String, String)>, body: Option<Vec<u8>>) -> Result<(FetchResp, String), String> {
    let mut url_s = url_s;
    let mut method = method;
    let mut body = body;
    for _ in 0..20 {
        let url = parse_url(&url_s).ok_or_else(|| format!("invalid URL '{}'", url_s))?;
        // the URL as the WHATWG parser serialises it (default ports dropped)
        url_s = format!("{}//{}{}{}", url.protocol, url.hostname, if url.port.is_empty() { String::new() } else { format!(":{}", url.port) }, url.path);
        let r = http_exchange(&url, &method, &headers, &body).map_err(|e| format!("fetch '{}': {}", url_s, e))?;
        if matches!(r.status, 301 | 302 | 303 | 307 | 308) {
            if let Some(loc) = header_val(&r.headers, "location") {
                let next = if loc.contains("://") {
                    loc.to_string()
                } else if loc.starts_with("//") {
                    format!("{}{}", url.protocol, loc)
                } else if loc.starts_with('/') {
                    let hp = if url.port.is_empty() { url.hostname.clone() } else { format!("{}:{}", url.hostname, url.port) };
                    format!("{}//{}{}", url.protocol, hp, loc)
                } else {
                    let hp = if url.port.is_empty() { url.hostname.clone() } else { format!("{}:{}", url.hostname, url.port) };
                    let dir = match url.path.rfind('/') {
                        Some(p) => &url.path[..=p],
                        None => "/",
                    };
                    format!("{}//{}{}{}", url.protocol, hp, dir, loc)
                };
                if r.status == 303 || ((r.status == 301 || r.status == 302) && method == "POST") {
                    if method != "HEAD" {
                        method = "GET".to_string();
                    }
                    body = None;
                }
                url_s = next;
                continue;
            }
        }
        return Ok((r, url_s));
    }
    Err(format!("fetch '{}': too many redirects", url_s))
}

const CLIENT_SKIP_HEADERS: &[&str] = &["host", "connection", "content-length", "transfer-encoding", "keep-alive", "upgrade"];

fn cr_send(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "aborted")?.truthy() || getp(vm, &this, "destroyed")?.truthy() {
        return Ok(resolved(vm, Value::Undefined));
    }
    setp(vm, &this, "headersSent", Value::Bool(true))?;
    let protocol = getp(vm, &this, "protocol")?;
    let protocol = string_of(vm, &protocol)?;
    let host = getp(vm, &this, "host")?;
    let host = string_of(vm, &host)?;
    let port = getp(vm, &this, "port")?;
    let port_s = if port.truthy() { format!(":{}", string_of(vm, &port)?) } else { String::new() };
    let path = getp(vm, &this, "path")?;
    let path = string_of(vm, &path)?;
    let url = format!("{}//{}{}{}", protocol, host, port_s, path);
    let mut pairs = Vec::new();
    for (n, v) in hdr_entries(vm, &this)? {
        if CLIENT_SKIP_HEADERS.contains(&n.to_lowercase().as_str()) {
            continue;
        }
        if matches!(&v, Value::Obj(o) if o.is_array()) {
            for x in crate::builtins::array::array_like_to_vec(vm, &v)? {
                pairs.push((n.clone(), string_of(vm, &x)?));
            }
        } else {
            pairs.push((n, string_of(vm, &v)?));
        }
    }
    let headers = normalize_headers(&pairs);
    let method = getp(vm, &this, "method")?;
    let method = string_of(vm, &method)?;
    let no_body = method == "GET" || method == "HEAD";
    let chunks = getp(vm, &this, "_bodyChunks")?;
    let list = crate::builtins::array::array_like_to_vec(vm, &chunks)?;
    let mut body_bytes = Vec::new();
    for c in list {
        body_bytes.extend(crate::runtime::buffer::bytes_of(vm, &c)?);
    }
    let body = if no_body || body_bytes.is_empty() { None } else { Some(body_bytes) };
    let cap = vm.new_promise_capability_intrinsic();
    let target = this.clone();
    let url2 = url.clone();
    let resolve = cap.resolve.clone();
    crate::runtime::spawn_op(
        vm,
        move || fetch_blocking(url2, method, headers, body),
        move |vm: &mut Vm, r: Result<(FetchResp, String), String>| {
            let res = match r {
                Ok((resp, final_url)) => on_fetch_response(vm, &target, resp, &url, &final_url),
                Err(msg) => on_fetch_error(vm, &target, &msg),
            };
            if let Err(e) = res {
                // the async _send rejects with nobody listening
                rejected_unhandled(vm, e);
            }
            let _ = vm.call(&resolve, Value::Undefined, &[]);
        },
    );
    Ok(cap.promise)
}

fn rejected_unhandled(vm: &mut Vm, e: Value) {
    let _ = crate::runtime::nodestream::rejected(vm, e);
}

fn on_fetch_error(vm: &mut Vm, this: &Value, msg: &str) -> JsResult<()> {
    cr_clear_timer_impl(vm, this)?;
    if getp(vm, this, "aborted")?.truthy() {
        return Ok(());
    }
    let err = vm.make_error("TypeError", msg);
    emit(vm, this, "error", &[err])?;
    Ok(())
}

fn on_fetch_response(vm: &mut Vm, this: &Value, resp: FetchResp, url: &str, _final_url: &str) -> JsResult<()> {
    if getp(vm, this, "aborted")?.truthy() || getp(vm, this, "destroyed")?.truthy() {
        return Ok(());
    }
    let c = classes(vm);
    let sock = getp(vm, this, "socket")?;
    let res = vm.construct(&Value::Obj(c.incoming), &[sock], None)?;
    setp(vm, &res, "statusCode", Value::Num(resp.status as f64))?;
    let sm = if resp.status_text.is_empty() { status_text(resp.status as f64).to_string() } else { resp.status_text.clone() };
    setp(vm, &res, "statusMessage", Value::str(&sm))?;
    setp(vm, &res, "url", Value::str(url))?;
    let method = getp(vm, this, "method")?;
    setp(vm, &res, "method", method)?;
    let headers = getp(vm, &res, "headers")?;
    let raw = getp(vm, &res, "rawHeaders")?;
    for (k, v) in normalize_headers(&resp.headers) {
        let existing = getp(vm, &headers, &k)?;
        let nv = if existing.is_undefined() { Value::str(&v) } else { Value::str(&format!("{}, {}", string_of(vm, &existing)?, v)) };
        setp(vm, &headers, &k, nv)?;
        call_method(vm, &raw, "push", &[Value::str(&k), Value::str(&v)])?;
    }
    setp(vm, this, "res", res.clone())?;
    setp(vm, &res, "req", this.clone())?;
    emit(vm, this, "response", &[res.clone()])?;
    // buf = Buffer.from(await fetchRes.arrayBuffer())
    let body = new_buffer(vm, resp.body)?;
    let job = closure(vm, "", 0, deliver_body_job, vec![this.clone(), res, body]);
    queue_microtask(vm, job);
    Ok(())
}

fn deliver_body_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, res, body) = (a.slot(0), a.slot(1), a.slot(2));
    cr_clear_timer_impl(vm, &this)?;
    if getp(vm, &this, "aborted")?.truthy() || getp(vm, &this, "destroyed")?.truthy() {
        call_method(vm, &res, "push", &[Value::Null])?;
        return Ok(Value::Undefined);
    }
    let l = getp(vm, &body, "length")?;
    if !matches!(l, Value::Num(n) if n == 0.0) {
        call_method(vm, &res, "push", &[body])?;
    }
    call_method(vm, &res, "push", &[Value::Null])?;
    setp(vm, &res, "complete", Value::Bool(true))?;
    Ok(Value::Undefined)
}

fn http_request(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.client_request), &[a.arg(0), a.arg(1), a.arg(2)], None)
}

fn http_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = http_request(vm, a)?;
    call_method(vm, &r, "end", &[])?;
    Ok(r)
}

fn https_request(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.https_client_request), &[a.arg(0), a.arg(1), a.arg(2)], None)
}

fn https_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = https_request(vm, a)?;
    call_method(vm, &r, "end", &[])?;
    Ok(r)
}

fn connection_listener(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:http _connectionListener is not supported in lumen (raw sockets are not exposed to JS)")
}

// ============================================================================================
// modules
// ============================================================================================

fn status_codes_obj(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    for (c, t) in STATUS_CODES {
        o.set_prop(PropKey::from_index(*c as u32), Value::str(t), WEC);
    }
    Value::Obj(o)
}

fn create_http(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let o = vm.new_object();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    let f = plain_fn(vm, "createServer", 2, create_server);
    put(&o, "createServer", Value::Obj(f));
    put(&o, "Server", Value::Obj(c.server.clone()));
    put(&o, "IncomingMessage", Value::Obj(c.incoming.clone()));
    put(&o, "ServerResponse", Value::Obj(c.response.clone()));
    put(&o, "OutgoingMessage", Value::Obj(c.outgoing.clone()));
    put(&o, "ClientRequest", Value::Obj(c.client_request.clone()));
    let sc = status_codes_obj(vm);
    put(&o, "STATUS_CODES", sc);
    let ms: Vec<Value> = METHODS.iter().map(|m| Value::str(m)).collect();
    let ma = vm.new_array(ms);
    put(&o, "METHODS", Value::Obj(ma));
    let f = plain_fn(vm, "request", 3, http_request);
    put(&o, "request", Value::Obj(f));
    let f = plain_fn(vm, "get", 3, http_get);
    put(&o, "get", Value::Obj(f));
    put(&o, "Agent", Value::Obj(c.agent.clone()));
    let ga = vm.construct(&Value::Obj(c.agent.clone()), &[], None).unwrap_or(Value::Undefined);
    put(&o, "globalAgent", ga);
    put(&o, "maxHeaderSize", Value::Num(16384.0));
    let f = plain_fn(vm, "validateHeaderName", 2, validate_header_name);
    put(&o, "validateHeaderName", Value::Obj(f));
    let f = plain_fn(vm, "validateHeaderValue", 2, validate_header_value_f);
    put(&o, "validateHeaderValue", Value::Obj(f));
    let f = plain_fn(vm, "setMaxIdleHTTPParsers", 1, noop);
    put(&o, "setMaxIdleHTTPParsers", Value::Obj(f));
    let f = plain_fn(vm, "_connectionListener", 0, connection_listener);
    put(&o, "_connectionListener", Value::Obj(f));
    for n in ["WebSocket", "MessageEvent", "CloseEvent"] {
        let v = vm.global.get_own_str(n).unwrap_or(Value::Undefined);
        put(&o, n, v);
    }
    Value::Obj(o)
}

fn create_https(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let o = vm.new_object();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    put(&o, "Server", Value::Obj(c.https_server.clone()));
    let f = plain_fn(vm, "createServer", 2, https_create_server);
    put(&o, "createServer", Value::Obj(f));
    let f = plain_fn(vm, "httpsRequest", 3, https_request);
    put(&o, "request", Value::Obj(f));
    let f = plain_fn(vm, "httpsGet", 3, https_get);
    put(&o, "get", Value::Obj(f));
    put(&o, "ClientRequest", Value::Obj(c.https_client_request.clone()));
    put(&o, "Agent", Value::Obj(c.https_agent.clone()));
    let ga = vm.construct(&Value::Obj(c.https_agent.clone()), &[], None).unwrap_or(Value::Undefined);
    put(&o, "globalAgent", ga);
    Value::Obj(o)
}

// --- http2 ---

fn h2_default_settings(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(vm.obj_from(vec![
        ("headerTableSize", Value::Num(4096.0)),
        ("enablePush", Value::Bool(true)),
        ("initialWindowSize", Value::Num(65535.0)),
        ("maxFrameSize", Value::Num(16384.0)),
        ("maxConcurrentStreams", Value::Num(4294967295.0)),
        ("maxHeaderSize", Value::Num(65535.0)),
        ("maxHeaderListSize", Value::Num(65535.0)),
        ("enableConnectProtocol", Value::Bool(false)),
    ])))
}

fn h2_packed_settings(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = if a.arg(0).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(0) };
    let mut entries: Vec<(u16, u32)> = Vec::new();
    let num = |vm: &mut Vm, v: &Value| -> JsResult<u32> { vm.to_uint32(v) };
    for (k, id) in [("headerTableSize", 1u16), ("maxConcurrentStreams", 3), ("initialWindowSize", 4), ("maxFrameSize", 5)] {
        let v = getp(vm, &s, k)?;
        if !v.is_undefined() {
            entries.push((id, num(vm, &v)?));
        }
    }
    let mhl = getp(vm, &s, "maxHeaderListSize")?;
    if !mhl.is_undefined() {
        entries.push((6, num(vm, &mhl)?));
    } else {
        let mhs = getp(vm, &s, "maxHeaderSize")?;
        if !mhs.is_undefined() {
            entries.push((6, num(vm, &mhs)?));
        }
    }
    for (k, id) in [("enablePush", 2u16), ("enableConnectProtocol", 8)] {
        let v = getp(vm, &s, k)?;
        if !v.is_undefined() {
            entries.push((id, if v.truthy() { 1 } else { 0 }));
        }
    }
    let mut out = Vec::new();
    for (id, v) in entries {
        out.extend_from_slice(&id.to_be_bytes());
        out.extend_from_slice(&v.to_be_bytes());
    }
    new_buffer(vm, out)
}

fn h2_unpacked_settings(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let b = buffer_call(vm, "from", &[a.arg(0)])?;
    let bytes = crate::runtime::buffer::bytes_of(vm, &b)?;
    if bytes.len() % 6 != 0 {
        return Err(error_with_code(vm, "RangeError", "Packed settings length must be a multiple of six", "ERR_HTTP2_INVALID_PACKED_SETTINGS_LENGTH"));
    }
    let o = vm.new_object();
    for ch in bytes.chunks(6) {
        let id = u16::from_be_bytes([ch[0], ch[1]]);
        let v = u32::from_be_bytes([ch[2], ch[3], ch[4], ch[5]]) as f64;
        match id {
            1 => o.set_prop(key("headerTableSize"), Value::Num(v), WEC),
            2 => o.set_prop(key("enablePush"), Value::Bool(v != 0.0), WEC),
            3 => o.set_prop(key("maxConcurrentStreams"), Value::Num(v), WEC),
            4 => o.set_prop(key("initialWindowSize"), Value::Num(v), WEC),
            5 => o.set_prop(key("maxFrameSize"), Value::Num(v), WEC),
            6 => {
                o.set_prop(key("maxHeaderListSize"), Value::Num(v), WEC);
                o.set_prop(key("maxHeaderSize"), Value::Num(v), WEC);
            }
            8 => o.set_prop(key("enableConnectProtocol"), Value::Bool(v != 0.0), WEC),
            _ => {}
        }
    }
    Ok(Value::Obj(o))
}

fn h2_not_supported(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "http2.performServerHandshake is not supported in lumen; use createServer or createSecureServer")
}

fn h2_unsupported_ctor(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:http2 is not supported in this build")
}

fn create_http2(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    let consts = vm.new_object();
    for (k, v) in H2_CONSTANTS {
        let val = match v {
            H2C::N(n) => Value::Num(*n),
            H2C::S(s) => Value::str(s),
        };
        consts.set_prop(key(k), val, WEC);
    }
    put(&o, "constants", Value::Obj(consts));
    put(&o, "sensitiveHeaders", Value::Sym(Sym::new(Some(JsStr::from_str("sensitiveHeaders")))));
    let f = plain_fn(vm, "getDefaultSettings", 0, h2_default_settings);
    put(&o, "getDefaultSettings", Value::Obj(f));
    let f = plain_fn(vm, "getPackedSettings", 0, h2_packed_settings);
    put(&o, "getPackedSettings", Value::Obj(f));
    let f = plain_fn(vm, "getUnpackedSettings", 1, h2_unpacked_settings);
    put(&o, "getUnpackedSettings", Value::Obj(f));
    for (n, l) in [("createServer", 2u32), ("createSecureServer", 0), ("connect", 3)] {
        let f = plain_fn(vm, n, l, h2_unsupported_ctor);
        put(&o, n, Value::Obj(f));
    }
    let f = plain_fn(vm, "notSupported", 0, h2_not_supported);
    put(&o, "performServerHandshake", Value::Obj(f));
    let sc = crate::runtime::nodestream::classes(vm);
    for (n, l, parent) in [
        ("Http2ServerRequest", 2u32, Some((&sc.readable, &sc.readable_proto))),
        ("Http2ServerResponse", 1, Some((&sc.writable, &sc.writable_proto))),
        ("ClientHttp2Session", 1, Some((&sc.ee, &sc.ee_proto))),
        ("ClientHttp2Stream", 3, Some((&sc.duplex, &sc.duplex_proto))),
        ("ServerHttp2Session", 2, Some((&sc.ee, &sc.ee_proto))),
        ("ServerHttp2Stream", 3, Some((&sc.duplex, &sc.duplex_proto))),
        ("Http2Server", 0, Some((&sc.ee, &sc.ee_proto))),
    ] {
        let (c, p) = make_class(vm, n, l, h2_unsupported_ctor, parent);
        let methods: &[(&str, u32)] = match n {
            "Http2ServerResponse" => &[("setHeader", 2), ("getHeader", 1), ("getHeaders", 0), ("hasHeader", 1), ("removeHeader", 1), ("writeHead", 2), ("_sendHeaders", 0), ("_write", 3), ("_final", 1)],
            "ClientHttp2Session" => &[
                ("_connected", 0),
                ("request", 0),
                ("_sendHeaders", 3),
                ("_sendData", 4),
                ("_writeFrame", 4),
                ("_receive", 1),
                ("_handleFrame", 1),
                ("ping", 2),
                ("close", 1),
                ("destroy", 1),
                ("ref", 0),
                ("unref", 0),
                ("_fail", 1),
                ("_socketClosed", 0),
            ],
            "ClientHttp2Stream" => &[("_write", 3), ("_final", 1), ("close", 0), ("_finish", 0)],
            "ServerHttp2Session" => &[
                ("_receive", 1),
                ("_handleFrame", 1),
                ("_sendHeaders", 3),
                ("_sendData", 4),
                ("_writeFrame", 4),
                ("close", 1),
                ("destroy", 1),
                ("ref", 0),
                ("unref", 0),
                ("_fail", 1),
                ("_socketClosed", 0),
            ],
            "ServerHttp2Stream" => &[("respond", 0), ("additionalHeaders", 1), ("_write", 3), ("_final", 1), ("close", 0), ("_remoteEnd", 0), ("_close", 0)],
            "Http2Server" => &[("listen", 0), ("_emitRequest", 2), ("address", 0), ("close", 1), ("getConnections", 1), ("ref", 0), ("unref", 0)],
            _ => &[],
        };
        for (m, ml) in methods {
            vm.def_method(&p, m, *ml, h2_unsupported_ctor);
        }
        put(&o, n, Value::Obj(c));
    }
    let _ = proto_of_ctor;
    Value::Obj(o)
}

#[allow(unused_variables)]
#[allow(dead_code)]
pub fn setup(vm: &mut Vm) {}

pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    match name {
        "http" => create_http(vm),
        "https" => create_https(vm),
        _ => create_http2(vm),
    }
}

enum H2C {
    N(f64),
    S(&'static str),
}

const H2_CONSTANTS: &[(&str, H2C)] = &[
    ("NGHTTP2_ERR_FRAME_SIZE_ERROR", H2C::N(-522.0)),
    ("NGHTTP2_SESSION_SERVER", H2C::N(0.0)),
    ("NGHTTP2_SESSION_CLIENT", H2C::N(1.0)),
    ("NGHTTP2_STREAM_STATE_IDLE", H2C::N(1.0)),
    ("NGHTTP2_STREAM_STATE_OPEN", H2C::N(2.0)),
    ("NGHTTP2_STREAM_STATE_RESERVED_LOCAL", H2C::N(3.0)),
    ("NGHTTP2_STREAM_STATE_RESERVED_REMOTE", H2C::N(4.0)),
    ("NGHTTP2_STREAM_STATE_HALF_CLOSED_LOCAL", H2C::N(5.0)),
    ("NGHTTP2_STREAM_STATE_HALF_CLOSED_REMOTE", H2C::N(6.0)),
    ("NGHTTP2_STREAM_STATE_CLOSED", H2C::N(7.0)),
    ("NGHTTP2_FLAG_NONE", H2C::N(0.0)),
    ("NGHTTP2_FLAG_END_STREAM", H2C::N(1.0)),
    ("NGHTTP2_FLAG_END_HEADERS", H2C::N(4.0)),
    ("NGHTTP2_FLAG_ACK", H2C::N(1.0)),
    ("NGHTTP2_FLAG_PADDED", H2C::N(8.0)),
    ("NGHTTP2_FLAG_PRIORITY", H2C::N(32.0)),
    ("DEFAULT_SETTINGS_HEADER_TABLE_SIZE", H2C::N(4096.0)),
    ("DEFAULT_SETTINGS_ENABLE_PUSH", H2C::N(1.0)),
    ("DEFAULT_SETTINGS_MAX_CONCURRENT_STREAMS", H2C::N(4294967295.0)),
    ("DEFAULT_SETTINGS_INITIAL_WINDOW_SIZE", H2C::N(65535.0)),
    ("DEFAULT_SETTINGS_MAX_FRAME_SIZE", H2C::N(16384.0)),
    ("DEFAULT_SETTINGS_MAX_HEADER_LIST_SIZE", H2C::N(65535.0)),
    ("DEFAULT_SETTINGS_ENABLE_CONNECT_PROTOCOL", H2C::N(0.0)),
    ("MAX_MAX_FRAME_SIZE", H2C::N(16777215.0)),
    ("MIN_MAX_FRAME_SIZE", H2C::N(16384.0)),
    ("MAX_INITIAL_WINDOW_SIZE", H2C::N(2147483647.0)),
    ("NGHTTP2_SETTINGS_HEADER_TABLE_SIZE", H2C::N(1.0)),
    ("NGHTTP2_SETTINGS_ENABLE_PUSH", H2C::N(2.0)),
    ("NGHTTP2_SETTINGS_MAX_CONCURRENT_STREAMS", H2C::N(3.0)),
    ("NGHTTP2_SETTINGS_INITIAL_WINDOW_SIZE", H2C::N(4.0)),
    ("NGHTTP2_SETTINGS_MAX_FRAME_SIZE", H2C::N(5.0)),
    ("NGHTTP2_SETTINGS_MAX_HEADER_LIST_SIZE", H2C::N(6.0)),
    ("NGHTTP2_SETTINGS_ENABLE_CONNECT_PROTOCOL", H2C::N(8.0)),
    ("PADDING_STRATEGY_NONE", H2C::N(0.0)),
    ("PADDING_STRATEGY_ALIGNED", H2C::N(1.0)),
    ("PADDING_STRATEGY_MAX", H2C::N(2.0)),
    ("PADDING_STRATEGY_CALLBACK", H2C::N(1.0)),
    ("NGHTTP2_NO_ERROR", H2C::N(0.0)),
    ("NGHTTP2_PROTOCOL_ERROR", H2C::N(1.0)),
    ("NGHTTP2_INTERNAL_ERROR", H2C::N(2.0)),
    ("NGHTTP2_FLOW_CONTROL_ERROR", H2C::N(3.0)),
    ("NGHTTP2_SETTINGS_TIMEOUT", H2C::N(4.0)),
    ("NGHTTP2_STREAM_CLOSED", H2C::N(5.0)),
    ("NGHTTP2_FRAME_SIZE_ERROR", H2C::N(6.0)),
    ("NGHTTP2_REFUSED_STREAM", H2C::N(7.0)),
    ("NGHTTP2_CANCEL", H2C::N(8.0)),
    ("NGHTTP2_COMPRESSION_ERROR", H2C::N(9.0)),
    ("NGHTTP2_CONNECT_ERROR", H2C::N(10.0)),
    ("NGHTTP2_ENHANCE_YOUR_CALM", H2C::N(11.0)),
    ("NGHTTP2_INADEQUATE_SECURITY", H2C::N(12.0)),
    ("NGHTTP2_HTTP_1_1_REQUIRED", H2C::N(13.0)),
    ("NGHTTP2_DEFAULT_WEIGHT", H2C::N(16.0)),
    ("HTTP2_HEADER_STATUS", H2C::S(":status")),
    ("HTTP2_HEADER_METHOD", H2C::S(":method")),
    ("HTTP2_HEADER_AUTHORITY", H2C::S(":authority")),
    ("HTTP2_HEADER_SCHEME", H2C::S(":scheme")),
    ("HTTP2_HEADER_PATH", H2C::S(":path")),
    ("HTTP2_HEADER_PROTOCOL", H2C::S(":protocol")),
    ("HTTP2_HEADER_ACCEPT_ENCODING", H2C::S("accept-encoding")),
    ("HTTP2_HEADER_ACCEPT_LANGUAGE", H2C::S("accept-language")),
    ("HTTP2_HEADER_ACCEPT_RANGES", H2C::S("accept-ranges")),
    ("HTTP2_HEADER_ACCEPT", H2C::S("accept")),
    ("HTTP2_HEADER_ACCESS_CONTROL_ALLOW_CREDENTIALS", H2C::S("access-control-allow-credentials")),
    ("HTTP2_HEADER_ACCESS_CONTROL_ALLOW_HEADERS", H2C::S("access-control-allow-headers")),
    ("HTTP2_HEADER_ACCESS_CONTROL_ALLOW_METHODS", H2C::S("access-control-allow-methods")),
    ("HTTP2_HEADER_ACCESS_CONTROL_ALLOW_ORIGIN", H2C::S("access-control-allow-origin")),
    ("HTTP2_HEADER_ACCESS_CONTROL_EXPOSE_HEADERS", H2C::S("access-control-expose-headers")),
    ("HTTP2_HEADER_ACCESS_CONTROL_REQUEST_HEADERS", H2C::S("access-control-request-headers")),
    ("HTTP2_HEADER_ACCESS_CONTROL_REQUEST_METHOD", H2C::S("access-control-request-method")),
    ("HTTP2_HEADER_AGE", H2C::S("age")),
    ("HTTP2_HEADER_AUTHORIZATION", H2C::S("authorization")),
    ("HTTP2_HEADER_CACHE_CONTROL", H2C::S("cache-control")),
    ("HTTP2_HEADER_CONNECTION", H2C::S("connection")),
    ("HTTP2_HEADER_CONTENT_DISPOSITION", H2C::S("content-disposition")),
    ("HTTP2_HEADER_CONTENT_ENCODING", H2C::S("content-encoding")),
    ("HTTP2_HEADER_CONTENT_LENGTH", H2C::S("content-length")),
    ("HTTP2_HEADER_CONTENT_TYPE", H2C::S("content-type")),
    ("HTTP2_HEADER_COOKIE", H2C::S("cookie")),
    ("HTTP2_HEADER_DATE", H2C::S("date")),
    ("HTTP2_HEADER_ETAG", H2C::S("etag")),
    ("HTTP2_HEADER_FORWARDED", H2C::S("forwarded")),
    ("HTTP2_HEADER_HOST", H2C::S("host")),
    ("HTTP2_HEADER_IF_MODIFIED_SINCE", H2C::S("if-modified-since")),
    ("HTTP2_HEADER_IF_NONE_MATCH", H2C::S("if-none-match")),
    ("HTTP2_HEADER_IF_RANGE", H2C::S("if-range")),
    ("HTTP2_HEADER_LAST_MODIFIED", H2C::S("last-modified")),
    ("HTTP2_HEADER_LINK", H2C::S("link")),
    ("HTTP2_HEADER_LOCATION", H2C::S("location")),
    ("HTTP2_HEADER_RANGE", H2C::S("range")),
    ("HTTP2_HEADER_REFERER", H2C::S("referer")),
    ("HTTP2_HEADER_SERVER", H2C::S("server")),
    ("HTTP2_HEADER_SET_COOKIE", H2C::S("set-cookie")),
    ("HTTP2_HEADER_STRICT_TRANSPORT_SECURITY", H2C::S("strict-transport-security")),
    ("HTTP2_HEADER_TRANSFER_ENCODING", H2C::S("transfer-encoding")),
    ("HTTP2_HEADER_TE", H2C::S("te")),
    ("HTTP2_HEADER_UPGRADE_INSECURE_REQUESTS", H2C::S("upgrade-insecure-requests")),
    ("HTTP2_HEADER_UPGRADE", H2C::S("upgrade")),
    ("HTTP2_HEADER_USER_AGENT", H2C::S("user-agent")),
    ("HTTP2_HEADER_VARY", H2C::S("vary")),
    ("HTTP2_HEADER_X_CONTENT_TYPE_OPTIONS", H2C::S("x-content-type-options")),
    ("HTTP2_HEADER_X_FRAME_OPTIONS", H2C::S("x-frame-options")),
    ("HTTP2_HEADER_KEEP_ALIVE", H2C::S("keep-alive")),
    ("HTTP2_HEADER_PROXY_CONNECTION", H2C::S("proxy-connection")),
    ("HTTP2_HEADER_X_XSS_PROTECTION", H2C::S("x-xss-protection")),
    ("HTTP2_HEADER_ALT_SVC", H2C::S("alt-svc")),
    ("HTTP2_HEADER_CONTENT_SECURITY_POLICY", H2C::S("content-security-policy")),
    ("HTTP2_HEADER_EARLY_DATA", H2C::S("early-data")),
    ("HTTP2_HEADER_EXPECT_CT", H2C::S("expect-ct")),
    ("HTTP2_HEADER_ORIGIN", H2C::S("origin")),
    ("HTTP2_HEADER_PURPOSE", H2C::S("purpose")),
    ("HTTP2_HEADER_TIMING_ALLOW_ORIGIN", H2C::S("timing-allow-origin")),
    ("HTTP2_HEADER_X_FORWARDED_FOR", H2C::S("x-forwarded-for")),
    ("HTTP2_HEADER_PRIORITY", H2C::S("priority")),
    ("HTTP2_HEADER_ACCEPT_CHARSET", H2C::S("accept-charset")),
    ("HTTP2_HEADER_ACCESS_CONTROL_MAX_AGE", H2C::S("access-control-max-age")),
    ("HTTP2_HEADER_ALLOW", H2C::S("allow")),
    ("HTTP2_HEADER_CONTENT_LANGUAGE", H2C::S("content-language")),
    ("HTTP2_HEADER_CONTENT_LOCATION", H2C::S("content-location")),
    ("HTTP2_HEADER_CONTENT_MD5", H2C::S("content-md5")),
    ("HTTP2_HEADER_CONTENT_RANGE", H2C::S("content-range")),
    ("HTTP2_HEADER_DNT", H2C::S("dnt")),
    ("HTTP2_HEADER_EXPECT", H2C::S("expect")),
    ("HTTP2_HEADER_EXPIRES", H2C::S("expires")),
    ("HTTP2_HEADER_FROM", H2C::S("from")),
    ("HTTP2_HEADER_IF_MATCH", H2C::S("if-match")),
    ("HTTP2_HEADER_IF_UNMODIFIED_SINCE", H2C::S("if-unmodified-since")),
    ("HTTP2_HEADER_MAX_FORWARDS", H2C::S("max-forwards")),
    ("HTTP2_HEADER_PREFER", H2C::S("prefer")),
    ("HTTP2_HEADER_PROXY_AUTHENTICATE", H2C::S("proxy-authenticate")),
    ("HTTP2_HEADER_PROXY_AUTHORIZATION", H2C::S("proxy-authorization")),
    ("HTTP2_HEADER_REFRESH", H2C::S("refresh")),
    ("HTTP2_HEADER_RETRY_AFTER", H2C::S("retry-after")),
    ("HTTP2_HEADER_TRAILER", H2C::S("trailer")),
    ("HTTP2_HEADER_TK", H2C::S("tk")),
    ("HTTP2_HEADER_VIA", H2C::S("via")),
    ("HTTP2_HEADER_WARNING", H2C::S("warning")),
    ("HTTP2_HEADER_WWW_AUTHENTICATE", H2C::S("www-authenticate")),
    ("HTTP2_HEADER_HTTP2_SETTINGS", H2C::S("http2-settings")),
    ("HTTP2_METHOD_ACL", H2C::S("ACL")),
    ("HTTP2_METHOD_BASELINE_CONTROL", H2C::S("BASELINE-CONTROL")),
    ("HTTP2_METHOD_BIND", H2C::S("BIND")),
    ("HTTP2_METHOD_CHECKIN", H2C::S("CHECKIN")),
    ("HTTP2_METHOD_CHECKOUT", H2C::S("CHECKOUT")),
    ("HTTP2_METHOD_CONNECT", H2C::S("CONNECT")),
    ("HTTP2_METHOD_COPY", H2C::S("COPY")),
    ("HTTP2_METHOD_DELETE", H2C::S("DELETE")),
    ("HTTP2_METHOD_GET", H2C::S("GET")),
    ("HTTP2_METHOD_HEAD", H2C::S("HEAD")),
    ("HTTP2_METHOD_LABEL", H2C::S("LABEL")),
    ("HTTP2_METHOD_LINK", H2C::S("LINK")),
    ("HTTP2_METHOD_LOCK", H2C::S("LOCK")),
    ("HTTP2_METHOD_MERGE", H2C::S("MERGE")),
    ("HTTP2_METHOD_MKACTIVITY", H2C::S("MKACTIVITY")),
    ("HTTP2_METHOD_MKCALENDAR", H2C::S("MKCALENDAR")),
    ("HTTP2_METHOD_MKCOL", H2C::S("MKCOL")),
    ("HTTP2_METHOD_MKREDIRECTREF", H2C::S("MKREDIRECTREF")),
    ("HTTP2_METHOD_MKWORKSPACE", H2C::S("MKWORKSPACE")),
    ("HTTP2_METHOD_MOVE", H2C::S("MOVE")),
    ("HTTP2_METHOD_OPTIONS", H2C::S("OPTIONS")),
    ("HTTP2_METHOD_ORDERPATCH", H2C::S("ORDERPATCH")),
    ("HTTP2_METHOD_PATCH", H2C::S("PATCH")),
    ("HTTP2_METHOD_POST", H2C::S("POST")),
    ("HTTP2_METHOD_PRI", H2C::S("PRI")),
    ("HTTP2_METHOD_PROPFIND", H2C::S("PROPFIND")),
    ("HTTP2_METHOD_PROPPATCH", H2C::S("PROPPATCH")),
    ("HTTP2_METHOD_PUT", H2C::S("PUT")),
    ("HTTP2_METHOD_REBIND", H2C::S("REBIND")),
    ("HTTP2_METHOD_REPORT", H2C::S("REPORT")),
    ("HTTP2_METHOD_SEARCH", H2C::S("SEARCH")),
    ("HTTP2_METHOD_TRACE", H2C::S("TRACE")),
    ("HTTP2_METHOD_UNBIND", H2C::S("UNBIND")),
    ("HTTP2_METHOD_UNCHECKOUT", H2C::S("UNCHECKOUT")),
    ("HTTP2_METHOD_UNLINK", H2C::S("UNLINK")),
    ("HTTP2_METHOD_UNLOCK", H2C::S("UNLOCK")),
    ("HTTP2_METHOD_UPDATE", H2C::S("UPDATE")),
    ("HTTP2_METHOD_UPDATEREDIRECTREF", H2C::S("UPDATEREDIRECTREF")),
    ("HTTP2_METHOD_VERSION_CONTROL", H2C::S("VERSION-CONTROL")),
    ("HTTP_STATUS_CONTINUE", H2C::N(100.0)),
    ("HTTP_STATUS_SWITCHING_PROTOCOLS", H2C::N(101.0)),
    ("HTTP_STATUS_PROCESSING", H2C::N(102.0)),
    ("HTTP_STATUS_EARLY_HINTS", H2C::N(103.0)),
    ("HTTP_STATUS_OK", H2C::N(200.0)),
    ("HTTP_STATUS_CREATED", H2C::N(201.0)),
    ("HTTP_STATUS_ACCEPTED", H2C::N(202.0)),
    ("HTTP_STATUS_NON_AUTHORITATIVE_INFORMATION", H2C::N(203.0)),
    ("HTTP_STATUS_NO_CONTENT", H2C::N(204.0)),
    ("HTTP_STATUS_RESET_CONTENT", H2C::N(205.0)),
    ("HTTP_STATUS_PARTIAL_CONTENT", H2C::N(206.0)),
    ("HTTP_STATUS_MULTI_STATUS", H2C::N(207.0)),
    ("HTTP_STATUS_ALREADY_REPORTED", H2C::N(208.0)),
    ("HTTP_STATUS_IM_USED", H2C::N(226.0)),
    ("HTTP_STATUS_MULTIPLE_CHOICES", H2C::N(300.0)),
    ("HTTP_STATUS_MOVED_PERMANENTLY", H2C::N(301.0)),
    ("HTTP_STATUS_FOUND", H2C::N(302.0)),
    ("HTTP_STATUS_SEE_OTHER", H2C::N(303.0)),
    ("HTTP_STATUS_NOT_MODIFIED", H2C::N(304.0)),
    ("HTTP_STATUS_USE_PROXY", H2C::N(305.0)),
    ("HTTP_STATUS_TEMPORARY_REDIRECT", H2C::N(307.0)),
    ("HTTP_STATUS_PERMANENT_REDIRECT", H2C::N(308.0)),
    ("HTTP_STATUS_BAD_REQUEST", H2C::N(400.0)),
    ("HTTP_STATUS_UNAUTHORIZED", H2C::N(401.0)),
    ("HTTP_STATUS_PAYMENT_REQUIRED", H2C::N(402.0)),
    ("HTTP_STATUS_FORBIDDEN", H2C::N(403.0)),
    ("HTTP_STATUS_NOT_FOUND", H2C::N(404.0)),
    ("HTTP_STATUS_METHOD_NOT_ALLOWED", H2C::N(405.0)),
    ("HTTP_STATUS_NOT_ACCEPTABLE", H2C::N(406.0)),
    ("HTTP_STATUS_PROXY_AUTHENTICATION_REQUIRED", H2C::N(407.0)),
    ("HTTP_STATUS_REQUEST_TIMEOUT", H2C::N(408.0)),
    ("HTTP_STATUS_CONFLICT", H2C::N(409.0)),
    ("HTTP_STATUS_GONE", H2C::N(410.0)),
    ("HTTP_STATUS_LENGTH_REQUIRED", H2C::N(411.0)),
    ("HTTP_STATUS_PRECONDITION_FAILED", H2C::N(412.0)),
    ("HTTP_STATUS_PAYLOAD_TOO_LARGE", H2C::N(413.0)),
    ("HTTP_STATUS_URI_TOO_LONG", H2C::N(414.0)),
    ("HTTP_STATUS_UNSUPPORTED_MEDIA_TYPE", H2C::N(415.0)),
    ("HTTP_STATUS_RANGE_NOT_SATISFIABLE", H2C::N(416.0)),
    ("HTTP_STATUS_EXPECTATION_FAILED", H2C::N(417.0)),
    ("HTTP_STATUS_TEAPOT", H2C::N(418.0)),
    ("HTTP_STATUS_MISDIRECTED_REQUEST", H2C::N(421.0)),
    ("HTTP_STATUS_UNPROCESSABLE_ENTITY", H2C::N(422.0)),
    ("HTTP_STATUS_LOCKED", H2C::N(423.0)),
    ("HTTP_STATUS_FAILED_DEPENDENCY", H2C::N(424.0)),
    ("HTTP_STATUS_TOO_EARLY", H2C::N(425.0)),
    ("HTTP_STATUS_UPGRADE_REQUIRED", H2C::N(426.0)),
    ("HTTP_STATUS_PRECONDITION_REQUIRED", H2C::N(428.0)),
    ("HTTP_STATUS_TOO_MANY_REQUESTS", H2C::N(429.0)),
    ("HTTP_STATUS_REQUEST_HEADER_FIELDS_TOO_LARGE", H2C::N(431.0)),
    ("HTTP_STATUS_UNAVAILABLE_FOR_LEGAL_REASONS", H2C::N(451.0)),
    ("HTTP_STATUS_INTERNAL_SERVER_ERROR", H2C::N(500.0)),
    ("HTTP_STATUS_NOT_IMPLEMENTED", H2C::N(501.0)),
    ("HTTP_STATUS_BAD_GATEWAY", H2C::N(502.0)),
    ("HTTP_STATUS_SERVICE_UNAVAILABLE", H2C::N(503.0)),
    ("HTTP_STATUS_GATEWAY_TIMEOUT", H2C::N(504.0)),
    ("HTTP_STATUS_HTTP_VERSION_NOT_SUPPORTED", H2C::N(505.0)),
    ("HTTP_STATUS_VARIANT_ALSO_NEGOTIATES", H2C::N(506.0)),
    ("HTTP_STATUS_INSUFFICIENT_STORAGE", H2C::N(507.0)),
    ("HTTP_STATUS_LOOP_DETECTED", H2C::N(508.0)),
    ("HTTP_STATUS_BANDWIDTH_LIMIT_EXCEEDED", H2C::N(509.0)),
    ("HTTP_STATUS_NOT_EXTENDED", H2C::N(510.0)),
    ("HTTP_STATUS_NETWORK_AUTHENTICATION_REQUIRED", H2C::N(511.0)),
];

// the reference's JS frames for errors raised synchronously by these entry points
crate::framed_native!(res_set_header_f, ["setHeader"], res_set_header);
crate::framed_native!(out_set_header_f, ["setHeader"], out_set_header);
crate::framed_native!(validate_header_value_f, ["validateHeaderValue"], validate_header_value);
