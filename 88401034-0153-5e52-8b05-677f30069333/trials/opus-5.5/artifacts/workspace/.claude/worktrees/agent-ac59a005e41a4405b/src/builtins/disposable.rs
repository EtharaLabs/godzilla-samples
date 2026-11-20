// DisposableStack and AsyncDisposableStack, and the disposal of `using` declarations.

use crate::builtins::promise::{perform_then_internal, promise_resolve_intrinsic};
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;

pub fn setup(vm: &mut Vm) {
    let p = vm.intr.disposable_stack_proto.clone();
    let c = vm.native_ctor("DisposableStack", 0, ds_ctor, &p);
    vm.def_method(&p, "use", 1, ds_use);
    vm.def_method(&p, "adopt", 2, ds_adopt);
    vm.def_method(&p, "defer", 1, ds_defer);
    vm.def_method(&p, "move", 0, ds_move);
    let dispose = vm.def_method(&p, "dispose", 0, ds_dispose);
    vm.def_getter(&p, "disposed", ds_disposed);
    p.set_prop(PropKey::Sym(vm.intr.sym_dispose.clone()), Value::Obj(dispose), WC);
    vm.set_tag(&p, "DisposableStack");
    vm.def_global("DisposableStack", Value::Obj(c));
    let ap = vm.intr.async_disposable_stack_proto.clone();
    let ac = vm.native_ctor("AsyncDisposableStack", 0, ds_ctor_async, &ap);
    vm.def_method(&ap, "use", 1, ads_use);
    vm.def_method(&ap, "adopt", 2, ads_adopt);
    vm.def_method(&ap, "defer", 1, ads_defer);
    vm.def_method(&ap, "move", 0, ads_move);
    let ad = vm.def_method(&ap, "disposeAsync", 0, ds_dispose_async);
    vm.def_getter(&ap, "disposed", ads_disposed);
    ap.set_prop(PropKey::Sym(vm.intr.sym_async_dispose.clone()), Value::Obj(ad), WC);
    vm.set_tag(&ap, "AsyncDisposableStack");
    vm.def_global("AsyncDisposableStack", Value::Obj(ac));
}

pub struct DisposableState {
    pub disposed: bool,
    pub items: Vec<(Value, Value, u8)>, // (value, method, kind: 0 use, 1 adopt, 2 defer)
    pub is_async: bool,
}

fn make(vm: &mut Vm, a: &Args, is_async: bool) -> JsResult<Value> {
    if a.new_target.is_none() {
        return vm.throw_type(format!("Constructor {} requires 'new'", if is_async { "AsyncDisposableStack" } else { "DisposableStack" }));
    }
    let fallback = if is_async { vm.intr.async_disposable_stack_proto.clone() } else { vm.intr.disposable_stack_proto.clone() };
    let proto = vm.proto_from_nt(&a.new_target, &fallback)?;
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(RefCell::new(DisposableState { disposed: false, items: Vec::new(), is_async }))))))
}

fn ds_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    make(vm, a, false)
}
fn ds_ctor_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    make(vm, a, true)
}

/// Run `f` on the state of a DisposableStack (`is_async` false) or AsyncDisposableStack receiver.
fn with_state<R>(vm: &mut Vm, v: &Value, is_async: bool, f: impl FnOnce(&mut DisposableState) -> R) -> JsResult<R> {
    if let Value::Obj(o) = v {
        if let ObjKind::Host(h) = &o.borrow().kind {
            if let Some(st) = h.downcast_ref::<RefCell<DisposableState>>() {
                let mut s = st.borrow_mut();
                if s.is_async == is_async {
                    return Ok(f(&mut s));
                }
            }
        }
    }
    vm.throw_type(format!("receiver is not a {}", if is_async { "AsyncDisposableStack" } else { "DisposableStack" }))
}

fn check_live(vm: &mut Vm, v: &Value, is_async: bool) -> JsResult<()> {
    if with_state(vm, v, is_async, |s| s.disposed)? {
        return vm.throw_error("ReferenceError", if is_async { "AsyncDisposableStack already disposed" } else { "DisposableStack already disposed" });
    }
    Ok(())
}

/// The disposal method of a value for `using` (`is_async`: `await using`), None for
/// null/undefined; TypeError if it has none.
pub fn dispose_method(vm: &mut Vm, v: &Value, is_async: bool) -> JsResult<Option<Value>> {
    dispose_method_msg(vm, v, is_async, "value is not disposable")
}

