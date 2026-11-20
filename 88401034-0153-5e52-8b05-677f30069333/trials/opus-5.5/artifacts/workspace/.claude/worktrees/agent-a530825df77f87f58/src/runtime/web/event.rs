// DOMException, Event and its subclasses, EventTarget, AbortController/AbortSignal,
// MessageChannel/MessagePort, BroadcastChannel, reportError and the global error hooks.

use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;

pub fn setup(vm: &mut Vm) {
    setup_dom_exception(vm);
    setup_events(vm);
    setup_event_target(vm);
    setup_abort(vm);
    setup_event_subclasses(vm);
    setup_messaging(vm);
}

// =============================================================================================
// DOMException
// =============================================================================================

fn setup_dom_exception(vm: &mut Vm) {
    let ep = vm.intr.error_proto.clone();
    let proto = Obj::new(Some(ep), ObjKind::Ordinary);
    let c = vm.native_ctor("DOMException", 0, dom_exception_ctor, &proto);
    let error_ctor = vm.intr.error_proto.get_own_str("constructor");
    if let Some(Value::Obj(ec)) = error_ctor {
        c.borrow_mut().proto = Some(ec);
    }
    reg_set("DOMException", &c);
    reg_set("DOMException.prototype", &proto);
    set_global(vm, "DOMException", Value::Obj(c));
}

fn dom_exception_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    construct_dom_exception(vm, a.new_target.clone(), a.arg(0), a.arg(1))
}

/// `class DOMException extends Error { constructor(message = "", name = "Error") { super(message);
/// this.name = String(name); } }`
pub fn construct_dom_exception(vm: &mut Vm, nt: Option<Obj>, message: Value, name: Value) -> JsResult<Value> {
    let fb = reg(vm, "DOMException.prototype");
    let proto = vm.proto_from_nt(&nt, &fb)?;
    let message = if message.is_undefined() { Value::str("") } else { message };
    let name = if name.is_undefined() { Value::str("Error") } else { name };
    let o = with_frame(vm, "DOMException", |vm| {
        let o = Obj::with_class(Some(proto), ObjKind::Error, "Error");
        let s = vm.to_string(&message)?;
        o.set_prop(vm.intr.key_message.clone(), Value::Str(s), WC);
        vm.attach_stack(&o, "Error", "");
        Ok(o)
    })?;
    let n = js_string(vm, &name)?;
    let ov = Value::Obj(o);
    set(vm, &ov, "name", Value::Str(n))?;
    Ok(ov)
}

// =============================================================================================
// Event
// =============================================================================================

fn setup_events(vm: &mut Vm) {
    let (c, p) = make_class(vm, "Event", "Event.prototype", 1, event_ctor, None);
    method(vm, &p, "preventDefault", 0, event_prevent_default);
    method(vm, &p, "stopPropagation", 0, event_stop_propagation);
    method(vm, &p, "stopImmediatePropagation", 0, event_stop_immediate);
    for (i, n) in ["NONE", "CAPTURING_PHASE", "AT_TARGET", "BUBBLING_PHASE"].iter().enumerate() {
        c.set_prop(key(n), Value::Num(i as f64), WEC);
    }
    set_global(vm, "Event", Value::Obj(c));

    let (c, _p) = make_class(vm, "CustomEvent", "CustomEvent.prototype", 1, custom_event_ctor, Some("Event"));
    set_global(vm, "CustomEvent", Value::Obj(c));
}

fn event_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "Event.prototype")?;
    let ov = Value::Obj(o);
    event_init(vm, &ov, a.args.len(), &a.arg(0), &a.arg(1))?;
    Ok(ov)
}

/// The body of `Event`'s constructor; returns the normalized init dictionary.
fn event_init(vm: &mut Vm, this: &Value, argc: usize, ty: &Value, init: &Value) -> JsResult<Value> {
    if argc == 0 {
        return vm.throw_type("Event constructor requires a type");
    }
    let init = if init.is_undefined() { Value::Obj(vm.new_object()) } else { init.clone() };
    let init = if is_object_type(&init) { init } else { Value::Obj(vm.new_object()) };
    let t = js_string(vm, ty)?;
    set(vm, this, "type", Value::Str(t))?;
    let b = get(vm, &init, "bubbles")?.truthy();
    set(vm, this, "bubbles", Value::Bool(b))?;
    let c = get(vm, &init, "cancelable")?.truthy();
    set(vm, this, "cancelable", Value::Bool(c))?;
    let cm = get(vm, &init, "composed")?.truthy();
    set(vm, this, "composed", Value::Bool(cm))?;
    set(vm, this, "defaultPrevented", Value::Bool(false))?;
    set(vm, this, "target", Value::Null)?;
    set(vm, this, "currentTarget", Value::Null)?;
    let ev = Value::Obj(reg(vm, "Event"));
    let phase = get(vm, &ev, "AT_TARGET")?;
    set(vm, this, "eventPhase", phase)?;
    set(vm, this, "isTrusted", Value::Bool(false))?;
    let now = super::perf::perf_now();
    set(vm, this, "timeStamp", Value::Num(now))?;
    set(vm, this, "_propagationStopped", Value::Bool(false))?;
    set(vm, this, "_immediateStopped", Value::Bool(false))?;
    Ok(init)
}

