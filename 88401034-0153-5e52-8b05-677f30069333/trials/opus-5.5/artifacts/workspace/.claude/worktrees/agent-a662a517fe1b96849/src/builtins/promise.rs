// Promise implementation (jobs, reactions, combinators).

use crate::object::*;
use crate::value::*;
use crate::vm::{Job, JsResult, ResumeMode, Vm};
use std::cell::Cell;

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.promise_proto.clone();
    let ctor = vm.native_ctor("Promise", 1, promise_ctor, &proto);
    vm.intr.promise_ctor = ctor.clone();
    vm.def_method(&ctor, "all", 1, promise_all);
    vm.def_method(&ctor, "allSettled", 1, promise_all_settled);
    vm.def_method(&ctor, "any", 1, promise_any);
    vm.def_method(&ctor, "race", 1, promise_race);
    vm.def_method(&ctor, "reject", 1, promise_reject_fn);
    vm.def_method(&ctor, "resolve", 1, promise_resolve_fn);
    vm.def_method(&ctor, "withResolvers", 0, with_resolvers);
    vm.def_method(&ctor, "try", 1, promise_try);
    vm.def_sym_getter(&ctor, &vm.intr.sym_species.clone(), "[Symbol.species]", |_vm, a| Ok(a.this.clone()));
    vm.def_method(&proto, "then", 2, then);
    vm.def_method(&proto, "catch", 1, catch);
    vm.def_method(&proto, "finally", 1, finally);
    vm.set_tag(&proto, "Promise");
    vm.def_global("Promise", Value::Obj(ctor));
}

pub fn is_promise(v: &Value) -> bool {
    matches!(v, Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Promise(_)))
}

pub fn new_promise_obj(vm: &mut Vm, proto: Obj) -> Obj {
    vm.promise_counter += 1;
    Obj::with_class(
        Some(proto),
        ObjKind::Promise(Box::new(PromiseData {
            state: PromiseState::Pending,
            fulfill_reactions: Vec::new(),
            reject_reactions: Vec::new(),
            is_handled: false,
            id: vm.promise_counter,
        })),
        "Promise",
    )
}

struct ResolvedFlag(Cell<bool>);

pub fn create_resolving_functions(vm: &mut Vm, p: &Obj) -> (Value, Value) {
    let flag = Value::Obj(Obj::new(None, ObjKind::Host(Box::new(ResolvedFlag(Cell::new(false))))));
    let res = vm.native_closure("", 1, resolve_fn, vec![Value::Obj(p.clone()), flag.clone()]);
    let rej = vm.native_closure("", 1, reject_fn, vec![Value::Obj(p.clone()), flag]);
    (Value::Obj(res), Value::Obj(rej))
}

fn check_and_set_flag(flag: &Value) -> bool {
    if let Value::Obj(f) = flag {
        if let ObjKind::Host(h) = &f.borrow().kind {
            if let Some(rf) = h.downcast_ref::<ResolvedFlag>() {
                if rf.0.get() {
                    return true;
                }
                rf.0.set(true);
            }
        }
    }
    false
}

fn resolve_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if check_and_set_flag(&a.slot(1)) {
        return Ok(Value::Undefined);
    }
    let p = a.slot(0).as_obj().unwrap().clone();
    resolve_promise(vm, &p, a.arg(0));
    Ok(Value::Undefined)
}

fn reject_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if check_and_set_flag(&a.slot(1)) {
        return Ok(Value::Undefined);
    }
    let p = a.slot(0).as_obj().unwrap().clone();
    reject_promise(vm, &p, a.arg(0));
    Ok(Value::Undefined)
}

/// The [[Resolve]] steps after the already-resolved check.
pub fn resolve_promise(vm: &mut Vm, p: &Obj, resolution: Value) {
    if let Value::Obj(r) = &resolution {
        if r.ptr_eq(p) {
            let e = vm.make_error("TypeError", "Chaining cycle detected for promise #<Promise>");
            reject_promise(vm, p, e);
            return;
        }
        let then = match vm.get(r, &vm.intr.key_then.clone(), &resolution) {
            Ok(t) => t,
            Err(e) => {
                reject_promise(vm, p, e);
                return;
            }
        };
        if then.is_callable() {
            vm.jobs.push_back(Job::ResolveThenable(p.clone(), resolution, then));
            return;
        }
    }
    fulfill_promise(vm, p, resolution);
}

