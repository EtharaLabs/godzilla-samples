// Web platform globals (the WinterTC "minimum common API" surface of the runtime):
// DOMException, the Event family, EventTarget, AbortController/AbortSignal, message channels,
// URL/URLSearchParams/URLPattern, TextEncoder/TextDecoder, atob/btoa, structuredClone,
// Blob/File/FormData, performance/navigator, reportError/onerror, plus the node `url`,
// `querystring` and `timers/promises` modules.
//
// The reference runtime implements most of these as JavaScript classes whose state lives in
// ordinary own properties (`_listeners`, `_c`, `_list`, symbol-keyed blob bytes, ...). These
// natives mirror that observable shape: instances carry the same own properties in the same
// order, methods read their state back through ordinary property access, and errors carry the
// same types and messages.

pub mod blob;
pub mod clone;
pub mod encoding;
pub mod event;
pub mod perf;
pub mod timers_promises;
pub mod url;

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, TraceEntry, Vm};
use std::cell::RefCell;
use std::collections::HashMap;

// ---------------------------------------------------------------------------------------------
// registry of the classes created at setup (prototypes/constructors looked up by name)
// ---------------------------------------------------------------------------------------------

thread_local! {
    static REGISTRY: RefCell<HashMap<&'static str, Obj>> = RefCell::new(HashMap::new());
}

pub fn reg_set(name: &'static str, o: &Obj) {
    REGISTRY.with(|r| {
        r.borrow_mut().insert(name, o.clone());
    });
}

pub fn reg_get(name: &str) -> Option<Obj> {
    REGISTRY.with(|r| r.borrow().get(name).cloned())
}

/// Registered object (prototype or constructor); falls back to Object.prototype if missing.
pub fn reg(vm: &Vm, name: &str) -> Obj {
    reg_get(name).unwrap_or_else(|| vm.intr.object_proto.clone())
}

// ---------------------------------------------------------------------------------------------
// small helpers shared by the submodules
// ---------------------------------------------------------------------------------------------

pub fn key(s: &str) -> PropKey {
    PropKey::from_str(s)
}

/// `obj.name` on any value (throws "cannot read property 'x' of undefined" for nullish bases).
pub fn get(vm: &mut Vm, base: &Value, name: &str) -> JsResult<Value> {
    vm.get_prop_of(base, &key(name))
}

pub fn get_key(vm: &mut Vm, base: &Value, k: &PropKey) -> JsResult<Value> {
    vm.get_prop_of(base, k)
}

/// `obj.name = v` in strict-mode code.
pub fn set(vm: &mut Vm, base: &Value, name: &str, v: Value) -> JsResult<()> {
    vm.set_prop_of(base, key(name), v, true)
}

pub fn set_key(vm: &mut Vm, base: &Value, k: PropKey, v: Value) -> JsResult<()> {
    vm.set_prop_of(base, k, v, true)
}

/// `base.method(...args)`
pub fn invoke(vm: &mut Vm, base: &Value, method: &str, args: &[Value]) -> JsResult<Value> {
    let f = vm.get_prop_of(base, &key(method))?;
    if !f.is_callable() {
        let what = describe_callee(base, method);
        return vm.throw_type(format!("{} is not a function", what));
    }
    vm.call(&f, base.clone(), args)
}

fn describe_callee(_base: &Value, method: &str) -> String {
    format!("(intermediate value).{}", method)
}

/// `String(v)` (symbols become their descriptive string instead of throwing).
pub fn js_string(vm: &mut Vm, v: &Value) -> JsResult<JsStr> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        Value::Sym(s) => Ok(JsStr::from_str(&s.descriptive_string())),
        _ => vm.to_string(v),
    }
}

/// `typeof v === "object" && v !== null`
pub fn is_object_type(v: &Value) -> bool {
    matches!(v, Value::Obj(_)) && v.type_of() == "object"
}

/// A fresh ordinary object with the given (enumerable) data properties, in order.
pub fn plain(vm: &mut Vm, pairs: Vec<(&str, Value)>) -> Obj {
    vm.obj_from(pairs)
}

