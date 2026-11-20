// node:timers/promises — setTimeout / setImmediate / setInterval (async iterator) / scheduler.

use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;
use std::collections::VecDeque;

pub fn create_module(vm: &mut Vm) -> Value {
    let m = vm.new_object();
    let st = plain_fn(vm, "setTimeoutP", 0, tp_set_timeout);
    m.set_prop(key("setTimeout"), Value::Obj(st), WEC);
    let si = plain_fn(vm, "setImmediateP", 1, tp_set_immediate);
    m.set_prop(key("setImmediate"), Value::Obj(si), WEC);
    let iv = interval_function(vm);
    m.set_prop(key("setInterval"), Value::Obj(iv), WEC);
    let sched = vm.new_object();
    let w = vm.native_fn("wait", 2, sched_wait);
    sched.set_prop(key("wait"), Value::Obj(w), WEC);
    let y = vm.native_fn("yield", 0, sched_yield);
    sched.set_prop(key("yield"), Value::Obj(y), WEC);
    m.set_prop(key("scheduler"), Value::Obj(sched), WEC);
    Value::Obj(m)
}

/// abortReason(signal): the signal's reason, or an AbortError (ABORT_ERR) Error.
fn abort_reason(vm: &mut Vm, signal: &Value) -> JsResult<Value> {
    let r = get(vm, signal, "reason")?;
    if !r.is_undefined() {
        return Ok(r);
    }
    let e = vm.make_error("Error", "The operation was aborted");
    set(vm, &e, "name", Value::str("AbortError"))?;
    set(vm, &e, "code", Value::str("ABORT_ERR"))?;
    Ok(e)
}

fn signal_aborted(vm: &mut Vm, signal: &Value) -> JsResult<bool> {
    Ok(signal.truthy() && get(vm, signal, "aborted")?.truthy())
}

/// setTimeoutP(delay = 1, value, options = {})
pub fn set_timeout_promise(vm: &mut Vm, delay: &Value, value: Value, options: &Value) -> JsResult<Value> {
    let delay = if delay.is_undefined() { Value::Num(1.0) } else { delay.clone() };
    let options = if options.is_undefined() { Value::Obj(vm.new_object()) } else { options.clone() };
    let signal = get(vm, &options, "signal")?;
    let cap = vm.new_promise_capability_intrinsic();
    if signal_aborted(vm, &signal)? {
        let r = abort_reason(vm, &signal)?;
        vm.call(&cap.reject, Value::Undefined, &[r])?;
        return Ok(cap.promise);
    }
    let cell = vm.new_object();
    let on_abort = vm.native_closure("onAbort", 0, timeout_on_abort, vec![Value::Obj(cell.clone()), cap.reject.clone(), signal.clone()]);
    let fire = vm.native_closure("", 0, timeout_fire, vec![cap.resolve.clone(), value, signal.clone(), Value::Obj(on_abort.clone())]);
    let ms = vm.to_number(&delay)?;
    let id = crate::runtime::timers::add_timer(vm, Value::Obj(fire), ms, Vec::new(), false);
    cell.set_prop(key("id"), Value::Num(id as f64), WEC);
    if signal.truthy() {
        let opts = Value::Obj(plain(vm, vec![("once", Value::Bool(true))]));
        invoke(vm, &signal, "addEventListener", &[Value::str("abort"), Value::Obj(on_abort), opts])?;
    }
    Ok(cap.promise)
}

fn timeout_fire(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let resolve = a.slot(0);
    let value = a.slot(1);
    let signal = a.slot(2);
    let on_abort = a.slot(3);
    if signal.truthy() {
        invoke(vm, &signal, "removeEventListener", &[Value::str("abort"), on_abort])?;
    }
    vm.call(&resolve, Value::Undefined, &[value])?;
    Ok(Value::Undefined)
}

fn timeout_on_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cell = a.slot(0);
    let reject = a.slot(1);
    let signal = a.slot(2);
    if let Value::Obj(c) = &cell {
        if let Some(id) = c.get_own_str("id") {
            crate::runtime::timers::clear_timer_id(vm, &id);
        }
    }
    let r = abort_reason(vm, &signal)?;
    vm.call(&reject, Value::Undefined, &[r])?;
    Ok(Value::Undefined)
}

fn tp_set_timeout(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    set_timeout_promise(vm, &a.arg(0), a.arg(1), &a.arg(2))
}