pub fn fulfill_promise(vm: &mut Vm, p: &Obj, v: Value) {
    let reactions = {
        let mut b = p.borrow_mut();
        match &mut b.kind {
            ObjKind::Promise(pd) => {
                if !matches!(pd.state, PromiseState::Pending) {
                    return;
                }
                pd.state = PromiseState::Fulfilled(v.clone());
                pd.reject_reactions.clear();
                std::mem::take(&mut pd.fulfill_reactions)
            }
            _ => return,
        }
    };
    for r in reactions {
        vm.jobs.push_back(Job::Reaction(r, v.clone()));
    }
}

pub fn reject_promise(vm: &mut Vm, p: &Obj, reason: Value) {
    let (reactions, handled) = {
        let mut b = p.borrow_mut();
        match &mut b.kind {
            ObjKind::Promise(pd) => {
                if !matches!(pd.state, PromiseState::Pending) {
                    return;
                }
                pd.state = PromiseState::Rejected(reason.clone());
                pd.fulfill_reactions.clear();
                (std::mem::take(&mut pd.reject_reactions), pd.is_handled)
            }
            _ => return,
        }
    };
    if !handled {
        vm.unhandled.push(p.clone());
    }
    for r in reactions {
        vm.jobs.push_back(Job::Reaction(r, reason.clone()));
    }
}

pub fn run_reaction(vm: &mut Vm, r: Reaction, arg: Value) {
    let result: JsResult<Value> = match &r.handler {
        Handler::Identity => Ok(arg),
        Handler::Thrower => Err(arg),
        Handler::Callable(f) => vm.call(f, Value::Undefined, &[arg]),
        Handler::Await(co) => {
            let mode = if r.is_reject { ResumeMode::Throw } else { ResumeMode::Next };
            vm.resume_coroutine(co, mode, arg);
            return;
        }
        Handler::Native(f, data) => f(vm, arg, data),
    };
    if let Some(cap) = &r.capability {
        let r2 = match result {
            Ok(v) => vm.call(&cap.resolve, Value::Undefined, &[v]),
            Err(e) => vm.call(&cap.reject, Value::Undefined, &[e]),
        };
        if let Err(e) = r2 {
            vm.report_uncaught(e);
        }
    } else if let Err(e) = result {
        // no capability: errors are reported
        vm.report_uncaught(e);
    }
}

pub fn run_resolve_thenable(vm: &mut Vm, p: Obj, thenable: Value, then: Value) {
    let (res, rej) = create_resolving_functions(vm, &p);
    if let Err(e) = vm.call(&then, thenable, &[res, rej.clone()]) {
        let _ = vm.call(&rej, Value::Undefined, &[e]);
    }
}

pub fn perform_then_internal(vm: &mut Vm, p: &Obj, on_ful: Handler, on_rej: Handler, cap: Option<Capability>) {
    let fr = Reaction { capability: cap.clone(), is_reject: false, handler: on_ful };
    let rr = Reaction { capability: cap, is_reject: true, handler: on_rej };
    let mut b = p.borrow_mut();
    if let ObjKind::Promise(pd) = &mut b.kind {
        match pd.state.clone() {
            PromiseState::Pending => {
                pd.fulfill_reactions.push(fr);
                pd.reject_reactions.push(rr);
            }
            PromiseState::Fulfilled(v) => {
                drop(b);
                vm.jobs.push_back(Job::Reaction(fr, v));
                b = p.borrow_mut();
            }
            PromiseState::Rejected(v) => {
                let was_handled = pd.is_handled;
                drop(b);
                if !was_handled {
                    vm.unhandled.retain(|x| !x.ptr_eq(p));
                }
                vm.jobs.push_back(Job::Reaction(rr, v));
                b = p.borrow_mut();
            }
        }
        if let ObjKind::Promise(pd) = &mut b.kind {
            pd.is_handled = true;
        }
    }
}

fn to_handler(v: &Value, default: Handler) -> Handler {
    if v.is_callable() {
        Handler::Callable(v.clone())
    } else {
        default
    }
}

