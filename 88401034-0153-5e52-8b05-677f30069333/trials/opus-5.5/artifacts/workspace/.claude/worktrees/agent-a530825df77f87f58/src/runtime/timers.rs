// setTimeout / setInterval / setImmediate / queueMicrotask

use super::Timer;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let fns: &[(&str, u32, NativeFn)] = &[
        ("setTimeout", 2, set_timeout),
        ("setInterval", 2, set_interval),
        ("clearTimeout", 1, clear_timer),
        ("clearInterval", 1, clear_timer),
        ("setImmediate", 1, set_immediate),
        ("queueMicrotask", 1, queue_microtask),
    ];
    for (n, l, f) in fns {
        let fo = vm.native_fn(n, *l, *f);
        vm.def_global(n, Value::Obj(fo));
    }
}

pub fn add_timer(vm: &mut Vm, cb: Value, delay: f64, args: Vec<Value>, repeat: bool) -> u64 {
    let id = vm.host.next_timer_id;
    vm.host.next_timer_id += 1;
    vm.host.timer_seq += 1;
    let seq = vm.host.timer_seq;
    let d = if delay.is_nan() || delay < 0.0 { 0.0 } else { delay };
    let interval = if repeat { Some(d.max(1.0)) } else { None };
    let due = vm.host.now_ms() + d;
    vm.host.timers.push(Timer { id, due, interval, callback: cb, args, seq });
    id
}

fn timer_common(vm: &mut Vm, a: &Args, name: &str, repeat: bool) -> JsResult<Value> {
    let cb = a.arg(0);
    if !cb.is_callable() {
        return vm.throw_type(format!("{} expects a function", name));
    }
    let delay = if a.arg(1).is_undefined() { 0.0 } else { vm.to_number(&a.arg(1))? };
    let args = if a.args.len() > 2 { a.args[2..].to_vec() } else { Vec::new() };
    let id = add_timer(vm, cb, delay, args, repeat);
    Ok(Value::Num(id as f64))
}

fn set_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    timer_common(vm, a, "setTimeout", false)
}

fn set_interval(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    timer_common(vm, a, "setInterval", true)
}

pub fn clear_timer_id(vm: &mut Vm, v: &Value) {
    let id = match v {
        Value::Num(n) => *n as u64,
        Value::Obj(o) => match o.get_own_str("__timer_id") {
            Some(Value::Num(n)) => n as u64,
            _ => return,
        },
        _ => return,
    };
    vm.host.timers.retain(|t| t.id != id);
}

fn clear_timer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    clear_timer_id(vm, &a.arg(0));
    Ok(Value::Undefined)
}

fn set_immediate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cb = a.arg(0);
    if !cb.is_callable() {
        return vm.throw_type("setImmediate expects a function");
    }
    let args = if a.args.len() > 1 { a.args[1..].to_vec() } else { Vec::new() };
    vm.host.callbacks.push_back((cb, args));
    Ok(Value::Undefined)
}

/// `queueMicrotask(cb)` behaves like `Promise.resolve().then(cb)` (an exception in cb is an
/// unhandled rejection); the global itself is (re)installed by web::setup.
fn queue_microtask(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    crate::runtime::web::event::queue_microtask(vm, a)
}