fn event_prevent_default(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if get(vm, &a.this, "cancelable")?.truthy() {
        set(vm, &a.this, "defaultPrevented", Value::Bool(true))?;
    }
    Ok(Value::Undefined)
}

fn event_stop_propagation(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    set(vm, &a.this, "_propagationStopped", Value::Bool(true))?;
    Ok(Value::Undefined)
}

fn event_stop_immediate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    set(vm, &a.this, "_propagationStopped", Value::Bool(true))?;
    set(vm, &a.this, "_immediateStopped", Value::Bool(true))?;
    Ok(Value::Undefined)
}

/// `new Event(type)` from native code.
pub fn new_event(vm: &mut Vm, ty: &str) -> JsResult<Value> {
    let p = reg(vm, "Event.prototype");
    let o = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    event_init(vm, &o, 1, &Value::str(ty), &Value::Undefined)?;
    Ok(o)
}

/// `init && "key" in init`
fn init_has(vm: &mut Vm, init: &Value, k: &str) -> JsResult<bool> {
    if !init.truthy() {
        return Ok(false);
    }
    match init {
        Value::Obj(o) => vm.has_property(o, &key(k)),
        _ => vm.throw_type("'in' requires an object on the right"),
    }
}

fn custom_event_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "CustomEvent.prototype")?;
    let ov = Value::Obj(o);
    let init = if a.arg(1).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(1) };
    with_frame(vm, "Event", |vm| event_init(vm, &ov, 2, &a.arg(0), &init))?;
    let detail = if init_has(vm, &init, "detail")? { get(vm, &init, "detail")? } else { Value::Null };
    set(vm, &ov, "detail", detail)?;
    Ok(ov)
}

// ---------------------------------------------------------------------------------------------
// MessageEvent, CloseEvent, ErrorEvent, PromiseRejectionEvent
// ---------------------------------------------------------------------------------------------

fn setup_event_subclasses(vm: &mut Vm) {
    let (c, _) = make_class(vm, "MessageEvent", "MessageEvent.prototype", 1, message_event_ctor, Some("Event"));
    set_global(vm, "MessageEvent", Value::Obj(c));
    let (c, _) = make_class(vm, "CloseEvent", "CloseEvent.prototype", 1, close_event_ctor, Some("Event"));
    set_global(vm, "CloseEvent", Value::Obj(c));
    let (c, _) = make_class(vm, "ErrorEvent", "ErrorEvent.prototype", 1, error_event_ctor, Some("Event"));
    set_global(vm, "ErrorEvent", Value::Obj(c));
    let (c, _) = make_class(vm, "PromiseRejectionEvent", "PromiseRejectionEvent.prototype", 2, promise_rejection_event_ctor, Some("Event"));
    set_global(vm, "PromiseRejectionEvent", Value::Obj(c));
}

fn sub_event_init(vm: &mut Vm, this: &Value, a: &Args) -> JsResult<Value> {
    let init = if a.arg(1).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(1) };
    with_frame(vm, "Event", |vm| event_init(vm, this, 2, &a.arg(0), &init))?;
    Ok(if is_object_type(&init) { init } else { Value::Obj(vm.new_object()) })
}

fn message_event_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ov = Value::Obj(new_this(vm, a, "MessageEvent.prototype")?);
    let init = sub_event_init(vm, &ov, a)?;
    message_event_fields(vm, &ov, &init)?;
    Ok(ov)
}

fn message_event_fields(vm: &mut Vm, ov: &Value, init: &Value) -> JsResult<()> {
    let data = if init_has(vm, init, "data")? { get(vm, init, "data")? } else { Value::Null };
    set(vm, ov, "data", data)?;
    let origin = if init_has(vm, init, "origin")? {
        let v = get(vm, init, "origin")?;
        Value::Str(js_string(vm, &v)?)
    } else {
        Value::str("")
    };
    set(vm, ov, "origin", origin)?;
    let lei = if init_has(vm, init, "lastEventId")? {
        let v = get(vm, init, "lastEventId")?;
        Value::Str(js_string(vm, &v)?)
    } else {
        Value::str("")
    };
    set(vm, ov, "lastEventId", lei)?;
    let source = if init_has(vm, init, "source")? { get(vm, init, "source")? } else { Value::Null };
    set(vm, ov, "source", source)?;
    let mut ports = Vec::new();
    if init_has(vm, init, "ports")? {
        let p = get(vm, init, "ports")?;
        if p.truthy() {
            ports = vm.iterate_to_vec(&p)?;
        }
    }
    let arr = vm.new_array(ports);
    crate::builtins::object::freeze_obj(vm, &arr);
    set(vm, ov, "ports", Value::Obj(arr))?;
    Ok(())
}

/// `new MessageEvent("message", { data })` from native code.
pub fn new_message_event(vm: &mut Vm, data: Value) -> JsResult<Value> {
    let p = reg(vm, "MessageEvent.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    let init = Value::Obj(plain(vm, vec![("data", data)]));
    event_init(vm, &ov, 2, &Value::str("message"), &init)?;
    message_event_fields(vm, &ov, &init)?;
    Ok(ov)
}

fn close_event_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ov = Value::Obj(new_this(vm, a, "CloseEvent.prototype")?);
    let init = sub_event_init(vm, &ov, a)?;
    let code_v = get(vm, &init, "code")?;
    let code = vm.to_number(&code_v)?;
    let wc = get(vm, &init, "wasClean")?.truthy();
    set(vm, &ov, "wasClean", Value::Bool(wc))?;
    let code = if code.is_finite() { (vm.to_int32(&Value::Num(code))? & 0xffff) as f64 } else { 0.0 };
    set(vm, &ov, "code", Value::Num(code))?;
    let reason = if init_has(vm, &init, "reason")? {
        let v = get(vm, &init, "reason")?;
        Value::Str(js_string(vm, &v)?)
    } else {
        Value::str("")
    };
    set(vm, &ov, "reason", reason)?;
    Ok(ov)
}