impl Vm {
    pub fn new_promise_capability_intrinsic(&mut self) -> Capability {
        let p = new_promise_obj(self, self.intr.promise_proto.clone());
        let (res, rej) = create_resolving_functions(self, &p);
        Capability { promise: Value::Obj(p), resolve: res, reject: rej }
    }
}

struct CapSlots {
    resolve: std::cell::RefCell<Value>,
    reject: std::cell::RefCell<Value>,
}

fn capability_executor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let slots = a.slot(0);
    if let Value::Obj(s) = &slots {
        if let ObjKind::Host(h) = &s.borrow().kind {
            if let Some(cs) = h.downcast_ref::<CapSlots>() {
                if !cs.resolve.borrow().is_undefined() || !cs.reject.borrow().is_undefined() {
                    drop(cs);
                    return Err(vm.make_error("TypeError", "Promise executor has already been invoked with non-undefined arguments"));
                }
                *cs.resolve.borrow_mut() = a.arg(0);
                *cs.reject.borrow_mut() = a.arg(1);
            }
        }
    }
    Ok(Value::Undefined)
}

pub fn new_promise_capability(vm: &mut Vm, c: &Value) -> JsResult<Capability> {
    if let Value::Obj(co) = c {
        if co.ptr_eq(&vm.intr.promise_ctor) {
            return Ok(vm.new_promise_capability_intrinsic());
        }
        if !co.is_constructor() {
            return vm.throw_type("Promise capability constructor is not a constructor");
        }
    } else {
        return vm.throw_type("Promise capability constructor is not a constructor");
    }
    let slots = Obj::new(None, ObjKind::Host(Box::new(CapSlots { resolve: std::cell::RefCell::new(Value::Undefined), reject: std::cell::RefCell::new(Value::Undefined) })));
    let exec = vm.native_closure("", 2, capability_executor, vec![Value::Obj(slots.clone())]);
    let p = vm.construct(c, &[Value::Obj(exec)], None)?;
    let (res, rej) = {
        let b = slots.borrow();
        match &b.kind {
            ObjKind::Host(h) => {
                let cs = h.downcast_ref::<CapSlots>().unwrap();
                let r = (cs.resolve.borrow().clone(), cs.reject.borrow().clone());
                r
            }
            _ => unreachable!(),
        }
    };
    if !res.is_callable() || !rej.is_callable() {
        return vm.throw_type("Promise resolve or reject function is not callable");
    }
    Ok(Capability { promise: p, resolve: res, reject: rej })
}

fn promise_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type("Promise constructor cannot be invoked without 'new'");
    }
    let exec = a.arg(0);
    if !exec.is_callable() {
        return vm.throw_type("Promise resolver is not a function");
    }
    let proto = vm.proto_from_nt(&a.new_target, &vm.intr.promise_proto.clone())?;
    let p = new_promise_obj(vm, proto);
    let (res, rej) = create_resolving_functions(vm, &p);
    if let Err(e) = vm.call(&exec, Value::Undefined, &[res, rej.clone()]) {
        vm.call(&rej, Value::Undefined, &[e])?;
    }
    Ok(Value::Obj(p))
}

pub fn promise_resolve(vm: &mut Vm, c: &Value, x: Value) -> JsResult<Value> {
    if is_promise(&x) {
        let xo = x.as_obj().unwrap().clone();
        let ctor = vm.get(&xo, &vm.intr.key_constructor.clone(), &x)?;
        if Value::strict_eq(&ctor, c) {
            return Ok(x);
        }
    }
    let cap = new_promise_capability(vm, c)?;
    vm.call(&cap.resolve, Value::Undefined, &[x])?;
    Ok(cap.promise)
}

/// PromiseResolve(%Promise%, v) returning the promise object
pub fn promise_resolve_intrinsic(vm: &mut Vm, v: Value) -> JsResult<Obj> {
    let c = Value::Obj(vm.intr.promise_ctor.clone());
    let p = promise_resolve(vm, &c, v)?;
    Ok(p.as_obj().unwrap().clone())
}

fn promise_resolve_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Promise.resolve called on non-object");
    }
    promise_resolve(vm, &a.this, a.arg(0))
}

fn promise_reject_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = new_promise_capability(vm, &a.this)?;
    vm.call(&cap.reject, Value::Undefined, &[a.arg(0)])?;
    Ok(cap.promise)
}