fn dispose_method_msg(vm: &mut Vm, v: &Value, is_async: bool, msg: &str) -> JsResult<Option<Value>> {
    if v.is_nullish() {
        return Ok(None);
    }
    if !v.is_object() {
        return vm.throw_type(msg.to_string()).map(|_: Value| None);
    }
    let mut m = Value::Undefined;
    if is_async {
        m = vm.get_prop_of(v, &PropKey::Sym(vm.intr.sym_async_dispose.clone()))?;
    }
    if m.is_nullish() {
        m = vm.get_prop_of(v, &PropKey::Sym(vm.intr.sym_dispose.clone()))?;
    }
    if !m.is_callable() {
        return vm.throw_type(msg.to_string()).map(|_: Value| None);
    }
    Ok(Some(m))
}

fn use_impl(vm: &mut Vm, a: &Args, is_async: bool) -> JsResult<Value> {
    check_live(vm, &a.this, is_async)?;
    let v = a.arg(0);
    let msg = if is_async { "value is not async-disposable" } else { "value is not disposable" };
    let m = match dispose_method_msg(vm, &v, is_async, msg)? {
        Some(m) => m,
        None => return Ok(v),
    };
    let vv = v.clone();
    with_state(vm, &a.this, is_async, |s| s.items.push((vv, m, 0)))?;
    Ok(v)
}

fn adopt_impl(vm: &mut Vm, a: &Args, is_async: bool) -> JsResult<Value> {
    check_live(vm, &a.this, is_async)?;
    let f = a.arg(1);
    if !f.is_callable() {
        return vm.throw_type("onDispose is not callable");
    }
    let v = a.arg(0);
    let vv = v.clone();
    with_state(vm, &a.this, is_async, |s| s.items.push((vv, f, 1)))?;
    Ok(v)
}

fn defer_impl(vm: &mut Vm, a: &Args, is_async: bool) -> JsResult<Value> {
    check_live(vm, &a.this, is_async)?;
    let f = a.arg(0);
    if !f.is_callable() {
        return vm.throw_type("onDispose is not callable");
    }
    with_state(vm, &a.this, is_async, |s| s.items.push((Value::Undefined, f, 2)))?;
    Ok(Value::Undefined)
}

fn move_impl(vm: &mut Vm, a: &Args, is_async: bool) -> JsResult<Value> {
    check_live(vm, &a.this, is_async)?;
    let items = with_state(vm, &a.this, is_async, |s| {
        s.disposed = true;
        std::mem::take(&mut s.items)
    })?;
    let proto = if is_async { vm.intr.async_disposable_stack_proto.clone() } else { vm.intr.disposable_stack_proto.clone() };
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(RefCell::new(DisposableState { disposed: false, items, is_async }))))))
}

fn ds_use(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    use_impl(vm, a, false)
}
fn ads_use(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    use_impl(vm, a, true)
}
fn ds_adopt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    adopt_impl(vm, a, false)
}
fn ads_adopt(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    adopt_impl(vm, a, true)
}
fn ds_defer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    defer_impl(vm, a, false)
}
fn ads_defer(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    defer_impl(vm, a, true)
}
fn ds_move(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    move_impl(vm, a, false)
}
fn ads_move(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    move_impl(vm, a, true)
}

fn ds_disposed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(with_state(vm, &a.this, false, |s| s.disposed)?))
}
fn ads_disposed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(with_state(vm, &a.this, true, |s| s.disposed)?))
}

/// A SuppressedError for an error thrown while disposing after an earlier error.
pub fn make_suppressed(vm: &mut Vm, error: Value, suppressed: Value) -> Value {
    let o = Obj::with_class(Some(vm.intr.suppressed_error_proto.clone()), ObjKind::Error, "Error");
    vm.attach_stack(&o, "SuppressedError", "");
    o.set_prop(PropKey::from_str("error"), error, WC);
    o.set_prop(PropKey::from_str("suppressed"), suppressed, WC);
    Value::Obj(o)
}

fn call_disposer(vm: &mut Vm, v: Value, m: &Value, kind: u8) -> JsResult<Value> {
    match kind {
        0 => vm.call(m, v, &[]),
        1 => vm.call(m, Value::Undefined, &[v]),
        _ => vm.call(m, Value::Undefined, &[]),
    }
}

/// Dispose resources synchronously (in reverse order); returns the resulting error, if any
/// (`initial`: an error that ended the scope).
pub fn dispose_sync(vm: &mut Vm, items: Vec<(Value, Value, u8)>, initial: Option<Value>) -> Option<Value> {
    let mut err = initial;
    for (v, m, kind) in items.into_iter().rev() {
        if let Err(e) = call_disposer(vm, v, &m, kind) {
            err = Some(match err {
                None => e,
                Some(prev) => make_suppressed(vm, e, prev),
            });
        }
    }
    err
}