/// `Number.isFinite(Number(v)) ? Number(v) >>> 0 : 0`
fn to_u32_or_zero(vm: &mut Vm, v: &Value) -> JsResult<f64> {
    let n = vm.to_number(v)?;
    if !n.is_finite() {
        return Ok(0.0);
    }
    let n2 = vm.to_number(v)?;
    Ok(vm.to_uint32(&Value::Num(n2))? as f64)
}

fn error_event_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ov = Value::Obj(new_this(vm, a, "ErrorEvent.prototype")?);
    let init = sub_event_init(vm, &ov, a)?;
    let message = if init_has(vm, &init, "message")? {
        let v = get(vm, &init, "message")?;
        Value::Str(js_string(vm, &v)?)
    } else {
        Value::str("")
    };
    set(vm, &ov, "message", message)?;
    let filename = if init_has(vm, &init, "filename")? {
        let v = get(vm, &init, "filename")?;
        Value::Str(js_string(vm, &v)?)
    } else {
        Value::str("")
    };
    set(vm, &ov, "filename", filename)?;
    let lineno = if init_has(vm, &init, "lineno")? {
        let v = get(vm, &init, "lineno")?;
        to_u32_or_zero(vm, &v)?
    } else {
        0.0
    };
    set(vm, &ov, "lineno", Value::Num(lineno))?;
    let colno = if init_has(vm, &init, "colno")? {
        let v = get(vm, &init, "colno")?;
        to_u32_or_zero(vm, &v)?
    } else {
        0.0
    };
    set(vm, &ov, "colno", Value::Num(colno))?;
    let error = if init_has(vm, &init, "error")? { get(vm, &init, "error")? } else { Value::Undefined };
    set(vm, &ov, "error", error)?;
    Ok(ov)
}

fn promise_rejection_event_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    let init = a.arg(1);
    let ok = match &init {
        Value::Obj(o) if init.type_of() == "object" => vm.has_property(o, &key("promise"))?,
        _ => false,
    };
    if !ok {
        return vm.throw_type("PromiseRejectionEvent requires an init with a promise");
    }
    let ov = Value::Obj(new_this(vm, a, "PromiseRejectionEvent.prototype")?);
    with_frame(vm, "Event", |vm| event_init(vm, &ov, 2, &a.arg(0), &init))?;
    let p = get(vm, &init, "promise")?;
    set(vm, &ov, "promise", p)?;
    let reason = if init_has(vm, &init, "reason")? { get(vm, &init, "reason")? } else { Value::Undefined };
    set(vm, &ov, "reason", reason)?;
    Ok(ov)
}

// =============================================================================================
// EventTarget
// =============================================================================================

fn setup_event_target(vm: &mut Vm) {
    let (c, p) = make_class(vm, "EventTarget", "EventTarget.prototype", 0, event_target_ctor, None);
    method(vm, &p, "addEventListener", 2, et_add_event_listener);
    method(vm, &p, "removeEventListener", 2, et_remove_event_listener);
    method(vm, &p, "dispatchEvent", 1, et_dispatch_event);
    set_global(vm, "EventTarget", Value::Obj(c));
}

fn event_target_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "EventTarget.prototype")?;
    let ov = Value::Obj(o);
    event_target_init(vm, &ov)?;
    Ok(ov)
}

fn event_target_init(vm: &mut Vm, this: &Value) -> JsResult<()> {
    let m = new_map(vm);
    set(vm, this, "_listeners", Value::Obj(m))
}

/// `options = typeof options === "boolean" ? { capture: options } : options;
///  options = options && typeof options === "object" ? options : {};`
fn normalize_listener_options(vm: &mut Vm, options: &Value) -> Value {
    let options = if options.is_undefined() { Value::Obj(vm.new_object()) } else { options.clone() };
    let options = match options {
        Value::Bool(b) => Value::Obj(plain(vm, vec![("capture", Value::Bool(b))])),
        o => o,
    };
    if options.truthy() && is_object_type(&options) {
        options
    } else {
        Value::Obj(vm.new_object())
    }
}