fn with_resolvers(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = new_promise_capability(vm, &a.this)?;
    let o = vm.new_object();
    o.set_str("promise", cap.promise, WEC);
    o.set_str("resolve", cap.resolve, WEC);
    o.set_str("reject", cap.reject, WEC);
    Ok(Value::Obj(o))
}

fn promise_try(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if !a.this.is_object() {
        return vm.throw_type("Promise.try called on non-object");
    }
    let cap = new_promise_capability(vm, &a.this)?;
    let rest = if a.args.len() > 1 { &a.args[1..] } else { &[][..] };
    match vm.call(&a.arg(0), Value::Undefined, rest) {
        Ok(v) => vm.call(&cap.resolve, Value::Undefined, &[v])?,
        Err(e) => vm.call(&cap.reject, Value::Undefined, &[e])?,
    };
    Ok(cap.promise)
}

fn species_constructor(vm: &mut Vm, o: &Obj, default: &Value) -> JsResult<Value> {
    let c = vm.get(o, &vm.intr.key_constructor.clone(), &Value::Obj(o.clone()))?;
    if c.is_undefined() {
        return Ok(default.clone());
    }
    let co = match &c {
        Value::Obj(co) => co.clone(),
        _ => return vm.throw_type("object.constructor is not an object"),
    };
    let s = vm.get(&co, &PropKey::Sym(vm.intr.sym_species.clone()), &c)?;
    if s.is_nullish() {
        return Ok(default.clone());
    }
    if matches!(&s, Value::Obj(so) if so.is_constructor()) {
        return Ok(s);
    }
    vm.throw_type("object.constructor[Symbol.species] is not a constructor")
}

pub fn promise_then(vm: &mut Vm, p: &Obj, on_ful: Value, on_rej: Value) -> JsResult<Value> {
    let default = Value::Obj(vm.intr.promise_ctor.clone());
    let c = species_constructor(vm, p, &default)?;
    let cap = new_promise_capability(vm, &c)?;
    let promise = cap.promise.clone();
    perform_then_internal(vm, p, to_handler(&on_ful, Handler::Identity), to_handler(&on_rej, Handler::Thrower), Some(cap));
    Ok(promise)
}

fn then(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::Promise(_)) => o.clone(),
        _ => return vm.throw_type("Promise.prototype.then called on incompatible receiver"),
    };
    promise_then(vm, &p, a.arg(0), a.arg(1))
}

fn catch(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let then = vm.get_prop_of(&a.this, &vm.intr.key_then.clone())?;
    vm.call(&then, a.this.clone(), &[Value::Undefined, a.arg(0)])
}

fn finally(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("Promise.prototype.finally called on non-object"),
    };
    let default = Value::Obj(vm.intr.promise_ctor.clone());
    let c = species_constructor(vm, &p, &default)?;
    let on_finally = a.arg(0);
    let (tf, cf) = if !on_finally.is_callable() {
        (on_finally.clone(), on_finally)
    } else {
        let t = vm.native_closure("", 1, then_finally, vec![on_finally.clone(), c.clone()]);
        let cfn = vm.native_closure("", 1, catch_finally, vec![on_finally, c]);
        (Value::Obj(t), Value::Obj(cfn))
    };
    let then = vm.get(&p, &vm.intr.key_then.clone(), &a.this)?;
    vm.call(&then, a.this.clone(), &[tf, cf])
}

fn then_finally(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let on_finally = a.slot(0);
    let c = a.slot(1);
    let r = vm.call(&on_finally, Value::Undefined, &[])?;
    let p = promise_resolve(vm, &c, r)?;
    let value = a.arg(0);
    let thunk = vm.native_closure("", 0, |_vm, a| Ok(a.slot(0)), vec![value]);
    let then = vm.get_prop_of(&p, &vm.intr.key_then.clone())?;
    vm.call(&then, p, &[Value::Obj(thunk)])
}

fn catch_finally(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let on_finally = a.slot(0);
    let c = a.slot(1);
    let r = vm.call(&on_finally, Value::Undefined, &[])?;
    let p = promise_resolve(vm, &c, r)?;
    let reason = a.arg(0);
    let thrower = vm.native_closure("", 0, |_vm, a| Err(a.slot(0)), vec![reason]);
    let then = vm.get_prop_of(&p, &vm.intr.key_then.clone())?;
    vm.call(&then, p, &[Value::Obj(thrower)])
}