/// setImmediateP(value, options = {})
fn set_immediate_promise(vm: &mut Vm, value: Value, options: &Value) -> JsResult<Value> {
    let options = if options.is_undefined() { Value::Obj(vm.new_object()) } else { options.clone() };
    let signal = get(vm, &options, "signal")?;
    let cap = vm.new_promise_capability_intrinsic();
    if signal_aborted(vm, &signal)? {
        let r = abort_reason(vm, &signal)?;
        vm.call(&cap.reject, Value::Undefined, &[r])?;
        return Ok(cap.promise);
    }
    let cell = vm.new_object();
    cell.set_prop(key("cleared"), Value::Bool(false), WEC);
    let on_abort = vm.native_closure("onAbort", 0, immediate_on_abort, vec![Value::Obj(cell.clone()), cap.reject.clone(), signal.clone()]);
    let fire = vm.native_closure("", 0, immediate_fire, vec![Value::Obj(cell), cap.resolve.clone(), value, signal.clone(), Value::Obj(on_abort.clone())]);
    vm.host.callbacks.push_back((Value::Obj(fire), Vec::new()));
    if signal.truthy() {
        let opts = Value::Obj(plain(vm, vec![("once", Value::Bool(true))]));
        invoke(vm, &signal, "addEventListener", &[Value::str("abort"), Value::Obj(on_abort), opts])?;
    }
    Ok(cap.promise)
}

fn immediate_fire(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cell = a.slot(0);
    if let Value::Obj(c) = &cell {
        if matches!(c.get_own_str("cleared"), Some(Value::Bool(true))) {
            return Ok(Value::Undefined);
        }
    }
    let resolve = a.slot(1);
    let value = a.slot(2);
    let signal = a.slot(3);
    let on_abort = a.slot(4);
    if signal.truthy() {
        invoke(vm, &signal, "removeEventListener", &[Value::str("abort"), on_abort])?;
    }
    vm.call(&resolve, Value::Undefined, &[value])?;
    Ok(Value::Undefined)
}

fn immediate_on_abort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cell = a.slot(0);
    let reject = a.slot(1);
    let signal = a.slot(2);
    if let Value::Obj(c) = &cell {
        c.set_prop(key("cleared"), Value::Bool(true), WEC);
    }
    let r = abort_reason(vm, &signal)?;
    vm.call(&reject, Value::Undefined, &[r])?;
    Ok(Value::Undefined)
}

fn tp_set_immediate(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    set_immediate_promise(vm, a.arg(0), &a.arg(1))
}

fn sched_wait(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    set_timeout_promise(vm, &a.arg(0), Value::Undefined, &a.arg(1))
}

fn sched_yield(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    set_immediate_promise(vm, Value::Undefined, &Value::Undefined)
}

// ---------------------------------------------------------------------------------------------
// setInterval: an async generator `async function* setIntervalP(delay = 1, value, options = {})`
// ---------------------------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
enum IState {
    Start,
    Running,
    Yielded,
    Done,
}

struct Request {
    kind: u8, // 0 next, 1 return, 2 throw
    value: Value,
    cap: Capability,
}

struct IntervalGen {
    state: IState,
    delay: Value,
    value: Value,
    options: Value,
    signal: Value,
    queue: VecDeque<Request>,
}

fn interval_function(vm: &mut Vm) -> Obj {
    let shared = match reg_get("%NativeAsyncGeneratorProto%") {
        Some(p) => p,
        None => {
            let p = Obj::new(Some(vm.intr.async_generator_proto.clone()), ObjKind::Ordinary);
            vm.def_method(&p, "next", 1, ig_next);
            vm.def_method(&p, "return", 1, ig_return);
            vm.def_method(&p, "throw", 1, ig_throw);
            reg_set("%NativeAsyncGeneratorProto%", &p);
            p
        }
    };
    let fproto = Obj::new(Some(shared), ObjKind::Ordinary);
    let f = vm.native_closure("setIntervalP", 0, interval_start, vec![Value::Obj(fproto.clone())]);
    f.borrow_mut().proto = Some(vm.intr.async_generator_function_proto.clone());
    f.set_prop(vm.intr.key_prototype.clone(), Value::Obj(fproto), WRITABLE);
    f
}

fn interval_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_some() {
        return vm.throw_type("(intermediate value) is not a constructor");
    }
    let proto = match a.slot(0) {
        Value::Obj(p) => p,
        _ => vm.intr.async_generator_proto.clone(),
    };
    let delay = if a.arg(0).is_undefined() { Value::Num(1.0) } else { a.arg(0) };
    let options = if a.arg(2).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(2) };
    let g = IntervalGen { state: IState::Start, delay, value: a.arg(1), options, signal: Value::Undefined, queue: VecDeque::new() };
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(RefCell::new(g))))))
}

fn with_ig<R>(o: &Value, f: impl FnOnce(&mut IntervalGen) -> R) -> Option<R> {
    if let Value::Obj(ob) = o {
        let b = ob.borrow();
        if let ObjKind::Host(h) = &b.kind {
            if let Some(cell) = h.downcast_ref::<RefCell<IntervalGen>>() {
                let mut g = cell.borrow_mut();
                return Some(f(&mut g));
            }
        }
    }
    None
}

fn ig_enqueue(vm: &mut Vm, a: &Args, kind: u8) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let promise = cap.promise.clone();
    let this = a.this.clone();
    let ok = with_ig(&this, |g| {
        g.queue.push_back(Request { kind, value: a.arg(0), cap: cap.clone() });
    });
    if ok.is_none() {
        let e = vm.make_error("TypeError", "AsyncGenerator method called on incompatible receiver");
        vm.call(&cap.reject, Value::Undefined, &[e])?;
        return Ok(promise);
    }
    let state = with_ig(&this, |g| g.state).unwrap();
    if state != IState::Running {
        ig_resume_next(vm, &this);
    }
    Ok(promise)
}