fn et_add_event_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let callback = a.arg(1);
    if callback.is_nullish() {
        return Ok(Value::Undefined);
    }
    let options = normalize_listener_options(vm, &a.arg(2));
    let k = Value::Str(js_string(vm, &a.arg(0))?);
    let listeners = get(vm, &this, "_listeners")?;
    let mut list = invoke(vm, &listeners, "get", &[k.clone()])?;
    if !list.truthy() {
        list = array(vm, Vec::new());
        invoke(vm, &listeners, "set", &[k.clone(), list.clone()])?;
    }
    let capture = get(vm, &options, "capture")?.truthy();
    for l in list_items(vm, &list)? {
        let cb = get(vm, &l, "callback")?;
        if Value::strict_eq(&cb, &callback) {
            let cap = get(vm, &l, "capture")?;
            if Value::strict_eq(&cap, &Value::Bool(capture)) {
                return Ok(Value::Undefined);
            }
        }
    }
    let signal = get(vm, &options, "signal")?;
    if signal.truthy() {
        let signal = get(vm, &options, "signal")?;
        if get(vm, &signal, "aborted")?.truthy() {
            return Ok(Value::Undefined);
        }
        let signal = get(vm, &options, "signal")?;
        let remover = vm.native_closure("", 0, signal_remove_listener, vec![this.clone(), k.clone(), callback.clone(), Value::Bool(capture)]);
        invoke(vm, &signal, "addEventListener", &[Value::str("abort"), Value::Obj(remover)])?;
    }
    let once = get(vm, &options, "once")?.truthy();
    let rec = plain(vm, vec![("callback", callback), ("capture", Value::Bool(capture)), ("once", Value::Bool(once)), ("removed", Value::Bool(false))]);
    arr_push(vm, &list, Value::Obj(rec))?;
    Ok(Value::Undefined)
}

/// `() => { this.removeEventListener(key, callback, { capture }); }`
fn signal_remove_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let target = a.slot(0);
    let k = a.slot(1);
    let cb = a.slot(2);
    let capture = a.slot(3);
    let opts = Value::Obj(plain(vm, vec![("capture", capture)]));
    invoke(vm, &target, "removeEventListener", &[k, cb, opts])?;
    Ok(Value::Undefined)
}

fn et_remove_event_listener(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let callback = a.arg(1);
    let options = normalize_listener_options(vm, &a.arg(2));
    let listeners = get(vm, &this, "_listeners")?;
    let k = Value::Str(js_string(vm, &a.arg(0))?);
    let list = invoke(vm, &listeners, "get", &[k])?;
    if !list.truthy() {
        return Ok(Value::Undefined);
    }
    let capture = get(vm, &options, "capture")?.truthy();
    let items = list_items(vm, &list)?;
    let mut found = None;
    for (i, l) in items.iter().enumerate() {
        let cb = get(vm, l, "callback")?;
        if Value::strict_eq(&cb, &callback) {
            let cap = get(vm, l, "capture")?;
            if Value::strict_eq(&cap, &Value::Bool(capture)) {
                found = Some(i);
                break;
            }
        }
    }
    if let Some(i) = found {
        set(vm, &items[i], "removed", Value::Bool(true))?;
        invoke(vm, &list, "splice", &[Value::Num(i as f64), Value::Num(1.0)])?;
    }
    Ok(Value::Undefined)
}

fn et_dispatch_event(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    dispatch_event(vm, &a.this, &a.arg(0))
}

pub fn dispatch_event(vm: &mut Vm, this: &Value, event: &Value) -> JsResult<Value> {
    let ev_ctor = Value::Obj(reg(vm, "Event"));
    if !vm.instance_of(event, &ev_ctor)? {
        return vm.throw_type("dispatchEvent expects an Event");
    }
    set(vm, event, "target", this.clone())?;
    set(vm, event, "currentTarget", this.clone())?;
    let listeners = get(vm, this, "_listeners")?;
    let ty = get(vm, event, "type")?;
    let list = invoke(vm, &listeners, "get", &[ty])?;
    if list.truthy() {
        let entries = vm.iterate_to_vec(&list)?;
        for entry in entries {
            if get(vm, event, "_immediateStopped")?.truthy() {
                break;
            }
            if get(vm, &entry, "removed")?.truthy() {
                continue;
            }
            if get(vm, &entry, "once")?.truthy() {
                let ty = get(vm, event, "type")?;
                let cb = get(vm, &entry, "callback")?;
                let cap = get(vm, &entry, "capture")?;
                let opts = Value::Obj(plain(vm, vec![("capture", cap)]));
                invoke(vm, this, "removeEventListener", &[ty, cb, opts])?;
            }
            let r: JsResult<()> = (|| {
                let cb = get(vm, &entry, "callback")?;
                if cb.is_callable() {
                    vm.call(&cb, this.clone(), &[event.clone()])?;
                } else if cb.truthy() {
                    let h = get(vm, &cb, "handleEvent")?;
                    if h.is_callable() {
                        let cb2 = get(vm, &entry, "callback")?;
                        invoke(vm, &cb2, "handleEvent", &[event.clone()])?;
                    }
                }
                Ok(())
            })();
            if let Err(e) = r {
                let s = error_summary(vm, &e)?;
                console_error(vm, &[Value::str("Uncaught (in event listener)"), s])?;
            }
        }
    }
    set(vm, event, "currentTarget", Value::Null)?;
    let dp = get(vm, event, "defaultPrevented")?.truthy();
    Ok(Value::Bool(!dp))
}

// =============================================================================================
// AbortSignal / AbortController
// =============================================================================================