// ---------------- combinators ----------------

/// shared state for Promise.all & friends
struct Combinator {
    values: std::cell::RefCell<Vec<Value>>,
    remaining: Cell<usize>,
}

fn combinator_state(n: usize) -> Value {
    Value::Obj(Obj::new(None, ObjKind::Host(Box::new(Combinator { values: std::cell::RefCell::new(vec![Value::Undefined; n]), remaining: Cell::new(1) }))))
}

fn with_comb<R>(v: &Value, f: impl FnOnce(&Combinator) -> R) -> R {
    let o = v.as_obj().unwrap();
    let b = o.borrow();
    match &b.kind {
        ObjKind::Host(h) => f(h.downcast_ref::<Combinator>().unwrap()),
        _ => unreachable!(),
    }
}

fn get_promise_resolve(vm: &mut Vm, c: &Value) -> JsResult<Value> {
    let co = c.as_obj().unwrap().clone();
    let r = vm.get(&co, &PropKey::from_str("resolve"), c)?;
    if !r.is_callable() {
        return vm.throw_type("Promise resolve is not a function");
    }
    Ok(r)
}

fn combinator(vm: &mut Vm, a: &Args, kind: u8) -> JsResult<Value> {
    let c = a.this.clone();
    let cap = new_promise_capability(vm, &c)?;
    let r = (|| -> JsResult<Value> {
        let resolve = get_promise_resolve(vm, &c)?;
        let (iter, next) = vm.get_iterator(&a.arg(0))?;
        let itv = Value::Obj(iter);
        let state = combinator_state(0);
        let mut index = 0usize;
        loop {
            let v = match vm.iter_step(&itv, &next) {
                Ok(Some(v)) => v,
                Ok(None) => break,
                Err(e) => return Err(e),
            };
            with_comb(&state, |s| s.values.borrow_mut().push(Value::Undefined));
            let next_p = match vm.call(&resolve, c.clone(), &[v]) {
                Ok(p) => p,
                Err(e) => {
                    let _ = vm.iterator_close(&itv);
                    return Err(e);
                }
            };
            with_comb(&state, |s| s.remaining.set(s.remaining.get() + 1));
            let idx = Value::Num(index as f64);
            let called = Value::Obj(Obj::new(None, ObjKind::Host(Box::new(Cell::new(false)))));
            let (onf, onr) = match kind {
                0 => {
                    let f = vm.native_closure("", 1, all_resolve_element, vec![state.clone(), idx, cap.resolve.clone(), called]);
                    (Value::Obj(f), cap.reject.clone())
                }
                1 => {
                    let f = vm.native_closure("", 1, all_settled_element, vec![state.clone(), idx.clone(), cap.resolve.clone(), called.clone(), Value::Bool(true)]);
                    let r = vm.native_closure("", 1, all_settled_element, vec![state.clone(), idx, cap.resolve.clone(), called, Value::Bool(false)]);
                    (Value::Obj(f), Value::Obj(r))
                }
                2 => {
                    let r = vm.native_closure("", 1, any_reject_element, vec![state.clone(), idx, cap.reject.clone(), called]);
                    (cap.resolve.clone(), Value::Obj(r))
                }
                _ => (cap.resolve.clone(), cap.reject.clone()),
            };
            let then = match vm.get_prop_of(&next_p, &vm.intr.key_then.clone()) {
                Ok(t) => t,
                Err(e) => {
                    let _ = vm.iterator_close(&itv);
                    return Err(e);
                }
            };
            if let Err(e) = vm.call(&then, next_p, &[onf, onr]) {
                let _ = vm.iterator_close(&itv);
                return Err(e);
            }
            index += 1;
        }
        if kind == 3 {
            return Ok(cap.promise.clone());
        }
        let remaining = with_comb(&state, |s| {
            s.remaining.set(s.remaining.get() - 1);
            s.remaining.get()
        });
        if remaining == 0 {
            let vals = with_comb(&state, |s| s.values.borrow().clone());
            if kind == 2 {
                let arr = vm.new_array(vals);
                let e = make_aggregate(vm, arr);
                vm.call(&cap.reject, Value::Undefined, &[e])?;
            } else {
                let arr = vm.new_array(vals);
                vm.call(&cap.resolve, Value::Undefined, &[Value::Obj(arr)])?;
            }
        }
        Ok(cap.promise.clone())
    })();
    match r {
        Ok(p) => Ok(p),
        Err(e) => {
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            Ok(cap.promise)
        }
    }
}

