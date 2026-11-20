// node:net, node:dns (+ dns/promises), node:tls and node:dgram, modelled on the reference:
//
// * net.Socket is a Duplex over a native TCP / Unix stream: a read pump pushes chunks (and EOF,
//   which ends the writable side too unless allowHalfOpen), writes go through `_write`, and
//   'close' follows once both directions are done. net.Server accepts in a loop and hands each
//   connection over as a Socket. Errors look like Node's ("connect ECONNREFUSED host:port"
//   with code/syscall/address/port).
// * dns.lookup uses the system resolver; resolve4/resolve6 resolve through it too, other record
//   types send a real query to the first nameserver of /etc/resolv.conf.
// * tls has no TLS engine here: the helpers work, connections fail.
// * dgram sockets are real UDP sockets; received datagrams are delivered from a timer.

use crate::object::*;
use crate::runtime::nodestream::{call_method, closure, emit, error_with_code, getp, host_obj, key, make_class, new_buffer, new_instance, plain_fn, queue_microtask, resolved, setp, string_of, with_host};
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream, ToSocketAddrs, UdpSocket};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

// ============================================================================================
// IP helpers
// ============================================================================================

fn is_ipv4_str(s: &str) -> bool {
    let parts: Vec<&str> = s.split('.').collect();
    parts.len() == 4 && parts.iter().all(|p| !p.is_empty() && p.len() <= 3 && p.bytes().all(|b| b.is_ascii_digit()) && p.parse::<u32>().map_or(false, |n| n <= 255))
}

/// /^([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}$/i
fn v6re(s: &str) -> bool {
    let parts: Vec<&str> = s.split(':').collect();
    let colons = parts.len() - 1;
    if !(2..=7).contains(&colons) {
        return false;
    }
    parts.iter().all(|p| p.len() <= 4 && p.bytes().all(|b| b.is_ascii_hexdigit()))
}

fn is_ipv6_str(s: &str) -> bool {
    if s.contains("::") {
        v6re(s) && s.split("::").count() <= 2
    } else {
        v6re(s)
    }
}

fn is_ip_value(v: &Value) -> u8 {
    match v {
        Value::Str(s) => {
            let r = s.to_rust_string();
            if is_ipv4_str(&r) {
                4
            } else if is_ipv6_str(&r) {
                6
            } else {
                0
            }
        }
        _ => 0,
    }
}

fn net_is_ip(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Num(is_ip_value(&a.arg(0)) as f64))
}

fn net_is_ipv4(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(is_ip_value(&a.arg(0)) == 4))
}

fn net_is_ipv6(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(&a.arg(0), Value::Str(s) if is_ipv6_str(&s.to_rust_string()))))
}

/// ipToBig(address, family) as a u128 (errors are TypeErrors).
fn ip_to_big(vm: &mut Vm, addr: &str, family: &str) -> JsResult<u128> {
    if family == "ipv6" {
        match addr.parse::<std::net::Ipv6Addr>() {
            Ok(a) => Ok(u128::from(a)),
            Err(_) => vm.throw_type(format!("Invalid IPv6 address: {}", addr)),
        }
    } else {
        if !is_ipv4_str(addr) {
            return vm.throw_type(format!("Invalid IPv4 address: {}", addr));
        }
        let mut n: u128 = 0;
        for p in addr.split('.') {
            n = (n << 8) | p.parse::<u128>().unwrap_or(0);
        }
        Ok(n)
    }
}

fn fam_label(f: &str) -> &'static str {
    if f == "ipv6" {
        "IPv6"
    } else {
        "IPv4"
    }
}

// --- BlockList ---

#[derive(Clone)]
enum Rule {
    Address(String, u128),
    Range(String, u128, u128),
    Subnet(String, u128, u128),
}

struct BlockState {
    rules: RefCell<Vec<Rule>>,
    strings: RefCell<Vec<String>>,
}

thread_local! {
    static NET_CLASSES: RefCell<Option<NetClasses>> = RefCell::new(None);
    static AUTO_SELECT: Cell<(bool, f64)> = Cell::new((true, 250.0));
    static NEXT_ID: Cell<u64> = Cell::new(1);
    static SOCKS: RefCell<HashMap<u64, NetStream>> = RefCell::new(HashMap::new());
    static LISTENERS: RefCell<HashMap<u64, ListenerEntry>> = RefCell::new(HashMap::new());
    static UDPS: RefCell<HashMap<u64, UdpEntry>> = RefCell::new(HashMap::new());
    static DNS_STATE: RefCell<(String, Option<Value>)> = RefCell::new(("verbatim".to_string(), None));
}

fn next_id() -> u64 {
    NEXT_ID.with(|n| {
        let v = n.get();
        n.set(v + 1);
        v
    })
}

fn block_state(vm: &mut Vm, this: &Value) -> JsResult<Value> {
    let s = getp(vm, this, "_rules")?;
    Ok(s)
}

fn norm_family(vm: &mut Vm, f: &Value) -> JsResult<String> {
    let s = string_of(vm, f)?.to_lowercase();
    if s != "ipv4" && s != "ipv6" {
        let raw = string_of(vm, f)?;
        return vm.throw_type(format!("Invalid family: {}", raw));
    }
    Ok(s)
}

fn socket_address_parts(vm: &mut Vm, v: &Value) -> JsResult<Option<(String, String)>> {
    let c = classes(vm);
    if vm.instance_of(v, &Value::Obj(c.socket_address.clone()))? {
        let a = getp(vm, v, "address")?;
        let f = getp(vm, v, "family")?;
        return Ok(Some((string_of(vm, &a)?, string_of(vm, &f)?)));
    }
    Ok(None)
}

fn blocklist_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.blocklist_proto)?;
    let this = Value::Obj(o);
    let st = host_obj(BlockState { rules: RefCell::new(Vec::new()), strings: RefCell::new(Vec::new()) });
    // the reference keeps `_rules` / `_strings` arrays; one hidden state object stands in
    setp(vm, &this, "_rules", st)?;
    let strings = Value::Obj(vm.new_array(Vec::new()));
    setp(vm, &this, "_strings", strings)?;
    Ok(this)
}

fn bl_push(vm: &mut Vm, this: &Value, rule: Rule, text: String) -> JsResult<()> {
    let st = block_state(vm, this)?;
    with_host::<BlockState, ()>(&st, |s| {
        s.rules.borrow_mut().insert(0, rule);
        s.strings.borrow_mut().insert(0, text.clone());
    });
    let strings = getp(vm, this, "_strings")?;
    call_method(vm, &strings, "unshift", &[Value::str(&text)])?;
    Ok(())
}

fn bl_norm_family(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = norm_family(vm, &a.arg(0))?;
    Ok(Value::str(&f))
}

fn bl_add_address(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (mut address, mut family) = (a.arg(0), if a.arg(1).is_undefined() { Value::str("ipv4") } else { a.arg(1) });
    if let Some((ad, f)) = socket_address_parts(vm, &address)? {
        address = Value::str(&ad);
        family = Value::str(&f);
    }
    let fam = norm_family(vm, &family)?;
    let ad = string_of(vm, &address)?;
    let n = ip_to_big(vm, &ad, &fam)?;
    bl_push(vm, &a.this, Rule::Address(fam.clone(), n), format!("Address: {} {}", fam_label(&fam), ad))?;
    Ok(Value::Undefined)
}

fn bl_add_range(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (mut start, mut end, mut family) = (a.arg(0), a.arg(1), if a.arg(2).is_undefined() { Value::str("ipv4") } else { a.arg(2) });
    if let Some((ad, f)) = socket_address_parts(vm, &start)? {
        start = Value::str(&ad);
        family = Value::str(&f);
    }
    if let Some((ad, _)) = socket_address_parts(vm, &end)? {
        end = Value::str(&ad);
    }
    let fam = norm_family(vm, &family)?;
    let ss = string_of(vm, &start)?;
    let es = string_of(vm, &end)?;
    let s = ip_to_big(vm, &ss, &fam)?;
    let e = ip_to_big(vm, &es, &fam)?;
    if e < s {
        return vm.throw_error("Error", "The value of \"start\" is out of range. It must be <= end");
    }
    bl_push(vm, &a.this, Rule::Range(fam.clone(), s, e), format!("Range: {} {}-{}", fam_label(&fam), ss, es))?;
    Ok(Value::Undefined)
}

fn bl_add_subnet(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (mut network, prefix, mut family) = (a.arg(0), a.arg(1), if a.arg(2).is_undefined() { Value::str("ipv4") } else { a.arg(2) });
    if let Some((ad, f)) = socket_address_parts(vm, &network)? {
        network = Value::str(&ad);
        family = Value::str(&f);
    }
    let fam = norm_family(vm, &family)?;
    let bits: i32 = if fam == "ipv6" { 128 } else { 32 };
    let p = vm.to_int32(&prefix)?;
    if p < 0 || p > bits {
        return vm.throw_range(format!("Invalid prefix: {}", p));
    }
    let full: u128 = if bits == 128 { u128::MAX } else { (1u128 << 32) - 1 };
    let mask = if p == 0 { 0 } else { (full << (bits - p) as u32) & full };
    let ns = string_of(vm, &network)?;
    let base = ip_to_big(vm, &ns, &fam)? & mask;
    bl_push(vm, &a.this, Rule::Subnet(fam.clone(), base, mask), format!("Subnet: {} {}/{}", fam_label(&fam), ns, p))?;
    Ok(Value::Undefined)
}

fn bl_check(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (mut address, mut family) = (a.arg(0), a.arg(1));
    if let Some((ad, f)) = socket_address_parts(vm, &address)? {
        address = Value::str(&ad);
        family = Value::str(&f);
    }
    if !family.truthy() {
        family = Value::str(if is_ip_value(&address) == 6 { "ipv6" } else { "ipv4" });
    }
    let fam = string_of(vm, &family)?.to_lowercase();
    let ad = string_of(vm, &address)?;
    let n = match ip_to_big(vm, &ad, &fam) {
        Ok(n) => n,
        Err(_) => return Ok(Value::Bool(false)),
    };
    let st = block_state(vm, &a.this)?;
    let rules = with_host::<BlockState, Vec<Rule>>(&st, |s| s.rules.borrow().clone()).unwrap_or_default();
    for r in rules {
        let hit = match r {
            Rule::Address(f, x) => f == fam && n == x,
            Rule::Range(f, s, e) => f == fam && n >= s && n <= e,
            Rule::Subnet(f, base, mask) => f == fam && (n & mask) == base,
        };
        if hit {
            return Ok(Value::Bool(true));
        }
    }
    Ok(Value::Bool(false))
}

fn bl_rules(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = getp(vm, &a.this, "_strings")?;
    call_method(vm, &s, "slice", &[])
}

// --- SocketAddress ---

fn socket_address_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.socket_address_proto)?;
    let this = Value::Obj(o.clone());
    let options = if a.arg(0).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(0) };
    let fo = getp(vm, &options, "family")?;
    let family = if fo.truthy() { string_of(vm, &fo)? } else { "ipv4".to_string() }.to_lowercase();
    if family != "ipv4" && family != "ipv6" {
        let raw = string_of(vm, &fo)?;
        return vm.throw_type(format!("Invalid family: {}", raw));
    }
    let ao = getp(vm, &options, "address")?;
    let address = if !ao.is_undefined() { string_of(vm, &ao)? } else if family == "ipv4" { "127.0.0.1".to_string() } else { "::".to_string() };
    let ok = if family == "ipv4" { is_ipv4_str(&address) } else { is_ipv6_str(&address) };
    if !ok {
        return vm.throw_type(format!("Invalid address: {}", address));
    }
    setp(vm, &this, "address", Value::str(&address))?;
    setp(vm, &this, "family", Value::str(&family))?;
    let po = getp(vm, &options, "port")?;
    let port = if po.is_undefined() { 0 } else { vm.to_int32(&po)? };
    setp(vm, &this, "port", Value::Num(port as f64))?;
    let fl = getp(vm, &options, "flowlabel")?;
    let flow = if fl.is_undefined() { 0 } else { vm.to_int32(&fl)? };
    setp(vm, &this, "flowlabel", Value::Num(flow as f64))?;
    // Object.freeze(this)
    let freeze = vm.get_str(&vm.intr.object_ctor.clone(), "freeze")?;
    vm.call(&freeze, Value::Undefined, &[this.clone()])?;
    Ok(this)
}

fn socket_address_parse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let input = string_of(vm, &a.arg(0))?;
    let c = classes(vm);
    let mk = |vm: &mut Vm, addr: &str, fam: &str, port: f64| -> Value {
        let o = vm.obj_from(vec![("address", Value::str(addr)), ("family", Value::str(fam)), ("port", Value::Num(port))]);
        vm.construct(&Value::Obj(c.socket_address.clone()), &[Value::Obj(o)], None).unwrap_or(Value::Undefined)
    };
    // [ipv6]:port
    if let Some(rest) = input.strip_prefix('[') {
        if let Some(end) = rest.find(']') {
            let addr = &rest[..end];
            let after = &rest[end + 1..];
            let port_ok = after.is_empty() || (after.starts_with(':') && after.len() > 1 && after[1..].bytes().all(|b| b.is_ascii_digit()));
            if !addr.is_empty() && addr.bytes().all(|b| b.is_ascii_hexdigit() || b == b':') && port_ok {
                let port = if after.is_empty() { 0.0 } else { after[1..].parse::<f64>().unwrap_or(0.0) };
                return Ok(mk(vm, addr, "ipv6", port));
            }
        }
    }
    // ipv4[:port]
    let (host, port) = match input.rfind(':') {
        Some(p) if !input.contains("::") && input[..p].contains('.') => (&input[..p], Some(&input[p + 1..])),
        _ => (input.as_str(), None),
    };
    let v4shape = host.split('.').count() == 4 && host.split('.').all(|p| !p.is_empty() && p.len() <= 3 && p.bytes().all(|b| b.is_ascii_digit()));
    if v4shape && port.map_or(true, |p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit())) {
        if !is_ipv4_str(host) {
            return Ok(Value::Undefined);
        }
        let pn = port.map(|p| p.parse::<f64>().unwrap_or(0.0)).unwrap_or(0.0);
        return Ok(mk(vm, host, "ipv4", pn));
    }
    if is_ipv6_str(&input) {
        return Ok(mk(vm, &input, "ipv6", 0.0));
    }
    Ok(Value::Undefined)
}

// --- autoSelectFamily ---

fn set_auto_select(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = a.arg(0).truthy();
    AUTO_SELECT.with(|s| {
        let (_, t) = s.get();
        s.set((v, t));
    });
    Ok(Value::Undefined)
}

fn get_auto_select(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(AUTO_SELECT.with(|s| s.get().0)))
}

fn set_auto_select_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = vm.to_number(&a.arg(0))?;
    if !(v.is_finite() && v.fract() == 0.0) || v <= 0.0 {
        return vm.throw_range("autoSelectFamilyAttemptTimeout must be a positive integer");
    }
    let v = if v < 10.0 { 10.0 } else { v };
    AUTO_SELECT.with(|s| {
        let (b, _) = s.get();
        s.set((b, v));
    });
    Ok(Value::Undefined)
}

fn get_auto_select_timeout(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(AUTO_SELECT.with(|s| s.get().1)))
}

/// _normalizeArgs(args) → [options, cb] (+ Symbol.for("normalizedArgs"))
fn normalize_args(vm: &mut Vm, args: &[Value]) -> JsResult<(Value, Value, Value)> {
    let options = vm.new_object();
    let mut cb = Value::Null;
    if !args.is_empty() {
        let first = &args[0];
        let opts = if first.is_object() && !first.is_callable() {
            first.clone()
        } else {
            match first {
                Value::Str(s) if !(s.to_rust_string().bytes().all(|b| b.is_ascii_digit()) && !s.to_rust_string().is_empty()) => {
                    options.set_prop(key("path"), first.clone(), WEC);
                }
                _ => {
                    options.set_prop(key("port"), first.clone(), WEC);
                }
            }
            Value::Obj(options.clone())
        };
        if let Some(Value::Str(_)) = args.get(1) {
            setp(vm, &opts, "host", args[1].clone())?;
        }
        if let Some(last) = args.last() {
            if last.is_callable() {
                cb = last.clone();
            }
        }
        let arr = vm.new_array(vec![opts.clone(), cb.clone()]);
        let sym = vm_symbol_for(vm, "normalizedArgs");
        arr.set_prop(PropKey::Sym(sym), Value::Bool(true), WEC);
        return Ok((opts, cb, Value::Obj(arr)));
    }
    let o = Value::Obj(options);
    let arr = vm.new_array(vec![o.clone(), Value::Null]);
    let sym = vm_symbol_for(vm, "normalizedArgs");
    arr.set_prop(PropKey::Sym(sym), Value::Bool(true), WEC);
    Ok((o, Value::Null, Value::Obj(arr)))
}