pub fn new_map(vm: &Vm) -> Obj {
    Obj::with_class(Some(vm.intr.map_proto.clone()), ObjKind::Map(Box::new(OrderedMap::new())), "Map")
}

pub fn array(vm: &Vm, items: Vec<Value>) -> Value {
    Value::Obj(vm.new_array(items))
}

/// Elements of an array-like value (fast path for ordinary arrays).
pub fn list_items(vm: &mut Vm, v: &Value) -> JsResult<Vec<Value>> {
    if let Value::Obj(o) = v {
        {
            let b = o.borrow();
            if let ObjKind::Array(ad) = &b.kind {
                if !ad.sparse && ad.dense.len() as u32 == ad.len && !ad.dense.iter().any(|x| x.is_empty()) {
                    return Ok(ad.dense.clone());
                }
            }
        }
        let len = vm.length_of(o)?;
        let mut out = Vec::with_capacity(len as usize);
        for i in 0..len {
            out.push(vm.get(o, &PropKey::from_index(i as u32), v)?);
        }
        return Ok(out);
    }
    let len_v = vm.get_prop_of(v, &key("length"))?;
    let len = vm.to_length(&len_v)?;
    let mut out = Vec::new();
    for i in 0..len {
        out.push(vm.get_prop_of(v, &PropKey::from_index(i as u32))?);
    }
    Ok(out)
}

/// Items of `list` for a JS-side `list.<method>(...)` call: a nullish list fails the way the
/// method lookup would (`method` = "\u{0}1" for iteration/spread).
pub fn list_for(vm: &mut Vm, list: &Value, method: &str) -> JsResult<Vec<Value>> {
    if list.is_nullish() {
        let what = if list.is_null() { "null" } else { "undefined" };
        return vm.throw_type(format!("cannot read property '{}' of {}", method, what));
    }
    if method == "\u{0}1" {
        return vm.iterate_to_vec(list);
    }
    let f = vm.get_prop_of(list, &key(method))?;
    if !f.is_callable() {
        return vm.throw_type(format!("(intermediate value).{} is not a function", method));
    }
    list_items(vm, list)
}

pub const ITER: &str = "\u{0}1";

/// `arr.push(v)` (direct for ordinary arrays)
pub fn arr_push(vm: &mut Vm, arr: &Value, v: Value) -> JsResult<()> {
    if let Value::Obj(o) = arr {
        let plain_array = matches!(&o.borrow().kind, ObjKind::Array(ad) if !ad.sparse && ad.length_writable) && o.borrow().extensible;
        if plain_array {
            crate::vm::array_push_raw(o, v);
            return Ok(());
        }
    }
    invoke(vm, arr, "push", &[v])?;
    Ok(())
}

/// `[...v]` (the reference reports spreading null/undefined as a failed Symbol.iterator read).
pub fn spread_to_vec(vm: &mut Vm, v: &Value) -> JsResult<Vec<Value>> {
    if v.is_nullish() {
        let what = if v.is_null() { "null" } else { "undefined" };
        return vm.throw_type(format!("cannot read property '\u{0}1' of {}", what));
    }
    vm.iterate_to_vec(v)
}

pub fn global_get(vm: &mut Vm, name: &str) -> JsResult<Value> {
    let g = vm.global.clone();
    vm.get(&g, &key(name), &Value::Obj(g.clone()))
}

/// Install a global the way the reference does (`globalThis.X = X`: writable, enumerable,
/// configurable).
pub fn set_global(vm: &mut Vm, name: &str, v: Value) {
    vm.global.set_prop(key(name), v, WEC);
}

/// Run `f` with an extra (native) frame named `name` on the trace, so error stacks captured
/// inside show the frame the reference's JS implementation would have.
pub fn with_frame<T>(vm: &mut Vm, name: &str, f: impl FnOnce(&mut Vm) -> JsResult<T>) -> JsResult<T> {
    vm.trace.push(TraceEntry { name: JsStr::from_str(name) });
    let r = f(vm);
    vm.trace.pop();
    r
}

/// The error a class constructor throws when called without `new`.
pub fn class_call_error<T>(vm: &mut Vm) -> JsResult<T> {
    vm.throw_type("Class constructor cannot be invoked without 'new'")
}