fn ig_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ig_enqueue(vm, a, 0)
}

fn ig_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ig_enqueue(vm, a, 1)
}

fn ig_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    ig_enqueue(vm, a, 2)
}

fn settle_req(vm: &mut Vm, req: &Request, ok: bool, v: Value) {
    let f = if ok { req.cap.resolve.clone() } else { req.cap.reject.clone() };
    let _ = vm.call(&f, Value::Undefined, &[v]);
}

/// Process queued requests until the generator starts waiting on a timer (or the queue empties).
fn ig_resume_next(vm: &mut Vm, this: &Value) {
    loop {
        let (state, req) = match with_ig(this, |g| {
            let st = g.state;
            (st, g.queue.pop_front())
        }) {
            Some(x) => x,
            None => return,
        };
        let req = match req {
            Some(r) => r,
            None => return,
        };
        match (state, req.kind) {
            (IState::Done, 0) => {
                let r = vm.iter_result(Value::Undefined, true);
                settle_req(vm, &req, true, r);
            }
            (IState::Done, 1) | (IState::Start, 1) => {
                with_ig(this, |g| g.state = IState::Done);
                let r = vm.iter_result(req.value.clone(), true);
                settle_req(vm, &req, true, r);
            }
            (IState::Done, _) | (IState::Start, 2) => {
                with_ig(this, |g| g.state = IState::Done);
                settle_req(vm, &req, false, req.value.clone());
            }
            (IState::Yielded, 1) => {
                with_ig(this, |g| g.state = IState::Done);
                let r = vm.iter_result(req.value.clone(), true);
                settle_req(vm, &req, true, r);
            }
            (IState::Yielded, 2) => {
                with_ig(this, |g| g.state = IState::Done);
                settle_req(vm, &req, false, req.value.clone());
            }
            (IState::Start, _) => {
                // body start: `const signal = options.signal; if (signal && signal.aborted) throw ...`
                let options = with_ig(this, |g| g.options.clone()).unwrap();
                let r: JsResult<Value> = (|| {
                    let signal = get(vm, &options, "signal")?;
                    if signal_aborted(vm, &signal)? {
                        return Err(abort_reason(vm, &signal)?);
                    }
                    Ok(signal)
                })();
                match r {
                    Ok(signal) => {
                        with_ig(this, |g| {
                            g.signal = signal;
                            g.state = IState::Running;
                            g.queue.push_front(req);
                        });
                        ig_wait(vm, this);
                        return;
                    }
                    Err(e) => {
                        with_ig(this, |g| g.state = IState::Done);
                        settle_req(vm, &req, false, e);
                    }
                }
            }
            (IState::Yielded, _) => {
                with_ig(this, |g| {
                    g.state = IState::Running;
                    g.queue.push_front(req);
                });
                ig_wait(vm, this);
                return;
            }
            (IState::Running, _) => {
                with_ig(this, |g| g.queue.push_front(req));
                return;
            }
        }
    }
}

/// `await setTimeoutP(delay, undefined, { signal })`
fn ig_wait(vm: &mut Vm, this: &Value) {
    let (delay, signal) = with_ig(this, |g| (g.delay.clone(), g.signal.clone())).unwrap();
    let opts = Value::Obj(plain(vm, vec![("signal", signal)]));
    match set_timeout_promise(vm, &delay, Value::Undefined, &opts) {
        Ok(p) => {
            if let Value::Obj(po) = &p {
                let ok = vm.native_closure("", 1, ig_timer_done, vec![this.clone()]);
                let err = vm.native_closure("", 1, ig_timer_failed, vec![this.clone()]);
                let _ = crate::builtins::promise::promise_then(vm, po, Value::Obj(ok), Value::Obj(err));
            }
        }
        Err(e) => ig_fail(vm, this, e),
    }
}

fn ig_timer_done(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    let (value, req) = match with_ig(&this, |g| (g.value.clone(), g.queue.pop_front())) {
        Some(x) => x,
        None => return Ok(Value::Undefined),
    };
    with_ig(&this, |g| g.state = IState::Yielded);
    if let Some(req) = req {
        let r = vm.iter_result(value, false);
        settle_req(vm, &req, true, r);
    }
    ig_resume_next(vm, &this);
    Ok(Value::Undefined)
}

fn ig_fail(vm: &mut Vm, this: &Value, e: Value) {
    let req = with_ig(this, |g| {
        g.state = IState::Done;
        g.queue.pop_front()
    })
    .flatten();
    if let Some(req) = req {
        settle_req(vm, &req, false, e);
    }
    ig_resume_next(vm, this);
}

fn ig_timer_failed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.slot(0);
    ig_fail(vm, &this, a.arg(0));
    Ok(Value::Undefined)
}