fn vm_symbol_for(vm: &mut Vm, name: &str) -> Sym {
    let k = JsStr::from_str(name);
    if let Some(s) = vm.symbol_registry.get(&k) {
        return s.clone();
    }
    let s = Sym::new(Some(k.clone()));
    vm.symbol_registry.insert(k, s.clone());
    s
}

fn net_normalize_args(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let args = crate::builtins::array::array_like_to_vec(vm, &a.arg(0))?;
    let (_, _, arr) = normalize_args(vm, &args)?;
    Ok(arr)
}

// ============================================================================================
// native streams
// ============================================================================================

enum NetStream {
    Tcp(TcpStream),
    Unix(UnixStream),
}

impl NetStream {
    fn try_clone(&self) -> std::io::Result<NetStream> {
        Ok(match self {
            NetStream::Tcp(s) => NetStream::Tcp(s.try_clone()?),
            NetStream::Unix(s) => NetStream::Unix(s.try_clone()?),
        })
    }
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            NetStream::Tcp(s) => s.read(buf),
            NetStream::Unix(s) => s.read(buf),
        }
    }
    fn write_all(&mut self, b: &[u8]) -> std::io::Result<()> {
        match self {
            NetStream::Tcp(s) => s.write_all(b),
            NetStream::Unix(s) => s.write_all(b),
        }
    }
    fn shutdown(&self, how: std::net::Shutdown) {
        let _ = match self {
            NetStream::Tcp(s) => s.shutdown(how),
            NetStream::Unix(s) => s.shutdown(how),
        };
    }
}

enum NetListener {
    Tcp(TcpListener),
    Unix(UnixListener),
}

struct ListenerEntry {
    listener: Arc<NetListener>,
    closed: Arc<AtomicBool>,
    addr: Option<SocketAddr>,
    path: Option<String>,
}

/// (id, localAddress, localPort, remoteAddress, remotePort, family) of an adopted stream.
type Desc = (u64, Value, Value, Value, Value, Value);

fn errno_code(e: &std::io::Error) -> String {
    use std::io::ErrorKind::*;
    let s = match e.kind() {
        ConnectionRefused => "ECONNREFUSED",
        ConnectionReset => "ECONNRESET",
        ConnectionAborted => "ECONNABORTED",
        AddrInUse => "EADDRINUSE",
        AddrNotAvailable => "EADDRNOTAVAIL",
        NotFound => "ENOENT",
        PermissionDenied => "EACCES",
        TimedOut => "ETIMEDOUT",
        BrokenPipe => "EPIPE",
        NotConnected => "ENOTCONN",
        _ => match e.raw_os_error() {
            Some(101) => "ENETUNREACH",
            Some(113) => "EHOSTUNREACH",
            Some(22) => "EINVAL",
            Some(99) => "EADDRNOTAVAIL",
            _ => "EIO",
        },
    };
    s.to_string()
}

#[derive(Clone)]
struct NetErr {
    syscall: String,
    code: String,
    address: Option<String>,
    port: Option<f64>,
    custom: Option<String>,
}

fn net_err_value(vm: &mut Vm, e: &NetErr) -> Value {
    let msg = match &e.custom {
        Some(m) => m.clone(),
        None => {
            let mut m = format!("{} {}", e.syscall, e.code);
            if let Some(a) = &e.address {
                m.push(' ');
                m.push_str(a);
                if let Some(p) = e.port {
                    m.push(':');
                    m.push_str(&crate::numconv::number_to_string(p));
                }
            }
            m
        }
    };
    let err = vm.make_error("Error", &msg);
    if let Value::Obj(o) = &err {
        o.set_prop(key("code"), Value::str(&e.code), WEC);
        o.set_prop(key("syscall"), Value::str(&e.syscall), WEC);
        if let Some(a) = &e.address {
            o.set_prop(key("address"), Value::str(a), WEC);
        }
        if let Some(p) = e.port {
            o.set_prop(key("port"), Value::Num(p), WEC);
        }
    }
    err
}

fn addr_strings(a: &SocketAddr) -> (String, f64, &'static str) {
    (a.ip().to_string(), a.port() as f64, if a.is_ipv6() { "IPv6" } else { "IPv4" })
}

fn register_stream(s: NetStream) -> u64 {
    let id = next_id();
    SOCKS.with(|m| m.borrow_mut().insert(id, s));
    id
}

fn desc_of(id: u64, local: Option<SocketAddr>, peer: Option<SocketAddr>) -> Desc {
    let (la, lp, fam) = match &local {
        Some(a) => {
            let (x, y, f) = addr_strings(a);
            (Value::str(&x), Value::Num(y), Value::str(f))
        }
        None => (Value::Undefined, Value::Undefined, Value::Undefined),
    };
    let (ra, rp) = match &peer {
        Some(a) => {
            let (x, y, _) = addr_strings(a);
            (Value::str(&x), Value::Num(y))
        }
        None => (Value::Undefined, Value::Undefined),
    };
    (id, la, lp, ra, rp, fam)
}

// ============================================================================================
// net.Socket
// ============================================================================================

#[derive(Clone)]
struct NetClasses {
    socket: Obj,
    socket_proto: Obj,
    server: Obj,
    server_proto: Obj,
    blocklist: Obj,
    blocklist_proto: Obj,
    socket_address: Obj,
    socket_address_proto: Obj,
    tls_socket: Obj,
    tls_socket_proto: Obj,
    tls_server: Obj,
    tls_server_proto: Obj,
    secure_context: Obj,
    dgram_socket: Obj,
    dgram_socket_proto: Obj,
    resolver: Obj,
    resolver_proto: Obj,
    promise_resolver: Obj,
    promise_resolver_proto: Obj,
}

fn noop(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Undefined)
}

fn return_this(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(a.this.clone())
}

fn classes(vm: &mut Vm) -> NetClasses {
    if let Some(c) = NET_CLASSES.with(|c| c.borrow().clone()) {
        return c;
    }
    let sc = crate::runtime::nodestream::classes(vm);
    // net.Socket extends Duplex
    let (socket, sp) = make_class(vm, "Socket", 0, socket_ctor_f, Some((&sc.duplex, &sc.duplex_proto)));
    let sm: &[(&str, u32, NativeFn)] = &[
        ("_adopt", 1, sock_adopt),
        ("_readRaw", 0, sock_read_raw),
        ("connect", 0, sock_connect_f),
        ("_write", 3, sock_write),
        ("_final", 1, sock_final),
        ("_maybeClose", 0, sock_maybe_close),
        ("destroy", 1, sock_destroy),
        ("destroySoon", 0, sock_destroy_plain),
        ("resetAndDestroy", 0, sock_destroy_plain),
        ("setTimeout", 2, sock_set_timeout),
        ("_clearTimeout", 0, sock_clear_timeout),
        ("_resetTimeout", 0, sock_reset_timeout),
        ("setNoDelay", 0, sock_set_no_delay),
        ("setKeepAlive", 0, sock_set_keep_alive),
        ("address", 0, sock_address),
        ("ref", 0, return_this),
        ("unref", 0, return_this),
    ];
    for (n, l, f) in sm {
        vm.def_method(&sp, n, *l, *f);
    }
    vm.def_getter(&sp, "readyState", sock_ready_state);
    vm.def_getter(&sp, "bufferSize", |_vm, _a| Ok(Value::Num(0.0)));

    let (server, svp) = make_class(vm, "Server", 2, server_ctor, Some((&sc.ee, &sc.ee_proto)));
    let svm: &[(&str, u32, NativeFn)] = &[
        ("listen", 0, server_listen_f),
        ("_acceptLoop", 0, server_accept_loop_method),
        ("address", 0, server_address),
        ("close", 1, server_close),
        ("_maybeEmitClose", 0, server_maybe_emit_close_method),
        ("getConnections", 1, server_get_connections),
        ("ref", 0, return_this),
        ("unref", 0, return_this),
    ];
    for (n, l, f) in svm {
        vm.def_method(&svp, n, *l, *f);
    }

    let (blocklist, blp) = make_class(vm, "BlockList", 0, blocklist_ctor, None);
    let blm: &[(&str, u32, NativeFn)] = &[("_normFamily", 1, bl_norm_family), ("addAddress", 1, bl_add_address), ("addRange", 2, bl_add_range), ("addSubnet", 2, bl_add_subnet), ("check", 2, bl_check)];
    for (n, l, f) in blm {
        vm.def_method(&blp, n, *l, *f);
    }
    vm.def_getter(&blp, "rules", bl_rules);

    let (socket_address, sap) = make_class(vm, "SocketAddress", 0, socket_address_ctor, None);
    vm.def_method(&socket_address, "parse", 1, socket_address_parse);

    // tls
    let (tls_socket, tsp) = make_class(vm, "TLSSocket", 1, tls_socket_ctor, Some((&sc.duplex, &sc.duplex_proto)));
    let tm: &[(&str, u32, NativeFn)] = &[
        ("_connect", 2, tls_connect_method),
        ("_upgrade", 3, tls_connect_method),
        ("_adopt", 1, noop),
        ("_pump", 0, noop),
        ("_write", 3, tls_write),
        ("_final", 1, tls_final),
        ("destroy", 1, tls_destroy),
        ("_finishClose", 0, noop),
        ("address", 0, |vm, _a| Ok(Value::Obj(vm.new_object()))),
        ("getProtocol", 0, |vm, a| getp(vm, &a.this, "_protocol")),
        ("getCipher", 0, |_vm, _a| Ok(Value::Null)),
        ("getPeerCertificate", 0, |vm, _a| Ok(Value::Obj(vm.new_object()))),
        ("getCertificate", 0, |vm, _a| Ok(Value::Obj(vm.new_object()))),
        ("getFinished", 0, noop),
        ("getPeerFinished", 0, noop),
        ("getSession", 0, noop),
        ("isSessionReused", 0, |_vm, _a| Ok(Value::Bool(false))),
        ("renegotiate", 2, |_vm, _a| Ok(Value::Bool(false))),
        ("setServername", 1, noop),
        ("setMaxSendFragment", 0, |_vm, _a| Ok(Value::Bool(true))),
        ("disableRenegotiation", 0, noop),
        ("ref", 0, return_this),
        ("unref", 0, return_this),
    ];
    for (n, l, f) in tm {
        vm.def_method(&tsp, n, *l, *f);
    }
    let (tls_server, tsvp) = make_class(vm, "Server", 2, tls_server_ctor, Some((&sc.ee, &sc.ee_proto)));
    let tsm: &[(&str, u32, NativeFn)] = &[
        ("listen", 0, tls_server_listen),
        ("_acceptLoop", 0, noop),
        ("address", 0, |vm, a| getp(vm, &a.this, "_address")),
        ("close", 1, tls_server_close),
        ("getConnections", 1, server_get_connections),
        ("ref", 0, return_this),
        ("unref", 0, return_this),
    ];
    for (n, l, f) in tsm {
        vm.def_method(&tsvp, n, *l, *f);
    }
    let (secure_context, _) = make_class(vm, "SecureContext", 0, secure_context_ctor, None);

    // dgram
    let (dgram_socket, dsp) = make_class(vm, "Socket", 2, dgram_socket_ctor_f, Some((&sc.ee, &sc.ee_proto)));
    let dm: &[(&str, u32, NativeFn)] = &[
        ("bind", 0, dgram_bind),
        ("_ensureBound", 0, dgram_ensure_bound),
        ("_recvLoop", 0, noop),
        ("send", 0, dgram_send),
        ("connect", 3, dgram_connect),
        ("disconnect", 0, dgram_disconnect),
        ("remoteAddress", 0, dgram_remote_address),
        ("address", 0, dgram_address),
        ("close", 1, dgram_close),
        ("_op", 1, noop),
        ("setBroadcast", 1, dgram_set_broadcast),
        ("setTTL", 1, dgram_set_ttl),
        ("setMulticastTTL", 1, dgram_set_multicast_ttl),
        ("setMulticastLoopback", 1, |_vm, a| Ok(Value::Bool(a.arg(0).truthy()))),
        ("setMulticastInterface", 1, return_this),
        ("addMembership", 2, noop),
        ("dropMembership", 2, noop),
        ("addSourceSpecificMembership", 3, noop),
        ("dropSourceSpecificMembership", 3, noop),
        ("ref", 0, return_this),
        ("unref", 0, return_this),
        ("getRecvBufferSize", 0, |_vm, _a| Ok(Value::Num(212992.0))),
        ("getSendBufferSize", 0, |_vm, _a| Ok(Value::Num(212992.0))),
        ("setRecvBufferSize", 1, noop),
        ("setSendBufferSize", 1, noop),
        ("_setBufferSize", 2, noop),
    ];
    for (n, l, f) in dm {
        vm.def_method(&dsp, n, *l, *f);
    }

    // dns
    let (resolver, rp) = make_class(vm, "Resolver", 1, resolver_ctor, None);
    let rm: &[(&str, u32, NativeFn)] = &[
        ("getServers", 0, resolver_get_servers),
        ("setServers", 1, resolver_set_servers),
        ("setLocalAddress", 0, noop),
        ("cancel", 0, noop),
        ("resolve", 3, resolver_resolve),
        ("reverse", 2, resolver_reverse),
    ];
    for (n, l, f) in rm {
        vm.def_method(&rp, n, *l, *f);
    }
    for (n, t) in RESOLVE_FNS {
        let f = vm.native_closure("", 3, resolver_resolve_typed, vec![Value::str(t)]);
        vm.make_ctor(&f);
        let p = vm.new_object();
        p.set_prop(key("constructor"), Value::Obj(f.clone()), WC);
        f.set_prop(key("prototype"), Value::Obj(p), WRITABLE);
        rp.set_prop(key(n), Value::Obj(f), WEC);
    }
    let (promise_resolver, prp) = make_class(vm, "PromiseResolver", 1, promise_resolver_ctor, None);
    let prm: &[(&str, u32, NativeFn)] = &[("getServers", 0, presolver_get_servers), ("setServers", 1, presolver_set_servers), ("setLocalAddress", 0, noop), ("cancel", 0, noop)];
    for (n, l, f) in prm {
        vm.def_method(&prp, n, *l, *f);
    }
    for n in std::iter::once("resolve").chain(std::iter::once("reverse")).chain(RESOLVE_FNS.iter().map(|(n, _)| *n)) {
        let f = vm.native_closure("", 0, presolver_method, vec![Value::str(n)]);
        vm.make_ctor(&f);
        let p = vm.new_object();
        p.set_prop(key("constructor"), Value::Obj(f.clone()), WC);
        f.set_prop(key("prototype"), Value::Obj(p), WRITABLE);
        prp.set_prop(key(n), Value::Obj(f), WEC);
    }

    let c = NetClasses {
        socket,
        socket_proto: sp,
        server,
        server_proto: svp,
        blocklist,
        blocklist_proto: blp,
        socket_address,
        socket_address_proto: sap,
        tls_socket,
        tls_socket_proto: tsp,
        tls_server,
        tls_server_proto: tsvp,
        secure_context,
        dgram_socket,
        dgram_socket_proto: dsp,
        resolver,
        resolver_proto: rp,
        promise_resolver,
        promise_resolver_proto: prp,
    };
    NET_CLASSES.with(|s| *s.borrow_mut() = Some(c.clone()));
    c
}

fn socket_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.socket_proto)?;
    let mut options = a.arg(0);
    if !options.is_object() || options.is_callable() && false {
        options = Value::Obj(vm.new_object());
    }
    if !getp(vm, &options, "fd")?.is_undefined() {
        return crate::runtime::nodestream::with_frames(vm, &["fdNotSupported"], |vm| vm.throw_error("Error", "node:net new Socket({ fd }) is not supported in lumen (arbitrary OS fd wrapping is unavailable)"));
    }
    let empty = Value::Obj(vm.new_object());
    crate::runtime::nodestream::duplex_init(vm, &o, &empty)?;
    let this = Value::Obj(o);
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "connecting", Value::Bool(false))?;
    setp(vm, &this, "pending", Value::Bool(true))?;
    setp(vm, &this, "destroyed", Value::Bool(false))?;
    let aho = getp(vm, &options, "allowHalfOpen")?.truthy();
    setp(vm, &this, "allowHalfOpen", Value::Bool(aho))?;
    for k in ["remoteAddress", "remotePort", "remoteFamily", "localAddress", "localPort", "localFamily"] {
        setp(vm, &this, k, Value::Undefined)?;
    }
    setp(vm, &this, "bytesRead", Value::Num(0.0))?;
    setp(vm, &this, "bytesWritten", Value::Num(0.0))?;
    setp(vm, &this, "_sawEof", Value::Bool(false))?;
    setp(vm, &this, "_closeEmitted", Value::Bool(false))?;
    setp(vm, &this, "_hadError", Value::Bool(false))?;
    setp(vm, &this, "_timeoutMs", Value::Num(0.0))?;
    setp(vm, &this, "_timeoutTimer", Value::Null)?;
    setp(vm, &this, "_pendingNoDelay", Value::Undefined)?;
    setp(vm, &this, "_pendingKeepAlive", Value::Undefined)?;
    let dr = getp(vm, &options, "_deferRead")?.truthy();
    setp(vm, &this, "_deferRead", Value::Bool(dr))?;
    Ok(this)
}