fn setup_abort(vm: &mut Vm) {
    let (c, p) = make_class(vm, "AbortSignal", "AbortSignal.prototype", 1, abort_signal_ctor, Some("EventTarget"));
    method(vm, &p, "throwIfAborted", 0, signal_throw_if_aborted);
    method(vm, &p, "_doAbort", 1, signal_do_abort);
    method(vm, &c, "abort", 1, signal_static_abort);
    method(vm, &c, "timeout", 1, signal_static_timeout);
    let any = plain_fn(vm, "any", 1, signal_static_any);
    c.set_prop(key("any"), Value::Obj(any), WEC);
    set_global(vm, "AbortSignal", Value::Obj(c));

    let (c, p) = make_class(vm, "AbortController", "AbortController.prototype", 0, abort_controller_ctor, None);
    method(vm, &p, "abort", 1, controller_abort);
    set_global(vm, "AbortController", Value::Obj(c));
}

fn abort_signal_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    vm.throw_type("Illegal constructor")
}

/// `new AbortSignal(kSignalCreate)`
pub fn create_signal(vm: &mut Vm) -> JsResult<Value> {
    let p = reg(vm, "AbortSignal.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    event_target_init(vm, &ov)?;
    set(vm, &ov, "aborted", Value::Bool(false))?;
    set(vm, &ov, "reason", Value::Undefined)?;
    set(vm, &ov, "onabort", Value::Null)?;
    Ok(ov)
}

fn signal_throw_if_aborted(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if get(vm, &a.this, "aborted")?.truthy() {
        return Err(get(vm, &a.this, "reason")?);
    }
    Ok(Value::Undefined)
}

fn signal_do_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    do_abort(vm, &a.this, a.arg(0))?;
    Ok(Value::Undefined)
}

pub fn do_abort(vm: &mut Vm, this: &Value, reason: Value) -> JsResult<()> {
    if get(vm, this, "aborted")?.truthy() {
        return Ok(());
    }
    set(vm, this, "aborted", Value::Bool(true))?;
    let reason = if reason.is_undefined() { dom_exception(vm, "signal is aborted without reason", "AbortError") } else { reason };
    set(vm, this, "reason", reason)?;
    let event = new_event(vm, "abort")?;
    let onabort = get(vm, this, "onabort")?;
    if onabort.is_callable() {
        let h = get(vm, this, "onabort")?;
        if let Err(e) = vm.call(&h, this.clone(), &[event.clone()]) {
            let s = error_summary(vm, &e)?;
            console_error(vm, &[Value::str("Uncaught (in onabort)"), s])?;
        }
    }
    invoke(vm, this, "dispatchEvent", &[event])?;
    Ok(())
}

fn signal_static_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = create_signal(vm)?;
    invoke(vm, &s, "_doAbort", &[a.arg(0)])?;
    Ok(s)
}

/// `new AbortController()`
pub fn create_controller(vm: &mut Vm) -> JsResult<Value> {
    let p = reg(vm, "AbortController.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    let s = create_signal(vm)?;
    set(vm, &ov, "signal", s)?;
    Ok(ov)
}

fn signal_static_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let controller = create_controller(vm)?;
    let cb = vm.native_closure("", 0, timeout_fire, vec![controller.clone()]);
    let delay = if a.arg(0).is_undefined() { 0.0 } else { vm.to_number(&a.arg(0))? };
    crate::runtime::timers::add_timer(vm, Value::Obj(cb), delay, Vec::new(), false);
    get(vm, &controller, "signal")
}

fn timeout_fire(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let controller = a.slot(0);
    with_frame(vm, "<anonymous>", |vm| {
        let reason = dom_exception(vm, "signal timed out", "TimeoutError");
        invoke(vm, &controller, "abort", &[reason])?;
        Ok(Value::Undefined)
    })
}

fn signal_static_any(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = spread_to_vec(vm, &a.arg(0))?;
    let controller = create_controller(vm)?;
    for s in &list {
        if get(vm, s, "aborted")?.truthy() {
            let r = get(vm, s, "reason")?;
            invoke(vm, &controller, "abort", &[r])?;
            return get(vm, &controller, "signal");
        }
    }
    for s in &list {
        let f = vm.native_closure("", 0, any_follow, vec![controller.clone(), s.clone()]);
        let opts = Value::Obj(plain(vm, vec![("once", Value::Bool(true))]));
        invoke(vm, s, "addEventListener", &[Value::str("abort"), Value::Obj(f), opts])?;
    }
    get(vm, &controller, "signal")
}

/// `() => controller.abort(s.reason)`
fn any_follow(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let controller = a.slot(0);
    let s = a.slot(1);
    let r = get(vm, &s, "reason")?;
    invoke(vm, &controller, "abort", &[r])
}

fn abort_controller_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "AbortController.prototype")?;
    let ov = Value::Obj(o);
    let s = create_signal(vm)?;
    set(vm, &ov, "signal", s)?;
    Ok(ov)
}