fn make_aggregate(vm: &mut Vm, errors: Obj) -> Value {
    let o = Obj::with_class(Some(vm.intr.aggregate_error_proto.clone()), ObjKind::Error, "Error");
    o.set_prop(vm.intr.key_message.clone(), Value::str("All promises were rejected"), WC);
    o.set_prop(PropKey::from_str("errors"), Value::Obj(errors), WC);
    vm.attach_stack(&o, "AggregateError", "All promises were rejected");
    Value::Obj(o)
}

fn take_called(v: &Value) -> bool {
    let o = v.as_obj().unwrap();
    let b = o.borrow();
    if let ObjKind::Host(h) = &b.kind {
        if let Some(c) = h.downcast_ref::<Cell<bool>>() {
            if c.get() {
                return true;
            }
            c.set(true);
        }
    }
    false
}

fn all_resolve_element(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if take_called(&a.slot(3)) {
        return Ok(Value::Undefined);
    }
    let state = a.slot(0);
    let idx = a.slot(1).as_num().unwrap() as usize;
    let remaining = with_comb(&state, |s| {
        s.values.borrow_mut()[idx] = a.arg(0);
        s.remaining.set(s.remaining.get() - 1);
        s.remaining.get()
    });
    if remaining == 0 {
        let vals = with_comb(&state, |s| s.values.borrow().clone());
        let arr = vm.new_array(vals);
        vm.call(&a.slot(2), Value::Undefined, &[Value::Obj(arr)])?;
    }
    Ok(Value::Undefined)
}

fn all_settled_element(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if take_called(&a.slot(3)) {
        return Ok(Value::Undefined);
    }
    let state = a.slot(0);
    let idx = a.slot(1).as_num().unwrap() as usize;
    let fulfilled = a.slot(4).truthy();
    let o = vm.new_object();
    if fulfilled {
        o.set_str("status", Value::str("fulfilled"), WEC);
        o.set_str("value", a.arg(0), WEC);
    } else {
        o.set_str("status", Value::str("rejected"), WEC);
        o.set_str("reason", a.arg(0), WEC);
    }
    let remaining = with_comb(&state, |s| {
        s.values.borrow_mut()[idx] = Value::Obj(o);
        s.remaining.set(s.remaining.get() - 1);
        s.remaining.get()
    });
    if remaining == 0 {
        let vals = with_comb(&state, |s| s.values.borrow().clone());
        let arr = vm.new_array(vals);
        vm.call(&a.slot(2), Value::Undefined, &[Value::Obj(arr)])?;
    }
    Ok(Value::Undefined)
}

fn any_reject_element(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if take_called(&a.slot(3)) {
        return Ok(Value::Undefined);
    }
    let state = a.slot(0);
    let idx = a.slot(1).as_num().unwrap() as usize;
    let remaining = with_comb(&state, |s| {
        s.values.borrow_mut()[idx] = a.arg(0);
        s.remaining.set(s.remaining.get() - 1);
        s.remaining.get()
    });
    if remaining == 0 {
        let vals = with_comb(&state, |s| s.values.borrow().clone());
        let arr = vm.new_array(vals);
        let e = make_aggregate(vm, arr);
        vm.call(&a.slot(2), Value::Undefined, &[e])?;
    }
    Ok(Value::Undefined)
}

fn promise_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    combinator(vm, a, 0)
}
fn promise_all_settled(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    combinator(vm, a, 1)
}
fn promise_any(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    combinator(vm, a, 2)
}
fn promise_race(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    combinator(vm, a, 3)
}

// ---------------- Array.fromAsync ----------------

struct FromAsync {
    iter: Option<(Value, Value)>,
    array_like: Option<(Obj, u64)>,
    index: Cell<u64>,
    arr: Obj,
    mapfn: Value,
    this_arg: Value,
    cap: Capability,
    is_async_iter: bool,
}