/// Allocate `this` for a class-like native constructor (prototype from new.target).
pub fn new_this(vm: &mut Vm, a: &Args, fallback_proto: &str) -> JsResult<Obj> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    let fb = reg(vm, fallback_proto);
    let proto = vm.proto_from_nt(&a.new_target, &fb)?;
    Ok(Obj::new(Some(proto), ObjKind::Ordinary))
}

// ---------------------------------------------------------------------------------------------
// framed natives: a trampoline pushes the frame name the reference's JS function shows in error
// stacks (`at dispatchEvent`, `at get href`, ...) around the real native. The wrapped native
// must not use `a.slot(..)` (the trampoline owns the slots).
// ---------------------------------------------------------------------------------------------

thread_local! {
    static FRAMED: RefCell<Vec<NativeFn>> = RefCell::new(Vec::new());
}

fn framed_tramp(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let idx = match a.slot(0) {
        Value::Num(n) => n as usize,
        _ => return Ok(Value::Undefined),
    };
    let f = match FRAMED.with(|t| t.borrow().get(idx).copied()) {
        Some(f) => f,
        None => return Ok(Value::Undefined),
    };
    let frame = match a.slot(1) {
        Value::Str(s) => s,
        _ => JsStr::empty(),
    };
    vm.trace.push(TraceEntry { name: frame });
    let r = f(vm, a);
    vm.trace.pop();
    r
}

/// A native function `name` whose calls show `frame` on stack traces.
pub fn framed_fn(vm: &mut Vm, name: &str, frame: &str, len: u32, f: NativeFn) -> Obj {
    let idx = FRAMED.with(|t| {
        let mut t = t.borrow_mut();
        t.push(f);
        t.len() - 1
    });
    vm.native_closure(name, len, framed_tramp, vec![Value::Num(idx as f64), Value::str(frame)])
}

/// Create a class-like constructor `name` (registered as `name` and `name.prototype`);
/// `parent` names a registered class to extend.
pub fn make_class(vm: &mut Vm, name: &'static str, proto_key: &'static str, len: u32, f: NativeFn, parent: Option<&str>) -> (Obj, Obj) {
    let parent_proto = match parent {
        Some(p) => reg_get(&format!("{}.prototype", p)).unwrap_or_else(|| vm.intr.object_proto.clone()),
        None => vm.intr.object_proto.clone(),
    };
    let proto = Obj::new(Some(parent_proto), ObjKind::Ordinary);
    let c = framed_fn(vm, name, name, len, f);
    vm.make_ctor(&c);
    c.set_prop(vm.intr.key_prototype.clone(), Value::Obj(proto.clone()), 0);
    proto.set_prop(vm.intr.key_constructor.clone(), Value::Obj(c.clone()), WC);
    if let Some(p) = parent {
        if let Some(pc) = reg_get(p) {
            c.borrow_mut().proto = Some(pc);
        }
    }
    reg_set(name, &c);
    reg_set(proto_key, &proto);
    (c, proto)
}

pub fn method(vm: &mut Vm, target: &Obj, name: &str, len: u32, f: NativeFn) -> Obj {
    let func = framed_fn(vm, name, name, len, f);
    target.set_prop(key(name), Value::Obj(func.clone()), WC);
    func
}

pub fn getter(vm: &mut Vm, target: &Obj, name: &str, f: NativeFn) -> Obj {
    let n = format!("get {}", name);
    let g = framed_fn(vm, &n, &n, 0, f);
    target.set_accessor(key(name), Some(g.clone()), None, CONFIGURABLE);
    g
}

pub fn accessor(vm: &mut Vm, target: &Obj, name: &str, g: NativeFn, s: NativeFn) {
    let gn = format!("get {}", name);
    let sn = format!("set {}", name);
    let gf = framed_fn(vm, &gn, &gn, 0, g);
    let sf = framed_fn(vm, &sn, &sn, 1, s);
    target.set_accessor(key(name), Some(gf), Some(sf), CONFIGURABLE);
}

/// An ordinary (non-class) function: constructible, with a `prototype` object.
pub fn plain_fn(vm: &mut Vm, name: &str, len: u32, f: NativeFn) -> Obj {
    plain_fn_framed(vm, name, name, len, f)
}