fn controller_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = get(vm, &a.this, "signal")?;
    invoke(vm, &s, "_doAbort", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

// =============================================================================================
// MessageChannel / MessagePort / BroadcastChannel
// =============================================================================================

thread_local! {
    /// BroadcastChannel registry: channel name -> open channels (insertion ordered).
    static CHANNELS: RefCell<Vec<(JsStr, Vec<Obj>)>> = RefCell::new(Vec::new());
    static HANDLER_SYMS: RefCell<Option<(Sym, Sym, Sym, Sym)>> = RefCell::new(None);
}

fn setup_messaging(vm: &mut Vm) {
    let (c, p) = make_class(vm, "MessagePort", "MessagePort.prototype", 1, message_port_ctor, Some("EventTarget"));
    method(vm, &p, "postMessage", 2, port_post_message);
    method(vm, &p, "start", 0, port_start);
    method(vm, &p, "close", 0, port_close);
    method(vm, &p, "_deliver", 1, port_deliver);
    method(vm, &p, "_dispatch", 1, port_dispatch);
    define_handler(vm, &p, "message", true);
    define_handler(vm, &p, "messageerror", false);
    set_global(vm, "MessagePort", Value::Obj(c));

    let (c, _p) = make_class(vm, "MessageChannel", "MessageChannel.prototype", 0, message_channel_ctor, None);
    set_global(vm, "MessageChannel", Value::Obj(c));

    let (c, p) = make_class(vm, "BroadcastChannel", "BroadcastChannel.prototype", 1, broadcast_channel_ctor, Some("EventTarget"));
    method(vm, &p, "postMessage", 1, bc_post_message);
    method(vm, &p, "close", 0, bc_close);
    define_handler(vm, &p, "message", false);
    define_handler(vm, &p, "messageerror", false);
    set_global(vm, "BroadcastChannel", Value::Obj(c));
}

fn handler_syms(event: &str) -> (Sym, Sym) {
    HANDLER_SYMS.with(|h| {
        let mut h = h.borrow_mut();
        if h.is_none() {
            *h = Some((
                Sym::new_private(JsStr::from_str("onmessage handler")),
                Sym::new_private(JsStr::from_str("onmessage listener")),
                Sym::new_private(JsStr::from_str("onmessageerror handler")),
                Sym::new_private(JsStr::from_str("onmessageerror listener")),
            ));
        }
        let t = h.as_ref().unwrap();
        if event == "message" {
            (t.0.clone(), t.1.clone())
        } else {
            (t.2.clone(), t.3.clone())
        }
    })
}

/// `on<event>` accessor pair backed by per-object handler/listener slots.
fn define_handler(vm: &mut Vm, proto: &Obj, event: &str, start_after_set: bool) {
    let ev = Value::str(event);
    let g = vm.native_closure("get", 0, handler_get, vec![ev.clone()]);
    let s = vm.native_closure("set", 1, handler_set, vec![ev, Value::Bool(start_after_set)]);
    proto.set_accessor(key(&format!("on{}", event)), Some(g), Some(s), CONFIGURABLE);
}

fn hidden_get(o: &Value, sym: &Sym) -> Option<Value> {
    match o {
        Value::Obj(ob) => ob.get_own_data(&PropKey::Sym(sym.clone())),
        _ => None,
    }
}

fn hidden_set(o: &Value, sym: &Sym, v: Option<Value>) {
    if let Value::Obj(ob) = o {
        let k = PropKey::Sym(sym.clone());
        match v {
            Some(v) => ob.set_prop(k, v, WC),
            None => {
                ob.borrow_mut().props.remove(&k);
            }
        }
    }
}

fn handler_get(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = a.slot(0);
    let evs = match &ev {
        Value::Str(s) => s.to_rust_string(),
        _ => String::new(),
    };
    let (hs, _) = handler_syms(&evs);
    Ok(hidden_get(&a.this, &hs).unwrap_or(Value::Null))
}

fn handler_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ev = a.slot(0);
    let start_after = a.slot(1).truthy();
    let evs = match &ev {
        Value::Str(s) => s.to_rust_string(),
        _ => String::new(),
    };
    let (hs, ls) = handler_syms(&evs);
    let this = a.this.clone();
    let f = a.arg(0);
    if let Some(old) = hidden_get(&this, &ls) {
        invoke(vm, &this, "removeEventListener", &[ev.clone(), old])?;
    }
    if f.is_callable() {
        hidden_set(&this, &hs, Some(f.clone()));
        let wrapped = vm.native_closure("", 1, handler_wrapper, vec![f, this.clone()]);
        hidden_set(&this, &ls, Some(Value::Obj(wrapped.clone())));
        invoke(vm, &this, "addEventListener", &[ev, Value::Obj(wrapped)])?;
    } else {
        hidden_set(&this, &hs, None);
        hidden_set(&this, &ls, None);
    }
    if start_after {
        invoke(vm, &this, "start", &[])?;
    }
    Ok(Value::Undefined)
}

/// `(e) => fn.call(this, e)`
fn handler_wrapper(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.slot(0);
    let this = a.slot(1);
    vm.call(&f, this, &[a.arg(0)])
}

fn message_port_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    vm.throw_type("Illegal constructor")
}

/// `new MessagePort(kPortCreate)`
fn create_port(vm: &mut Vm) -> JsResult<Value> {
    let p = reg(vm, "MessagePort.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    event_target_init(vm, &ov)?;
    set(vm, &ov, "_other", Value::Null)?;
    let q = array(vm, Vec::new());
    set(vm, &ov, "_queue", q)?;
    set(vm, &ov, "_started", Value::Bool(false))?;
    set(vm, &ov, "_closed", Value::Bool(false))?;
    Ok(ov)
}

fn port_post_message(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "_closed")?.truthy() {
        return Ok(Value::Undefined);
    }
    let options = a.arg(1);
    let is_arr = crate::builtins::array::is_array(vm, &options)?;
    let transfer = if is_arr {
        options.clone()
    } else if options.truthy() && is_object_type(&options) && get(vm, &options, "transfer")?.truthy() {
        get(vm, &options, "transfer")?
    } else {
        array(vm, Vec::new())
    };
    let _ = get(vm, &transfer, "length")?;
    let data = super::clone::structured_clone(vm, &a.arg(0))?;
    let target = get(vm, &this, "_other")?;
    if !target.truthy() || get(vm, &target, "_closed")?.truthy() {
        return Ok(Value::Undefined);
    }
    let cb = vm.native_closure("", 0, port_deliver_task, vec![target, data]);
    crate::runtime::timers::add_timer(vm, Value::Obj(cb), 0.0, Vec::new(), false);
    Ok(Value::Undefined)
}