pub fn run_disposals(vm: &mut Vm, items: Vec<(Value, Value, u8)>) -> JsResult<()> {
    match dispose_sync(vm, items, None) {
        Some(e) => Err(e),
        None => Ok(()),
    }
}

fn ds_dispose(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let already = with_state(vm, &a.this, false, |s| s.disposed)?;
    if already {
        return Ok(Value::Undefined);
    }
    let items = with_state(vm, &a.this, false, |s| {
        s.disposed = true;
        std::mem::take(&mut s.items)
    })?;
    run_disposals(vm, items)?;
    Ok(Value::Undefined)
}

fn ds_dispose_async(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let items = match with_state(vm, &a.this, true, |s| {
        if s.disposed {
            None
        } else {
            s.disposed = true;
            Some(std::mem::take(&mut s.items))
        }
    }) {
        Ok(i) => i,
        Err(e) => {
            let cap = vm.new_promise_capability_intrinsic();
            vm.call(&cap.reject, Value::Undefined, &[e])?;
            return Ok(cap.promise);
        }
    };
    let items = items.unwrap_or_default().into_iter().map(|(v, m, k)| (v, m, k, true)).collect();
    Ok(dispose_async(vm, items, None))
}

// ---------------- asynchronous disposal ----------------

struct AsyncDisposal {
    /// remaining (value, method, call kind, await the result), disposed from the end
    items: RefCell<Vec<(Value, Value, u8, bool)>>,
    err: RefCell<Option<Value>>,
    cap: Capability,
}

/// Dispose resources in reverse order, awaiting asynchronous disposers; returns a promise that
/// rejects with the resulting error (`initial`: an error that ended the scope).
pub fn dispose_async(vm: &mut Vm, items: Vec<(Value, Value, u8, bool)>, initial: Option<Value>) -> Value {
    let cap = vm.new_promise_capability_intrinsic();
    let st = Value::Obj(Obj::new(None, ObjKind::Host(Box::new(AsyncDisposal { items: RefCell::new(items), err: RefCell::new(initial), cap: cap.clone() }))));
    ad_step(vm, &st);
    cap.promise
}

fn ad_with<R>(st: &Value, f: impl FnOnce(&AsyncDisposal) -> R) -> R {
    let o = st.as_obj().unwrap();
    let b = o.borrow();
    match &b.kind {
        ObjKind::Host(h) => f(h.downcast_ref::<AsyncDisposal>().unwrap()),
        _ => unreachable!(),
    }
}

fn ad_error(vm: &mut Vm, st: &Value, e: Value) {
    let prev = ad_with(st, |s| s.err.borrow_mut().take());
    let ne = match prev {
        None => e,
        Some(p) => make_suppressed(vm, e, p),
    };
    ad_with(st, |s| *s.err.borrow_mut() = Some(ne));
}

fn ad_step(vm: &mut Vm, st: &Value) {
    loop {
        let next = ad_with(st, |s| s.items.borrow_mut().pop());
        match next {
            None => {
                let (err, cap) = ad_with(st, |s| (s.err.borrow_mut().take(), s.cap.clone()));
                let _ = match err {
                    Some(e) => vm.call(&cap.reject, Value::Undefined, &[e]),
                    None => vm.call(&cap.resolve, Value::Undefined, &[Value::Undefined]),
                };
                return;
            }
            Some((v, m, kind, awaited)) => match call_disposer(vm, v, &m, kind) {
                Err(e) => ad_error(vm, st, e),
                Ok(r) => {
                    if awaited {
                        match promise_resolve_intrinsic(vm, r) {
                            Ok(p) => {
                                perform_then_internal(vm, &p, Handler::Native(ad_fulfilled, st.clone()), Handler::Native(ad_rejected, st.clone()), None);
                                return;
                            }
                            Err(e) => ad_error(vm, st, e),
                        }
                    }
                }
            },
        }
    }
}

fn ad_fulfilled(vm: &mut Vm, _v: Value, st: &Value) -> JsResult<Value> {
    ad_step(vm, st);
    Ok(Value::Undefined)
}

fn ad_rejected(vm: &mut Vm, e: Value, st: &Value) -> JsResult<Value> {
    ad_error(vm, st, e);
    ad_step(vm, st);
    Ok(Value::Undefined)
}