fn sock_id(vm: &mut Vm, this: &Value) -> JsResult<Option<u64>> {
    Ok(match getp(vm, this, "_id")? {
        Value::Num(n) => Some(n as u64),
        _ => None,
    })
}

fn desc_to_array(vm: &mut Vm, d: &Desc) -> Value {
    Value::Obj(vm.new_array(vec![Value::Num(d.0 as f64), d.1.clone(), d.2.clone(), d.3.clone(), d.4.clone(), d.5.clone()]))
}

fn sock_adopt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let d = a.arg(0);
    let g = |vm: &mut Vm, i: u32| vm.get_prop_of(&d, &PropKey::from_index(i));
    let id = g(vm, 0)?;
    setp(vm, &this, "_id", id.clone())?;
    let la = g(vm, 1)?;
    setp(vm, &this, "localAddress", la)?;
    let lp = g(vm, 2)?;
    setp(vm, &this, "localPort", lp)?;
    let ra = g(vm, 3)?;
    setp(vm, &this, "remoteAddress", ra)?;
    let rp = g(vm, 4)?;
    setp(vm, &this, "remotePort", rp)?;
    let fam = g(vm, 5)?;
    setp(vm, &this, "remoteFamily", fam.clone())?;
    setp(vm, &this, "localFamily", fam)?;
    setp(vm, &this, "pending", Value::Bool(false))?;
    setp(vm, &this, "connecting", Value::Bool(false))?;
    let nd = getp(vm, &this, "_pendingNoDelay")?;
    if !nd.is_undefined() {
        set_no_delay_native(vm, &id, nd.truthy());
    }
    if !getp(vm, &this, "_deferRead")?.truthy() {
        pump_socket(vm, this);
    }
    Ok(Value::Undefined)
}

fn set_no_delay_native(_vm: &mut Vm, id: &Value, on: bool) {
    if let Value::Num(n) = id {
        SOCKS.with(|m| {
            if let Some(NetStream::Tcp(s)) = m.borrow().get(&(*n as u64)) {
                let _ = s.set_nodelay(on);
            }
        });
    }
}

/// net.read(id) on a worker: Ok(bytes) (empty at EOF) or the error.
fn native_read(vm: &mut Vm, id: u64, then: impl FnOnce(&mut Vm, Result<Vec<u8>, NetErr>) + 'static) {
    let s = SOCKS.with(|m| m.borrow().get(&id).map(|s| s.try_clone()));
    let mut s = match s {
        Some(Ok(s)) => s,
        _ => {
            let r: Result<Vec<u8>, NetErr> = Ok(Vec::new());
            crate::runtime::spawn_op(vm, move || r, then);
            return;
        }
    };
    crate::runtime::spawn_op(
        vm,
        move || {
            let mut buf = vec![0u8; 65536];
            loop {
                match s.read(&mut buf) {
                    Ok(n) => {
                        buf.truncate(n);
                        return Ok(buf);
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(e) => return Err(NetErr { syscall: "read".into(), code: errno_code(&e), address: None, port: None, custom: None }),
                }
            }
        },
        then,
    );
}

/// pumpSocket(socket)
fn pump_socket(vm: &mut Vm, socket: Value) {
    let id = match sock_id(vm, &socket) {
        Ok(Some(i)) => i,
        _ => return,
    };
    native_read(vm, id, move |vm: &mut Vm, r: Result<Vec<u8>, NetErr>| {
        // `await socket._readRaw()` resumes one microtask after the read completes
        let payload = match r {
            Ok(b) => {
                if b.is_empty() {
                    Value::Null
                } else {
                    new_buffer(vm, b).unwrap_or(Value::Null)
                }
            }
            Err(e) => {
                let ev = net_err_value(vm, &e);
                let j = closure(vm, "", 0, pump_error_job, vec![socket.clone(), ev]);
                queue_microtask(vm, j);
                return;
            }
        };
        let j = closure(vm, "", 0, pump_chunk_job, vec![socket.clone(), payload]);
        queue_microtask(vm, j);
    });
}

fn pump_error_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let socket = a.slot(0);
    call_method(vm, &socket, "destroy", &[a.slot(1)])?;
    Ok(Value::Undefined)
}

fn pump_chunk_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let socket = a.slot(0);
    let chunk = a.slot(1);
    let r: JsResult<bool> = (|| {
        if getp(vm, &socket, "_id")?.is_null() {
            return Ok(false);
        }
        if chunk.is_null() {
            setp(vm, &socket, "_sawEof", Value::Bool(true))?;
            // once 'end' is delivered: end our side too (unless half-open) and maybe close
            let on_end = closure(vm, "", 0, socket_on_eof_end, vec![socket.clone()]);
            call_method(vm, &socket, "once", &[Value::str("end"), on_end])?;
            call_method(vm, &socket, "push", &[Value::Null])?;
            return Ok(false);
        }
        let l = getp(vm, &chunk, "length")?;
        let br = getp(vm, &socket, "bytesRead")?;
        let nb = vm.op_add(&br, &l)?;
        setp(vm, &socket, "bytesRead", nb)?;
        call_method(vm, &socket, "_resetTimeout", &[])?;
        call_method(vm, &socket, "push", &[chunk])?;
        Ok(true)
    })();
    match r {
        Ok(true) => pump_socket(vm, socket),
        Ok(false) => {}
        Err(e) => {
            call_method(vm, &socket, "destroy", &[e])?;
        }
    }
    Ok(Value::Undefined)
}

fn socket_on_eof_end(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let socket = a.slot(0);
    let ws = getp(vm, &socket, "_writableState")?;
    if !getp(vm, &socket, "allowHalfOpen")?.truthy() && !getp(vm, &ws, "ended")?.truthy() && !getp(vm, &socket, "destroyed")?.truthy() {
        call_method(vm, &socket, "end", &[])?;
    }
    call_method(vm, &socket, "_maybeClose", &[])?;
    Ok(Value::Undefined)
}

fn sock_read_raw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = sock_id(vm, &a.this)?;
    let cap = vm.new_promise_capability_intrinsic();
    match id {
        None => {
            let e = vm.make_error("Error", "Socket is not connected");
            vm.call(&cap.reject, Value::Undefined, &[e])?;
        }
        Some(id) => {
            let (res, rej) = (cap.resolve.clone(), cap.reject.clone());
            native_read(vm, id, move |vm: &mut Vm, r: Result<Vec<u8>, NetErr>| {
                let _ = match r {
                    Ok(b) if b.is_empty() => vm.call(&res, Value::Undefined, &[Value::Null]),
                    Ok(b) => {
                        let bv = new_buffer(vm, b).unwrap_or(Value::Null);
                        vm.call(&res, Value::Undefined, &[bv])
                    }
                    Err(e) => {
                        let ev = net_err_value(vm, &e);
                        vm.call(&rej, Value::Undefined, &[ev])
                    }
                };
            });
        }
    }
    Ok(cap.promise)
}

fn parse_port_option(vm: &mut Vm, port: &Value) -> JsResult<u16> {
    let n = crate::runtime::nodestream::to_num(vm, port)?;
    if !(n.is_finite() && n.fract() == 0.0) || n < 0.0 || n > 65535.0 {
        let d = crate::runtime::display_value(vm, port);
        return vm.throw_range(format!("\"port\" option should be >= 0 and < 65536. Received {}.", d));
    }
    Ok(n as u16)
}

fn sock_connect(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (options, cb) = if !a.args.is_empty() && a.arg(0).is_object() && !a.arg(0).is_callable() {
        (a.arg(0), if a.arg(1).is_callable() { a.arg(1) } else { Value::Null })
    } else {
        let (o, c, _) = normalize_args(vm, a.args)?;
        (o, c)
    };
    let path = getp(vm, &options, "path")?;
    if !path.is_undefined() {
        let p = string_of(vm, &path)?;
        if cb.truthy() {
            call_method(vm, &this, "once", &[Value::str("connect"), cb])?;
        }
        setp(vm, &this, "connecting", Value::Bool(true))?;
        let target = this.clone();
        let p2 = p.clone();
        crate::runtime::spawn_op(
            vm,
            move || UnixStream::connect(&p2).map_err(|e| NetErr { syscall: "connect".into(), code: errno_code(&e), address: Some(p2.clone()), port: None, custom: None }),
            move |vm: &mut Vm, r: Result<UnixStream, NetErr>| {
                let r = r.map(|s| {
                    let id = register_stream(NetStream::Unix(s));
                    (id, Value::Undefined, Value::Undefined, Value::Undefined, Value::Undefined, Value::Undefined)
                });
                connect_done(vm, target, r);
            },
        );
        return Ok(this);
    }
    let port = getp(vm, &options, "port")?;
    let pn = parse_port_option(vm, &port)?;
    let host = getp(vm, &options, "host")?;
    let host = if host.is_undefined() { "localhost".to_string() } else { string_of(vm, &host)? };
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("connect"), cb])?;
    }
    setp(vm, &this, "connecting", Value::Bool(true))?;
    let target = this.clone();
    crate::runtime::spawn_op(
        vm,
        move || -> Result<(TcpStream, Option<SocketAddr>, Option<SocketAddr>), NetErr> {
            let addrs: Vec<SocketAddr> = match (host.as_str(), pn).to_socket_addrs() {
                Ok(a) => a.collect(),
                Err(_) => return Err(NetErr { syscall: "getaddrinfo".into(), code: "ENOTFOUND".into(), address: Some(host.clone()), port: Some(pn as f64), custom: None }),
            };
            let mut last = None;
            for ad in &addrs {
                match TcpStream::connect(ad) {
                    Ok(s) => {
                        let l = s.local_addr().ok();
                        let p = s.peer_addr().ok();
                        return Ok((s, l, p));
                    }
                    Err(e) => last = Some(e),
                }
            }
            let code = last.map(|e| errno_code(&e)).unwrap_or_else(|| "ENOTFOUND".into());
            Err(NetErr { syscall: "connect".into(), code, address: Some(host.clone()), port: Some(pn as f64), custom: None })
        },
        move |vm: &mut Vm, r: Result<(TcpStream, Option<SocketAddr>, Option<SocketAddr>), NetErr>| {
            let r = r.map(|(s, l, p)| {
                let id = register_stream(NetStream::Tcp(s));
                desc_of(id, l, p)
            });
            connect_done(vm, target, r);
        },
    );
    Ok(this)
}

/// The `.then(desc => ..., err => ...)` of a connect: one microtask after completion.
fn connect_done(vm: &mut Vm, target: Value, r: Result<Desc, NetErr>) {
    match r {
        Ok(d) => {
            let arr = desc_to_array(vm, &d);
            let j = closure(vm, "", 0, connect_ok_job, vec![target, arr]);
            queue_microtask(vm, j);
        }
        Err(e) => {
            let ev = net_err_value(vm, &e);
            let j = closure(vm, "", 0, connect_err_job, vec![target, ev]);
            queue_microtask(vm, j);
        }
    }
}

fn connect_ok_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, desc) = (a.slot(0), a.slot(1));
    if getp(vm, &this, "destroyed")?.truthy() {
        let id = vm.get_prop_of(&desc, &PropKey::from_index(0))?;
        if let Value::Num(n) = id {
            close_native(n as u64);
        }
        return Ok(Value::Undefined);
    }
    call_method(vm, &this, "_adopt", &[desc])?;
    call_method(vm, &this, "_resetTimeout", &[])?;
    emit(vm, &this, "connect", &[])?;
    emit(vm, &this, "ready", &[])?;
    Ok(Value::Undefined)
}

fn connect_err_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, err) = (a.slot(0), a.slot(1));
    setp(vm, &this, "connecting", Value::Bool(false))?;
    call_method(vm, &this, "destroy", &[err])?;
    Ok(Value::Undefined)
}

fn close_native(id: u64) {
    if let Some(s) = SOCKS.with(|m| m.borrow_mut().remove(&id)) {
        s.shutdown(std::net::Shutdown::Both);
    }
}

fn sock_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (chunk, encoding, cb) = (a.arg(0), a.arg(1), a.arg(2));
    let id = match sock_id(vm, &this)? {
        Some(i) => i,
        None => {
            let e = vm.make_error("Error", "This socket has been ended by the other party");
            vm.call(&cb, Value::Undefined, &[e])?;
            return Ok(Value::Undefined);
        }
    };
    let u8c = Value::Obj(vm.intr.ta_ctors[1].clone());
    let bytes_v = if vm.instance_of(&chunk, &u8c)? {
        chunk
    } else {
        let s = string_of(vm, &chunk)?;
        let enc = if matches!(&encoding, Value::Str(s) if !s.is_empty()) { encoding } else { Value::str("utf8") };
        crate::runtime::nodestream::buffer_call(vm, "from", &[Value::str(&s), enc])?
    };
    let bytes = crate::runtime::buffer::bytes_of(vm, &bytes_v)?;
    let bw = getp(vm, &this, "bytesWritten")?;
    let nb = vm.op_add(&bw, &Value::Num(bytes.len() as f64))?;
    setp(vm, &this, "bytesWritten", nb)?;
    call_method(vm, &this, "_resetTimeout", &[])?;
    let s = SOCKS.with(|m| m.borrow().get(&id).map(|s| s.try_clone()));
    match s {
        Some(Ok(mut s)) => {
            crate::runtime::spawn_op(
                vm,
                move || s.write_all(&bytes).map_err(|e| NetErr { syscall: "write".into(), code: errno_code(&e), address: None, port: None, custom: None }),
                move |vm: &mut Vm, r: Result<(), NetErr>| {
                    let res = match r {
                        Ok(()) => vm.call(&cb, Value::Undefined, &[]),
                        Err(e) => {
                            let ev = net_err_value(vm, &e);
                            vm.call(&cb, Value::Undefined, &[ev])
                        }
                    };
                    if let Err(e) = res {
                        crate::runtime::report_uncaught(vm, &e);
                    }
                },
            );
        }
        _ => {
            let e = vm.make_error("Error", "This socket has been ended by the other party");
            vm.call(&cb, Value::Undefined, &[e])?;
        }
    }
    Ok(Value::Undefined)
}

fn sock_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if let Some(id) = sock_id(vm, &this)? {
        SOCKS.with(|m| {
            if let Some(s) = m.borrow().get(&id) {
                s.shutdown(std::net::Shutdown::Write);
            }
        });
    }
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    call_method(vm, &this, "_maybeClose", &[])?;
    Ok(Value::Undefined)
}

fn emit_close_had_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let h = getp(vm, &this, "_hadError")?;
    emit(vm, &this, "close", &[h])?;
    Ok(Value::Undefined)
}

fn sock_maybe_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "_closeEmitted")?.truthy() {
        return Ok(Value::Undefined);
    }
    let destroyed = getp(vm, &this, "destroyed")?.truthy();
    let read_done = getp(vm, &this, "_sawEof")?.truthy() || destroyed;
    let ws = getp(vm, &this, "_writableState")?;
    let write_done = getp(vm, &ws, "finished")?.truthy() || destroyed;
    if read_done && write_done {
        setp(vm, &this, "_closeEmitted", Value::Bool(true))?;
        if let Some(id) = sock_id(vm, &this)? {
            close_native(id);
        }
        setp(vm, &this, "_id", Value::Null)?;
        call_method(vm, &this, "_clearTimeout", &[])?;
        let j = closure(vm, "", 0, emit_close_had_error, vec![this]);
        queue_microtask(vm, j);
    }
    Ok(Value::Undefined)
}

fn destroy_emit_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, err) = (a.slot(0), a.slot(1));
    if err.truthy() {
        emit(vm, &this, "error", &[err])?;
    }
    let h = getp(vm, &this, "_hadError")?;
    emit(vm, &this, "close", &[h])?;
    Ok(Value::Undefined)
}

fn sock_destroy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "destroyed")?.truthy() {
        return Ok(this);
    }
    setp(vm, &this, "destroyed", Value::Bool(true))?;
    setp(vm, &this, "connecting", Value::Bool(false))?;
    let err = a.arg(0);
    if err.truthy() {
        setp(vm, &this, "_hadError", Value::Bool(true))?;
    }
    if let Some(id) = sock_id(vm, &this)? {
        close_native(id);
    }
    setp(vm, &this, "_id", Value::Null)?;
    call_method(vm, &this, "_clearTimeout", &[])?;
    setp(vm, &this, "readable", Value::Bool(false))?;
    setp(vm, &this, "writable", Value::Bool(false))?;
    let rs = getp(vm, &this, "_readableState")?;
    let ws = getp(vm, &this, "_writableState")?;
    setp(vm, &rs, "destroyed", Value::Bool(true))?;
    setp(vm, &ws, "destroyed", Value::Bool(true))?;
    if err.truthy() {
        setp(vm, &rs, "errored", err.clone())?;
        setp(vm, &ws, "errored", err.clone())?;
    }
    if !getp(vm, &this, "_closeEmitted")?.truthy() {
        setp(vm, &this, "_closeEmitted", Value::Bool(true))?;
        let j = closure(vm, "", 0, destroy_emit_job, vec![this.clone(), err]);
        queue_microtask(vm, j);
    }
    Ok(this)
}