/// `() => target._deliver(data)`
fn port_deliver_task(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let target = a.slot(0);
    let data = a.slot(1);
    invoke(vm, &target, "_deliver", &[data])
}

fn port_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "_started")?.truthy() || get(vm, &this, "_closed")?.truthy() {
        return Ok(Value::Undefined);
    }
    set(vm, &this, "_started", Value::Bool(true))?;
    let q = get(vm, &this, "_queue")?;
    let queued = invoke(vm, &q, "splice", &[Value::Num(0.0)])?;
    for data in vm.iterate_to_vec(&queued)? {
        let cb = vm.native_closure("", 0, port_dispatch_task, vec![this.clone(), data]);
        crate::runtime::timers::add_timer(vm, Value::Obj(cb), 0.0, Vec::new(), false);
    }
    Ok(Value::Undefined)
}

/// `() => this._dispatch(data)`
fn port_dispatch_task(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let port = a.slot(0);
    let data = a.slot(1);
    invoke(vm, &port, "_dispatch", &[data])
}

fn port_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    set(vm, &this, "_closed", Value::Bool(true))?;
    let other = get(vm, &this, "_other")?;
    if other.truthy() {
        let other = get(vm, &this, "_other")?;
        set(vm, &other, "_other", Value::Null)?;
    }
    set(vm, &this, "_other", Value::Null)?;
    Ok(Value::Undefined)
}

fn port_deliver(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "_closed")?.truthy() {
        return Ok(Value::Undefined);
    }
    if !get(vm, &this, "_started")?.truthy() {
        let q = get(vm, &this, "_queue")?;
        arr_push(vm, &q, a.arg(0))?;
        return Ok(Value::Undefined);
    }
    invoke(vm, &this, "_dispatch", &[a.arg(0)])?;
    Ok(Value::Undefined)
}

fn port_dispatch(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "_closed")?.truthy() {
        return Ok(Value::Undefined);
    }
    let ev = new_message_event(vm, a.arg(0))?;
    invoke(vm, &this, "dispatchEvent", &[ev])?;
    Ok(Value::Undefined)
}

fn message_channel_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "MessageChannel.prototype")?;
    let ov = Value::Obj(o);
    let p1 = create_port(vm)?;
    let p2 = create_port(vm)?;
    set(vm, &p1, "_other", p2.clone())?;
    set(vm, &p2, "_other", p1.clone())?;
    set(vm, &ov, "port1", p1)?;
    set(vm, &ov, "port2", p2)?;
    Ok(ov)
}

fn broadcast_channel_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return class_call_error(vm);
    }
    if a.args.is_empty() {
        return vm.throw_type("BroadcastChannel requires a name");
    }
    let o = new_this(vm, a, "BroadcastChannel.prototype")?;
    let ov = Value::Obj(o.clone());
    event_target_init(vm, &ov)?;
    let name = js_string(vm, &a.arg(0))?;
    set(vm, &ov, "name", Value::Str(name))?;
    set(vm, &ov, "_closed", Value::Bool(false))?;
    let n = get(vm, &ov, "name")?;
    let n = js_string(vm, &n)?;
    CHANNELS.with(|c| {
        let mut c = c.borrow_mut();
        match c.iter_mut().find(|(k, _)| *k == n) {
            Some((_, set)) => {
                if !set.iter().any(|x| x.ptr_eq(&o)) {
                    set.push(o.clone());
                }
            }
            None => c.push((n, vec![o.clone()])),
        }
    });
    Ok(ov)
}

fn bc_post_message(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    if get(vm, &this, "_closed")?.truthy() {
        return throw_dom(vm, "BroadcastChannel is closed", "InvalidStateError");
    }
    let data = super::clone::structured_clone(vm, &a.arg(0))?;
    let n = get(vm, &this, "name")?;
    let n = js_string(vm, &n)?;
    let members: Vec<Obj> = CHANNELS.with(|c| c.borrow().iter().find(|(k, _)| *k == n).map(|(_, s)| s.clone()).unwrap_or_default());
    let mut peers = Vec::new();
    for m in members {
        let mv = Value::Obj(m.clone());
        if let Value::Obj(t) = &this {
            if t.ptr_eq(&m) {
                continue;
            }
        }
        if get(vm, &mv, "_closed")?.truthy() {
            continue;
        }
        peers.push(mv);
    }
    let peers = array(vm, peers);
    let cb = vm.native_closure("", 0, bc_deliver_task, vec![peers, data]);
    crate::runtime::timers::add_timer(vm, Value::Obj(cb), 0.0, Vec::new(), false);
    Ok(Value::Undefined)
}