fn fa_state(v: &Value) -> std::cell::Ref<'_, ObjectData> {
    v.as_obj().unwrap().borrow()
}

pub fn array_from_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let cap = vm.new_promise_capability_intrinsic();
    let r = (|| -> JsResult<()> {
        let items = a.arg(0);
        let mapfn = a.arg(1);
        if !mapfn.is_undefined() && !mapfn.is_callable() {
            return vm.throw_type("Array.fromAsync: mapFn is not callable");
        }
        if items.is_nullish() {
            return vm.throw_type("Array.fromAsync requires an array-like or iterable");
        }
        let am = vm.get_prop_of(&items, &PropKey::Sym(vm.intr.sym_async_iterator.clone()))?;
        let (iter, array_like, is_async) = if !am.is_nullish() {
            let (io, next) = vm.get_iterator_from_method(&items, &am)?;
            (Some((Value::Obj(io), next)), None, true)
        } else {
            let sm = vm.get_prop_of(&items, &PropKey::Sym(vm.intr.sym_iterator.clone()))?;
            if !sm.is_nullish() {
                let (io, next) = vm.get_iterator_from_method(&items, &sm)?;
                (Some((Value::Obj(io), next)), None, false)
            } else {
                let o = vm.to_object(&items)?;
                let len = vm.length_of(&o)?;
                (None, Some((o, len)), false)
            }
        };
        let c = a.this.clone();
        let arr = if matches!(&c, Value::Obj(co) if co.is_constructor() && !co.ptr_eq(&vm.intr.array_ctor)) {
            vm.construct(&c, &[], None)?.as_obj().cloned().unwrap()
        } else {
            vm.new_array(Vec::new())
        };
        let st = Value::Obj(Obj::new(
            None,
            ObjKind::Host(Box::new(FromAsync { iter, array_like, index: Cell::new(0), arr, mapfn, this_arg: a.arg(2), cap: cap.clone(), is_async_iter: is_async })),
        ));
        fa_step(vm, &st);
        Ok(())
    })();
    if let Err(e) = r {
        vm.call(&cap.reject, Value::Undefined, &[e])?;
    }
    Ok(cap.promise)
}

fn fa_fail(vm: &mut Vm, st: &Value, e: Value, close: bool) {
    let (cap, iter) = {
        let b = fa_state(st);
        let s = match &b.kind {
            ObjKind::Host(h) => h.downcast_ref::<FromAsync>().unwrap(),
            _ => unreachable!(),
        };
        (s.cap.clone(), s.iter.clone())
    };
    if close {
        if let Some((it, _)) = iter {
            let _ = vm.iterator_close(&it);
        }
    }
    let _ = vm.call(&cap.reject, Value::Undefined, &[e]);
}

/// Request the next element and await it.
fn fa_step(vm: &mut Vm, st: &Value) {
    let (iter, array_like, idx, cap, arr) = {
        let b = fa_state(st);
        let s = match &b.kind {
            ObjKind::Host(h) => h.downcast_ref::<FromAsync>().unwrap(),
            _ => unreachable!(),
        };
        (s.iter.clone(), s.array_like.clone(), s.index.get(), s.cap.clone(), s.arr.clone())
    };
    let next_val: JsResult<Value> = if let Some((it, next)) = iter {
        vm.call(&next, it, &[])
    } else if let Some((o, len)) = array_like {
        if idx >= len {
            let _ = crate::builtins::array::set_length(vm, &arr, idx);
            let _ = vm.call(&cap.resolve, Value::Undefined, &[Value::Obj(arr)]);
            return;
        }
        vm.get(&o, &PropKey::from_index(idx as u32), &Value::Obj(o.clone()))
    } else {
        return;
    };
    let v = match next_val {
        Ok(v) => v,
        Err(e) => return fa_fail(vm, st, e, false),
    };
    let p = match promise_resolve_intrinsic(vm, v) {
        Ok(p) => p,
        Err(e) => return fa_fail(vm, st, e, false),
    };
    perform_then_internal(vm, &p, Handler::Native(fa_on_value, st.clone()), Handler::Native(fa_on_error, st.clone()), None);
}