fn sock_destroy_plain(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.this, "destroy", &[])
}

fn sock_set_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let n = vm.to_number(&a.arg(0)).unwrap_or(0.0);
    setp(vm, &this, "_timeoutMs", Value::Num(if n.is_nan() { 0.0 } else { n }))?;
    if a.arg(1).truthy() {
        call_method(vm, &this, "once", &[Value::str("timeout"), a.arg(1)])?;
    }
    call_method(vm, &this, "_resetTimeout", &[])?;
    Ok(this)
}

fn sock_clear_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = getp(vm, &a.this, "_timeoutTimer")?;
    if !t.is_null() {
        crate::runtime::timers::clear_timer_id(vm, &t);
        setp(vm, &a.this, "_timeoutTimer", Value::Null)?;
    }
    Ok(Value::Undefined)
}

fn sock_timeout_fire(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "timeout", &[])?;
    Ok(Value::Undefined)
}

fn sock_reset_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    call_method(vm, &this, "_clearTimeout", &[])?;
    let ms = getp(vm, &this, "_timeoutMs")?;
    let n = vm.to_number(&ms).unwrap_or(0.0);
    if n > 0.0 && !getp(vm, &this, "destroyed")?.truthy() {
        let f = closure(vm, "", 0, sock_timeout_fire, vec![this.clone()]);
        let id = crate::runtime::timers::add_timer(vm, f, n, Vec::new(), false);
        setp(vm, &this, "_timeoutTimer", Value::Num(id as f64))?;
    }
    Ok(Value::Undefined)
}

fn sock_set_no_delay(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let on = a.arg(0).is_undefined() || a.arg(0).truthy();
    let id = getp(vm, &a.this, "_id")?;
    if !id.is_null() {
        set_no_delay_native(vm, &id, on);
    } else {
        setp(vm, &a.this, "_pendingNoDelay", Value::Bool(on))?;
    }
    Ok(a.this.clone())
}

fn sock_set_keep_alive(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = getp(vm, &a.this, "_id")?;
    if id.is_null() {
        let en = a.arg(0).truthy();
        let d = vm.to_number(&a.arg(1)).unwrap_or(0.0);
        let arr = Value::Obj(vm.new_array(vec![Value::Bool(en), Value::Num(if d.is_nan() { 0.0 } else { d })]));
        setp(vm, &a.this, "_pendingKeepAlive", arr)?;
    }
    Ok(a.this.clone())
}

fn sock_address(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = match sock_id(vm, &a.this)? {
        Some(i) => i,
        None => return Ok(Value::Obj(vm.new_object())),
    };
    let la = SOCKS.with(|m| match m.borrow().get(&id) {
        Some(NetStream::Tcp(s)) => s.local_addr().ok(),
        _ => None,
    });
    match la {
        Some(a) => {
            let (x, p, f) = addr_strings(&a);
            Ok(Value::Obj(vm.obj_from(vec![("address", Value::str(&x)), ("family", Value::str(f)), ("port", Value::Num(p))])))
        }
        None => Ok(Value::Obj(vm.new_object())),
    }
}

fn sock_ready_state(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if getp(vm, &a.this, "connecting")?.truthy() {
        return Ok(Value::str("opening"));
    }
    let r = getp(vm, &a.this, "readable")?.truthy();
    let w = getp(vm, &a.this, "writable")?.truthy();
    Ok(Value::str(if r && w {
        "open"
    } else if r {
        "readOnly"
    } else if w {
        "writeOnly"
    } else {
        "closed"
    }))
}

// ============================================================================================
// net.Server
// ============================================================================================

fn server_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.server_proto)?;
    crate::runtime::events::init_emitter(vm, &o);
    let this = Value::Obj(o);
    let (mut options, mut listener) = (a.arg(0), a.arg(1));
    if options.is_callable() {
        listener = options;
        options = Value::Obj(vm.new_object());
    }
    if !options.truthy() {
        options = Value::Obj(vm.new_object());
    }
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "listening", Value::Bool(false))?;
    let set_ctor = vm.global.get_own_str("Set").unwrap_or(Value::Undefined);
    let conns = vm.construct(&set_ctor, &[], None)?;
    setp(vm, &this, "_connections", conns)?;
    setp(vm, &this, "_closing", Value::Bool(false))?;
    let aho = getp(vm, &options, "allowHalfOpen")?.truthy();
    setp(vm, &this, "allowHalfOpen", Value::Bool(aho))?;
    if listener.truthy() {
        call_method(vm, &this, "on", &[Value::str("connection"), listener])?;
    }
    Ok(this)
}

fn emit_error_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "error", &[a.slot(1)])?;
    Ok(Value::Undefined)
}

fn emit_listening_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "listening", &[])?;
    Ok(Value::Undefined)
}

fn listen_native(host: &str, port: u16, path: Option<&str>) -> Result<(u64, ListenerEntry), NetErr> {
    if let Some(p) = path {
        let l = UnixListener::bind(p).map_err(|e| NetErr { syscall: "listen".into(), code: errno_code(&e), address: Some(p.to_string()), port: None, custom: None })?;
        let id = next_id();
        return Ok((id, ListenerEntry { listener: Arc::new(NetListener::Unix(l)), closed: Arc::new(AtomicBool::new(false)), addr: None, path: Some(p.to_string()) }));
    }
    let h = if host.is_empty() { "0.0.0.0" } else { host };
    let addrs: Vec<SocketAddr> = (h, port)
        .to_socket_addrs()
        .map_err(|_| NetErr { syscall: "getaddrinfo".into(), code: "ENOTFOUND".into(), address: Some(h.to_string()), port: Some(port as f64), custom: None })?
        .collect();
    let mut last = None;
    for a in &addrs {
        match TcpListener::bind(a) {
            Ok(l) => {
                let addr = l.local_addr().ok();
                let id = next_id();
                return Ok((id, ListenerEntry { listener: Arc::new(NetListener::Tcp(l)), closed: Arc::new(AtomicBool::new(false)), addr, path: None }));
            }
            Err(e) => last = Some(e),
        }
    }
    let code = last.map(|e| errno_code(&e)).unwrap_or_else(|| "EADDRNOTAVAIL".into());
    Err(NetErr { syscall: "listen".into(), code, address: Some(h.to_string()), port: Some(port as f64), custom: None })
}

fn server_listen(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (options, cb) = if !a.args.is_empty() && a.arg(0).is_object() && !a.arg(0).is_callable() {
        (a.arg(0), if a.arg(1).is_callable() { a.arg(1) } else { Value::Null })
    } else {
        let (o, c, _) = normalize_args(vm, a.args)?;
        (o, c)
    };
    if getp(vm, &this, "listening")?.truthy() {
        return vm.throw_error("Error", "Server is already listening");
    }
    let pv = getp(vm, &options, "port")?;
    let port = if pv.is_undefined() { 0 } else { (vm.to_number(&pv)? as i64 as i32) as i64 };
    let hv = getp(vm, &options, "host")?;
    let host = if hv.is_undefined() { String::new() } else { string_of(vm, &hv)? };
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("listening"), cb])?;
    }
    let pathv = getp(vm, &options, "path")?;
    let path = if pathv.is_undefined() { None } else { Some(string_of(vm, &pathv)?) };
    let r = listen_native(&host, (port & 0xffff) as u16, path.as_deref());
    match r {
        Err(e) => {
            let ev = net_err_value(vm, &e);
            let j = closure(vm, "", 0, emit_error_job, vec![this.clone(), ev]);
            queue_microtask(vm, j);
            return Ok(this);
        }
        Ok((id, entry)) => {
            LISTENERS.with(|l| l.borrow_mut().insert(id, entry));
            setp(vm, &this, "_id", Value::Num(id as f64))?;
        }
    }
    setp(vm, &this, "listening", Value::Bool(true))?;
    accept_next(vm, this.clone());
    let j = closure(vm, "", 0, emit_listening_job, vec![this.clone()]);
    queue_microtask(vm, j);
    Ok(this)
}

fn server_accept_loop_method(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    accept_next(vm, a.this.clone());
    Ok(Value::Undefined)
}

enum Accepted {
    Tcp(TcpStream, Option<SocketAddr>, Option<SocketAddr>),
    Unix(UnixStream),
    Closed,
    Error(NetErr),
}

/// One iteration of the accept loop: __net.accept → (one microtask later) a Socket.
fn accept_next(vm: &mut Vm, server: Value) {
    let id = match getp(vm, &server, "_id") {
        Ok(Value::Num(n)) => n as u64,
        _ => return,
    };
    let entry = LISTENERS.with(|l| l.borrow().get(&id).map(|e| (e.listener.clone(), e.closed.clone())));
    let (listener, closed) = match entry {
        Some(x) => x,
        None => return,
    };
    crate::runtime::spawn_op(
        vm,
        move || {
            let r = match &*listener {
                NetListener::Tcp(l) => match l.accept() {
                    Ok((s, peer)) => {
                        let local = s.local_addr().ok();
                        Accepted::Tcp(s, local, Some(peer))
                    }
                    Err(e) => Accepted::Error(NetErr { syscall: "accept".into(), code: errno_code(&e), address: None, port: None, custom: None }),
                },
                NetListener::Unix(l) => match l.accept() {
                    Ok((s, _)) => Accepted::Unix(s),
                    Err(e) => Accepted::Error(NetErr { syscall: "accept".into(), code: errno_code(&e), address: None, port: None, custom: None }),
                },
            };
            if closed.load(Ordering::SeqCst) {
                return Accepted::Closed;
            }
            r
        },
        move |vm: &mut Vm, r: Accepted| {
            let desc = match r {
                Accepted::Tcp(s, l, p) => {
                    let sid = register_stream(NetStream::Tcp(s));
                    let d = desc_of(sid, l, p);
                    desc_to_array(vm, &d)
                }
                Accepted::Unix(s) => {
                    let sid = register_stream(NetStream::Unix(s));
                    Value::Obj(vm.new_array(vec![Value::Num(sid as f64)]))
                }
                Accepted::Closed => Value::Null,
                Accepted::Error(e) => {
                    let ev = net_err_value(vm, &e);
                    let j = closure(vm, "", 0, emit_error_job, vec![server.clone(), ev]);
                    queue_microtask(vm, j);
                    return;
                }
            };
            let j = closure(vm, "", 0, accept_job, vec![server.clone(), desc]);
            queue_microtask(vm, j);
        },
    );
}

fn conn_close_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (server, socket) = (a.slot(0), a.slot(1));
    let conns = getp(vm, &server, "_connections")?;
    call_method(vm, &conns, "delete", &[socket])?;
    server_maybe_emit_close(vm, &server)?;
    Ok(Value::Undefined)
}

fn accept_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (server, desc) = (a.slot(0), a.slot(1));
    if desc.is_null() || getp(vm, &server, "_id")?.is_null() {
        // like the reference, a connection accepted while the server was closing is left as is
        return Ok(Value::Undefined);
    }
    let r: JsResult<()> = (|| {
        let c = classes(vm);
        let aho = getp(vm, &server, "allowHalfOpen")?;
        let opts = Value::Obj(vm.obj_from(vec![("allowHalfOpen", aho), ("_deferRead", Value::Bool(true))]));
        let socket = vm.construct(&Value::Obj(c.socket), &[opts], None)?;
        call_method(vm, &socket, "_adopt", &[desc])?;
        let conns = getp(vm, &server, "_connections")?;
        call_method(vm, &conns, "add", &[socket.clone()])?;
        let onclose = closure(vm, "", 0, conn_close_listener, vec![server.clone(), socket.clone()]);
        call_method(vm, &socket, "on", &[Value::str("close"), onclose])?;
        emit(vm, &server, "connection", &[socket.clone()])?;
        setp(vm, &socket, "_deferRead", Value::Bool(false))?;
        pump_socket(vm, socket);
        Ok(())
    })();
    match r {
        Ok(()) => accept_next(vm, server),
        Err(e) => {
            // the accept loop's .catch: emit 'error'
            let j = closure(vm, "", 0, emit_error_job, vec![server, e]);
            queue_microtask(vm, j);
        }
    }
    Ok(Value::Undefined)
}

fn server_address(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = match getp(vm, &a.this, "_id")? {
        Value::Num(n) => n as u64,
        _ => return Ok(Value::Null),
    };
    let info = LISTENERS.with(|l| l.borrow().get(&id).map(|e| (e.addr, e.path.clone())));
    match info {
        Some((_, Some(p))) => Ok(Value::str(&p)),
        Some((Some(addr), None)) => {
            let (x, p, f) = addr_strings(&addr);
            Ok(Value::Obj(vm.obj_from(vec![("address", Value::str(&x)), ("family", Value::str(f)), ("port", Value::Num(p))])))
        }
        _ => Ok(Value::Null),
    }
}

fn server_maybe_emit_close(vm: &mut Vm, this: &Value) -> JsResult<()> {
    if getp(vm, this, "_closing")?.truthy() {
        let conns = getp(vm, this, "_connections")?;
        let size = getp(vm, &conns, "size")?;
        if matches!(size, Value::Num(n) if n == 0.0) {
            setp(vm, this, "_closing", Value::Bool(false))?;
            let j = closure(vm, "", 0, emit_close_plain_job, vec![this.clone()]);
            queue_microtask(vm, j);
        }
    }
    Ok(())
}

fn emit_close_plain_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "close", &[])?;
    Ok(Value::Undefined)
}

fn server_maybe_emit_close_method(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    server_maybe_emit_close(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn close_listener_native(id: u64) {
    let e = LISTENERS.with(|l| l.borrow_mut().remove(&id));
    if let Some(e) = e {
        e.closed.store(true, Ordering::SeqCst);
        // wake the blocking accept
        match (&*e.listener, &e.path) {
            (NetListener::Tcp(_), _) => {
                if let Some(mut addr) = e.addr {
                    if addr.ip().is_unspecified() {
                        addr.set_ip(if addr.is_ipv4() { std::net::IpAddr::from([127, 0, 0, 1]) } else { std::net::IpAddr::from([0u16, 0, 0, 0, 0, 0, 0, 1]) });
                    }
                    let _ = TcpStream::connect_timeout(&addr, std::time::Duration::from_millis(200));
                }
            }
            (NetListener::Unix(_), Some(p)) => {
                let _ = UnixStream::connect(p);
                let _ = std::fs::remove_file(p);
            }
            _ => {}
        }
    }
}

fn call_with_err_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.slot(0), Value::Undefined, &[a.slot(1)])
}

fn server_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    let id = getp(vm, &this, "_id")?;
    if id.is_null() {
        let err = error_with_code(vm, "Error", "Server is not running.", "ERR_SERVER_NOT_RUNNING");
        if cb.truthy() {
            let j = closure(vm, "", 0, call_with_err_job, vec![cb, err]);
            queue_microtask(vm, j);
        }
        return Ok(this);
    }
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("close"), cb])?;
    }
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "listening", Value::Bool(false))?;
    setp(vm, &this, "_closing", Value::Bool(true))?;
    if let Value::Num(n) = id {
        close_listener_native(n as u64);
    }
    server_maybe_emit_close(vm, &this)?;
    Ok(this)
}

fn get_connections_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let conns = getp(vm, &a.slot(1), "_connections")?;
    let size = if conns.truthy() { getp(vm, &conns, "size")? } else { Value::Num(0.0) };
    vm.call(&a.slot(0), Value::Undefined, &[Value::Null, size])
}

fn server_get_connections(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let j = closure(vm, "", 0, get_connections_job, vec![a.arg(0), a.this.clone()]);
    queue_microtask(vm, j);
    Ok(a.this.clone())
}

fn net_connect_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (options, cb) = if !a.args.is_empty() && a.arg(0).is_object() && !a.arg(0).is_callable() {
        (a.arg(0), if a.arg(1).is_callable() { a.arg(1) } else { Value::Null })
    } else {
        let (o, c, _) = normalize_args(vm, a.args)?;
        (o, c)
    };
    let c = classes(vm);
    let socket = vm.construct(&Value::Obj(c.socket), &[options.clone()], None)?;
    let cbv = if cb.truthy() { cb } else { Value::Undefined };
    call_method(vm, &socket, "connect", &[options, cbv])?;
    Ok(socket)
}