/// `plain_fn` whose stack frame is named `frame`.
pub fn plain_fn_framed(vm: &mut Vm, name: &str, frame: &str, len: u32, f: NativeFn) -> Obj {
    let inner = framed_fn(vm, name, frame, len, f);
    let outer = vm.native_closure(name, len, plain_fn_shim, vec![Value::Obj(inner)]);
    vm.make_ctor(&outer);
    let proto = vm.new_object();
    proto.set_prop(vm.intr.key_constructor.clone(), Value::Obj(outer.clone()), WC);
    outer.set_prop(vm.intr.key_prototype.clone(), Value::Obj(proto), WRITABLE);
    outer
}

fn plain_fn_shim(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let inner = a.slot(0);
    match &a.new_target {
        None => vm.call(&inner, a.this.clone(), a.args),
        Some(nt) => {
            let fb = vm.intr.object_proto.clone();
            let proto = vm.proto_from_nt(&Some(nt.clone()), &fb)?;
            let obj = Value::Obj(Obj::new(Some(proto), ObjKind::Ordinary));
            let r = vm.call(&inner, obj.clone(), a.args)?;
            Ok(if r.is_object() { r } else { obj })
        }
    }
}

// ---------------------------------------------------------------------------------------------
// DOMException helpers
// ---------------------------------------------------------------------------------------------

/// `new DOMException(message, name)`
pub fn dom_exception(vm: &mut Vm, message: &str, name: &str) -> Value {
    match event::construct_dom_exception(vm, None, Value::str(message), Value::str(name)) {
        Ok(v) => v,
        Err(e) => e,
    }
}

pub fn throw_dom<T>(vm: &mut Vm, message: &str, name: &str) -> JsResult<T> {
    Err(dom_exception(vm, message, name))
}

// ---------------------------------------------------------------------------------------------
// promises
// ---------------------------------------------------------------------------------------------

pub fn resolved_promise(vm: &mut Vm, v: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.resolve, Value::Undefined, &[v]);
    cap.promise
}

pub fn rejected_promise(vm: &mut Vm, e: Value) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
    cap.promise
}

/// The promise an `async` method returns for a body that already ran.
pub fn settle(vm: &mut Vm, r: JsResult<Value>) -> Value {
    match r {
        Ok(v) => resolved_promise(vm, v),
        Err(e) => rejected_promise(vm, e),
    }
}

// ---------------------------------------------------------------------------------------------
// console.error / uncaught descriptions
// ---------------------------------------------------------------------------------------------

/// `console.error(...args)` through the (possibly user-replaced) global console.
pub fn console_error(vm: &mut Vm, args: &[Value]) -> JsResult<()> {
    let console = global_get(vm, "console")?;
    invoke(vm, &console, "error", args)?;
    Ok(())
}

/// `e instanceof Error ? `${e.name}: ${e.message}` : String(e)` as used by the listener
/// error reports.
pub fn error_summary(vm: &mut Vm, e: &Value) -> JsResult<Value> {
    if let Value::Obj(_) = e {
        let ep = vm.intr.error_proto.clone();
        if has_in_chain(vm, e, &ep)? {
            let n = get(vm, e, "name")?;
            let n = vm.to_string(&n)?;
            let m = get(vm, e, "message")?;
            let m = vm.to_string(&m)?;
            return Ok(Value::str(&format!("{}: {}", n, m)));
        }
    }
    Ok(Value::Str(js_string(vm, e)?))
}

/// `v instanceof C` for an intrinsic C, i.e. `proto` on v's prototype chain.
pub fn has_in_chain(vm: &mut Vm, v: &Value, proto: &Obj) -> JsResult<bool> {
    let mut cur = match v {
        Value::Obj(o) => vm.get_prototype_of(o)?,
        _ => return Ok(false),
    };
    let mut guard = 0;
    while let Some(p) = cur {
        if p.ptr_eq(proto) {
            return Ok(true);
        }
        guard += 1;
        if guard > 100_000 {
            break;
        }
        cur = vm.get_prototype_of(&p)?;
    }
    Ok(false)
}