fn fa_on_error(vm: &mut Vm, e: Value, st: &Value) -> JsResult<Value> {
    fa_fail(vm, st, e, true);
    Ok(Value::Undefined)
}

fn fa_on_value(vm: &mut Vm, v: Value, st: &Value) -> JsResult<Value> {
    let (is_iter, is_async, idx, arr, mapfn, this_arg, cap) = {
        let b = fa_state(st);
        let s = match &b.kind {
            ObjKind::Host(h) => h.downcast_ref::<FromAsync>().unwrap(),
            _ => unreachable!(),
        };
        (s.iter.is_some(), s.is_async_iter, s.index.get(), s.arr.clone(), s.mapfn.clone(), s.this_arg.clone(), s.cap.clone())
    };
    let value = if is_iter {
        // v is an iterator result (for async iterators after await; for sync, the result object)
        let ro = match &v {
            Value::Obj(o) => o.clone(),
            _ => {
                let e = vm.make_error("TypeError", "iterator result is not an object");
                fa_fail(vm, st, e, false);
                return Ok(Value::Undefined);
            }
        };
        let done = vm.get(&ro, &vm.intr.key_done.clone(), &v)?.truthy();
        if done {
            let _ = crate::builtins::array::set_length(vm, &arr, idx);
            vm.call(&cap.resolve, Value::Undefined, &[Value::Obj(arr)])?;
            return Ok(Value::Undefined);
        }
        let val = vm.get(&ro, &vm.intr.key_value.clone(), &v)?;
        if !is_async {
            // sync iterator values are awaited
            let p = promise_resolve_intrinsic(vm, val)?;
            perform_then_internal(vm, &p, Handler::Native(fa_store, st.clone()), Handler::Native(fa_on_error, st.clone()), None);
            return Ok(Value::Undefined);
        }
        val
    } else {
        v
    };
    fa_store(vm, value, st)?;
    let _ = mapfn;
    let _ = this_arg;
    Ok(Value::Undefined)
}

fn fa_store(vm: &mut Vm, value: Value, st: &Value) -> JsResult<Value> {
    let (idx, arr, mapfn, this_arg) = {
        let b = fa_state(st);
        let s = match &b.kind {
            ObjKind::Host(h) => h.downcast_ref::<FromAsync>().unwrap(),
            _ => unreachable!(),
        };
        (s.index.get(), s.arr.clone(), s.mapfn.clone(), s.this_arg.clone())
    };
    if !mapfn.is_undefined() {
        let mapped = match vm.call(&mapfn, this_arg, &[value, Value::Num(idx as f64)]) {
            Ok(m) => m,
            Err(e) => {
                fa_fail(vm, st, e, true);
                return Ok(Value::Undefined);
            }
        };
        let p = promise_resolve_intrinsic(vm, mapped)?;
        perform_then_internal(vm, &p, Handler::Native(fa_store_final, st.clone()), Handler::Native(fa_on_error, st.clone()), None);
        return Ok(Value::Undefined);
    }
    if let Err(e) = vm.create_data_property_or_throw(&arr, PropKey::from_index(idx as u32), value) {
        fa_fail(vm, st, e, true);
        return Ok(Value::Undefined);
    }
    fa_advance(vm, st);
    Ok(Value::Undefined)
}

fn fa_store_final(vm: &mut Vm, value: Value, st: &Value) -> JsResult<Value> {
    let (idx, arr) = {
        let b = fa_state(st);
        let s = match &b.kind {
            ObjKind::Host(h) => h.downcast_ref::<FromAsync>().unwrap(),
            _ => unreachable!(),
        };
        (s.index.get(), s.arr.clone())
    };
    if let Err(e) = vm.create_data_property_or_throw(&arr, PropKey::from_index(idx as u32), value) {
        fa_fail(vm, st, e, true);
        return Ok(Value::Undefined);
    }
    fa_advance(vm, st);
    Ok(Value::Undefined)
}

fn fa_advance(vm: &mut Vm, st: &Value) {
    {
        let b = fa_state(st);
        if let ObjKind::Host(h) = &b.kind {
            let s = h.downcast_ref::<FromAsync>().unwrap();
            s.index.set(s.index.get() + 1);
        }
    }
    fa_step(vm, st);
}