fn net_create_server(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.server), &[a.arg(0), a.arg(1)], None)
}

fn net_create_server_handle(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:net raw server handles are not supported in lumen (use net.createServer)")
}

fn create_net(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let o = vm.new_object();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    let fns: &[(&str, u32, NativeFn)] = &[("isIP", 1, net_is_ip), ("isIPv4", 1, net_is_ipv4), ("isIPv6", 1, net_is_ipv6)];
    for (n, l, f) in fns {
        let fo = plain_fn(vm, n, *l, *f);
        put(&o, n, Value::Obj(fo));
    }
    put(&o, "BlockList", Value::Obj(c.blocklist.clone()));
    put(&o, "SocketAddress", Value::Obj(c.socket_address.clone()));
    let fns2: &[(&str, u32, NativeFn)] = &[
        ("setDefaultAutoSelectFamily", 1, set_auto_select),
        ("getDefaultAutoSelectFamily", 0, get_auto_select),
        ("setDefaultAutoSelectFamilyAttemptTimeout", 1, set_auto_select_timeout),
        ("getDefaultAutoSelectFamilyAttemptTimeout", 0, get_auto_select_timeout),
        ("_normalizeArgs", 1, net_normalize_args),
        ("_setSimultaneousAccepts", 0, noop),
    ];
    for (n, l, f) in fns2 {
        let fo = plain_fn(vm, n, *l, *f);
        put(&o, n, Value::Obj(fo));
    }
    put(&o, "Socket", Value::Obj(c.socket.clone()));
    put(&o, "Server", Value::Obj(c.server.clone()));
    put(&o, "Stream", Value::Obj(c.socket.clone()));
    let connect = plain_fn(vm, "connect", 0, net_connect_fn_f);
    put(&o, "connect", Value::Obj(connect.clone()));
    put(&o, "createConnection", Value::Obj(connect));
    let cs = plain_fn(vm, "createServer", 2, net_create_server);
    put(&o, "createServer", Value::Obj(cs));
    let ch = plain_fn(vm, "_createServerHandle", 0, net_create_server_handle);
    put(&o, "_createServerHandle", Value::Obj(ch));
    Value::Obj(o)
}

// ============================================================================================
// dns
// ============================================================================================

const RESOLVE_FNS: &[(&str, &str)] = &[
    ("resolve4", "A"),
    ("resolve6", "AAAA"),
    ("resolveCname", "CNAME"),
    ("resolveNs", "NS"),
    ("resolveMx", "MX"),
    ("resolveTxt", "TXT"),
    ("resolvePtr", "PTR"),
    ("resolveSoa", "SOA"),
    ("resolveSrv", "SRV"),
    ("resolveNaptr", "NAPTR"),
    ("resolveCaa", "CAA"),
    ("resolveTlsa", "TLSA"),
    ("resolveAny", "ANY"),
];

const DNS_CODES: &[(&str, &str)] = &[
    ("NODATA", "ENODATA"),
    ("FORMERR", "EFORMERR"),
    ("SERVFAIL", "ESERVFAIL"),
    ("NOTFOUND", "ENOTFOUND"),
    ("NOTIMP", "ENOTIMP"),
    ("REFUSED", "EREFUSED"),
    ("BADQUERY", "EBADQUERY"),
    ("BADNAME", "EBADNAME"),
    ("BADFAMILY", "EBADFAMILY"),
    ("BADRESP", "EBADRESP"),
    ("CONNREFUSED", "ECONNREFUSED"),
    ("TIMEOUT", "ETIMEOUT"),
    ("EOF", "EOF"),
    ("FILE", "EFILE"),
    ("NOMEM", "ENOMEM"),
    ("DESTRUCTION", "EDESTRUCTION"),
    ("BADSTR", "EBADSTR"),
    ("BADFLAGS", "EBADFLAGS"),
    ("NONAME", "ENONAME"),
    ("BADHINTS", "EBADHINTS"),
    ("NOTINITIALIZED", "ENOTINITIALIZED"),
    ("LOADIPHLPAPI", "ELOADIPHLPAPI"),
    ("ADDRGETNETWORKPARAMS", "EADDRGETNETWORKPARAMS"),
    ("CANCELLED", "ECANCELLED"),
];

fn system_nameservers() -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(s) = std::fs::read_to_string("/etc/resolv.conf") {
        for l in s.lines() {
            let l = l.trim();
            if let Some(rest) = l.strip_prefix("nameserver") {
                let ns = rest.trim();
                if !ns.is_empty() {
                    out.push(ns.to_string());
                }
            }
        }
    }
    out
}

/// normalizeLookupOptions(options) → (family, all)
fn lookup_options(vm: &mut Vm, options: &Value) -> JsResult<(u8, bool)> {
    match options {
        Value::Num(n) => Ok((*n as u8, false)),
        Value::Obj(_) => {
            let f = getp(vm, options, "family")?;
            let fam = match &f {
                Value::Num(n) => *n as u8,
                Value::Str(s) if s.eq_str("IPv4") => 4,
                Value::Str(s) if s.eq_str("IPv6") => 6,
                _ => 0,
            };
            let all = getp(vm, options, "all")?.truthy();
            Ok((fam, all))
        }
        _ => Ok((0, false)),
    }
}

/// __dns.lookup(hostname, family) on a worker.
fn lookup_blocking(host: &str, family: u8) -> Result<Vec<(String, u8)>, String> {
    let addrs = (host, 0u16).to_socket_addrs().map_err(|e| format!("getaddrinfo {}: {}", host, e))?;
    let mut out: Vec<(String, u8)> = Vec::new();
    for a in addrs {
        let f = if a.is_ipv6() { 6 } else { 4 };
        if family != 0 && f != family {
            continue;
        }
        let s = a.ip().to_string();
        if !out.iter().any(|(x, _)| *x == s) {
            out.push((s, f));
        }
    }
    if out.is_empty() {
        return Err(format!("getaddrinfo {}: failed to lookup address information: Name or service not known", host));
    }
    Ok(out)
}

fn dns_lookup(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let hostname = a.arg(0);
    let (mut options, mut callback) = (a.arg(1), a.arg(2));
    if options.is_callable() {
        callback = options;
        options = Value::Obj(vm.new_object());
    }
    let (family, all) = lookup_options(vm, &options)?;
    let host = string_of(vm, &hostname)?;
    crate::runtime::spawn_op(
        vm,
        move || lookup_blocking(&host, family),
        move |vm: &mut Vm, r: Result<Vec<(String, u8)>, String>| {
            let res = match r {
                Ok(list) => {
                    if all {
                        let items: Vec<Value> = list.iter().map(|(a, f)| Value::Obj(vm.obj_from(vec![("address", Value::str(a)), ("family", Value::Num(*f as f64))]))).collect();
                        let arr = Value::Obj(vm.new_array(items));
                        vm.call(&callback, Value::Undefined, &[Value::Null, arr])
                    } else {
                        let (ad, f) = list[0].clone();
                        vm.call(&callback, Value::Undefined, &[Value::Null, Value::str(&ad), Value::Num(f as f64)])
                    }
                }
                Err(msg) => {
                    let e = error_with_code(vm, "Error", &msg, "EAI_FAIL");
                    vm.call(&callback, Value::Undefined, &[e])
                }
            };
            if let Err(e) = res {
                crate::runtime::report_uncaught(vm, &e);
            }
        },
    );
    Ok(Value::Undefined)
}

fn dns_lookup_service(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let addr = string_of(vm, &a.arg(0))?;
    let e = vm.make_error("Error", &format!("getnameinfo ENOTIMP {}", addr));
    if let Value::Obj(o) = &e {
        o.set_prop(key("code"), Value::str("ENOTIMP"), WEC);
        o.set_prop(key("syscall"), Value::str("getnameinfo"), WEC);
        o.set_prop(key("hostname"), Value::str(&addr), WEC);
    }
    let j = closure(vm, "", 0, call_with_err_job, vec![a.arg(2), e]);
    queue_microtask(vm, j);
    Ok(Value::Undefined)
}

fn dns_servers(vm: &mut Vm) -> Value {
    if let Some(v) = DNS_STATE.with(|d| d.borrow().1.clone()) {
        return v;
    }
    let list: Vec<Value> = system_nameservers().iter().map(|s| Value::str(s)).collect();
    Value::Obj(vm.new_array(list))
}

fn dns_get_servers(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let s = dns_servers(vm);
    call_method(vm, &s, "slice", &[])
}

fn dns_set_servers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !matches!(&a.arg(0), Value::Obj(o) if o.is_array()) {
        return vm.throw_type("The \"servers\" argument must be an instance of Array");
    }
    let copy = call_method(vm, &a.arg(0), "slice", &[])?;
    DNS_STATE.with(|d| d.borrow_mut().1 = Some(copy));
    Ok(Value::Undefined)
}

fn dns_set_order(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = string_of(vm, &a.arg(0))?;
    DNS_STATE.with(|d| d.borrow_mut().0 = s);
    Ok(Value::Undefined)
}

fn dns_get_order(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::str(&DNS_STATE.with(|d| d.borrow().0.clone())))
}

enum DnsAnswer {
    List(Vec<DnsRecord>),
    Err { message: String, code: String, syscall: Option<String> },
}

#[derive(Clone)]
enum DnsRecord {
    Text(String),
    Mx(String, u16),
    Txt(Vec<String>),
    Srv(String, u16, u16, u16),
    Soa(String, String, u32, u32, u32, u32, u32),
}

fn qtype_of(t: &str) -> Option<u16> {
    Some(match t {
        "A" => 1,
        "NS" => 2,
        "CNAME" => 5,
        "SOA" => 6,
        "PTR" => 12,
        "MX" => 15,
        "TXT" => 16,
        "AAAA" => 28,
        "SRV" => 33,
        "NAPTR" => 35,
        "CAA" => 257,
        "TLSA" => 52,
        _ => return None,
    })
}

fn read_name(msg: &[u8], mut pos: usize) -> Option<(String, usize)> {
    let mut labels = Vec::new();
    let mut jumped = false;
    let mut end = pos;
    let mut guard = 0;
    loop {
        guard += 1;
        if guard > 128 {
            return None;
        }
        let len = *msg.get(pos)? as usize;
        if len == 0 {
            if !jumped {
                end = pos + 1;
            }
            break;
        }
        if len & 0xc0 == 0xc0 {
            let off = ((len & 0x3f) << 8) | *msg.get(pos + 1)? as usize;
            if !jumped {
                end = pos + 2;
            }
            jumped = true;
            pos = off;
            continue;
        }
        let l = msg.get(pos + 1..pos + 1 + len)?;
        labels.push(String::from_utf8_lossy(l).into_owned());
        pos += 1 + len;
    }
    Some((labels.join("."), end))
}

/// A minimal DNS query over UDP to the first configured nameserver.
fn dns_query(host: &str, qtype: u16, servers: &[String]) -> DnsAnswer {
    let server = match servers.first() {
        Some(s) => s.clone(),
        None => return DnsAnswer::Err { message: "ECONNREFUSED".into(), code: "ECONNREFUSED".into(), syscall: None },
    };
    let mut q = vec![0x4c, 0x55, 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0];
    for label in host.trim_end_matches('.').split('.') {
        if label.is_empty() {
            continue;
        }
        q.push(label.len().min(63) as u8);
        q.extend_from_slice(&label.as_bytes()[..label.len().min(63)]);
    }
    q.push(0);
    q.extend_from_slice(&qtype.to_be_bytes());
    q.extend_from_slice(&[0, 1]);
    let addr = if server.contains(':') { format!("[{}]:53", server) } else { format!("{}:53", server) };
    let sock = match UdpSocket::bind(if server.contains(':') { "[::]:0" } else { "0.0.0.0:0" }) {
        Ok(s) => s,
        Err(_) => return DnsAnswer::Err { message: "ECONNREFUSED".into(), code: "ECONNREFUSED".into(), syscall: None },
    };
    let _ = sock.set_read_timeout(Some(std::time::Duration::from_secs(5)));
    if sock.send_to(&q, &addr).is_err() {
        return DnsAnswer::Err { message: "ECONNREFUSED".into(), code: "ECONNREFUSED".into(), syscall: None };
    }
    let mut buf = vec![0u8; 4096];
    let n = match sock.recv_from(&mut buf) {
        Ok((n, _)) => n,
        Err(_) => return DnsAnswer::Err { message: "ETIMEOUT".into(), code: "ETIMEOUT".into(), syscall: None },
    };
    let msg = &buf[..n];
    if msg.len() < 12 {
        return DnsAnswer::Err { message: "EBADRESP".into(), code: "EBADRESP".into(), syscall: None };
    }
    let rcode = msg[3] & 0x0f;
    match rcode {
        0 => {}
        3 => return DnsAnswer::Err { message: "NXDOMAIN".into(), code: "ENOTFOUND".into(), syscall: None },
        2 => return DnsAnswer::Err { message: "SERVFAIL".into(), code: "ESERVFAIL".into(), syscall: None },
        5 => return DnsAnswer::Err { message: "REFUSED".into(), code: "EREFUSED".into(), syscall: None },
        _ => return DnsAnswer::Err { message: "FORMERR".into(), code: "EFORMERR".into(), syscall: None },
    }
    let qd = u16::from_be_bytes([msg[4], msg[5]]) as usize;
    let an = u16::from_be_bytes([msg[6], msg[7]]) as usize;
    let mut pos = 12;
    for _ in 0..qd {
        match read_name(msg, pos) {
            Some((_, e)) => pos = e + 4,
            None => return DnsAnswer::Err { message: "EBADRESP".into(), code: "EBADRESP".into(), syscall: None },
        }
    }
    let mut out = Vec::new();
    for _ in 0..an {
        let (_, e) = match read_name(msg, pos) {
            Some(x) => x,
            None => break,
        };
        if e + 10 > msg.len() {
            break;
        }
        let t = u16::from_be_bytes([msg[e], msg[e + 1]]);
        let rdlen = u16::from_be_bytes([msg[e + 8], msg[e + 9]]) as usize;
        let rd = e + 10;
        if rd + rdlen > msg.len() {
            break;
        }
        pos = rd + rdlen;
        if t != qtype {
            continue;
        }
        let data = &msg[rd..rd + rdlen];
        match t {
            1 if rdlen == 4 => out.push(DnsRecord::Text(format!("{}.{}.{}.{}", data[0], data[1], data[2], data[3]))),
            28 if rdlen == 16 => {
                let mut b = [0u8; 16];
                b.copy_from_slice(data);
                out.push(DnsRecord::Text(std::net::Ipv6Addr::from(b).to_string()));
            }
            2 | 5 | 12 => {
                if let Some((n, _)) = read_name(msg, rd) {
                    out.push(DnsRecord::Text(n));
                }
            }
            15 if rdlen > 2 => {
                let pr = u16::from_be_bytes([data[0], data[1]]);
                if let Some((n, _)) = read_name(msg, rd + 2) {
                    out.push(DnsRecord::Mx(n, pr));
                }
            }
            16 => {
                let mut parts = Vec::new();
                let mut i = 0;
                while i < data.len() {
                    let l = data[i] as usize;
                    let end = (i + 1 + l).min(data.len());
                    parts.push(String::from_utf8_lossy(&data[i + 1..end]).into_owned());
                    i = end;
                }
                out.push(DnsRecord::Txt(parts));
            }
            33 if rdlen > 6 => {
                let pr = u16::from_be_bytes([data[0], data[1]]);
                let w = u16::from_be_bytes([data[2], data[3]]);
                let p = u16::from_be_bytes([data[4], data[5]]);
                if let Some((n, _)) = read_name(msg, rd + 6) {
                    out.push(DnsRecord::Srv(n, p, pr, w));
                }
            }
            6 => {
                if let Some((m, e1)) = read_name(msg, rd) {
                    if let Some((r, e2)) = read_name(msg, e1) {
                        if e2 + 20 <= msg.len() {
                            let g = |o: usize| u32::from_be_bytes([msg[e2 + o], msg[e2 + o + 1], msg[e2 + o + 2], msg[e2 + o + 3]]);
                            out.push(DnsRecord::Soa(m, r, g(0), g(4), g(8), g(12), g(16)));
                        }
                    }
                }
            }
            _ => {}
        }
    }
    if out.is_empty() {
        return DnsAnswer::Err { message: "ENODATA".into(), code: "ENODATA".into(), syscall: None };
    }
    DnsAnswer::List(out)
}