/// Description used by `reportError` and by uncaught exceptions from tasks:
/// `name: message` for values with a name, otherwise `String(value)`.
pub fn describe_reported(vm: &mut Vm, e: &Value) -> String {
    match e {
        Value::Obj(_) => {
            let name = match get(vm, e, "name") {
                Ok(v) => v,
                Err(_) => Value::Undefined,
            };
            if !name.is_undefined() {
                let n = crate::runtime::display_value(vm, &name);
                let msg = match get(vm, e, "message") {
                    Ok(v) => v,
                    Err(_) => Value::Undefined,
                };
                if msg.is_undefined() {
                    return n;
                }
                let m = crate::runtime::display_value(vm, &msg);
                if m.is_empty() {
                    return n;
                }
                return format!("{}: {}", n, m);
            }
            crate::runtime::display_value(vm, e)
        }
        _ => crate::runtime::display_value(vm, e),
    }
}

// ---------------------------------------------------------------------------------------------
// setup
// ---------------------------------------------------------------------------------------------

/// Installs every web global. The reference interleaves them with other modules' globals:
///   setup_core      DOMException .. URLPattern     (before ReadableStream & co)
///   setup_blob      Blob File FormData             (before Headers/Request/Response/fetch)
///   setup_platform  navigator self Performance performance   (after crypto, before WebAssembly)
///   setup_late      queueMicrotask onerror onunhandledrejection reportError   (very last)
/// `setup` runs all four in that order; a runtime wanting the reference's exact global order
/// can call the phases individually instead.
pub fn setup(vm: &mut Vm) {
    setup_core(vm);
    setup_blob(vm);
    setup_platform(vm);
    setup_late(vm);
}

/// Whether the class registered as `name` is this VM's global `name` (setup already ran).
fn installed(vm: &Vm, name: &str) -> bool {
    match (vm.global.get_own_str(name), reg_get(name)) {
        (Some(Value::Obj(g)), Some(r)) => g.ptr_eq(&r),
        _ => false,
    }
}

pub fn setup_core(vm: &mut Vm) {
    if installed(vm, "DOMException") {
        return;
    }
    event::setup(vm);
    encoding::setup(vm);
    clone::setup(vm);
    url::setup(vm);
}

pub fn setup_blob(vm: &mut Vm) {
    setup_core(vm);
    if installed(vm, "Blob") {
        return;
    }
    blob::setup(vm);
}

pub fn setup_platform(vm: &mut Vm) {
    setup_core(vm);
    if installed(vm, "Performance") {
        return;
    }
    perf::setup(vm);
}

pub fn setup_late(vm: &mut Vm) {
    setup_core(vm);
    event::setup_late(vm);
}

/// `new <Class>(...args)` for one of the web classes (e.g. "CloseEvent", "ErrorEvent",
/// "MessageEvent", "Blob", "URL") from other runtime modules.
#[allow(dead_code)]
pub fn construct_class(vm: &mut Vm, name: &str, args: &[Value]) -> JsResult<Value> {
    match reg_get(name) {
        Some(c) => {
            let cv = Value::Obj(c);
            vm.construct(&cv, args, None)
        }
        None => vm.throw_type(format!("{} is not a constructor", name)),
    }
}

pub fn create_timers_promises(vm: &mut Vm) -> Value {
    timers_promises::create_module(vm)
}

pub fn create_url_module(vm: &mut Vm) -> Value {
    url::create_url_module(vm)
}

pub fn create_querystring_module(vm: &mut Vm) -> Value {
    url::create_querystring_module(vm)
}

/// Hook for the event loop: an uncaught exception escaped a task (timer, immediate, ...).
/// Offers it to `globalThis.onerror`, and prints `Uncaught ...` unless that returned true.
pub fn report_task_error(vm: &mut Vm, e: &Value) {
    event::report_error_value(vm, e);
}

/// Hook for the event loop: a rejected promise went unhandled. Offers it to
/// `globalThis.onunhandledrejection`; returns true when the handler called `preventDefault()`.
pub fn unhandled_rejection_prevented(vm: &mut Vm, promise: &Value, reason: &Value) -> bool {
    event::fire_unhandled_rejection(vm, promise, reason)
}