fn bc_deliver_task(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let peers = a.slot(0);
    let data = a.slot(1);
    with_frame(vm, "<anonymous>", |vm| {
        for peer in list_items(vm, &peers)? {
            if get(vm, &peer, "_closed")?.truthy() {
                continue;
            }
            let d = super::clone::structured_clone(vm, &data)?;
            let ev = with_frame(vm, "MessageEvent", |vm| new_message_event(vm, d))?;
            invoke(vm, &peer, "dispatchEvent", &[ev])?;
        }
        Ok(Value::Undefined)
    })
}

fn bc_close(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    set(vm, &this, "_closed", Value::Bool(true))?;
    let n = get(vm, &this, "name")?;
    let n = js_string(vm, &n)?;
    if let Value::Obj(o) = &this {
        CHANNELS.with(|c| {
            let mut c = c.borrow_mut();
            if let Some(pos) = c.iter().position(|(k, _)| *k == n) {
                c[pos].1.retain(|x| !x.ptr_eq(o));
                if c[pos].1.is_empty() {
                    c.remove(pos);
                }
            }
        });
    }
    Ok(Value::Undefined)
}

// =============================================================================================
// reportError / onerror / onunhandledrejection / queueMicrotask
// =============================================================================================

pub fn setup_late(vm: &mut Vm) {
    let qm = framed_fn(vm, "", "<anonymous>", 1, queue_microtask);
    // the reference defines queueMicrotask late (after the node globals): move it to the end
    vm.global.borrow_mut().props.remove(&key("queueMicrotask"));
    set_global(vm, "queueMicrotask", Value::Obj(qm));
    set_global(vm, "onerror", Value::Null);
    set_global(vm, "onunhandledrejection", Value::Null);
    let re = plain_fn(vm, "reportError", 1, report_error);
    set_global(vm, "reportError", Value::Obj(re));
}

/// `(cb) => { if (typeof cb !== 'function') throw new TypeError(...); Promise.resolve().then(cb); }`
pub fn queue_microtask(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(0);
    if !cb.is_callable() {
        return vm.throw_type("queueMicrotask expects a function");
    }
    let p = crate::builtins::promise::promise_resolve_intrinsic(vm, Value::Undefined)?;
    crate::builtins::promise::promise_then(vm, &p, cb, Value::Undefined)?;
    Ok(Value::Undefined)
}

fn report_error(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.args.is_empty() {
        return vm.throw_type("reportError requires at least 1 argument");
    }
    report_error_value(vm, &a.arg(0));
    Ok(Value::Undefined)
}

/// Offer `e` to `globalThis.onerror(message, "", 0, 0, e)`; true when it returned `true`.
pub fn fire_onerror(vm: &mut Vm, e: &Value) -> bool {
    let h = match global_get(vm, "onerror") {
        Ok(h) => h,
        Err(_) => return false,
    };
    if !h.is_callable() {
        return false;
    }
    let msg = format!("Uncaught {}", describe_reported(vm, e));
    let g = Value::Obj(vm.global.clone());
    match vm.call(&h, g, &[Value::str(&msg), Value::str(""), Value::Num(0.0), Value::Num(0.0), e.clone()]) {
        Ok(Value::Bool(true)) => true,
        _ => false,
    }
}

/// `if (!fire(e)) report(e)`
pub fn report_error_value(vm: &mut Vm, e: &Value) {
    if fire_onerror(vm, e) {
        return;
    }
    let s = describe_reported(vm, e);
    crate::runtime::write_stderr(&format!("Uncaught {}\n", s));
}

/// Offer an unhandled rejection to `globalThis.onunhandledrejection`; true when prevented.
pub fn fire_unhandled_rejection(vm: &mut Vm, promise: &Value, reason: &Value) -> bool {
    let h = match global_get(vm, "onunhandledrejection") {
        Ok(h) => h,
        Err(_) => return false,
    };
    if !h.is_callable() {
        return false;
    }
    let flag = vm.new_object();
    flag.set_prop(key("prevented"), Value::Bool(false), WEC);
    let ev = plain(vm, vec![
        ("type", Value::str("unhandledrejection")),
        ("promise", promise.clone()),
        ("reason", reason.clone()),
        ("cancelable", Value::Bool(true)),
    ]);
    let pd = vm.native_closure("preventDefault", 0, rejection_prevent_default, vec![Value::Obj(flag.clone())]);
    ev.set_prop(key("preventDefault"), Value::Obj(pd), WEC);
    let g = vm.native_closure("get defaultPrevented", 0, rejection_default_prevented, vec![Value::Obj(flag.clone())]);
    ev.set_accessor(key("defaultPrevented"), Some(g), None, ENUMERABLE | CONFIGURABLE);
    let gv = Value::Obj(vm.global.clone());
    let _ = vm.call(&h, gv, &[Value::Obj(ev)]);
    matches!(flag.get_own_str("prevented"), Some(Value::Bool(true)))
}

fn rejection_prevent_default(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(f) = a.slot(0) {
        f.set_prop(key("prevented"), Value::Bool(true), WEC);
    }
    Ok(Value::Undefined)
}

fn rejection_default_prevented(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(f) = a.slot(0) {
        return Ok(f.get_own_str("prevented").unwrap_or(Value::Bool(false)));
    }
    Ok(Value::Bool(false))
}