/// rawResolve(hostname, rrtype) on a worker.
fn raw_resolve_blocking(host: String, rrtype: String, servers: Vec<String>) -> DnsAnswer {
    match rrtype.as_str() {
        "A" | "AAAA" => {
            let fam = if rrtype == "A" { 4 } else { 6 };
            match lookup_blocking(&host, fam) {
                Ok(list) => DnsAnswer::List(list.into_iter().map(|(a, _)| DnsRecord::Text(a)).collect()),
                Err(_) => DnsAnswer::Err { message: "NXDOMAIN".into(), code: "ENOTFOUND".into(), syscall: None },
            }
        }
        t => match qtype_of(t) {
            Some(q) => dns_query(&host, q, &servers),
            None => {
                let mut cs = t.chars();
                let pretty = match cs.next() {
                    Some(f) => format!("query{}{}", f, cs.as_str().to_lowercase()),
                    None => "query".to_string(),
                };
                DnsAnswer::Err { message: format!("{} ENOTIMP {}", pretty, host), code: "ENOTIMP".into(), syscall: Some(pretty) }
            }
        },
    }
}

fn record_value(vm: &mut Vm, r: &DnsRecord) -> Value {
    match r {
        DnsRecord::Text(s) => Value::str(s),
        DnsRecord::Mx(n, p) => Value::Obj(vm.obj_from(vec![("exchange", Value::str(n)), ("priority", Value::Num(*p as f64))])),
        DnsRecord::Txt(parts) => {
            let v: Vec<Value> = parts.iter().map(|p| Value::str(p)).collect();
            Value::Obj(vm.new_array(v))
        }
        DnsRecord::Srv(n, port, pr, w) => Value::Obj(vm.obj_from(vec![("name", Value::str(n)), ("port", Value::Num(*port as f64)), ("priority", Value::Num(*pr as f64)), ("weight", Value::Num(*w as f64))])),
        DnsRecord::Soa(m, r, s, re, rt, ex, min) => Value::Obj(vm.obj_from(vec![
            ("nsname", Value::str(m)),
            ("hostmaster", Value::str(r)),
            ("serial", Value::Num(*s as f64)),
            ("refresh", Value::Num(*re as f64)),
            ("retry", Value::Num(*rt as f64)),
            ("expire", Value::Num(*ex as f64)),
            ("minttl", Value::Num(*min as f64)),
        ])),
    }
}

fn raw_resolve(vm: &mut Vm, hostname: &Value, rrtype: &str, callback: Value) -> JsResult<()> {
    let host = string_of(vm, hostname)?;
    let rr = rrtype.to_string();
    let servers = {
        let s = dns_servers(vm);
        crate::builtins::array::array_like_to_vec(vm, &s)?.into_iter().map(|v| crate::runtime::display_value(vm, &v)).collect::<Vec<_>>()
    };
    let host2 = host.clone();
    crate::runtime::spawn_op(
        vm,
        move || raw_resolve_blocking(host2, rr, servers),
        move |vm: &mut Vm, ans: DnsAnswer| {
            let res = match ans {
                DnsAnswer::List(list) => {
                    if list.len() == 1 && matches!(list[0], DnsRecord::Soa(..)) {
                        let v = record_value(vm, &list[0]);
                        vm.call(&callback, Value::Undefined, &[Value::Null, v])
                    } else {
                        let vals: Vec<Value> = list.iter().map(|r| record_value(vm, r)).collect();
                        let arr = Value::Obj(vm.new_array(vals));
                        vm.call(&callback, Value::Undefined, &[Value::Null, arr])
                    }
                }
                DnsAnswer::Err { message, code, syscall } => {
                    let e = vm.make_error("Error", &message);
                    if let Value::Obj(o) = &e {
                        o.set_prop(key("code"), Value::str(&code), WEC);
                        if let Some(s) = syscall {
                            o.set_prop(key("syscall"), Value::str(&s), WEC);
                            o.set_prop(key("hostname"), Value::str(&host), WEC);
                        }
                    }
                    vm.call(&callback, Value::Undefined, &[e])
                }
            };
            if let Err(e) = res {
                crate::runtime::report_uncaught(vm, &e);
            }
        },
    );
    Ok(())
}

fn reverse_impl(vm: &mut Vm, ip: &Value, callback: Value) -> JsResult<()> {
    let ips = string_of(vm, ip)?;
    let ip2 = ips.clone();
    crate::runtime::spawn_op(
        vm,
        move || {
            let mut names = Vec::new();
            if let Ok(s) = std::fs::read_to_string("/etc/hosts") {
                for l in s.lines() {
                    let l = l.split('#').next().unwrap_or("");
                    let mut it = l.split_whitespace();
                    if it.next() == Some(ip2.as_str()) {
                        for n in it {
                            if !names.contains(&n.to_string()) {
                                names.push(n.to_string());
                            }
                        }
                    }
                }
            }
            names
        },
        move |vm: &mut Vm, names: Vec<String>| {
            let res = if names.is_empty() {
                let e = vm.make_error("Error", &format!("getHostByAddr ENOTFOUND {}", ips));
                if let Value::Obj(o) = &e {
                    o.set_prop(key("code"), Value::str("ENOTFOUND"), WEC);
                }
                vm.call(&callback, Value::Undefined, &[e])
            } else {
                let v: Vec<Value> = names.iter().map(|n| Value::str(n)).collect();
                let arr = Value::Obj(vm.new_array(v));
                vm.call(&callback, Value::Undefined, &[Value::Null, arr])
            };
            if let Err(e) = res {
                crate::runtime::report_uncaught(vm, &e);
            }
        },
    );
    Ok(())
}

fn dns_resolve(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (mut rrtype, mut cb) = (a.arg(1), a.arg(2));
    if rrtype.is_callable() {
        cb = rrtype;
        rrtype = Value::str("A");
    }
    let t = if rrtype.is_undefined() { "A".to_string() } else { string_of(vm, &rrtype)? };
    raw_resolve(vm, &a.arg(0), &t, cb)?;
    Ok(Value::Undefined)
}

fn dns_resolve_typed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = string_of(vm, &a.slot(0))?;
    let (opts, mut cb) = (a.arg(1), a.arg(2));
    if opts.is_callable() {
        cb = opts;
    }
    raw_resolve(vm, &a.arg(0), &t, cb)?;
    Ok(Value::Undefined)
}

fn dns_reverse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    reverse_impl(vm, &a.arg(0), a.arg(1))?;
    Ok(Value::Undefined)
}

fn resolver_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.resolver_proto)?;
    let this = Value::Obj(o);
    let list: Vec<Value> = system_nameservers().iter().map(|s| Value::str(s)).collect();
    let arr = Value::Obj(vm.new_array(list));
    setp(vm, &this, "_servers", arr)?;
    let opts = if a.arg(0).truthy() { a.arg(0) } else { Value::Obj(vm.new_object()) };
    setp(vm, &this, "_options", opts)?;
    Ok(this)
}

fn resolver_get_servers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = getp(vm, &a.this, "_servers")?;
    call_method(vm, &s, "slice", &[])
}

fn resolver_set_servers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !matches!(&a.arg(0), Value::Obj(o) if o.is_array()) {
        return vm.throw_type("The \"servers\" argument must be an instance of Array");
    }
    let copy = call_method(vm, &a.arg(0), "slice", &[])?;
    setp(vm, &a.this, "_servers", copy)?;
    Ok(Value::Undefined)
}

fn resolver_resolve(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    dns_resolve(vm, a)
}

fn resolver_resolve_typed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    dns_resolve_typed(vm, a)
}

fn resolver_reverse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    dns_reverse(vm, a)
}

fn promise_resolver_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.promise_resolver_proto)?;
    let this = Value::Obj(o);
    let r = vm.construct(&Value::Obj(c.resolver), &[a.arg(0)], None)?;
    setp(vm, &this, "_resolver", r)?;
    Ok(this)
}

fn presolver_get_servers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = getp(vm, &a.this, "_resolver")?;
    call_method(vm, &r, "getServers", &[])
}

fn presolver_set_servers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = getp(vm, &a.this, "_resolver")?;
    call_method(vm, &r, "setServers", &[a.arg(0)])
}

/// promisified callback (err, ...vals) → resolve(vals.length > 1 ? vals : vals[0])
fn promisified_cb(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (res, rej) = (a.slot(0), a.slot(1));
    let err = a.arg(0);
    if err.truthy() {
        vm.call(&rej, Value::Undefined, &[err])?;
    } else {
        let vals = if a.args.len() > 1 { a.args[1..].to_vec() } else { Vec::new() };
        let v = if vals.len() > 1 { Value::Obj(vm.new_array(vals)) } else { vals.first().cloned().unwrap_or(Value::Undefined) };
        vm.call(&res, Value::Undefined, &[v])?;
    }
    Ok(Value::Undefined)
}

fn call_promisified(vm: &mut Vm, f: &Value, this: Value, args: &[Value]) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let cb = closure(vm, "", 0, promisified_cb, vec![cap.resolve.clone(), cap.reject.clone()]);
    let mut all = args.to_vec();
    all.push(cb);
    if let Err(e) = vm.call(f, this, &all) {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

fn presolver_method(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let m = string_of(vm, &a.slot(0))?;
    let r = getp(vm, &a.this, "_resolver")?;
    let f = getp(vm, &r, &m)?;
    call_promisified(vm, &f, r, a.args)
}

fn dns_promises_lookup(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (family, all) = lookup_options(vm, &a.arg(1))?;
    let host = string_of(vm, &a.arg(0))?;
    let cap = vm.new_promise_capability_intrinsic();
    let (res, rej) = (cap.resolve.clone(), cap.reject.clone());
    crate::runtime::spawn_op(
        vm,
        move || lookup_blocking(&host, family),
        move |vm: &mut Vm, r: Result<Vec<(String, u8)>, String>| {
            let _ = match r {
                Ok(list) => {
                    let v = if all {
                        let items: Vec<Value> = list.iter().map(|(a, f)| Value::Obj(vm.obj_from(vec![("address", Value::str(a)), ("family", Value::Num(*f as f64))]))).collect();
                        Value::Obj(vm.new_array(items))
                    } else {
                        let (ad, f) = list[0].clone();
                        Value::Obj(vm.obj_from(vec![("address", Value::str(&ad)), ("family", Value::Num(f as f64))]))
                    };
                    vm.call(&res, Value::Undefined, &[v])
                }
                Err(msg) => {
                    let e = error_with_code(vm, "Error", &msg, "EAI_FAIL");
                    vm.call(&rej, Value::Undefined, &[e])
                }
            };
        },
    );
    Ok(cap.promise)
}

fn dns_promises_wrap(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.slot(0);
    call_promisified(vm, &f, Value::Undefined, a.args)
}

fn create_dns(vm: &mut Vm, promises_only: bool) -> Value {
    let c = classes(vm);
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    // callback API functions
    let lookup = plain_fn(vm, "lookup", 3, dns_lookup);
    let lookup_service = plain_fn(vm, "lookupService", 3, dns_lookup_service);
    let get_servers = vm.native_fn("getServers", 0, dns_get_servers);
    let set_servers = vm.native_fn("setServers", 1, dns_set_servers);
    let set_order = vm.native_fn("setDefaultResultOrder", 1, dns_set_order);
    let get_order = vm.native_fn("getDefaultResultOrder", 0, dns_get_order);
    let resolve = vm.native_fn("bound resolve", 3, dns_resolve);
    let reverse = vm.native_fn("bound reverse", 2, dns_reverse);
    let mut typed: Vec<(&str, Obj)> = Vec::new();
    for (n, t) in RESOLVE_FNS {
        let f = vm.native_closure("bound ", 3, dns_resolve_typed, vec![Value::str(t)]);
        typed.push((n, f));
    }
    // promises object
    let p = vm.new_object();
    let pl = vm.native_fn("lookupPromise", 2, dns_promises_lookup);
    put(&p, "lookup", Value::Obj(pl));
    let pls = vm.native_closure("", 0, dns_promises_wrap, vec![Value::Obj(lookup_service.clone())]);
    put(&p, "lookupService", Value::Obj(pls));
    put(&p, "getServers", Value::Obj(get_servers.clone()));
    put(&p, "setServers", Value::Obj(set_servers.clone()));
    put(&p, "setDefaultResultOrder", Value::Obj(set_order.clone()));
    put(&p, "getDefaultResultOrder", Value::Obj(get_order.clone()));
    put(&p, "Resolver", Value::Obj(c.promise_resolver.clone()));
    for (n, code) in DNS_CODES {
        put(&p, n, Value::str(code));
    }
    let pr = vm.native_closure("", 0, dns_promises_wrap, vec![Value::Obj(resolve.clone())]);
    put(&p, "resolve", Value::Obj(pr));
    let prv = vm.native_closure("", 0, dns_promises_wrap, vec![Value::Obj(reverse.clone())]);
    put(&p, "reverse", Value::Obj(prv));
    for (n, f) in &typed {
        let w = vm.native_closure("", 0, dns_promises_wrap, vec![Value::Obj(f.clone())]);
        put(&p, n, Value::Obj(w));
    }
    if promises_only {
        return Value::Obj(p);
    }
    let o = vm.new_object();
    put(&o, "lookup", Value::Obj(lookup));
    put(&o, "lookupService", Value::Obj(lookup_service));
    put(&o, "getServers", Value::Obj(get_servers));
    put(&o, "setServers", Value::Obj(set_servers));
    put(&o, "setDefaultResultOrder", Value::Obj(set_order));
    put(&o, "getDefaultResultOrder", Value::Obj(get_order));
    put(&o, "Resolver", Value::Obj(c.resolver.clone()));
    put(&o, "resolve", Value::Obj(resolve));
    put(&o, "reverse", Value::Obj(reverse));
    for (n, f) in typed {
        put(&o, n, Value::Obj(f));
    }
    put(&o, "ADDRCONFIG", Value::Num(1024.0));
    put(&o, "ALL", Value::Num(256.0));
    put(&o, "V4MAPPED", Value::Num(2048.0));
    for (n, code) in DNS_CODES {
        put(&o, n, Value::str(code));
    }
    put(&o, "promises", Value::Obj(p));
    Value::Obj(o)
}

// ============================================================================================
// tls
// ============================================================================================

fn tls_not_supported(vm: &mut Vm) -> Value {
    vm.make_error("Error", "TLS is not supported in this build")
}

fn tls_socket_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.tls_socket_proto)?;
    let empty = Value::Obj(vm.new_object());
    crate::runtime::nodestream::duplex_init(vm, &o, &empty)?;
    let this = Value::Obj(o);
    let fields: &[(&str, Value)] = &[
        ("_id", Value::Null),
        ("connecting", Value::Bool(false)),
        ("pending", Value::Bool(true)),
        ("destroyed", Value::Bool(false)),
        ("encrypted", Value::Bool(true)),
        ("authorized", Value::Bool(false)),
        ("authorizationError", Value::Null),
        ("alpnProtocol", Value::Bool(false)),
        ("servername", Value::Undefined),
        ("remoteAddress", Value::Undefined),
        ("remotePort", Value::Undefined),
        ("localAddress", Value::Undefined),
        ("localPort", Value::Undefined),
        ("bytesRead", Value::Num(0.0)),
        ("bytesWritten", Value::Num(0.0)),
        ("_protocol", Value::Null),
        ("_cipher", Value::Null),
        ("_closeEmitted", Value::Bool(false)),
        ("_sawEof", Value::Bool(false)),
        ("_serverSide", Value::Bool(false)),
    ];
    for (k, v) in fields {
        setp(vm, &this, k, v.clone())?;
    }
    Ok(this)
}

/// _connect / _upgrade: the handshake cannot happen here; fail like a refused handshake.
fn tls_connect_method(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let options = if a.arg(0).is_object() { a.arg(0) } else { Value::Obj(vm.new_object()) };
    let cb = a.args.iter().skip(1).find(|v| v.is_callable()).cloned().unwrap_or(Value::Undefined);
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("secureConnect"), cb])?;
    }
    let host = getp(vm, &options, "host")?;
    let sn = getp(vm, &options, "servername")?;
    let name = if sn.truthy() { sn } else if host.truthy() { host } else { Value::str("localhost") };
    let name_s = string_of(vm, &name)?;
    setp(vm, &this, "servername", Value::str(&name_s))?;
    setp(vm, &this, "connecting", Value::Bool(true))?;
    let err = tls_not_supported(vm);
    let j = closure(vm, "", 0, tls_fail_job, vec![this.clone(), err]);
    queue_microtask(vm, j);
    Ok(this)
}

fn tls_fail_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    call_method(vm, &a.slot(0), "destroy", &[a.slot(1)])
}

fn tls_write(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let e = vm.make_error("Error", "TLS socket is not connected");
    vm.call(&a.arg(2), Value::Undefined, &[e])?;
    Ok(Value::Undefined)
}

fn tls_final(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    vm.call(&a.arg(0), Value::Undefined, &[])?;
    Ok(Value::Undefined)
}

fn tls_destroy_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, err) = (a.slot(0), a.slot(1));
    if err.truthy() {
        emit(vm, &this, "error", &[err.clone()])?;
    }
    emit(vm, &this, "close", &[Value::Bool(err.truthy())])?;
    Ok(Value::Undefined)
}

fn tls_destroy(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if getp(vm, &this, "destroyed")?.truthy() {
        return Ok(this);
    }
    setp(vm, &this, "destroyed", Value::Bool(true))?;
    setp(vm, &this, "connecting", Value::Bool(false))?;
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "readable", Value::Bool(false))?;
    setp(vm, &this, "writable", Value::Bool(false))?;
    if !getp(vm, &this, "_closeEmitted")?.truthy() {
        setp(vm, &this, "_closeEmitted", Value::Bool(true))?;
        let j = closure(vm, "", 0, tls_destroy_job, vec![this.clone(), a.arg(0)]);
        queue_microtask(vm, j);
    }
    Ok(this)
}

fn tls_server_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.tls_server_proto)?;
    crate::runtime::events::init_emitter(vm, &o);
    let this = Value::Obj(o);
    let (mut options, mut listener) = (a.arg(0), a.arg(1));
    if options.is_callable() {
        listener = options;
        options = Value::Obj(vm.new_object());
    }
    let opts = if options.truthy() { options } else { Value::Obj(vm.new_object()) };
    setp(vm, &this, "options", opts)?;
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "_address", Value::Null)?;
    setp(vm, &this, "listening", Value::Bool(false))?;
    let set_ctor = vm.global.get_own_str("Set").unwrap_or(Value::Undefined);
    let conns = vm.construct(&set_ctor, &[], None)?;
    setp(vm, &this, "_connections", conns)?;
    if listener.truthy() {
        call_method(vm, &this, "on", &[Value::str("secureConnection"), listener])?;
    }
    Ok(this)
}

fn tls_server_listen(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if let Some(cb) = a.args.iter().find(|v| v.is_callable()) {
        call_method(vm, &this, "once", &[Value::str("listening"), cb.clone()])?;
    }
    let options = getp(vm, &this, "options")?;
    let sc = getp(vm, &options, "secureContext")?;
    let ctx = if sc.truthy() {
        let c = getp(vm, &sc, "context")?;
        if c.truthy() {
            c
        } else {
            options.clone()
        }
    } else {
        options.clone()
    };
    let cert = getp(vm, &ctx, "cert")?;
    let keyv = getp(vm, &ctx, "key")?;
    if cert.is_nullish() || keyv.is_nullish() {
        return vm.throw_type("tls.createServer requires cert and key options");
    }
    Err(tls_not_supported(vm))
}

fn tls_server_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if a.arg(0).truthy() {
        call_method(vm, &this, "once", &[Value::str("close"), a.arg(0)])?;
    }
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "listening", Value::Bool(false))?;
    let j = closure(vm, "", 0, emit_close_plain_job, vec![this.clone()]);
    queue_microtask(vm, j);
    Ok(this)
}

fn secure_context_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let fb = vm.intr.object_proto.clone();
    let o = new_instance(vm, a, &fb)?;
    let this = Value::Obj(o);
    let copy = vm.new_object();
    if let Value::Obj(src) = &a.arg(0) {
        let keys = vm.enumerable_own_keys(src)?;
        for k in keys {
            let pk = PropKey::Str(k);
            let v = vm.get(src, &pk, &a.arg(0))?;
            copy.set_prop(pk, v, WEC);
        }
    }
    setp(vm, &this, "context", Value::Obj(copy))?;
    Ok(this)
}

fn tls_connect(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let sock = vm.construct(&Value::Obj(c.tls_socket), &[], None)?;
    let (options, cb) = if a.arg(0).is_object() && !a.arg(0).is_callable() {
        (a.arg(0), a.args.iter().skip(1).find(|v| v.is_callable()).cloned().unwrap_or(Value::Undefined))
    } else {
        let o = vm.new_object();
        if !a.arg(0).is_undefined() {
            o.set_prop(key("port"), a.arg(0), WEC);
        }
        if let Value::Str(_) = a.arg(1) {
            o.set_prop(key("host"), a.arg(1), WEC);
        }
        (Value::Obj(o), a.args.iter().find(|v| v.is_callable()).cloned().unwrap_or(Value::Undefined))
    };
    call_method(vm, &sock, "_connect", &[options, cb])
}

fn tls_create_server(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.tls_server), &[a.arg(0), a.arg(1)], None)
}

fn tls_create_secure_pair(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "tls.createSecurePair is deprecated and not supported in lumen")
}

fn tls_create_secure_context(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.secure_context), &[a.arg(0)], None)
}

fn match_hostname(host: &str, pattern: &str) -> bool {
    if let Some(rest) = pattern.strip_prefix("*.") {
        match host.find('.') {
            Some(p) => &host[p + 1..] == rest,
            None => false,
        }
    } else {
        host == pattern
    }
}

fn tls_check_server_identity(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let hostname = string_of(vm, &a.arg(0))?;
    let cert = a.arg(1);
    let mut dns_names: Vec<String> = Vec::new();
    let mut ips: Vec<String> = Vec::new();
    let san = if cert.truthy() { getp(vm, &cert, "subjectaltname")? } else { Value::Undefined };
    if san.truthy() {
        let s = string_of(vm, &san)?;
        for part in s.split(", ") {
            let idx = part.find(':').unwrap_or(part.len());
            let kind = &part[..idx];
            let val = if idx < part.len() { &part[idx + 1..] } else { "" };
            if kind == "DNS" {
                dns_names.push(val.to_string());
            } else if kind == "IP Address" {
                ips.push(val.to_string());
            }
        }
    }
    if dns_names.is_empty() && ips.is_empty() && cert.truthy() {
        let subj = getp(vm, &cert, "subject")?;
        if subj.truthy() {
            let cn = getp(vm, &subj, "CN")?;
            if cn.truthy() {
                if matches!(&cn, Value::Obj(o) if o.is_array()) {
                    for x in crate::builtins::array::array_like_to_vec(vm, &cn)? {
                        dns_names.push(string_of(vm, &x)?);
                    }
                } else {
                    dns_names.push(string_of(vm, &cn)?);
                }
            }
        }
    }
    let valid = if is_ipv4_str(&hostname) || is_ipv6_str(&hostname) {
        ips.contains(&hostname)
    } else {
        let h = hostname.to_lowercase();
        dns_names.iter().any(|n| match_hostname(&h, &n.to_lowercase()))
    };
    if valid {
        return Ok(Value::Undefined);
    }
    let alt = if san.truthy() {
        string_of(vm, &san)?
    } else {
        dns_names.iter().map(|d| format!("DNS:{}", d)).chain(ips.iter().map(|i| format!("IP Address:{}", i))).collect::<Vec<_>>().join(", ")
    };
    let reason = format!("Host: {}. is not in the cert's altnames: {}", hostname, alt);
    let err = vm.make_error("Error", &format!("Hostname/IP does not match certificate's altnames: {}", reason));
    if let Value::Obj(o) = &err {
        o.set_prop(key("name"), Value::str("Error"), WEC);
        o.set_prop(key("reason"), Value::str(&reason), WEC);
        o.set_prop(key("host"), Value::str(&hostname), WEC);
        o.set_prop(key("cert"), cert, WEC);
        o.set_prop(key("code"), Value::str("ERR_TLS_CERT_ALTNAME_INVALID"), WEC);
    }
    Ok(err)
}

fn tls_convert_alpn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (protocols, context) = (a.arg(0), a.arg(1));
    let buf = if matches!(&protocols, Value::Obj(o) if o.is_array()) {
        let mut out = Vec::new();
        for p in crate::builtins::array::array_like_to_vec(vm, &protocols)? {
            let s = string_of(vm, &p)?;
            let b = s.as_bytes();
            out.push(b.len() as u8);
            out.extend_from_slice(b);
        }
        new_buffer(vm, out)?
    } else if crate::runtime::nodestream::is_uint8_array(&protocols) {
        crate::runtime::nodestream::buffer_call(vm, "from", &[protocols])?
    } else {
        new_buffer(vm, Vec::new())?
    };
    if context.truthy() {
        setp(vm, &context, "ALPNProtocols", buf)?;
    }
    Ok(Value::Undefined)
}

const TLS_CIPHERS: &[&str] = &[
    "aes128-gcm-sha256", "aes128-sha", "aes128-sha256", "aes256-gcm-sha384", "aes256-sha", "aes256-sha256", "dhe-psk-aes128-cbc-sha", "dhe-psk-aes128-cbc-sha256",
    "dhe-psk-aes128-gcm-sha256", "dhe-psk-aes256-cbc-sha", "dhe-psk-aes256-cbc-sha384", "dhe-psk-aes256-gcm-sha384", "dhe-psk-chacha20-poly1305", "dhe-rsa-aes128-gcm-sha256",
    "dhe-rsa-aes128-sha", "dhe-rsa-aes128-sha256", "dhe-rsa-aes256-gcm-sha384", "dhe-rsa-aes256-sha", "dhe-rsa-aes256-sha256", "dhe-rsa-chacha20-poly1305",
    "ecdhe-ecdsa-aes128-gcm-sha256", "ecdhe-ecdsa-aes128-sha", "ecdhe-ecdsa-aes128-sha256", "ecdhe-ecdsa-aes256-gcm-sha384", "ecdhe-ecdsa-aes256-sha",
    "ecdhe-ecdsa-aes256-sha384", "ecdhe-ecdsa-chacha20-poly1305", "ecdhe-psk-aes128-cbc-sha", "ecdhe-psk-aes128-cbc-sha256", "ecdhe-psk-aes256-cbc-sha",
    "ecdhe-psk-aes256-cbc-sha384", "ecdhe-psk-chacha20-poly1305", "ecdhe-rsa-aes128-gcm-sha256", "ecdhe-rsa-aes128-sha", "ecdhe-rsa-aes128-sha256",
    "ecdhe-rsa-aes256-gcm-sha384", "ecdhe-rsa-aes256-sha", "ecdhe-rsa-aes256-sha384", "ecdhe-rsa-chacha20-poly1305", "psk-aes128-cbc-sha", "psk-aes128-cbc-sha256",
    "psk-aes128-gcm-sha256", "psk-aes256-cbc-sha", "psk-aes256-cbc-sha384", "psk-aes256-gcm-sha384", "psk-chacha20-poly1305", "rsa-psk-aes128-cbc-sha",
    "rsa-psk-aes128-cbc-sha256", "rsa-psk-aes128-gcm-sha256", "rsa-psk-aes256-cbc-sha", "rsa-psk-aes256-cbc-sha384", "rsa-psk-aes256-gcm-sha384",
    "rsa-psk-chacha20-poly1305", "srp-aes-128-cbc-sha", "srp-aes-256-cbc-sha", "srp-rsa-aes-128-cbc-sha", "srp-rsa-aes-256-cbc-sha", "tls_aes_128_ccm_8_sha256",
    "tls_aes_128_ccm_sha256", "tls_aes_128_gcm_sha256", "tls_aes_256_gcm_sha384", "tls_chacha20_poly1305_sha256",
];

const TLS_DEFAULT_CIPHERS: &str = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA256:DHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384:DHE-RSA-AES256-SHA384:ECDHE-RSA-AES256-SHA256:DHE-RSA-AES256-SHA256:HIGH:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!SRP:!CAMELLIA";

fn create_tls(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let o = vm.new_object();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    let f = plain_fn(vm, "connect", 0, tls_connect);
    put(&o, "connect", Value::Obj(f));
    let f = plain_fn(vm, "createServer", 2, tls_create_server);
    put(&o, "createServer", Value::Obj(f));
    put(&o, "TLSSocket", Value::Obj(c.tls_socket.clone()));
    put(&o, "Server", Value::Obj(c.tls_server.clone()));
    let f = plain_fn(vm, "createSecurePair", 0, tls_create_secure_pair);
    put(&o, "createSecurePair", Value::Obj(f));
    let f = plain_fn(vm, "createSecureContext", 1, tls_create_secure_context);
    put(&o, "createSecureContext", Value::Obj(f));
    put(&o, "SecureContext", Value::Obj(c.secure_context.clone()));
    let f = plain_fn(vm, "checkServerIdentity", 2, tls_check_server_identity);
    put(&o, "checkServerIdentity", Value::Obj(f));
    let f = plain_fn(vm, "convertALPNProtocols", 2, tls_convert_alpn);
    put(&o, "convertALPNProtocols", Value::Obj(f));
    let f = vm.native_fn("getCiphers", 0, |vm, _a| {
        let v: Vec<Value> = TLS_CIPHERS.iter().map(|s| Value::str(s)).collect();
        Ok(Value::Obj(vm.new_array(v)))
    });
    put(&o, "getCiphers", Value::Obj(f));
    let f = vm.native_fn("getCACertificates", 0, |vm, _a| Ok(Value::Obj(vm.new_array(Vec::new()))));
    put(&o, "getCACertificates", Value::Obj(f));
    let rc = vm.new_array(Vec::new());
    put(&o, "rootCertificates", Value::Obj(rc));
    put(&o, "CLIENT_RENEG_LIMIT", Value::Num(3.0));
    put(&o, "CLIENT_RENEG_WINDOW", Value::Num(600.0));
    put(&o, "DEFAULT_CIPHERS", Value::str(TLS_DEFAULT_CIPHERS));
    put(&o, "DEFAULT_ECDH_CURVE", Value::str("auto"));
    put(&o, "DEFAULT_MIN_VERSION", Value::str("TLSv1.2"));
    put(&o, "DEFAULT_MAX_VERSION", Value::str("TLSv1.3"));
    Value::Obj(o)
}

// ============================================================================================
// dgram
// ============================================================================================

struct UdpEntry {
    sock: Arc<UdpSocket>,
    closed: Arc<AtomicBool>,
}

fn dgram_err(vm: &mut Vm, msg: &str, code: &str, kind: &str) -> Value {
    error_with_code(vm, kind, msg, code)
}

fn dgram_socket_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    let o = new_instance(vm, a, &c.dgram_socket_proto)?;
    crate::runtime::events::init_emitter(vm, &o);
    let this = Value::Obj(o);
    let (ty, listener) = (a.arg(0), a.arg(1));
    let options = if matches!(ty, Value::Str(_)) { Value::Obj(vm.obj_from(vec![("type", ty.clone())])) } else { ty.clone() };
    let t = if options.truthy() { getp(vm, &options, "type")? } else { Value::Undefined };
    let ts = match &t {
        Value::Str(s) => s.to_rust_string(),
        _ => String::new(),
    };
    if ts != "udp4" && ts != "udp6" {
        return Err(dgram_err(vm, "Bad socket type specified. Valid types are: udp4, udp6", "ERR_SOCKET_BAD_TYPE", "Error"));
    }
    setp(vm, &this, "type", Value::str(&ts))?;
    setp(vm, &this, "_id", Value::Null)?;
    setp(vm, &this, "_bindState", Value::Num(0.0))?;
    setp(vm, &this, "_closed", Value::Bool(false))?;
    setp(vm, &this, "_remote", Value::Null)?;
    if listener.truthy() {
        call_method(vm, &this, "on", &[Value::str("message"), listener])?;
    }
    Ok(this)
}

fn dgram_bind(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if !matches!(getp(vm, &this, "_bindState")?, Value::Num(n) if n == 0.0) {
        return Err(dgram_err(vm, "Socket is already bound", "ERR_SOCKET_ALREADY_BOUND", "Error"));
    }
    let mut port = 0.0;
    let mut address = String::new();
    let mut cb = Value::Null;
    let first = a.arg(0);
    if first.is_object() && !first.is_callable() {
        let p = getp(vm, &first, "port")?;
        let pn = vm.to_number(&p).unwrap_or(f64::NAN);
        port = if pn.is_nan() { 0.0 } else { pn };
        let ad = getp(vm, &first, "address")?;
        if !ad.is_undefined() {
            address = string_of(vm, &ad)?;
        }
        if a.arg(1).is_callable() {
            cb = a.arg(1);
        }
    } else {
        if matches!(first, Value::Num(_) | Value::Str(_)) {
            let pn = vm.to_number(&first).unwrap_or(f64::NAN);
            port = if pn.is_nan() { 0.0 } else { pn };
        }
        if let Value::Str(s) = a.arg(1) {
            address = s.to_rust_string();
        }
        if let Some(l) = a.args.last() {
            if l.is_callable() {
                cb = l.clone();
            }
        }
    }
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("listening"), cb])?;
    }
    setp(vm, &this, "_bindState", Value::Num(1.0))?;
    let ty = getp(vm, &this, "type")?;
    let v6 = matches!(&ty, Value::Str(s) if s.eq_str("udp6"));
    let host = if address.is_empty() { if v6 { "::".to_string() } else { "0.0.0.0".to_string() } } else { address.clone() };
    let bound = (host.as_str(), port as u16).to_socket_addrs().ok().and_then(|mut it| it.find(|a| a.is_ipv6() == v6)).ok_or(()).and_then(|a| UdpSocket::bind(a).map_err(|_| ()));
    let sock = match bound {
        Ok(s) => s,
        Err(_) => {
            setp(vm, &this, "_bindState", Value::Num(0.0))?;
            let e = net_err_value(vm, &NetErr { syscall: "bind".into(), code: "EADDRINUSE".into(), address: Some(host), port: Some(port), custom: None });
            let j = closure(vm, "", 0, emit_error_job, vec![this.clone(), e]);
            queue_microtask(vm, j);
            return Ok(this);
        }
    };
    let _ = sock.set_read_timeout(Some(std::time::Duration::from_millis(100)));
    let id = next_id();
    UDPS.with(|u| u.borrow_mut().insert(id, UdpEntry { sock: Arc::new(sock), closed: Arc::new(AtomicBool::new(false)) }));
    setp(vm, &this, "_id", Value::Num(id as f64))?;
    setp(vm, &this, "_bindState", Value::Num(2.0))?;
    udp_recv_next(vm, this.clone(), id);
    let j = closure(vm, "", 0, emit_listening_job, vec![this.clone()]);
    queue_microtask(vm, j);
    Ok(this)
}

fn udp_recv_next(vm: &mut Vm, this: Value, id: u64) {
    let e = UDPS.with(|u| u.borrow().get(&id).map(|e| (e.sock.clone(), e.closed.clone())));
    let (sock, closed) = match e {
        Some(x) => x,
        None => return,
    };
    crate::runtime::spawn_op(
        vm,
        move || {
            let mut buf = vec![0u8; 65536];
            loop {
                if closed.load(Ordering::SeqCst) {
                    return None;
                }
                match sock.recv_from(&mut buf) {
                    Ok((n, from)) => {
                        buf.truncate(n);
                        return Some((buf, from));
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut || e.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(_) => return None,
                }
            }
        },
        move |vm: &mut Vm, r: Option<(Vec<u8>, SocketAddr)>| {
            let (data, from) = match r {
                Some(x) => x,
                None => return,
            };
            if getp(vm, &this, "_id").map_or(true, |v| v.is_null()) {
                return;
            }
            let size = data.len();
            let packet = new_buffer(vm, data).unwrap_or(Value::Null);
            let (ad, port, fam) = addr_strings(&from);
            let info = Value::Obj(vm.obj_from(vec![("address", Value::str(&ad)), ("family", Value::str(fam)), ("port", Value::Num(port)), ("size", Value::Num(size as f64))]));
            // `await` the recv promise, then deliver from a setTimeout(0)
            let deliver = closure(vm, "", 0, udp_deliver, vec![this.clone(), packet, info]);
            let j = closure(vm, "", 0, udp_schedule, vec![deliver]);
            queue_microtask(vm, j);
            udp_recv_next(vm, this, id);
        },
    );
}

fn udp_schedule(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    crate::runtime::timers::add_timer(vm, a.slot(0), 0.0, Vec::new(), false);
    Ok(Value::Undefined)
}

fn udp_deliver(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    if !getp(vm, &this, "_id")?.is_null() {
        emit(vm, &this, "message", &[a.slot(1), a.slot(2)])?;
    }
    Ok(Value::Undefined)
}

fn dgram_ensure_bound(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if matches!(getp(vm, &a.this, "_bindState")?, Value::Num(n) if n == 0.0) {
        call_method(vm, &a.this, "bind", &[Value::Num(0.0)])?;
    }
    Ok(Value::Undefined)
}

fn send_fail(vm: &mut Vm, cb: &Value, e: Value) -> JsResult<Value> {
    if cb.truthy() {
        let j = closure(vm, "", 0, call_with_err_job, vec![cb.clone(), e]);
        queue_microtask(vm, j);
        Ok(Value::Undefined)
    } else {
        Err(e)
    }
}

fn dgram_send(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    // normalizeSendArgs: (msg, [offset, length,] port, address, cb)
    let args: Vec<Value> = a.args.to_vec();
    let mut cb = Value::Undefined;
    let mut rest = args.clone();
    if let Some(l) = rest.last() {
        if l.is_callable() {
            cb = l.clone();
            rest.pop();
        }
    }
    let msg = rest.first().cloned().unwrap_or(Value::Undefined);
    let (offset, length, port, address) = if rest.len() >= 4 && matches!(rest.get(1), Some(Value::Num(_))) && matches!(rest.get(2), Some(Value::Num(_))) && rest.len() >= 4 {
        (rest.get(1).cloned(), rest.get(2).cloned(), rest.get(3).cloned().unwrap_or(Value::Undefined), rest.get(4).cloned().unwrap_or(Value::Undefined))
    } else {
        (None, None, rest.get(1).cloned().unwrap_or(Value::Undefined), rest.get(2).cloned().unwrap_or(Value::Undefined))
    };
    if getp(vm, &this, "_closed")?.truthy() {
        return Err(dgram_err(vm, "Not running", "ERR_SOCKET_DGRAM_NOT_RUNNING", "Error"));
    }
    // toBytes(msg, offset, length)
    let bytes: Vec<u8> = match (|| -> JsResult<Vec<u8>> {
        let parts: Vec<Value> = if matches!(&msg, Value::Obj(o) if o.is_array()) { crate::builtins::array::array_like_to_vec(vm, &msg)? } else { vec![msg.clone()] };
        let mut out = Vec::new();
        for p in parts {
            let b = match &p {
                Value::Str(_) => crate::runtime::buffer::bytes_of(vm, &p)?,
                Value::Obj(o) if matches!(o.borrow().kind, ObjKind::TypedArray(_) | ObjKind::DataView(_) | ObjKind::ArrayBuffer(_)) => crate::builtins::typedarray::ta_bytes(o),
                _ => {
                    return Err(error_with_code(vm, "TypeError", "The \"buffer\" argument must be of type string or an instance of Buffer, TypedArray, or DataView.", "ERR_INVALID_ARG_TYPE"));
                }
            };
            out.extend(b);
        }
        if let (Some(o), Some(l)) = (&offset, &length) {
            let o = vm.to_number(o)? as usize;
            let l = vm.to_number(l)? as usize;
            let end = (o + l).min(out.len());
            out = out[o.min(end)..end].to_vec();
        }
        Ok(out)
    })() {
        Ok(b) => b,
        Err(e) => return send_fail(vm, &cb, e),
    };
    let remote = getp(vm, &this, "_remote")?;
    let (dport_raw, daddr) = if remote.truthy() {
        if !port.is_undefined() {
            let e = dgram_err(vm, "Already connected", "ERR_SOCKET_DGRAM_IS_CONNECTED", "Error");
            return send_fail(vm, &cb, e);
        }
        (getp(vm, &remote, "port")?, getp(vm, &remote, "address")?)
    } else {
        (port, address)
    };
    let dport = vm.to_number(&dport_raw).unwrap_or(f64::NAN);
    if !(dport.is_finite() && dport.fract() == 0.0) || dport <= 0.0 || dport > 65535.0 {
        let d = crate::runtime::display_value(vm, &dport_raw);
        let e = dgram_err(vm, &format!("Port should be > 0 and < 65536. Received {}.", d), "ERR_SOCKET_BAD_PORT", "RangeError");
        return send_fail(vm, &cb, e);
    }
    let ty = getp(vm, &this, "type")?;
    let v6 = matches!(&ty, Value::Str(s) if s.eq_str("udp6"));
    let host = if daddr.is_undefined() || matches!(&daddr, Value::Str(s) if s.is_empty()) { if v6 { "::1".to_string() } else { "127.0.0.1".to_string() } } else { string_of(vm, &daddr)? };
    call_method(vm, &this, "_ensureBound", &[])?;
    let id = match getp(vm, &this, "_id")? {
        Value::Num(n) => n as u64,
        _ => return Ok(Value::Undefined),
    };
    let sock = UDPS.with(|u| u.borrow().get(&id).map(|e| e.sock.clone()));
    let sock = match sock {
        Some(s) => s,
        None => return Ok(Value::Undefined),
    };
    let target = this.clone();
    crate::runtime::spawn_op(
        vm,
        move || {
            let addr = (host.as_str(), dport as u16).to_socket_addrs().ok().and_then(|mut i| i.next());
            match addr {
                Some(a) => sock.send_to(&bytes, a).map_err(|e| errno_code(&e)),
                None => Err("ENOTFOUND".to_string()),
            }
        },
        move |vm: &mut Vm, r: Result<usize, String>| {
            // promise .then(): one microtask later
            let (ok, val) = match r {
                Ok(n) => (true, Value::Num(n as f64)),
                Err(code) => (false, net_err_value(vm, &NetErr { syscall: "send".into(), code, address: None, port: None, custom: None })),
            };
            let j = closure(vm, "", 0, udp_send_done, vec![target, cb, Value::Bool(ok), val]);
            queue_microtask(vm, j);
        },
    );
    Ok(Value::Undefined)
}

fn udp_send_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let (this, cb, ok, val) = (a.slot(0), a.slot(1), a.slot(2).truthy(), a.slot(3));
    if ok {
        if cb.truthy() {
            vm.call(&cb, Value::Undefined, &[Value::Null, val])?;
        }
    } else if cb.truthy() {
        vm.call(&cb, Value::Undefined, &[val])?;
    } else {
        emit(vm, &this, "error", &[val])?;
    }
    Ok(Value::Undefined)
}

fn dgram_connect(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let (port, mut address, mut cb) = (a.arg(0), a.arg(1), a.arg(2));
    if address.is_callable() {
        cb = address;
        address = Value::Undefined;
    }
    if getp(vm, &this, "_remote")?.truthy() {
        return Err(dgram_err(vm, "Already connected", "ERR_SOCKET_DGRAM_IS_CONNECTED", "Error"));
    }
    call_method(vm, &this, "_ensureBound", &[])?;
    let ty = getp(vm, &this, "type")?;
    let v6 = matches!(&ty, Value::Str(s) if s.eq_str("udp6"));
    let ad = if address.is_undefined() { if v6 { "::1".to_string() } else { "127.0.0.1".to_string() } } else { string_of(vm, &address)? };
    let pn = vm.to_number(&port).unwrap_or(f64::NAN);
    let remote = vm.obj_from(vec![("address", Value::str(&ad)), ("family", Value::str(if v6 { "IPv6" } else { "IPv4" })), ("port", Value::Num(pn))]);
    setp(vm, &this, "_remote", Value::Obj(remote))?;
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("connect"), cb])?;
    }
    let j = closure(vm, "", 0, emit_connect_job, vec![this.clone()]);
    queue_microtask(vm, j);
    Ok(this)
}

fn emit_connect_job(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    emit(vm, &a.slot(0), "connect", &[])?;
    Ok(Value::Undefined)
}

fn dgram_disconnect(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !getp(vm, &a.this, "_remote")?.truthy() {
        return Err(dgram_err(vm, "Not connected", "ERR_SOCKET_DGRAM_NOT_CONNECTED", "Error"));
    }
    setp(vm, &a.this, "_remote", Value::Null)?;
    Ok(Value::Undefined)
}

fn dgram_remote_address(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = getp(vm, &a.this, "_remote")?;
    if !r.truthy() {
        return Err(dgram_err(vm, "Not connected", "ERR_SOCKET_DGRAM_NOT_CONNECTED", "Error"));
    }
    let ad = getp(vm, &r, "address")?;
    let fam = getp(vm, &r, "family")?;
    let p = getp(vm, &r, "port")?;
    Ok(Value::Obj(vm.obj_from(vec![("address", ad), ("family", fam), ("port", p)])))
}

fn dgram_address(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let id = match getp(vm, &a.this, "_id")? {
        Value::Num(n) => n as u64,
        _ => return Err(dgram_err(vm, "getsockname EBADF", "EBADF", "Error")),
    };
    let la = UDPS.with(|u| u.borrow().get(&id).and_then(|e| e.sock.local_addr().ok()));
    match la {
        Some(addr) => {
            let (x, p, f) = addr_strings(&addr);
            Ok(Value::Obj(vm.obj_from(vec![("address", Value::str(&x)), ("family", Value::str(f)), ("port", Value::Num(p))])))
        }
        None => Err(dgram_err(vm, "getsockname EBADF", "EBADF", "Error")),
    }
}

fn dgram_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cb = a.arg(0);
    if getp(vm, &this, "_closed")?.truthy() {
        let e = dgram_err(vm, "Not running", "ERR_SOCKET_DGRAM_NOT_RUNNING", "Error");
        if cb.truthy() {
            let j = closure(vm, "", 0, call_with_err_job, vec![cb, e]);
            queue_microtask(vm, j);
            return Ok(this);
        }
        return Err(e);
    }
    if cb.truthy() {
        call_method(vm, &this, "once", &[Value::str("close"), cb])?;
    }
    setp(vm, &this, "_closed", Value::Bool(true))?;
    if let Value::Num(n) = getp(vm, &this, "_id")? {
        if let Some(e) = UDPS.with(|u| u.borrow_mut().remove(&(n as u64))) {
            e.closed.store(true, Ordering::SeqCst);
        }
    }
    setp(vm, &this, "_id", Value::Null)?;
    let j = closure(vm, "", 0, emit_close_plain_job, vec![this.clone()]);
    queue_microtask(vm, j);
    Ok(this)
}

fn dgram_check_bound(vm: &mut Vm, this: &Value, name: &str) -> JsResult<()> {
    if getp(vm, this, "_id")?.is_null() {
        return Err(dgram_err(vm, &format!("{} EBADF", name), "EBADF", "Error"));
    }
    Ok(())
}

fn dgram_set_broadcast(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    dgram_check_bound(vm, &a.this, "setBroadcast")?;
    Ok(Value::Undefined)
}

fn dgram_set_ttl(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = vm.to_number(&a.arg(0))?;
    if !(t.is_finite() && t.fract() == 0.0) || t < 1.0 || t > 255.0 {
        let d = crate::numconv::number_to_string(t);
        return Err(dgram_err(vm, &format!("The value of \"ttl\" is out of range. It must be >= 1 and <= 255. Received {}", d), "ERR_OUT_OF_RANGE", "RangeError"));
    }
    dgram_check_bound(vm, &a.this, "setTTL")?;
    Ok(Value::Num(t))
}

fn dgram_set_multicast_ttl(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = vm.to_number(&a.arg(0))?;
    if !(t.is_finite() && t.fract() == 0.0) || t < 0.0 || t > 255.0 {
        let d = crate::numconv::number_to_string(t);
        return Err(dgram_err(vm, &format!("The value of \"ttl\" is out of range. It must be >= 0 and <= 255. Received {}", d), "ERR_OUT_OF_RANGE", "RangeError"));
    }
    dgram_check_bound(vm, &a.this, "setMulticastTTL")?;
    Ok(Value::Num(t))
}

fn dgram_create_socket(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let c = classes(vm);
    vm.construct(&Value::Obj(c.dgram_socket), &[a.arg(0), a.arg(1)], None)
}

fn dgram_create_handle(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    vm.throw_error("Error", "node:dgram raw socket handles are not supported in lumen (use dgram.createSocket)")
}

fn create_dgram(vm: &mut Vm) -> Value {
    let c = classes(vm);
    let o = vm.new_object();
    o.set_prop(key("Socket"), Value::Obj(c.dgram_socket.clone()), WEC);
    let f = plain_fn(vm, "createSocket", 2, dgram_create_socket_f);
    o.set_prop(key("createSocket"), Value::Obj(f), WEC);
    let f = plain_fn(vm, "_createSocketHandle", 0, dgram_create_handle);
    o.set_prop(key("_createSocketHandle"), Value::Obj(f), WEC);
    let _ = resolved;
    Value::Obj(o)
}

#[allow(unused_variables)]
#[allow(dead_code)]
pub fn setup(vm: &mut Vm) {}

pub fn create_module(vm: &mut Vm, name: &str) -> Value {
    match name {
        "net" => create_net(vm),
        "dns" => create_dns(vm, false),
        "dns/promises" => {
            let d = match crate::runtime::node::builtin_module(vm, "dns") {
                Ok(Some(d)) => d,
                _ => return create_dns(vm, true),
            };
            getp(vm, &d, "promises").unwrap_or(Value::Undefined)
        }
        "tls" => create_tls(vm),
        "dgram" => create_dgram(vm),
        _ => Value::Obj(vm.new_object()),
    }
}

// the reference's JS frames for errors raised synchronously by these entry points
crate::framed_native!(socket_ctor_f, ["Socket"], socket_ctor);
crate::framed_native!(sock_connect_f, ["connect"], sock_connect);
crate::framed_native!(server_listen_f, ["listen"], server_listen);
crate::framed_native!(net_connect_fn_f, ["connect"], net_connect_fn);
crate::framed_native!(dgram_socket_ctor_f, ["Socket"], dgram_socket_ctor);
crate::framed_native!(dgram_create_socket_f, ["createSocket"], dgram_create_socket);
